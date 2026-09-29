"""Verify CINDERHAVEN_CANONICAL.md against the live SSOT.

Run via Claude Code with the live DB reachable:
    flyctl proxy 5432:5432 -a cinderhaven-db          # in one shell
    DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/cinderhaven \
        python scripts/verify_canonical.py             # in another

Prints, for each headline canonical figure: the value queried from the live
DB (or read from an owner repo's fresh JSON export) next to the value
currently documented in CINDERHAVEN_CANONICAL.md, and flags mismatches.

This does NOT edit canonical. It produces the report a human (or Claude)
uses to reconcile canonical down to the SSOT.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

# psycopg2 is imported lazily inside from_db() so the artifact-emit step
# (canonical_values.json + supersedes.txt) runs on every invocation even when
# psycopg2 is not installed or no live DB is reachable.

# The summary table prints a "Δ" column header; force UTF-8 so the run completes
# on Windows consoles (cp1252 default) — matches validate_workbook.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
# projects/ root = two levels up from the platform repo (…/projects/active datasources/cinderhaven-data-platform)
PROJECTS = ROOT.parent.parent

# (label, documented canonical value) — keep in sync with CINDERHAVEN_CANONICAL.md
DOCUMENTED = {
    "SKU count": 50,
    "Product lines": 5,
    "Contracted retailers": 6,
    "Distributors": 3,
    "Lifecycle retailer (¢/$)": 87.2,
    "Lifecycle combined (¢/$)": 87.3,
    "Deductions backlog cross-channel ($)": 1_346_815,
    "Deductions rows cross-channel": 16_917,
    "Deductions retailer-only ($)": 1_118_682,
    "Deductions retailer rows": 14_947,
    "Chargebacks total": 3_357,
    "Chargebacks retailer": 2_873,
    "Chargebacks distributor": 484,
    "OTIF internal fill": 0.9923,
    "Walmart shipments on time and complete": 0.8445,
    "OTIF total exposure ($)": 57_196,
    "Short-ship total 3yr ($)": 894_174,
    "Channel retail advantage / $1M ($)": 54_000,
    "PDHA product-data cost ($/yr)": 93_000,
    "Trade all-in ($/yr)": 3_600_000,
    "Trade all-in rate": 0.110,
    "Distributor lifecycle (¢/$)": 93.13,
    "Combined wholesale lifecycle (¢/$)": 89.08,
}

# Source the period-explicit values from the machine-readable SSOT so this
# check compares like to like instead of trusting prose. Default period is
# cy2025; all-time counts are period-independent.
CANONICAL_YAML = ROOT / "reference" / "canonical_values.yml"
if not CANONICAL_YAML.exists():
    print(
        f"canonical file not found at {CANONICAL_YAML} — this is a hard "
        f"failure, not a skip. A drift check that silently finds nothing "
        f"passes green while checking nothing; refusing to do that.",
        file=sys.stderr,
    )
    sys.exit(1)
try:
    import yaml
except ImportError:
    print("PyYAML not installed. pip install pyyaml", file=sys.stderr)
    sys.exit(1)
_cv = yaml.safe_load(CANONICAL_YAML.read_text(encoding="utf-8"))
DOCUMENTED["SKU count"] = _cv["universe"]["skus_total"]["all_time"]
DOCUMENTED["Product lines"] = _cv["universe"]["product_lines"]["all_time"]
DOCUMENTED["Contracted retailers"] = _cv["universe"]["retailers"]["all_time"]
DOCUMENTED["Distributors"] = _cv["universe"]["distributors"]["all_time"]
DOCUMENTED["Chargebacks retailer"] = _cv["chargebacks"]["retailer_count"]["all_time"]
DOCUMENTED["Chargebacks distributor"] = _cv["chargebacks"]["distributor_count"]["all_time"]
DOCUMENTED["Chargebacks total"] = (
    _cv["chargebacks"]["retailer_count"]["all_time"]
    + _cv["chargebacks"]["distributor_count"]["all_time"]
)

rows: list[tuple[str, object, object]] = []  # (label, live, documented)


def rec(label, live):
    rows.append((label, live, DOCUMENTED.get(label)))


def q1(cur, sql):
    cur.execute(sql)
    r = cur.fetchone()
    return r[0] if r else None


def from_db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set — skipping DB queries (JSON checks only).\n")
        return
    try:
        import psycopg2  # noqa: F401 — lazy so emit runs without it
    except ImportError:
        print("psycopg2 not installed — skipping DB queries. "
              "pip install psycopg2-binary to enable them.\n", file=sys.stderr)
        return
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute("SET search_path TO public_marts, public_staging, raw, public")

    def trydb(label, sql):
        try:
            rec(label, q1(cur, sql))
        except Exception as e:
            conn.rollback()
            rec(label, f"ERR: {e.__class__.__name__}")

    trydb("SKU count", "SELECT COUNT(DISTINCT sku) FROM raw.product_master")
    trydb("Product lines", "SELECT COUNT(DISTINCT product_line) FROM raw.product_master")
    trydb("Contracted retailers", "SELECT COUNT(*) FROM raw.retailers")
    trydb("Distributors", "SELECT COUNT(*) FROM raw.distributors")

    # Lifecycle: retailer, distributor, and combined wholesale (net / gross).
    g_r = n_r = g_d = n_d = None
    try:
        cur.execute("SELECT SUM(gross_amount), SUM(net_amount) FROM fct_retailer_payments")
        g_r, n_r = cur.fetchone()
        rec("Lifecycle retailer (¢/$)", round(float(n_r) / float(g_r) * 100, 1) if g_r else None)
    except Exception as e:
        conn.rollback(); rec("Lifecycle retailer (¢/$)", f"ERR: {e.__class__.__name__}")
    try:
        cur.execute("SELECT SUM(gross_amount), SUM(net_amount) FROM fct_distributor_payments")
        g_d, n_d = cur.fetchone()
        rec("Distributor lifecycle (¢/$)", round(float(n_d) / float(g_d) * 100, 2) if g_d else None)
    except Exception as e:
        conn.rollback(); rec("Distributor lifecycle (¢/$)", f"ERR: {e.__class__.__name__}")
    if g_r and g_d:
        rec("Combined wholesale lifecycle (¢/$)",
            round((float(n_r) + float(n_d)) / (float(g_r) + float(g_d)) * 100, 2))

    # Deductions retailer-only.
    try:
        cur.execute("SELECT COUNT(*), SUM(deduction_amount) FROM fct_retailer_deductions")
        c, s = cur.fetchone()
        rec("Deductions retailer rows", c)
        rec("Deductions retailer-only ($)", round(float(s)) if s else None)
    except Exception as e:
        conn.rollback(); rec("Deductions retailer rows", f"ERR: {e.__class__.__name__}")

    # Chargebacks — table name uncertain; try a few candidates.
    for label, sql in [
        ("Chargebacks retailer", "SELECT COUNT(*) FROM raw.retailer_chargebacks"),
        ("Chargebacks distributor", "SELECT COUNT(*) FROM raw.distributor_chargebacks"),
    ]:
        trydb(label, sql)

    conn.close()


def from_json():
    """Read derived figures from owner repos' fresh JSON exports if present."""
    def load(rel):
        p = PROJECTS / rel
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    s = load("published/contract-to-cash/frontend/public/json/summary.json")
    if s:
        rec("Lifecycle combined (¢/$)", s.get("combined", {}).get("cents_per_dollar"))

    d = load("published/retailer-deduction-recovery/frontend/public/json/summary.json")
    if d:
        t = d.get("totals", {})
        rec("Deductions backlog cross-channel ($)", round(t.get("deductions_dollar", 0)))
        rec("Deductions rows cross-channel", t.get("deductions_count"))

    o = load("published/otif-blind-spot/frontend/src/data/summary.json")
    if o:
        rec("OTIF internal fill", o.get("internal_fill_rate"))
        rec("Walmart shipments on time and complete", o.get("retailer_otif"))
    oe = load("published/otif-blind-spot/frontend/src/data/exposure.json")
    if oe:
        rec("OTIF total exposure ($)", round(oe.get("total_exposure", 0)))

    ss = load("published/short-ship-cost/web/dist/data/validation.json")
    if ss:
        rec("Short-ship total 3yr ($)", round(ss.get("baseline_totals", {}).get("total", 0)))


