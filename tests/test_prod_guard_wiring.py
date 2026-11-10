"""The prod guard sits in front of every write path to Postgres.

The seed scripts (generation/), seed_costing.py, ingest_sqlite_to_postgres.py and the Dagster
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
sys.path.insert(0, str(ROOT / "scripts"))  # ingest_sqlite_to_postgres.py
sys.path.insert(0, str(ROOT / "generation"))  # the seeders (U4 moved them out of scripts/)
sys.path.insert(0, str(ROOT / "orchestration"))

import prod_guard  # noqa: E402  (generation/prod_guard.py; the copies are byte-identical, tested below)
import psycopg2  # noqa: E402

GUARD_COPIES = ("scripts/prod_guard.py", "generation/prod_guard.py",
                "orchestration/cinderhaven_orchestration/prod_guard.py")


def test_the_vendored_prod_guard_copies_are_byte_identical():
    texts = {p: (ROOT / p).read_bytes().replace(b"\r\n", b"\n") for p in GUARD_COPIES}
    assert len(set(texts.values())) == 1, f"prod_guard copies differ: {sorted(texts)}"


def test_every_seeder_lives_in_generation_and_none_in_scripts():
    assert not list((ROOT / "scripts").glob("seed_*.py")), "a seeder is back in scripts/"
    assert len(list((ROOT / "generation").glob("seed_*.py"))) == 10


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


def _load_assets(monkeypatch, tmp_path):
    """Import assets.py with a one-model manifest and a faked dbt CLI: no dbt, no database."""
    dagster_dbt = pytest.importorskip("dagster_dbt")
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
    # project.py points at ~/.dbt, a machine-local profile CI does not have (Dagster's
    # credential lives there, owner 2026-11-09); the resource only checks a profiles.yml is there.
    (tmp_path / "profiles.yml").write_text("cinderhaven: {}\n")
    monkeypatch.setattr(project, "DBT_PROFILES_DIR", tmp_path)
    assets = _fresh_import("cinderhaven_orchestration.assets")
    return assets


def test_dagster_dbt_build_refuses_fly_tunnel_before_running_dbt(fly_tunnel, monkeypatch, tmp_path):
    dagster = pytest.importorskip("dagster")
    from cinderhaven_orchestration import prod_guard as orch_guard

    monkeypatch.setattr(orch_guard, "_listener", lambda port: "flyctl")
    assets = _load_assets(monkeypatch, tmp_path)

    ran = []
    fake_dbt = types.SimpleNamespace(cli=lambda *a, **kw: ran.append(a) or pytest.fail("dbt ran"))
    context = dagster.build_asset_context()
    with pytest.raises(orch_guard.ProdDatabaseError):
        list(assets.cinderhaven_dbt_assets.op.compute_fn.decorated_fn(context, fake_dbt))
    assert ran == [], "dbt build ran despite the fly tunnel"


def test_dagster_checks_the_login_before_it_builds(monkeypatch, tmp_path):
    # Path 5 (plan U4): run-operation assert_scoped_login runs, and finishes,
    # before `dbt build` starts. A local, non-fly listener lets the guard pass.
    dagster = pytest.importorskip("dagster")
    from cinderhaven_orchestration import prod_guard as orch_guard
    monkeypatch.delenv("ALLOW_PROD_DB", raising=False)
    monkeypatch.setattr(orch_guard, "_listener", lambda port: "postgres")
    assets = _load_assets(monkeypatch, tmp_path)

    calls = []

    def cli(args, **kw):
        calls.append(args[0])
        return types.SimpleNamespace(wait=lambda: calls.append("waited"),
                                     stream=lambda: iter(()))
    context = dagster.build_asset_context()
    list(assets.cinderhaven_dbt_assets.op.compute_fn.decorated_fn(context, types.SimpleNamespace(cli=cli)))
    assert calls == ["run-operation", "waited", "build"], calls
