"""Every band test's measured value is saved at every seed whose models built (owner, 2026-11-14)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import band_measures
import seed_runs
from seed_runs import Gate, Outcome, SeedNotBuilt

ROOT = Path(__file__).resolve().parent.parent


def _gates():
    return [Gate("hard_stub", "hard", lambda s: Outcome(passed=True))]


def _rows(v):
    return {"m": {"k": [v, 0.0, 1.0]}}


# ── fast tier ───────────────────────────────────────────────────────

def test_every_dbt_band_test_has_a_measure():
    band_tests = {f"cinderhaven/tests/{p.name}" for p in (ROOT / "cinderhaven" / "tests").glob("*_in_band.sql")}
    measured = {path for path, _ in band_measures.MEASURES.values()}
    assert band_tests, "no band tests found: the glob is wrong"
    assert band_tests <= measured, sorted(band_tests - measured)
    assert "tests/test_costing_integrity.sql" in measured  # its 2% invoices-vs-COGS band
    for path in measured:
        assert (ROOT / path).exists(), path


def test_measures_are_saved_for_built_seeds_and_for_a_seed_refused_only_by_dbt_tests(tmp_path):
    def rebuild(s):
        if s == 1:
            raise SeedNotBuilt({"guard": "void_deletion", "retailer": "R", "loss": 0.02, "limit": 0.015})
        if s == 2:
            raise SeedNotBuilt({"guard": "dbt_tests", "tests": ["t"]})
    progress = tmp_path / "p.jsonl"
    rec = seed_runs.run([0, 1, 2], rebuild, _gates(), progress, measure=lambda s: _rows(0.1 * s))
    assert sorted(rec.measures) == [0, 2]  # the void trip stopped before any model built
    saved = [json.loads(line) for line in progress.read_text().splitlines()[1:]]
    assert ["measures" in e for e in saved] == [True, False, True]


def test_resumed_seeds_keep_their_saved_measures(tmp_path):
    progress = tmp_path / "p.jsonl"
    seed_runs.run([0, 1], lambda s: None, _gates(), progress, measure=lambda s: _rows(0.5))
    rec = seed_runs.run([0, 1], lambda s: pytest.fail("finished seeds must not rebuild"), _gates(), progress,
                        measure=lambda s: pytest.fail("finished seeds must not re-measure"))
    assert rec.measures == {0: _rows(0.5), 1: _rows(0.5)}


def test_the_spread_reports_the_observed_range_and_the_seeds_out_of_band():
    entries = [{"seed": 0, "measures": _rows(0.5)}, {"seed": 3, "measures": _rows(1.2)},
               {"seed": 4, "measures": _rows(-0.1)}]
    s = band_measures.spread(entries)["m"]["k"]
    assert s == {"min": -0.1, "max": 1.2, "band": [0.0, 1.0], "seeds": 3, "out_of_band_seeds": [3, 4]}


def test_a_missing_value_counts_as_out_of_band():
    assert band_measures.out_of_band({"m": {"k": [None, 0.0, 1.0], "j": [0.5, 0.0, 1.0]}}) == {"m": ["k"]}


def test_the_record_carries_the_spread(tmp_path):
    rec = seed_runs.run([0, 1], lambda s: None, _gates(), measure=lambda s: _rows(0.2 + s))
    data = json.loads(seed_runs.write_record(rec, tmp_path).read_text())
    assert data["band_spread"]["m"]["k"]["out_of_band_seeds"] == [1]
    assert data["measures"]["0"] == _rows(0.2)


# ── database tier: each measure agrees with its own test ────────────

@pytest.mark.db
@pytest.mark.parametrize("name", sorted(band_measures.MEASURES))
def test_a_measure_is_out_of_band_exactly_where_its_test_fails(db, name):
    """On the harness's world, the keys a measure puts out of band are as many as the rows its test
    returns. Reads the dbt test as dbt last compiled it (the harness build writes target/)."""
    path, _ = band_measures.MEASURES[name]
    measured = band_measures.measure(db)[name]
    assert measured, f"{name} measured no rows"
    bad = band_measures.out_of_band({name: measured}).get(name, [])
    with db.cursor() as cur:
        if path.startswith("cinderhaven/"):
            compiled = ROOT / "cinderhaven" / "target" / "compiled" / "cinderhaven" / "tests" / Path(path).name
            assert compiled.exists(), f"{compiled} missing: rebuild the harness world first"
            cur.execute(compiled.read_text(encoding="utf-8"))
            failing = cur.fetchall()
            assert len(failing) == len(bad), (failing, bad)
        else:
            cur.execute((ROOT / path).read_text(encoding="utf-8"))
            checks = [r[0] for r in cur.fetchall()]
            assert ("supplier invoices vs COGS outside 2pct" in checks) == bool(bad), (checks, bad)
    db.rollback()
