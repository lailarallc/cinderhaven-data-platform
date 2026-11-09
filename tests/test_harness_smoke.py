"""Fast tier: the harness itself, with no database connection."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import external_ref
import harness
import seed_runs
from seed_runs import Gate, Outcome

ROOT = Path(__file__).resolve().parent.parent


# ── pytest exit status ──────────────────────────────────────────────

def _pytest_on(tmp_path: Path, body: str) -> int:
    (tmp_path / "test_probe.py").write_text(body)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-c", str(ROOT / "pytest.ini"),
                           "--rootdir", str(ROOT), str(tmp_path)], capture_output=True).returncode


def test_a_failing_assertion_exits_non_zero(tmp_path):
    assert _pytest_on(tmp_path, "def test_x():\n    assert 1 == 2\n") != 0


def test_a_skip_fails_the_run(tmp_path):
    assert _pytest_on(tmp_path, "import pytest\ndef test_x():\n    pytest.skip('absent')\n") != 0


def test_a_passing_probe_exits_zero(tmp_path):
    # Control for the two above: the probe mechanism itself passes a clean test.
    assert _pytest_on(tmp_path, "def test_x():\n    assert True\n") == 0


# ── credentials and the guard ───────────────────────────────────────

def test_missing_credentials_fail_with_the_generation_command(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "HARNESS_ENV", tmp_path / "absent.env")
    for k in harness.KEYS:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(harness.HarnessError, match="make_harness_env.py"):
        harness.harness_values()


def test_child_env_drops_production_password_variables(monkeypatch):
    monkeypatch.setenv("POSTGRES_PASSWORD", "x")
    monkeypatch.setenv("ALLOW_PROD_DB", "1")
    vals = {k: "v" for k in harness.KEYS}
    env = harness.child_env(vals)
    assert "POSTGRES_PASSWORD" not in env and "ALLOW_PROD_DB" not in env
    assert env["DATABASE_URL"].startswith("host=v port=v dbname=v")


@pytest.mark.parametrize("step", ["run_seed", "run_build"])
def test_every_connecting_step_stops_at_the_guard_before_running_anything(step, monkeypatch):
    # The guard's real CLI shells out to netstat; fake its verdict at the
    # subprocess boundary as a fly tunnel on the target port.
    monkeypatch.setattr(harness, "harness_values", lambda: {k: "1" for k in harness.KEYS})
    monkeypatch.setattr(harness.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1))
    ran = []
    monkeypatch.setattr(harness, "_run", lambda *a, **kw: ran.append(a))
    with pytest.raises(harness.HarnessError, match="prod_guard refused"):
        getattr(harness, step)()
    assert ran == []


def test_the_guard_is_handed_the_harness_host_and_port(monkeypatch):
    seen = []
    monkeypatch.setattr(harness.subprocess, "run",
                        lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0))
    harness.guard({"HARNESS_PG_HOST": "127.0.0.1", "HARNESS_PG_PORT": "55432",
                   "HARNESS_PG_DB": "d", "HARNESS_PG_USER": "u", "HARNESS_PG_PASSWORD": "p"})
    assert seen[0][-1] == "127.0.0.1:55432" and seen[0][-2].endswith("prod_guard.py")


def test_a_run_seed_other_than_zero_is_refused_until_u2():
    with pytest.raises(harness.HarnessError, match="U2"):
        harness.run_seed(1)


# ── the multi-seed runner ───────────────────────────────────────────

def _stub_gates(hard_miss_seed=None, draw_miss_seed=None, mean_stat=None, band=(0.0, 1.0)):
    return [
        Gate("hard", "hard", lambda s: Outcome(s != hard_miss_seed)),
        Gate("draw", "draw", lambda s: Outcome(s != draw_miss_seed), min_pass_rate=0.6),
        Gate("mean", "mean", lambda s: Outcome(True, mean_stat(s) if mean_stat else 0.5),
             band=lambda n: band),
    ]


def test_the_runner_records_one_outcome_per_gate_per_seed():
    built = []
    rec = seed_runs.run([0, 1, 2], built.append, _stub_gates())
    assert built == [0, 1, 2]
    assert {g: [o["seed"] for o in v] for g, v in rec.outcomes.items()} == \
        {"hard": [0, 1, 2], "draw": [0, 1, 2], "mean": [0, 1, 2]}
    assert rec.passed


def test_a_hard_gate_fails_the_run_on_one_seed():
    rec = seed_runs.run([0, 1, 2], lambda s: None, _stub_gates(hard_miss_seed=1))
    assert rec.verdicts["hard"] == {"kind": "hard", "passed": False, "failed_seeds": [1]}
    assert not rec.passed


def test_a_draw_gate_records_a_single_miss_without_failing():
    rec = seed_runs.run([0, 1, 2], lambda s: None, _stub_gates(draw_miss_seed=1))
    assert rec.outcomes["draw"][1]["passed"] is False
    assert rec.verdicts["draw"]["passed"] and rec.passed


def test_a_mean_gate_fails_outside_its_band_and_passes_inside():
    inside = seed_runs.run([0, 1, 2], lambda s: None, _stub_gates(mean_stat=lambda s: 0.4 + 0.1 * s))
    outside = seed_runs.run([0, 1, 2], lambda s: None, _stub_gates(mean_stat=lambda s: 1.0 + s))
    assert inside.verdicts["mean"]["passed"]
    assert not outside.verdicts["mean"]["passed"]


def test_a_truth_reading_gate_cannot_record_a_statistic():
    g = Gate("ledger", "hard", lambda s: Outcome(True, 3.0), reads_truth=True)
    with pytest.raises(ValueError, match="reads truth"):
        seed_runs.run([0], lambda s: None, [g])


def test_a_mean_gate_may_not_read_truth():
    with pytest.raises(ValueError, match="truth"):
        Gate("m", "mean", lambda s: Outcome(True, 1.0), reads_truth=True, band=lambda n: (0, 1))


def test_a_run_with_no_gates_is_refused():
    with pytest.raises(ValueError, match="vacuously"):
        seed_runs.run([0], lambda s: None, [])


def test_a_seed_that_cannot_be_built_fails_the_run_loudly():
    def rebuild(s):
        if s == 1:
            raise harness.HarnessError("boom")
    with pytest.raises(harness.HarnessError):
        seed_runs.run([0, 1], rebuild, _stub_gates())


def test_the_record_is_written_with_commit_seeds_and_verdicts(tmp_path):
    rec = seed_runs.run([0, 1, 2], lambda s: None, _stub_gates())
    data = json.loads(seed_runs.write_record(rec, tmp_path).read_text())
    assert set(data) == {"commit", "mode", "seeds", "passed", "outcomes", "verdicts"}
    assert data["seeds"] == [0, 1, 2]


def test_poisson_band_is_the_ruled_rule():
    # U18 (2026-10-20): at 30 seeds a window mean of 7.84 holds within +/- 1.00.
    lo, hi = seed_runs.poisson_band(7.84, 30)
    assert round(hi - 7.84, 2) == 1.00 and round(7.84 - lo, 2) == 1.00
    # It moves with the count: four times the seeds halves the band.
    lo4, hi4 = seed_runs.poisson_band(7.84, 120)
    assert abs((hi4 - lo4) * 2 - (hi - lo)) < 1e-9


# ── cross-repo references ───────────────────────────────────────────

def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def pinned_repo(tmp_path):
    repo = tmp_path / "ext"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "gate.py").write_text("print('ok')\n")
    _git(repo, "add", "gate.py")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "pin")
    import hashlib
    sha = hashlib.sha256((repo / "gate.py").read_bytes()).hexdigest()
    return external_ref.ExternalRef(repo, _git(repo, "rev-parse", "HEAD"), "gate.py", sha)


def test_an_external_file_at_its_pin_resolves(pinned_repo):
    assert external_ref.resolve(pinned_repo).name == "gate.py"


def test_an_external_reference_with_no_checkout_fails_loudly(pinned_repo, tmp_path):
    ref = external_ref.ExternalRef(tmp_path / "nowhere", pinned_repo.commit, "gate.py", pinned_repo.sha256)
    with pytest.raises(external_ref.ExternalRefError, match="no checkout"):
        external_ref.resolve(ref)


def test_an_external_reference_at_another_commit_fails_loudly(pinned_repo):
    (pinned_repo.repo / "other.txt").write_text("x")
    _git(pinned_repo.repo, "add", "other.txt")
    _git(pinned_repo.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "move")
    with pytest.raises(external_ref.ExternalRefError, match="pinned"):
        external_ref.resolve(pinned_repo)


def test_an_external_file_edited_in_place_fails_loudly(pinned_repo):
    (pinned_repo.repo / "gate.py").write_text("print('changed')\n")
    with pytest.raises(external_ref.ExternalRefError, match="local changes"):
        external_ref.resolve(pinned_repo)
