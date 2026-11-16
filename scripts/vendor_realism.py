"""Vendor the realism bundle from a spec checkout at a named commit (plans U5, U15).

    python scripts/vendor_realism.py --spec <spec checkout> --commit <sha>

The whole-bundle procedure (U15): every re-vendor after it, U9's step 0 and U11's
A1.11 record among them, runs this one procedure, so the MANIFEST always names
one spec commit for every file.

The spec checkout must be clean and at that commit. The spec gate
(scripts/check_anchors.py) runs there, in this process, and a commit whose gate
reports any blocking finding is refused: a CLEAN spec gate at the vendored
commit is the precondition of vendoring, so the platform never re-implements a
rule the spec gate already blocks on. Then the spec gate's own `--export` writes
outputs.json there; it refuses on its own unless the gate is clean and the tree
matches the commit.

Copies into vendor/realism/:
- anchors.yml, anchor_enums.yml: the registry and its enums, never edited here;
- check_anchors.py: the spec gate itself, so the coverage gate computes a
  first-order row's fingerprint and reads a row's printed figures by the spec
  gate's own functions, and the loader keys its memo and decodes outputs.json by
  them, never a copy that can drift (platform DECISIONS 2026-11-15);
- group8_dtc.py, group9_ledger.py, group10_floors.py, group11_compliance.py:
  the four generators, byte copies; at generation time they are platform code;
- outputs.json: every entry function's return, as the spec gate exported it;
- unit_status.json: derived from the regen plan's `**Status (date):**` line per
  unit: its date and whether it reads DONE. Only that, never the plan's prose:
  seed_all.AWAITING_WRITER's test reads whether a table's writer unit is DONE;
- MANIFEST.json: the spec commit, a SHA-256 per file, the memo key (the spec
  gate's cache key over the four generators), the pinned trial's index and
  digest, and the spec gate's result per check (name, level, finding count).

Before anything is installed, the slow recompute runs on the staged copies in a
fresh process: groups 8 and 9's outputs() recomputed equal outputs.json exactly;
groups 10 and 11's, given the memo's solved factor and never solving it, equal it
too; and a fresh solve returns the memo's factor. A mismatch refuses the
re-vendor. A re-vendor prints every file whose hash moved. A dev-time step whose
output is committed, like scripts/refresh_canonical.py; never a CI step, and
generation/seed_all.py never runs it.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor" / "realism"
sys.path.insert(0, str(ROOT / "generation"))
import realism_bundle  # noqa: E402  (the memo key's and the trial digest's one definition)

#: published name -> path in the spec repo
BUNDLE = {"anchors.yml": "reference/anchors.yml",
          "anchor_enums.yml": "reference/anchor_enums.yml",
          "check_anchors.py": "scripts/check_anchors.py",
          "group8_dtc.py": "scripts/group8_dtc.py",
          "group9_ledger.py": "scripts/group9_ledger.py",
          "group10_floors.py": "scripts/group10_floors.py",
          "group11_compliance.py": "scripts/group11_compliance.py"}
OUTPUTS = realism_bundle.OUTPUTS
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


def run_spec_export(spec: Path) -> bytes:
    """outputs.json as the spec gate's `--export` writes it at `spec`, in a fresh process, outside the spec tree."""
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, "scripts/check_anchors.py", "--export", tmp], cwd=spec,
                           capture_output=True, text=True)
        path = Path(tmp) / OUTPUTS
        if r.returncode != 0 or not path.is_file():
            raise VendorRefused(f"the spec gate's --export refused: {(r.stdout + r.stderr).strip()[-400:]}")
        return path.read_bytes()


def run_recompute(stage: Path) -> list[str]:
    """The slow recompute on the staged copies, in a fresh process; the mismatches it names (none when it holds)."""
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--recompute", str(stage)],
                       capture_output=True, text=True)
    bad = [line[len("MISMATCH "):] for line in r.stdout.splitlines() if line.startswith("MISMATCH ")]
    if r.returncode != 0 and not bad:
        bad = [f"the recompute did not run: {(r.stdout + r.stderr).strip()[-600:]}"]
    return bad


