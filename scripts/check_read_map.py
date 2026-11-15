"""The consumer read map as a contract (plan U19, ruling 3).

The spec repo's read map (docs/consumers/CONSUMER-READ-MAP.md) carries a parseable table, "## The table": one row per
warehouse read a named consumer makes, `schema.table`, its fields and a file:line that names it. This check reads that
table from the spec checkout; the platform keeps no copy of the list, and the check states no count of it.

Arms run here, each a failure when it does not hold:
  1. The table parses: its header, every row's class (A-D), status (live / retired) and read (`schema.table` or `-`).
  2. The table and the map's list ("## The list, by how a regen reaches it") name the same repos in the same classes.
  3. Every cited file:line exists in the repo's working copy and names the table it is cited for. A repo with no
     working copy under the fleet root fails by name.
  4. Every canon key the map's "## Canon keys read" lists exists in this repo's reference/canonical_values.json.
  5. With --warehouse: every listed read and field resolves in the harness instance's information_schema, or is on
     the map's break list (field `-` for the whole table) with its reader and U12 repoint; and every break-list
     entry is a table row the instance really breaks, so a fixed read cannot stay listed.

The warehouse arm connects to the harness's local test instance only, through tests/harness.py's values and
scripts/prod_guard.py; it takes no DSN, so it cannot be pointed at production (owner, 2026-11-14: production only
through the cinderhaven_ci_reader workflow). Without --warehouse it reads code and the vendored canon only, and says
the warehouse went unchecked.

Not built yet: the page-population arm.

    python scripts/check_read_map.py [--read-map PATH] [--fleet-root DIR] [--canon PATH] [--warehouse]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from check_export_allowlist import FLEET_ROOT, READ_MAP, find_repo

ROOT = Path(__file__).resolve().parent.parent
CANON = ROOT / "reference" / "canonical_values.json"
HEADER = "| Repo | Class | Status | Read | Fields | Where |"
NONE = "—"
CLASSES = "ABCD"
STATUSES = ("live", "retired")


def _section(text: str, heading: str) -> str:
    """The body under a `## ` heading, up to the next `## ` heading."""
    m = re.search(r"^## %s[^\n]*\n(.*?)(?=^## |\Z)" % re.escape(heading), text, re.M | re.S)
    return m.group(1) if m else ""


def parse_table(text: str) -> tuple[list[dict], list[str]]:
    """The table's rows, and the failures parsing them."""
    body = _section(text, "The table")
    lines = body.split("\n")
    if HEADER not in lines:
        return [], [f"the read map has no '## The table' with the header {HEADER!r}"]
    rows, bad = [], []
    for line in lines[lines.index(HEADER) + 2:]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 6:
            bad.append(f"table row with {len(cells)} cells, not 6: {line!r}")
            continue
        repo, cls, status, read, fields, where = cells
        row = dict(repo=repo, cls=cls, status=status, read=read, where=where,
                   fields=[] if fields == NONE else [f.strip() for f in fields.split(",")])
        if cls not in CLASSES:
            bad.append(f"{repo}: class {cls!r} is not one of {', '.join(CLASSES)}")
        if status not in STATUSES:
            bad.append(f"{repo}: status {status!r} is not one of {', '.join(STATUSES)}")
        if read != NONE and not re.fullmatch(r"\w+\.\w+", read):
            bad.append(f"{repo}: read {read!r} is not schema.table")
        if (read == NONE) != (where == NONE):
            bad.append(f"{repo}: read {read!r} and where {where!r}: a read has a file:line and only a read has one")
        if where != NONE and not re.fullmatch(r"[^:\s]+:\d+", where):
            bad.append(f"{repo}: where {where!r} is not path:line")
        rows.append(row)
    return rows, bad


def parse_list(text: str) -> dict[str, str]:
    """repo -> class, from the map's list section: each `**X. ...**` paragraph names its class's repos in backticks."""
    out = {}
    for m in re.finditer(r"^\*\*([A-D])\. [^\n]*?\*\*(.*?)(?=^\*\*[A-D]\. |^A \+ B|\Z)",
                         _section(text, "The list"), re.M | re.S):
        for name in re.findall(r"`([\w.-]+)`", m.group(2)):
            out[name] = m.group(1)
    return out


def check_classes(rows: list[dict], listed: dict[str, str]) -> list[str]:
    tabled = {}
    bad = []
    for r in rows:
        if tabled.setdefault(r["repo"], r["cls"]) != r["cls"]:
            bad.append(f"{r['repo']}: the table gives it classes {tabled[r['repo']]} and {r['cls']}")
    for repo in sorted(set(listed) - set(tabled)):
        bad.append(f"{repo}: class {listed[repo]} in the map's list, missing from the table")
    for repo in sorted(set(tabled) - set(listed)):
        bad.append(f"{repo}: in the table, missing from the map's list")
    for repo in sorted(set(listed) & set(tabled)):
        if listed[repo] != tabled[repo]:
            bad.append(f"{repo}: class {listed[repo]} in the map's list, {tabled[repo]} in the table")
    return bad


