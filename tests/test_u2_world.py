"""Plan U2's test scenarios on a world seed_all.py built (database tier).

Each test reads the harness's rebuilt world, or plants a fixture inside a
transaction and rolls back. Needs a rebuilt world at run seed 0
(python tests/harness.py rebuild).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parent.parent
COPACK_FIVE = ("co_packers", "production_lines", "sku_production_config", "production_schedule", "sku_inventory")
READERS = ("cinderhaven_reader", "cinderhaven_validator", "cinderhaven_dbt")


@pytest.fixture
def cur(db):
    c = db.cursor()
    yield c
    db.rollback()
    c.close()


def _sku_tables(cur, schema):
    """Every table in `schema` with a sku column, read from the catalog the DDL built: no hand list."""
    cur.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'sku' AND NOT a.attisdropped "
                "WHERE n.nspname = %s AND c.relkind = 'r' ORDER BY 1", (schema,))
    return [r[0] for r in cur.fetchall()]


def _orphans(cur, schema, table):
    cur.execute(f"SELECT count(*) FROM {schema}.{table} t "
                "WHERE NOT EXISTS (SELECT 1 FROM raw.product_master p WHERE p.sku = t.sku)")
    return cur.fetchone()[0]


# -- one catalog: no orphan SKUs ---------------------------------------------

def test_every_costing_sku_exists_in_the_catalog(cur):
    tables = _sku_tables(cur, "costing")
    assert "fct_production_runs" in tables, tables  # the one tests/test_costing_integrity.sql omits
    assert {t: _orphans(cur, "costing", t) for t in tables} == {t: 0 for t in tables}


def test_every_copack_sku_exists_in_the_catalog(cur):
    tables = [t for t in _sku_tables(cur, "copack") if t in COPACK_FIVE]
    assert sorted(tables) == ["production_schedule", "sku_inventory", "sku_production_config"], tables
    assert {t: _orphans(cur, "copack", t) for t in tables} == {t: 0 for t in tables}


def test_the_orphan_check_catches_a_sku_the_catalog_lost(cur):
    # A raw-only reseed with a new catalog leaves costing keyed to old SKUs.
    cur.execute("UPDATE costing.fct_product_costs SET sku = 'CHP-XX-999' WHERE sku = "
                "(SELECT min(sku) FROM costing.fct_product_costs)")
    assert _orphans(cur, "costing", "fct_product_costs") > 0


# -- population ---------------------------------------------------------------

def test_product_master_history_holds_one_row_per_catalog_sku_per_snapshot_month(cur):
    cur.execute("SELECT count(*), count(DISTINCT sku), count(DISTINCT snapshot_date) FROM raw.product_master_history")
    rows, skus, months = cur.fetchone()
    cur.execute("SELECT count(*) FROM raw.product_master")
    catalog = cur.fetchone()[0]
    assert months > 0 and skus == catalog == 50 and rows == skus * months, (rows, skus, months, catalog)


def test_store_addresses_hold_exactly_one_row_per_store(cur):
    cur.execute("SELECT (SELECT count(*) FROM raw.stores), (SELECT count(*) FROM voidfinder.store_addresses), "
                "(SELECT count(*) FROM raw.stores s FULL JOIN voidfinder.store_addresses a "
                " ON a.store_id = s.store_id WHERE a.store_id IS NULL OR s.store_id IS NULL)")
    stores, addresses, unmatched = cur.fetchone()
    assert stores == addresses and unmatched == 0, (stores, addresses, unmatched)


# -- grants survive the rebuild ------------------------------------------------

@pytest.mark.parametrize("role", READERS)
@pytest.mark.parametrize("table", COPACK_FIVE)
def test_readers_can_select_each_recreated_copack_table(cur, role, table):
    cur.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", (role, f"copack.{table}"))
    assert cur.fetchone()[0], f"{role} lost SELECT on copack.{table}"


# -- the DDL step leaves other repos' tables alone ------------------------------

def test_the_ddl_step_keeps_copack_and_edi_stand_ins_byte_identical(db, monkeypatch):
    """seed_all's DDL step is the only step that drops; run it in a transaction over
    stand-ins for production-demand-forecast's snapshot tables and the edi_* schemas."""
    monkeypatch.setenv("DATABASE_URL", db.dsn)
    sys.path.insert(0, str(ROOT / "generation"))
    for m in ("seed_config", "seed_all"):
        sys.modules.pop(m, None)
    import seed_all

    class NoCommit:  # execute_ddl commits; the test rolls the whole step back instead
        def cursor(self):
            return db.cursor()

        def commit(self):
            pass

    stand_ins = ["copack.forecast_snapshot_dg", "edi_raw.dg_fixture", "edi_staging.dg_fixture",
                 "edi_marts.dg_fixture"]
    cur = db.cursor()
    try:
        for schema in ("edi_raw", "edi_staging", "edi_marts"):
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        for t in stand_ins:
            cur.execute(f"CREATE TABLE {t} (k int, v text)")
            cur.execute(f"INSERT INTO {t} VALUES (1, 'a'), (2, 'b')")
        cur.execute("SELECT oid FROM pg_namespace WHERE nspname = 'copack'")
        copack_oid = cur.fetchone()[0]
        before = {}
        for t in stand_ins:
            cur.execute(f"SELECT md5(string_agg(x::text, '|' ORDER BY x::text)) FROM {t} x")
            before[t] = cur.fetchone()[0]

        seed_all.execute_ddl(NoCommit())

        cur.execute("SELECT oid FROM pg_namespace WHERE nspname = 'copack'")
        assert cur.fetchone()[0] == copack_oid, "schema copack was dropped and recreated"
        for t in stand_ins:
            cur.execute(f"SELECT md5(string_agg(x::text, '|' ORDER BY x::text)) FROM {t} x")
            assert cur.fetchone()[0] == before[t], f"{t} changed"
    finally:
        db.rollback()
        cur.close()


# -- truth: a boolean, never a count -------------------------------------------

def test_verify_counts_reports_truth_as_populated_and_prints_no_truth_count(db, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", db.dsn)
    sys.path.insert(0, str(ROOT / "generation"))
    for m in ("seed_config", "seed_all"):
        sys.modules.pop(m, None)
    import seed_all
    cur = db.cursor()
    try:
        cur.execute("CREATE TABLE truth.dg_fixture (x int)")
        cur.execute("ALTER TABLE truth.dg_fixture OWNER TO cinderhaven_generator")
        cur.execute("INSERT INTO truth.dg_fixture SELECT generate_series(1, 37)")
        seed_all.verify_counts(db)
    finally:
        db.rollback()
        cur.close()
    out = capsys.readouterr().out
    truth_lines = [line for line in out.splitlines() if "truth" in line]
    assert truth_lines == ["  truth populated: yes"], truth_lines
