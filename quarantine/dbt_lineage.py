"""dbt's two truth checks (plan U4), run after `dbt compile`.

1. Lineage: walk every node's depends_on.nodes in target/manifest.json and fail
   any node that TRANSITIVELY depends on a source in the `truth` source,
   wherever it materializes. A model in public_marts can source('truth', ...),
   aggregate it and land under an innocuous name; a schema-location test ships
   that green. Every resource type is walked, not only models.
2. Compiled SQL: scan target/compiled/**/*.sql with the gate's needle. dbt only
   records edges from parsed ref()/source(); a literal truth table name (or a
   Jinja-built one) compiles with no edge, so the walk cannot see it.

A third, weaker check: no node materializes into a schema named for truth.

Exemptions are explicit .sql file paths (list 3): mart_counterfactual only.

    python quarantine/dbt_lineage.py cinderhaven/target
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from .text_scan import scan_text
except ImportError:
    from text_scan import scan_text

#: List 3. Named now, created in Phase 4 (N38), in its own schema with a narrower
#: grant than public_marts. Changing this list needs a DECISIONS entry.
DBT_EXEMPT = ("cinderhaven/models/counterfactual/mart_counterfactual.sql",)


class LineageViolation(AssertionError):
    pass


def _exempt(path: str, exempt) -> bool:
    path = path.replace("\\", "/")
    return any(path == e or path.endswith("/" + e) or e.endswith("/" + path) for e in exempt)


def truth_descendants(manifest: dict) -> dict[str, str]:
    """{node unique_id: the truth source it reaches}, for every node of any type."""
    truth_sources = {uid for uid, s in manifest.get("sources", {}).items() if s.get("source_name") == "truth"}
    nodes = manifest.get("nodes", {})
    memo: dict[str, str | None] = {}

    def reach(uid: str, seen: frozenset) -> str | None:
        if uid in truth_sources:
            return uid
        if uid in memo:
            return memo[uid]
        if uid in seen:
            return None
        hit = None
        for dep in nodes.get(uid, {}).get("depends_on", {}).get("nodes", []):
            hit = reach(dep, seen | {uid})
            if hit:
                break
        memo[uid] = hit
        return hit

    return {uid: src for uid in nodes if (src := reach(uid, frozenset()))}


def check_lineage(manifest: dict, exempt=DBT_EXEMPT) -> None:
    nodes = manifest.get("nodes", {})
    if not nodes:
        raise ValueError("manifest has no nodes: nothing to audit")
    bad = {uid: src for uid, src in truth_descendants(manifest).items()
           if not _exempt(nodes[uid].get("original_file_path", ""), exempt)}
    bad_schema = [uid for uid, n in nodes.items() if "truth" in str(n.get("schema", "")).lower()
                  and not _exempt(n.get("original_file_path", ""), exempt)]
    lines = [f"  {uid} ({nodes[uid].get('resource_type')}) depends on {src}" for uid, src in sorted(bad.items())]
    lines += [f"  {uid} materializes into schema {nodes[uid]['schema']!r}" for uid in bad_schema]
    if lines:
        raise LineageViolation("dbt nodes reach quarantined ground truth:\n" + "\n".join(lines))


def check_compiled(compiled_dir: Path, exempt=DBT_EXEMPT) -> None:
    files = sorted(Path(compiled_dir).rglob("*.sql"))
    if not files:
        raise ValueError(f"no compiled SQL under {compiled_dir}: run dbt compile first")
    report = {}
    for f in files:
        rel = f.relative_to(compiled_dir).as_posix()
        # target/compiled/<project>/models/x.sql mirrors <project>/models/x.sql
        if _exempt(rel, exempt):
            continue
        hits = scan_text(f.read_text(encoding="utf-8"))
        if hits:
            report[rel] = hits
    if report:
        raise LineageViolation("compiled dbt SQL names quarantined ground truth:\n" + "\n".join(
            f"  {rel}: {'; '.join(h)}" for rel, h in report.items()))


def main(argv: list[str]) -> int:
    target = Path(argv[0] if argv else "cinderhaven/target")
    try:
        check_lineage(json.loads((target / "manifest.json").read_text(encoding="utf-8")))
        check_compiled(target / "compiled")
    except (LineageViolation, ValueError) as e:
        print(e, file=sys.stderr)
        return 1
    print("dbt lineage and compiled SQL: no node reaches truth")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
