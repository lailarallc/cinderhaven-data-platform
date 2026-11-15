"""Assert that Cinderhaven Postgres SSOT matches CINDERHAVEN_CANONICAL.md.

Passes on an additive regen (new tables, new rows in non-cited tables).
Fails when a cited figure moves beyond tolerance.

Requires DATABASE_URL env var or flyctl proxy on localhost:5432.
Set PGPORT to override the default port (e.g. PGPORT=5434).
"""
from __future__ import annotations

import os
import re
import sys
from decimal import Decimal
from pathlib import Path

import psycopg2

CANONICAL_PATH = Path(__file__).resolve().parent.parent / "reference" / "CINDERHAVEN_CANONICAL.md"

TOLERANCE_PCT = 0.02  # 2% tolerance on dollar figures
TOLERANCE_RATE_PP = 0.005  # 0.5 percentage points on rates

QUERIES = {
    "chargeback_count_retailer": "SELECT COUNT(*) FROM raw.retailer_chargebacks",
    "chargeback_count_distributor": "SELECT COUNT(*) FROM raw.distributor_chargebacks",
    "trailing_52w_revenue": """
        WITH ranked_weeks AS (
            SELECT DISTINCT week_ending
            FROM raw.scan_data
            ORDER BY week_ending DESC
            LIMIT 52
        )
        SELECT SUM(sd.dollars_sold)
        FROM raw.scan_data sd
        WHERE sd.week_ending >= (SELECT MIN(week_ending) FROM ranked_weeks)
    """,
    "channel_revenue": """
        WITH ranked_weeks AS (
            SELECT DISTINCT week_ending
            FROM raw.scan_data
            ORDER BY week_ending DESC
            LIMIT 52
        )
        SELECT r.name, SUM(sd.dollars_sold) AS rev
        FROM raw.scan_data sd
        JOIN raw.stores s ON sd.store_id = s.store_id
        JOIN raw.retailers r ON s.retailer_id = r.retailer_id
        WHERE sd.week_ending >= (SELECT MIN(week_ending) FROM ranked_weeks)
        GROUP BY r.name
    """,
    "channel_rates": """
        SELECT
            AVG(trade_spend_pct_walmart)      AS rate_walmart,
            AVG(trade_spend_pct_costco)       AS rate_costco,
            AVG(trade_spend_pct_whole_foods)  AS rate_whole_foods,
            AVG(trade_spend_pct_sprouts)      AS rate_sprouts,
            AVG(trade_spend_pct_kroger)       AS rate_kroger,
            AVG(trade_spend_pct_regional)     AS rate_regional
        FROM raw.sku_costs
    """,
    "operational_waste_retailer": """
        SELECT SUM(amount)
        FROM raw.retailer_deductions
        WHERE deduction_type != 'promo_billback'
    """,
    "operational_waste_distributor": """
        SELECT COALESCE(SUM(amount), 0)
        FROM raw.distributor_deductions
        WHERE deduction_type != 'promo_billback'
    """,
}


def to_float(val):
    if val is None:
        return 0.0
    if isinstance(val, Decimal):
        return float(val)
    return float(val)


