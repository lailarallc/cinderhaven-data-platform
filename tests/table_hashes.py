"""Per-table content hashes of the generated schemas on the harness instance.

Used to prove a change value-neutral (U4's move to generation/, U2's
characterization): hash before, hash after, compare. A table's hash is the md5
of its rows' md5s in sorted order, so it does not depend on physical row order.

Only generated schemas are hashed. `truth` is never hashed: a hash of it is an
aggregate of it, and an aggregate of truth is truth (plan U4, path 7).

    python tests/table_hashes.py > output/harness/hashes-before.json
    python tests/table_hashes.py --compare output/harness/hashes-before.json
"""
from __future__ import annotations

import json
import sys

import psycopg2
from psycopg2 import sql

import harness

SCHEMAS = ("raw", "costing", "voidfinder")


def table_hashes(conn) -> dict[str, str]:
    out: dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT schemaname, tablename FROM pg_tables WHERE schemaname = ANY(%s) "
                    "ORDER BY 1, 2", (list(SCHEMAS),))
        for schema, table in cur.fetchall():
            cur.execute(sql.SQL("SELECT count(*), md5(coalesce(string_agg(h, '' ORDER BY h), '')) "
                                "FROM (SELECT md5(t::text) h FROM {}.{} t) s")
                        .format(sql.Identifier(schema), sql.Identifier(table)))
            n, h = cur.fetchone()
            out[f"{schema}.{table}"] = f"{n}:{h}"
    return out


def main(argv: list[str]) -> int:
    vals = harness.harness_values()
    harness.guard(vals)
    with psycopg2.connect(harness.dsn(vals), connect_timeout=5) as conn:
        now = table_hashes(conn)
    if argv[:1] == ["--compare"]:
        before = json.loads(open(argv[1]).read())
        diff = sorted(k for k in before.keys() | now.keys() if before.get(k) != now.get(k))
        for k in diff:
            print(f"DIFF {k}: {before.get(k)} -> {now.get(k)}")
        print(f"{len(now)} tables, {len(diff)} differ")
        return 1 if diff else 0
    print(json.dumps(now, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
