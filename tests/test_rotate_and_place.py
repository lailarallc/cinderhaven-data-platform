"""scripts/rotate_and_place.py on the harness: rotate, place, test, with no password printed.

Stands in for production: a scratch database on the harness instance, a temp
.env holding the harness's test credentials, a temp profiles.yml, and a fake gh
that records the secret it is sent. No real credential is involved.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest
import yaml

import harness
from test_apply_truth_roles import PROBE_DB, _passwords, _run, probe  # noqa: F401  (fixture)

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parent.parent
PROFILE = """cinderhaven:
  target: dev
  outputs:
    dev:
      type: postgres
      host: localhost
      port: 5432
      user: postgres
      password: "{{ env_var('POSTGRES_PASSWORD') }}"
      dbname: cinderhaven
      schema: public
      threads: 4

edi_reconciliation:
  target: dev
  outputs:
    dev:
      type: postgres
      user: "{{ env_var('POSTGRES_USER', 'postgres') }}"
      password: "{{ env_var('POSTGRES_PASSWORD') }}"
"""
FAKE_GH = """import sys
from pathlib import Path
args = sys.argv[1:]
if args[:2] == ["secret", "set"]:
    Path(sys.argv[0]).with_name("secret.txt").write_text(sys.stdin.read(), newline="")
sys.exit(0)
"""


@pytest.fixture
def world(probe, tmp_path):  # noqa: F811
    vals = harness.harness_values()
    (tmp_path / ".env").write_text(f"POSTGRES_USER={vals['HARNESS_PG_USER']}\n"
                                   f"POSTGRES_PASSWORD={vals['HARNESS_PG_PASSWORD']}\nPOSTGRES_DB={PROBE_DB}\n")
    (tmp_path / "profiles.yml").write_text(PROFILE)
    (tmp_path / "fake_gh.py").write_text(FAKE_GH)
    yield probe, tmp_path
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute("DROP ROLE IF EXISTS cinderhaven_dagster; DROP ROLE IF EXISTS cinderhaven_ci_reader")
    conn.close()


def _orchestrate(probe, tmp, stdin, docker="docker"):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "rotate_and_place.py"), "--port", probe["HARNESS_PG_PORT"],
         "--env-file", str(tmp / ".env"), "--profiles", str(tmp / "profiles.yml"),
         "--gh", f"{sys.executable}|{tmp / 'fake_gh.py'}", "--no-dispatch", "--docker", docker,
         "--backup-dir", str(tmp)],
        input=stdin, capture_output=True, text=True, cwd=ROOT, env=harness.child_env(probe))


def _create_logins(probe):
    r = _run(probe, "--apply", "--dagster-login", "cinderhaven_dagster", "--reader-login", "cinderhaven_ci_reader",
             stdin="APPLY\n")
    assert r.returncode == 0, r.stderr
    return _passwords(r.stdout)


def _logs_in(probe, user, password):
    try:
        psycopg2.connect(harness.dsn(dict(probe, HARNESS_PG_USER=user, HARNESS_PG_PASSWORD=password))).close()
        return True
    except psycopg2.OperationalError:
        return False


def test_without_apply_typed_nothing_changes(world):
    probe, tmp = world
    old = _create_logins(probe)
    r = _orchestrate(probe, tmp, "yes\n")
    assert r.returncode == 1 and "nothing changed" in r.stdout
    assert all(_logs_in(probe, u, p) for u, p in old.items())
    assert (tmp / "profiles.yml").read_text() == PROFILE and not (tmp / "secret.txt").exists()


def test_it_rotates_places_and_tests_without_printing_a_password(world):
    probe, tmp = world
    old = _create_logins(probe)
    r = _orchestrate(probe, tmp, "APPLY\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "group roles present: cinderhaven_generator" in r.stdout          # the state report
    # Dagster: the profile now names its login, and the password read back from it works.
    prof = yaml.safe_load((tmp / "profiles.yml").read_text())
    dev = prof["cinderhaven"]["outputs"]["dev"]
    assert dev["user"] == "cinderhaven_dagster" and _logs_in(probe, dev["user"], dev["password"])
    assert prof["edi_reconciliation"] == yaml.safe_load(PROFILE)["edi_reconciliation"]   # untouched
    assert len(list(tmp.glob("profiles.yml.bak-*"))) == 1
    # Reader: the secret gh was sent works, exactly, with no trailing newline.
    secret = (tmp / "secret.txt").read_text()
    assert secret == secret.strip() and _logs_in(probe, "cinderhaven_ci_reader", secret)
    # The old passwords are dead.
    assert not any(_logs_in(probe, u, p) for u, p in old.items())
    assert "PASS  Dagster login" in r.stdout and "PASS  Reader login" in r.stdout
    # Nothing secret on screen.
    shown = r.stdout + r.stderr
    for value in (dev["password"], secret, probe["HARNESS_PG_PASSWORD"]):
        assert value not in shown


# ── the first apply (owner, 2026-11-11: production's apply never ran) ──

WRITER = "copack_writer_probe"


@pytest.fixture
def prod_like(world):
    """The scratch database shaped like production on 2026-11-11: no logins, raw and costing
    owned by the admin, copack owned by another repo's login."""
    probe, tmp = world
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute(f"DROP ROLE IF EXISTS {WRITER}; CREATE ROLE {WRITER}")
        c.execute(f"CREATE SCHEMA copack AUTHORIZATION {WRITER}; CREATE TABLE copack.forecast_snapshot (x int);"
                  f"ALTER TABLE copack.forecast_snapshot OWNER TO {WRITER}; INSERT INTO raw.stores VALUES ('S1')")
    conn.close()
    yield probe, tmp
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute(f"DROP SCHEMA IF EXISTS copack CASCADE")
    conn.close()
    with psycopg2.connect(harness.dsn(dict(probe, HARNESS_PG_DB="postgres"))) as conn:
        pass
    conn.close()


