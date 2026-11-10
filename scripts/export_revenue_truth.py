"""Canonical revenue export — single source of truth for all Cinderhaven projects.

Queries Postgres for every revenue metric at every standard time window,
broken down by retailer. Output: JSON + CSV that any project can reference
instead of computing its own figures.

Usage:
    1. Start Fly.io proxy:  flyctl proxy 5432 -a cinderhaven-db
    2. Run:  python scripts/export_revenue_truth.py
    3. Output:  output/revenue_truth.json + output/revenue_truth.csv

Requires: psycopg2-binary, python-dotenv
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"

TODAY = date.today()


def _sub_months(d: date, months: int) -> date:
    m = d.month - months
    y = d.year
    while m < 1:
        m += 12
        y -= 1
    return d.replace(year=y, month=m)


def _build_time_windows() -> dict[str, tuple[date, date]]:
    return {
        "full":   (date(2023, 1, 1),  TODAY),
        "t3m":    (_sub_months(TODAY, 3), TODAY),
        "t6m":    (_sub_months(TODAY, 6), TODAY),
        "t12m":   (_sub_months(TODAY, 12), TODAY),
        "cy2024": (date(2024, 1, 1),  date(2024, 12, 31)),
        "fy2025": (date(2024, 4, 1),  date(2025, 3, 31)),
    }


def _load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        env_path = ROOT.parent / ".env"
    load_dotenv(env_path)


def get_conn():
    _load_env()
    return psycopg2.connect(
        host=os.getenv("POSTGRES_PROXY_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PROXY_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "cinderhaven"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


# ---------------------------------------------------------------------------
# Query builders
# ---------------------------------------------------------------------------

def query_scan_revenue(cur, start: date, end: date) -> list[dict]:
    """Retail sell-through from scan_data, by retailer."""
    cur.execute("""
        SELECT
            st.retailer,
            SUM(sd.dollars_sold)::float    AS revenue,
            SUM(sd.units_sold)::float      AS units,
            COUNT(*)::int                  AS row_count,
            MIN(sd.week_ending)::text      AS date_min,
            MAX(sd.week_ending)::text      AS date_max
        FROM public_staging.stg_scan_data sd
        JOIN public_staging.stg_stores st ON st.store_id = sd.store_id
        WHERE sd.week_ending BETWEEN %s AND %s
        GROUP BY st.retailer
        ORDER BY revenue DESC
    """, (start, end))
    return cur.fetchall()


def query_order_revenue(cur, start: date, end: date) -> list[dict]:
    """Invoiced revenue from channel-specific order marts, by partner."""
    cur.execute("""
        SELECT retailer, channel, revenue, units, order_count, line_count, date_min, date_max
        FROM (
            SELECT
                dr.retailer_name            AS retailer,
                'B2B'                       AS channel,
                SUM(fo.total_value)::float  AS revenue,
                SUM(fo.total_units)::float  AS units,
                COUNT(*)::int               AS order_count,
                SUM(fo.line_count)::int     AS line_count,
                MIN(fo.po_date)::text       AS date_min,
                MAX(fo.po_date)::text       AS date_max
            FROM public_marts.fct_retailer_orders fo
            JOIN public_marts.dim_retailers dr ON dr.retailer_id = fo.retailer_id
            WHERE fo.po_date BETWEEN %(start)s AND %(end)s
            GROUP BY dr.retailer_name

            UNION ALL

            SELECT
                dd.distributor_name         AS retailer,
                'B2B'                       AS channel,
                SUM(fo.total_value)::float  AS revenue,
                SUM(fo.total_units)::float  AS units,
                COUNT(*)::int               AS order_count,
                SUM(fo.line_count)::int     AS line_count,
                MIN(fo.po_date)::text       AS date_min,
                MAX(fo.po_date)::text       AS date_max
            FROM public_marts.fct_distributor_orders fo
            JOIN public_marts.dim_distributors dd ON dd.distributor_id = fo.distributor_id
            WHERE fo.po_date BETWEEN %(start)s AND %(end)s
            GROUP BY dd.distributor_name

            UNION ALL

            SELECT
                'DTC'                            AS retailer,
                'DTC'                            AS channel,
                SUM(fo.gross_revenue)::float     AS revenue,
                SUM(fo.total_units)::float       AS units,
                COUNT(*)::int                    AS order_count,
                SUM(fo.line_count)::int          AS line_count,
                MIN(fo.created_at::date)::text   AS date_min,
                MAX(fo.created_at::date)::text   AS date_max
            FROM public_marts.fct_dtc_orders fo
            WHERE fo.created_at::date BETWEEN %(start)s AND %(end)s
        ) combined
        ORDER BY revenue DESC
    """, {"start": start, "end": end})
    return cur.fetchall()


def query_payment_revenue(cur, start: date, end: date) -> list[dict]:
    """Cash received from channel-specific payment marts, by partner."""
    cur.execute("""
        SELECT retailer, gross, net, deductions_in_remittance, remittance_count, date_min, date_max
        FROM (
            SELECT
                dr.retailer_name                 AS retailer,
                SUM(fp.gross_amount)::float      AS gross,
                SUM(fp.net_amount)::float        AS net,
                SUM(fp.total_deductions)::float  AS deductions_in_remittance,
                COUNT(*)::int                    AS remittance_count,
                MIN(fp.received_date)::text      AS date_min,
                MAX(fp.received_date)::text      AS date_max
            FROM public_marts.fct_retailer_payments fp
            JOIN public_marts.dim_retailers dr ON dr.retailer_id = fp.retailer_id
            WHERE fp.received_date BETWEEN %(start)s AND %(end)s
            GROUP BY dr.retailer_name

            UNION ALL

            SELECT
                dd.distributor_name              AS retailer,
                SUM(fp.gross_amount)::float      AS gross,
                SUM(fp.net_amount)::float        AS net,
                SUM(fp.total_deductions)::float  AS deductions_in_remittance,
                COUNT(*)::int                    AS remittance_count,
                MIN(fp.received_date)::text      AS date_min,
                MAX(fp.received_date)::text      AS date_max
            FROM public_marts.fct_distributor_payments fp
            JOIN public_marts.dim_distributors dd ON dd.distributor_id = fp.distributor_id
            WHERE fp.received_date BETWEEN %(start)s AND %(end)s
            GROUP BY dd.distributor_name
        ) combined
        ORDER BY gross DESC
    """, {"start": start, "end": end})
    return cur.fetchall()


def query_deductions(cur, start: date, end: date) -> list[dict]:
    """Deductions from channel-specific deduction marts, by partner and type."""
    cur.execute("""
        SELECT retailer, deduction_type, amount, recovered, net_loss, deduction_count, date_min, date_max
        FROM (
            SELECT
                dr.retailer_name                      AS retailer,
                fd.deduction_type,
                SUM(fd.deduction_amount)::float       AS amount,
                SUM(fd.recovered_amount)::float       AS recovered,
                SUM(fd.net_deduction_amount)::float   AS net_loss,
                COUNT(*)::int                         AS deduction_count,
                MIN(fd.deduction_date)::text          AS date_min,
                MAX(fd.deduction_date)::text          AS date_max
            FROM public_marts.fct_retailer_deductions fd
            JOIN public_marts.dim_retailers dr ON dr.retailer_id = fd.retailer_id
            WHERE fd.deduction_date BETWEEN %(start)s AND %(end)s
            GROUP BY dr.retailer_name, fd.deduction_type

            UNION ALL

            SELECT
                dd.distributor_name                   AS retailer,
                fd.deduction_type,
                SUM(fd.deduction_amount)::float       AS amount,
                SUM(fd.recovered_amount)::float       AS recovered,
                SUM(fd.net_deduction_amount)::float   AS net_loss,
                COUNT(*)::int                         AS deduction_count,
                MIN(fd.deduction_date)::text          AS date_min,
                MAX(fd.deduction_date)::text          AS date_max
            FROM public_marts.fct_distributor_deductions fd
            JOIN public_marts.dim_distributors dd ON dd.distributor_id = fd.distributor_id
            WHERE fd.deduction_date BETWEEN %(start)s AND %(end)s
            GROUP BY dd.distributor_name, fd.deduction_type
        ) combined
        ORDER BY amount DESC
    """, {"start": start, "end": end})
    return cur.fetchall()


def query_deduction_totals(cur, start: date, end: date) -> list[dict]:
    """Deduction totals by partner (no type breakdown)."""
    cur.execute("""
        SELECT retailer, amount, recovered, net_loss, deduction_count
        FROM (
            SELECT
                dr.retailer_name                      AS retailer,
                SUM(fd.deduction_amount)::float       AS amount,
                SUM(fd.recovered_amount)::float       AS recovered,
                SUM(fd.net_deduction_amount)::float   AS net_loss,
                COUNT(*)::int                         AS deduction_count
            FROM public_marts.fct_retailer_deductions fd
            JOIN public_marts.dim_retailers dr ON dr.retailer_id = fd.retailer_id
            WHERE fd.deduction_date BETWEEN %(start)s AND %(end)s
            GROUP BY dr.retailer_name

            UNION ALL

            SELECT
                dd.distributor_name                   AS retailer,
                SUM(fd.deduction_amount)::float       AS amount,
                SUM(fd.recovered_amount)::float       AS recovered,
                SUM(fd.net_deduction_amount)::float   AS net_loss,
                COUNT(*)::int                         AS deduction_count
            FROM public_marts.fct_distributor_deductions fd
            JOIN public_marts.dim_distributors dd ON dd.distributor_id = fd.distributor_id
            WHERE fd.deduction_date BETWEEN %(start)s AND %(end)s
            GROUP BY dd.distributor_name
        ) combined
        ORDER BY amount DESC
    """, {"start": start, "end": end})
    return cur.fetchall()


def query_channel_contribution(cur) -> list[dict]:
    """Cross-channel waterfall from mart_channel_contribution (no date filter — pre-aggregated)."""
    cur.execute("""
        SELECT
            channel                         AS retailer,
            gross_revenue::float,
            total_cogs::float,
            gross_margin::float,
            total_deductions::float,
            total_recovered::float,
            total_chargebacks::float,
            total_trade_spend::float,
            net_revenue::float,
            contribution_margin::float,
            revenue_share::float
        FROM public_marts.mart_channel_contribution
        ORDER BY gross_revenue DESC
    """)
    return cur.fetchall()


def query_shopify_dtc(cur, start: date, end: date) -> list[dict]:
    """DTC revenue from shopify_transactions."""
    cur.execute("""
        SELECT
            SUM(order_amount)::float       AS gross,
            SUM(processing_fee)::float     AS fees,
            SUM(net_amount)::float         AS net,
            COUNT(*)::int                  AS transaction_count,
            MIN(transaction_date)::text    AS date_min,
            MAX(transaction_date)::text    AS date_max
        FROM raw.shopify_transactions
        WHERE transaction_date BETWEEN %s AND %s
    """, (start, end))
    return cur.fetchall()


def query_quarterly(cur) -> list[dict]:
    """Order revenue by quarter and partner."""
    cur.execute("""
        SELECT quarter, retailer, channel, revenue, order_count
        FROM (
            SELECT
                DATE_TRUNC('quarter', fo.po_date)::date::text AS quarter,
                dr.retailer_name                              AS retailer,
                'B2B'                                         AS channel,
                SUM(fo.total_value)::float                    AS revenue,
                COUNT(*)::int                                 AS order_count
            FROM public_marts.fct_retailer_orders fo
            JOIN public_marts.dim_retailers dr ON dr.retailer_id = fo.retailer_id
            WHERE fo.po_date <= %(today)s
            GROUP BY DATE_TRUNC('quarter', fo.po_date), dr.retailer_name

            UNION ALL

            SELECT
                DATE_TRUNC('quarter', fo.po_date)::date::text AS quarter,
                dd.distributor_name                           AS retailer,
                'B2B'                                         AS channel,
                SUM(fo.total_value)::float                    AS revenue,
                COUNT(*)::int                                 AS order_count
            FROM public_marts.fct_distributor_orders fo
            JOIN public_marts.dim_distributors dd ON dd.distributor_id = fo.distributor_id
            WHERE fo.po_date <= %(today)s
            GROUP BY DATE_TRUNC('quarter', fo.po_date), dd.distributor_name

            UNION ALL

            SELECT
                DATE_TRUNC('quarter', fo.created_at)::date::text AS quarter,
                'DTC'                                            AS retailer,
                'DTC'                                            AS channel,
                SUM(fo.gross_revenue)::float                     AS revenue,
                COUNT(*)::int                                    AS order_count
            FROM public_marts.fct_dtc_orders fo
            WHERE fo.created_at <= %(today)s
            GROUP BY DATE_TRUNC('quarter', fo.created_at)
        ) combined
        ORDER BY quarter, revenue DESC
    """, {"today": TODAY})
    return cur.fetchall()


def query_scan_quarterly(cur) -> list[dict]:
    """Scan revenue by quarter and retailer."""
    cur.execute("""
        SELECT
            DATE_TRUNC('quarter', sd.week_ending)::date::text AS quarter,
            st.retailer,
            SUM(sd.dollars_sold)::float                      AS revenue,
            SUM(sd.units_sold)::float                        AS units
        FROM public_staging.stg_scan_data sd
        JOIN public_staging.stg_stores st ON st.store_id = sd.store_id
        WHERE sd.week_ending <= %s
        GROUP BY DATE_TRUNC('quarter', sd.week_ending), st.retailer
        ORDER BY quarter, revenue DESC
    """, (TODAY,))
    return cur.fetchall()


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------

def _sum_rows(rows: list[dict], key: str) -> float:
    return sum(r.get(key) or 0 for r in rows)


def _add_totals(rows: list[dict], revenue_key: str = "revenue") -> list[dict]:
    """Append an ALL row summing numeric fields."""
    if not rows:
        return rows
    total = {"retailer": "ALL"}
    for k in rows[0]:
        if k == "retailer":
            continue
        if isinstance(rows[0].get(k), (int, float)) and rows[0].get(k) is not None:
            total[k] = sum(r.get(k) or 0 for r in rows)
        elif k in ("date_min",):
            total[k] = min((r[k] for r in rows if r.get(k)), default=None)
        elif k in ("date_max",):
            total[k] = max((r[k] for r in rows if r.get(k)), default=None)
        else:
            total[k] = None
    return rows + [total]


# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------

#: Egress path 2 (plan U4): the schemas this export reads, explicitly. It checks
#: its own source against them before connecting, so a query that strays
#: outside fails here instead of exporting.
EXPORT_SCHEMAS = {"raw", "public_staging", "public_marts"}


def export_all():
    from check_export_allowlist import assert_allowlisted
    assert_allowlisted(Path(__file__), EXPORT_SCHEMAS)
    conn = get_conn()
    cur = conn.cursor()

    time_windows = _build_time_windows()

    print(f"Connected. Export date: {TODAY}")
    print(f"Time windows: {list(time_windows.keys())}")

    result = {
        "generated_at": datetime.now().isoformat(),
        "generated_date": str(TODAY),
        "database": "cinderhaven (Fly.io Postgres)",
        "time_windows": {k: {"start": str(v[0]), "end": str(v[1])} for k, v in time_windows.items()},
    }

    csv_rows = []

    # --- Scan revenue (retail sell-through) ---
    print("\n=== Scan Revenue (scan_data.dollars_sold) ===")
    result["scan_revenue"] = {}
    for window_name, (start, end) in time_windows.items():
        rows = query_scan_revenue(cur, start, end)
        rows = _add_totals(rows)
        result["scan_revenue"][window_name] = rows
        for r in rows:
            csv_rows.append({
                "metric": "scan_revenue",
                "time_window": window_name,
                "window_start": str(start),
                "window_end": str(end),
                "retailer": r["retailer"],
                "value": r.get("revenue"),
                "units": r.get("units"),
                "row_count": r.get("row_count"),
                "date_min": r.get("date_min"),
                "date_max": r.get("date_max"),
            })
        total = next((r for r in rows if r["retailer"] == "ALL"), {})
        print(f"  {window_name}: ${total.get('revenue', 0):,.2f}")

    # --- Order revenue (channel-specific order marts) ---
    print("\n=== Order Revenue (fct_retailer/distributor/dtc_orders) ===")
    result["order_revenue"] = {}
    for window_name, (start, end) in time_windows.items():
        rows = query_order_revenue(cur, start, end)
        # Aggregate B2B and DTC separately, plus combined total
        b2b = [r for r in rows if r["channel"] == "B2B"]
        dtc = [r for r in rows if r["channel"] == "DTC"]
        b2b_total = _sum_rows(b2b, "revenue")
        dtc_total = _sum_rows(dtc, "revenue")
        combined = b2b_total + dtc_total
        result["order_revenue"][window_name] = {
            "b2b_total": b2b_total,
            "dtc_total": dtc_total,
            "combined": combined,
            "by_retailer": rows,
        }
        for r in rows:
            csv_rows.append({
                "metric": f"order_revenue_{r['channel'].lower()}",
                "time_window": window_name,
                "window_start": str(start),
                "window_end": str(end),
                "retailer": r["retailer"],
                "value": r.get("revenue"),
                "units": r.get("units"),
                "row_count": r.get("line_count"),
                "date_min": r.get("date_min"),
                "date_max": r.get("date_max"),
            })
        csv_rows.append({
            "metric": "order_revenue_combined",
            "time_window": window_name,
            "window_start": str(start),
            "window_end": str(end),
            "retailer": "ALL",
            "value": combined,
            "units": None,
            "row_count": sum(r.get("line_count") or 0 for r in rows),
            "date_min": None,
            "date_max": None,
        })
        print(f"  {window_name}: B2B ${b2b_total:,.2f}  DTC ${dtc_total:,.2f}  Combined ${combined:,.2f}")

    # --- Payment revenue (channel-specific payment marts) ---
    print("\n=== Payment Revenue (fct_retailer/distributor_payments) ===")
    result["payment_revenue"] = {}
    for window_name, (start, end) in time_windows.items():
        rows = query_payment_revenue(cur, start, end)
        rows = _add_totals(rows, "gross")
        result["payment_revenue"][window_name] = rows
        for r in rows:
            csv_rows.append({
                "metric": "payment_gross",
                "time_window": window_name,
                "window_start": str(start),
                "window_end": str(end),
                "retailer": r["retailer"],
                "value": r.get("gross"),
                "units": None,
                "row_count": r.get("remittance_count"),
                "date_min": r.get("date_min"),
                "date_max": r.get("date_max"),
            })
            csv_rows.append({
                "metric": "payment_net",
                "time_window": window_name,
                "window_start": str(start),
                "window_end": str(end),
                "retailer": r["retailer"],
                "value": r.get("net"),
                "units": None,
                "row_count": r.get("remittance_count"),
                "date_min": r.get("date_min"),
                "date_max": r.get("date_max"),
            })
        total = next((r for r in rows if r["retailer"] == "ALL"), {})
        print(f"  {window_name}: Gross ${total.get('gross', 0):,.2f}  Net ${total.get('net', 0):,.2f}")

    # --- Deductions (channel-specific deduction marts) ---
    print("\n=== Deductions (fct_retailer/distributor_deductions) ===")
    result["deductions"] = {}
    for window_name, (start, end) in time_windows.items():
        detail = query_deductions(cur, start, end)
        totals = query_deduction_totals(cur, start, end)
        totals = _add_totals(totals, "amount")
        result["deductions"][window_name] = {"by_retailer": totals, "by_retailer_type": detail}
        for r in totals:
            csv_rows.append({
                "metric": "deductions",
                "time_window": window_name,
                "window_start": str(start),
                "window_end": str(end),
                "retailer": r["retailer"],
                "value": r.get("amount"),
                "units": None,
                "row_count": r.get("deduction_count"),
                "date_min": None,
                "date_max": None,
            })
        total = next((r for r in totals if r["retailer"] == "ALL"), {})
        print(f"  {window_name}: ${total.get('amount', 0):,.2f} ({total.get('deduction_count', 0)} deductions)")

    # --- DTC / Shopify ---
    print("\n=== DTC / Shopify ===")
    result["dtc_shopify"] = {}
    for window_name, (start, end) in time_windows.items():
        rows = query_shopify_dtc(cur, start, end)
        result["dtc_shopify"][window_name] = rows[0] if rows else {}
        r = rows[0] if rows else {}
        csv_rows.append({
            "metric": "dtc_shopify_gross",
            "time_window": window_name,
            "window_start": str(start),
            "window_end": str(end),
            "retailer": "DTC",
            "value": r.get("gross"),
            "units": None,
            "row_count": r.get("transaction_count"),
            "date_min": r.get("date_min"),
            "date_max": r.get("date_max"),
        })
        print(f"  {window_name}: Gross ${r.get('gross', 0):,.2f}  Net ${r.get('net', 0):,.2f}")

    # --- Channel waterfall (mart — no date filter, pre-aggregated) ---
    print("\n=== Channel Waterfall (mart_channel_contribution) ===")
    waterfall = query_channel_contribution(cur)
    result["channel_waterfall"] = waterfall
    for r in waterfall:
        csv_rows.append({
            "metric": "channel_gross_revenue",
            "time_window": "mart_all_time",
            "window_start": None,
            "window_end": None,
            "retailer": r["retailer"],
            "value": r.get("gross_revenue"),
            "units": None,
            "row_count": None,
            "date_min": None,
            "date_max": None,
        })
        csv_rows.append({
            "metric": "channel_net_contribution",
            "time_window": "mart_all_time",
            "window_start": None,
            "window_end": None,
            "retailer": r["retailer"],
            "value": r.get("contribution_margin"),
            "units": None,
            "row_count": None,
            "date_min": None,
            "date_max": None,
        })
    grand = sum(r.get("gross_revenue") or 0 for r in waterfall)
    net = sum(r.get("contribution_margin") or 0 for r in waterfall)
    print(f"  Gross: ${grand:,.2f}  Net contribution: ${net:,.2f}")

    # --- Quarterly breakdowns ---
    print("\n=== Quarterly Order Revenue ===")
    quarterly_orders = query_quarterly(cur)
    result["quarterly_orders"] = quarterly_orders
    for r in quarterly_orders:
        csv_rows.append({
            "metric": f"quarterly_order_{r['channel'].lower()}",
            "time_window": r["quarter"],
            "window_start": r["quarter"],
            "window_end": None,
            "retailer": r["retailer"],
            "value": r.get("revenue"),
            "units": None,
            "row_count": r.get("order_count"),
            "date_min": None,
            "date_max": None,
        })

    print("\n=== Quarterly Scan Revenue ===")
    quarterly_scan = query_scan_quarterly(cur)
    result["quarterly_scan"] = quarterly_scan
    for r in quarterly_scan:
        csv_rows.append({
            "metric": "quarterly_scan",
            "time_window": r["quarter"],
            "window_start": r["quarter"],
            "window_end": None,
            "retailer": r["retailer"],
            "value": r.get("revenue"),
            "units": r.get("units"),
            "row_count": None,
            "date_min": None,
            "date_max": None,
        })

    cur.close()
    conn.close()

    # --- Write outputs ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUTPUT_DIR / "revenue_truth.json"
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nJSON: {json_path} ({json_path.stat().st_size / 1024:.1f} KB)")

    csv_path = OUTPUT_DIR / "revenue_truth.csv"
    fieldnames = ["metric", "time_window", "window_start", "window_end",
                   "retailer", "value", "units", "row_count", "date_min", "date_max"]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)
    print(f"CSV:  {csv_path} ({len(csv_rows)} rows)")

    # --- Print summary table ---
    print("\n" + "=" * 80)
    print("REVENUE SUMMARY (annualized where applicable)")
    print("=" * 80)
    scan = result["scan_revenue"]
    orders = result["order_revenue"]
    payments = result["payment_revenue"]
    deductions_data = result["deductions"]

    headers = f"{'Window':<10} {'Scan Rev':>14} {'Order Rev':>14} {'Payments':>14} {'Deductions':>14}"
    print(headers)
    print("-" * len(headers))
    for w in time_windows:
        scan_total = next((r for r in scan[w] if r["retailer"] == "ALL"), {})
        order_combined = orders[w]["combined"]
        pay_total = next((r for r in payments[w] if r["retailer"] == "ALL"), {})
        ded_total = next((r for r in deductions_data[w]["by_retailer"] if r["retailer"] == "ALL"), {})
        print(f"{w:<10} ${scan_total.get('revenue', 0):>12,.0f} ${order_combined:>12,.0f} ${pay_total.get('gross', 0):>12,.0f} ${ded_total.get('amount', 0):>12,.0f}")

    return result


if __name__ == "__main__":
    try:
        export_all()
    except psycopg2.OperationalError as e:
        print(f"\nERROR: Cannot connect to Postgres.\n{e}", file=sys.stderr)
        print("\nMake sure flyctl proxy is running:", file=sys.stderr)
        print("  flyctl proxy 5432 -a cinderhaven-db", file=sys.stderr)
        sys.exit(1)
