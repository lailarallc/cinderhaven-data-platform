"""Path 5's check (plan U4): `dbt run-operation assert_scoped_login` on the harness.

It refuses the harness administrator, a superuser, and passes a fresh login in
cinderhaven_dbt, the shape of Dagster's cinderhaven_dagster.
"""
from __future__ import annotations

import secrets
import subprocess

import pytest

import harness

pytestmark = pytest.mark.db

LOGIN = "dagster_shape_probe"


def _run_operation(vals):
    return subprocess.run(harness.dbt_cmd("run-operation", "assert_scoped_login"),
                          cwd=harness.ROOT / "cinderhaven", env=harness.child_env(vals),
                          capture_output=True, text=True)


def test_the_check_refuses_a_superuser():
    r = _run_operation(harness.harness_values())
    assert r.returncode != 0 and "a superuser" in r.stdout + r.stderr


def test_the_check_passes_a_login_in_the_dbt_role(db):
    password = secrets.token_urlsafe(24)  # a test value for a throwaway harness login
    with db.cursor() as c:
        c.execute(f"DROP ROLE IF EXISTS {LOGIN}")
        c.execute(f"CREATE ROLE {LOGIN} LOGIN PASSWORD %s IN ROLE cinderhaven_dbt", (password,))
    db.commit()
    try:
        r = _run_operation(dict(harness.harness_values(), HARNESS_PG_USER=LOGIN, HARNESS_PG_PASSWORD=password))
        assert r.returncode == 0, r.stdout[-2000:]
        assert "is not a superuser and has no truth access" in r.stdout
    finally:
        with db.cursor() as c:
            c.execute(f"DROP ROLE IF EXISTS {LOGIN}")
        db.commit()
