"""Plan U19a: move the five writers' tables out of the platform's schemas, each into a
schema its repo owns. The owner runs this through scripts/move_writer_tables.ps1,
which opens and closes the Fly proxy; no session runs it against production
(DECISIONS#u19-start, the owner's 2026-11-15 order).

In one run:
  1. reads the admin credential from the platform .env, inside this process only;
  2. checks the deploy order: production-demand-forecast's app reads its snapshot
     tables through a search path that finds them before and after the move, so the
     move waits until the commit fly-deploy last deployed from main has that path;
  3. surveys production: every writer relation, where it is, its owner, its rows;
  4. backs the database up with pg_dump and checks the file reads back; stops if not;
  5. prints the plan: every relation moved with its current owner and new schema,
     every relation dropped, every schema created and the grants each repo's login
     gets; asks for MOVE;
  6. applies it in one transaction, re-counting every moved relation inside it, and
     rolls back on any failure;
  7. reads production back on a fresh connection and prints PASS/FAIL per repo.

No password or DSN is ever printed. Nothing outside the relations named in REPOS is
touched. What production held on 2026-11-17 (reader run 44197572155):
  - production-demand-forecast: four snapshot tables in copack (one owned by postgres,
    three and the snapshot_meta sequence by cinderhaven_demand_forecast);
  - dimension-weight-integrity: four source tables in public, four views in
    public_staging, four in public_intermediate, four tables in public_marts, and a
    stale copy of the four marts in public_public_marts (a dbt run without its schema
    macro; nothing depends on it);
  - retail-velocity-decision-tool and the-question-engine: none of their tables;
  - contract-to-cash: none; production's raw.shopify_* are the platform's.
"""
from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psycopg2
from psycopg2 import sql

import prod_guard
from rotate_and_place import admin_creds, backup

ROOT = Path(__file__).resolve().parent.parent
ORG = "lailarallc"
CONFIRM = "MOVE"

DWI_SOURCES = ("netsuite_items", "wms_dimensions", "gdsn_published", "shopify_products")
DWI_STAGING = tuple(f"stg_{t}" for t in DWI_SOURCES)
DWI_INTERMEDIATE = ("int_dim_and_billable", "int_freight_class_by_system", "int_measurement_of_record",
                    "int_system_attribute_divergence")
DWI_MARTS = ("fct_attribute_divergence", "fct_dimension_cost", "fct_freight_class_by_system",
             "fct_governed_product_master")
PLATFORM_SCHEMAS = ("raw", "costing", "copack", "voidfinder", "public", "public_staging", "public_intermediate",
                    "public_marts")


@dataclass
class Repo:
    name: str
    schema: str | None            # the schema the repo owns; None: it writes nothing (contract-to-cash)
    login: str | None             # its own login in production, if it has one
    move: list[tuple[str, str]] = field(default_factory=list)       # (schema, relation) where the old code put it
    find: tuple[str, ...] = ()    # relation names its old code may have written into any platform schema
    drop: list[tuple[str, str]] = field(default_factory=list)       # stale copies, dropped
    drop_schemas: tuple[str, ...] = ()                             # emptied by the drops, dropped if empty
    note: str = ""


REPOS = [
    Repo("production-demand-forecast", "production_demand_forecast", "cinderhaven_demand_forecast",
         move=[("copack", t) for t in ("forecast_snapshot", "forecast_week_snapshot", "doom_loop_snapshot",
                                       "snapshot_meta")]),
    Repo("dimension-weight-integrity", "dimension_weight_integrity", None,
         move=[("public", t) for t in DWI_SOURCES] + [("public_staging", t) for t in DWI_STAGING]
         + [("public_intermediate", t) for t in DWI_INTERMEDIATE] + [("public_marts", t) for t in DWI_MARTS],
         drop=[("public_public_marts", t) for t in DWI_MARTS],
         drop_schemas=("public_public_marts", "public_public_staging", "public_public_intermediate")),
    Repo("retail-velocity-decision-tool", "retail_velocity_decision_tool", "retail_velocity_decision_tool",
         find=("stg_category_benchmarks",)),
    Repo("the-question-engine", "the_question_engine", None, find=("q12_summary", "q12_by_sku")),
    Repo("contract-to-cash", None, None,
         note="it writes no warehouse table: its generator is retired and it reads the platform's "
              "raw.shopify_* tables"),
]

# The deploy-order guard: the app that reads moved tables live, and what its deployed code must say.
LIVE_READERS = {"production-demand-forecast": ("fly-deploy.yml", "app/db.py",
                                               "search_path=production_demand_forecast,copack")}


@dataclass
class Rel:
    repo: str
    schema: str
    name: str
    kind: str
    owner: str
    rows: int | None = None


KIND = {"r": "TABLE", "p": "TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW"}


