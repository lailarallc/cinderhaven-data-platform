"""The roles that quarantine truth (plan U4), on the harness instance.

Each check runs as the harness administrator, switches to the role under test
with SET LOCAL ROLE inside a transaction, and rolls back: no logins are made and
the world is left as it was. Needs a rebuilt world (python tests/harness.py rebuild).
"""
from __future__ import annotations

import re
from pathlib import Path

import psycopg2
import pytest

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parent.parent
TRUTH_DDL = (ROOT / "sql" / "truth_schema.sql").read_text()
ROLES_SQL = (ROOT / "sql" / "truth_roles.sql").read_text()
TRUTH_TABLES = re.findall(r"CREATE TABLE truth\.(\w+)", TRUTH_DDL)
ROLES = ("cinderhaven_generator", "cinderhaven_dbt", "cinderhaven_reader", "cinderhaven_validator")


@pytest.fixture
def cur(db):
    c = db.cursor()
    yield c
    db.rollback()
    c.close()


def _as(cur, role, sql, params=None):
    cur.execute(f"SET LOCAL ROLE {role}")
    cur.execute(sql, params)


def _denied(db, role, sql):
    with db.cursor() as c:
        try:
            _as(c, role, sql)
        except psycopg2.errors.InsufficientPrivilege:
            return True
        finally:
            db.rollback()
    return False


def test_the_truth_ddl_creates_six_tables():
    assert sorted(TRUTH_TABLES) == sorted(["injection_ledger", "corruption_ledger", "promo_events",
                                           "outage_episodes", "defect_ledger", "consequence_chains"])


@pytest.mark.parametrize("role", ["cinderhaven_reader", "cinderhaven_dbt"])
@pytest.mark.parametrize("table", TRUTH_TABLES)
def test_reader_and_dbt_roles_cannot_select_any_truth_table(db, role, table):
    assert _denied(db, role, f"SELECT 1 FROM truth.{table} LIMIT 1"), f"{role} read truth.{table}"


@pytest.mark.parametrize("role", ["cinderhaven_generator", "cinderhaven_validator"])
@pytest.mark.parametrize("table", TRUTH_TABLES)
def test_generator_and_validator_can_select_every_truth_table(cur, role, table):
    _as(cur, role, f"SELECT 1 FROM truth.{table} LIMIT 1")


@pytest.mark.parametrize("sql", [
    "INSERT INTO truth.defect_ledger (sku, defect_type) VALUES ('x', 'y')",
    "DELETE FROM raw.stores",
    "DELETE FROM costing.fct_product_costs",
    "DELETE FROM voidfinder.store_addresses",
    "CREATE TABLE raw.validator_probe (x int)",
])
def test_the_validator_writes_nothing(db, sql):
    assert _denied(db, "cinderhaven_validator", sql)


def test_only_the_generator_writes_truth(cur):
    _as(cur, "cinderhaven_generator",
        "INSERT INTO truth.defect_ledger (sku, defect_type) VALUES ('probe', 'probe')")


@pytest.mark.parametrize("schema_table", ["raw.stores", "costing.fct_product_costs",
                                          "voidfinder.store_addresses"])
def test_the_reader_reads_the_generated_schemas(cur, schema_table):
    _as(cur, "cinderhaven_reader", f"SELECT 1 FROM {schema_table} LIMIT 1")


def test_the_reader_reads_the_dbt_models(cur):
    cur.execute("SELECT schemaname || '.' || tablename FROM pg_tables WHERE schemaname = 'public_marts' LIMIT 1")
    mart = cur.fetchone()[0]
    _as(cur, "cinderhaven_reader", f"SELECT 1 FROM {mart} LIMIT 1")


def test_truth_populated_is_a_boolean_and_false_on_an_empty_truth(cur):
    _as(cur, "cinderhaven_reader", "SELECT public.truth_populated()")
    assert cur.fetchone()[0] is False


def test_truth_populated_turns_true_on_one_row(cur):
    cur.execute("INSERT INTO truth.defect_ledger (sku, defect_type) VALUES ('probe', 'probe')")
    _as(cur, "cinderhaven_reader", "SELECT public.truth_populated()")
    assert cur.fetchone()[0] is True


def test_truth_populated_is_false_where_truth_does_not_exist(cur):
    cur.execute("DROP SCHEMA truth CASCADE")
    _as(cur, "cinderhaven_reader", "SELECT public.truth_populated()")
    assert cur.fetchone()[0] is False


@pytest.mark.parametrize("bad", [
    "preventable_by = 'manual_review'",
    "cost_if_caught = 0",
    "cost_if_caught = 0.0199",
    "benchmark_detection_rate = 1",
])
def test_injection_ledger_rejects_values_outside_its_constraints(db, bad):
    col, val = (p.strip() for p in bad.split("="))
    with db.cursor() as c:
        with pytest.raises(psycopg2.errors.CheckViolation):
            c.execute(f"INSERT INTO truth.injection_ledger (row_class, occurred_date, actor, error_type, "
                      f"entity_type, entity_id, {col}) VALUES ('injected_error', '2024-01-01', 'retailer', "
                      f"'duplicate_deduction', 'deduction', 'D1', {val})")
    db.rollback()


def test_applying_the_roles_twice_leaves_one_set(cur):
    cur.execute(ROLES_SQL)
    cur.execute(ROLES_SQL)
    cur.execute("SELECT rolname, rolcanlogin, rolsuper FROM pg_roles WHERE rolname LIKE 'cinderhaven\\_%' "
                "ORDER BY 1")
    assert cur.fetchall() == [(r, False, False) for r in sorted(ROLES)]


def test_rebuilding_raw_and_costing_keeps_the_readers_grants(cur):
    cur.execute((ROOT / "sql" / "raw_schema.sql").read_text())
    cur.execute((ROOT / "sql" / "costing_schema.sql").read_text())
    cur.execute("SELECT has_table_privilege('cinderhaven_reader', 'raw.stores', 'SELECT'), "
                "has_table_privilege('cinderhaven_reader', 'costing.fct_product_costs', 'SELECT'), "
                "has_schema_privilege('cinderhaven_reader', 'truth', 'USAGE')")
    assert cur.fetchone() == (True, True, False)


def test_rerunning_the_voidfinder_seeder_keeps_the_readers_grants(cur):
    import seed_void_patterns
    seed_void_patterns.seed_addresses(cur)
    cur.execute("SELECT has_table_privilege('cinderhaven_reader', 'voidfinder.store_addresses', 'SELECT')")
    assert cur.fetchone()[0] is True


def test_cost_if_caught_is_a_ratio_at_or_above_a612s_floor(cur):
    # A6.12: a ratio, floor 0.02; dollars are derived at read, so a dollar figure
    # does not fit the column.
    cur.execute("INSERT INTO truth.injection_ledger (row_class, occurred_date, actor, error_type, entity_type, "
                "entity_id, expected_cost, cost_if_caught) VALUES ('injected_error', '2024-01-01', 'retailer', "
                "'duplicate_deduction', 'deduction', 'D1', 400.00, 0.02) RETURNING cost_if_caught * expected_cost")
    assert float(cur.fetchone()[0]) == 8.0
    with pytest.raises(psycopg2.errors.NumericValueOutOfRange):
        cur.execute("INSERT INTO truth.injection_ledger (row_class, occurred_date, actor, error_type, "
                    "entity_type, entity_id, cost_if_caught) VALUES ('injected_error', '2024-01-01', 'retailer', "
                    "'duplicate_deduction', 'deduction', 'D2', 120.00)")
