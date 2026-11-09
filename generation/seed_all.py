"""Run all seed generators in the correct order.

1. Execute DDL (drop and recreate raw schema)
2. Shared tables (products, retailers, distributors, stores, etc.)
3. Retailer pipeline
4. Distributor pipeline
5. DTC/Shopify pipeline
6. Scan data (depends on stores + distribution_log from shared)
6.5. Void patterns for Void Finder (depends on scan data; adds the
     never-scanned cluster, went-dark scatter, and store addresses)

Usage:
    python generation/seed_all.py

Requires:
    - flyctl proxy running (localhost:5432)
    - POSTGRES_PASSWORD env var set
"""
from __future__ import annotations

import sys
import time
import psycopg2
from pathlib import Path

from seed_config import DATABASE_URL


def execute_ddl(conn):
    """Run raw_schema.sql to drop and recreate the raw schema."""
    ddl_path = Path(__file__).parent.parent / "sql" / "raw_schema.sql"
    ddl = ddl_path.read_text()

    # Also drop dbt schemas so they get rebuilt clean
    preamble = """
    DROP SCHEMA IF EXISTS public_staging CASCADE;
    DROP SCHEMA IF EXISTS public_intermediate CASCADE;
    DROP SCHEMA IF EXISTS public_marts CASCADE;
    """

    cur = conn.cursor()
    cur.execute(preamble)
    cur.execute(ddl)
    conn.commit()
    cur.close()
    print("DDL executed — raw schema recreated, dbt schemas dropped.")


def run_generator(module_name: str):
    """Import and run a seed generator module."""
    import importlib
    mod = importlib.import_module(module_name)
    mod.main()


def verify_counts(conn):
    """Print row counts for all raw tables."""
    cur = conn.cursor()
    cur.execute("""
        SELECT schemaname || '.' || tablename AS table_name
        FROM pg_tables
        WHERE schemaname = 'raw'
        ORDER BY tablename
    """)
    tables = [row[0] for row in cur.fetchall()]

    print("\n" + "=" * 50)
    print("FINAL ROW COUNTS")
    print("=" * 50)
    total = 0
    for table in tables:
        cur.execute(f"SELECT count(*) FROM {table}")
        count = cur.fetchone()[0]
        total += count
        print(f"  {table:45s} {count:>10,}")
    print(f"  {'TOTAL':45s} {total:>10,}")
    cur.close()


def main():
    start = time.time()

    print("=" * 50)
    print("CINDERHAVEN SEED: Full rebuild")
    print("=" * 50)

    print("\nStep 1: Executing DDL...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    execute_ddl(conn)
    conn.close()

    print("\nStep 2: Seeding shared tables...")
    run_generator("seed_shared")

    print("\nStep 3: Seeding retailer pipeline...")
    run_generator("seed_retailer")

    print("\nStep 4: Seeding distributor pipeline...")
    run_generator("seed_distributor")

    print("\nStep 5: Seeding DTC/Shopify pipeline...")
    run_generator("seed_dtc")

    print("\nStep 6: Seeding scan data (this is the big one)...")
    run_generator("seed_scan_data")

    print("\nStep 6.5: Seeding void patterns (Void Finder)...")
    run_generator("seed_void_patterns")

    print("\nStep 7: Verifying...")
    conn = psycopg2.connect(DATABASE_URL)
    verify_counts(conn)
    conn.close()

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s")


if __name__ == "__main__":
    # Ensure scripts/ is on the path for imports
    sys.path.insert(0, str(Path(__file__).parent))
    main()
