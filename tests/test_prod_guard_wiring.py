"""The prod guard sits in front of every write path to Postgres.

The seed scripts, seed_costing.py, ingest_sqlite_to_postgres.py and the Dagster
`dbt build` all default to localhost:5432 -- a `fly proxy` tunnel to production
when one is open. These tests fake a flyctl listener and assert nothing connects.

Run: python -m pytest -q tests/
"""

import importlib
import json
import sys
import types
import pathlib

import pytest

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "orchestration"))

import prod_guard  # noqa: E402  (scripts/prod_guard.py)
import psycopg2  # noqa: E402


@pytest.fixture
def fly_tunnel(monkeypatch):
    # Fake the port owner: the real lookup shells out to netstat and would see
    # whatever happens to be listening on this machine.
    monkeypatch.delenv("ALLOW_PROD_DB", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(prod_guard, "_listener", lambda port: "flyctl")
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **kw: pytest.fail("connected"))


def _fresh_import(name):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def test_seed_scripts_refuse_fly_tunnel_when_seed_config_loads(fly_tunnel):
    # All 8 seed scripts get DATABASE_URL from seed_config; importing it is the guard.
    with pytest.raises(prod_guard.ProdDatabaseError):
        _fresh_import("seed_config")


def test_seed_all_refuses_fly_tunnel_before_connecting(fly_tunnel):
    sys.modules.pop("seed_config", None)
    with pytest.raises(prod_guard.ProdDatabaseError):
        _fresh_import("seed_all")


def test_seed_costing_refuses_fly_tunnel_before_connecting(fly_tunnel):
    seed_costing = _fresh_import("seed_costing")
    with pytest.raises(prod_guard.ProdDatabaseError):
        seed_costing.main()


def test_ingest_refuses_fly_tunnel_on_the_configured_port(fly_tunnel, monkeypatch):
    ingest = _fresh_import("ingest_sqlite_to_postgres")
    monkeypatch.setattr(ingest, "_load_env", lambda: None)  # don't read the real .env
    monkeypatch.setenv("POSTGRES_PROXY_PORT", "15432")
    seen = []
    monkeypatch.setattr(prod_guard, "_listener", lambda port: seen.append(port) or "flyctl")
    with pytest.raises(prod_guard.ProdDatabaseError):
        ingest.get_pg_connection()
    assert seen == [15432], f"guard checked ports {seen}, expected [15432]"


def test_dagster_dbt_build_refuses_fly_tunnel_before_running_dbt(fly_tunnel, monkeypatch, tmp_path):
    dagster = pytest.importorskip("dagster")
    dagster_dbt = pytest.importorskip("dagster_dbt")
    from cinderhaven_orchestration import prod_guard as orch_guard

    monkeypatch.setattr(orch_guard, "_listener", lambda port: "flyctl")
    # assets.py runs `dbt parse` at import; hand it a one-model manifest instead
    # so the test needs neither dbt nor a database.
    manifest = {
        "metadata": {"dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json",
                     "project_name": "cinderhaven", "adapter_type": "postgres"},
        "nodes": {"model.cinderhaven.m": {
            "unique_id": "model.cinderhaven.m", "resource_type": "model", "name": "m",
            "package_name": "cinderhaven", "fqn": ["cinderhaven", "m"], "schema": "public",
            "database": "cinderhaven", "original_file_path": "models/m.sql",
            "config": {"materialized": "view", "meta": {}, "tags": []}, "meta": {}, "tags": [],
            "depends_on": {"nodes": []}, "description": "", "columns": {},
        }},
        "sources": {}, "exposures": {}, "metrics": {}, "semantic_models": {},
        "saved_queries": {}, "unit_tests": {}, "selectors": {}, "disabled": {},
        "child_map": {"model.cinderhaven.m": []}, "parent_map": {"model.cinderhaven.m": []},
        "group_map": {}, "groups": {},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(dagster_dbt.DbtCliResource, "cli",
                        lambda self, *a, **kw: types.SimpleNamespace(target_path=tmp_path))
    from cinderhaven_orchestration import project
    monkeypatch.setattr(project, "DBT_EXECUTABLE", sys.executable)  # resource checks the path exists
    assets = _fresh_import("cinderhaven_orchestration.assets")

    ran = []
    fake_dbt = types.SimpleNamespace(cli=lambda *a, **kw: ran.append(a) or pytest.fail("dbt ran"))
    context = dagster.build_asset_context()
    with pytest.raises(orch_guard.ProdDatabaseError):
        list(assets.cinderhaven_dbt_assets.op.compute_fn.decorated_fn(context, fake_dbt))
    assert ran == [], "dbt build ran despite the fly tunnel"
