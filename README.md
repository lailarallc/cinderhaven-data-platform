# Cinderhaven Data Platform

[![CI](https://github.com/MsShawnP/cinderhaven-data-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/MsShawnP/cinderhaven-data-platform/actions/workflows/ci.yml)
[![dbt docs](https://img.shields.io/badge/dbt%20docs-live-blue)](https://msshawnp.github.io/cinderhaven-data-platform/)

The complete source-to-mart data platform behind every published Lailara LLC engagement — a synthetic $25M specialty food brand with real data shapes, real volume, and real retailer complexity, so analytical methodology can be shown in full without exposing client data.

## What it does

Cinderhaven Provisions is an invented brand: ~$25M annual manufacturer revenue, 50 SKUs across 5 product lines, 6 contracted retailers (Walmart, Costco, Whole Foods, Sprouts, Kroger, a regional group), 3 distributors (UNFI, KeHE, DPI Northwest), and a Shopify DTC channel, across a 36-month data window.

This repo builds and maintains the warehouse that models it end to end:

- **Generate** — Python seed scripts create three years of transactional data (orders, shipments, deductions, payments, scan data, promotions) and load it into Postgres via chunked, resumable COPY.
- **Transform** — dbt models the raw data through staging, intermediate, and mart layers:

| Layer | Count | Materialization | Purpose |
|-------|-------|-----------------|---------|
| Raw | 38 tables | table | Faithful copy of source data |
| Staging | 38 models | view | Type casting, cleaning, null handling |
| Intermediate | 14 models | view | Crosswalks, entity resolution, economics |
| Marts | 27 models | table | 7 dimensions, 16 facts, 4 analysis marts |

- **Test** — 313 dbt tests enforce unique keys, not-null business columns, accepted values, and referential integrity between facts and dimensions.
- **Orchestrate** — a Dagster project wraps the dbt models as assets on a daily schedule.

## Why it matters

Seven published projects read from these marts — none generates its own sample data, so every figure across the portfolio traces back to one warehouse:

| Project | What it does | Live |
|---------|-------------|------|
| [product-data-health-audit](https://github.com/MsShawnP/product-data-health-audit) | Data readiness audit — traces ~$93K/yr in chargebacks to specific product data defects | [audit.lailarallc.com](https://audit.lailarallc.com) |
| [retailer-deduction-recovery](https://github.com/MsShawnP/retailer-deduction-recovery) | Deduction recovery — $1.35M backlog, five compounding operational failures, recovery simulation | [deductions.lailarallc.com](https://deductions.lailarallc.com) |
| [short-ship-cost](https://github.com/MsShawnP/short-ship-cost) | Short-ship cost — $888K over three years across four cost dimensions ($296K/yr) | [shortships.lailarallc.com](https://shortships.lailarallc.com) |
| [trade-spend-leakage](https://github.com/MsShawnP/trade-spend-leakage) | Trade spend forensics — double-funded promotions, phantom promos, rate discrepancies | [trade-spend.lailarallc.com](https://trade-spend.lailarallc.com) |
| [otif-blind-spot](https://github.com/MsShawnP/otif-blind-spot) | OTIF diagnostic — 99.2% internal fill vs 84.5% of Walmart shipments on time and complete, $57K/yr exposure | [otif.lailarallc.com](https://otif.lailarallc.com) |
| [contract-to-cash](https://github.com/MsShawnP/contract-to-cash) | Revenue lifecycle — traces every invoiced dollar to cash receipt (87¢ per dollar) | [cash.lailarallc.com](https://cash.lailarallc.com) |
| [where-the-money-comes-from](https://github.com/MsShawnP/where-the-money-comes-from) | Channel profitability — ~$54K more contribution per $1M deployed to retail vs distribution | [capital.lailarallc.com](https://capital.lailarallc.com) |

**Canonical integrity.** `CINDERHAVEN_CANONICAL.md` locks the headline numbers (revenue, trade rates, chargeback counts, OTIF gaps) so no downstream project re-derives them and drifts. `scripts/check_canonical.py` validates the live database against those locked values on every regen and fails if any figure drifts beyond tolerance (2% for dollar amounts, 0.5 percentage points for rates).

## Quick start

```bash
# Start Postgres 16 locally (init script restores from a pg_dump)
docker compose up -d

# Install Python dependencies (dbt-core, dbt-postgres, psycopg2, dotenv)
pip install -r requirements.txt

# Validate the warehouse against the canonical locked figures
make check-canonical

# Refresh the local dump from the Fly.io production database (requires flyctl auth)
./scripts/dump_flyio.sh
```

Default credentials: `postgres`/`postgres`, database `cinderhaven` (see `.env.example`).

## Canonical enforcement (single-canonical program)

`reference/canonical_values.yml` is the one canon. `scripts/verify_canonical.py`
emits two derived artifacts on every run — `reference/canonical_values.json`
(machine-readable) and `reference/supersedes.txt` (retired figures). Consuming
repos vendor these plus the drift gate and stay in sync via
`scripts/refresh_canonical.py`, which copies **four** synced artifacts from this
platform: `canonical_values.json`, `supersedes.txt`, `check_canonical_drift.py`
(the gate itself), and `refresh_canonical.py` (self-updating). A CI drift gate
(`check_canonical_drift.py` + `.github/workflows/canonical-drift.yml`) fails any
build that lets a retired figure reach a live surface. To change a figure: edit
the yml → run `verify_canonical.py` → run `refresh_canonical.py` in each repo →
commit.

> **Gate-sync note (2026-08-01):** the gate script became a synced artifact on
> this date (case-insensitive matching, portable Windows/Linux). Tool repos pull
> the hardened gate automatically on their next `refresh_canonical.py` run;
> until a given repo has refreshed, it carries the earlier gate. That earlier
> gate matches allowlist/exclusion patterns **case-sensitively on Linux CI**, so
> **do not add a mixed-case `.canonical-allowlist` pattern in a repo before it
> has been refreshed** — write allowlist globs in the exact case of the path, or
> refresh the repo first.

## Tech stack

| Component | Tool | Version |
|-----------|------|---------|
| Warehouse | Postgres on Fly.io | 16 |
| Transformation | dbt-core + dbt-postgres | 1.11 |
| Orchestration | Dagster + dagster-dbt | 1.13 |
| Ingestion | Python (psycopg2 COPY) | 3.13 |

## Project structure

```
cinderhaven/                # dbt project (staging / intermediate / marts + tests)
orchestration/              # Dagster project (assets, jobs, schedules)
scripts/                    # seeders, COPY-based loader, canonical validator
sql/raw_schema.sql          # 38 CREATE TABLE statements
docs/                       # architecture, walkthrough, data-gap assessment, dbt docs
CINDERHAVEN_CANONICAL.md    # single source of truth for headline figures
```

Note: the `copack` schema (co-packer S&OP tables) is owned by the
[production-demand-forecast](https://github.com/MsShawnP/production-demand-forecast) project and
survives platform reseeds — `seed_all.py` drops only the `raw` schema. Seed it from that repo
with `python db/seed_copack.py`.

Further reading: [Architecture](docs/architecture.md) · [Walkthrough](docs/walkthrough.md) · [Data gap assessment](docs/data-gap-assessment.md) · [dbt docs](docs/dbt-docs/index.html)

## License

MIT

---

Built by [Lailara LLC](https://lailarallc.com) — data hygiene and analytics consulting for specialty food brands scaling into national retail.