def parse_canonical():
    if not CANONICAL_PATH.exists():
        raise SystemExit(
            f"canonical file not found at {CANONICAL_PATH} — this is a hard "
            f"failure, not a skip. A drift check that silently finds nothing "
            f"passes green while checking nothing; refusing to do that."
        )
    text = CANONICAL_PATH.read_text(encoding="utf-8")
    expected = {}

    m = re.search(
        r'\| Chargebacks\s*\|\s*([\d,]+)\s*\|\s*([\d,]+) retailer \+ ([\d,]+) distributor',
        text,
    )
    if m:
        expected["chargeback_count_total"] = int(m.group(1).replace(',', ''))
        expected["chargeback_count_retailer"] = int(m.group(2).replace(',', ''))
        expected["chargeback_count_distributor"] = int(m.group(3).replace(',', ''))

    m = re.search(r'\| Scan revenue \(trailing-52w\)\s*\|\s*\$([0-9.]+)M\s*\|', text)
    if m:
        expected["trailing_52w_revenue"] = float(m.group(1)) * 1_000_000

    m = re.search(
        r'\| All-in trade cost \(annualized\)\s*\|\s*\$([0-9.]+)M/yr\s*\|', text
    )
    if m:
        expected["all_in_annual"] = float(m.group(1)) * 1_000_000

    m = re.search(r'\| All-in trade rate\s*\|\s*([0-9.]+)%\s*\|', text)
    if m:
        expected["trade_rate"] = float(m.group(1)) / 100

    m = re.search(r'\| Structural trade \(annual\)\s*\|\s*~?\$([0-9.]+)M/yr\s*\|', text)
    if m:
        expected["structural_annual"] = float(m.group(1)) * 1_000_000

    m = re.search(r'\| Structural trade rate\s*\|\s*([0-9.]+)%\s*\|', text)
    if m:
        expected["structural_rate"] = float(m.group(1)) / 100

    m = re.search(r'\| Operational waste rate\s*\|\s*([0-9.]+)%\s*\|', text)
    if m:
        expected["op_waste_rate"] = float(m.group(1)) / 100

    # OTIF exposure (pipeline-derived, not directly in Postgres)
    m = re.search(
        r'\| OTIF — total annual exposure\s*\|\s*\$?([\d,]+)', text
    )
    if m:
        expected["otif_exposure_total"] = float(m.group(1).replace(',', ''))

    m = re.search(
        r'\| OTIF — annual fines \(measured\)\s*\|\s*\$?([\d,]+)', text
    )
    if m:
        expected["otif_fines_annual"] = float(m.group(1).replace(',', ''))

    m = re.search(
        r'\| OTIF — annual velocity damage \(modeled\)\s*\|\s*\$?([\d,]+)', text
    )
    if m:
        expected["otif_velocity_annual"] = float(m.group(1).replace(',', ''))

    # Short-ship self-consistency (engagement-level, not in Postgres)
    m = re.search(
        r'\| Short-ship — total cost \(3yr\)\s*\|\s*\$?([\d,]+)', text
    )
    if m:
        expected["shortship_total_3yr"] = float(m.group(1).replace(',', ''))

    m = re.search(
        r'\| Short-ship — total cost \(annual\)\s*\|\s*\$?([\d,]+)', text
    )
    if m:
        expected["shortship_annual"] = float(m.group(1).replace(',', ''))

    shortship_dims = {}
    for dim in ("forgone revenue", "compliance fines", "chargebacks", "deductions"):
        m = re.search(
            rf'\| Short-ship — {dim} \(3yr\)\s*\|\s*\$?([\d,]+)', text
        )
        if m:
            shortship_dims[dim] = float(m.group(1).replace(',', ''))
    # All four or none: a sum over the rows that happened to parse checks nothing (plan U19).
    if len(shortship_dims) == 4:
        expected["shortship_dims_sum"] = sum(shortship_dims.values())

    return expected


#: Every row parse_canonical() reads is required (plan U19): a reworded row fails here instead of switching its
#: check off while the script stays green.
REQUIRED = (
    "chargeback_count_total", "chargeback_count_retailer", "chargeback_count_distributor",
    "trailing_52w_revenue", "all_in_annual", "trade_rate",
    "structural_annual", "structural_rate", "op_waste_rate",
    "otif_exposure_total", "otif_fines_annual", "otif_velocity_annual",
    "shortship_total_3yr", "shortship_annual", "shortship_dims_sum",
)


def get_connection():
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        return psycopg2.connect(dsn)
    password = os.environ.get("POSTGRES_PASSWORD", "")
    port = int(os.environ.get("PGPORT", "5432"))
    return psycopg2.connect(
        host="localhost", port=port,
        dbname="cinderhaven", user="postgres", password=password,
    )


def approx(actual, expected, tolerance_pct):
    if expected == 0:
        return actual == 0
    return abs(actual - expected) / abs(expected) <= tolerance_pct


