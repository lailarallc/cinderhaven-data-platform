"""Seed product_master_history with synthetic point-in-time data quality snapshots.

Generates monthly snapshots for all 50 SKUs from 2024-01-01 through 2027-02-01,
introducing realistic data quality gaps that resolve monotonically over time.

Used by the chargeback-prediction-model to reconstruct data quality state at
shipment time via: WHERE snapshot_date <= ship_date ORDER BY snapshot_date DESC LIMIT 1

Two SKUs have hardcoded profiles for test verifiability:
  CHP-AS-001: gtin14_present = FALSE before 2025-03-01, TRUE after
  CHP-SC-002: case_dims_present = FALSE before 2025-07-01, TRUE after

Usage (from project root or scripts/ directory):
    python generation/seed_product_master_history.py
"""
from __future__ import annotations

import io
import os
import random
import sys
from datetime import date

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from seed_config import DATABASE_URL, PRODUCT_MASTER_HISTORY_SKUS, WINDOW_START

import psycopg2

SEED = 42
SNAPSHOT_END = date(2026, 2, 1)

ALL_SKUS = PRODUCT_MASTER_HISTORY_SKUS  # seed_config, this path's order


def months_range(start: date, end: date):
    """Yield the first of each month from start through end (inclusive)."""
    current = date(start.year, start.month, 1)
    while current <= end:
        yield current
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


def add_months(d: date, n: int) -> date:
    """Return date shifted forward by n months."""
    month = d.month - 1 + n
    year = d.year + month // 12
    month = month % 12 + 1
    return date(year, month, 1)


def build_sku_profiles(rng: random.Random) -> dict[str, dict[str, date | None]]:
    """
    Assign data quality resolution dates for each SKU.
    None means the flag is True (data present) from the start of the window.
    A date means the flag flips from False to True on that date.
    """
    # Hardcoded profiles for test verifiability
    profiles: dict[str, dict[str, date | None]] = {
        "CHP-AS-001": {
            "gtin14": date(2024, 3, 1),   # missing until 2024-03-01
            "upc": None,
            "case_dims": None,
            "case_weight": None,
        },
        "CHP-SC-002": {
            "gtin14": None,
            "upc": None,
            "case_dims": date(2024, 7, 1),  # missing until 2024-07-01
            "case_weight": None,
        },
    }

    for sku in ALL_SKUS:
        if sku in profiles:
            continue

        profile: dict[str, date | None] = {
            "gtin14": None,
            "upc": None,
            "case_dims": None,
            "case_weight": None,
        }

        # 36% chance of GTIN14 issue, resolved in months 3-24 after window start
        if rng.random() < 0.36:
            profile["gtin14"] = add_months(WINDOW_START, rng.randint(3, 24))

        # 30% chance of case_dims issue, resolved in months 2-30
        if rng.random() < 0.30:
            profile["case_dims"] = add_months(WINDOW_START, rng.randint(2, 30))

        # 24% chance of case_weight issue, resolved in months 2-24
        if rng.random() < 0.24:
            profile["case_weight"] = add_months(WINDOW_START, rng.randint(2, 24))

        # 16% chance of UPC issue, resolved in months 1-18
        if rng.random() < 0.16:
            profile["upc"] = add_months(WINDOW_START, rng.randint(1, 18))

        profiles[sku] = profile

    return profiles


def generate_rows(profiles: dict[str, dict[str, date | None]]) -> list[tuple]:
    snapshots = list(months_range(WINDOW_START, SNAPSHOT_END))
    rows = []
    for sku in ALL_SKUS:
        p = profiles[sku]
        for snap in snapshots:
            gtin14 = p["gtin14"] is None or snap >= p["gtin14"]
            upc = p["upc"] is None or snap >= p["upc"]
            case_dims = p["case_dims"] is None or snap >= p["case_dims"]
            case_weight = p["case_weight"] is None or snap >= p["case_weight"]
            score = int(gtin14) + int(upc) + int(case_dims) + int(case_weight)
            rows.append((sku, snap.isoformat(), gtin14, upc, case_dims, case_weight, score))
    return rows


def load_rows(rows: list[tuple]) -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE raw.product_master_history")
            sql = (
                "COPY raw.product_master_history "
                "(sku, snapshot_date, gtin14_present, upc_present, "
                "case_dims_present, case_weight_present, data_quality_score) "
                "FROM STDIN WITH (FORMAT text, NULL '\\N')"
            )
            buf = io.StringIO()
            for row in rows:
                line = "\t".join("\\N" if v is None else str(v) for v in row)
                buf.write(line + "\n")
            buf.seek(0)
            cur.copy_expert(sql, buf)
        conn.commit()
        print(f"Loaded {len(rows):,} rows into raw.product_master_history")
    finally:
        conn.close()


def main() -> None:
    rng = random.Random(SEED)
    profiles = build_sku_profiles(rng)

    # Print summary of which SKUs have issues
    sku_with_issues = [s for s, p in profiles.items() if any(v is not None for v in p.values())]
    print(f"SKUs with historical data quality gaps: {len(sku_with_issues)}/50")
    for sku in sorted(sku_with_issues):
        p = profiles[sku]
        flags = [f for f, d in p.items() if d is not None]
        print(f"  {sku}: {', '.join(flags)}")

    rows = generate_rows(profiles)
    print(f"\nGenerating {len(rows):,} snapshots ({len(ALL_SKUS)} SKUs x {len(rows)//len(ALL_SKUS)} months)")
    load_rows(rows)
    print("Done.")


if __name__ == "__main__":
    main()
