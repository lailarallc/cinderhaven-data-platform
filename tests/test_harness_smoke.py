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


def test_the_run_seed_reaches_seed_all_and_defaults_to_zero(monkeypatch):
    monkeypatch.setenv("CINDERHAVEN_RUN_SEED", "7")  # a stray value in the shell
    vals = {k: "v" for k in harness.KEYS}
    assert harness.child_env(vals)["CINDERHAVEN_RUN_SEED"] == "0"
    assert harness.child_env(vals, 3)["CINDERHAVEN_RUN_SEED"] == "3"


def test_a_negative_run_seed_is_refused():
    with pytest.raises(harness.HarnessError, match=">= 0"):
        harness.run_seed(-1)


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
    assert set(data) == {"commit", "mode", "seeds", "passed", "outcomes", "verdicts", "not_built"}
    assert data["seeds"] == [0, 1, 2]


# ── resuming the multi-seed run (a shutdown mid-run) ────────────────

def _interrupted(progress, seeds, stop_at):
    """A run cut off while rebuilding `stop_at`, as a shutdown would."""
    def rebuild(s):
        if s == stop_at:
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        seed_runs.run(seeds, rebuild, _stub_gates(hard_miss_seed=1), progress)


def test_each_finished_seed_is_saved_and_a_restart_skips_it(tmp_path):
    progress = tmp_path / "progress.jsonl"
    _interrupted(progress, [0, 1, 2, 3], stop_at=2)
    assert [json.loads(line)["seed"] for line in progress.read_text().splitlines()[1:]] == [0, 1]
    built = []
    rec = seed_runs.run([0, 1, 2, 3], built.append, _stub_gates(hard_miss_seed=1), progress)
    assert built == [2, 3], "a restart rebuilt a seed that had already finished"
    whole = seed_runs.run([0, 1, 2, 3], lambda s: None, _stub_gates(hard_miss_seed=1))
    assert rec.outcomes == whole.outcomes and rec.verdicts == whole.verdicts  # judged from saved results
    assert rec.verdicts["hard"]["failed_seeds"] == [1], "seed 1's saved failure was lost on resume"


def test_a_torn_last_line_is_dropped_and_that_seed_reruns(tmp_path):
    progress = tmp_path / "progress.jsonl"
    _interrupted(progress, [0, 1, 2], stop_at=2)
    text = progress.read_text()
    progress.write_text(text[: len(text) - 10])  # power cut mid-write of seed 1's line
    built = []
    seed_runs.run([0, 1, 2], built.append, _stub_gates(), progress)
    assert built == [1, 2]


def test_a_progress_file_from_another_commit_refuses(tmp_path, monkeypatch):
    progress = tmp_path / "progress.jsonl"
    _interrupted(progress, [0, 1], stop_at=1)
    monkeypatch.setattr(seed_runs, "_commit", lambda: "f" * 40)
    with pytest.raises(ValueError, match="not mixed"):
        seed_runs.run([0, 1], lambda s: None, _stub_gates(), progress)


def test_the_multi_seed_run_refuses_uncommitted_run_inputs(monkeypatch):
    monkeypatch.setattr(seed_runs, "_dirty_inputs", lambda: ["generation/seed_config.py"])
    monkeypatch.setattr(seed_runs, "run", lambda *a, **k: pytest.fail("the run started"))
    assert seed_runs.main(["--seeds", "2"]) == 2


# ── guard trips and the U2 run-seed verdict (owner, 2026-11-14) ─────

TRIP = {"guard": "void_deletion", "retailer": "RET-REGIONAL", "loss": 0.0163, "limit": 0.015}


def _tripping(trip_seed):
    def rebuild(s):
        if s == trip_seed:
            raise seed_runs.SeedNotBuilt(TRIP)
    return rebuild


def _world(s):  # a distinct, repeatable world per seed
    return {"raw.t": {"rows": 1, "hash": f"h{s}"}}


def test_a_guard_trip_is_that_seeds_result_and_the_run_goes_on(tmp_path):
    progress = tmp_path / "p.jsonl"
    rec = seed_runs.run([0, 1, 2], _tripping(1), _stub_gates(), progress, _world)
    assert rec.not_built == {1: TRIP}
    assert [o["seed"] for o in rec.outcomes["hard"]] == [0, 2], "gates judge the built seeds"
    assert sorted(rec.worlds) == [0, 2] and rec.repeat == {"repeat_of": 0, "world": _world(0)}
    built = []
    again = seed_runs.run([0, 1, 2], built.append, _stub_gates(), progress, _world)
    assert built == [] and again.not_built == {1: TRIP}, "a resume reran a saved seed, trip or repeat"


