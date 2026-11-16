"""Plan U19, the fleet check: shown to pass a conforming fleet and to fail on each thing it checks.

Builds a fixture platform, read map and fleet in tmp_path; needs neither the fleet nor a database.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import check_gate_presence as gp

MAP = """# map

## The table

| Repo | Class | Status | Read | Fields | Where |
|---|---|---|---|---|---|
| repo-a | A | live | raw.scan_data | sku | app/db.py:1 |
| repo-c | C | live | — | — | — |
| old-repo | B | retired | — | — | — |

## Per repo
"""


def _platform(tmp_path: Path) -> Path:
    plat = tmp_path / "platform"
    for src_dir, fname, _ in gp.ARTIFACTS:
        (plat / src_dir).mkdir(parents=True, exist_ok=True)
        (plat / src_dir / fname).write_bytes(f"# {fname}\nline two\n".encode())
    (plat / gp.CEILINGS).parent.mkdir(parents=True, exist_ok=True)
    (plat / gp.CEILINGS).write_text("# ceilings\nrepo-a: 2  # two typed figures\n", encoding="utf-8")
    return plat


LEDGER = "# a comment\nfile_line\tprinted\nREADME.md:1\t$1.2M\nREADME.md:2\t42%\n"


def _repo(fleet: Path, plat: Path, name: str, files: dict[str, str] | None = None) -> Path:
    repo = fleet / "published" / name
    for src_dir, fname, dest in gp.ARTIFACTS:
        (repo / dest).mkdir(parents=True, exist_ok=True)
        (repo / dest / fname).write_bytes((plat / src_dir / fname).read_bytes())
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / gp.DRIFT_WORKFLOW).write_text("name: drift\n")
    for rel, text in (files or {}).items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    return repo


def _run(tmp_path: Path, a_files: dict[str, str] | None = None, classes: str = "ABCD", mutate=None):
    plat = _platform(tmp_path)
    fleet = tmp_path / "fleet"
    a = _repo(fleet, plat, "repo-a", {"app/db.py": "SELECT sku FROM raw.scan_data\n", gp.LEDGER: LEDGER,
                                      **(a_files or {})})
    _repo(fleet, plat, "repo-c")
    if mutate:
        mutate(a)
    m = tmp_path / "map.md"
    m.write_text(MAP, encoding="utf-8")
    return gp.check(m, fleet, classes, plat)


def test_a_conforming_fleet_passes_and_the_retired_repo_is_skipped(tmp_path):
    assert _run(tmp_path) == ([], ["old-repo"])


@pytest.mark.parametrize("ledger,expect", [
    (LEDGER + "README.md:3\t9.8%\n", "repo-a: reference/typed_unkeyed.tsv has 3 rows, over its ceiling of 2"),
    (LEDGER.rsplit("README.md:2", 1)[0], "repo-a: reference/typed_unkeyed.tsv has 1 rows; lower its ceiling in "
                                         "reference/typed_unkeyed_ceilings.yml from 2 to 1"),
])
def test_the_ledger_is_held_to_its_ceiling_both_ways(tmp_path, ledger, expect):
    bad, _ = _run(tmp_path, {gp.LEDGER: ledger})
    assert bad == [expect]


def test_a_missing_ledger_under_a_ceiling_fails(tmp_path):
    bad, _ = _run(tmp_path, mutate=lambda a: (a / gp.LEDGER).unlink())
    assert bad == ["repo-a: reference/typed_unkeyed.tsv missing (ceiling 2)"]


def test_a_ledger_without_a_ceiling_fails_once_it_has_rows(tmp_path):
    def add(a):
        (a.parent / "repo-c" / "reference").mkdir(exist_ok=True)
        (a.parent / "repo-c" / gp.LEDGER).write_text(LEDGER, encoding="utf-8")
    bad, _ = _run(tmp_path, mutate=add)
    assert bad == ["repo-c: reference/typed_unkeyed.tsv has 2 rows, over its ceiling of 0"]


def test_the_platform_ceilings_file_parses():
    ceilings = gp.load_ceilings(gp.ROOT)
    assert ceilings and all(isinstance(v, int) and v >= 0 for v in ceilings.values())


def test_crlf_line_endings_are_not_drift(tmp_path):
    def crlf(a):
        p = a / "scripts" / "refresh_canonical.py"
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert _run(tmp_path, mutate=crlf)[0] == []


def test_the_class_filter_drops_a_repo(tmp_path):
    def gone(a):
        (a / gp.DRIFT_WORKFLOW).unlink()
    assert _run(tmp_path, classes="CD", mutate=gone)[0] == []
    assert _run(tmp_path / "x", classes="A", mutate=gone)[0] != []


@pytest.mark.parametrize("files,mutate,expect", [
    (None, lambda a: (a / "quarantine" / "truth_gate.py").unlink(), "repo-a: quarantine/truth_gate.py missing"),
    (None, lambda a: (a / "reference" / "canonical_values.json").write_text("{}"),
     "repo-a: reference/canonical_values.json differs"),
    (None, lambda a: (a / gp.DRIFT_WORKFLOW).unlink(), "repo-a: .github/workflows/canonical-drift.yml missing"),
    ({"s.py": 'cur.execute("DROP TABLE IF EXISTS raw.shopify_refunds CASCADE")\n'}, None,
     "repo-a: s.py:1 writes raw.shopify_refunds"),
    ({"s.py": 'q = """\nCREATE INDEX i ON public_marts.fct_scan_data (sku)\n"""\n'}, None,
     "repo-a: s.py:2 writes public_marts.fct_scan_data"),
    ({"s.py": 'c = connect(options="-c search_path=public_marts,raw")\ncur.execute("ALTER TABLE dim_products ADD x int")\n'},
     None, "repo-a: s.py:2 writes public_marts.dim_products (search_path)"),
    ({"s.sql": "insert into copack.forecast_snapshot values (1);\n"}, None, "repo-a: s.sql:1 writes copack.forecast_snapshot"),
    ({"dbt/dbt_project.yml": "models:\n  x:\n    marts:\n      +schema: public_marts\n"}, None,
     "repo-a: dbt/dbt_project.yml:4 builds dbt models into public_marts"),
])
def test_each_check_fails(tmp_path, files, mutate, expect):
    failures, _ = _run(tmp_path, files, mutate=mutate)
    assert any(expect in f for f in failures), failures


@pytest.mark.parametrize("files", [
    {"s.py": 'import sqlite3\nc = connect(options="-c search_path=raw")\ncur.execute("CREATE TABLE price_history (x int)")\n'},
    {"s.py": 'cur.execute("CREATE TABLE edi_raw.orders (x int)")\n'},
    {"s.py": 'cur.execute("SELECT * FROM raw.scan_data")\n'},
    {"dbt/dbt_project.yml": "models:\n  x:\n    +schema: edi_marts\n"},
])
def test_what_is_not_a_platform_write_passes(tmp_path, files):
    assert _run(tmp_path, files)[0] == []


def test_a_named_exception_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(gp, "EXCEPTIONS", {("repo-a", "db/seed.py")})
    assert _run(tmp_path, {"db/seed.py": 'cur.execute("TRUNCATE copack.co_packers")\n'})[0] == []


def test_a_repo_with_no_working_copy_fails(tmp_path):
    failures, _ = _run(tmp_path, mutate=lambda a: a.rename(a.parent / "moved-away"))
    assert any("repo-a: no working copy" in f for f in failures), failures