def recompute(stage: Path) -> list[str]:
    """Run in its own process (`--recompute`), the staged generators first on the path."""
    stage = Path(stage).resolve()
    gate = realism_bundle.gate_module(stage)
    sys.path.insert(0, str(stage))
    import group8_dtc as D
    import group9_ledger as G
    import group10_floors as F
    import group11_compliance as L
    exported = json.loads((stage / OUTPUTS).read_text(encoding="utf-8"))["generators"]
    as_json = lambda o: json.loads(json.dumps(o, default=gate._encode))  # noqa: E731
    bad = []
    for name, fn in (("group8_dtc", D.outputs), ("group9_ledger", G.outputs)):
        if as_json(fn()) != exported[name]:
            bad.append(f"{name}.outputs() recomputed does not equal outputs.json")
    acct = json.loads(json.dumps(exported["group10_floors"]), object_hook=gate._decode)["printed"]["A11.27"][
        gate.FACTOR]
    solve = L.solve_account_factor

    def refused(*a, **kw):
        raise AssertionError("an entry function given the memo's factor solved it")
    L.solve_account_factor = refused
    try:
        if as_json(F.outputs(acct)) != exported["group10_floors"]:
            bad.append("group10_floors.outputs(acct) recomputed does not equal outputs.json")
        if as_json(L.outputs(acct)) != exported["group11_compliance"]:
            bad.append("group11_compliance.outputs(acct) recomputed does not equal outputs.json")
    finally:
        L.solve_account_factor = solve
    F._SOLVED.clear()
    fresh = L.solve_account_factor()
    if fresh != acct:
        bad.append(f"a fresh solve on the vendored copies returns {fresh!r}, the memo holds {acct!r}")
    return bad


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


def vendor(spec: Path, commit: str, out: Path = VENDOR, gate=run_spec_gate, export=run_spec_export,
           slow=run_recompute) -> dict:
    head, dirty = spec_state(spec)
    if dirty:
        raise VendorRefused(f"the spec checkout is not clean: {', '.join(dirty[:5])}")
    if head != commit and not head.startswith(commit):
        raise VendorRefused(f"the spec checkout is at {head[:12]}, not {commit}")
    checks = gate(spec)
    if spec_state(spec) != (head, []):
        raise VendorRefused(f"the spec gate run changed the spec tree at {head[:12]}")
    blocking = [f"{c['name']} ({c['findings']})" for c in checks if c["level"] == "BLOCK" and c["findings"]]
    if blocking:
        raise VendorRefused(f"the spec gate is not CLEAN at {head[:12]}: {'; '.join(blocking)}")
    if not (spec / PLAN).is_file():
        raise VendorRefused(f"the spec checkout has no {PLAN}")
    exported = export(spec)
    if spec_state(spec) != (head, []):
        raise VendorRefused(f"the spec gate's export changed the spec tree at {head[:12]}")
    raw = json.loads(exported.decode("utf-8"))
    if raw.get("commit") != head:
        raise VendorRefused(f"outputs.json was exported at {raw.get('commit')}, not {head[:12]}")
    status = (json.dumps(unit_status((spec / PLAN).read_text(encoding="utf-8")), indent=1, sort_keys=True)
              + "\n").encode("utf-8")
    old_path = out / "MANIFEST.json"
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        for name, rel in BUNDLE.items():
            (stage / name).write_bytes((spec / rel).read_bytes())
        (stage / OUTPUTS).write_bytes(exported)
        (stage / UNIT_STATUS).write_bytes(status)
        names = list(BUNDLE) + [OUTPUTS, UNIT_STATUS]
        new = manifest(head, {n: stage / n for n in names}, checks)
        new["memo_sha256"] = realism_bundle.memo_key(stage, realism_bundle.gate_module(stage))
        new["pinned_trial"] = {"index": realism_bundle.PINNED_TRIAL,
                               "digest": realism_bundle.trial_digest(raw["generators"]["group11_compliance"]["trial"])}
        mismatches = slow(stage)
        if mismatches:
            raise VendorRefused("the recompute on the vendored copies does not hold: " + "; ".join(mismatches))
        old = json.loads(old_path.read_text(encoding="utf-8")) if old_path.exists() else None
        out.mkdir(parents=True, exist_ok=True)
        for n in names:
            shutil.copyfile(stage / n, out / n)
    old_path.write_text(json.dumps(new, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    new["moved"] = moved(old, new)
    return new


def main(argv: list[str]) -> int:
    if argv[:1] == ["--recompute"]:
        bad = recompute(Path(argv[1]))
        for b in bad:
            print(f"MISMATCH {b}")
        print("recompute: " + ("holds" if not bad else f"{len(bad)} mismatch(es)"))
        return 1 if bad else 0
    p = argparse.ArgumentParser()
    p.add_argument("--spec", required=True, type=Path)
    p.add_argument("--commit", required=True)
    args = p.parse_args(argv)
    try:
        m = vendor(args.spec.resolve(), args.commit)
    except VendorRefused as e:
        print(f"vendor refused: {e}", file=sys.stderr)
        return 1
    print(f"vendored spec {m['spec_commit'][:12]}: spec gate CLEAN, {len(m['spec_gate']['checks'])} checks recorded; "
          f"the recompute held; memo key {m['memo_sha256'][:20]}, trial {m['pinned_trial']['index']}")
    print("moved: " + (", ".join(m["moved"]) if m["moved"] else "nothing"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
