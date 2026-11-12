"""sql/drop_guard.sql against fixtures on the harness instance (plan U2).

Each test plants its fixture inside a transaction as the harness administrator,
runs the guard, and rolls back: the world is left as it was. The inputs are
built the way deploy-costing.yml's Step 0 builds them: the reference columns
from sql/raw_schema.sql applied to a scratch schema, the expected relations
from that DDL and dbt's manifest. Needs a rebuilt world.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parent.parent
GUARD = (ROOT / "sql" / "drop_guard.sql").read_text(encoding="utf-8")
RAW_DDL = (ROOT / "sql" / "raw_schema.sql").read_text(encoding="utf-8")
MANIFEST = ROOT / "cinderhaven" / "target" / "manifest.json"
COPACK_FIVE = ("co_packers", "production_lines", "sku_production_config", "production_schedule", "sku_inventory")

# The column map, as Step 0 reads it from the reference DDL on a scratch instance.
REF_COLUMNS_SQL = """
SELECT json_object_agg(relname, cols) FROM (
  SELECT c.relname, json_agg(a.attname ORDER BY a.attnum) AS cols
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
  WHERE n.nspname = %s AND c.relkind = 'r' GROUP BY c.relname) t
"""


def _manifest_relations() -> list[str]:
    nodes = json.loads(MANIFEST.read_text(encoding="utf-8"))["nodes"].values()
    return sorted(f'{n["schema"]}.{n.get("alias") or n["name"]}' for n in nodes
                  if n["resource_type"] in ("model", "seed", "snapshot")
                  and n["config"].get("materialized") != "ephemeral")


@pytest.fixture(scope="module")
def inputs(db):
    """The reference column map and expected list, from the DDL itself, not a parser."""
    with db.cursor() as c:
        scratch = re.sub(r"\braw\.", "dg_reference.", RAW_DDL)
        scratch = scratch.replace("DROP SCHEMA IF EXISTS raw CASCADE", "DROP SCHEMA IF EXISTS dg_reference CASCADE")
        scratch = scratch.replace("CREATE SCHEMA raw", "CREATE SCHEMA dg_reference")
        c.execute(scratch)
        c.execute(REF_COLUMNS_SQL, ("dg_reference",))
        ref = c.fetchone()[0]
    db.rollback()
    assert len(ref) == 41, f"reference DDL gave {len(ref)} raw tables, expected 41"
    expected = [f"raw.{t}" for t in sorted(ref)] + _manifest_relations()
    return {"raw_reference": json.dumps(ref), "expected": ",".join(expected)}


@pytest.fixture
def cur(db):
    c = db.cursor()
    yield c
    db.rollback()
    c.close()


def run_guard(cur, inputs, force=False, leftover="", omit=()):
    settings = dict(inputs, leftover=leftover, force_recreate="true" if force else "false")
    for name, value in settings.items():
        if name not in omit:
            cur.execute("SELECT set_config(%s, %s, true)", (f"drop_guard.{name}", value))
    cur.execute(GUARD)
    return [r[0] for r in cur.fetchall()]


def test_the_rebuilt_world_passes_with_force_recreate(cur, inputs):
    # Equal to the reference, every relation the platform's: nothing but the populated arm.
    assert run_guard(cur, inputs, force=True) == []


def test_every_populated_generated_table_refuses_by_name_without_force_recreate(cur, inputs):
    got = run_guard(cur, inputs)
    cur.execute("SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE c.relkind = 'r' AND (n.nspname IN ('raw', 'costing') "
                "OR (n.nspname = 'copack' AND c.relname = ANY (%s)))", (list(COPACK_FIVE),))
    tables = sorted(r[0] for r in cur.fetchall())
    assert len(tables) == 54, f"expected raw 41 + costing 8 + copack 5, found {len(tables)}"
    want = sorted(f"populated: {t} (re-dispatch with force_recreate to drop it)" for t in tables)
    assert sorted(got) == want


def test_a_fresh_instance_returns_zero_rows(cur, inputs):
    for schema in ("raw", "costing", "truth", "public_staging", "public_intermediate", "public_marts"):
        cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    cur.execute("DROP TABLE " + ", ".join(f"copack.{t}" for t in COPACK_FIVE))
    assert run_guard(cur, inputs) == []


def test_no_truth_schema_passes_the_truth_arm(cur, inputs):
    cur.execute("DROP SCHEMA truth CASCADE")
    assert run_guard(cur, inputs, force=True) == []


def test_a_populated_truth_refuses_without_force_and_prints_no_count(cur, inputs):
    cur.execute("CREATE TABLE truth.dg_fixture (x int)")
    # truth's tables are the generator's (truth_populated() runs as it); one the
    # generator could not read would be "unreadable", the test below.
    cur.execute("ALTER TABLE truth.dg_fixture OWNER TO cinderhaven_generator")
    cur.execute("INSERT INTO truth.dg_fixture VALUES (1), (2), (3)")
    got = [r for r in run_guard(cur, inputs) if r.startswith("truth")]
    assert got == ["truth: populated (re-dispatch with force_recreate to drop it)"]
    assert run_guard(cur, inputs, force=True) == []


def test_a_truth_schema_whose_state_cannot_be_read_refuses_even_with_force(cur, inputs):
    cur.execute("DROP FUNCTION public.truth_populated()")
    assert run_guard(cur, inputs, force=True) == [
        "truth: schema present, populated state unreadable (public.truth_populated())"]


def test_a_login_without_the_truth_boolean_is_refused(cur, inputs):
    # cinderhaven_dbt holds no EXECUTE on truth_populated(); it may read raw.
    cur.execute("SET LOCAL ROLE cinderhaven_dbt")
    got = run_guard(cur, inputs, force=True)
    assert "truth: schema present, populated state unreadable (public.truth_populated())" in got


def test_a_consumer_table_in_public_marts_refuses_with_and_without_force(cur, inputs):
    cur.execute("CREATE SCHEMA IF NOT EXISTS public_marts")
    cur.execute("CREATE TABLE public_marts.q12_summary (sku text)")
    want = ("not the platform's: public_marts.q12_summary (absent from raw_schema.sql and the dbt manifest; "
            "name it in the leftover list once U19 records it)")
    assert run_guard(cur, inputs, force=True) == [want]
    assert want in run_guard(cur, inputs)


def test_contract_to_cash_column_set_refuses_even_with_force(cur, inputs):
    # contract-to-cash recreates the table without these three (CASCADE takes the staging view).
    cur.execute("ALTER TABLE raw.shopify_transactions DROP COLUMN platform_fee CASCADE, "
                "DROP COLUMN gateway CASCADE, DROP COLUMN card_brand CASCADE")
    assert run_guard(cur, inputs, force=True) == [
        "columns differ from the pre-regen reference: raw.shopify_transactions "
        "(missing: card_brand, gateway, platform_fee; extra: none)"]


def test_a_column_a_consumer_added_refuses(cur, inputs):
    cur.execute("ALTER TABLE raw.stores ADD COLUMN category text")
    assert run_guard(cur, inputs, force=True) == [
        "columns differ from the pre-regen reference: raw.stores (missing: none; extra: category)"]


def test_the_leftover_list_passes_what_it_names_and_nothing_else(cur, inputs):
    cur.execute("CREATE SCHEMA IF NOT EXISTS public_marts")
    cur.execute("CREATE TABLE public_marts.q12_summary (sku text)")
    cur.execute("CREATE TABLE public.dg_unlisted (x int)")
    cur.execute("ALTER TABLE raw.shopify_transactions DROP COLUMN gateway CASCADE")
    got = run_guard(cur, inputs, force=True,
                    leftover="public_marts.q12_summary, raw.shopify_transactions")
    assert got == ["not the platform's: public.dg_unlisted (absent from raw_schema.sql and the dbt manifest; "
                   "name it in the leftover list once U19 records it)"]


@pytest.mark.parametrize("missing", ["expected", "raw_reference"])
def test_a_missing_input_refuses(cur, inputs, missing):
    got = run_guard(cur, inputs, force=True, omit=(missing,))
    assert len(got) == 1 and got[0].startswith(f"input missing: drop_guard.{missing}")
