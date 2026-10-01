# Cinderhaven Data Platform — Current Work Plan

The current arc of work. Updated when the arc changes, not every
session. For session-by-session state, see HANDOFF.md.

---

## ACTIVE ARC (2026-06-12 — causal fulfillment, tracked externally)

The causal-fulfillment arc (single fulfillment reality as the causal
source for every downstream figure) is planned and tracked in the
**cinderhaven-causal-fulfillment** repo — PLAN.md, HANDOFF.md,
CAUSAL_FULFILLMENT_DESIGN.md, and verification/ live there. This repo
receives the commit-gated implementation groups. Status: **ARC COMPLETE
through production deployment (2026-06-14).** All 6 groups (A–F)
accepted, Phase 4 canonical relock applied, Fly.io Postgres reseeded
with causal model data (2,399,045 rows), dbt build 437/437 PASS,
canonical freeze guard 12/12 GREEN. Volume extended 1GB→3GB (permanent).
Backup of pre-causal state preserved at project root.

**DTC cost layers deployed (2026-06-20).** Fulfillment cost (18–22%,
weight-based, Q4 surcharge), platform/payment fees (5–6%), and
packaging-aware returns added to DTC pipeline. Prod reseeded
(2,305,185 rows), dbt build 457/457 PASS, DTC margin 52.8%.

**Downstream cascade complete (2026-06-20).** All 12 downstream tools
regenerated from reseeded platform. 6 committed+deployed (short-ship-cost,
retailer-deduction-recovery, contract-to-cash, where-the-money-comes-from,
trade-spend-leakage, sku-rationalization-framework). 5 no-delta
(data independent of failure rates). 1 blocked (recall-blast-radius —
DDL schema mismatch, structurally independent of this cascade).

**Slotting dispute fix cascade (2026-06-28).** 333 fake slotting disputes
removed. Canonical restatement: recovery ~16%→~15%, win rate stays ~42%,
dispute rate ~35% added. 5 repos updated (Phase A). JSON re-exported
(Phase B). 10-tool regen (Phase C): 2 data changes committed
(trade-spend-leakage, sku-rationalization-framework), 4 no-delta, 2
gitignored extracts, 1 skipped (recall-blast-radius). 2 bugs fixed:
production-demand-forecast search_path, contract-to-cash NULL recovered.
All pushed.

---

## Goal (2026-05-15 — dirty dataset arc, COMPLETE)

Create a standalone repository containing a realistically degraded
clone of the Cinderhaven dataset. Generators take the clean SQLite as
input and introduce root-cause-organized defects (Excel damage,
governance decay, integration gaps) with configurable severity and
deterministic output. Purpose: supply future data-hygiene portfolio
pieces with data that is genuinely hard to clean.

Requirements: docs/brainstorms/dirty-dataset-requirements.md
Plan: docs/plans/2026-05-15-001-feat-dirty-dataset-generators-plan.md
Repo: github.com/MsShawnP/cinderhaven-data-dirty
Tier: Medium

## Goal (2026-05-12 — platform arc, COMPLETE)

Build a portfolio-quality modern data platform (Postgres + dbt +
Dagster) that demonstrates the practice can build data infrastructure.
Primary audience: technical reviewers (client CTOs, fractional CTOs,
hiring managers).

## Why this arc, why now

