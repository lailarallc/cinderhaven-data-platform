"""Generate the warehouse: the one entry point (plan U2).

1. DDL, every schema this run owns, in one place: drop the three public_*
   dbt schemas; raw (drops with CASCADE); truth (U4); costing; copack's five
   tables (table-scoped: the schema and that repo's snapshot tables stay).
2. The raw generators: shared, retailer, distributor, DTC, scan data, void
   patterns (voidfinder.store_addresses), product master history.
3. copack's rows.
4. dbt staging build: seed_costing reads public_staging's views.
5. seed_costing.
6. The full dbt build, so every run is a complete world, marts included.
7. verify_counts: raw, costing, copack's five, voidfinder; truth as a
   boolean only, never a count.

dbt runs through orchestration/profiles.yml with the connection this run
seeded, taken from DATABASE_URL. A run that seeds one instance and builds
another is the half-world this unit exists to prevent, so dbt connection
values in the environment that name another instance are refused, and the
staging build must show up on this run's own connection.

Usage:
    python generation/seed_all.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psycopg2
from psycopg2.extensions import parse_dsn

from seed_config import DATABASE_URL

ROOT = Path(__file__).resolve().parent.parent
SQL = ROOT / "sql"
DBT_PROJECT = ROOT / "cinderhaven"
DBT_PROFILES = ROOT / "orchestration"  # every value from CINDERHAVEN_PG_*; nothing machine-local

# (schema, table) the run seeds outside raw, for verify_counts
COPACK_TABLES = ("co_packers", "production_lines", "sku_production_config", "production_schedule",
                 "sku_inventory")


class SeedError(RuntimeError):
    pass


def execute_ddl(conn):
    """Drop and recreate every schema the run owns. Schema creation happens here and nowhere else."""
    preamble = """
    DROP SCHEMA IF EXISTS public_staging CASCADE;
    DROP SCHEMA IF EXISTS public_intermediate CASCADE;
    DROP SCHEMA IF EXISTS public_marts CASCADE;
    """
    cur = conn.cursor()
    cur.execute(preamble)
    for name in ("raw_schema.sql", "truth_schema.sql", "costing_schema.sql", "copack_schema.sql"):
        cur.execute((SQL / name).read_text(encoding="utf-8"))
    conn.commit()
    cur.close()
    print("DDL executed: raw, truth and costing recreated; copack's five tables recreated; dbt schemas dropped.")


def report_truth(conn):
    """Report truth as populated or not, never as a count (plan U4, path 7: an
    aggregate of truth is truth, and this log is persisted)."""
    cur = conn.cursor()
    cur.execute("SELECT public.truth_populated()")
    print(f"  truth populated: {'yes' if cur.fetchone()[0] else 'no'}")
    cur.close()


def run_generator(module_name: str):
    """Import and run a seed generator module."""
    import importlib
    mod = importlib.import_module(module_name)
    mod.main()


def dbt_env() -> dict[str, str]:
    """dbt's connection: the instance DATABASE_URL names, and no other."""
    p = parse_dsn(DATABASE_URL)
    want = {
        "CINDERHAVEN_PG_HOST": p.get("host", "localhost"),
        "CINDERHAVEN_PG_PORT": p.get("port", "5432"),
        "CINDERHAVEN_PG_DB": p.get("dbname", ""),
        "CINDERHAVEN_PG_USER": p.get("user", ""),
    }
    clash = [k for k, v in want.items() if os.environ.get(k) not in (None, "", v)]
    if clash:
        raise SeedError(f"dbt's target is not the instance this run seeds ({', '.join(clash)} name another); "
                        "unset them: seed_all.py hands dbt the connection it seeded")
    env = {k: v for k, v in os.environ.items() if k != "DBT_PROFILES_DIR"}
    env.update(want)
    env["CINDERHAVEN_PG_PASSWORD"] = p.get("password", "")
    return env


def run_dbt(*args: str):
    exe = shutil.which("dbt")
    base = [exe] if exe else [sys.executable, "-c", "import sys; from dbt.cli.main import cli; sys.exit(cli())"]
    r = subprocess.run([*base, *args, "--profiles-dir", str(DBT_PROFILES)], cwd=DBT_PROJECT, env=dbt_env())
    if r.returncode != 0:
        raise SeedError(f"dbt {' '.join(args)} failed (exit {r.returncode})")


def assert_staging_built_here(conn):
    """The staging build must be visible on this run's own connection: public_staging
    was dropped in the DDL step, so finding its views proves dbt built this instance."""
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public_staging' AND c.relkind = 'v'")
    if cur.fetchone()[0] == 0:
        raise SeedError("dbt's staging build is not on the instance this run seeded; refusing to continue")
    cur.close()


def verify_counts(conn):
    """Print row counts for raw, costing, copack's five and voidfinder; truth as a boolean only."""
    cur = conn.cursor()
    cur.execute("""
        SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p') AND NOT c.relispartition
          AND (n.nspname IN ('raw', 'costing', 'voidfinder')
               OR (n.nspname = 'copack' AND c.relname = ANY (%s)))
        ORDER BY 1
    """, (list(COPACK_TABLES),))
    tables = [row[0] for row in cur.fetchall()]

    print("\n" + "=" * 50)
    print("FINAL ROW COUNTS")
    print("=" * 50)
    total = 0
    empty = []
    for table in tables:
        cur.execute(f"SELECT count(*) FROM {table}")
        count = cur.fetchone()[0]
        total += count
        if count == 0:
            empty.append(table)
        print(f"  {table:45s} {count:>10,}")
    print(f"  {'TOTAL':45s} {total:>10,}")
    cur.close()
    report_truth(conn)
    if empty:
        raise SeedError(f"empty after a full run: {', '.join(empty)}")


def main():
    start = time.time()

    print("=" * 50)
    print("CINDERHAVEN SEED: Full rebuild")
    print("=" * 50)
    dbt_env()  # refuse a mismatched dbt target before anything is dropped

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

    print("\nStep 7: Seeding product master history...")
    run_generator("seed_product_master_history")

    print("\nStep 8: Seeding copack...")
    run_generator("seed_copack")

    print("\nStep 9: dbt staging build (seed_costing reads it)...")
    run_dbt("run", "--select", "staging")
    conn = psycopg2.connect(DATABASE_URL)
    assert_staging_built_here(conn)
    conn.close()

    print("\nStep 10: Seeding costing...")
    run_generator("seed_costing")

    print("\nStep 11: Full dbt build...")
    run_dbt("build")

    print("\nStep 12: Verifying...")
    conn = psycopg2.connect(DATABASE_URL)
    verify_counts(conn)
    conn.close()

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s")


if __name__ == "__main__":
    # Ensure generation/ is on the path for imports
    sys.path.insert(0, str(Path(__file__).parent))
    main()
