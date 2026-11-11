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


def _orchestrate(probe, tmp, stdin):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "rotate_and_place.py"), "--port", probe["HARNESS_PG_PORT"],
         "--env-file", str(tmp / ".env"), "--profiles", str(tmp / "profiles.yml"),
         "--gh", f"{sys.executable}|{tmp / 'fake_gh.py'}", "--no-dispatch"],
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


def test_it_stops_before_changing_anything_when_the_apply_never_ran(world):
    probe, tmp = world
    r = _orchestrate(probe, tmp, "APPLY\n")
    assert r.returncode == 1 and "STOP" in r.stdout and "has not run here" in r.stdout
    assert "logins present:      none" in r.stdout
    assert (tmp / "profiles.yml").read_text() == PROFILE and not (tmp / "secret.txt").exists()


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
