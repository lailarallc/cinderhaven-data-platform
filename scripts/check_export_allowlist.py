"""Egress path 2: every warehouse extract names its schemas from an allowlist (plan U4).

A `SELECT *` across schemas, run as a role that can read truth, ships truth to
GitHub. The role is the control underneath; this check makes the query's own
schema list explicit and enforced.

Population: every class B entry in the spec repo's consumer read map
(docs/consumers/CONSUMER-READ-MAP.md), by the extract scripts the entry names,
plus this repo's scripts/export_revenue_truth.py. The map is the record, so the
population is parsed from it, never retyped. An entry with no extract script,
a script that cannot be found, or a repo with no working copy FAILS; nothing
is skipped.

Each script fails on: a schema-qualified name outside ALLOWED_SCHEMAS (truth
always outside), the truth gate's needle, or enumerating the catalog
(pg_tables, information_schema.tables, pg_class), which copies whatever
schemas exist instead of a named list. Per repo it records whether the
extract's output is committed.

    python scripts/check_export_allowlist.py [--read-map PATH] [--fleet-root DIR]

It reads code only, never a credential. It reports today's state; findings are
U12's and U19's to fix in the consumer repos.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLEET_ROOT = Path.home() / "projects"
READ_MAP = FLEET_ROOT / "active" / "cinderhaven-data-realism" / "docs" / "consumers" / "CONSUMER-READ-MAP.md"

#: The platform's own readable schemas. A repo's own schemas (edi_* for
#: edi-reconciliation-tool) are added per repo below.
ALLOWED_SCHEMAS = {"raw", "costing", "copack", "voidfinder", "public_staging", "public_intermediate", "public_marts"}
OWN_SCHEMAS = {"edi-reconciliation-tool": {"edi_raw", "edi_staging", "edi_marts"}}
#: The warehouse's schemas, by name: a pattern like public_\w+ matches Python attributes.
WAREHOUSE_SCHEMAS = ("raw", "costing", "copack", "voidfinder", "truth", "public_staging", "public_intermediate",
                     "public_marts", "edi_raw", "edi_staging", "edi_marts")
SCHEMA_REF = re.compile(r"\b(" + "|".join(WAREHOUSE_SCHEMAS) + r")\.([a-z_]\w*)", re.IGNORECASE)
#: Only a literal identifier list counts; a search_path built from a variable is the role's to control.
SEARCH_PATH = re.compile(r"search_path\s*(?:=|\bto\b)\s*['\"]?([\w$]+(?:\s*,\s*[\w$]+)*)", re.IGNORECASE)
CATALOG = re.compile(r"\b(pg_tables|information_schema\.tables|pg_class)\b", re.IGNORECASE)
SCRIPT_SUFFIXES = (".py", ".R", ".r", ".sql", ".sh", ".ipynb", ".qmd")
OUTPUT_SUFFIXES = (".json", ".csv", ".db", ".rds", ".parquet", ".sqlite")
SELF = "scripts/export_revenue_truth.py"


def class_b_entries(read_map: Path) -> dict[str, list[str]]:
    """{repo: backticked paths in its entry} for every entry under '### B'."""
    text = read_map.read_text(encoding="utf-8")
    start, end = text.index("### B"), text.index("### C")
    entries: dict[str, list[str]] = {}
    for block in re.split(r"\n(?=\*\*`)", text[start:end]):
        m = re.match(r"\*\*`([\w.-]+)`\*\*", block)
        if m:
            entries[m.group(1)] = re.findall(r"`([^`]+)`", block)
    return entries


def _paths(refs: list[str], suffixes) -> list[str]:
    out = []
    for r in refs:
        r = re.sub(r":[\d,\-]+$", "", r.strip())
        if r.endswith(tuple(suffixes)) and " " not in r:
            out.append(r)
    return sorted(set(out))


def find_repo(name: str, fleet_root: Path) -> Path | None:
    hits = [p for p in fleet_root.glob(f"*/{name}") if (p / ".git").exists()]
    return hits[0] if hits else None


def resolve(repo: Path, ref: str) -> list[Path]:
    """The tracked files the reference names: its path, or, for a bare name, every tracked file so named."""
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True).stdout.splitlines()
    if any(c in ref for c in "*?["):
        return sorted(repo / t for t in tracked if fnmatch.fnmatch(t, ref) or fnmatch.fnmatch(t, "*/" + ref))
    return sorted(repo / t for t in tracked if t == ref or t.endswith("/" + ref) or Path(t).name == ref)


def scan_text(text: str, allowed: set[str]) -> list[str]:
    hits = []
    for m in SCHEMA_REF.finditer(text):
        schema = m.group(1).lower()
        if schema not in allowed:
            hits.append(f"names {m.group(0)!r} (schema {schema!r} not in the allowlist)")
    for m in SEARCH_PATH.finditer(text):
        for s in re.split(r"\s*,\s*", m.group(1).strip()):
            s = s.strip("'\"").lower()
            if s and s not in allowed and s not in {"public", "$user", "pg_catalog"}:
                hits.append(f"search_path names {s!r}")
    for m in CATALOG.finditer(text):
        hits.append(f"enumerates the catalog ({m.group(1)}): name the tables instead")
    return sorted(set(hits))


def assert_allowlisted(path: Path, allowed: set[str] = ALLOWED_SCHEMAS) -> None:
    """Raise SystemExit if `path` names a schema outside `allowed`. Export scripts
    call this on themselves before exporting."""
    hits = scan_text(path.read_text(encoding="utf-8"), allowed)
    if hits:
        raise SystemExit(f"{path.name} is outside its schema allowlist; not exporting:\n  " + "\n  ".join(hits))


def committed(repo: Path, outputs: list[str]) -> list[str]:
    tracked = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True).stdout.splitlines()
    out = []
    for o in outputs:
        pat = re.escape(o).replace(r"\{", "(").replace(r"\}", ")").replace(",", "|").replace(r"\*", ".*")
        out += [t for t in tracked if re.search(pat + "$", t)]
    return sorted(set(out))


def check(read_map: Path, fleet_root: Path) -> tuple[list[str], list[str]]:
    failures, notes = [], []
    entries = class_b_entries(read_map)
    if not entries:
        failures.append(f"{read_map}: no class B entries parsed")
    for repo_name, refs in sorted(entries.items()):
        scripts = _paths(refs, SCRIPT_SUFFIXES)
        if not scripts:
            failures.append(f"{repo_name}: its read-map entry names no extract script")
            continue
        repo = find_repo(repo_name, fleet_root)
        if repo is None:
            failures.append(f"{repo_name}: no working copy under {fleet_root}")
            continue
        allowed = ALLOWED_SCHEMAS | OWN_SCHEMAS.get(repo_name, set())
        for ref in scripts:
            files = resolve(repo, ref)
            if not files:
                failures.append(f"{repo_name}: {ref} named by the read map, not found")
            for f in files:
                try:
                    hits = scan_text(f.read_text(encoding="utf-8"), allowed)
                except UnicodeDecodeError:
                    failures.append(f"{repo_name}: {f.relative_to(repo)} unreadable")
                    continue
                failures += [f"{repo_name}: {f.relative_to(repo).as_posix()}: {h}" for h in hits]
        outs = committed(repo, _paths(refs, OUTPUT_SUFFIXES))
        notes.append(f"{repo_name}: extract output committed: {', '.join(outs) if outs else 'none found'}")
    own = ROOT / SELF
    failures += [f"cinderhaven-data-platform: {SELF}: {h}" for h in scan_text(own.read_text(encoding="utf-8"),
                                                                              ALLOWED_SCHEMAS)]
    notes.append("cinderhaven-data-platform: extract output committed: none (output/ is gitignored)")
    return failures, notes


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--read-map", type=Path, default=READ_MAP)
    p.add_argument("--fleet-root", type=Path, default=FLEET_ROOT)
    args = p.parse_args(argv)
    if not args.read_map.is_file():
        print(f"read map not found: {args.read_map}", file=sys.stderr)
        return 2
    failures, notes = check(args.read_map, args.fleet_root)
    for n in notes:
        print(n)
    print(f"\n{len(failures)} finding(s)")
    for f in failures:
        print(f"  FAIL {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
