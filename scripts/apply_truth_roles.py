"""Apply sql/truth_roles.sql to a host whose schemas predate the roles (production).

The owner runs this; no session does (DECISIONS#u4-custody-shape, 2026-11-09).
It transfers ownership of raw, costing, copack and voidfinder to
cinderhaven_generator, so it runs after a backup, and it prints every change
before it makes one.

    # 1. take a backup first
    # 2. set DATABASE_URL to the administrator DSN from the platform's secret location
    #    (production through a fly proxy also needs ALLOW_PROD_DB=1)
    python scripts/apply_truth_roles.py                       # dry run: prints the change list, changes nothing
    python scripts/apply_truth_roles.py --dbt-login NAME      # dry run, plus Dagster's login joining cinderhaven_dbt
    python scripts/apply_truth_roles.py --apply [--dbt-login NAME]   # asks for APPLY, then one transaction

The DSN is never printed. The SQL applied is sql/truth_roles.sql, unchanged.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

import prod_guard

ROOT = Path(__file__).resolve().parent.parent
ROLES_SQL = ROOT / "sql" / "truth_roles.sql"
ROLES = ("cinderhaven_generator", "cinderhaven_dbt", "cinderhaven_reader", "cinderhaven_validator")
SCHEMAS = ("raw", "costing", "copack", "voidfinder")
KIND = {"r": "TABLE", "p": "TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW"}
BACKUP_REMINDER = ("BACKUP: this transfers ownership of existing schemas. Confirm a backup of this database was "
                   "taken before running with --apply.")


def change_list(cur, dbt_login: str | None) -> list[str]:
    """Every change sql/truth_roles.sql (and --dbt-login) would make here, read from the catalog."""
    out: list[str] = []
    cur.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (list(ROLES),))
    have = {r for (r,) in cur.fetchall()}
    out += [f"CREATE ROLE {r} NOLOGIN" for r in ROLES if r not in have]
    cur.execute("SELECT pg_has_role('cinderhaven_generator', 'cinderhaven_dbt', 'MEMBER')"
                if "cinderhaven_generator" in have and "cinderhaven_dbt" in have else "SELECT false")
    if not cur.fetchone()[0]:
        out.append("GRANT cinderhaven_dbt TO cinderhaven_generator")
    cur.execute("SELECT current_database()")
    db = cur.fetchone()[0]
    out.append(f"GRANT CONNECT, CREATE ON DATABASE {db} TO cinderhaven_generator, cinderhaven_dbt")
    out.append(f"GRANT CONNECT ON DATABASE {db} TO cinderhaven_reader, cinderhaven_validator")
    for s in SCHEMAS:
        cur.execute("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s", (s,))
        row = cur.fetchone()
        if row is None:
            out.append(f"-- schema {s}: absent here, nothing to transfer")
            continue
        out.append(f"ALTER SCHEMA {s} OWNER: {row[0]} -> cinderhaven_generator")
        cur.execute("SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = %s AND c.relkind IN ('r', 'p', 'v', 'm') ORDER BY 1", (s,))
        for name, kind, owner in cur.fetchall():
            out.append(f"ALTER {KIND[kind]} {s}.{name} OWNER: {owner} -> cinderhaven_generator")
        readers = "cinderhaven_reader, cinderhaven_validator" + ("" if s == "voidfinder" else ", cinderhaven_dbt")
        out.append(f"GRANT USAGE ON SCHEMA {s}, SELECT ON ALL TABLES IN SCHEMA {s} TO {readers}")
        out.append(f"GRANT SELECT ON ALL SEQUENCES IN SCHEMA {s} TO cinderhaven_reader")
    out.append("CREATE OR REPLACE FUNCTION public.truth_populated() (SECURITY DEFINER, owner "
               "cinderhaven_generator; EXECUTE to reader, validator, generator)")
    if dbt_login:
        out.append(f"GRANT cinderhaven_dbt TO {dbt_login}")
    return out


def check_dbt_login(cur, login: str) -> None:
    cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = %s", (login,))
    row = cur.fetchone()
    if row is None:
        raise SystemExit(f"--dbt-login {login}: no such role here")
    if row[0]:
        raise SystemExit(f"--dbt-login {login} is a superuser: membership would mean nothing, since a superuser "
                         "ignores grants. Dagster needs its own non-superuser login first (plan U4, path 5).")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="make the changes (asks for confirmation)")
    p.add_argument("--dbt-login", help="Dagster's existing login, to join cinderhaven_dbt")
    args = p.parse_args(argv)

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("Set DATABASE_URL to the administrator DSN from the platform's secret location.", file=sys.stderr)
        return 2
    print(BACKUP_REMINDER)
    try:
        prod_guard.check(dsn)
    except prod_guard.ProdDatabaseError as e:
        print(f"prod_guard: {e}\nFor the production apply, set ALLOW_PROD_DB=1 for this run.", file=sys.stderr)
        return 1

    conn = psycopg2.connect(dsn, connect_timeout=10)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user, current_database(), inet_server_port()")
            user, db, port = cur.fetchone()
            print(f"Target: database {db}, port {port}, as {user}")
            if args.dbt_login:
                check_dbt_login(cur, args.dbt_login)
            changes = change_list(cur, args.dbt_login)
        print(f"\n{len(changes)} change(s):")
        for c in changes:
            print(f"  {c}")
        if not args.apply:
            print("\nDry run: nothing changed. Re-run with --apply to make these changes.")
            return 0
        if input("\nType APPLY to make these changes in one transaction: ").strip() != "APPLY":
            print("Not confirmed: nothing changed.")
            return 1
        with conn.cursor() as cur:
            cur.execute(ROLES_SQL.read_text())
            if args.dbt_login:
                cur.execute(sql.SQL("GRANT cinderhaven_dbt TO {}").format(sql.Identifier(args.dbt_login)))
        conn.commit()
        print("Applied and committed.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