def run_checks():
    expected = parse_canonical()
    missing = [k for k in REQUIRED if k not in expected]
    if missing:
        print(f"FAIL: Could not parse from CINDERHAVEN_CANONICAL.md: {missing}")
        return 1

    results = []

    try:
        conn = get_connection()
    except Exception as e:
        print(f"FAIL: Cannot connect to Postgres: {e}")
        print("Set DATABASE_URL or PGPORT, or run flyctl proxy first.")
        return 1

    cur = conn.cursor()

    # 1. Chargeback counts (exact)
    cb_counts = {}
    for key in ("chargeback_count_retailer", "chargeback_count_distributor"):
        cur.execute(QUERIES[key])
        actual = cur.fetchone()[0]
        cb_counts[key] = actual
        ok = actual == expected[key]
        results.append(("PASS" if ok else "FAIL", key, expected[key], actual))

    total_cb = sum(cb_counts.values())
    ok = total_cb == expected["chargeback_count_total"]
    results.append(("PASS" if ok else "FAIL", "chargeback_count_total",
                    expected["chargeback_count_total"], total_cb))

    # 2. Trailing-52w revenue
    cur.execute(QUERIES["trailing_52w_revenue"])
    revenue = to_float(cur.fetchone()[0])
    exp_rev = expected["trailing_52w_revenue"]
    ok = approx(revenue, exp_rev, TOLERANCE_PCT)
    results.append(("PASS" if ok else "FAIL", "trailing_52w_revenue",
                    f"${exp_rev/1e6:.1f}M", f"${revenue/1e6:.2f}M"))

    # 3. Structural trade (annual: rate × trailing-52w channel revenue)
    cur.execute(QUERIES["channel_revenue"])
    channel_rev = {name: to_float(rev) for name, rev in cur.fetchall()}
    cur.execute(QUERIES["channel_rates"])
    rates_row = cur.fetchone()
    rate_keys = ["rate_walmart", "rate_costco", "rate_whole_foods",
                 "rate_sprouts", "rate_kroger", "rate_regional"]
    rates = {k: to_float(v) for k, v in zip(rate_keys, rates_row)}

    # Scan revenue only exists for the six contracted retailers, so the map
    # carries exactly those six names. An unmapped channel is a guard FAIL,
    # not a silent fall-through: the old regional fallback priced Kroger and
    # Sprouts at 7% when their seeded rates are 10% and 9%.
    rate_map = {
        "Walmart": rates["rate_walmart"],
        "Costco": rates["rate_costco"],
        "Whole Foods": rates["rate_whole_foods"],
        "Sprouts": rates["rate_sprouts"],
        "Kroger": rates["rate_kroger"],
        "Regional Group": rates["rate_regional"],
    }

    structural_annual = 0.0
    unmapped = []
    for channel, rev in channel_rev.items():
        rate = rate_map.get(channel)
        if rate is None:
            unmapped.append(channel)
            continue
        structural_annual += rev * rate
    if unmapped:
        results.append(("FAIL", "rate_map_unmapped_channels",
                        "every scan channel has an explicit rate",
                        ", ".join(sorted(unmapped))))

    # 4. Operational waste (36mo total → annualized)
    cur.execute(QUERIES["operational_waste_retailer"])
    ret_waste = to_float(cur.fetchone()[0])
    cur.execute(QUERIES["operational_waste_distributor"])
    dist_waste = to_float(cur.fetchone()[0])
    op_waste_annual = (ret_waste + dist_waste) / 3

    # All-in annual = structural (already annual) + waste (annualized)
    all_in_annual = structural_annual + op_waste_annual

    exp_all_in = expected["all_in_annual"]
    ok = approx(all_in_annual, exp_all_in, TOLERANCE_PCT)
    results.append(("PASS" if ok else "FAIL", "all_in_annual",
                    f"${exp_all_in/1e6:.1f}M", f"${all_in_annual/1e6:.2f}M"))

    # Trade rate (all-in annual / trailing-52w revenue)
    trade_rate = all_in_annual / revenue if revenue else 0
    exp_rate = expected["trade_rate"]
    ok = abs(trade_rate - exp_rate) <= TOLERANCE_RATE_PP
    results.append(("PASS" if ok else "FAIL", "trade_rate",
                    f"{exp_rate*100:.1f}%", f"{trade_rate*100:.1f}%"))

    # Derived figures for downstream copy
    structural_rate = structural_annual / revenue if revenue else 0
    op_waste_rate = op_waste_annual / revenue if revenue else 0

    exp_struct_annual = expected.get("structural_annual")
    if exp_struct_annual is not None:
        ok = approx(structural_annual, exp_struct_annual, TOLERANCE_PCT)
        results.append(("PASS" if ok else "FAIL", "structural_annual",
                        f"${exp_struct_annual/1e6:.2f}M", f"${structural_annual/1e6:.2f}M"))

    exp_struct_rate = expected.get("structural_rate")
    if exp_struct_rate is not None:
        ok = abs(structural_rate - exp_struct_rate) <= TOLERANCE_RATE_PP
        results.append(("PASS" if ok else "FAIL", "structural_rate",
                        f"{exp_struct_rate*100:.1f}%", f"{structural_rate*100:.1f}%"))

    exp_op_rate = expected.get("op_waste_rate")
    if exp_op_rate is not None:
        ok = abs(op_waste_rate - exp_op_rate) <= TOLERANCE_RATE_PP
        results.append(("PASS" if ok else "FAIL", "op_waste_rate",
                        f"{exp_op_rate*100:.1f}%", f"{op_waste_rate*100:.1f}%"))

    # OTIF exposure self-consistency (pipeline-derived; no direct SQL validation)
    otif_total = expected.get("otif_exposure_total")
    otif_fines = expected.get("otif_fines_annual")
    otif_velocity = expected.get("otif_velocity_annual")
    if otif_total and otif_fines and otif_velocity:
        computed_total = otif_fines + otif_velocity
        ok = approx(computed_total, otif_total, TOLERANCE_PCT)
        results.append(("PASS" if ok else "FAIL", "otif_exposure_consistency",
                        f"${otif_total/1e3:.0f}K", f"${computed_total/1e3:.0f}K"))
    else:
        results.append(("FAIL", "otif_exposure_parse",
                        "3 OTIF rows", "could not parse all rows"))

    # Short-ship self-consistency (engagement-level; no direct SQL validation)
    ss_total = expected.get("shortship_total_3yr")
    ss_annual = expected.get("shortship_annual")
    ss_dims_sum = expected.get("shortship_dims_sum")
    if ss_total and ss_dims_sum:
        ok = approx(ss_dims_sum, ss_total, TOLERANCE_PCT)
        results.append(("PASS" if ok else "FAIL", "shortship_dims_sum_consistency",
                        f"${ss_total/1e6:.2f}M", f"${ss_dims_sum/1e6:.2f}M"))
    if ss_total and ss_annual:
        computed_annual = ss_total / 3
        ok = approx(computed_annual, ss_annual, TOLERANCE_PCT)
        results.append(("PASS" if ok else "FAIL", "shortship_annual_consistency",
                        f"${ss_annual/1e6:.2f}M", f"${computed_annual/1e6:.2f}M"))

    conn.close()

    # Report
    print("\n=== Canonical Freeze Guard ===\n")
    print(f"  Source: {CANONICAL_PATH.name}")
    print()
    any_fail = False
    for status, name, exp_val, actual in results:
        marker = "OK" if status == "PASS" else "XX"
        print(f"  {marker} {name}: expected {exp_val}, got {actual}")
        if status == "FAIL":
            any_fail = True

    if any_fail:
        print("\nFAIL: Canonical figures have drifted. See CINDERHAVEN_CANONICAL.md.")
        return 1
    else:
        print("\nPASS: All canonical figures match Postgres SSOT.")

    if "--emit" in sys.argv:
        print("\n=== Derived figures (for CINDERHAVEN_CANONICAL.md) ===\n")
        print(f"| Structural trade (annual) | ~${structural_annual/1e6:.1f}M/yr "
              f"| Rate × trailing-52w channel revenue |")
        print(f"| Structural trade rate | {structural_rate*100:.1f}% "
              f"| Of trailing-52w scan revenue (${revenue/1e6:.1f}M) |")
        print(f"| Operational waste rate | {op_waste_rate*100:.1f}% "
              f"| Of trailing-52w scan revenue (${revenue/1e6:.1f}M) |")

    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(run_checks())
