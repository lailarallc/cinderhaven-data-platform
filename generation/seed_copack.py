"""Seed the copack schema's five co-packer tables (plan U2).

Ported from production-demand-forecast's db/seed_copack.py: same rows, same
columns. Draws nothing at random. The SKU-keyed rows come from seed_config.py
(the one catalog); the co-packer and its two lines stay here.

seed_all.py's DDL step applies sql/copack_schema.sql, which drops and recreates
only these five tables (that repo's forecast snapshot tables in copack are left
alone); this module inserts their rows and checks them. seed_all.py runs it.
"""
from __future__ import annotations

import psycopg2

from seed_config import (
    COPACK_PRODUCTION_SCHEDULE, COPACK_SKU_INVENTORY, COPACK_SKU_PRODUCTION_CONFIG, DATABASE_URL,
)

CO_PACKERS = [
    ("COPACK-001", "Midwest Production Partners, LLC", "Racine, WI",
     "Single co-packer for all Cinderhaven product lines in v1"),
]

PRODUCTION_LINES = [
    # Line A: Artisan Sauces + top 5 Specialty Condiments (SHARED): the conflict story.
    ("LINE-A", "COPACK-001", "Line A — Wet/Sauce",
     "Artisan Sauces; Specialty Condiments (top 5)",
     "Shared line. Artisan Sauces top 5 SKUs and Condiments top 5 SKUs "
     "compete for the same production window."),
    # Line B: remaining Condiments + Pantry, Dried Goods, Snack Bites (DEDICATED).
    ("LINE-B", "COPACK-001", "Line B — Condiments/Dry",
     "Specialty Condiments (remaining); Pantry Staples",
     "Dedicated line. No shared-line conflicts in v1."),
]

INSERTS = [
    ("copack.co_packers (co_packer_id, name, location, notes)", CO_PACKERS),
    ("copack.production_lines (line_id, co_packer_id, line_name, product_line_affinity, notes)", PRODUCTION_LINES),
    ("copack.sku_production_config (sku, line_id, lead_time_weeks, min_run_cases, notes)",
     COPACK_SKU_PRODUCTION_CONFIG),
    ("copack.production_schedule (run_id, sku, line_id, scheduled_week, quantity_cases, status)",
     COPACK_PRODUCTION_SCHEDULE),
    ("copack.sku_inventory (sku, as_of_date, on_hand_cases, notes)", COPACK_SKU_INVENTORY),
]


def seed(cur) -> None:
    for target, rows in INSERTS:
        n_cols = len(rows[0])
        cur.executemany(f"INSERT INTO {target} VALUES ({', '.join(['%s'] * n_cols)})", rows)
        print(f"  {target.split(' ')[0]}: {len(rows)} rows")


def verify(cur) -> None:
    """The original seeder's checks, against the qualified tables."""
    checks = [
        ("SELECT count(*) FROM copack.sku_production_config", 50),
        ("SELECT count(*) FROM copack.production_schedule", len(COPACK_PRODUCTION_SCHEDULE)),
        ("SELECT count(*) FROM copack.sku_inventory", 50),
        # every catalog SKU has a production config row
        ("SELECT count(*) FROM raw.product_master p LEFT JOIN copack.sku_production_config c "
         "ON c.sku = p.sku WHERE c.sku IS NULL", 0),
        # the hero SKU has exactly one booked run
        ("SELECT count(*) FROM copack.production_schedule WHERE sku = 'CHP-AS-001'", 1),
    ]
    for sql, want in checks:
        cur.execute(sql)
        got = cur.fetchone()[0]
        if got != want:
            raise SystemExit(f"copack check failed: {sql!r} returned {got}, expected {want}")
    # at least one week with two or more Line-A SKUs scheduled (the conflict story)
    cur.execute("SELECT count(*) FROM (SELECT scheduled_week FROM copack.production_schedule "
                "WHERE line_id = 'LINE-A' GROUP BY scheduled_week HAVING count(DISTINCT sku) >= 2) t")
    if cur.fetchone()[0] < 1:
        raise SystemExit("copack check failed: no week with 2+ Line-A SKUs scheduled")


def main() -> None:
    print("Seeding copack...")
    with psycopg2.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        seed(cur)
        verify(cur)
    conn.close()
    print("copack seeded and verified.")


if __name__ == "__main__":
    main()
