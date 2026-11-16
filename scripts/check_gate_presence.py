"""The fleet check (plan U19): every named consumer carries what the platform's refresh ships, and writes no
platform schema.

The named list is the spec read map's "## The table" (repo, class, status), read from the spec checkout through
check_read_map.py's parser; the platform keeps no copy of the list and this check states no count of it. A repo the
table marks `retired` is skipped by name. `--classes` filters by the table's class column (U12 runs A, B and D; U22
runs the whole list).

Per repo, each a failure when it does not hold:
  1. A working copy exists under the fleet root.
  2. Every artifact in refresh_canonical.py's ARTIFACTS is present at its destination and identical to the
     platform's copy, line endings normalized (a Windows checkout's CRLF is not drift). The vendored
     canonical_values.json is the currency check: no consumer pins a SHA.
  3. .github/workflows/canonical-drift.yml is present.
  4. No tracked script holds DDL or DML against a platform schema (raw, costing, truth, copack, voidfinder, public,
     public_*), schema-qualified, or unqualified in a file whose literal search_path names one. The exceptions are
     named in EXCEPTIONS, never inferred.
  5. Its ledger of typed, unkeyed figures (reference/typed_unkeyed.tsv) holds exactly as many rows as its ceiling
     in the platform's reference/typed_unkeyed_ceilings.yml (owner, 2026-11-15). More fails; fewer fails too, until
     the ceiling is lowered to match, so the count only falls. A repo with no ceiling has a ceiling of 0.

Not checked yet: the truth-gate CI job, which U12 or U22 installs.

    python scripts/check_gate_presence.py [--read-map PATH] [--fleet-root DIR] [--classes ABCD]

It reads working copies only; it connects to nothing.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from check_export_allowlist import FLEET_ROOT, READ_MAP, find_repo
from check_read_map import parse_table
from refresh_canonical import ARTIFACTS

ROOT = Path(__file__).resolve().parent.parent
DRIFT_WORKFLOW = ".github/workflows/canonical-drift.yml"
LEDGER = "reference/typed_unkeyed.tsv"
CEILINGS = Path("reference") / "typed_unkeyed_ceilings.yml"
PLATFORM_SCHEMAS = r"(?:raw|costing|truth|copack|voidfinder|public|public_\w+)"
WRITE_VERB = r"(?:CREATE\s+(?:OR\s+REPLACE\s+)?(?:TEMP\w*\s+)?(?:TABLE|VIEW|SCHEMA|INDEX[^;]*?\bON)|DROP\s+(?:TABLE|VIEW|SCHEMA)" \
             r"|ALTER\s+TABLE|TRUNCATE(?:\s+TABLE)?|INSERT\s+INTO|UPDATE|DELETE\s+FROM|COPY)"
IFX = r"(?:\s+IF\s+(?:NOT\s+)?EXISTS)?(?:\s+ONLY)?\s+[\"`]?"
QUALIFIED = re.compile(WRITE_VERB + IFX + r"(" + PLATFORM_SCHEMAS + r")[\"`]?\.[\"`]?(\w+)", re.I)
UNQUALIFIED = re.compile(WRITE_VERB + IFX + r"([a-z_]\w*)\b(?!\s*\.)", re.I)
SEARCH_PATH = re.compile(r"search_path\s*(?:=|\bto\b)\s*['\"]?([\w$]+(?:\s*,\s*[\w$]+)*)", re.I)
SUFFIXES = (".py", ".R", ".r", ".sql", ".sh", ".js", ".mjs", ".ts")
#: Writes into a platform schema that U19 names, by repo and file. Each says why.
EXCEPTIONS = {
    # Fill copack's seeded tables until U12 deletes them (plan U19, "the fleet check").
    ("production-demand-forecast", "db/seed_copack.py"),
    ("production-demand-forecast", "db/schema_copack.sql"),
    # Its own database, recall_blast_radius, not the platform's (read map, writers; plan U19).
    ("recall-blast-radius", "data/schema/genealogy_ddl.sql"),
    ("recall-blast-radius", "pipeline/seed.py"),
    ("recall-blast-radius", "pipeline/assets.py"),
}
#: Words after a write verb that are SQL, not a table name.
NOT_A_NAME = {"select", "set", "values", "with", "from", "where", "as", "table", "on", "only", "to", "stdin", "stdout",
              "if", "not", "exists"}
#: A file that opens SQLite writes its unqualified tables there; only its qualified writes count.
SQLITE = re.compile(r"\bsqlite3?\b|RSQLite", re.I)
DBT_SCHEMA = re.compile(r"^\s*\+?schema:\s*['\"]?(\w+)", re.M)


def named_list(read_map: Path, classes: str) -> tuple[list[tuple[str, str]], list[str], list[str]]:
    """(repo, class) in scope, the repos skipped as retired, and the table's parse failures."""
    rows, bad = parse_table(read_map.read_text(encoding="utf-8"))
    seen, keep, retired = set(), [], []
    for r in rows:
        if r["repo"] in seen:
            continue
        seen.add(r["repo"])
        if r["status"] == "retired":
            retired.append(r["repo"])
        elif r["cls"] in classes:
            keep.append((r["repo"], r["cls"]))
    return keep, retired, bad


