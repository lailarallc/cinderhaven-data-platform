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
"""
from __future__ import annotations

import argparse
import json
import math
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


@dataclass
class RunRecord:
    commit: str
    seeds: list[int]
    outcomes: dict[str, list[dict]] = field(default_factory=dict)
    verdicts: dict[str, dict] = field(default_factory=dict)
    mode: str = "seeds"

    @property
    def passed(self) -> bool:
        return all(v["passed"] for v in self.verdicts.values())


def _commit() -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


def run(seeds: list[int], rebuild: Callable[[int], None], gates: list[Gate]) -> RunRecord:
    """Rebuild at each seed, record one outcome per gate per seed, then judge across seeds.

    A rebuild that raises fails the run loudly: a seed that cannot be built is
    not a draw.
    """
    if not gates:
        raise ValueError("no gates: a run that judges nothing would pass vacuously")
    rec = RunRecord(commit=_commit(), seeds=list(seeds), outcomes={g.name: [] for g in gates})
    for seed in seeds:
        rebuild(seed)
        for g in gates:
            o = g.check(seed)
            if g.reads_truth and o.statistic is not None:
                raise ValueError(f"gate {g.name} reads truth; its record may hold a boolean only")
            rec.outcomes[g.name].append({"seed": seed, "passed": bool(o.passed), "statistic": o.statistic})
    for g in gates:
        rec.verdicts[g.name] = judge(g, rec.outcomes[g.name])
    return rec


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
                                "outcomes": rec.outcomes, "verdicts": rec.verdicts}, indent=2))
    return path


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

    Until U2 gives seed_all.py a run seed, N "seeds" can only be N rebuilds of
    one world. That run is recorded as repeats, never as N seeds, and what it
    proves is determinism: the baseline U2's characterization starts from.
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


def _platform_rebuild(seed: int) -> None:
    import harness
    t0 = time.time()
    harness.run_seed(seed)
    harness.run_build()
    print(f"seed {seed}: rebuilt in {time.time() - t0:.0f}s", flush=True)


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
        rec = run(list(range(args.seeds)), _platform_rebuild, _platform_gates())
    path = write_record(rec)
    print(f"record: {path}  ({rec.mode})")
    for name, v in rec.verdicts.items():
        print(f"  {name:30s} {'PASS' if v['passed'] else 'FAIL'}")
    return 0 if rec.passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
