"""scripts/move_writer_tables.py on the harness: survey, backup, plan, typed MOVE, one transaction, PASS/FAIL.

Stands in for production: a scratch database on the harness instance holding the writers' relations
where production held them on 2026-11-17 (reader run 44197572155), plus the two that only an old
seeder run would leave (retail-velocity-decision-tool's benchmarks, the-question-engine's q12 tables);
a temp .env holding the harness's test credentials; a fake gh for the deploy-order check; a fake docker
for the backup (rotate_and_place's own tests run the real pg_dump). No real credential is involved.
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
PROBE_DB = "move_writers_probe"
LOGINS = ("cinderhaven_demand_forecast", "retail_velocity_decision_tool")
NEW_DBPY = 'options="-c search_path=production_demand_forecast,copack,raw,public"\n'
OLD_DBPY = 'options="-c search_path=copack,raw,public"\n'
FAKE_GH = """import base64, sys
from pathlib import Path
here = Path(sys.argv[0]).parent
args = sys.argv[1:]
dbpy = here / "deployed_db.py"
if args[:2] == ["run", "list"]:
    print("abc1234def" if dbpy.exists() else "")
elif args[:1] == ["api"]:
    print(base64.b64encode(dbpy.read_bytes()).decode())
"""
FAKE_DOCKER = """import sys
from pathlib import Path
if (Path(sys.argv[0]).parent / "docker_fails").exists():
    sys.exit(1)
if "pg_dump" in sys.argv:
    during = Path(sys.argv[0]).parent / "during_dump.sql"  # what production does while the dump runs
    if during.exists():
        import psycopg2
        with psycopg2.connect((Path(sys.argv[0]).parent / "dsn").read_text()) as conn, conn.cursor() as c:
            c.execute(during.read_text())
        conn.close()
    sys.stdout.write("fake dump")
elif "pg_restore" in sys.argv:
    sys.stdin.read()
    print("1; 0 0 TABLE DATA copack forecast_snapshot")
