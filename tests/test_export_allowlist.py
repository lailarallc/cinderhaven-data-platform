"""Egress path 2 (plan U4): the export allowlist check, shown to fail.

Runs against a fixture read map and fixture consumer repos built in tmp_path,
so it needs neither the fleet nor a database.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import check_export_allowlist as cea

ROOT = Path(__file__).resolve().parent.parent

MAP = """# map
### A — live
### B — through a committed extract

**`good-repo`** — B. Warehouse: `public_marts.fct_x` (`scripts/extract.py:12`). Baked to `data/out.json`.

**`{bad}`** — B. Warehouse (`scripts/pull.py`). Baked to `data/out.json`.

### C — no warehouse read
"""


def _repo(fleet: Path, name: str, files: dict[str, str]) -> Path:
    repo = fleet / "active" / name
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], cwd=repo, check=True)
    return repo


def _check(tmp_path, bad_name, bad_files):
    fleet = tmp_path / "fleet"
    _repo(fleet, "good-repo", {"scripts/extract.py": 'Q = "SELECT a FROM public_marts.fct_x"\n',
                               "data/out.json": "{}"})
    if bad_files is not None:
        _repo(fleet, bad_name, bad_files)
    m = tmp_path / "map.md"
    m.write_text(MAP.format(bad=bad_name), encoding="utf-8")
    return cea.check(m, fleet)


def test_a_clean_population_passes_and_records_committed_output(tmp_path):
    failures, notes = _check(tmp_path, "also-good", {"scripts/pull.py": 'Q = "SELECT b FROM raw.stores"\n'})
    assert failures == []
    assert "good-repo: extract output committed: data/out.json" in notes


@pytest.mark.parametrize("body,expect", [
    ('Q = "SELECT * FROM truth.injection_ledger"', "truth"),
    ('Q = "SELECT * FROM edi_marts.fct_y"', "edi_marts"),                  # another repo's schema
    ("OPTS = \"-c search_path=public_marts,truth\"", "search_path names 'truth'"),
    ('Q = "SELECT tablename FROM pg_tables"', "enumerates the catalog"),
])
def test_an_extract_outside_the_allowlist_fails(tmp_path, body, expect):
    failures, _ = _check(tmp_path, "bad-repo", {"scripts/pull.py": body + "\n"})
    assert any(expect in f for f in failures), failures


def test_an_entry_whose_script_is_missing_fails(tmp_path):
    failures, _ = _check(tmp_path, "bad-repo", {"scripts/other.py": "x = 1\n"})
    assert any("not found" in f for f in failures)


def test_a_repo_with_no_working_copy_fails(tmp_path):
    failures, _ = _check(tmp_path, "absent-repo", None)
    assert any("no working copy" in f for f in failures)


def test_an_entry_naming_no_script_fails(tmp_path):
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    m = tmp_path / "map.md"
    m.write_text("### B\n\n**`vague-repo`** — B. Reads the warehouse somehow.\n\n### C\n", encoding="utf-8")
    failures, _ = cea.check(m, fleet)
    assert any("names no extract script" in f for f in failures)


def test_the_export_refuses_before_connecting_when_it_strays(tmp_path):
    stray = tmp_path / "export_x.py"
    stray.write_text('Q = "SELECT * FROM costing.fct_product_costs"\n')
    with pytest.raises(SystemExit, match="not exporting"):
        cea.assert_allowlisted(stray, {"raw", "public_marts"})


def test_export_revenue_truth_is_inside_its_allowlist():
    import export_revenue_truth
    cea.assert_allowlisted(ROOT / "scripts" / "export_revenue_truth.py", export_revenue_truth.EXPORT_SCHEMAS)
