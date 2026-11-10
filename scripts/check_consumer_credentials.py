"""Egress path 4: every consumer connects as its own reader login (plan U4).

THE OWNER RUNS THIS; no session does (DECISIONS#u4-custody-shape, 2026-11-09):
it reads each repo's configured credential.

Population: the consumer read map's classes A and B, plus recall-blast-radius
(its own database on the same cluster), parsed from the map, never retyped.
For each repo it finds the configured credential:
  - a .env in the working copy (DATABASE_URL, or POSTGRES_USER / PGUSER), or
  - the Fly app's DATABASE_URL secret, read from inside the app with
    `flyctl ssh console` when the repo has a fly.toml and no .env credential.
It keeps only the LOGIN NAME. Nothing else from a credential is printed,
stored or used: the role's attributes are read through the administrator
connection (DATABASE_URL in this shell), so no consumer password is ever sent
anywhere.

A pass is a login that exists, is not a superuser, is a member of
cinderhaven_reader and holds no USAGE on truth. On the host it also asserts
cinderhaven_validator has no LOGIN and no members. It reports today's state
(every consumer on the superuser fails) and goes green at U12, when each repo
gets its own reader login.

    DATABASE_URL=<admin DSN> ALLOW_PROD_DB=1 python scripts/check_consumer_credentials.py
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

import prod_guard

FLEET_ROOT = Path.home() / "projects"
READ_MAP = FLEET_ROOT / "active" / "cinderhaven-data-realism" / "docs" / "consumers" / "CONSUMER-READ-MAP.md"
EXTRA = ("recall-blast-radius",)


def population(read_map: Path) -> list[str]:
    text = read_map.read_text(encoding="utf-8")
    names: list[str] = []
    for head, nxt in (("### A", "### B"), ("### B", "### C")):
        block = text[text.index(head):text.index(nxt)]
        names += re.findall(r"^\*\*`([\w.-]+)`\*\*", block, re.MULTILINE)
    return sorted(set(names) | set(EXTRA))


def _user_from_dsn(dsn: str) -> str | None:
    if "://" in dsn:
        return urlparse(dsn).username
    m = re.search(r"\buser=(\S+)", dsn)
    return m.group(1) if m else None


def user_from_env_file(path: Path) -> str | None:
    vals = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Z_]+)\s*=\s*['\"]?([^'\"\n]*)", line)
        if m:
            vals[m.group(1)] = m.group(2).strip()
    if vals.get("DATABASE_URL"):
        return _user_from_dsn(vals["DATABASE_URL"])
    return vals.get("POSTGRES_USER") or vals.get("PGUSER")


def user_from_fly(repo: Path) -> tuple[str | None, str]:
    toml = (repo / "fly.toml").read_text(encoding="utf-8")
    m = re.search(r'^app\s*=\s*["\']([^"\']+)', toml, re.MULTILINE)
    if not m:
        return None, "fly.toml names no app"
    r = subprocess.run(["flyctl", "ssh", "console", "-a", m.group(1), "-C", "printenv DATABASE_URL"],
                       capture_output=True, text=True, timeout=120)
    dsn = r.stdout.strip()
    user = _user_from_dsn(dsn) if dsn else None
    del dsn
    return user, f"Fly secret of {m.group(1)}" if user else f"Fly app {m.group(1)}: no DATABASE_URL read"


def find_repo(name: str, fleet_root: Path) -> Path | None:
    hits = [p for p in fleet_root.glob(f"*/{name}") if (p / ".git").exists()]
    return hits[0] if hits else None


def role_verdict(cur, user: str) -> tuple[bool, str]:
    cur.execute("SELECT rolsuper, rolcanlogin FROM pg_roles WHERE rolname = %s", (user,))
    row = cur.fetchone()
    if row is None:
        return False, f"login {user!r} does not exist on this host"
    superuser, can_login = row
    cur.execute("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cinderhaven_reader') "
                "AND pg_has_role(%s, 'cinderhaven_reader', 'MEMBER')", (user,))
    reader = cur.fetchone()[0]
    cur.execute("SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'truth') "
                "THEN has_schema_privilege(%s, 'truth', 'USAGE') END", (user,))
    truth = cur.fetchone()[0]
    ok = can_login and not superuser and reader and not truth
    detail = (f"login {user!r}: superuser={superuser}, reader member={reader}, "
              f"truth USAGE={'n/a (no truth schema)' if truth is None else truth}")
    return ok, detail


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--read-map", type=Path, default=READ_MAP)
    p.add_argument("--fleet-root", type=Path, default=FLEET_ROOT)
    p.add_argument("--no-fly", action="store_true", help="do not read Fly secrets (report those repos as unchecked)")
    args = p.parse_args(argv)
    admin = os.environ.get("DATABASE_URL")
    if not admin:
        print("Set DATABASE_URL to the administrator DSN (it reads role attributes only).", file=sys.stderr)
        return 2
    try:
        prod_guard.check(admin)
    except prod_guard.ProdDatabaseError as e:
        print(f"prod_guard: {e}\nFor production, set ALLOW_PROD_DB=1 for this run.", file=sys.stderr)
        return 1

    results: list[tuple[str, bool, str]] = []
    conn = psycopg2.connect(admin, connect_timeout=10)
    try:
        with conn.cursor() as cur:
            for name in population(args.read_map):
                repo = find_repo(name, args.fleet_root)
                if repo is None:
                    results.append((name, False, "no working copy"))
                    continue
                user, source = None, ""
                if (repo / ".env").is_file():
                    user, source = user_from_env_file(repo / ".env"), ".env"
                if user is None and (repo / "fly.toml").is_file():
                    if args.no_fly:
                        results.append((name, False, "Fly-secret credential not checked (--no-fly)"))
                        continue
                    user, source = user_from_fly(repo)
                if user is None:
                    results.append((name, False, f"no configured credential found ({source or 'no .env, no fly.toml'})"))
                    continue
                ok, detail = role_verdict(cur, user)
                results.append((name, ok, f"{detail} [{source}]"))
            cur.execute("SELECT rolcanlogin, (SELECT count(*) FROM pg_auth_members m WHERE m.roleid = r.oid) "
                        "FROM pg_roles r WHERE rolname = 'cinderhaven_validator'")
            row = cur.fetchone()
            if row is None:
                results.append(("cinderhaven_validator", False, "role absent: apply sql/truth_roles.sql first"))
            else:
                results.append(("cinderhaven_validator", not row[0] and row[1] == 0,
                                f"LOGIN={row[0]}, members={row[1]} (must be False, 0 on this host)"))
    finally:
        conn.close()

    fails = sum(1 for _, ok, _ in results if not ok)
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    print(f"\n{len(results) - fails} pass, {fails} fail")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
