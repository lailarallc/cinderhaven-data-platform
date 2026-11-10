"""Egress path 4 (plan U4): the consumer-credential check, against the harness instance.

Fixture repos carry .env files whose credentials name test logins made here;
no real consumer credential is read.
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
MAP = ("### A\n\n**`live-good`** — A.\n\n**`live-super`** — A.\n\n### B\n\n**`extract-none`** — B.\n\n"
       "**`extract-missing-login`** — B.\n\n### C\n")
LOGINS = {"live_good_probe": "IN ROLE cinderhaven_reader", "live_super_probe": "SUPERUSER"}


@pytest.fixture
def fleet(tmp_path, db):
    with db.cursor() as c:
        for name, attrs in LOGINS.items():
            c.execute(f"DROP ROLE IF EXISTS {name}; CREATE ROLE {name} LOGIN {attrs}")
    db.commit()
    root = tmp_path / "fleet"
    envs = {"live-good": "DATABASE_URL=postgresql://live_good_probe@localhost:5432/cinderhaven\n",
            "live-super": "POSTGRES_USER=live_super_probe\nPOSTGRES_PASSWORD=x\n",
            "extract-missing-login": "PGUSER=no_such_login_probe\n"}
    for repo in ("live-good", "live-super", "extract-none", "extract-missing-login", "recall-blast-radius"):
        d = root / "active" / repo
        (d / ".git").mkdir(parents=True)
        if repo in envs:
            (d / ".env").write_text(envs[repo])
    m = tmp_path / "map.md"
    m.write_text(MAP, encoding="utf-8")
    yield root, m
    with db.cursor() as c:
        for name in LOGINS:
            c.execute(f"DROP ROLE IF EXISTS {name}")
    db.commit()


def test_the_check_reports_pass_and_fail_by_repo(fleet):
    root, m = fleet
    env = harness.child_env(harness.harness_values())
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_consumer_credentials.py"), "--read-map", str(m),
                        "--fleet-root", str(root), "--no-fly"], capture_output=True, text=True, env=env, cwd=ROOT)
    out = r.stdout
    assert r.returncode == 1
    assert "PASS  live-good: login 'live_good_probe': superuser=False, reader member=True" in out
    assert "FAIL  live-super: login 'live_super_probe': superuser=True" in out
    assert "FAIL  extract-none: no configured credential found" in out
    assert "FAIL  extract-missing-login: login 'no_such_login_probe' does not exist" in out
    assert "recall-blast-radius" in out  # the named extra is in the population
    assert "PASS  cinderhaven_validator: LOGIN=False, members=0" in out
    assert "localhost:5432" not in out and "PASSWORD" not in out
