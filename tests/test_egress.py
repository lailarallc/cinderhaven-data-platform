"""Egress checks (plan U4, R11): one per path, each shown to fail.

Path 3: the language-agnostic text scan fails on every file type a consumer
reads the warehouse from, and passes the clean files. A scan never shown to fail
on a non-Python file type is not known to cover it.

Path 7: generation-path logging reports truth as populated or not, never a count.

Path 8: U3's harness keeps no snapshot; truth never enters one, and nothing the
harness writes is outside .gitignore.
"""
from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from quarantine.text_scan import TextScanViolation, assert_no_truth_text

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "egress"
VIOLATIONS = sorted(p.name for p in FIX.glob("violation*"))
CLEAN = sorted(p.name for p in FIX.glob("clean*"))


def test_there_is_a_violation_fixture_for_every_file_type():
    suffixes = {Path(n).suffix for n in VIOLATIONS}
    assert {".R", ".qmd", ".ipynb", ".sql", ".sh", ".yml"} <= suffixes


@pytest.mark.parametrize("fixture", VIOLATIONS)
def test_the_text_scan_fails_on(fixture):
    with pytest.raises(TextScanViolation):
        assert_no_truth_text(FIX / fixture)


@pytest.mark.parametrize("fixture", CLEAN)
def test_the_text_scan_passes(fixture):
    assert_no_truth_text(FIX / fixture)


# ── path 7 ──

def _prints_in(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "print"]


def test_seed_all_reports_truth_as_a_boolean_through_truth_populated():
    src = (ROOT / "generation" / "seed_all.py").read_text(encoding="utf-8")
    assert "public.truth_populated()" in src
    # verify_counts counts raw, costing, voidfinder and copack's five (plan U2) and never
    # truth: extending it to truth would print the injected-error count.
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "verify_counts")
    body = ast.get_source_segment(src, fn)
    assert "n.nspname IN ('raw', 'costing', 'voidfinder')" in body and "n.nspname = 'copack'" in body
    assert "truth" not in body.replace("report_truth(conn)", "").replace("truth as a boolean only", ""), \
        "verify_counts names truth outside its boolean report"


def test_no_generation_print_formats_a_value_from_truth():
    # A print that formats a value and mentions truth is a candidate leak; the
    # populated yes/no is the one named exemption. A constant message is not.
    for f in sorted((ROOT / "generation").glob("*.py")):
        text = f.read_text(encoding="utf-8")
        for call in _prints_in(f):
            seg = ast.get_source_segment(text, call) or ""
            formats = any(not isinstance(a, ast.Constant) for a in call.args)
            assert not (formats and "truth" in seg.lower() and "populated" not in seg.lower()), f"{f.name}: {seg}"


def test_the_print_rule_catches_a_formatted_truth_count(tmp_path):
    f = tmp_path / "leak.py"
    f.write_text('print(f"truth injection rows: {n}")\n')
    text = f.read_text()
    call = _prints_in(f)[0]
    seg = ast.get_source_segment(text, call)
    assert any(not isinstance(a, ast.Constant) for a in call.args) and "truth" in seg


# ── path 8 ──

@pytest.mark.parametrize("path", ["output/seed_runs/x.json", "output/harness/hashes.json", "tests/harness.env"])
def test_what_the_harness_writes_is_gitignored(path):
    r = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
    assert r.returncode == 0, f"{path} is not covered by .gitignore"


def test_the_table_hash_tool_never_hashes_truth():
    import table_hashes
    assert "truth" not in table_hashes.SCHEMAS
