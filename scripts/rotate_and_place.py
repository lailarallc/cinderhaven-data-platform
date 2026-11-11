"""Rotate cinderhaven_dagster and cinderhaven_ci_reader, and put each new password
where it is read. The owner runs this through scripts/rotate_and_place.ps1, which
opens and closes the Fly proxy; no session runs it (DECISIONS#u4-custody-shape).

In one run:
  1. reads the admin credential from the platform .env, inside this process only;
  2. prints production's current state (roles, logins, schema owners): which
     steps of the apply have happened;
  3. stops if the two logins do not exist (then the apply itself never ran);
  4. shows the dry run and asks for APPLY;
  5. rotates both logins (server receives SCRAM verifiers only);
  6. backs up ~/.dbt/profiles.yml and writes cinderhaven_dagster and its password
     into the cinderhaven profile;
  7. sets the POSTGRES_PASSWORD Actions secret of lailarallc/cinderhaven-data-platform
     with `gh secret set`, the password on stdin;
  8. logs in as each login with its new password (Dagster's read back from the
     profile it was written to) and prints PASS/FAIL;
  9. dispatches verify-production-figures.yml, the workflow that reads the
     secret, and prints its PASS/FAIL.

No password or DSN is ever printed. The repo-level POSTGRES_PASSWORD secret is
updated in place, not created (owner, 2026-11-09: no new secret).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psycopg2
import yaml
from dotenv import dotenv_values

import apply_truth_roles as atr
import prod_guard

ROOT = Path(__file__).resolve().parent.parent
REPO = "lailarallc/cinderhaven-data-platform"
SECRET = "POSTGRES_PASSWORD"
DAGSTER, READER = "cinderhaven_dagster", "cinderhaven_ci_reader"
WORKFLOW = "verify-production-figures.yml"


def dsn(host: str, port: int, db: str, user: str, password: str) -> str:
    return f"host={host} port={port} dbname={db} user={user} password={password}"


def admin_dsn(env_file: Path, port: int) -> tuple[str, str]:
    vals = dotenv_values(env_file)
    password = vals.get("POSTGRES_PASSWORD")
    if not password:
        raise SystemExit(f"{env_file}: no POSTGRES_PASSWORD (the admin credential); nothing changed")
    db = vals.get("POSTGRES_DB") or "cinderhaven"
    return dsn("localhost", port, db, vals.get("POSTGRES_USER") or "postgres", password), db


def state(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)",
                    (list(atr.ROLES) + [DAGSTER, READER],))
        have = {r for (r,) in cur.fetchall()}
        cur.execute("SELECT nspname, pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = ANY(%s) ORDER BY 1",
                    (list(atr.SCHEMAS + atr.DBT_SCHEMAS),))
        owners = dict(cur.fetchall())
    return {"roles": [r for r in atr.ROLES if r in have], "logins": [l for l in (DAGSTER, READER) if l in have],
            "owners": owners}


def print_state(s: dict) -> None:
    print("\nProduction now:")
    print(f"  group roles present: {', '.join(s['roles']) or 'none'}  ({len(s['roles'])} of {len(atr.ROLES)})")
    print(f"  logins present:      {', '.join(s['logins']) or 'none'}")
    for schema, owner in s["owners"].items():
        print(f"  schema {schema:20s} owner {owner}")


def write_profile(path: Path, user: str, password: str) -> Path:
    """Back up `path`, then set user and password in its cinderhaven profile's single output."""
    text = path.read_text(encoding="utf-8")
    profile = (yaml.safe_load(text) or {}).get("cinderhaven") or {}
    outputs = profile.get("outputs") or {}
    if len(outputs) != 1:
        raise SystemExit(f"{path}: the cinderhaven profile has {len(outputs)} outputs; expected one. Nothing changed.")
    backup = path.with_name(f"{path.name}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    lines, out, in_block, user_line, pw_done = text.splitlines(keepends=True), [], False, None, False
    for line in lines:
        if re.match(r"^\S", line):
            in_block = line.startswith("cinderhaven:")
        m = re.match(r"^(\s+)(user|password):", line) if in_block else None
        if m and m.group(2) == "user":
            out.append(f'{m.group(1)}user: {user}\n')
            user_line = (len(out), m.group(1))
            continue
        if m and m.group(2) == "password":
            out.append(f'{m.group(1)}password: "{password}"\n')
            pw_done = True
            continue
        out.append(line)
    if user_line is None:
        raise SystemExit(f"{path}: no user line in the cinderhaven profile. Restore from {backup.name}.")
    if not pw_done:
        out.insert(user_line[0], f'{user_line[1]}password: "{password}"\n')
    path.write_text("".join(out), encoding="utf-8")
    written = next(iter((yaml.safe_load(path.read_text(encoding="utf-8"))["cinderhaven"]["outputs"]).values()))
    if written.get("user") != user or written.get("password") != password:
        shutil.copy2(backup, path)
        raise SystemExit(f"{path}: the write did not read back; restored from {backup.name}.")
    return backup


def profile_credential(path: Path) -> tuple[str, str]:
    out = next(iter(yaml.safe_load(path.read_text(encoding="utf-8"))["cinderhaven"]["outputs"].values()))
    return out["user"], out["password"]


def login_test(port: int, db: str, user: str, password: str, role: str) -> tuple[bool, str]:
    try:
        conn = psycopg2.connect(dsn("localhost", port, db, user, password), connect_timeout=10)
    except psycopg2.OperationalError as e:
        return False, f"could not log in ({str(e).splitlines()[-1].strip()})"
    with conn, conn.cursor() as cur:
        cur.execute("SELECT current_user, rolsuper, pg_has_role(current_user, %s, 'MEMBER') FROM pg_roles "
                    "WHERE rolname = current_user", (role,))
        who, su, member = cur.fetchone()
    conn.close()
    ok = who == user and not su and member
    return ok, f"logged in as {who}, superuser={su}, member of {role}={member}"


def set_secret(gh: list[str], value: str) -> bool:
    r = subprocess.run([*gh, "secret", "set", SECRET, "--repo", REPO], input=value, text=True,
                       capture_output=True)
    return r.returncode == 0


def dispatch_and_wait(gh: list[str]) -> tuple[bool, str]:
    before = subprocess.run([*gh, "run", "list", "--workflow", WORKFLOW, "--repo", REPO, "--limit", "1",
                             "--json", "databaseId", "--jq", ".[0].databaseId"], capture_output=True, text=True)
    subprocess.run([*gh, "workflow", "run", WORKFLOW, "--repo", REPO, "--ref", "main"], check=True,
                   capture_output=True)
    run_id = before.stdout.strip()
    for _ in range(30):
        time.sleep(4)
        now = subprocess.run([*gh, "run", "list", "--workflow", WORKFLOW, "--repo", REPO, "--limit", "1",
                              "--json", "databaseId", "--jq", ".[0].databaseId"], capture_output=True, text=True)
        if now.stdout.strip() and now.stdout.strip() != run_id:
            run_id = now.stdout.strip()
            break
    else:
        return False, "the dispatched run did not appear"
    r = subprocess.run([*gh, "run", "watch", run_id, "--repo", REPO, "--exit-status"], capture_output=True, text=True)
    return r.returncode == 0, f"https://github.com/{REPO}/actions/runs/{run_id}"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=int(os.environ.get("ROTATE_PROXY_PORT", "15432")))
    p.add_argument("--env-file", type=Path, default=ROOT / ".env")
    p.add_argument("--profiles", type=Path, default=Path.home() / ".dbt" / "profiles.yml")
    p.add_argument("--gh", default="gh", help=argparse.SUPPRESS)  # tests pass a fake
    p.add_argument("--no-dispatch", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    gh = args.gh.split("|")

    admin, db = admin_dsn(args.env_file, args.port)
    try:
        prod_guard.check(admin)
    except prod_guard.ProdDatabaseError as e:
        print(f"prod_guard: {e}", file=sys.stderr)
        return 1
    conn = psycopg2.connect(admin, connect_timeout=10)
    try:
        s = state(conn)
        print_state(s)
        missing = [l for l in (DAGSTER, READER) if l not in s["logins"]]
        if missing:
            print(f"\nSTOP: {', '.join(missing)} not on this host, so the apply (apply_truth_roles.py --apply) has "
                  "not run here. This script only rotates. Nothing changed.")
            return 1
        atr.check_rotatable(conn, [DAGSTER, READER])
        print("\nThis run will:")
        print(f"  1. give {DAGSTER} and {READER} new passwords (old ones stop working)")
        print(f"  2. back up {args.profiles} and set the cinderhaven profile's user to {DAGSTER} and its password")
        print(f"  3. set the {SECRET} Actions secret of {REPO} to {READER}'s password")
        print("  4. log in as each, then run the verify workflow")
        if input("\nType APPLY to do this: ").strip() != "APPLY":
            print("Not confirmed: nothing changed.")
            return 1
        passwords = atr.rotate_passwords(conn, [DAGSTER, READER])
    finally:
        conn.close()
    print("Rotated both logins.")

    backup = write_profile(args.profiles, DAGSTER, passwords[DAGSTER])
    print(f"Wrote {DAGSTER} into {args.profiles} (backup: {backup.name}).")
    secret_ok = set_secret(gh, passwords[READER])
    print(f"{'Set' if secret_ok else 'FAILED to set'} the {SECRET} secret.")

    results = []
    user, pw = profile_credential(args.profiles)
    results.append((f"Dagster login, read back from {args.profiles.name}",
                    *login_test(args.port, db, user, pw, "cinderhaven_dbt")))
    results.append(("Reader login", *login_test(args.port, db, READER, passwords[READER], "cinderhaven_reader")))
    passwords.clear()
    if not secret_ok:
        results.append((f"{SECRET} secret", False, "gh secret set failed; the reader login works but CI cannot use it"))
    elif not args.no_dispatch:
        results.append((f"{WORKFLOW} with the new secret", *dispatch_and_wait(gh)))

    print()
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