def check_where(rows: list[dict], fleet_root: Path) -> list[str]:
    bad, seen = [], {}
    for r in rows:
        if r["read"] == NONE:
            continue
        if r["repo"] not in seen:
            seen[r["repo"]] = find_repo(r["repo"], fleet_root)
            if seen[r["repo"]] is None:
                bad.append(f"{r['repo']}: no working copy under {fleet_root}")
        repo = seen[r["repo"]]
        if repo is None:
            continue
        rel, _, n = r["where"].rpartition(":")
        path = repo / rel
        if not path.is_file():
            bad.append(f"{r['repo']}: {r['where']} (for {r['read']}): no such file")
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        bare = r["read"].split(".")[1]
        if int(n) > len(lines) or not re.search(r"\b%s\b" % re.escape(bare), lines[int(n) - 1]):
            bad.append(f"{r['repo']}: {r['where']} does not name {bare} (cited for {r['read']})")
    return bad


def canon_keys(text: str) -> list[tuple[str, str]]:
    """(repo, key) for every key the map's canon-keys table lists."""
    out = []
    for line in _section(text, "Canon keys read").split("\n"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].startswith("`"):
            out += [(cells[0].strip("`"), k) for k in re.findall(r"`([\w.]+)`", cells[1])]
    return out


def check_canon(keys: list[tuple[str, str]], canon: dict) -> list[str]:
    bad = []
    for repo, key in keys:
        node = canon
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            bad.append(f"{repo}: canon key {key} is not in canonical_values.json")
    if not keys:
        bad.append("the map's '## Canon keys read' lists no key")
    return bad


BREAK_HEADER = "| Repo | Read | Field | Broken by | U12 repoint |"


def parse_breaks(text: str) -> tuple[list[dict], list[str]]:
    """The break list's entries, and the failures parsing them."""
    lines = _section(text, "The table").split("\n")
    if BREAK_HEADER not in lines:
        return [], [f"the read map's table section has no break list with the header {BREAK_HEADER!r}"]
    out, bad = [], []
    for line in lines[lines.index(BREAK_HEADER) + 2:]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 5 or not all(cells):
            bad.append(f"break-list row needs five filled cells: {line!r}")
            continue
        out.append(dict(repo=cells[0], read=cells[1], field=cells[2], by=cells[3], repoint=cells[4]))
    return out, bad


def check_warehouse(rows: list[dict], breaks: list[dict], catalog: dict[tuple[str, str], set[str]]) -> list[str]:
    """Each read and field against the instance's catalog, (schema, table) -> columns; the break list both ways."""
    listed = {(b["repo"], b["read"], b["field"]) for b in breaks}
    broken, bad = set(), []
    for r in rows:
        if r["read"] == NONE:
            continue
        cols = catalog.get(tuple(r["read"].split(".")))
        if cols is None:
            broken.add((r["repo"], r["read"], NONE))
            if (r["repo"], r["read"], NONE) not in listed:
                bad.append(f"{r['repo']}: {r['read']} is not in the instance and not on the break list")
            continue
        for f in r["fields"]:
            if f not in cols:
                broken.add((r["repo"], r["read"], f))
                if (r["repo"], r["read"], f) not in listed:
                    bad.append(f"{r['repo']}: {r['read']}.{f} is not in the instance and not on the break list")
    for b in sorted(listed - broken):
        bad.append(f"break list names {b[0]}: {b[1]} field {b[2]}, which the instance does not break")
    return bad


def load_catalog() -> dict[tuple[str, str], set[str]]:
    """The harness instance's columns. tests/harness.py supplies the values and runs prod_guard first."""
    sys.path.insert(0, str(ROOT / "tests"))
    import harness
    import psycopg2

    vals = harness.harness_values()
    harness.guard(vals)
    conn = psycopg2.connect(harness.dsn(vals), connect_timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT table_schema, table_name, column_name FROM information_schema.columns")
            out: dict[tuple[str, str], set[str]] = {}
            for s, t, c in cur.fetchall():
                out.setdefault((s, t), set()).add(c)
    finally:
        conn.close()
    return out


def check(read_map: Path, fleet_root: Path, canon_path: Path,
          catalog: dict[tuple[str, str], set[str]] | None = None) -> list[str]:
    text = read_map.read_text(encoding="utf-8")
    rows, bad = parse_table(text)
    bad += check_classes(rows, parse_list(text))
    bad += check_where(rows, fleet_root)
    bad += check_canon(canon_keys(text), json.loads(canon_path.read_text(encoding="utf-8")))
    if catalog is not None:
        breaks, bad_breaks = parse_breaks(text)
        bad += bad_breaks + check_warehouse(rows, breaks, catalog)
    return bad


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--read-map", type=Path, default=READ_MAP)
    p.add_argument("--fleet-root", type=Path, default=FLEET_ROOT)
    p.add_argument("--canon", type=Path, default=CANON)
    p.add_argument("--warehouse", action="store_true", help="also resolve every read in the harness instance")
    args = p.parse_args(argv)
    for path in (args.read_map, args.canon):
        if not path.is_file():
            print(f"not found: {path}", file=sys.stderr)
            return 2
    catalog = load_catalog() if args.warehouse else None
    failures = check(args.read_map, args.fleet_root, args.canon, catalog)
    arms = "table, classes, file:line, canon keys"
    arms += ", warehouse (harness instance)" if args.warehouse else "; warehouse NOT checked (pass --warehouse)"
    print(f"read map: {args.read_map}\narms run: {arms}; page population not built")
    print(f"{len(failures)} finding(s)")
    for f in failures:
        print(f"  FAIL {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
