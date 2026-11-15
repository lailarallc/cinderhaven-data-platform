"""scripts/vendor_realism.py (plan U5): refuses what it must, records every spec check, names what moved."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import vendor_realism  # noqa: E402

CLEAN = [{"name": "check one", "level": "BLOCK", "findings": 0},
         {"name": "check two", "level": "WARN", "findings": 3},
         {"name": "check three", "level": "INFO", "findings": 0}]


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def spec(tmp_path):
    s = tmp_path / "spec"
    for rel in vendor_realism.BUNDLE.values():
        (s / rel).parent.mkdir(parents=True, exist_ok=True)
        (s / rel).write_text(f"# {rel}\n", encoding="utf-8")
    _git(s, "init", "-q")
    _git(s, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(s, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "x")
    return s


def test_a_clean_gate_vendors_every_file_and_records_every_check_with_its_level(spec, tmp_path):
    out = tmp_path / "vendor"
    m = vendor_realism.vendor(spec, _git(spec, "rev-parse", "HEAD"), out, gate=lambda s: CLEAN)
    assert sorted(p.name for p in out.iterdir()) == ["MANIFEST.json", "anchor_enums.yml", "anchors.yml",
                                                     "check_anchors.py"]
    saved = json.loads((out / "MANIFEST.json").read_text())
    assert saved["spec_gate"] == {"clean": True, "blocking_findings": 0, "checks": CLEAN}
    assert saved["files"]["anchors.yml"] == vendor_realism.sha256(out / "anchors.yml")
    assert m["moved"] == ["anchor_enums.yml", "anchors.yml", "check_anchors.py"]


def test_a_gate_that_is_not_clean_is_refused_and_nothing_is_written(spec, tmp_path):
    out = tmp_path / "vendor"
    red = CLEAN + [{"name": "check four", "level": "BLOCK", "findings": 2}]
    with pytest.raises(vendor_realism.VendorRefused, match="check four"):
        vendor_realism.vendor(spec, _git(spec, "rev-parse", "HEAD"), out, gate=lambda s: red)
    assert not out.exists()


def test_a_dirty_spec_checkout_is_refused(spec, tmp_path):
    (spec / "reference" / "anchors.yml").write_text("edited\n", encoding="utf-8")
    with pytest.raises(vendor_realism.VendorRefused, match="not clean"):
        vendor_realism.vendor(spec, _git(spec, "rev-parse", "HEAD"), tmp_path / "v", gate=lambda s: CLEAN)


def test_a_checkout_at_another_commit_is_refused(spec, tmp_path):
    with pytest.raises(vendor_realism.VendorRefused, match="not 0000000"):
        vendor_realism.vendor(spec, "0000000", tmp_path / "v", gate=lambda s: CLEAN)


def test_a_gate_run_that_changes_the_spec_tree_is_refused(spec, tmp_path):
    def dirtying(s):
        (s / "stray.txt").write_text("x", encoding="utf-8")
        return CLEAN
    with pytest.raises(vendor_realism.VendorRefused, match="changed the spec tree"):
        vendor_realism.vendor(spec, _git(spec, "rev-parse", "HEAD"), tmp_path / "v", gate=dirtying)


def test_a_re_vendor_names_exactly_the_files_that_moved(spec, tmp_path):
    out = tmp_path / "vendor"
    vendor_realism.vendor(spec, _git(spec, "rev-parse", "HEAD"), out, gate=lambda s: CLEAN)
    (spec / "reference" / "anchors.yml").write_text("# a new row\n", encoding="utf-8")
    _git(spec, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "y")
    m = vendor_realism.vendor(spec, _git(spec, "rev-parse", "HEAD"), out, gate=lambda s: CLEAN)
    assert m["moved"] == ["anchors.yml"]


def test_the_committed_bundle_matches_its_manifest_and_a_clean_spec_gate():
    vendor = ROOT / "vendor" / "realism"
    m = json.loads((vendor / "MANIFEST.json").read_text(encoding="utf-8"))
    assert {n: vendor_realism.sha256(vendor / n) for n in m["files"]} == m["files"]
    assert m["spec_gate"]["clean"] and m["spec_gate"]["blocking_findings"] == 0
    assert set(m["files"]) == set(vendor_realism.BUNDLE)
