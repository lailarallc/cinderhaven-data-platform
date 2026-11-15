"""The multi-seed runner (U3).

Rebuilds the off-host instance at each run seed, runs every gate's per-seed
check, records one outcome per gate per seed, then judges each gate across the
seeds by its kind:

- hard:  fails if any seed fails (zero orphans, a ledger that reconciles).
- draw:  a single seed's miss is recorded, never failed; the gate fails only if
         its pass rate falls below its registered floor.
- mean:  the mean of the per-seed statistic must sit inside the gate's band at
         the seed count in force (for late_cancel, `poisson_band` on A5.07's mean).

The seed count and tolerances are not the harness's to choose: U18 ruled 30
seeds and the Poisson rule (owner, 2026-10-20, spec:DECISIONS#u18-rulings).
Bands are computed by rule from a mean and the seed count, never typed.

A gate that reads `truth` records its boolean only: the record is egress, so a
statistic from a truth-reading gate is refused, not written.

Each run writes output/seed_runs/<utc>.json (gitignored): commit, seeds, every
outcome, every verdict. U12's relock reads it.

    python tests/seed_runs.py --seeds 30

The multi-seed run is resumable: each seed's outcomes land in
output/seed_runs/progress-<commit>-<n>seeds.jsonl as the seed finishes, and the
same command after a shutdown skips the finished seeds. It refuses a tree whose
generation inputs differ from the commit, so every saved seed is that commit's.
After a shutdown, one line starts Docker, the harness database and the run:

    powershell -ExecutionPolicy Bypass -File tests/resume_seed_run.ps1
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output" / "seed_runs"
RULED_SEED_COUNT = 30  # U18, owner, 2026-10-20


def poisson_band(mean: float, n_seeds: int) -> tuple[float, float]:
    """95% Poisson band on an across-seed mean: mean +/- 1.96 * sqrt(mean / n_seeds)."""
    if n_seeds < 1 or mean < 0:
        raise ValueError(f"poisson_band needs mean >= 0 and n_seeds >= 1, got {mean}, {n_seeds}")
    half = 1.96 * math.sqrt(mean / n_seeds)
    return mean - half, mean + half


@dataclass
class Outcome:
    passed: bool
    statistic: Optional[float] = None


@dataclass
class Gate:
    name: str
    kind: str  # "hard" | "draw" | "mean"
    check: Callable[[int], Outcome]
    reads_truth: bool = False
    min_pass_rate: Optional[float] = None  # draw gates
    band: Optional[Callable[[int], tuple[float, float]]] = None  # mean gates: seed count -> (lo, hi)

    def __post_init__(self):
        if self.kind not in ("hard", "draw", "mean"):
            raise ValueError(f"gate {self.name}: unknown kind {self.kind!r}")
        if self.kind == "draw" and self.min_pass_rate is None:
            raise ValueError(f"gate {self.name}: a draw gate needs its registered min_pass_rate")
        if self.kind == "mean" and self.band is None:
            raise ValueError(f"gate {self.name}: a mean gate needs its band rule")
        if self.kind == "mean" and self.reads_truth:
            raise ValueError(f"gate {self.name}: a mean gate records a statistic, which may not come from truth")


class SeedNotBuilt(Exception):
    """A rebuild a generator's guard refused (owner, 2026-11-14): that seed's
    recorded result, not a failure of the run. `detail` says what tripped."""

    def __init__(self, detail: dict):
        self.detail = detail
        super().__init__(str(detail))


@dataclass
class RunRecord:
    commit: str
    seeds: list[int]
    outcomes: dict[str, list[dict]] = field(default_factory=dict)
    verdicts: dict[str, dict] = field(default_factory=dict)
    mode: str = "seeds"
    not_built: dict[int, dict] = field(default_factory=dict)  # seed -> what tripped
    worlds: dict[int, dict] = field(default_factory=dict)  # seed -> table hashes, built seeds only
    repeat: Optional[dict] = None  # {"repeat_of": seed, "world": ...}: a second rebuild of one seed
    measures: dict[int, dict] = field(default_factory=dict)  # seed -> band_measures.measure(), seeds whose models built

    @property
    def passed(self) -> bool:
        return all(v["passed"] for v in self.verdicts.values())


def _commit() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def _load_progress(progress: Path, commit: str, gate_names: list[str]) -> tuple[dict[int, dict], Optional[dict]]:
    """Finished seeds from a progress file, {seed: entry}, and the repeat entry if
    saved. A header from another commit or gate set refuses; a torn last line
    (power cut mid-write) is dropped, and that seed reruns."""
    done: dict[int, dict] = {}
    repeat = None
    lines = progress.read_text(encoding="utf-8").splitlines()
    header = json.loads(lines[0])
    if header["commit"] != commit or header["gates"] != gate_names:
        raise ValueError(f"{progress.name} was written at commit {header['commit'][:12]} with gates "
                         f"{header['gates']}; this run is {commit[:12]} with {gate_names}. Results from "
                         "another tree are not mixed: move the file aside to start over")
    for i, line in enumerate(lines[1:], start=2):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            if i == len(lines):
                break  # torn final line
            raise
        if "repeat_of" in entry:
            repeat = entry
        else:
            done[entry["seed"]] = entry
    return done, repeat


def _save(progress: Optional[Path], entry: dict) -> None:
    if progress is None:
        return
    with progress.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
        f.flush()
        os.fsync(f.fileno())


def run(seeds: list[int], rebuild: Callable[[int], None], gates: list[Gate],
        progress: Optional[Path] = None, fingerprint: Optional[Callable[[int], dict]] = None,
        measure: Optional[Callable[[int], dict]] = None) -> RunRecord:
    """Rebuild at each seed, record one outcome per gate per seed, then judge across seeds.

    With `progress`, each seed's result is appended to that file the moment the
    seed finishes, a restart skips every seed already there, and the verdict is
    judged from the saved results. A seed cut off mid-rebuild has no line and
    reruns from DDL.

    A rebuild a generator's guard refuses (SeedNotBuilt) is that seed's result:
    recorded with what tripped, and the run goes on; gates judge the built seeds.
    Any other rebuild that raises fails the run loudly.

    With `fingerprint`, each built seed also saves its world (table hashes), and
    after the last seed the first built seed is rebuilt once more and saved as
    the repeat, so determinism and distinctness are judged from saved results.

    With `measure`, every seed whose models built saves what each band test
    measured (tests/band_measures.py): a built seed, and a seed refused only
    because dbt tests failed, whose models are all there (owner, 2026-11-14).
    """
    if not gates:
        raise ValueError("no gates: a run that judges nothing would pass vacuously")
    commit = _commit()
    names = [g.name for g in gates]
    rec = RunRecord(commit=commit, seeds=list(seeds), outcomes={n: [] for n in names})
    done: dict[int, dict] = {}
    repeat = None
    if progress is not None:
        if progress.exists():
            done, repeat = _load_progress(progress, commit, names)
            print(f"resuming {progress.name}: {len(done)} of {len(seeds)} seeds already finished", flush=True)
        else:
            progress.parent.mkdir(parents=True, exist_ok=True)
            progress.write_text(json.dumps({"commit": commit, "seeds": list(seeds), "gates": names}) + "\n",
                                encoding="utf-8")
    results: list[dict] = []  # one entry per element of `seeds`, in order (--repeat lists seed 0 N times)
    for seed in seeds:
        if seed in done:  # saved by an earlier, interrupted run of this commit
            results.append(done[seed])
            continue
        try:
            rebuild(seed)
        except SeedNotBuilt as e:
            print(f"seed {seed}: not built, {e.detail}", flush=True)
            entry = {"seed": seed, "not_built": e.detail}
            if measure is not None and e.detail.get("guard") == "dbt_tests":
                entry["measures"] = measure(seed)
            _save(progress, entry)
            results.append(entry)
            continue
        outcomes = {}
        for g in gates:
            o = g.check(seed)
            if g.reads_truth and o.statistic is not None:
                raise ValueError(f"gate {g.name} reads truth; its record may hold a boolean only")
            outcomes[g.name] = {"seed": seed, "passed": bool(o.passed), "statistic": o.statistic}
        entry = {"seed": seed, "outcomes": outcomes}
        if fingerprint is not None:
            entry["world"] = fingerprint(seed)
        if measure is not None:
            entry["measures"] = measure(seed)
        _save(progress, entry)
        results.append(entry)
    built = [e["seed"] for e in results if "outcomes" in e]
    if fingerprint is not None and built and repeat is None:
        again = built[0]
        try:
            rebuild(again)
            repeat = {"repeat_of": again, "world": fingerprint(again)}
        except SeedNotBuilt as e:  # it built the first time: that is nondeterminism, recorded
            repeat = {"repeat_of": again, "not_built": e.detail}
        _save(progress, repeat)
    for e in results:
        if "outcomes" not in e:
            continue
        for n in names:
            rec.outcomes[n].append(e["outcomes"][n])
        if "world" in e:
            rec.worlds[e["seed"]] = e["world"]
    rec.not_built = {e["seed"]: e["not_built"] for e in results if "not_built" in e}
    rec.measures = {e["seed"]: e["measures"] for e in results if "measures" in e}
    rec.repeat = repeat
    for g in gates:
        rec.verdicts[g.name] = judge(g, rec.outcomes[g.name])
    return rec


def run_seed_machinery(rec: RunRecord, baseline: Optional[dict]) -> dict:
    """U2's verdict (owner, 2026-11-14): the run seed works if every built seed is
    deterministic and distinct, and run seed 0 is today's world. Guard trips are
    reported beside it, not counted against it."""
    worlds = rec.worlds
    canon = {s: json.dumps(w, sort_keys=True) for s, w in worlds.items()}
    distinct = len(set(canon.values())) == len(canon)
    rep = rec.repeat or {}
    deterministic = "world" in rep and json.dumps(rep["world"], sort_keys=True) == canon.get(rep["repeat_of"])
    seed0 = 0 in worlds and (baseline is None or worlds[0] == baseline)
    return {"kind": "u2_run_seed", "passed": len(worlds) >= 2 and distinct and deterministic and seed0,
            "built": sorted(worlds), "distinct": distinct, "deterministic": deterministic,
            "repeat_of": rep.get("repeat_of"), "seed0_is_baseline": seed0,
            "guard_trips": {str(s): d for s, d in sorted(rec.not_built.items())}}


def judge(gate: Gate, outcomes: list[dict]) -> dict:
    n = len(outcomes)
    passes = sum(o["passed"] for o in outcomes)
    if gate.kind == "hard":
        failed = [o["seed"] for o in outcomes if not o["passed"]]
        return {"kind": "hard", "passed": not failed, "failed_seeds": failed}
    if gate.kind == "draw":
        rate = passes / n
        return {"kind": "draw", "passed": rate >= gate.min_pass_rate, "pass_rate": rate,
                "min_pass_rate": gate.min_pass_rate}
    stats = [o["statistic"] for o in outcomes]
    if any(s is None for s in stats):
        return {"kind": "mean", "passed": False, "error": "a seed recorded no statistic"}
    mean = sum(stats) / n
    lo, hi = gate.band(n)
    return {"kind": "mean", "passed": lo <= mean <= hi, "mean": mean, "band": [lo, hi], "n_seeds": n}


def write_record(rec: RunRecord, out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps({"commit": rec.commit, "mode": rec.mode, "seeds": rec.seeds, "passed": rec.passed,
                                "outcomes": rec.outcomes, "verdicts": rec.verdicts,
                                "not_built": {str(s): d for s, d in rec.not_built.items()},
                                "measures": {str(s): m for s, m in rec.measures.items()},
                                "band_spread": band_spread(rec)}, indent=2))
    return path


def band_spread(rec: RunRecord) -> dict:
    """U7's work list (owner, 2026-11-14): each band test's observed range and out-of-band seeds."""
    import band_measures
    return band_measures.spread([{"seed": s, "measures": m} for s, m in sorted(rec.measures.items())])


# ── The platform's gates today ──────────────────────────────────────
# U7 pre-registers the acceptance gates and adds them here. Until then the
# runner judges the two hard gates today's world can answer.

def _platform_gates() -> list[Gate]:
    import psycopg2
    import harness

    def costing_integrity(seed: int) -> Outcome:
        sql = (ROOT / "tests" / "test_costing_integrity.sql").read_text()
        with psycopg2.connect(harness.dsn(harness.harness_values()), connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                return Outcome(passed=cur.fetchall() == [])

    return [Gate("costing_integrity", "hard", costing_integrity)]


def _repeat_gate() -> Gate:
    """Hard gate for --repeat: every rebuild of run seed 0 hashes identical to the first.

    N rebuilds of one run seed, recorded as repeats, never as N seeds: what it
    proves is determinism. Since U2 the multi-seed run (--seeds) varies the world.
    """
    import psycopg2
    import harness
    import table_hashes

    first: dict = {}

    def identical(seed: int) -> Outcome:
        with psycopg2.connect(harness.dsn(harness.harness_values()), connect_timeout=5) as conn:
            now = table_hashes.table_hashes(conn)
        if not first:
            first.update(now)
        return Outcome(passed=now == first)

    return Gate("world_identical_to_first_rebuild", "hard", identical)


#: What a rebuild and its gates read; uncommitted edits here would make saved
#: seeds and later seeds come from different trees.
RUN_INPUTS = ("generation", "sql", "cinderhaven", "orchestration", "tests/harness.py", "tests/seed_runs.py",
              "tests/table_hashes.py", "tests/test_costing_integrity.sql", "tests/band_measures.py")


def _dirty_inputs() -> list[str]:
    r = subprocess.run(["git", "status", "--porcelain", "--", *RUN_INPUTS], cwd=ROOT,
                       capture_output=True, text=True)
    return [line[3:] for line in r.stdout.splitlines() if line.strip()]


def _platform_rebuild(seed: int) -> None:
    import harness
    t0 = time.time()
    try:
        harness.run_seed(seed)  # seed_all.py builds every dbt model since U2
    except harness.GuardTripped as e:
        raise SeedNotBuilt(e.detail) from e
    print(f"seed {seed}: rebuilt in {time.time() - t0:.0f}s", flush=True)


def _platform_measures(seed: int) -> dict:
    import psycopg2
    import harness
    import band_measures
    with psycopg2.connect(harness.dsn(harness.harness_values()), connect_timeout=5) as conn:
        return band_measures.measure(conn)


def _platform_world(seed: int) -> dict:
    """The seed's world as sql/world_hashes.sql hashes it: the U2 baseline's form."""
    import harness
    return {t: {"rows": n, "hash": h} for t, n, h in harness.world_hashes(harness.harness_values())}


U2_BASELINE = ROOT / "tests" / "fixtures" / "world_hashes_before_u2.json"


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(ROOT / "tests"))
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--seeds", type=int, default=RULED_SEED_COUNT)
    g.add_argument("--repeat", type=int, metavar="N",
                   help="N rebuilds of run seed 0 (determinism), recorded as repeats, not seeds")
    args = p.parse_args(argv)
    if args.repeat:
        rec = run([0] * args.repeat, _platform_rebuild, _platform_gates() + [_repeat_gate()])
        rec.mode = f"repeat: {args.repeat} rebuilds of run seed 0; not a multi-seed run"
    else:
        dirty = _dirty_inputs()
        if dirty:
            print("refusing: uncommitted changes in files the run reads, so its results would not be "
                  f"the commit's: {', '.join(dirty)}", file=sys.stderr)
            return 2
        progress = OUT_DIR / f"progress-{_commit()[:12]}-{args.seeds}seeds.jsonl"
        rec = run(list(range(args.seeds)), _platform_rebuild, _platform_gates(), progress, _platform_world,
                  _platform_measures)
        baseline = json.loads(U2_BASELINE.read_text())["tables"]
        rec.verdicts["u2_run_seed"] = run_seed_machinery(rec, baseline)
    path = write_record(rec)
    print(f"record: {path}  ({rec.mode})")
    for name, v in rec.verdicts.items():
        print(f"  {name:30s} {'PASS' if v['passed'] else 'FAIL'}")
    m = rec.verdicts.get("u2_run_seed")
    if m:
        print(f"  {len(m['built'])} of {len(rec.seeds)} seeds built; deterministic: {m['deterministic']} "
              f"(seed {m['repeat_of']} rebuilt); distinct: {m['distinct']}; seed 0 = U2 baseline: "
              f"{m['seed0_is_baseline']}")
    for s, d in sorted(rec.not_built.items()):
        what = (f"{d['retailer']} {d['loss']:.2%} > limit {d['limit']:.1%}" if d.get("guard") == "void_deletion"
                else f"dbt tests failed: {', '.join(d.get('tests', []))}" if d.get("guard") == "dbt_tests"
                else str(d))
        print(f"  guard trip (reported, not a U2 failure): seed {s}: {what}")
    for name, keys in band_spread(rec).items():
        for key, s in keys.items():
            if s["out_of_band_seeds"]:
                seen = "no value" if s["min"] is None else f"{s['min']:.4f}..{s['max']:.4f}"
                print(f"  band out at seeds {s['out_of_band_seeds']}: {name}[{key}] observed "
                      f"{seen} over {s['seeds']} seeds, band {s['band'][0]}..{s['band'][1]}")
    return 0 if rec.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
