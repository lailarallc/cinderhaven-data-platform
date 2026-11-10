"""The truth gate (plan U4). Two claims, kept separate as in Lift Math:

1. The platform's scan roots cannot reach truth (AST gate, text scan).
2. The gate rejects violations: every fixture under tests/fixtures/truth_gate
   is shown to fire, because a guardrail never shown to fire is not evidence.

Exemption lists are explicit file paths, pinned to their logged set. Changing
one needs a DECISIONS entry (platform DECISIONS.md, "truth exemptions"), not a
test edit.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from quarantine import truth_gate
from quarantine.text_scan import TextScanViolation, assert_no_truth_text
from quarantine.truth_gate import TruthAccessViolation, assert_no_truth_access

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "truth_gate"

#: The scan roots. generation/, vendor/realism/, quarantine/ and tests/ sit
#: outside every root by construction; cinderhaven/ holds no Python, so the AST
#: gate walks two and the text scan five.
AST_ROOTS = ("scripts", "orchestration")
TEXT_ROOTS = ("scripts", "cinderhaven", "orchestration", "sql", ".github/workflows")

#: List 1: empty. With every writer in generation/, nothing in a root names truth.
AST_EXEMPT: tuple = ()
#: List 2: the DDL whose job is to name the tables, and list 3's one entry.
TEXT_SCAN_EXEMPT = ("sql/truth_schema.sql", "sql/truth_roles.sql",
                    "cinderhaven/models/counterfactual/mart_counterfactual.sql")


def test_the_platform_scan_roots_cannot_reach_truth():
    assert_no_truth_access(*(ROOT / r for r in AST_ROOTS), exclude=AST_EXEMPT)


def test_the_platform_text_roots_name_no_truth_table():
    assert_no_truth_text(*(ROOT / r for r in TEXT_ROOTS), exempt=TEXT_SCAN_EXEMPT, base=ROOT)


def test_the_needles_table_list_equals_the_tables_the_ddl_creates():
    # The regression test for the closed errors./truth. defect, over every table.
    ddl = (ROOT / "sql" / "truth_schema.sql").read_text()
    assert sorted(re.findall(r"CREATE TABLE truth\.(\w+)", ddl)) == sorted(truth_gate.TRUTH_TABLES)


@pytest.mark.parametrize("fixture", [
    "violation_imports_truth.py",
    "violation_import_dotted_truth.py",
    "violation_names_truth_table.py",          # a SQL string
    "violation_docstring_names_table.py",      # prose fails like any literal: reword, never exempt
    "violation_search_path.py",
    "truth.py",                                # no truth.py skip
])
def test_the_gate_rejects(fixture):
    with pytest.raises(TruthAccessViolation):
        assert_no_truth_access(FIX / fixture)


@pytest.mark.parametrize("fixture", ["clean_prose.py", "clean_estimator.py"])
def test_the_gate_passes_prose_and_filenames_that_contain_the_word(fixture):
    # "source of truth.", revenue_truth.json/.csv, --exclude-schema=truth.
    assert_no_truth_access(FIX / fixture)


def test_a_comment_naming_a_truth_table_fails_the_text_scan(tmp_path):
    (tmp_path / "m.py").write_text("x = 1  # then read truth.promo_events\n")
    assert_no_truth_access(tmp_path)  # the AST sees no comment ...
    with pytest.raises(TextScanViolation):
        assert_no_truth_text(tmp_path)  # ... the text scan does


def test_the_gate_raises_when_any_one_root_is_empty(tmp_path):
    full, empty = tmp_path / "full", tmp_path / "empty"
    full.mkdir(), empty.mkdir()
    (full / "ok.py").write_text("x = 1\n")
    (empty / "notes.txt").write_text("no python")
    with pytest.raises(ValueError, match="empty"):
        assert_no_truth_access(full, empty)


def test_the_geometry_generation_is_not_visited_and_scripts_is(tmp_path):
    # The same module fails under scripts/ and is never visited under generation/,
    # because generation/ is not a root. Tested, not assumed.
    for d in ("scripts", "generation"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "seed_x.py").write_text((FIX / "violation_names_truth_table.py").read_text())
    with pytest.raises(TruthAccessViolation):
        assert_no_truth_access(tmp_path / "scripts")
    assert "generation" not in AST_ROOTS + TEXT_ROOTS
    assert not any((ROOT / r).resolve() in (ROOT / "generation").resolve().parents
                   or (ROOT / r).resolve() == (ROOT / "generation").resolve() for r in AST_ROOTS + TEXT_ROOTS)


@pytest.mark.parametrize("name,entries,suffixes", [
    ("AST", AST_EXEMPT, (".py",)),
    ("text scan", TEXT_SCAN_EXEMPT, (".py", ".sql")),
])
def test_every_exemption_is_an_explicit_file_path(name, entries, suffixes):
    for e in entries:
        assert e.endswith(suffixes) and not e.endswith("/"), f"{name} exemption {e!r} is not a file path"


def test_the_exemption_lists_match_the_logged_decision():
    assert AST_EXEMPT == (), "the AST exemption list changed: that needs a DECISIONS entry, not a test edit"
    assert TEXT_SCAN_EXEMPT == ("sql/truth_schema.sql", "sql/truth_roles.sql",
                                "cinderhaven/models/counterfactual/mart_counterfactual.sql"), (
        "the text-scan exemption list changed: that needs a DECISIONS entry, not a test edit")