def _drop_writer(probe):
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute(f"DROP SCHEMA IF EXISTS copack CASCADE; DROP ROLE IF EXISTS {WRITER}")
    conn.close()


def _owner_of(probe, schema):
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s", (schema,))
        owner = c.fetchone()[0]
    conn.close()
    return owner


def _logins_exist(probe):
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute("SELECT count(*) FROM pg_roles WHERE rolname IN ('cinderhaven_dagster', 'cinderhaven_ci_reader')")
        n = c.fetchone()[0]
    conn.close()
    return n


def test_first_apply_backs_up_first_prints_everything_then_applies_and_places(prod_like):
    probe, tmp = prod_like
    admin = probe["HARNESS_PG_USER"]
    try:
        r = _orchestrate(probe, tmp, "APPLY\n")
        out = r.stdout
        assert r.returncode == 0, out + r.stderr
        # The backup came first and reads back.
        assert out.index("Backup: backup-prod-") < out.index("This run will:") < out.index("Type APPLY")
        dumps = list(tmp.glob("backup-prod-*.dump"))
        assert len(dumps) == 1 and dumps[0].stat().st_size > 0 and "reads back" in out
        # The plan lists every transfer and grant, and the writer schema's owner stays.
        assert f"ALTER SCHEMA raw OWNER: {admin} -> cinderhaven_generator" in out
        assert "ALTER TABLE raw.stores OWNER" in out
        assert f"-- schema copack: owner stays {WRITER}" in out
        assert "GRANT USAGE ON SCHEMA copack" in out
        assert "CREATE ROLE cinderhaven_dagster LOGIN NOSUPERUSER" in out
        # Applied as printed.
        assert _owner_of(probe, "raw") == "cinderhaven_generator"
        assert _owner_of(probe, "copack") == WRITER
        with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
            c.execute("SELECT pg_get_userbyid(relowner), has_table_privilege('cinderhaven_reader', "
                      "'copack.forecast_snapshot', 'SELECT') FROM pg_class WHERE relname = 'forecast_snapshot'")
            assert c.fetchone() == (WRITER, True)
        conn.close()
        # Placed and tested.
        dev = yaml.safe_load((tmp / "profiles.yml").read_text())["cinderhaven"]["outputs"]["dev"]
        assert dev["user"] == "cinderhaven_dagster" and _logs_in(probe, dev["user"], dev["password"])
        assert _logs_in(probe, "cinderhaven_ci_reader", (tmp / "secret.txt").read_text())
        assert "PASS  Dagster login" in out and "PASS  Reader login" in out
        assert dev["password"] not in out + r.stderr and probe["HARNESS_PG_PASSWORD"] not in out + r.stderr
    finally:
        _drop_writer(probe)


def test_first_apply_stops_with_nothing_changed_when_the_backup_fails(prod_like):
    probe, tmp = prod_like
    (tmp / "fake_docker.py").write_text("import sys; sys.exit(1)\n")
    try:
        r = _orchestrate(probe, tmp, "APPLY\n", docker=f"{sys.executable}|{tmp / 'fake_docker.py'}")
        assert r.returncode == 1 and "STOP: backup failed" in r.stdout and "This run will:" not in r.stdout
        assert _logins_exist(probe) == 0 and _owner_of(probe, "raw") == probe["HARNESS_PG_USER"]
        assert (tmp / "profiles.yml").read_text() == PROFILE and not (tmp / "secret.txt").exists()
    finally:
        _drop_writer(probe)


def test_first_apply_without_apply_typed_changes_nothing(prod_like):
    probe, tmp = prod_like
    try:
        r = _orchestrate(probe, tmp, "no\n")
        assert r.returncode == 1 and "nothing changed" in r.stdout
        assert _logins_exist(probe) == 0 and _owner_of(probe, "raw") == probe["HARNESS_PG_USER"]
        assert (tmp / "profiles.yml").read_text() == PROFILE and not (tmp / "secret.txt").exists()
    finally:
        _drop_writer(probe)


def test_one_login_missing_stops(world):
    probe, tmp = world
    _create_logins(probe)
    with psycopg2.connect(harness.dsn(probe)) as conn, conn.cursor() as c:
        c.execute("DROP ROLE cinderhaven_ci_reader")
    conn.close()
    r = _orchestrate(probe, tmp, "APPLY\n")
    assert r.returncode == 1 and "only cinderhaven_ci_reader is missing" in r.stdout
