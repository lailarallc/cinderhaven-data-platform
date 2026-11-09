"""Rebuild the harness's off-host instance, and run the harness's tiers.

The Makefile's targets call this; it is also the entry point on a machine with
no `make`. Every step that connects runs scripts/prod_guard.py first, against
the harness instance's host and port, so no step reaches production through a
fly tunnel.

    python tests/harness.py seed      # today's platform paths, in today's order
    python tests/harness.py build     # dbt build (all models and tests)
    python tests/harness.py rebuild   # seed + build, each step timed
    python tests/harness.py test      # fast tier: no database connection
    python tests/harness.py test-db   # database tier: needs the harness instance

Credentials come from tests/harness.env (python tests/make_harness_env.py),
a separate local test set. The platform .env is never read: children get
DATABASE_URL from the harness values and POSTGRES_PASSWORD is removed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
HARNESS_ENV = ROOT / "tests" / "harness.env"
DBT_PROFILES = ROOT / "tests" / "harness_dbt"
KEYS = ("HARNESS_PG_HOST", "HARNESS_PG_PORT", "HARNESS_PG_DB", "HARNESS_PG_USER", "HARNESS_PG_PASSWORD")


class HarnessError(RuntimeError):
    pass


def harness_values() -> dict[str, str]:
    """The harness instance's connection values: the environment, then tests/harness.env."""
    file_vals = dotenv_values(HARNESS_ENV) if HARNESS_ENV.exists() else {}
    vals = {k: os.environ.get(k) or file_vals.get(k) for k in KEYS}
    missing = [k for k, v in vals.items() if not v]
    if missing:
        raise HarnessError(
            f"harness credentials missing ({', '.join(missing)}); run python tests/make_harness_env.py "
            "and start the instance: docker compose --env-file tests/harness.env up -d harness-db")
    return vals


def dsn(vals: dict[str, str]) -> str:
    return (f"host={vals['HARNESS_PG_HOST']} port={vals['HARNESS_PG_PORT']} dbname={vals['HARNESS_PG_DB']} "
            f"user={vals['HARNESS_PG_USER']} password={vals['HARNESS_PG_PASSWORD']}")


def child_env(vals: dict[str, str]) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("POSTGRES_PASSWORD", "ALLOW_PROD_DB", "PGPASSWORD")}
    env.update(vals)
    env["DATABASE_URL"] = dsn(vals)
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"  # step logs land as they happen when redirected to a file
    return env


def guard(vals: dict[str, str]) -> None:
    """scripts/prod_guard.py's CLI against the harness host:port; non-zero aborts."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "prod_guard.py"),
                        f"{vals['HARNESS_PG_HOST']}:{vals['HARNESS_PG_PORT']}"],
                       env=child_env(vals))
    if r.returncode != 0:
        raise HarnessError("prod_guard refused the harness target; nothing connected")


def dbt_cmd(*args: str) -> list[str]:
    exe = shutil.which("dbt")
    base = [exe] if exe else [sys.executable, "-c", "import sys; from dbt.cli.main import cli; sys.exit(cli())"]
    return [*base, *args, "--profiles-dir", str(DBT_PROFILES)]


def _run(label: str, cmd: list[str], vals: dict[str, str], cwd: Path, timings: list) -> None:
    print(f"\n== {label}", flush=True)
    t0 = time.time()
    r = subprocess.run(cmd, cwd=cwd, env=child_env(vals))
    timings.append((label, time.time() - t0))
    if r.returncode != 0:
        raise HarnessError(f"{label} failed (exit {r.returncode})")


SEED_STEPS = [
    ("seed_all.py", [sys.executable, "generation/seed_all.py"], ROOT),
    ("dbt run: staging", dbt_cmd("run", "--select", "staging"), ROOT / "cinderhaven"),
    ("seed_costing.py", [sys.executable, "generation/seed_costing.py"], ROOT),
    ("seed_product_master_history.py", [sys.executable, "generation/seed_product_master_history.py"], ROOT),
]
BUILD_STEPS = [("dbt build: all", dbt_cmd("build"), ROOT / "cinderhaven")]


def run_seed(run_seed: int = 0) -> list:
    """Rebuild the world at `run_seed`. Today's platform has one world: run seed 0.

    U2 gives seed_all.py the run seed (plan U3). Until it lands, any other seed
    would rebuild the same world under another label, so it is refused.
    """
    if run_seed != 0:
        raise HarnessError(f"run seed {run_seed}: seed_all.py takes no run seed until U2; only run seed 0 exists")
    vals = harness_values()
    guard(vals)
    timings: list = []
    t0 = time.time()
    apply_roles(vals)
    timings.append(("sql/truth_roles.sql", time.time() - t0))
    for label, cmd, cwd in SEED_STEPS:
        _run(label, cmd, vals, cwd, timings)
    return timings


def apply_roles(vals: dict[str, str]) -> None:
    """Apply sql/truth_roles.sql as the harness instance's administrator (its
    bootstrap superuser): the one administrator connection the plan keeps."""
    import psycopg2
    print("\n== sql/truth_roles.sql", flush=True)
    with psycopg2.connect(dsn(vals), connect_timeout=5) as conn, conn.cursor() as cur:
        cur.execute((ROOT / "sql" / "truth_roles.sql").read_text())


def run_build() -> list:
    vals = harness_values()
    guard(vals)
    timings: list = []
    for label, cmd, cwd in BUILD_STEPS:
        _run(label, cmd, vals, cwd, timings)
    return timings


def _report(timings: list) -> None:
    print("\n== timings")
    for label, secs in timings:
        print(f"  {label:34s} {secs:8.1f}s")
    print(f"  {'TOTAL':34s} {sum(s for _, s in timings):8.1f}s")


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "help"
    try:
        if cmd == "seed":
            _report(run_seed())
        elif cmd == "build":
            _report(run_build())
        elif cmd == "rebuild":
            _report(run_seed() + run_build())
        elif cmd == "test":
            return subprocess.run([sys.executable, "-m", "pytest", "-m", "not db", "tests"], cwd=ROOT).returncode
        elif cmd == "test-db":
            vals = harness_values()
            guard(vals)
            return subprocess.run([sys.executable, "-m", "pytest", "-m", "db", "tests"], cwd=ROOT,
                                  env=child_env(vals)).returncode
        else:
            print(__doc__)
            return 2
    except HarnessError as e:
        print(f"harness: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