Every shipped portfolio piece is analytical — queries, dashboards,
reports. None demonstrate data engineering. The platform fills this
gap and becomes the substrate every future piece runs on. Building it
now unblocks Contract-to-Cash (#193) and compounds with every
downstream build.

## Business question this arc answers

Can the practice build real data infrastructure, not just analytical
scripts on bundled files?

## Scope (from /clarify — 2026-05-12)

- **Data source:** Existing cinderhaven-data repo (21 tables, 1.1M+
  rows, SQLite) is the bootstrap. Platform ingests into Postgres,
  transforms via dbt. cinderhaven-data becomes dormant once platform
  is live. Data gaps (Shopify DTC, additional POS) assessed during
  build. EDI deferred to EDI Pre-flight delivery.
- **Deployment:** Postgres on Fly.io, dbt docs on GitHub Pages,
  Dagster hosted or screenshot-documented.
- **Quality bar:** Production polish. No errors, no clunky interfaces,
  professional design/layout. Portfolio impressiveness wins when it
  conflicts with pragmatism.
- **Role split:** Claude Code does technical implementation. User
  directs domain modeling, business logic, narrative, quality review.
- **Consumer migration:** Not in v1. Existing projects stay on SQLite
  submodules. Migration is future work.

## Tasks

See decomposition below for detailed sub-tasks.

---

## Decomposition: Full Platform Build

Goal: Deliver a portfolio-quality data platform with Postgres, dbt,
Dagster, hosted docs, and professional documentation.

### Phase 1: Infrastructure

- [x] P1.1: Provision Postgres on Fly.io
    - Depends on: none
    - Done when: `psql` connects to remote database, can CREATE TABLE
      and INSERT a test row
- [x] P1.2: Design raw schema DDL from existing SQLite tables
    - Depends on: none (can work locally)
    - Done when: SQL file exists with CREATE TABLE for all 16 data
      tables, column types mapped from SQLite → Postgres
- [x] P1.3: Build ingestion script (SQLite → Postgres raw schema)
    - Depends on: P1.1, P1.2
    - Done when: Python script loads all 16 tables from
      cinderhaven-data SQLite into Postgres `raw` schema, row counts
      match source

### Phase 2: Data Gap Assessment + Generation

- [x] P2.1: Audit existing data for gaps against brief
    - Depends on: none
    - Done when: written assessment of what exists vs. what the brief
      specifies (Shopify DTC, POS shape, any missing layers), with
      recommendation on what to generate
- [x] P2.2: Generate missing synthetic data layers
    - Depends on: P2.1 (need gap assessment to know what to build)
    - Done when: new data tables exist in cinderhaven-data SQLite with
      realistic volume and quality, generation scripts documented
- [x] P2.3: Load new data into Postgres raw schema
    - Depends on: P1.3, P2.2
    - Done when: all new tables loaded into Postgres `raw` schema,
      row counts verified

### Phase 3: dbt Foundation + Staging

- [x] P3.1: Initialize dbt project and configure connection
    - Depends on: P1.1 (need Postgres running)
    - Done when: `dbt debug` passes, profiles.yml configured,
      project compiles with no errors
- [x] P3.2: Define dbt sources (raw schema tables)
    - Depends on: P3.1, P1.3 (need dbt project + data in Postgres)
    - Done when: `sources.yml` defines all raw tables, `dbt compile`
      succeeds
- [x] P3.3: Build staging models (raw → typed, cleaned, deduped)
    - Depends on: P3.2
    - Done when: one staging model per source table, `dbt run`
      materializes all staging models without errors
- [x] P3.4: Write staging tests
    - Depends on: P3.3
    - Done when: `dbt test` passes — unique keys, not-null on
      required columns, accepted values where applicable

### Phase 4: dbt Transformation + Marts

- [x] P4.1: Build intermediate models (entity resolution, crosswalks)
    - Depends on: P3.3
    - Done when: deduction reason code crosswalk, SKU-across-systems
      resolution, and retailer-payment joins modeled as intermediate
      models, `dbt run` succeeds
- [x] P4.2: Build dimension marts (dim_products, dim_retailers,
      dim_deduction_reasons)
    - Depends on: P4.1
    - Done when: dimension tables materialized, GTIN hierarchy
      modeled, retailer-specific attributes included, `dbt run`
      succeeds
- [x] P4.3: Build fact marts (fct_orders, fct_shipments,
      fct_chargebacks, fct_deductions, fct_payments)
    - Depends on: P4.1, P4.2
    - Done when: fact tables materialized with correct foreign keys
      to dimensions, `dbt run` succeeds
- [x] P4.4: Write mart tests (data contracts on critical joins)
    - Depends on: P4.2, P4.3
    - Done when: `dbt test` passes — referential integrity between
      facts and dimensions, deduction-to-order lineage valid,
      financial totals reconcile to source

### Phase 5: Dagster Orchestration

- [x] P5.1: Initialize Dagster project, integrate with dbt
    - Depends on: P3.1 (need dbt project)
    - Done when: `dagster dev` launches, dbt assets appear in
      Dagster UI
- [x] P5.2: Define asset dependencies and lineage
    - Depends on: P5.1, P4.3 (need full dbt model graph)
    - Done when: Dagster asset graph shows correct dependency chain
      from raw → staging → intermediate → marts
- [x] P5.3: Configure scheduling and capture screenshots
    - Depends on: P5.2
    - Done when: schedule defined for full pipeline refresh, asset
      graph screenshot saved to repo docs

### Phase 6: Documentation + Polish

- [x] P6.1: Create architecture diagram
    - Depends on: none (can draft early, finalize after Phase 4)
    - Done when: SVG/PNG diagram showing source → ingestion →
      warehouse → transformation → marts → consumers, included
      in README
- [x] P6.2: Generate and host dbt docs on GitHub Pages
    - Depends on: P4.4 (need complete models with descriptions)
    - Done when: dbt docs site live on GitHub Pages, lineage
      graph navigable, every model and column has a description
- [x] P6.3: Write walkthrough article
    - Depends on: P4.4, P5.3 (need complete platform to write about)
    - Done when: markdown article in repo covering source contracts,
      staging decisions, crosswalk design, test philosophy,
      orchestration approach
- [x] P6.4: Polish README, repo structure, final validation
    - Depends on: P6.1, P6.2, P6.3
    - Done when: README is professional with architecture diagram,
      repo structure is clean, `dbt build` runs end-to-end with
      zero errors, all docs accurate — ready to flip public

## Out of scope for this arc

- Migrating existing consumer projects to Postgres
- EDI data layers (deferred to EDI Pre-flight)
- Docker Compose / cross-platform "clone and run" setup
- Real-time / streaming ingestion
- Snowflake, BigQuery, or alternative warehouses
- MLOps / feature stores
- Data lake / lakehouse architecture
- Reverse ETL
- Multi-tenant or multi-environment setup
- Metabase/Lightdash dashboard (nice-to-have, not v1 requirement)

## Definition of done for this arc

- [x] Postgres on Fly.io has all Cinderhaven data loaded
- [x] dbt models build clean: staging → intermediate → marts
- [x] dbt tests pass with no failures
- [x] dbt docs hosted on GitHub Pages with lineage visible
- [x] Dagster asset graph visible and running
- [x] Architecture diagram on README
- [x] Written walkthrough in repo explaining design decisions
- [x] Repo is private, clean, professional — ready to flip public
- [x] A technical reviewer browsing the repo sees infrastructure
      capability, not scripts

---

## Arc history

When an arc completes, archive its goal, completion date, and outcome
here. Then start a new arc above. Provides continuity without bloating
the active plan.

### 2026-05-15 — Dirty dataset arc

Shipped cinderhaven-data-dirty: 6 root-cause degraders, 3 severity
levels, deterministic output, 18 tests passing. Repo at
github.com/MsShawnP/cinderhaven-data-dirty. Key learning: cascade
model must follow actual join keys (sku), not assumed ones (upc/gtin).

### 2026-05-13 — Platform arc

Shipped cinderhaven-data-platform: Postgres on Fly.io, 34 dbt models,
132 tests, Dagster orchestration, dbt docs on GitHub Pages. All 19
tasks complete.

---

## Improvement History

### 2026-10-01 — Audit (health check only)
- **Findings:** 0 critical, 7 important, 4 nice-to-have
- **Top concerns:** The README Quick start fails: scripts/dump_flyio.sh proxies to Fly app `cinderhaven-data-platform-db`, which does not exist (the real app is cinderhaven-db), and the README runs `docker compose up` before the dump, so init-db.sh warns and exits with an empty database. Verification judged this stale docs rather than a broken system (prod workflows use cinderhaven-db; HANDOFF documents the seed_all.py path) so it is counted as important.
- **Other items:** dbt docs badge/link 404s (Pages not re-enabled after the move to lailarallc; docs snapshot from 2026-05-18). README stats stale (claims 38/38/27/313 vs 41 raw, 41 staging, 32 marts, 87 models, 371 tests) and still calls the root canonical pointer the source of truth. Prod-guard wiring tests never run in CI and pytest is undeclared. HANDOFF (last 2026-07-29) and PLAN active arc (June) lag ~30 commits. CLAUDE.md stack section is still template text and its design-system path is broken. Four DECISIONS entries from 2026-07-29 sit only on unmerged origin/claude/cinderhaven-verify-enrich-het3l0. Nice: canon's "$296K superseded" lines read ambiguously now that $296K/yr is the live short-ship figure; 11 stale remote branches (8 merged, 3 carrying the abandoned May 17 integrity layer); 640 MB June prod dump and two detached worktrees in the working dir (gitignored); repo-level POSTGRES_PASSWORD Actions secret conflicts with the org-secrets policy unless documented as an exception.
- **Verified OK:** Security, code-quality and data-correctness reviews done manually (/security-review and /ce:review not callable from the subagent). gitleaks history clean apart from 3 placeholder DSNs; .gitignore covers secrets, dumps and *.db; pre-commit gitleaks hook configured. Every Postgres writer is behind prod_guard; vendored guard copies identical. No model multiplies order quantities by case_pack_qty after the 2026-09-28 fix; short-ship canon internally consistent (887,699/3 = $296K/yr); drift gate clean (41 retired tokens). CI and canonical-drift green on a62695f. Tests: no listeners on 5432-5434/15432-15433; tests/test_prod_guard_wiring.py 4 passed, 1 deselected (system Python, DB env vars unset); check_canonical_drift.py clean. Skipped: Dagster guard test and dbt parse (writes outside repo); check_canonical.py, verify_canonical.py, dbt build/test, test_costing_integrity.sql (needs prod DB). Step 2 interview skipped (batch mode). No untracked files left behind.
- **Action taken:** Audit only — no fixes this session
- **Next review:** 2026-10-22
