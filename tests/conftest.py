"""Shared fixtures for the harness (U3).

`db` is session-scoped: one connection to the harness's off-host instance per
run. It fails, never skips, when the instance is unconfigured or unreachable,
so a database test cannot pass vacuously. Tests that use it carry the `db`
marker, which CI's fast tier excludes.
"""
from __future__ import annotations

import pytest

import harness


@pytest.fixture(scope="session")
def db():
    import psycopg2

    try:
        vals = harness.harness_values()
        harness.guard(vals)
    except harness.HarnessError as e:
        pytest.fail(f"harness database not available: {e}", pytrace=False)
    try:
        conn = psycopg2.connect(harness.dsn(vals), connect_timeout=5)
    except psycopg2.OperationalError as e:
        pytest.fail(f"harness database at {vals['HARNESS_PG_HOST']}:{vals['HARNESS_PG_PORT']} unreachable "
                    f"(start it: docker compose --env-file tests/harness.env up -d harness-db): "
                    f"{str(e).splitlines()[0]}", pytrace=False)
    yield conn
    conn.close()