def _norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def check_artifacts(name: str, repo: Path, platform: Path) -> list[str]:
    bad = []
    for src_dir, fname, dest_dir in ARTIFACTS:
        ours, theirs = platform / src_dir / fname, repo / dest_dir / fname
        if not theirs.is_file():
            bad.append(f"{name}: {dest_dir}/{fname} missing")
        elif _norm(theirs.read_bytes()) != _norm(ours.read_bytes()):
            bad.append(f"{name}: {dest_dir}/{fname} differs from the platform's")
    if not (repo / DRIFT_WORKFLOW).is_file():
        bad.append(f"{name}: {DRIFT_WORKFLOW} missing")
    return bad


def tracked(repo: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True).stdout.splitlines()
    return [t for t in out if t.endswith(SUFFIXES)]


def scan_writes(text: str) -> list[tuple[int, str]]:
    """(line, schema.table) for each write into a platform schema, qualified or through a literal search_path."""
    hits = []
    for m in QUALIFIED.finditer(text):
        hits.append((text.count("\n", 0, m.start()) + 1, f"{m.group(1)}.{m.group(2)}".lower()))
    paths = [p for m in SEARCH_PATH.finditer(text) for p in re.split(r"\s*,\s*", m.group(1).lower())]
    platform = [p for p in paths if re.fullmatch(PLATFORM_SCHEMAS, p, re.I)]
    if platform and not SQLITE.search(text):
        for m in UNQUALIFIED.finditer(text):
            if m.group(1).lower() not in NOT_A_NAME:
                hits.append((text.count("\n", 0, m.start()) + 1, f"{platform[0]}.{m.group(1).lower()} (search_path)"))
    return sorted(set(hits))


def check_writes(name: str, repo: Path) -> list[str]:
    bad = []
    files = subprocess.run(["git", "-C", str(repo), "ls-files"], capture_output=True, text=True).stdout.splitlines()
    for rel in files:
        if (name, rel) in EXCEPTIONS or not (repo / rel).is_file():
            continue
        text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        if rel.endswith(SUFFIXES):
            for line, target in scan_writes(text):
                bad.append(f"{name}: {rel}:{line} writes {target}")
        elif rel.endswith("dbt_project.yml"):
            for m in DBT_SCHEMA.finditer(text):
                if re.fullmatch(PLATFORM_SCHEMAS, m.group(1), re.I):
                    line = text.count("\n", 0, m.start()) + 1
                    bad.append(f"{name}: {rel}:{line} builds dbt models into {m.group(1)}")
    return bad


def load_ceilings(platform: Path) -> dict[str, int]:
    out = {}
    for line in (platform / CEILINGS).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name, _, n = line.partition(":")
            out[name.strip()] = int(n)
    return out


def ledger_rows(path: Path) -> int:
    """Data rows: neither a `#` comment nor the header."""
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    return max(len(lines) - 1, 0)


def check_ledger(name: str, repo: Path, ceiling: int) -> list[str]:
    path = repo / LEDGER
    n = ledger_rows(path) if path.is_file() else 0
    if ceiling and not path.is_file():
        return [f"{name}: {LEDGER} missing (ceiling {ceiling})"]
    if n > ceiling:
        return [f"{name}: {LEDGER} has {n} rows, over its ceiling of {ceiling}"]
    if n < ceiling:
        return [f"{name}: {LEDGER} has {n} rows; lower its ceiling in {CEILINGS.as_posix()} from {ceiling} to {n}"]
    return []


def check(read_map: Path, fleet_root: Path, classes: str, platform: Path = ROOT) -> tuple[list[str], list[str]]:
    repos, retired, bad = named_list(read_map, classes)
    ceilings = load_ceilings(platform)
    for name, _cls in repos:
        repo = find_repo(name, fleet_root)
        if repo is None:
            bad.append(f"{name}: no working copy under {fleet_root}")
            continue
        bad += check_artifacts(name, repo, platform)
        bad += check_writes(name, repo)
        bad += check_ledger(name, repo, ceilings.get(name, 0))
    return bad, retired


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--read-map", type=Path, default=READ_MAP)
    p.add_argument("--fleet-root", type=Path, default=FLEET_ROOT)
    p.add_argument("--classes", default="ABCD")
    args = p.parse_args(argv)
    if not args.read_map.is_file():
        print(f"not found: {args.read_map}", file=sys.stderr)
        return 2
    if set(args.classes) - set("ABCD") or not args.classes:
        print(f"--classes takes letters from ABCD, not {args.classes!r}", file=sys.stderr)
        return 2
    failures, retired = check(args.read_map, args.fleet_root, args.classes)
    print(f"read map: {args.read_map}\nclasses: {args.classes}; skipped as retired: {', '.join(retired) or 'none'}")
    print("not checked: the truth-gate CI job (installed by U12 or U22)")
    print(f"{len(failures)} finding(s)")
    for f in failures:
        print(f"  FAIL {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
