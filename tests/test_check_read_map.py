"""Plan U19, ruling 3: the read map as a contract, shown to fail on every arm it runs.

Runs against a fixture read map, a fixture fleet and a fixture canon built in tmp_path, so it needs neither the fleet
nor a database.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import check_read_map as crm

MAP = """# map

## The list, by how a regen reaches it

**A. Reads the warehouse live at runtime (1).** `live-repo`.

**C. Reads no warehouse table; carries typed figures (1).** `print-repo`.

A + C = 1 + 1 names.

## Canon keys read (1 repo)

| Repo | Keys | Where |
|---|---|---|
| `live-repo` | `revenue.combined_invoiced.cy2025` | `tests/t.py:1` |

## The table

| Repo | Class | Status | Read | Fields | Where |
|---|---|---|---|---|---|
| live-repo | A | live | public_marts.fct_scan_data | sku, units_sold | app/db.py:2 |
| print-repo | C | live | — | — | — |

## Per repo
"""
CANON = {"revenue": {"combined_invoiced": {"cy2025": 1.0}}}


def _fleet(tmp_path: Path) -> Path:
    fleet = tmp_path / "fleet"
    repo = fleet / "published" / "live-repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "db.py").write_text('Q = """\nSELECT sku FROM fct_scan_data\n"""\n')
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return fleet


def _run(tmp_path: Path, text: str = MAP, canon: dict = CANON) -> list[str]:
    m = tmp_path / "map.md"
    m.write_text(text, encoding="utf-8")
    c = tmp_path / "canon.json"
    c.write_text(json.dumps(canon), encoding="utf-8")
    return crm.check(m, _fleet(tmp_path), c)


def test_a_map_whose_table_list_citations_and_keys_agree_passes(tmp_path):
    assert _run(tmp_path) == []


@pytest.mark.parametrize("old,new,expect", [
    ("| print-repo | C | live | — | — | — |\n", "", "print-repo: class C in the map's list, missing from the table"),
    ("| print-repo | C |", "| print-repo | D |", "print-repo: class C in the map's list, D in the table"),
    ("| live-repo | A | live |", "| live-repo | A | archived |", "status 'archived'"),
    ("app/db.py:2 |", "app/db.py:1 |", "app/db.py:1 does not name fct_scan_data"),
    ("app/db.py:2 |", "app/app.py:2 |", "app/app.py:2 (for public_marts.fct_scan_data): no such file"),
    ("| live-repo | A | live | public_marts.fct_scan_data |", "| ghost-repo | A | live | public_marts.fct_scan_data |",
     "ghost-repo: no working copy"),
    ("`revenue.combined_invoiced.cy2025`", "`revenue.combined_invoiced.cy2026`",
     "canon key revenue.combined_invoiced.cy2026 is not in canonical_values.json"),
    ("| Repo | Class | Status | Read | Fields | Where |", "| Repo | Class | Read | Fields | Where |",
     "has no '## The table'"),
])
def test_each_arm_fails_on_a_broken_map(tmp_path, old, new, expect):
    assert MAP.count(old) == 1
    failures = _run(tmp_path, MAP.replace(old, new))
    assert any(expect in f for f in failures), failures