def relation(cur, schema: str, name: str) -> tuple[str, str] | None:
    cur.execute("SELECT c.relkind, pg_get_userbyid(c.relowner) FROM pg_class c JOIN pg_namespace n "
                "ON n.oid = c.relnamespace WHERE n.nspname = %s AND c.relname = %s AND c.relkind IN "
                "('r','p','v','m')", (schema, name))
    return cur.fetchone()


def count(cur, schema: str, name: str) -> int:
    cur.execute(sql.SQL("SELECT count(*) FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(name)))
    return cur.fetchone()[0]


def role_exists(cur, role: str | None) -> bool:
    if not role:
        return False
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    return cur.fetchone() is not None


def survey(conn) -> dict:
    """What production holds for each repo now. Raises SystemExit on a state the plan cannot carry."""
    out = {}
    with conn.cursor() as cur:
        cur.execute("SELECT current_user")
        admin = cur.fetchone()[0]
        for r in REPOS:
            moves, already, absent, drops, problems = [], [], [], [], []
            wanted = list(r.move)
            for name in r.find:
                cur.execute("SELECT n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "WHERE c.relname = %s AND n.nspname = ANY(%s) AND c.relkind IN ('r','p','v','m')",
                            (name, list(PLATFORM_SCHEMAS)))
                found = [s for (s,) in cur.fetchall()]
                wanted += [(s, name) for s in found] or [(None, name)]
            for schema, name in wanted:
                old = relation(cur, schema, name) if schema else None
                new = relation(cur, r.schema, name) if r.schema else None
                if old and new:
                    problems.append(f"{name} is in both {schema} and {r.schema}; which copy is current is the "
                                    "owner's call")
                elif old:
                    moves.append(Rel(r.name, schema, name, old[0], old[1], count(cur, schema, name)))
                elif new:
                    already.append(Rel(r.name, r.schema, name, new[0], new[1], count(cur, r.schema, name)))
                else:
                    absent.append(f"{schema}.{name}" if schema else name)
            for schema, name in r.drop:
                old = relation(cur, schema, name)
                if old:
                    drops.append(Rel(r.name, schema, name, old[0], old[1], count(cur, schema, name)))
            dropped = {(d.schema, d.name) for d in drops}
            cur.execute("SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)", (list(r.drop_schemas),))
            present = {s for (s,) in cur.fetchall()}
            drop_schemas = [s for s in r.drop_schemas if s in present]
            for s in drop_schemas:
                cur.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "WHERE n.nspname = %s AND c.relkind IN ('r','p','v','m','S','f')", (s,))
                extra = [n for (n,) in cur.fetchall() if (s, n) not in dropped]
                if extra:
                    problems.append(f"{s} holds relations the plan does not name: {', '.join(sorted(extra))}")
            for d in drops:
                cur.execute("SELECT DISTINCT dn.nspname || '.' || dc.relname FROM pg_depend dp "
                            "JOIN pg_rewrite w ON w.oid = dp.objid JOIN pg_class dc ON dc.oid = w.ev_class "
                            "JOIN pg_namespace dn ON dn.oid = dc.relnamespace "
                            "WHERE dp.refobjid = %s::regclass AND dc.oid <> dp.refobjid",
                            (f'"{d.schema}"."{d.name}"',))
                deps = [x for (x,) in cur.fetchall()]
                if deps:
                    problems.append(f"{d.schema}.{d.name} has dependents: {', '.join(deps)}")
            schema_exists = owner = None
            if r.schema:
                cur.execute("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s", (r.schema,))
                row = cur.fetchone()
                schema_exists, owner = row is not None, (row[0] if row else None)
            login = r.login if role_exists(cur, r.login) else None
            out[r.name] = {"repo": r, "moves": moves, "already": already, "absent": absent, "drops": drops,
                           "drop_schemas": drop_schemas,
                           "problems": problems, "schema_exists": schema_exists, "schema_owner": owner,
                           "login": login, "new_owner": login or admin, "admin": admin}
        cur.execute("SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n "
                    "ON n.oid = c.relnamespace WHERE n.nspname = 'public_marts' AND c.relname = 'dim_products' "
                    "AND a.attname = 'category' AND NOT a.attisdropped")
        out["_dim_products_category"] = cur.fetchone() is not None
        cur.execute("SELECT 1 FROM pg_class WHERE relname = 'idx_scan_sku_store' AND relkind = 'i'")
        out["_scan_index"] = cur.fetchone() is not None
    return out


def print_plan(s: dict) -> None:
    print("\nThis run will, in one transaction (any failure rolls all of it back):")
    for r in REPOS:
        st = s[r.name]
        print(f"\n  {r.name}")
        if r.schema is None:
            print(f"    nothing to move; {r.note}")
            continue
        verb = "exists, owner " + st["schema_owner"] if st["schema_exists"] else "create"
        print(f"    schema {r.schema}: {verb}; owner after: {st['new_owner']}")
        for m in st["moves"]:
            print(f"    move {KIND[m.kind].lower():5s} {m.schema}.{m.name}  (owner {m.owner}, {m.rows} rows)"
                  f"  ->  {r.schema}.{m.name}")
        for m in st["already"]:
            print(f"    already moved: {r.schema}.{m.name} ({m.rows} rows)")
        for a in st["absent"]:
            print(f"    not in production: {a} (nothing to move)")
        for d in st["drops"]:
            print(f"    DROP  {KIND[d.kind].lower():5s} {d.schema}.{d.name}  (owner {d.owner}, {d.rows} rows; a stale "
                  f"copy of {r.schema}'s, nothing depends on it)")
        for sch in st["drop_schemas"]:
            print(f"    DROP  schema {sch} (empty once the stale copies go; the drop fails if it is not)")
        if st["login"]:
            print(f"    grants: {st['login']} owns {r.schema} (USAGE, CREATE) and every relation moved into it")
        else:
            print(f"    grants: none; the repo has no login of its own in production. {st['admin']} owns the "
                  f"schema; U12 hands it to the repo's writer login")
    if s["_dim_products_category"]:
        print("\n  left as found: public_marts.dim_products has a category column (retail-velocity-decision-tool's "
              "old seeder added it); dbt's next build of the table drops it")
    if s["_scan_index"]:
        print("\n  left as found: index idx_scan_sku_store on public_marts.fct_scan_data (the-question-engine's "
              "retired add_index.py); dbt's next build of the table drops it")


def apply(conn, s: dict) -> None:
    """Every step in one transaction; each moved relation re-counted in its new schema before commit."""
    with conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '15s'")
        for r in REPOS:
            st = s[r.name]
            if r.schema is None:
                continue
            owner = sql.Identifier(st["new_owner"])
            schema = sql.Identifier(r.schema)
            if st["schema_exists"]:
                cur.execute(sql.SQL("ALTER SCHEMA {} OWNER TO {}").format(schema, owner))
            else:
                cur.execute(sql.SQL("CREATE SCHEMA {} AUTHORIZATION {}").format(schema, owner))
            if st["login"]:
                cur.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA {} TO {}").format(schema, owner))
            for m in st["moves"]:
                kind = sql.SQL(KIND[m.kind])
                cur.execute(sql.SQL("ALTER {} {}.{} SET SCHEMA {}").format(
                    kind, sql.Identifier(m.schema), sql.Identifier(m.name), schema))
                if st["login"]:
                    cur.execute(sql.SQL("ALTER {} {}.{} OWNER TO {}").format(
                        kind, schema, sql.Identifier(m.name), owner))
                got = count(cur, r.schema, m.name)
                if got != m.rows:
                    raise RuntimeError(f"{r.schema}.{m.name} counts {got} rows after the move, {m.rows} before")
            for d in st["drops"]:
                cur.execute(sql.SQL("DROP {} {}.{}").format(sql.SQL(KIND[d.kind]), sql.Identifier(d.schema),
                                                            sql.Identifier(d.name)))
            for sch in st["drop_schemas"]:
                cur.execute(sql.SQL("DROP SCHEMA {}").format(sql.Identifier(sch)))  # no CASCADE: fails if not empty
    conn.commit()


def verify(conn, s: dict) -> list[tuple[str, bool, str]]:
    """Read production back on a fresh connection: one PASS/FAIL line per repo."""
    results = []
    with conn.cursor() as cur:
        for r in REPOS:
            st = s[r.name]
            bad = []
            if r.schema is None:
                cur.execute("SELECT pg_get_userbyid(c.relowner), bool_or(a.attname = 'payment_method') "
                            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 "
                            "WHERE n.nspname = 'raw' AND c.relname = 'shopify_transactions' GROUP BY 1")
                row = cur.fetchone()
                if row and row[1]:
                    bad.append("raw.shopify_transactions has the repo's generated shape (payment_method)")
                results.append((r.name, not bad, "; ".join(bad) or f"nothing to move; {r.note}"))
                continue
            cur.execute("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s", (r.schema,))
            row = cur.fetchone()
            if not row:
                bad.append(f"schema {r.schema} missing")
            elif row[0] != st["new_owner"]:
                bad.append(f"schema {r.schema} owned by {row[0]}, not {st['new_owner']}")
            if st["login"]:
                cur.execute("SELECT has_schema_privilege(%s, %s, 'USAGE'), has_schema_privilege(%s, %s, 'CREATE')",
                            (st["login"], r.schema, st["login"], r.schema))
                if not all(cur.fetchone()):
                    bad.append(f"{st['login']} lacks USAGE or CREATE on {r.schema}")
            for m in st["moves"] + st["already"]:
                if relation(cur, m.schema, m.name) and m.schema != r.schema:
                    bad.append(f"{m.schema}.{m.name} still there")
                now = relation(cur, r.schema, m.name)
                if not now:
                    bad.append(f"{r.schema}.{m.name} missing")
                    continue
                n = count(cur, r.schema, m.name)
                if n != m.rows:
                    bad.append(f"{r.schema}.{m.name}: {n} rows, {m.rows} before")
                if st["login"] and now[1] != st["login"]:
                    bad.append(f"{r.schema}.{m.name} owned by {now[1]}")
            for d in st["drops"]:
                if relation(cur, d.schema, d.name):
                    bad.append(f"{d.schema}.{d.name} not dropped")
            moved = len(st["moves"]) + len(st["already"])
            detail = (f"{moved} relation(s) in {r.schema}, rows equal; {len(st['drops'])} stale dropped"
                      if not bad else "; ".join(bad))
            results.append((r.name, not bad, detail))
    return results


def deploy_order(gh: list[str]) -> list[str]:
    """Each live reader's last successful deploy from main must read through the new search path."""
    stops = []
    for repo, (workflow, path, marker) in LIVE_READERS.items():
        full = f"{ORG}/{repo}"
        r = subprocess.run([*gh, "run", "list", "--repo", full, "--workflow", workflow, "--branch", "main",
                            "--status", "success", "--limit", "1", "--json", "headSha", "--jq", ".[0].headSha"],
                           capture_output=True, text=True)
        sha = r.stdout.strip()
        if r.returncode != 0 or not sha:
            stops.append(f"{repo}: no successful {workflow} run on main found")
            continue
        c = subprocess.run([*gh, "api", f"repos/{full}/contents/{path}?ref={sha}", "--jq", ".content"],
                           capture_output=True, text=True)
        text = base64.b64decode(c.stdout.strip() or b"").decode(errors="replace") if c.returncode == 0 else ""
        if marker not in text:
            stops.append(f"{repo}: the deployed commit {sha[:7]} does not read through {marker!r} ({path}); merge "
                         f"its u19a-writer-move branch and let {workflow} finish first, or its live page loses its "
                         "snapshot tables when they move")
    return stops


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--port", type=int, default=int(os.environ.get("MOVE_PROXY_PORT", "15434")))
    p.add_argument("--env-file", type=Path, default=ROOT / ".env")
    p.add_argument("--gh", default="gh", help=argparse.SUPPRESS)  # tests pass a fake
    p.add_argument("--docker", default="docker", help=argparse.SUPPRESS)
    p.add_argument("--backup-dir", type=Path, default=ROOT, help=argparse.SUPPRESS)
    p.add_argument("--host", default="localhost", help=argparse.SUPPRESS)
    args = p.parse_args(argv)

    creds = admin_creds(args.env_file)
    admin = f"host={args.host} port={args.port} dbname={creds['db']} user={creds['user']} password={creds['password']}"
    try:
        prod_guard.check(admin)
    except prod_guard.ProdDatabaseError as e:
        print(f"prod_guard: {e}", file=sys.stderr)
        return 1

    stops = deploy_order(args.gh.split("|"))
    if stops:
        print("STOP: the deploy order is not met. Nothing changed.")
        for s in stops:
            print(f"  {s}")
        return 1
    print("Deploy order: every live reader's deployed code finds its tables before and after the move.")

    conn = psycopg2.connect(admin, connect_timeout=10)
    try:
        s = survey(conn)
        conn.rollback()
        problems = [f"{r.name}: {p}" for r in REPOS for p in s[r.name]["problems"]]
        if problems:
            print("STOP: production is not in a state this plan carries. Nothing changed.")
            for x in problems:
                print(f"  {x}")
            return 1
        out = args.backup_dir / f"backup-prod-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.dump"
        print(f"\nBacking up the database to {out.name} (a few minutes) ...", flush=True)
        ok, detail = backup(creds, args.port, out, args.docker.split("|"))
        if not ok:
            print(f"STOP: backup failed: {detail}. Nothing changed.")
            return 1
        print(f"Backup: {detail}")
        print_plan(s)
        if input(f"\nType {CONFIRM} to do this: ").strip() != CONFIRM:
            print("Not confirmed: nothing changed.")
            return 1
        try:
            apply(conn, s)
        except Exception as e:  # noqa: BLE001 - any failure rolls the whole move back
            conn.rollback()
            print(f"FAILED, rolled back, nothing changed: {str(e).strip().splitlines()[0]}")
            return 1
        print("Committed.")
    finally:
        conn.close()

    check = psycopg2.connect(admin, connect_timeout=10)
    try:
        results = verify(check, s)
    finally:
        check.close()
    print()
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}: {detail}")
    return 0 if all(ok for _, ok, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
