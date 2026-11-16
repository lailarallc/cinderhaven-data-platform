"""The realism bundle and its one import (plan U15).

Bundle tests: the committed bundle loads at one spec commit; a one-byte change
to a vendored file fails the load and names it; a memo key that does not match
the vendored sources refuses the load rather than solving; loading and the
pinned trial's replay never solve, and the replay hashes to the digest the spec
side recorded; U4's ban rejects scan-root modules that reach the bundle.

A seeder that re-derives is a second generator, each test over an enumerated
surface (generation/*.py, the loader excepted):
1. one import: no module imports a group module or reads vendor/realism/;
2. no literal: no numeric literal equals a bundle output of three or more
   significant figures, and no list or tuple carries a bundle series of two or
   more values in order, unless its line names why (`mirror-exempt: <why>`, the
   spec gate's convention). Today's hits are an owed list, by the unit that
   rewires the seeder; it only shrinks (platform DECISIONS 2026-11-15, U15).
3. perturbation: tests/acceptance/test_generator_parity.py.
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
import textwrap
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "generation"))
import realism_bundle  # noqa: E402

from quarantine.truth_gate import TruthAccessViolation, assert_no_generator_access  # noqa: E402

VENDOR = ROOT / "vendor" / "realism"
GENERATION = ROOT / "generation"
GROUP_MODULES = ("group8_dtc", "group9_ledger", "group10_floors", "group11_compliance", "check_anchors")
EXEMPT = re.compile(r"mirror-exempt:\s*(\S.*)?$")

#: Today's literal hits, by (file, value) and (file, series), with their count and the unit that rewires that
#: seeder (U9: the catalogue, prices and doors; U10: dispersion, lifecycle, transit and lead). Only ever lower a count
#: or remove a line; a hit beyond it fails.
LITERALS_OWED = {
    ("seed_config.py", 1.05): (6, "U10"),
    ("seed_config.py", 6.49): (3, "U9"),
    ("seed_config.py", 6.99): (5, "U9"),
    ("seed_config.py", 8.99): (5, "U9"),
    ("seed_scan_data.py", 1.05): (1, "U10"),
    ("seed_shared.py", 1.05): (1, "U10"),
    ("seed_shared.py", 1.08): (1, "U10"),
}
SERIES_OWED = {
    ("seed_distributor.py", (2.0, 3.0)): (1, "U10"),
    ("seed_dtc.py", (2.0, 3.0)): (2, "U10"),
    ("seed_dtc.py", (4, 3)): (1, "U10"),
    ("seed_dtc.py", (5, 5, 5)): (1, "U10"),
    ("seed_retailer.py", (2.0, 3.0)): (2, "U10"),
    ("seed_shared.py", (1, 2, 2)): (2, "U10"),
    ("seed_shared.py", (2.0, 3.0)): (1, "U10"),
}


@pytest.fixture(scope="module")
def bundle():
    return realism_bundle.load()


# ---------------------------------------------------------------- the bundle
def test_the_committed_bundle_loads_at_one_spec_commit(bundle):
    m = bundle.manifest
    assert bundle.outputs["commit"] == m["spec_commit"]
    assert {"anchors.yml", "anchor_enums.yml", "check_anchors.py", "group8_dtc.py", "group9_ledger.py",
            "group10_floors.py", "group11_compliance.py", "outputs.json"} <= set(m["files"])
    assert m["spec_gate"]["clean"] and m["pinned_trial"]["index"] == realism_bundle.PINNED_TRIAL == 0
    for name in ("group8_dtc", "group9_ledger", "group10_floors", "group11_compliance"):
        assert Path(sys.modules[name].__file__).resolve().parent == VENDOR.resolve()


def _copy(tmp_path) -> Path:
    out = tmp_path / "realism"
    shutil.copytree(VENDOR, out)
    return out


def test_a_one_byte_change_to_a_vendored_generator_fails_the_load_and_names_it(tmp_path):
    v = _copy(tmp_path)
    b = bytearray((v / "group10_floors.py").read_bytes())
    b[-2] = ord("#") if b[-2] != ord("#") else ord(" ")
    (v / "group10_floors.py").write_bytes(bytes(b))
    with pytest.raises(realism_bundle.BundleError, match="group10_floors.py"):
        realism_bundle.load(v)


def test_a_memo_key_that_does_not_match_the_vendored_sources_refuses_rather_than_solving(tmp_path):
    v = _copy(tmp_path)
    m = json.loads((v / "MANIFEST.json").read_text(encoding="utf-8"))
    m["memo_sha256"] = "0" * 64
    (v / "MANIFEST.json").write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(realism_bundle.BundleError, match="refuses to load rather than solve"):
        realism_bundle.load(v)


def test_the_memo_key_is_the_spec_gates_own_cache_key(bundle):
    assert realism_bundle.memo_key(VENDOR, bundle._gate) == bundle.manifest["memo_sha256"]
    assert bundle._gate.GENERATORS == ("scripts/group9_ledger.py", "scripts/group10_floors.py",
                                       "scripts/group11_compliance.py", "scripts/group8_dtc.py")


NEVER_SOLVES = textwrap.dedent("""
    import sys
    sys.path.insert(0, {vendor!r}); sys.path.insert(0, {generation!r})
    import group11_compliance as L
    def refused(*a, **k):
        raise SystemExit("SOLVED")
    L.solve_account_factor = refused
    import realism_bundle
    b = realism_bundle.load()
    t = b.trial()
    print("REPLAYED", sorted(t))
