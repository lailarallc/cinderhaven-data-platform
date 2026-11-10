"""dbt's truth checks (plan U4) on synthetic manifests and compiled SQL.

The CI job `dbt-quarantine` runs the same checks on the real project after
`dbt compile`, and on a copy with tests/fixtures/dbt_lineage's models planted.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from quarantine import dbt_lineage
from quarantine.dbt_lineage import LineageViolation, check_compiled, check_lineage

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "dbt_lineage"
SRC = "source.cinderhaven.truth.injection_ledger"


def _node(uid, deps, path, rtype="model", schema="public_marts"):
    return uid, {"resource_type": rtype, "depends_on": {"nodes": deps}, "original_file_path": path,
                 "schema": schema}


def _manifest(*nodes):
    return {"sources": {SRC: {"source_name": "truth"},
                        "source.cinderhaven.raw.stores": {"source_name": "raw"}},
            "nodes": dict(nodes)}


def test_a_model_that_sources_truth_into_public_marts_fails_the_walk():
    # The bypass a schema-location test misses.
    m = _manifest(_node("model.c.fct_innocuous", [SRC], "models/marts/fct_innocuous.sql"))
    with pytest.raises(LineageViolation, match="fct_innocuous"):
        check_lineage(m)


def test_a_transitive_dependency_fails_the_walk():
    m = _manifest(_node("model.c.a", [SRC], "models/a.sql"),
                  _node("model.c.b", ["model.c.a"], "models/b.sql"),
                  _node("model.c.c", ["model.c.b"], "models/c.sql"))
    with pytest.raises(LineageViolation) as e:
        check_lineage(m)
    assert all(f"model.c.{x}" in str(e.value) for x in "abc")


@pytest.mark.parametrize("rtype", ["snapshot", "analysis", "seed", "test"])
def test_the_walk_covers_every_resource_type(rtype):
    m = _manifest(_node(f"{rtype}.c.x", [SRC], f"x/{rtype}.sql", rtype=rtype))
    with pytest.raises(LineageViolation):
        check_lineage(m)


def test_a_clean_manifest_passes():
    check_lineage(_manifest(_node("model.c.ok", ["source.cinderhaven.raw.stores"], "models/ok.sql")))


def test_the_named_exemption_passes_and_nothing_else_does():
    exempt = _node("model.c.mart_counterfactual", [SRC], "models/counterfactual/mart_counterfactual.sql",
                   schema="counterfactual")
    check_lineage(_manifest(exempt))
    with pytest.raises(LineageViolation):
        check_lineage(_manifest(exempt, _node("model.c.copy", ["model.c.mart_counterfactual"], "models/copy.sql")))


def test_a_model_materializing_into_a_truth_schema_fails():
    with pytest.raises(LineageViolation, match="materializes"):
        check_lineage(_manifest(_node("model.c.m", [], "models/m.sql", schema="truth_derived")))


def test_an_empty_manifest_is_refused():
    with pytest.raises(ValueError):
        check_lineage({"nodes": {}, "sources": {}})


def test_a_literal_truth_table_registers_no_edge_and_fails_the_compiled_scan(tmp_path):
    # The literal model passes the walk (no depends_on edge) ...
    check_lineage(_manifest(_node("model.c.mart_literal_truth", [], "models/marts/mart_literal_truth.sql")))
    # ... and fails the compiled-SQL scan.
    d = tmp_path / "compiled" / "cinderhaven" / "models" / "marts"
    d.mkdir(parents=True)
    shutil.copy(FIX / "mart_literal_truth.sql", d / "mart_literal_truth.sql")
    shutil.copy(FIX / "mart_clean.sql", d / "mart_clean.sql")
    with pytest.raises(LineageViolation, match="mart_literal_truth"):
        check_compiled(tmp_path / "compiled")


def test_the_compiled_scan_passes_clean_sql_and_refuses_an_empty_dir(tmp_path):
    d = tmp_path / "compiled"
    d.mkdir()
    with pytest.raises(ValueError):
        check_compiled(d)
    shutil.copy(FIX / "mart_clean.sql", d / "mart_clean.sql")
    check_compiled(d)


def test_the_dbt_exemption_list_matches_the_logged_decision():
    assert dbt_lineage.DBT_EXEMPT == ("cinderhaven/models/counterfactual/mart_counterfactual.sql",), (
        "the dbt exemption list changed: that needs a DECISIONS entry, not a test edit")
    assert all(e.endswith(".sql") for e in dbt_lineage.DBT_EXEMPT)
