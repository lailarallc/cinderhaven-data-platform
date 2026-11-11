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
    python scripts/apply_truth_roles.py --reader-login NAME             # dry run, plus a workflow reader login
    python scripts/apply_truth_roles.py --apply [--dagster-login NAME] [--reader-login NAME]
                                                                        # asks for APPLY, then one transaction

--rotate LOGIN (repeatable) gives cinderhaven_dagster or cinderhaven_ci_reader
a new password, the same way, and changes nothing else; any other role is
refused (owner, 2026-11-10, after both first passwords went unkept).

    python scripts/apply_truth_roles.py --rotate cinderhaven_dagster --rotate cinderhaven_ci_reader [--apply]

--reader-login creates a NEW non-superuser login, a member of cinderhaven_reader,
the same way, for the platform's own read paths (verify-production-figures.yml,
dump_flyio.sh). Where its password is kept is the owner's ruling.

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


def change_list(cur, logins: list[tuple[str, str]]) -> list[str]:
    """Every change sql/truth_roles.sql (and each new login) would make here, read from the catalog."""
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
    for login, role in logins:
        out.append(f"CREATE ROLE {login} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE IN ROLE {role} "
                   "(password generated at apply, shown once)")
    return out


def check_new_login(cur, login: str) -> None:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (login,))
    if cur.fetchone():
        raise SystemExit(f"{login}: a role by that name exists. This script creates new logins; "
                         "it never takes over or resets an existing one.")


#: Where each new login's password goes, printed beside it (owner, 2026-11-09).
PLACE = {"cinderhaven_dbt": "Place it in ~/.dbt/profiles.yml (user and password of Dagster's cinderhaven target) now.",
         "cinderhaven_reader": "Place it in the platform repo's POSTGRES_PASSWORD Actions secret "
                               "(lailarallc/cinderhaven-data-platform) now."}

#: The only logins --rotate touches (owner, 2026-11-10), each with the role it must still be in.
ROTATABLE = {"cinderhaven_dagster": "cinderhaven_dbt", "cinderhaven_ci_reader": "cinderhaven_reader"}


def check_rotatable(conn, names: list[str]) -> None:
    """Raise SystemExit unless every name is a rotatable, existing, non-superuser login still in its role."""
    for n in names:
        if n not in ROTATABLE:
            raise SystemExit(f"--rotate {n}: refused. Only {', '.join(ROTATABLE)} can be rotated.")
    with conn.cursor() as cur:
        for n in names:
            cur.execute("SELECT rolsuper, rolcanlogin, pg_has_role(%s, %s, 'MEMBER') FROM pg_roles "
                        "WHERE rolname = %s", (n, ROTATABLE[n], n))
            row = cur.fetchone()
            if row is None:
                raise SystemExit(f"--rotate {n}: no such login here; it is created with --dagster-login/--reader-login")
            if row != (False, True, True):
                raise SystemExit(f"--rotate {n}: refused; expected a non-superuser login in {ROTATABLE[n]}, "
                                 f"found superuser={row[0]} login={row[1]} member={row[2]}")


def rotate_passwords(conn, names: list[str]) -> dict[str, str]:
    """ALTER each login's password to a new generated one, commit, and return them. Prints nothing."""
    check_rotatable(conn, names)
    passwords = {n: secrets.token_urlsafe(32) for n in names}
    with conn.cursor() as cur:
        for n in names:
            cur.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(sql.Identifier(n),
                                                                    sql.Literal(scram_verifier(passwords[n]))))
    conn.commit()
    return passwords


def rotate(conn, names: list[str], apply: bool) -> int:
    """Give each named login a new generated password; change nothing else."""
    check_rotatable(conn, names)
    print(f"\n{len(names)} change(s):")
    for n in names:
        print(f"  ALTER ROLE {n} PASSWORD (new, generated at apply, shown once; nothing else changes)")
    if not apply:
        print("\nDry run: nothing changed. Re-run with --apply to make these changes.")
        return 0
    if input("\nType APPLY to make these changes in one transaction: ").strip() != "APPLY":
        print("Not confirmed: nothing changed.")
        return 1
    passwords = rotate_passwords(conn, names)
    print("Applied and committed. The old passwords no longer work.")
    for n in names:
        print(f"\nLogin {n} ({ROTATABLE[n]}): its password follows, shown ONCE and stored nowhere.\n"
              f"{PLACE[ROTATABLE[n]]}\n\n    {passwords[n]}\n")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="make the changes (asks for confirmation)")
    p.add_argument("--dagster-login", help="create Dagster's own login, a member of cinderhaven_dbt")
    p.add_argument("--reader-login", help="create a workflow reader login, a member of cinderhaven_reader")
    p.add_argument("--rotate", action="append", metavar="LOGIN",
                   help=f"new password for an existing login, repeatable; only {', '.join(ROTATABLE)}")
    args = p.parse_args(argv)
    if args.rotate and (args.dagster_login or args.reader_login):
        raise SystemExit("--rotate runs alone: it changes passwords and nothing else")
    logins = [(n, r) for n, r in ((args.dagster_login, "cinderhaven_dbt"),
                                  (args.reader_login, "cinderhaven_reader")) if n]
    if len({n for n, _ in logins}) != len(logins):
        raise SystemExit("--dagster-login and --reader-login must name different logins")

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("Set DATABASE_URL to the administrator DSN from the platform's secret location.", file=sys.stderr)
        return 2
    if not args.rotate:
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
        if args.rotate:
            return rotate(conn, list(dict.fromkeys(args.rotate)), args.apply)
        with conn.cursor() as cur:
            for login, _ in logins:
                check_new_login(cur, login)
            changes = change_list(cur, logins)
        print(f"\n{len(changes)} change(s):")
        for c in changes:
            print(f"  {c}")
        if not args.apply:
            print("\nDry run: nothing changed. Re-run with --apply to make these changes.")
            return 0
        if input("\nType APPLY to make these changes in one transaction: ").strip() != "APPLY":
            print("Not confirmed: nothing changed.")
            return 1
        passwords = {}
        with conn.cursor() as cur:
            cur.execute(ROLES_SQL.read_text())
            for login, role in logins:
                passwords[login] = secrets.token_urlsafe(32)
                cur.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {} IN ROLE {}")
                            .format(sql.Identifier(login), sql.Literal(scram_verifier(passwords[login])),
                                    sql.Identifier(role)))
        conn.commit()
        print("Applied and committed.")
        for login, role in logins:
            print(f"\nLogin {login} ({role}): its password follows, shown ONCE and stored nowhere.\n"
                  f"{PLACE[role]}\n\n    {passwords[login]}\n")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
