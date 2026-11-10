"""The gate reaches a consumer through the platform's refresh (plan U4).

A copy of tests/fixtures/consumer_repo gets the platform's refresh_canonical.py
(as U19 hand-vendors it once), runs it, and must then hold the gate in its own
quarantine/. The consumer's own gate run passes on its clean code and fails on
a planted violation, using only the vendored files.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "consumer_repo"
GATE_RUN = ("import sys; sys.path.insert(0, 'quarantine'); "
            "from truth_gate import assert_no_truth_access; from text_scan import assert_no_truth_text; "
            "assert_no_truth_access('src'); assert_no_truth_text('src')")


@pytest.fixture
def consumer(tmp_path):
    repo = tmp_path / "consumer"
    shutil.copytree(FIXTURE, repo)
    (repo / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "refresh_canonical.py", repo / "scripts" / "refresh_canonical.py")
    env = dict(os.environ, CINDERHAVEN_PLATFORM=str(ROOT))
    r = subprocess.run([sys.executable, "scripts/refresh_canonical.py"], cwd=repo, env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return repo


def _gate(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", "-c", GATE_RUN], cwd=repo, capture_output=True, text=True)


def test_the_refresh_vendors_the_gate_into_the_consumers_quarantine(consumer):
    for name in ("truth_gate.py", "text_scan.py"):
        assert (consumer / "quarantine" / name).read_bytes() == (ROOT / "quarantine" / name).read_bytes()


def test_the_vendored_gate_passes_the_consumers_clean_code(consumer):
    r = _gate(consumer)
    assert r.returncode == 0, r.stderr


def test_the_vendored_gate_fails_on_a_planted_violation(consumer):
    (consumer / "src" / "estimators" / "peek.py").write_text(
        'Q = "SELECT * FROM truth.promo_events"\n')
    r = _gate(consumer)
    assert r.returncode != 0 and "TruthAccessViolation" in r.stderr