""")


def test_loading_and_replaying_the_pinned_trial_never_solve_and_the_replay_hashes_to_the_spec_digest():
    """trial() refuses a replay whose digest differs from the spec side's export, so a pass is both."""
    r = subprocess.run([sys.executable, "-c", NEVER_SOLVES.format(vendor=str(VENDOR), generation=str(GENERATION))],
                       capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REPLAYED ['club_exits_y3', 'decliners', 'exits', 'launches', 'trial', 'window_end', 'window_start']" \
        in r.stdout


def test_a_patched_bundle_moves_only_what_it_patches(bundle):
    key = ("constant", "group9_ledger", "DPO")
    p = bundle.patched(key, bundle.constant("group9_ledger", "DPO") + 1)
    assert p.constant("group9_ledger", "DPO") == bundle.constant("group9_ledger", "DPO") + 1
    assert bundle.constant("group9_ledger", "DPO") == 32
    assert p.ap_schedule() is bundle.ap_schedule()


# ---------------------------------------------------------------- U4's ban, on the bundle
@pytest.mark.parametrize("fixture", sorted(p.name for p in (ROOT / "tests" / "fixtures" / "bundle").glob("*.py")))
def test_the_import_ban_rejects_a_scan_root_module_that_reaches_the_bundle(fixture):
    with pytest.raises(TruthAccessViolation):
        assert_no_generator_access(ROOT / "tests" / "fixtures" / "bundle" / fixture)


# ---------------------------------------------------------------- 1. one import
def one_import_violations(paths) -> list[str]:
    bad = []
    for p in paths:
        for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            hit = [n for n in names if n.split(".")[-1] in GROUP_MODULES or n.split(".")[0] in GROUP_MODULES]
            bad += [f"{p.name}:{node.lineno} imports {n}" for n in hit]
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and "vendor/realism" in node.value.replace("\\", "/"):
                bad.append(f"{p.name}:{node.lineno} reads vendor/realism/")
            if isinstance(node, ast.Constant) and node.value == "realism":
                bad.append(f"{p.name}:{node.lineno} names the bundle's directory")
    return bad


def _seeders():
    return sorted(p for p in GENERATION.glob("*.py") if p.name != "realism_bundle.py")


def test_no_module_in_generation_but_the_loader_imports_a_group_module_or_reads_the_bundle():
    assert one_import_violations(_seeders()) == []


def test_the_one_import_test_fails_on_a_seeder_that_imports_a_group_module(tmp_path):
    (tmp_path / "seed_stray.py").write_text("import group10_floors\nfrom group9_ledger import DPO\n")
    (tmp_path / "seed_reader.py").write_text("P = ROOT / 'vendor' / 'realism' / 'outputs.json'\n")
    assert len(one_import_violations([tmp_path / "seed_stray.py", tmp_path / "seed_reader.py"])) == 3


# ---------------------------------------------------------------- 2. no literal
def _sig(v) -> int:
    s = repr(v).lower().lstrip("-")
    if "e" in s:
        return 99
    if "." in s:
        a, b = s.split(".")
        b = b.rstrip("0")
        if b:                      # 1.05 -> 3, 0.0450 -> 2
            return len((a + b).lstrip("0"))
        s = a                      # 400.0 is 400: trailing zeros of a whole number are not significant
    return len(s.strip("0")) if s.strip("0") else 1


def bundle_values(outputs) -> tuple[set, set]:
    """Every numeric leaf of the entry functions' returns, and every all-numeric list of two or more."""
    vals, seqs = set(), set()

    def walk(x):
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            vals.add(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            if len(x) >= 2 and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in x):
                seqs.add(tuple(x))
            for v in x:
                walk(v)
    walk(json.loads(json.dumps(outputs["generators"], default=str)))
    return {v for v in vals if _sig(v) >= 3}, seqs


def literal_hits(paths, vals, seqs) -> tuple[Counter, Counter, list]:
    """(file, value) and (file, series) counts, and lines whose exemption names no reason."""
    lits, runs, empty = Counter(), Counter(), []
    for p in paths:
        lines = p.read_text(encoding="utf-8").splitlines()

        def exempt(node):
            m = EXEMPT.search(lines[node.lineno - 1])
            if m and not (m.group(1) or "").strip():
                empty.append(f"{p.name}:{node.lineno}")
                return False
            return bool(m)
        for node in ast.walk(ast.parse("\n".join(lines))):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                    and not isinstance(node.value, bool) and node.value in vals and not exempt(node):
                lits[(p.name, float(node.value))] += 1
            if isinstance(node, (ast.List, ast.Tuple)):
                xs = [e.value for e in node.elts if isinstance(e, ast.Constant)
                      and isinstance(e.value, (int, float)) and not isinstance(e.value, bool)]
                for s in seqs:
                    if 2 <= len(s) <= len(xs) and any(tuple(xs[i:i + len(s)]) == s for i in range(len(xs) - len(s) + 1)) \
                            and not exempt(node):
                        runs[(p.name, s)] += 1
    return lits, runs, empty


def test_no_seeder_carries_a_bundle_output_as_a_literal_beyond_the_owed_list(bundle):
    vals, seqs = bundle_values(bundle.outputs)
    lits, runs, empty = literal_hits(_seeders(), vals, seqs)
    over = {k: n for k, n in lits.items() if n > LITERALS_OWED.get(k, (0, None))[0]}
    over_s = {k: n for k, n in runs.items() if n > SERIES_OWED.get(tuple(k), (0, None))[0]}
    assert (over, over_s, empty) == ({}, {}, []), \
        "a seeder carries a bundle output as a literal: read it through generation/realism_bundle.py"


def test_the_literal_test_fails_on_a_seeder_carrying_a7_04s_door_series(bundle, tmp_path):
    vals, seqs = bundle_values(bundle.outputs)
    doors = bundle.printed("group10_floors", "A7.04", "A7.04 the door totals")
    (tmp_path / "seed_doors.py").write_text(f"DOORS = {[int(x) for x in doors]}\n")
    lits, runs, _ = literal_hits([tmp_path / "seed_doors.py"], vals, seqs)
    assert runs and lits
    (tmp_path / "seed_doors.py").write_text(f"DOORS = {[int(x) for x in doors]}  # mirror-exempt:\n")
    lits, runs, empty = literal_hits([tmp_path / "seed_doors.py"], vals, seqs)
    assert empty and runs                                       # an exemption that names no reason still fails
    (tmp_path / "seed_doors.py").write_text(f"DOORS = {[int(x) for x in doors]}  # mirror-exempt: a fixture\n")
    assert literal_hits([tmp_path / "seed_doors.py"], vals, seqs) == (Counter(), Counter(), [])


def test_the_owed_lists_name_window_units():
    units = json.loads((VENDOR / "unit_status.json").read_text(encoding="utf-8"))
    assert {u for _, u in list(LITERALS_OWED.values()) + list(SERIES_OWED.values())} <= set(units)