def test_repeat_mode_rebuilds_seed_zero_every_time():
    built = []
    rec = seed_runs.run([0, 0, 0], built.append, _stub_gates())
    assert built == [0, 0, 0] and len(rec.outcomes["hard"]) == 3


def test_the_u2_verdict_passes_deterministic_distinct_worlds_and_reports_trips_beside_it(tmp_path):
    rec = seed_runs.run([0, 1, 2], _tripping(1), _stub_gates(), None, _world)
    v = seed_runs.run_seed_machinery(rec, baseline=_world(0))
    assert v["passed"] and v["built"] == [0, 2] and v["guard_trips"] == {"1": TRIP}


def test_the_u2_verdict_fails_on_a_repeat_that_differs_twin_worlds_or_a_moved_seed_zero():
    worlds = iter([_world(0), _world(1), _world(9)])  # the repeat of seed 0 comes back different
    rec = seed_runs.run([0, 1], lambda s: None, _stub_gates(), None, lambda s: next(worlds))
    assert not seed_runs.run_seed_machinery(rec, _world(0))["deterministic"]
    rec = seed_runs.run([0, 1], lambda s: None, _stub_gates(), None, lambda s: _world(0))
    assert not seed_runs.run_seed_machinery(rec, _world(0))["distinct"]
    rec = seed_runs.run([0, 1], lambda s: None, _stub_gates(), None, _world)
    assert not seed_runs.run_seed_machinery(rec, _world(5))["seed0_is_baseline"]


def test_seed_all_exit_3_with_a_report_becomes_guard_tripped(monkeypatch):
    def fake_run(cmd, cwd=None, env=None):
        Path(env["CINDERHAVEN_GUARD_REPORT"]).write_text(json.dumps(TRIP))
        return subprocess.CompletedProcess(cmd, harness.GUARD_TRIP_EXIT)
    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    with pytest.raises(harness.GuardTripped) as e:
        harness._run("seed_all.py", ["x"], {k: "v" for k in harness.KEYS}, ROOT, [], 9)
    assert e.value.detail == TRIP


def test_the_void_guard_message_prints_the_limit_it_enforces():
    sys.path.insert(0, str(ROOT / "generation"))
    src = (ROOT / "generation" / "seed_void_patterns.py").read_text(encoding="utf-8")
    assert "MAX_RETAILER_REVENUE_DELETION = 0.015" in src
    ns: dict = {}
    cls_src = src[src.index("class DeletionGuardTripped"):src.index("def check_deletion_guard")]
    exec(cls_src, ns)
    msg = str(ns["DeletionGuardTripped"]("RET-REGIONAL", 0.0163, 0.015))
    assert "(limit 1.5%)" in msg and "1.63%" in msg, msg


def _seed_all_with_build_results(monkeypatch, tmp_path, statuses):
    import importlib
    monkeypatch.setenv("DATABASE_URL", "host=localhost port=5999 dbname=w user=g password=x")
    sys.path.insert(0, str(ROOT / "generation"))
    for m in ("seed_config", "seed_all"):
        sys.modules.pop(m, None)
    seed_all = importlib.import_module("seed_all")
    monkeypatch.setattr(seed_all, "DBT_PROJECT", tmp_path)
    (tmp_path / "target").mkdir()

    def failing_build(*args):
        rows = [{"unique_id": f"node.{i}", "status": s} for i, s in enumerate(statuses)]
        (tmp_path / "target" / "run_results.json").write_text(json.dumps({"results": rows}))
        raise seed_all.SeedError("dbt build failed (exit 1)")
    monkeypatch.setattr(seed_all, "run_dbt", failing_build)
    return seed_all


def test_a_dbt_build_whose_tests_fail_is_a_recorded_refusal(monkeypatch, tmp_path):
    seed_all = _seed_all_with_build_results(monkeypatch, tmp_path, ["pass", "fail", "skipped"])
    with pytest.raises(seed_all.DbtTestsFailed) as e:
        seed_all.full_build()
    assert e.value.tests == ["node.1"]


def test_a_dbt_build_with_an_error_fails_loudly(monkeypatch, tmp_path):
    seed_all = _seed_all_with_build_results(monkeypatch, tmp_path, ["fail", "error"])
    with pytest.raises(seed_all.SeedError) as e:
        seed_all.full_build()
    assert not isinstance(e.value, seed_all.DbtTestsFailed)


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
