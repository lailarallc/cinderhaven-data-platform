"""Load all tables from cinderhaven-data SQLite into Postgres raw schema.

Usage:
    1. Start Fly.io proxy:  flyctl proxy 5432 -a cinderhaven-db
    2. Run:  python scripts/ingest_sqlite_to_postgres.py
    3. Resume after failure:  python scripts/ingest_sqlite_to_postgres.py --resume

Requires: psycopg2-binary, python-dotenv
"""
import csv
import io
import os
import sqlite3
import sys
import time

import psycopg2
from dotenv import load_dotenv

import prod_guard

SQLITE_PATH = r"C:\Users\mssha\projects\active\cinderhaven-data\data\cinderhaven_product_master.db"

SKIP_TABLES = {"sqlite_sequence"}

# Small chunks to stay within Fly.io shared-cpu-1x memory limits.
# scan_data (1.1M rows) crashes the instance with larger chunks.
CHUNK_ROWS = 25_000


def _load_env():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(project_root, ".env")
    if not os.path.exists(env_path):
        parent_project = os.path.abspath(os.path.join(project_root, "..", "..", ".."))
        env_path = os.path.join(parent_project, ".env")
    load_dotenv(env_path)


def get_pg_connection():
    _load_env()
    host = os.getenv("POSTGRES_PROXY_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PROXY_PORT", "5432"))
    prod_guard.check(host=host, port=port)  # refuses a fly tunnel to production
    return psycopg2.connect(
        host=host,
        port=port,
        dbname=os.getenv("POSTGRES_DB", "cinderhaven"),
        user=os.getenv("POSTGRES_USER", "postgres"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def get_sqlite_tables(sqlite_conn):
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [r[0] for r in cursor.fetchall() if r[0] not in SKIP_TABLES]


def get_columns(sqlite_conn, table):
    cursor = sqlite_conn.cursor()
    cursor.execute(f'PRAGMA table_info("{table}")')
    return [row[1] for row in cursor.fetchall()]


def get_source_count(sqlite_conn, table):
    cur = sqlite_conn.cursor()
    cur.execute(f'SELECT COUNT(*) FROM "{table}"')
    return cur.fetchone()[0]


def get_pg_count(pg_conn, table):
    cur = pg_conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM raw.{table}")
    return cur.fetchone()[0]


def rows_to_tsv_buffer(rows):
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
    for row in rows:
        writer.writerow(["\\N" if v is None else v for v in row])
    buf.seek(0)
    return buf


def load_table(sqlite_conn, table, columns, get_conn):
    """Load a table using COPY, reconnecting between chunks."""
    col_list = ", ".join(columns)

    pg_conn = get_conn()
    pg_cur = pg_conn.cursor()
    pg_cur.execute(f"TRUNCATE TABLE raw.{table}")
    pg_conn.commit()
    pg_conn.close()

    sq_cur = sqlite_conn.cursor()
    sq_cur.execute(f'SELECT {col_list} FROM "{table}"')

    total = 0
    while True:
        rows = sq_cur.fetchmany(CHUNK_ROWS)
        if not rows:
            break
        buf = rows_to_tsv_buffer(rows)
        pg_conn = get_conn()
        pg_cur = pg_conn.cursor()
        pg_cur.copy_expert(
            f"COPY raw.{table} ({col_list}) FROM STDIN WITH (FORMAT text, NULL '\\N')",
            buf,
        )
        pg_conn.commit()
        pg_conn.close()
        total += len(rows)
        if total % 50_000 == 0:
            print(f"    ... {total:,} rows loaded", flush=True)

    return total


def verify_counts(sqlite_conn, tables, get_conn):
    mismatches = []
    pg_conn = get_conn()
    sq_cur = sqlite_conn.cursor()
    pg_cur = pg_conn.cursor()

    for table in tables:
        sq_cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        src = sq_cur.fetchone()[0]
        pg_cur.execute(f"SELECT COUNT(*) FROM raw.{table}")
        dst = pg_cur.fetchone()[0]
        if src != dst:
            mismatches.append((table, src, dst))

    pg_conn.close()
    return mismatches


def main():
    resume = "--resume" in sys.argv

    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: SQLite database not found at {SQLITE_PATH}")
        sys.exit(1)

    sqlite_conn = sqlite3.connect(SQLITE_PATH)

    print("Connecting to Postgres (localhost proxy)...")
    try:
        pg_conn = get_pg_connection()
        pg_conn.close()
    except Exception as e:
        print(f"ERROR: Cannot connect to Postgres. Is flyctl proxy running?\n  {e}")
        sys.exit(1)

    tables = get_sqlite_tables(sqlite_conn)
    print(f"Found {len(tables)} tables to load\n")

    total_rows = 0
    skipped = 0
    start = time.time()

    for table in tables:
        columns = get_columns(sqlite_conn, table)
        src_count = get_source_count(sqlite_conn, table)

        if resume:
            try:
                pg_conn = get_pg_connection()
                pg_count = get_pg_count(pg_conn, table)
                pg_conn.close()
                if pg_count == src_count:
                    print(f"  {table:25s}  {pg_count:>10,} rows  (skipped — already loaded)")
                    total_rows += pg_count
                    skipped += 1
                    continue
            except Exception:
                pass

        t0 = time.time()
        try:
            count = load_table(sqlite_conn, table, columns, get_pg_connection)
        except Exception as e:
            print(f"  {table:25s}  FAILED: {e}")
            continue
        elapsed = time.time() - t0
        total_rows += count
        print(f"  {table:25s}  {count:>10,} rows  ({elapsed:.1f}s)")

    wall = time.time() - start
    print(f"\nLoaded {total_rows:,} rows across {len(tables)} tables in {wall:.1f}s")
    if skipped:
        print(f"  ({skipped} tables skipped — already at correct count)")

    print("\nVerifying row counts...")
    mismatches = verify_counts(sqlite_conn, tables, get_pg_connection)
    if mismatches:
        print("MISMATCH detected:")
        for table, src, dst in mismatches:
            print(f"  {table}: source={src:,} postgres={dst:,}")
        sys.exit(1)
    else:
        print("All row counts match. Ingestion complete.")

    sqlite_conn.close()


if __name__ == "__main__":
    main()
