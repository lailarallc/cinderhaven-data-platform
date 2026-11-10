"""scripts/apply_truth_roles.py against a scratch database on the harness instance.

The scratch database stands in for production: schemas that predate the roles,
owned by the administrator. It is created and dropped by the test.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest

import harness

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parent.parent
PROBE_DB = "apply_roles_probe"


@pytest.fixture
def probe():
    vals = harness.harness_values()
    admin = psycopg2.connect(harness.dsn(vals), connect_timeout=5)
    admin.autocommit = True
    with admin.cursor() as c:
        c.execute(f"DROP DATABASE IF EXISTS {PROBE_DB}")
        c.execute(f"CREATE DATABASE {PROBE_DB}")
    probe_vals = dict(vals, HARNESS_PG_DB=PROBE_DB)
    with psycopg2.connect(harness.dsn(probe_vals)) as conn, conn.cursor() as c:
        c.execute("CREATE SCHEMA raw; CREATE TABLE raw.stores (store_id text PRIMARY KEY);"
                  "CREATE SCHEMA costing; CREATE TABLE costing.fct_product_costs (sku text);")
    conn.close()
    yield probe_vals
    with admin.cursor() as c:
        c.execute(f"DROP DATABASE IF EXISTS {PROBE_DB} WITH (FORCE)")
    admin.close()


def _run(vals, *args, stdin=""):
    env = harness.child_env(vals)
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "apply_truth_roles.py"), *args],
                          input=stdin, capture_output=True, text=True, env=env, cwd=ROOT)


def _owner(vals, schema):
    with psycopg2.connect(harness.dsn(vals)) as conn, conn.cursor() as c:
        c.execute("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s", (schema,))
        owner = c.fetchone()[0]
    conn.close()
    return owner


def test_the_dry_run_prints_every_transfer_and_grant_and_changes_nothing(probe):
    before = _owner(probe, "raw")
    r = _run(probe)
    assert r.returncode == 0, r.stderr
    assert "BACKUP" in r.stdout
    assert f"ALTER SCHEMA raw OWNER: {before} -> cinderhaven_generator" in r.stdout
    assert f"ALTER TABLE raw.stores OWNER: {before} -> cinderhaven_generator" in r.stdout
    assert f"ALTER TABLE costing.fct_product_costs OWNER: {before} -> cinderhaven_generator" in r.stdout
    assert "schema copack: absent here" in r.stdout
    assert "Dry run: nothing changed" in r.stdout
    assert _owner(probe, "raw") == before


def test_the_dsn_is_never_printed(probe):
    r = _run(probe)
    assert probe["HARNESS_PG_PASSWORD"] not in r.stdout + r.stderr


def test_apply_without_the_typed_confirmation_changes_nothing(probe):
    before = _owner(probe, "raw")
    r = _run(probe, "--apply", stdin="yes\n")
    assert r.returncode == 1 and "nothing changed" in r.stdout
    assert _owner(probe, "raw") == before


def test_apply_with_the_confirmation_transfers_ownership(probe):
    r = _run(probe, "--apply", stdin="APPLY\n")
    assert r.returncode == 0, r.stderr
    assert _owner(probe, "raw") == "cinderhaven_generator"
    assert _owner(probe, "costing") == "cinderhaven_generator"
    again = _run(probe)  # idempotent: a second dry run proposes no new roles
    assert "CREATE ROLE" not in again.stdout


def test_an_existing_role_is_never_taken_over_as_dagsters_login(probe):
    r = _run(probe, "--dagster-login", probe["HARNESS_PG_USER"])
    assert r.returncode != 0 and "exists" in (r.stdout + r.stderr)


def test_the_dbt_schemas_go_to_the_dbt_role(probe):
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute("CREATE SCHEMA public_marts; CREATE TABLE public_marts.fct_x (x int)")
    conn.close()
    assert "ALTER SCHEMA public_marts OWNER" in _run(probe).stdout
    assert _run(probe, "--apply", stdin="APPLY\n").returncode == 0
    assert _owner(probe, "public_marts") == "cinderhaven_dbt"


def test_dagsters_login_is_created_once_shown_once_and_works(probe):
    name = "dagster_probe"
    dry = _run(probe, "--dagster-login", name)
    assert f"CREATE ROLE {name} LOGIN NOSUPERUSER" in dry.stdout and "shown once" in dry.stdout
    r = _run(probe, "--apply", "--dagster-login", name, stdin="APPLY\n")
    try:
        assert r.returncode == 0, r.stderr
        lines = r.stdout.splitlines()
        password = lines[lines.index(next(l for l in lines if "shown ONCE" in l)) + 3].strip()
        # The password works as a login, and the login is a non-superuser member of the dbt role.
        login = dict(probe, HARNESS_PG_USER=name, HARNESS_PG_PASSWORD=password)
        with psycopg2.connect(harness.dsn(login)) as conn, conn.cursor() as c:
            c.execute("SELECT rolsuper, pg_has_role(current_user, 'cinderhaven_dbt', 'MEMBER') "
                      "FROM pg_roles WHERE rolname = current_user")
            assert c.fetchone() == (False, True)
        conn.close()
        # Stored as a SCRAM verifier, never the plaintext.
        with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
            c.execute("SELECT rolpassword LIKE 'SCRAM-SHA-256$%%' FROM pg_authid WHERE rolname = %s", (name,))
            assert c.fetchone()[0] is True
        conn.close()
        # A second run refuses to reset it.
        assert _run(probe, "--dagster-login", name).returncode != 0
    finally:
        with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
            c.execute(f"DROP ROLE IF EXISTS {name}")
        conn.close()


def test_a_workflow_reader_login_is_created_in_the_reader_role(probe):
    name = "workflow_reader_probe"
    r = _run(probe, "--apply", "--reader-login", name, stdin="APPLY\n")
    try:
        assert r.returncode == 0, r.stderr
        assert f"Login {name} (cinderhaven_reader)" in r.stdout
        with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
            c.execute("SELECT rolsuper, rolcanlogin, pg_has_role(%s, 'cinderhaven_reader', 'MEMBER'), "
                      "pg_has_role(%s, 'cinderhaven_dbt', 'MEMBER') FROM pg_roles WHERE rolname = %s",
                      (name, name, name))
            assert c.fetchone() == (False, True, True, False)
        conn.close()
    finally:
        with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
            c.execute(f"DROP ROLE IF EXISTS {name}")
        conn.close()
