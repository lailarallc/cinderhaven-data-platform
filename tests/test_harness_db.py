"""Database tier: needs a rebuilt world on the harness instance (python tests/harness.py rebuild)."""
from __future__ import annotations

from pathlib import Path

import psycopg2
import pytest

pytestmark = pytest.mark.db

INTEGRITY_SQL = (Path(__file__).parent / "test_costing_integrity.sql").read_text()


def test_db_fixture_connects_to_the_harness_instance(db):
    # The database is named cinderhaven (dbt's sources pin it); what makes it
    # the harness's is the login, which is the generated test user.
    with db.cursor() as cur:
        cur.execute("SELECT current_user")
        assert cur.fetchone()[0].startswith("harness_"), "connected as a login that is not the harness test set"


def test_costing_integrity_suite_returns_no_failing_checks(db):
    with db.cursor() as cur:
        cur.execute(INTEGRITY_SQL)
        failures = cur.fetchall()
    db.rollback()
    assert failures == [], f"integrity failures: {failures}"


def test_costing_integrity_suite_breaks_when_a_table_it_reads_is_removed(db):
    # A vacuous pass is impossible: drop a table inside a transaction, the suite
    # must error, then roll back so the world is untouched.
    with db.cursor() as cur:
        cur.execute("DROP TABLE costing.fct_lot_shipments CASCADE")
        with pytest.raises(psycopg2.errors.UndefinedTable):
            cur.execute(INTEGRITY_SQL)
    db.rollback()
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('costing.fct_lot_shipments') IS NOT NULL")
        assert cur.fetchone()[0], "rollback did not restore costing.fct_lot_shipments"
