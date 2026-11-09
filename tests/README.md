# Test harness

Where the regen's pre-registered acceptance suites live and run (spec plan U3).

## Tiers

| Tier | What | Runs where | Command |
|---|---|---|---|
| Fast | No database connection: prod_guard wiring, the harness's own smoke tests | CI on push (`ci.yml` `python-check`) and locally | `python tests/harness.py test` |
| Database (`db` marker) | Needs a rebuilt world: the fixture connects, `test_costing_integrity.sql` | Locally, against the off-host instance | `python tests/harness.py test-db` |
| Generated world | Multi-seed runs; U7's acceptance suites | Locally, against the off-host instance | `python tests/seed_runs.py --seeds N` |

A skip anywhere fails the run (`tests/skip_is_failure.py`, loaded by `pytest.ini`). A database test fails, never
skips, when the instance is unconfigured or unreachable.

## Setup (once)

1. `python tests/make_harness_env.py` writes `tests/harness.env` (gitignored): a separate local test set, generated,
   never a production credential (U18, 2026-10-20). `tests/harness.env.example` is the template. Nothing here reads
   the platform `.env`.
2. `docker compose --env-file tests/harness.env up -d harness-db` starts Postgres on `127.0.0.1:55432`, with no
   production dump mounted.
3. `python tests/harness.py rebuild` rebuilds the world from DDL: `seed_all.py`, `dbt run` of staging,
   `seed_costing.py`, `seed_product_master_history.py`, then a full `dbt build` (profile: `tests/harness_dbt/`).
   Every step runs `scripts/prod_guard.py` against the harness host and port first.

The Makefile wraps each command (`make harness-db`, `make rebuild`, `make test`, `make test-db`, `make test-seeds`).

## Multi-seed runs

`tests/seed_runs.py` rebuilds at each run seed, records one outcome per gate per seed, and judges each gate:
`hard` fails on any seed; `draw` records a single seed's miss and fails only below its registered pass rate;
`mean` checks the across-seed mean against a band computed by rule (`poisson_band`: mean ± 1.96·√(mean/n)), never
a typed number. A gate that reads `truth` records a boolean only. Records go to `output/seed_runs/` (gitignored).

The ruled seed count is 30 (U18). Today `seed_all.py` takes no run seed — U2 gives it one — so only run seed 0
exists and the runner refuses any other. `--repeat N` rebuilds run seed 0 N times with a hard gate that every
rebuild hashes identical to the first (`tests/table_hashes.py`): a determinism proof, recorded as repeats, never
as seeds. The 30-seed run is U2's, once `seed_all.py` takes a run seed.

## Cross-repo references

`tests/external_ref.py` resolves a file in another repository as repo, pinned commit and path, verifying the
commit, a clean file and its SHA-256; it fails loudly otherwise. U7 writes the pin for price-point-architecture's
`readiness_gate.py`; U19 changes that gate to take its credentials as parameters before the harness runs it.
