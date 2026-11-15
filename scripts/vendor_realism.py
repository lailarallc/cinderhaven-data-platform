"""Vendor the realism registry from a spec checkout at a named commit (plan U5).

    python scripts/vendor_realism.py --spec <spec checkout> --commit <sha>

The spec checkout must be clean and at that commit. The spec gate
(scripts/check_anchors.py) runs there, in this process, and a commit whose gate
reports any blocking finding is refused: a CLEAN spec gate at the vendored
commit is the precondition of vendoring, so the platform never re-implements a
rule the spec gate already blocks on.

Copies into vendor/realism/:
- anchors.yml, anchor_enums.yml: the registry and its enums, never edited here;
- check_anchors.py: the spec gate itself, so the coverage gate computes a
  first-order row's fingerprint and reads a row's printed figures by the spec
  gate's own functions, not a copy that can drift (platform DECISIONS 2026-11-15);
- unit_status.json: derived from the regen plan's `**Status (date):**` line per
  unit: its date and whether it reads DONE. Only that, never the plan's prose:
  seed_all.AWAITING_WRITER's test reads whether a table's writer unit is DONE;
- MANIFEST.json: the spec commit, a SHA-256 per file, and the spec gate's
  result per check (name, level, finding count), ok checks included.

A re-vendor prints every file whose hash moved. A dev-time step whose output is
committed, like scripts/refresh_canonical.py; never a CI step.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "realism"
#: published name -> path in the spec repo
BUNDLE = {"anchors.yml": "reference/anchors.yml",
          "anchor_enums.yml": "reference/anchor_enums.yml",
          "check_anchors.py": "scripts/check_anchors.py"}
#: the regen plan, read for unit_status.json only
PLAN = "docs/plans/2026-09-02-001-feat-cinderhaven-realism-regen-plan.md"
UNIT_STATUS = "unit_status.json"
_UNIT = re.compile(r"^### (U\d+)\.", re.M)
_STATUS = re.compile(r"^\*\*Status \((\d{4}-\d{2}-\d{2})[^)]*\):\*\*\s*(\S+)", re.M)


def unit_status(plan: str) -> dict:
    """{unit: {"date", "done"}} from each unit's first Status line. A unit is DONE when its status
    starts with DONE; "Done in substance" and "Code complete" are not."""
    out: dict = {}
    heads = list(_UNIT.finditer(plan))
    for i, h in enumerate(heads):
        body = plan[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(plan)]
        s = _STATUS.search(body)
        if s:
            out[h.group(1)] = {"date": s.group(1), "done": s.group(2).rstrip(".,;:") == "DONE"}
    if not out:
        raise VendorRefused(f"{PLAN} gave no unit status")
    return out


class VendorRefused(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(spec: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=spec, capture_output=True, text=True, check=True).stdout.strip()


def spec_state(spec: Path) -> tuple[str, list[str]]:
    """(HEAD, porcelain lines) of the spec checkout."""
    return _git(spec, "rev-parse", "HEAD"), _git(spec, "status", "--porcelain").splitlines()


def run_spec_gate(spec: Path) -> list[dict]:
    """Every check the spec gate ran at `spec`, as {name, level, findings}, in its order."""
    mod_spec = importlib.util.spec_from_file_location("spec_check_anchors", spec / "scripts" / "check_anchors.py")
    gate = importlib.util.module_from_spec(mod_spec)
    mod_spec.loader.exec_module(gate)
    import yaml
    enums = yaml.safe_load(gate.rd(gate.ENUMS))
    rows = yaml.safe_load(gate.rd(gate.REGISTRY))
    index = {r["anchor_id"]: r for r in rows}
    try:
        exceptions = yaml.safe_load(gate.rd(gate.EXCEPTIONS))
    except OSError:
        exceptions = {}
    del gate.RESULTS[:]
    gate._run_all(rows, index, enums, exceptions)
    return [{"name": name, "level": level, "findings": len(messages)} for level, name, messages in gate.RESULTS]


def manifest(commit: str, files: dict[str, Path], checks: list[dict]) -> dict:
    blocking = sum(c["findings"] for c in checks if c["level"] == "BLOCK")
    return {"spec_commit": commit,
            "files": {name: sha256(p) for name, p in sorted(files.items())},
            "spec_gate": {"clean": blocking == 0, "blocking_findings": blocking, "checks": checks}}


def moved(old: dict | None, new: dict) -> list[str]:
    """Files whose hash differs between two MANIFESTs, added and removed files included."""
    before = (old or {}).get("files", {})
    after = new["files"]
    return sorted(n for n in before.keys() | after.keys() if before.get(n) != after.get(n))


def vendor(spec: Path, commit: str, out: Path = VENDOR, gate=run_spec_gate) -> dict:
    head, dirty = spec_state(spec)
    if dirty:
        raise VendorRefused(f"the spec checkout is not clean: {', '.join(dirty[:5])}")
    if head != commit and not head.startswith(commit):
        raise VendorRefused(f"the spec checkout is at {head[:12]}, not {commit}")
    checks = gate(spec)
    if spec_state(spec) != (head, []):
        raise VendorRefused(f"the spec gate run changed the spec tree at {head[:12]}")
    sources = {name: spec / rel for name, rel in BUNDLE.items()}
    if not (spec / PLAN).is_file():
        raise VendorRefused(f"the spec checkout has no {PLAN}")
    status = (json.dumps(unit_status((spec / PLAN).read_text(encoding="utf-8")), indent=1, sort_keys=True)
              + "\n").encode("utf-8")
    new = manifest(head, sources, checks)
    new["files"][UNIT_STATUS] = hashlib.sha256(status).hexdigest()
    new["files"] = dict(sorted(new["files"].items()))
    if not new["spec_gate"]["clean"]:
        bad = [f"{c['name']} ({c['findings']})" for c in checks if c["level"] == "BLOCK" and c["findings"]]
        raise VendorRefused(f"the spec gate is not CLEAN at {head[:12]}: {'; '.join(bad)}")
    old_path = out / "MANIFEST.json"
    old = json.loads(old_path.read_text(encoding="utf-8")) if old_path.exists() else None
    out.mkdir(parents=True, exist_ok=True)
    for name, src in sources.items():
        (out / name).write_bytes(src.read_bytes())
    (out / UNIT_STATUS).write_bytes(status)
    old_path.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    new["moved"] = moved(old, new)
    return new


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--commit", required=True)
    args = p.parse_args(argv)
    try:
        m = vendor(args.spec.resolve(), args.commit)
    except VendorRefused as e:
        print(f"vendor refused: {e}", file=sys.stderr)
        return 1
    print(f"vendored spec {m['spec_commit'][:12]}: spec gate CLEAN, {len(m['spec_gate']['checks'])} checks recorded")
    print("moved: " + (", ".join(m["moved"]) if m["moved"] else "nothing"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
