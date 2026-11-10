"""Apply sql/truth_roles.sql to a host whose schemas predate the roles (production).

The owner runs this; no session does (DECISIONS#u4-custody-shape, 2026-11-09).
It transfers ownership of raw, costing, copack and voidfinder to
cinderhaven_generator, and of the three dbt schemas to cinderhaven_dbt, so it
runs after a backup, and it prints every change before it makes one.

    # 1. take a backup first
    # 2. set DATABASE_URL to the administrator DSN from the platform's secret location
    #    (production through a fly proxy also needs ALLOW_PROD_DB=1)
    python scripts/apply_truth_roles.py                                 # dry run: prints the changes, makes none
    python scripts/apply_truth_roles.py --dagster-login NAME            # dry run, plus Dagster's new login
    python scripts/apply_truth_roles.py --apply [--dagster-login NAME]  # asks for APPLY, then one transaction

--dagster-login creates a NEW non-superuser login, a member of cinderhaven_dbt
(path 5). Its password is generated at apply time and printed ONCE, after the
commit, for the owner to place in ~/.dbt/profiles.yml, where Dagster's
credential already lives. The script never writes it anywhere, and the server
receives only a SCRAM-SHA-256 verifier computed here, so no statement log can
hold the plaintext.

The DSN is never printed. The SQL applied is sql/truth_roles.sql, unchanged.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import os
import secrets
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql

import prod_guard

ROOT = Path(__file__).resolve().parent.parent
ROLES_SQL = ROOT / "sql" / "truth_roles.sql"
ROLES = ("cinderhaven_generator", "cinderhaven_dbt", "cinderhaven_reader", "cinderhaven_validator")
SCHEMAS = ("raw", "costing", "copack", "voidfinder")
DBT_SCHEMAS = ("public_staging", "public_intermediate", "public_marts")
KIND = {"r": "TABLE", "p": "TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW"}
BACKUP_REMINDER = ("BACKUP: this transfers ownership of existing schemas. Confirm a backup of this database was "
                   "taken before running with --apply.")


def scram_verifier(password: str, iterations: int = 4096) -> str:
    """A SCRAM-SHA-256 verifier for `password`, the form Postgres stores (RFC 5802/7677).
    The generated password is ASCII, so SASLprep is the identity."""
    salt = secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.new(salted, b"Client Key", "sha256").digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b"Server Key", "sha256").digest()
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def _relations(cur, schema: str, owner_to: str, out: list[str]) -> None:
    cur.execute("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s", (schema,))
    row = cur.fetchone()
    if row is None:
        out.append(f"-- schema {schema}: absent here, nothing to transfer")
        return
    out.append(f"ALTER SCHEMA {schema} OWNER: {row[0]} -> {owner_to}")
    cur.execute("SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relkind IN ('r', 'p', 'v', 'm') ORDER BY 1", (schema,))
    for name, kind, owner in cur.fetchall():
        out.append(f"ALTER {KIND[kind]} {schema}.{name} OWNER: {owner} -> {owner_to}")


def change_list(cur, dagster_login: str | None) -> list[str]:
    """Every change sql/truth_roles.sql (and --dagster-login) would make here, read from the catalog."""
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
        _relations(cur, s, "cinderhaven_generator", out)
        if out[-1].startswith("-- schema"):
            continue
        readers = "cinderhaven_reader, cinderhaven_validator" + ("" if s == "voidfinder" else ", cinderhaven_dbt")
        out.append(f"GRANT USAGE ON SCHEMA {s}, SELECT ON ALL TABLES IN SCHEMA {s} TO {readers}")
        out.append(f"GRANT SELECT ON ALL SEQUENCES IN SCHEMA {s} TO cinderhaven_reader")
    for s in DBT_SCHEMAS:
        _relations(cur, s, "cinderhaven_dbt", out)
        if not out[-1].startswith("-- schema"):
            out.append(f"GRANT USAGE ON SCHEMA {s}, SELECT ON ALL TABLES IN SCHEMA {s} "
                       "TO cinderhaven_reader, cinderhaven_validator")
    out.append("CREATE OR REPLACE FUNCTION public.truth_populated() (SECURITY DEFINER, owner "
               "cinderhaven_generator; EXECUTE to reader, validator, generator)")
    if dagster_login:
        out.append(f"CREATE ROLE {dagster_login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE IN ROLE cinderhaven_dbt "
                   "(password generated at apply, shown once)")
    return out


def check_dagster_login(cur, login: str) -> None:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (login,))
    if cur.fetchone():
        raise SystemExit(f"--dagster-login {login}: a role by that name exists. This script creates Dagster's login; "
                         "it never takes over or resets an existing one.")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="make the changes (asks for confirmation)")
    p.add_argument("--dagster-login", help="create Dagster's own login, a member of cinderhaven_dbt")
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
            if args.dagster_login:
                check_dagster_login(cur, args.dagster_login)
            changes = change_list(cur, args.dagster_login)
        print(f"\n{len(changes)} change(s):")
        for c in changes:
            print(f"  {c}")
        if not args.apply:
            print("\nDry run: nothing changed. Re-run with --apply to make these changes.")
            return 0
        if input("\nType APPLY to make these changes in one transaction: ").strip() != "APPLY":
            print("Not confirmed: nothing changed.")
            return 1
        password = None
        with conn.cursor() as cur:
            cur.execute(ROLES_SQL.read_text())
            if args.dagster_login:
                password = secrets.token_urlsafe(32)
                cur.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {} "
                                    "IN ROLE cinderhaven_dbt").format(sql.Identifier(args.dagster_login),
                                                                      sql.Literal(scram_verifier(password))))
        conn.commit()
        print("Applied and committed.")
        if password:
            print(f"\nDagster login {args.dagster_login}: its password follows, shown ONCE and stored nowhere.\n"
                  "Place it in ~/.dbt/profiles.yml (user and password of Dagster's cinderhaven target) now.\n\n"
                  f"    {password}\n")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