"""
WORLD = """
CREATE SCHEMA raw; CREATE SCHEMA copack; CREATE SCHEMA public_staging; CREATE SCHEMA public_intermediate;
CREATE SCHEMA public_marts; CREATE SCHEMA public_public_marts; CREATE SCHEMA public_public_staging;
CREATE SCHEMA public_public_intermediate;
CREATE TABLE raw.shopify_transactions (transaction_id text, platform_fee numeric, gateway text);
CREATE TABLE copack.co_packers (id int);
CREATE TABLE copack.forecast_snapshot AS SELECT g AS sku FROM generate_series(1, 50) g;
CREATE TABLE copack.forecast_week_snapshot AS SELECT g AS sku FROM generate_series(1, 600) g;
CREATE TABLE copack.doom_loop_snapshot AS SELECT g AS sku FROM generate_series(1, 39) g;
CREATE TABLE copack.snapshot_meta (id serial PRIMARY KEY, sku_count int); INSERT INTO copack.snapshot_meta (sku_count) VALUES (50);
CREATE TABLE public.netsuite_items AS SELECT g::text AS sku FROM generate_series(1, 5) g;
CREATE TABLE public.wms_dimensions AS SELECT g::text AS sku FROM generate_series(1, 5) g;
CREATE TABLE public.gdsn_published AS SELECT g::text AS sku FROM generate_series(1, 5) g;
CREATE TABLE public.shopify_products AS SELECT g::text AS sku FROM generate_series(1, 5) g;
CREATE VIEW public_staging.stg_netsuite_items AS SELECT * FROM public.netsuite_items;
CREATE VIEW public_staging.stg_wms_dimensions AS SELECT * FROM public.wms_dimensions;
CREATE VIEW public_staging.stg_gdsn_published AS SELECT * FROM public.gdsn_published;
CREATE VIEW public_staging.stg_shopify_products AS SELECT * FROM public.shopify_products;
CREATE VIEW public_intermediate.int_measurement_of_record AS SELECT * FROM public_staging.stg_wms_dimensions;
CREATE VIEW public_intermediate.int_dim_and_billable AS SELECT * FROM public_intermediate.int_measurement_of_record;
CREATE VIEW public_intermediate.int_freight_class_by_system AS SELECT * FROM public_staging.stg_gdsn_published;
CREATE VIEW public_intermediate.int_system_attribute_divergence AS SELECT * FROM public_staging.stg_netsuite_items;
CREATE TABLE public_marts.fct_attribute_divergence AS SELECT g FROM generate_series(1, 7) g;
CREATE TABLE public_marts.fct_dimension_cost AS SELECT g FROM generate_series(1, 3) g;
CREATE TABLE public_marts.fct_freight_class_by_system AS SELECT g FROM generate_series(1, 3) g;
CREATE TABLE public_marts.fct_governed_product_master AS SELECT g FROM generate_series(1, 5) g;
CREATE TABLE public_public_marts.fct_attribute_divergence AS SELECT g FROM generate_series(1, 7) g;
CREATE TABLE public_public_marts.fct_dimension_cost AS SELECT g FROM generate_series(1, 3) g;
CREATE TABLE public_public_marts.fct_freight_class_by_system AS SELECT g FROM generate_series(1, 3) g;
CREATE TABLE public_public_marts.fct_governed_product_master AS SELECT g FROM generate_series(1, 5) g;
CREATE TABLE public_marts.stg_category_benchmarks AS SELECT g FROM generate_series(1, 28) g;
CREATE TABLE public_marts.q12_summary AS SELECT 1 AS mape_pct;
CREATE TABLE public_marts.q12_by_sku AS SELECT g FROM generate_series(1, 10) g;
CREATE TABLE public_marts.fct_scan_data (sku text);
"""
MOVED = {"production_demand_forecast": 4, "dimension_weight_integrity": 16, "retail_velocity_decision_tool": 1,
         "the_question_engine": 2}


@pytest.fixture
def world(tmp_path):
    vals = harness.harness_values()
    admin = psycopg2.connect(harness.dsn(vals), connect_timeout=5)
    admin.autocommit = True
    created = []
    with admin.cursor() as c:
        c.execute(f"DROP DATABASE IF EXISTS {PROBE_DB} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {PROBE_DB}")
        for role in LOGINS:  # production's two writer logins; NOLOGIN here, and dropped only if made here
            c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if not c.fetchone():
                c.execute(f"CREATE ROLE {role} NOLOGIN")
                created.append(role)
    probe = dict(vals, HARNESS_PG_DB=PROBE_DB)
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute(WORLD)
        c.execute("ALTER TABLE copack.forecast_snapshot OWNER TO cinderhaven_demand_forecast")
    conn.close()
    (tmp_path / ".env").write_text(f"POSTGRES_USER={vals['HARNESS_PG_USER']}\n"
                                   f"POSTGRES_PASSWORD={vals['HARNESS_PG_PASSWORD']}\nPOSTGRES_DB={PROBE_DB}\n")
    (tmp_path / "fake_gh.py").write_text(FAKE_GH)
    (tmp_path / "fake_docker.py").write_text(FAKE_DOCKER)
    (tmp_path / "deployed_db.py").write_text(NEW_DBPY)
    yield probe, tmp_path
    with admin.cursor() as c:
        c.execute(f"DROP DATABASE IF EXISTS {PROBE_DB} WITH (FORCE)")
        for role in created:
            c.execute(f"DROP ROLE IF EXISTS {role}")
    admin.close()


def _run(probe, tmp, stdin):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "move_writer_tables.py"), "--port", probe["HARNESS_PG_PORT"],
         "--env-file", str(tmp / ".env"), "--gh", f"{sys.executable}|{tmp / 'fake_gh.py'}",
         "--docker", f"{sys.executable}|{tmp / 'fake_docker.py'}", "--backup-dir", str(tmp)],
        input=stdin, capture_output=True, text=True, cwd=ROOT, env=harness.child_env(probe))


def _where(probe) -> dict[str, list[str]]:
    """schema -> sorted relation names, for every schema the move touches."""
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute("SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                  "WHERE c.relkind IN ('r','v') AND n.nspname NOT IN ('pg_catalog','information_schema') "
                  "ORDER BY 1, 2")
        out: dict[str, list[str]] = {}
        for s, r in c.fetchall():
            out.setdefault(s, []).append(r)
    conn.close()
    return out


def test_plan_names_every_relation_and_owner_and_a_wrong_word_changes_nothing(world):
    probe, tmp = world
    before = _where(probe)
    r = _run(probe, tmp, "move\n")
    assert r.returncode == 1 and "Not confirmed: nothing changed." in r.stdout
    assert _where(probe) == before
    assert list(tmp.glob("backup-prod-*.dump")), "the backup runs before the plan is shown"
    for line in ("move table copack.forecast_snapshot  (owner cinderhaven_demand_forecast, 50 rows)  ->  "
                 "production_demand_forecast.forecast_snapshot",
                 "move view  public_staging.stg_wms_dimensions",
                 "move table public_marts.stg_category_benchmarks  (owner",
                 "move table public_marts.q12_by_sku",
                 "DROP  table public_public_marts.fct_dimension_cost",
                 "grants: cinderhaven_demand_forecast owns production_demand_forecast (USAGE, CREATE)",
                 "grants: retail_velocity_decision_tool owns retail_velocity_decision_tool (USAGE, CREATE)",
                 "contract-to-cash\n    nothing to move"):
        assert line in r.stdout, line
    assert sum(r.stdout.count(f"->  {s}.") for s in MOVED) == sum(MOVED.values())
    assert "password" not in r.stdout.lower()


def test_unmet_deploy_order_stops_before_the_backup(world):
    probe, tmp = world
    (tmp / "deployed_db.py").write_text(OLD_DBPY)
    before = _where(probe)
    r = _run(probe, tmp, "MOVE\n")
    assert r.returncode == 1 and "STOP: the deploy order is not met. Nothing changed." in r.stdout
    assert "production-demand-forecast: the deployed commit abc1234" in r.stdout
    assert not list(tmp.glob("backup-prod-*.dump")) and _where(probe) == before
    (tmp / "deployed_db.py").unlink()
    r = _run(probe, tmp, "MOVE\n")
    assert r.returncode == 1 and "no successful fly-deploy.yml run on main found" in r.stdout


def test_a_failed_backup_stops_with_nothing_changed(world):
    probe, tmp = world
    (tmp / "docker_fails").write_text("")
    before = _where(probe)
    r = _run(probe, tmp, "MOVE\n")
    assert r.returncode == 1 and "STOP: backup failed" in r.stdout and "This run will" not in r.stdout
    assert _where(probe) == before


def test_move_commits_passes_per_repo_and_a_rerun_finds_it_done(world):
    probe, tmp = world
    r = _run(probe, tmp, "MOVE\n")
    assert r.returncode == 0, r.stdout + r.stderr
    for repo in ("production-demand-forecast", "dimension-weight-integrity", "retail-velocity-decision-tool",
                 "the-question-engine", "contract-to-cash"):
        assert f"  PASS  {repo}:" in r.stdout, repo
    after = _where(probe)
    for schema, n in MOVED.items():
        assert len(after[schema]) == n, schema
    assert "public_public_marts" not in after and "public" not in after
    assert "public_staging" not in after and "public_intermediate" not in after
    assert after["public_marts"] == ["fct_scan_data"] and after["copack"] == ["co_packers"]
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute("SELECT count(*) FROM dimension_weight_integrity.int_dim_and_billable")  # the view chain holds
        assert c.fetchone()[0] == 5
        c.execute("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = "
                  "'production_demand_forecast.forecast_week_snapshot'::regclass")
        assert c.fetchone()[0] == "cinderhaven_demand_forecast"
        c.execute("SELECT nextval('production_demand_forecast.snapshot_meta_id_seq')")  # the serial moved with it
        assert c.fetchone()[0] == 2
    conn.close()
    again = _run(probe, tmp, "MOVE\n")
    assert again.returncode == 0 and again.stdout.count("already moved:") == sum(MOVED.values())


def test_a_failure_inside_the_transaction_rolls_all_of_it_back(world):
    probe, tmp = world
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute("""CREATE FUNCTION fail_on_q12() RETURNS event_trigger LANGUAGE plpgsql AS $$
            DECLARE o record; BEGIN FOR o IN SELECT * FROM pg_event_trigger_ddl_commands() LOOP
              IF o.object_identity LIKE '%q12_by_sku' THEN RAISE EXCEPTION 'injected'; END IF; END LOOP; END $$;
            CREATE EVENT TRIGGER fail_on_q12 ON ddl_command_end WHEN TAG IN ('ALTER TABLE')
            EXECUTE FUNCTION fail_on_q12()""")
    conn.close()
    before = _where(probe)
    try:
        r = _run(probe, tmp, "MOVE\n")
    finally:
        with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
            c.execute("DROP EVENT TRIGGER fail_on_q12; DROP FUNCTION fail_on_q12()")
        conn.close()
    assert r.returncode == 1 and "FAILED, rolled back, nothing changed: injected" in r.stdout
    assert _where(probe) == before
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute("SELECT count(*) FROM pg_namespace WHERE nspname = ANY(%s)", (list(MOVED),))
        assert c.fetchone()[0] == 0
    conn.close()


def test_a_connection_dropped_during_the_backup_does_not_stop_the_move(world):
    """Production, 2026-11-17: the Fly proxy dropped the survey's connection while the dump and the prompt ran."""
    probe, tmp = world
    (tmp / "dsn").write_text(harness.dsn(probe))
    (tmp / "during_dump.sql").write_text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                                         "WHERE datname = current_database() AND pid <> pg_backend_pid()")
    r = _run(probe, tmp, "MOVE\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("  PASS  ") == 5


def test_production_changed_after_the_plan_stops_with_nothing_changed(world):
    probe, tmp = world
    (tmp / "dsn").write_text(harness.dsn(probe))
    (tmp / "during_dump.sql").write_text("INSERT INTO copack.snapshot_meta (sku_count) VALUES (51)")
    before = _where(probe)
    r = _run(probe, tmp, "MOVE\n")
    assert r.returncode == 1 and "STOP: production changed between the plan above and the confirmation" in r.stdout
    assert _where(probe) == before


def test_a_table_in_both_schemas_or_an_unnamed_stale_relation_stops(world):
    probe, tmp = world
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute("CREATE SCHEMA the_question_engine; CREATE TABLE the_question_engine.q12_summary (x int);"
                  "CREATE TABLE public_public_marts.someone_elses (x int)")
    conn.close()
    before = _where(probe)
    r = _run(probe, tmp, "MOVE\n")
    assert r.returncode == 1 and "STOP: production is not in a state this plan carries. Nothing changed." in r.stdout
    assert "q12_summary is in both public_marts and the_question_engine" in r.stdout
    assert "public_public_marts holds relations the plan does not name: someone_elses" in r.stdout
    assert not list(tmp.glob("backup-prod-*.dump")) and _where(probe) == before
