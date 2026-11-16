"""scripts/vendor_realism.py (plans U5, U15): the whole bundle; refuses what it must, records every spec check,
keys the memo and pins the trial, runs the recompute before it installs anything, names what moved."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import vendor_realism  # noqa: E402

PLAN_STUB = ("### U1. One\n\n**Status (2026-10-07):** DONE 2026-09-02. A record.\n\n"
             "### U6. Six\n\n**Status (2026-10-07):** Done in substance.\n\n"
             "### U8. Eight\n\n**Status (2026-11-15, later):** DONE, merged.\n\n"
             "### U9. Nine\n\n**Status (2026-10-07):** Not started. DONE later.\n")

CLEAN = [{"name": "check one", "level": "BLOCK", "findings": 0},
         {"name": "check two", "level": "WARN", "findings": 3},
         {"name": "check three", "level": "INFO", "findings": 0}]


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


#: a stub spec gate: what the loader reads from the real one (its generator list, the memo's function, the codec)
GATE_STUB = ('GENERATORS = ("scripts/group9_ledger.py", "scripts/group10_floors.py", "scripts/group11_compliance.py",\n'
             '              "scripts/group8_dtc.py")\nFACTOR = "factor"\n\n\ndef _outputs_compute():\n    return {}\n\n\n'
             'def _encode(o):\n    raise TypeError(o)\n\n\ndef _decode(d):\n    return d\n')
TRIAL = {"exits": [1, 7, 3], "trial": 0}


def _export(spec):
    head = _git(spec, "rev-parse", "HEAD")
    return json.dumps({"commit": head, "generators": {"group11_compliance": {"printed": {}, "trial": TRIAL}}}).encode()


def _holds(stage):
    return []


def _vendor(spec, out, **kw):
    kw.setdefault("gate", lambda s: CLEAN)
    kw.setdefault("export", _export)
    kw.setdefault("slow", _holds)
    return vendor_realism.vendor(spec, _git(spec, "rev-parse", "HEAD"), out, **kw)


@pytest.fixture
def spec(tmp_path):
    s = tmp_path / "spec"
    for rel in vendor_realism.BUNDLE.values():
        (s / rel).parent.mkdir(parents=True, exist_ok=True)
        (s / rel).write_text(GATE_STUB if rel.endswith("check_anchors.py") else f"# {rel}\n", encoding="utf-8")
    (s / vendor_realism.PLAN).parent.mkdir(parents=True, exist_ok=True)
    (s / vendor_realism.PLAN).write_text(PLAN_STUB, encoding="utf-8")
    _git(s, "init", "-q")
    _git(s, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(s, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "x")
    return s


def test_a_clean_gate_vendors_every_file_and_records_every_check_with_its_level(spec, tmp_path):
    out = tmp_path / "vendor"
    m = _vendor(spec, out)
    assert sorted(p.name for p in out.iterdir()) == ["MANIFEST.json", "anchor_enums.yml", "anchors.yml",
                                                     "check_anchors.py", "group10_floors.py",
                                                     "group11_compliance.py", "group8_dtc.py", "group9_ledger.py",
                                                     "outputs.json", "unit_status.json"]
    saved = json.loads((out / "MANIFEST.json").read_text())
    assert saved["spec_gate"] == {"clean": True, "blocking_findings": 0, "checks": CLEAN}
    assert saved["files"]["anchors.yml"] == vendor_realism.sha256(out / "anchors.yml")
    assert saved["files"]["unit_status.json"] == vendor_realism.sha256(out / "unit_status.json")
    assert m["moved"] == ["anchor_enums.yml", "anchors.yml", "check_anchors.py", "group10_floors.py",
                          "group11_compliance.py", "group8_dtc.py", "group9_ledger.py", "outputs.json",
                          "unit_status.json"]
    for name, rel in vendor_realism.BUNDLE.items():              # byte copies
        assert (out / name).read_bytes() == (spec / rel).read_bytes()
    assert saved["pinned_trial"] == {"index": 0, "digest": vendor_realism.realism_bundle.trial_digest(TRIAL)}
    assert saved["memo_sha256"] == vendor_realism.realism_bundle.memo_key(out, vendor_realism.realism_bundle.gate_module(out))
    # DONE leads the status; "Done in substance" and a later "DONE" in the prose do not count.
    assert json.loads((out / "unit_status.json").read_text()) == {
        "U1": {"date": "2026-10-07", "done": True}, "U6": {"date": "2026-10-07", "done": False},
        "U8": {"date": "2026-11-15", "done": True}, "U9": {"date": "2026-10-07", "done": False}}


def test_a_gate_that_is_not_clean_is_refused_and_nothing_is_written(spec, tmp_path):
    out = tmp_path / "vendor"
    red = CLEAN + [{"name": "check four", "level": "BLOCK", "findings": 2}]
    with pytest.raises(vendor_realism.VendorRefused, match="check four"):
        _vendor(spec, out, gate=lambda s: red)
    assert not out.exists()


def test_a_dirty_spec_checkout_is_refused(spec, tmp_path):
    (spec / "reference" / "anchors.yml").write_text("edited\n", encoding="utf-8")
    with pytest.raises(vendor_realism.VendorRefused, match="not clean"):
        _vendor(spec, tmp_path / "v")


def test_a_checkout_at_another_commit_is_refused(spec, tmp_path):
    with pytest.raises(vendor_realism.VendorRefused, match="not 0000000"):
        vendor_realism.vendor(spec, "0000000", tmp_path / "v", gate=lambda s: CLEAN, export=_export, slow=_holds)


def test_a_gate_run_that_changes_the_spec_tree_is_refused(spec, tmp_path):
    def dirtying(s):
        (s / "stray.txt").write_text("x", encoding="utf-8")
        return CLEAN
    with pytest.raises(vendor_realism.VendorRefused, match="changed the spec tree"):
        _vendor(spec, tmp_path / "v", gate=dirtying)


def test_a_re_vendor_names_exactly_the_files_that_moved(spec, tmp_path):
    out = tmp_path / "vendor"
    _vendor(spec, out)
    (spec / "reference" / "anchors.yml").write_text("# a new row\n", encoding="utf-8")
    _git(spec, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "y")
    m = _vendor(spec, out)
    assert m["moved"] == ["anchors.yml", "outputs.json"]       # outputs.json names its commit


def test_the_committed_bundle_matches_its_manifest_and_a_clean_spec_gate():
    vendor = ROOT / "vendor" / "realism"
    m = json.loads((vendor / "MANIFEST.json").read_text(encoding="utf-8"))
    assert {n: vendor_realism.sha256(vendor / n) for n in m["files"]} == m["files"]
    assert m["spec_gate"]["clean"] and m["spec_gate"]["blocking_findings"] == 0
    assert set(m["files"]) == set(vendor_realism.BUNDLE) | {vendor_realism.UNIT_STATUS, vendor_realism.OUTPUTS}
    raw = json.loads((vendor / "outputs.json").read_text(encoding="utf-8"))
    assert raw["commit"] == m["spec_commit"]                   # one commit for every file
    assert m["pinned_trial"]["digest"] == vendor_realism.realism_bundle.trial_digest(
        raw["generators"]["group11_compliance"]["trial"])


def test_a_spec_checkout_without_the_plan_is_refused(spec, tmp_path):
    (spec / vendor_realism.PLAN).unlink()
    _git(spec, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "no plan")
    with pytest.raises(vendor_realism.VendorRefused, match="has no"):
        _vendor(spec, tmp_path / "v")


def test_a_recompute_that_does_not_hold_is_refused_and_nothing_is_installed(spec, tmp_path):
    out = tmp_path / "vendor"
    with pytest.raises(vendor_realism.VendorRefused, match="fresh solve"):
        _vendor(spec, out, slow=lambda stage: ["a fresh solve on the vendored copies returns 0.6"])
    assert not out.exists()


def test_the_recompute_runs_on_the_staged_bytes_before_anything_is_installed(spec, tmp_path):
    out, seen = tmp_path / "vendor", {}

    def looks(stage):
        seen["files"] = sorted(p.name for p in stage.iterdir())
        seen["installed"] = out.exists()
        return []
    _vendor(spec, out, slow=looks)
    assert seen["installed"] is False and "outputs.json" in seen["files"] and "group10_floors.py" in seen["files"]


def test_an_export_at_another_commit_is_refused(spec, tmp_path):
    with pytest.raises(vendor_realism.VendorRefused, match="exported at"):
        _vendor(spec, tmp_path / "v", export=lambda s: json.dumps({"commit": "0" * 40, "generators": {}}).encode())