def _platform_head() -> str:
    """Short git SHA of the platform repo, for JSON provenance. '' if unavailable."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def emit_artifacts() -> None:
    """Derive the two machine-readable artifacts from the YAML SSOT.

    Runs on EVERY invocation (independent of DB reachability):
      reference/canonical_values.json — the full canon as JSON, with a
        `_generated` provenance header. Repos vendor this via
        scripts/refresh_canonical.py; their test_canonical_regression.* read it.
      reference/supersedes.txt — one retired token per line (from the YAML
        `supersedes:` block). The per-repo drift gate greps against this file.
    """
    generated = date.today().isoformat()
    head = _platform_head()

    payload = {
        "_generated": {
            "source": "reference/canonical_values.yml",
            "generator": "scripts/verify_canonical.py",
            "generated": generated,
            "platform_head": head,
            "verified_against_production": _cv.get("meta", {}).get(
                "verified_against_production"
            ),
        },
        **_cv,
    }
    json_path = ROOT / "reference" / "canonical_values.json"
    json_path.write_text(
        json.dumps(payload, indent=1, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )

    supersedes = _cv.get("supersedes", []) or []
    tokens = [str(e["token"]) for e in supersedes if isinstance(e, dict) and e.get("token")]
    if not tokens:
        print(
            "WARNING: canonical_values.yml has no `supersedes:` tokens — "
            "supersedes.txt would be empty, which disables the drift gate. "
            "Refusing to emit an empty gate file.",
            file=sys.stderr,
        )
    else:
        sup_path = ROOT / "reference" / "supersedes.txt"
        header = (
            "# Retired Cinderhaven figures/strings — generated from "
            "canonical_values.yml `supersedes:` by verify_canonical.py.\n"
            f"# generated {generated} | platform {head or 'unknown'}\n"
            "# The drift gate fails a build on any hit (excluding history/"
            "SUPERSEDES docs and per-repo allowlists). Do not edit by hand.\n"
        )
        sup_path.write_text(header + "\n".join(tokens) + "\n", encoding="utf-8")
        print(f"  emitted {sup_path.name} ({len(tokens)} retired tokens)")
    print(f"  emitted {json_path.name} (canon as JSON, head={head or 'unknown'})")


def main():
    print("=" * 78)
    print("  CANONICAL vs LIVE SSOT")
    print("=" * 78)
    print("\n  Emitting derived artifacts …")
    emit_artifacts()
    print()
    from_db()
    from_json()
    print(f"\n  {'Figure':<42}{'Live':>16}{'Documented':>16}  Δ")
    print("  " + "-" * 76)
    mismatches = 0
    for label, live, doc in rows:
        flag = ""
        if isinstance(live, (int, float)) and isinstance(doc, (int, float)) and doc:
            if abs(live - doc) / abs(doc) > 0.02:
                flag = "  <-- MISMATCH"
                mismatches += 1
        print(f"  {label:<42}{str(live):>16}{str(doc):>16}{flag}")
    if mismatches:
        print(f"\n  {mismatches} MISMATCH(es) — reconcile CINDERHAVEN_CANONICAL.md to the live SSOT.")
        sys.exit(1)
    print("\n  OK — canonical matches the live SSOT (within 2% tolerance).")
    sys.exit(0)


if __name__ == "__main__":
    main()
