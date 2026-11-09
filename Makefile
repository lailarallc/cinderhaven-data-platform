.PHONY: check-canonical harness-env harness-db seed build rebuild test test-db test-acceptance test-seeds

check-canonical:
	python scripts/check_canonical.py

# ── Test harness (U3). Each target that connects runs scripts/prod_guard.py
# first, via tests/harness.py, against the harness instance. On a machine with
# no make, run the python line directly.

harness-env:
	python tests/make_harness_env.py

harness-db: harness-env
	docker compose --env-file tests/harness.env up -d harness-db

seed:
	python tests/harness.py seed

build:
	python tests/harness.py build

rebuild:
	python tests/harness.py rebuild

test:
	python tests/harness.py test

test-db:
	python tests/harness.py test-db

# U7's pre-registered suites live in tests/acceptance/. No suites yet: pytest
# collects nothing and exits non-zero, which is the intended failure.
test-acceptance:
	python -m pytest tests/acceptance

# Until U2 gives seed_all.py a run seed, only run seed 0 exists: --seeds N>1
# is refused. The determinism proof is `python tests/seed_runs.py --repeat 3`.
test-seeds:
	python tests/seed_runs.py --seeds 30
