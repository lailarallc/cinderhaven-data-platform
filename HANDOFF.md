# Cinderhaven Data Platform — Handoff Log

Session-by-session state. Updated by /log mid-session and /wrap at
session end.

For durable choices, see DECISIONS.md.
For the current work arc, see PLAN.md.
For things that didn't work, see FAILURES.md.

---

## 2026-07-29 (wrap) — cost-side data model, production deploy, period-explicit canonical; all merged to main

**Started from:** Phase 1 complete (entry below). User directed the full
enrichment arc across several turns.

**Did (four arcs, all merged to main at `0ea3961` via squashed PR #2):**
- **Cost side.** New isolated `costing` schema — `fct_product_costs`,
  `fct_inventory_snapshot`, `dim_suppliers`, `fct_supplier_invoices`, plus
  production runs, inventory lots, lot balances, and a lot→shipment→store
  bridge. Five named margin lines (gross-at-standard 51.98%, contribution
  49.01%, gross-at-landed ~43.5%, loaded-at-standard 42.5% flat,
  loaded-at-actual 42.3% blended). PPV carries the compression (standard
  frozen at launch; actual walks 45.0→42.4→39.6). CCC 119.7 (t36m,
  production). Additive-only: nine protected tables byte-identical before/after.
  No cross-schema FKs (DROP SCHEMA raw CASCADE would silently drop them);
  integrity in the generator + `tests/test_costing_integrity.sql`. Stored
  totals are GENERATED STORED.
- **Production deploy.** Dispatch-only workflow `deploy-costing.yml` with a
  pre-flight guard (halts if `costing` holds rows unless force_recreate).
  First install — `costing` did not previously exist. Every acceptance figure
  matched the replica; integrity clean. One-cent divergence on
  `fct_retailer_payments` + `mart_channel_contribution` diagnosed as a
  different seed run, not tampering (it foots, raw=mart, only float-rounded
  currency columns differ).
- **Period-explicit canonical.** Rebuilt `CINDERHAVEN_CANONICAL.md` →
  `reference/` so every value carries a basis AND a period; added
  machine-readable `reference/canonical_values.yml` keyed
  `metric.basis.period`; root pointer left behind. Default period **cy2025**
  (≡ trailing_12m). Headline: prior canonical figures were silently
  trailing-36m, which is why cy2025 tools read as failing (DIO 127.3=t36m,
  cy2025=134.6). Guards hard-fail if the file is missing;
  `verify_canonical.py` reads the YAML. Three findings recorded not smoothed:
  2024 revenue is a velocity peak on a shrinking door base; authorizations
  9,943/0/49 is an initial-load artifact; promo spend + deauths are zero in
  cy2025 (windows ended 2024). Values VERIFIED-AGAINST-PRODUCTION via
  read-only workflow.
- **CI bug fixed.** `canonical-drift.yml` had hardcoded the literal string
  `REDACTED` as the Postgres password since `a4cebc4` — the drift check had
  **never** authenticated. `f97abbf` interpolates `$POSTGRES_PASSWORD`; drift
  now green against production.

**State:** main `0ea3961`, clean. PR #1 (Phase 1 + cost side) and PR #2
(period-explicit canonical) both merged. Designated branch recreated from main
for this wrap. `costing.*` live in production, nine protected tables intact,
**nothing wired to `costing.*`** — no tool, no dbt model, no live app.
Local replica is ephemeral to the container. flyctl/Fly creds are NOT in the
session; all production work went through dispatch-only GitHub Actions
(FLY_API_TOKEN + POSTGRES_PASSWORD secrets). Remote branch deletion is blocked
from the session env (git proxy + REST both refuse); user deletes branches.

**Next (post-CEO-window, separate work):** wire tools to `costing.*` one at a
time (recall-blast-radius, the four margin tools, Spin Rate migration, etc.).
The four UNSOURCED hypotheses (trade-spend trajectory, best-seller-worst-margin,
master-data degradation, deduction learning curve) still need SPINS/Nielsen
checks before becoming demo numbers. `reference/COST-SIDE-DATA-SPEC.md` was
referenced by the user but never existed in the repo — schemas were designed
from the prompt.

---

## 2026-07-29 — Phase 1: canonical verified against Postgres, both contradictions resolved, pre-Phase-2 baseline recorded

**Started from:** Two-phase instruction from user. Phase 1 (measure,
read-only) to run tonight; Phase 2 (enrich the generator) explicitly
blocked pending go-ahead — a CEO may see the live site within 48 hours
and Phase 2 moves published figures across ~20 repos.

**Did:**
- Could not reach the live Fly Postgres — no `flyctl`, no Fly
  credentials in this remote environment. Substituted a deterministic
  local replica: native PostgreSQL 16 cluster, `scripts/seed_all.py`
  (SEED=42, frozen block untouched), then `dbt build` — 457/457 PASS.
  Replica reproduces every documented row count exactly (2,873/484
  chargebacks, 14,947/1,970 deductions, 50 SKUs, 222 remittances);
  `verify_canonical.py` zero delta, `check_canonical.py` 12/12 PASS.
  Caveat recorded in canonical: this cannot detect a manual edit made
  directly against production.
- Verified 17 canonical figures. One drift found: trailing-52w scan
  revenue measures **$32,323,139.62 against a documented $32.8M**
  (−1.5%), passing the freeze guard only on its ±2% tolerance.
  Deliberately NOT corrected in the locked tables — it is the
  denominator for the published 11.0% / 9.8% / 1.2% trade rates, so
  correcting it moves percentages portfolio-wide. Flagged for an
  explicit user decision.
- **Contradiction 1 resolved:** `invoiced == gross_payments` is exact
  by construction. `generate_remittances()` partitions every order into
  exactly one retailer-month remittance with `gross = sum(order
  totals)`; `finalize_remittances()` sets `net = gross −
  total_deductions`. No aging bucket, no bad-debt concept anywhere in
  the schema. Uncollected receivables are $0. The data is right;
  contract-to-cash's hero copy is wrong and needs rewriting.
- **Contradiction 2 resolved:** 32,539,868 and 32,800,000 are the same
  measure (trailing-52w scan revenue) at different generator vintages.
  `seed_void_patterns.py` DELETEs scan rows under a ≤1% per-retailer
  guard; each step stayed inside the 2% tolerance so canonical was
  never updated. Both stale; current value $32,323,139.62.
- Recorded the pre-Phase-2 baseline in canonical: revenue by year,
  growth decomposition, trade rates, deduction rates by year and
  partner, seasonality, COGS availability, authorizations, promotions.

**Three Phase 2 premises measured as wrong:**
- **COGS already exists.** Listed under NEEDED as "the number does not
  exist." It exists at every layer — `raw.sku_costs`, `dim_products`,
  `mart_channel_contribution`, `dim_category_benchmarks`,
  `int_loaded_contribution_by_sku`. 85 cost/margin columns, populated
  for 50/50 SKUs, margin 33.3%–65.3%. Whatever blocks the four tools,
  it is not data availability.
- **There is no growth to reshape.** Invoiced $25.09M / $25.64M /
  $25.15M — flat, down in 2025. Doors fixed at 640 all three years, so
  growth decomposes to 100% velocity / 0% new doors; active sku-store
  pairs decline 9,943 → 9,584 → 9,127. Distribution-led growth would
  have to be manufactured, not tilted.
- **Seasonality exists and is strong** — CV 27.0%, 2.92×
  peak-to-trough. Pooling all 3 years hides that 2023 is a launch ramp
  (Jan index 8.3). True 2024–25 shape: Nov/Dec holiday peak, February
  the second-weakest month (~70). Super Bowl peak genuinely absent, but
  the fix is reshaping an existing signal, not adding one. If the
  forecast tool renders noise against a 2.9× seasonal, that points at
  the tool.

Stop-date claims all confirmed: authorizations effectively end 2023
(49 rows in 2025 are void-finder inserts), last deauthorization
2024-11-10, promotions end 2024-11-03. Extra finding: `promo_billback`
deductions continue through 2025 (546 rows), so billbacks already
outlive the promotions that would justify them.

Opportunistic check of one unsourced hypothesis: "best-selling SKU
carries the worst margin" is false for #1 (margin rank 21/50), but #2
and #5 sit in the worst four and revenue-vs-margin correlation is
already −0.357. A mild version is in the data. Other unsourced
hypotheses not investigated, per instruction.

**State:** Commit `5c50a40` on `claude/cinderhaven-verify-enrich-het3l0`,
pushed. Draft PR #1 open, CI green (`python-check`, `dbt-validate`).
Documentation-only change — one file, `CINDERHAVEN_CANONICAL.md`, gains
a "Verification Run 2026-07-29" section plus a "Last refreshed from
Postgres" line. No locked figure edited, no generator or seed touched.
Local replica still running on port 5432 (`/var/lib/postgresql/ccdata`);
it is ephemeral to this container. Self check-in armed on PR #1.

**Two setup discrepancies worth knowing:**
`reference/CINDERHAVEN_CANONICAL.md` does not exist — the file is at the
repo root, has no ASSERTED markers, no "Verification Queries" section,
and does not name the two contradictions. Queries were written from
scratch. If a separate copy is being edited elsewhere, the two have
diverged.

**Next:** Phase 2 is blocked pending explicit go-ahead. Before its
change set is worth drafting, two things need resolving: what actually
blocks the four margin tools given COGS exists, and whether the flat /
declining revenue and fixed 640-door base get rewritten (a much larger
change than "enrich"). Also open: whether to correct the $32.8M scan
revenue denominator, which cascades to published trade rates.

---

## 2026-07-18 — Canonical drift check workflow fix

**Started from:** No active arc. User reported canonical drift check
GitHub Actions workflow failing since July 11 (3 consecutive daily
failures).

**Did:** Diagnosed root cause — `POSTGRES_PASSWORD` GitHub Actions
secret out of sync with actual DB password. Likely drifted when Fly
reconciled the `postgres` role to the modified `OPERATOR_PASSWORD`
(changed July 2 during pg health check debugging) after an internal
restart between July 10–11. Verified DB accessible with local .env
password via flyctl proxy. Updated GitHub secret via stdin pipe from
.env (credential never exposed). Triggered manual run — passed.

**State:** Canonical drift check green again. Fly.io DB running,
pg health check still cosmetic-critical (known, documented). No code
changes — only the GitHub Actions secret was updated. flyctl proxy
may be running on port 5433 (will die on reboot).

**Next:** No active work arc. Outstanding items: pg health check
rebuild (Fly support or fresh app), recall-blast-radius DDL alignment.
Otherwise choose new work.

---

## 2026-07-02 (close-out) — flyctl proxy killed, 3 downstream repos already clean, cinderhaven-data re-archived, pg check PROVEN unrepairable in place

**Started from:** Four-item close-out list: kill lingering flyctl proxy,
push outstanding commits in 3 downstream repos, decide + execute
cinderhaven-db pg-check fix, re-archive cinderhaven-data.

**Did:**
- Killed the lingering `flyctl proxy 5432 -a cinderhaven-db` process
  (PID 17268). Left the persistent `fly agent run` helper process alone —
  that's shared infra for all flyctl commands, not a leftover.
- Checked trade-spend-data-diagnostic, retailer-deduction-recovery, and
  product-data-health-audit: all three were already clean and 0
  ahead/behind origin — the 2026-06-30 "regen: reconcile..." commits
  already covered what an earlier HANDOFF entry described as pending.
  Nothing to commit or push.
- cinderhaven-db pg check: user overrode the earlier REBUILD decision —
  data already verified clean via verify_canonical.py this session, so
  no reseed; and no 6-app DATABASE_URL cutover as a bolt-on to a
  close-out task. Instead ran one clean, careful in-place repair attempt:
  confirmed `flypgadmin` role exists/has a password (not a missing-role
  problem), confirmed none of the 3 tracked secrets currently match it,
  realigned it to `OPERATOR_PASSWORD` via a file-uploaded SQL script
  (inline shell-quoting through `flyctl ssh console -C` had silently
  corrupted the password to empty twice before this — see FAILURES.md),
  then proved via independent, quoting-safe checks that (a) the DB-level
  password is now provably correct and (b) the checker process's own
  live environment has the identical value — and the checker STILL
  rejects it. This rules out every credential-mismatch theory. Per the
  user's explicit fallback, did NOT escalate to a fresh-Postgres-app
  rebuild — documented as a scoped future task instead.
- Re-archived `cinderhaven-data` via `gh api -X PATCH ... archived=true`.
  Confirmed `"archived": true`.

**State:** flyctl proxy gone. 3 downstream repos confirmed already
in sync with origin, nothing pending. cinderhaven-data archived on
GitHub. cinderhaven-db `pg` check still critical — but now backed by
airtight proof it's not a credential-value problem, so no more
SQL/secrets attempts are worth trying without Fly support or a genuine
rebuild. App-facing `postgres` role and all 6 downstream apps unaffected
throughout. `cinderhaven-db-pg-health-check-blocked` memory file has the
full attempt-3 writeup.

**Next:** If the pg check is ever worth fixing: provision a fresh Fly
Postgres app (clean credentials from birth), run the seed pipeline
against it, repoint the 6 apps' `DATABASE_URL` secrets — or open a Fly
support ticket. Otherwise treat it as a known cosmetic-only red check.

---

## 2026-07-02 — lailara-website footer fixes + cinderhaven-db pg check (still blocked)

**Started from:** Fleet regen from the slotting-fix cascade truncated last
session (uncommitted edits in several downstream repos). cinderhaven-db's
internal `pg` health check critical since 2026-06-25.

**Did:**
- Committed and pushed 4 blog-post footer fixes in lailara-website/site
  (PDHA $458K→$93K on 3 posts, OTIF 95%/86%/$433K→99%/84%/~$57K on 1
  post). Deployed via GitHub Actions → Cloudflare Workers. Verified live.
- Diagnosed and attempted to fix cinderhaven-db's `pg` health check in two
  scoped rounds:
  - Round 1: found `OPERATOR_PASSWORD` secret out of sync with the
    `postgres` role's real password (root cause of the 06-20 app-level
    reset never propagating to the Fly secret). Fixed via `flyctl secrets
    set OPERATOR_PASSWORD=...` — confirmed durable. Attempted `ALTER ROLE
    flypgadmin` via direct SQL to fix the health-check role too — didn't
    survive a restart.
  - Round 2: took a verified `pg_dump` backup first (on-volume + off-box,
    byte-identical, 38.6MB/427 objects), confirmed single-machine
    topology, then tried the theory that `flypgadmin` reconciles to
    `SU_PASSWORD` on boot. Set a new `SU_PASSWORD` secret, confirmed
    propagation — `flypgadmin` still didn't authenticate with it, no
    reconcile log fired. Stopped per explicit instruction rather than try
    a third theory.
- Updated the `cinderhaven-db-pg-health-check-blocked` memory file with
  full history of both attempts.

**State:** lailara-website clean, pushed, deployed, verified live.
cinderhaven-data-platform clean, no local changes. cinderhaven-db `pg`
check still critical; `postgres`-role auth and all spot-checked apps
confirmed fine. Backup dump still on the Fly volume
(`/data/backups/pre-su-password-fix-2026-07-01.dump`) and in local
scratchpad — not yet cleaned up. trade-spend-data-diagnostic /
retailer-deduction-recovery / product-data-health-audit commits and the
flyctl proxy kill requested earlier this session were NOT executed —
flagging so they aren't assumed done.

**Next:**
1. cinderhaven-db `pg` check: rebuild `cinderhaven-db` fresh from the
   platform pipeline, or open a Fly support ticket — stop guessing at
   credential-reconciliation theories. Delete the backup dump once
   resolved either way.
2. Revisit the trade-spend-data-diagnostic / RDR / PDHA commits + flyctl
   proxy kill — still outstanding.

---

## 2026-06-30 — Slotting fix cascade: regen fixes + verify blocked

**Started from:** Phase C (10-tool downstream regen) complete from
prior session. 3 tools skipped: production-demand-forecast (search_path
bug), contract-to-cash (NULL recovered), recall-blast-radius (no repo).

**Did:**
- **Fix 1: production-demand-forecast** (72837e7, pushed)
  - `_calibrate.py` had `search_path=raw,public` but `sku_production_config`
    lives in `copack` schema. Fixed to `search_path=copack,raw,public`.
  - Ran seed_copack.py (5 tables), _calibrate.py (50 SKUs), and
    precompute_forecast.py (50 forecast + 3,900 doom-loop rows).
  - Copack schema now has 8 tables including snapshot tables.

- **Fix 2: contract-to-cash** (8e28fcc, pushed)
  - `export_json.py` crashed on `round(row["recovered"], 2)` when
    `SUM(recovered_amount)` returned NULL for undisputed deduction types.
  - Fixed with `round(row["recovered"] or 0, 2)`.
  - Re-exported all JSON. CY2024 headline: 82.8¢/dollar (matches
    canonical "CY2024 produces 83¢" in supersedes table).

- **Fix 3: recall-blast-radius** — STILL BLOCKED
  - Repo at `active/recall-blast-radius` (not `published/`).
  - `seed.py` DDL references `sku_id` column in FK constraints but
    platform uses `sku`. Insert expects `retailer_name` but platform
    column is `name`. Non-trivial schema mismatch.

- All 5 commits pushed (production-demand-forecast, contract-to-cash,
  trade-spend-leakage, sku-rationalization-framework).

- **verify_canonical.py** — attempted but Docker Desktop went down
  mid-session. Needs the Docker stale-socket workaround (rename
  `%LOCALAPPDATA%\Docker\run` + `docker-secrets-engine` aside, relaunch).

**State:** All regen fixes committed and pushed. Docker Postgres is
DOWN (Docker Desktop crashed). Platform repo has pre-existing uncommitted
changes from a prior session: `.gitignore`, `CINDERHAVEN_CANONICAL.md`,
`README.md` (modified), plus `.pre-commit-config.yaml` and
`scripts/verify_canonical.py` (untracked). These were NOT touched
this session.

**Next:**
1. Docker stale-socket fix (memory: docker-desktop-stale-socket-fix.md)
2. Run `verify_canonical.py` against local Docker Postgres
3. Investigate + commit the pre-existing dirty files in platform repo
4. recall-blast-radius DDL alignment (separate concern)
5. lailara-website deploy (Phase A commits pushed but not deployed)

---

## 2026-06-30 20:00 — Fleet regen (truncated): trade-spend rates updated, jobs incomplete

**Started from:** Full fleet regen in progress. verify_canonical.py showed 2 near-misses (chargebacks 2,873 vs 2,879, deductions backlog ~$1,347K vs $1,350K). contract-to-cash, where-the-money-comes-from, sku-rationalization-framework done. trade-spend workbook built. Multiple background jobs running (short-ship-cost, otif-blind-spot, PDHA, baked SQLite exports).

**Did:**
- Updated `trade-spend-data-diagnostic/validate_workbook.py`: waste $407K→$343K, all-in 10.5%→10.3%, structural 9.2%→9.21%, waste rate 1.2%→1.1%
- Updated `trade-spend-data-diagnostic/tests/test_canonical_regression.py`: all-in tolerance 0.102→0.103, structural 0.090→0.092
- otif-blind-spot background job confirmed complete (46,760 shipments, Walmart OTIF 84.5%, total exposure $57,196)
- Session hit context limit before any commits or test runs

**State:** trade-spend-data-diagnostic files edited but NOT committed, NOT tested. otif-blind-spot exports done, NOT committed. Background jobs for short-ship-cost, PDHA, retailer-deduction-recovery SQLite, retail-velocity-decision-tool SQLite completed (exit codes unknown — never verified). xfail decorators still in retailer-deduction-recovery (lines 81, 89) and retail-velocity-decision-tool (lines 43, 53, 61). Platform repo dirty: .gitignore, CINDERHAVEN_CANONICAL.md, README.md modified; .pre-commit-config.yaml, scripts/verify_canonical.py untracked.

**Next:**
1. Start flyctl proxy on port 5433
2. Verify short-ship-cost, PDHA, baked SQLite job outputs (check task output files or re-run)
3. If SQLite exports good: remove xfail decorators in rdr (lines 81, 89) and rvdt (lines 43, 53, 61)
4. Update CINDERHAVEN_CANONICAL.md: chargebacks 2,879→2,873, deductions backlog $1,350K→$1,347K
5. Run test suites for each repo
6. Commit + push all 9 downstream repos + platform repo
7. Consider committing /tmp/export_rdr.py and /tmp/export_rvdt.py as scripts/export_from_postgres.py

---

## 2026-06-28 — Slotting dispute fix: canonical cascade + downstream regen

**Started from:** 333 slotting deductions had fake disputes/recovery.
Prior session committed the seed fix (a72dfaf), reseeded DB, and
completed Phase A (canonical restatement across 5 repos) and Phase B
(JSON re-export in retailer-deduction-recovery).

**Did:**
- **Phase C: 10-tool downstream regen against local Docker Postgres**
  - 4 no-delta: retailer-scorecard, channel-profitability-analysis,
    retail-velocity-decision-tool, production-demand-forecast (after fix)
  - 2 data changed + committed: trade-spend-leakage (cc08567, results.db),
    sku-rationalization-framework (f848358 + 47112e0, thresholds + rescore)
  - 2 extracted but gitignored: trade-spend-data-diagnostic (14,947 deductions),
    product-data-health-audit (50 SKUs, 2,873 chargebacks)
  - 1 skipped: recall-blast-radius (DDL schema mismatch — `sku_id` vs `sku`)

- All commits from Phase A/B pushed to remotes.

**State:** All downstream tools regenerated or confirmed no-delta.
Docker Postgres has copack schema with snapshot tables.

**Next:** Fix 3 skipped tools, run verify_canonical.py.

---

## 2026-06-28 — Slotting dispute exclusion

**Started from:** Downstream cascade complete. 333 slotting deductions
had won/partial dispute outcomes with $24.6K in false recovery.

**Did:** Fixed dispute generation to exclude slotting (negotiated cost
of access, not disputable). Iterated through three approaches:
(1) in-loop `continue` before draws — shifted RNG for all subsequent
deductions; (2) pre-loop filter — identical result to (1), both skip
the same draws; (3) consume all draws, skip only the INSERT — preserves
RNG stream byte-identical for non-slotting deductions. Reseeded and
rebuilt dbt 457/457 PASS three times. Grepped all ~45 repos for
surfaces citing canonical 16% recovery / 42% win rate — found ~29
surfaces across 8+ repos.

**State:** `seed_retailer.py` committed (`a72dfaf`). Database reseeded.
Slotting disputes: 0. Current figures: 16,917 deductions / $1.35M,
6,011 disputes, 14.69% recovery, 50.15% win rate. CINDERHAVEN_CANONICAL.md
NOT updated. No downstream re-export yet. Surface audit complete.

**Next:** Decide new canonical recovery (~14.7%) and win rate (~50%)
values. Update CINDERHAVEN_CANONICAL.md. Re-export retailer-deduction-
recovery JSON and validate. Update ~29 downstream surfaces citing
16% and 42%.

---

## 2026-06-20 — Downstream cascade: 12-tool regen from reseed

**Started from:** Shipment failure distributions tuned to realistic
specialty food ranges (prior session). 12 downstream tools needed
data regeneration to reflect lower failure rates. Two previously
deployed (otif-blind-spot, channel-profitability-analysis).

**Did:**
- Regenerated all 12 tools. 5 had meaningful data changes, 4 had
  output unchanged (data independent of failure rates), 3 were
  initially blocked.
- Committed 5 tools with changes:
  - short-ship-cost (994438f) — $894K/3yr at 99.3% fill
  - retailer-deduction-recovery (ca47736) — 16,917 deductions / $1.35M
  - contract-to-cash (14ca206) — 82.9c headline
  - trade-spend-leakage (1710823) — 2,569 instances / $248K
  - sku-rationalization-framework (b285f77) — 50 SKUs rescored
- Deployed all 5: 3 Cloudflare Pages + 2 Fly.io
- Fixed where-the-money-comes-from (14b458a):
  - SQL GROUP BY bug: inner SELECTs had raw `po_date`/`deduction_date`
    but GROUP BY used `DATE_TRUNC(...)` — invalid in standard PostgreSQL
  - Added `--local` flag: psycopg2 direct connection via DATABASE_URL
    or --dsn, eliminating flyctl subprocess dependency
  - Seed metadata timestamps now use `datetime.now()` instead of
    hardcoded "2026-05-22"
  - Regenerated against local DB: $1.35M deductions, $87K short-ship
  - First Cloudflare Pages deploy for this project (project created)
- Cleared stale `CLOUDFLARE_API_TOKEN` env var (53 chars) — it was
  overriding `wrangler login` browser OAuth. Must be cleared from
  system env vars permanently.

**No-delta tools (data independent of failure rates):**
- trade-spend-data-diagnostic (.db gitignored)
- product-data-health-audit (.db gitignored)
- retailer-scorecard-renegotiation-simulator (output identical)
- retail-velocity-decision-tool (output identical)
- production-demand-forecast (calibrate output identical)

**Still blocked:**
- recall-blast-radius (at `active/recall-blast-radius`, not
  `published/`): DDL schema mismatch — genealogy tables' FK references
  `sku_id` column that doesn't exist in platform tables. Genealogy data
  is structurally independent of shipment failure rates anyway.

**State:** 11 of 12 tools resolved (6 committed+deployed, 5 no-delta).
1 blocked (recall-blast-radius — likely not affected by this cascade).
All committed tools pushed to their remotes via deploy. No broken code.

**Next:** recall-blast-radius DDL fix if needed (separate concern from
this cascade). CINDERHAVEN_CANONICAL.md short-ship figure update
($6.6M → $894K) — major change that affects thesis range. Custom
domain setup for where-the-money-comes-from (.pages.dev only currently).

---

## 2026-06-20 — DTC cost layers: production deployment to Fly.io

**Started from:** DTC cost layers built and verified locally in prior
session (commits 6069c2b, 457/457 dbt, 12/12 canonical, DTC margin
52.8%). Channel-profitability already updated and deployed (67f851f).
Prod Fly.io Postgres still on pre-cost-layer schema.

**Did:**
- Reset Fly.io postgres password via SSH local trust auth (pg_hba.conf
  uses `trust` for local socket, `md5` for TCP — exploited local socket
  to run ALTER USER)
- Reseeded prod Fly.io Postgres via flyctl proxy (localhost:5433):
  2,305,185 rows across 41 tables in 639s. New columns confirmed:
  shopify_orders.fulfillment_cost, shopify_transactions.platform_fee
- Ran dbt build against prod with `--threads 1`: **457/457 PASS**
  (87 models, 370 tests, 0 errors, 30 min)
- Verified prod DTC margin: **52.8%** ($299,091 / $566,125) — matches
  local exactly. Fulfillment $113,885 (20.1%), platform fees $30,563
  (5.4% of DTC rev incl. payment processing), refunds $21,967 (3.9%)
- Reverted ~/.dbt/profiles.yml port from 5433 back to 5432 (both
  cinderhaven and edi_reconciliation profiles)

**Downstream tools affected by DTC data changes:**
1. **channel-profitability** — already updated and deployed (67f851f)
2. **the-question-engine** — Q09 (channel contribution) needs re-run
3. **contract-to-cash** — needs JSON re-export from new mart data
4. **where-the-money-comes-from** — needs snapshot re-export

**State:** Prod Fly.io Postgres fully current with DTC cost layers.
All 457 dbt tests pass against prod. profiles.yml reverted to local
Docker port. flyctl proxy (PID 19652) may still be running on 5433.
No broken code.

**Next:** Re-run 3 downstream tools against updated prod data
(the-question-engine Q09, contract-to-cash, where-the-money-comes-from).
Or move to next work.

---

## 2026-06-16 — SKU-level seasonal profiles + archetype velocity system

**Started from:** Uniform seasonal scaler (SEASONALITY dict) applied
identically to all 50 SKUs — every product moved in parallel across
quarters. Pre-existing uncommitted archetype system (SKU_ARCHETYPES +
ARCHETYPE_VELOCITY_MULT) in working tree inflated revenue ~1.82×.

**Did:**
- Added 6 SKU-level seasonal profile shapes to seed_config.py:
  grilling (summer peak), baking (fall/winter), snack_flat, gift_spike
  (holiday ramp), emerging (steady growth), pantry_staple (near-flat).
  Each profile normalized so annual mean matches original SEASONALITY
  mean (1.0167).
- Mapped all 50 SKUs to profiles via SKU_SEASONAL_PROFILE dict.
- Wired get_sku_seasonal() into seed_scan_data.py — healthy and
  delist-risk generators use per-SKU seasonal; borderline intentionally
  excluded (declining products don't bounce back for holidays).
- Added archetype velocity system with distribution-weighted
  normalization (weighted_mean=1.8247) to keep total revenue within
  canonical tolerance despite archetype multiplier spread.
- Full reseed: 1,325,794 scan_data rows.
- check_canonical.py: 12/12 PASS. Revenue $32.47M (target $32.8M ±2%).
- Spot-checks confirmed: 3 SKUs from different lines show non-parallel
  quarterly curves; 8 unique SKUs cross the quarterly velocity median
  (12 crossover events total).

**Committed:** d84502b — feat: SKU-level seasonal profiles + archetype
velocity system.

**State:** All seed scripts updated, canonical guard green, local
Docker replica current. Not pushed to remote. Fly.io prod not reseeded.

**Next:** Push to remote when ready. Fly.io prod reseed if desired
(would need flyctl proxy + full seed_all.py run). Or move to next work.

---

## 2026-06-14 — Production deployment: causal fulfillment model to Fly.io

**Started from:** Groups A–F accepted and verified on local Docker
replica. Prod Fly.io Postgres still on pre-causal data. First prod
data change since the causal arc began.

**Did:**
- Backed up pre-causal prod state (backup-prod-2026-06-14.sql, 611 MB)
- Ran full seeder suite against prod via flyctl proxy — 41 tables,
  2,399,045 rows, completed in 1289s
- dbt build failed twice: first run hit "read-only transaction" (WAL
  pressure from scan_data COPY), second run hit OOM crash (4 threads
  materializing large tables concurrently on a 99%-full 1GB disk)
- Root cause: 1GB Fly.io volume too small for 2.4M-row dataset + mart
  materializations. Extended volume 1GB→3GB, restarted machine.
- dbt retry with --threads 1 succeeded: 437/437 PASS (85 models,
  352 tests, 0 errors)
- Checksum verification: row counts exact (41/41), MD5 comparison N/A
  (cross-installation CAST(t.* AS TEXT) differs between Docker Postgres
  17-alpine and Fly.io postgres-flex:17.2)
- Canonical freeze guard: 12/12 PASS — all business metrics match
  CINDERHAVEN_CANONICAL.md (chargebacks 6,563 exact, revenue $32.80M,
  trade rate 11.3%, OTIF $423K, short-ship $6.58M)

**Infrastructure changes (permanent):**
- Fly.io volume: 1GB → 3GB (was at 99% utilization)
- .gitignore: added `backup-*.sql` pattern

**Cleanup done:**
- ~/.dbt/profiles.yml: reverted DBT_PORT env_var override to hardcoded 5432
- flyctl proxy: stopped
- Temp scripts deleted: _check_write.py, _check_active.py

**State:** Prod Fly.io Postgres is fully current with the causal
fulfillment model. All downstream consumers can query against prod.
Backup at project root. No broken code.

**Next:** Causal fulfillment arc is COMPLETE through production
deployment. Remaining work is downstream: recovery denominator
restatement (9 surfaces in lailara-website — user handling separately),
$458K PDHA item (8 surfaces), 33 CODE_FIX entries across downstream
projects.

---

## 2026-06-13 — Channel inversion + lifecycle fix (10+4 surfaces)

**Started from:** Phase 5 Tier 4 gate pending. Channel-profitability
pipeline had run partial (live revenue, stale deductions). Needed
exact figures before narrative rewrite.

**Did:**
- Re-ran channel-profitability pipeline fully against relocked
  Postgres (all data streams live — revenue, deductions, disputes,
  COGS). Extracted the 4 key figures:
  - Retail contribution margin: 50.6%
  - Distributor contribution margin: 45.3%
  - Per-million delta: retail returns $53,140 more per $1M
  - Net cash per dollar: retail 50.6¢, distributor 45.3¢
- Revenue drifted from 2026-05-22 snapshot (UNFI −$805K, KeHE +$458K
  largest swings). Deductions now from relocked canonical set.
- Applied approved verbatim replacement blocks [A]–[D] across 7 files
  in lailara-website (12 edits total):
  - [A] hero sentence: 3 surfaces (channel-profitability page, phase-2
    engagement content)
  - [B] findings paragraph: 2 surfaces (channel-profitability page,
    phase-2 engagement content)
  - [C] shorthand: 4 surfaces (ten-decisions page, ten-decisions
    content, channel-profitability blog, ten-decisions blog)
  - [D] lifecycle 83¢→86¢ / 17¢→14¢: 4 surfaces (channel-profitability
    page, phase-2 engagement content, ten-decisions content,
    contract-to-cash blog)
- Site build verified clean. Committed 817a012, pushed.

**Not touched (per guardrails):**
- the-ten-decisions/page.tsx line 454 ("83 cents") — lifecycle
  reference not in approved list
- $458K data cost (8 surfaces) — depends on PDHA deferred item
- Recovery denominator restatement (9 surfaces) — needs approved
  two-metric phrasing
- $32.8M/$53M short-ship figures
- OTIF figures ($433K, $136K, $297K, 95%/86%)
- 33 CODE_FIX entries across downstream projects
- Chargeback prediction model AUC regression

**State:** Channel story inversion fixed on 10 surfaces. Lifecycle
figure fixed on 4 surfaces. All committed and pushed. No broken code.

**Next:** Remaining Phase 5 text changes — recovery denominator
restatement (9 surfaces, needs approved phrasing), $458K (8 surfaces,
blocked on PDHA), remaining lifecycle references, OTIF figures. Or
CODE_FIX entries to unblock downstream pipelines.

---

## 2026-06-13 — Phase 5 public surface sweep complete (Tiers 1–4)

**Started from:** Phase 4 canonical relock complete. Cascade inventory
(§5.1–5.4) ready for downstream sweep.

**Did:**
- **Tier 1 (8 high-impact):** 5 pipelines ran, 5 repos committed+pushed
  (contract-to-cash, retailer-deduction-recovery, otif-blind-spot,
  channel-profitability-analysis, short-ship-cost). 28 text changes, 19
  CODE_FIX entries cataloged. ACCEPTED.
- **Tier 2 (7 moderate):** 3 pipelines ran (chargeback-prediction-model
  AUC dropped 0.7834→0.6986 due to 1,222 unmapped receiving_discrepancy
  chargebacks; sku-rationalization scored JSON regenerated; retailer-
  scorecard no changes). 2 repos committed+pushed. 62 text changes, 12
  CODE_FIX. ACCEPTED.
- **Tier 3 (12 low):** 2 of 12 affected (monday-morning-report,
  product-master-data-model). 11 text changes, 2 CODE_FIX. ACCEPTED.
- **Tier 4 (website):** 21 surfaces scanned across lailarallc.com. 56
  text changes found (37 FIGURE_SWAP, 10 NARRATIVE_REWRITE for channel
  story inversion, 9 DENOMINATOR_MISMATCH for recovery metrics).
  **Fixed 2 LIVE-MISMATCHED pages** (trade-spend-deduction-recovery +
  trade-promotion-leakage) — committed+pushed to lailara-website
  (ef1bd41). Tier 4 catalog complete, gate pending.
- **Security fix:** Removed hardcoded Fly.io password from trade-spend-
  data-diagnostic extract script (a141819). Credential rotated by Shawn.

**Cumulative:** 48 surfaces swept, 8 pipelines ran, 9 repos with
committed output, 157 text changes cataloged, 33 CODE_FIX entries.

**State:** PHASE5_CHANGE_REPORT.md in causal-fulfillment repo has full
detail (2343448). All pipeline commits pushed. Two live-mismatched pages
fixed. Remaining 147 text changes and 33 CODE_FIX entries are cataloged
but not executed — awaiting prioritized resolution.

**Key open items from the change report:**
1. Channel story inversion (10 surfaces) — retail now beats distributor
   by ~7pts; narrative re-review needed, not mechanical swap
2. Recovery denominator restatement (9 surfaces) — "16%→65%" pairing
   needs two-metric approved phrasing
3. $458K data cost (8 surfaces) — depends on PDHA deferred item
4. 83¢→86¢ lifecycle (4 surfaces) — mechanical swap
5. Chargeback prediction model AUC regression — needs receiving_
   discrepancy added to harmonization map
6. 33 CODE_FIX entries across downstream projects

**Next:** Shawn decides priority order for remaining text changes.
Options: (1) fix channel-profitability inversion next (highest-impact
narrative issue), (2) batch all mechanical FIGURE_SWAPs across the
website, (3) address CODE_FIX entries to unblock blocked pipelines,
(4) different project entirely.

---

## 2026-06-13 — Phase 4 canonical relock complete

**Started from:** Phase 4 drift report at the approval gate. Shawn
reviewing proposed canonical set before relock.

**Did:** Received approval with one addition (usage rule for
16%/42%/65% denominator boundary). Applied §4.1–4.9 to
CINDERHAVEN_CANONICAL.md: chargebacks 6,563, deductions $1.59M/22,425,
op waste $460K/1.4%, Option C recovery restatement with usage rule,
lifecycle waterfall section, 10 SUPERSEDES entries. Updated
check_canonical.py regex for comma-formatted counts. Guard 10/10
GREEN. Committed and pushed both repos.

**State:** Both repos synced with origin. Platform ea8fd7d, causal
91be603. Canonical set relocked. Causal-fulfillment arc (Groups A–F)
fully accepted and documented. No broken code.

**Next:** Arc is done. Options: (1) cascade regen — 8 high-impact
downstream projects per drift report §5, (2) update causal repo state
files (PLAN.md needs Groups E+F checked off), (3) different project.

---

## 2026-06-13 — Group F complete, at approval gate

**Started from:** Groups A–E accepted and pushed. Group F GO —
validation + Phase 4 package.

**Did:** Full Group F verification:
- Determinism: seed_all.py ×3 (pre + 2 fresh), 41/41 byte-identical
- dbt build: 437/437 PASS, 0 errors
- Plausibility: classification 98.1%/97.9%, residual 1.9%/2.1% (all 4 GREEN)
- Freeze guard: 7/10 GREEN, 3 RED (chargeback counts — expected)
- Queried every canonical figure from Postgres replica
- Wrote PHASE4_DRIFT_REPORT.md (causal repo) with all 5 sections:
  §1 drift ledger resolved, §2 pipeline verification, §3 headline
  recompute, §4 proposed new canonical set, §5 cascade inventory

**State:** PHASE4_DRIFT_REPORT.md written to causal repo (uncommitted).
Platform repo at ed40c08. Causal repo at 0526d57. Report is AT THE
GATE — Shawn reviews before CINDERHAVEN_CANONICAL.md or
check_canonical.py change. Verification artifacts in causal repo
verification/ (groupF-{pre,run1,run2}-checksums.txt). query_canonical.py
in platform repo scripts/.

**Key proposed changes (pending approval):**
- Chargebacks: 837 → 6,563
- Deductions: $1.66M/16,023 → $1.59M/22,425
- Op waste: $480K → $460K
- Recovery: Option C two-metric restatement (16% per all ded $, 42% per disputed $)
- Short-ship $32.8M/$53M retired, replaced by fill rates 92%/94%
- Lifecycle confirmed 86¢ (85–87¢ band)
- 10 new SUPERSEDED entries
- check_canonical.py: 4 values change (3 chargeback counts + op_waste_rate)

**Next:** Shawn reviews PHASE4_DRIFT_REPORT.md Section 4. On approval:
apply changes to CINDERHAVEN_CANONICAL.md and check_canonical.py, run
guard to confirm 10/10 GREEN, commit, push both repos. Then update
causal repo state files (HANDOFF.md stale since Group D, PLAN.md
needs Group E+F checked off).

---

## 2026-06-13 16:30 — Group E ACCEPTED

**Started from:** Group E mid-implementation. finalize_remittances()
existed in both seed files; schema and staging had new columns;
mart_distributor_reconciliation CTE updated but select/gap formula not.
No reseed or verification run yet.

**Did:** Completed mart_distributor_reconciliation.sql. Fixed FK
circular dependency (skeleton INSERT then UPDATE). Fixed cp1252 Unicode
error. Applied Docker stale-socket workaround. Ran seed ×2
(determinism verified). dbt build 437/437. Built lifecycle waterfall —
86¢ confirmed as honest result (trade 9.53%, fulfillment 0.52%).
Restated lifecycle target 80–85¢ → 85–87¢; canonical relocked to 86¢.

**State:** Groups A–E complete, committed, pushed (ae77cfb). All 437
dbt tests pass. Both channels deterministic, classification rates
>97%, residuals 1–3%. Canonical lifecycle 86¢.

**Next:** Group F — validation + Phase 4 package. Build
PHASE4_DRIFT_REPORT.md with every guard check old-vs-new, headline
recomputes, and the proposed new canonical set for Shawn's approval.

---

## 2026-06-13 — Group D ACCEPTED, GO on Group E

**Started from:** Group D docs complete, stopped at acceptance gate.

**Did:** Shawn reviewed and accepted Group D. All 8 judgment calls
approved as implemented. Denominator mismatch resolved — two separately
denominated canonical metrics replace the retired "16.5% → 65%" pairing:
(1) Recovery rate ~16% per all deduction $ (standalone diagnostic),
(2) Win rate ~42% → ~65% per disputed $ (same denominator, apples to
apples). Old decision struck through in DECISIONS.md with superseded-by
note; two new entries added (denominator decision + Group D acceptance).
Both repos pushed.

**State:** Both repos at origin. Causal repo: 0526d57. Platform repo
synced. Group D is the current certified replica state.

**Next:** Group E — remittance reconstruction (§3.3). generate_remittances:
net = gross − itemized deductions − trade allowances − applied chargebacks
− timing residual (~2% target). Verify: classification rate ≥97% with
actual rate recorded, residual 1–3%, subset≤superset and net≤gross dbt
tests, mart_retailer_reconciliation unexplained gap ≈ residual only.

---

## 2026-06-13 — Group D documentation complete, stopped at acceptance gate

**Started from:** Group D verification 6/8 done, docs remaining (steps
7–8 of the checklist).

**Did:** Recovered C2-state dispute baselines from existing checkpoint
docs (GROUP-C2-VERIFICATION.md §6 and DRIFT-LEDGER.md Group C section) —
no reseed needed. Wrote all three documents in the causal repo:
1. GROUP-D-VERIFICATION.md — 8 judgment calls with alternatives
   considered (tier-conditioned selection, weight_check mapping, DQ
   factor source, ≥75 boundary, DDL column, distributor binary POD,
   filing-delay clip, universal factor application), 4 verification
   gates documented, aggregate statistics, known simplifications
2. DRIFT-LEDGER.md Group D section — disputes 4,233+462 → 7,756+926,
   evidence 12,711 → 34,743, per-disputed ~44% → 41.8% restatement
3. PLAN.md Group D entry marked verified with full summary

C2-state retailer recovered $ was not captured in any checkpoint (only
distributor: $29,458.26 from C2 verification §6). The Group D column
has the complete figures; the restatement from ~44% to ~41% per-disputed
is the meaningful signal for the drift ledger.

**State:** Replica on Group D state (main branch, 2,399,045 rows).
All verification steps complete (8/8). Causal repo committed locally
(bdf9b3c, 4 commits ahead of origin). Platform repo synced with origin.
Nothing pushed per mid-group rule.

**Next:** Shawn reviews Group D — 8 judgment calls in
GROUP-D-VERIFICATION.md §1, especially §1.1 (tier-conditioned selection
is structurally required, not stylistic) and the ~19/51/30 underlying
tier mix (moderate-centered, not 50/25/25 as PLAN sketched). On
acceptance: push both repos, then Group E (remittance reconstruction).

---

## 2026-06-12 (wrap) — Group D verification 6/8 complete, docs remaining

**Started from:** Group D implementation committed (1a9279d), run1
reseed clean, verification pending (8-step checklist).

**Did:** Steps 1–6 of the verification checklist COMPLETE:
1. Spot-checked run1 state — counts match calibration expectations
2. Wrote verify_groupD.py (4 gates + diagnostics, replay from platform
   generators, SCENARIO_B_REDRAW_SEED = 550)
3. Ran all gates — results:
   - dbt: 437/437 PASS
   - Guard: 7/10 (3 expected count REDs, all dollar checks green)
   - Determinism: 41/41 byte-identical (run1 vs run2)
   - Stream preservation: 3/41 changed (exactly retailer_disputes,
     retailer_dispute_evidence, distributor_disputes)
   - Replay linkage: 100% both channels
   - Scenario (a): combined 16.16% of all deduction dollars
   - Scenario (b): redraw 64.76% per disputed dollar
   - Per-tier recovery: 9/10 cells green; distributor strong 60.77%
     RED per-channel (sampling noise on n=478; combined wholesale
     strong 64.37% passes, dbt test grain is combined)
4. Checksums: groupD-run1 and groupD-run2 created in causal repo
5. Determinism: 41/41 identical across independent reseeds
6. dbt build 437/437, guard 7/10

**Retailer dispute aggregates:** 7,756 disputes (3,316/3,515/925
S/M/W), $209,342.28 recovered, $505,414.90 disputed, 14,256 labor
hours, 1,259 pending.

**Distributor dispute aggregates:** 926 disputes (478/343/105),
$47,257.57 recovered, $108,399.17 disputed, 1,689 labor hours,
122 pending.

**NOT done (Task 7):** GROUP-D-VERIFICATION.md, DRIFT-LEDGER.md
Group D section, PLAN.md update. These need C2-state dispute baselines
for the drift ledger's before/after comparison. Attempted to recover
C2 baselines (checked out 6fce555, reseeded C2 state) but the disputes
tables live in Postgres, not the SQLite source file — need to query
Postgres after a C2 reseed, or compute from the C2 checksum state.

**State:** Replica is on Group D state (main branch, Postgres reseed
complete, 2,399,045 rows). verify_groupD.py and both checksum files
exist in the causal repo. Nothing pushed (mid-group rule). Platform
repo 2 commits ahead of origin.

**Next concrete action:** Fresh session should:
1. Recover C2-state dispute baselines — either checkout 6fce555 +
   reseed + query Postgres for retailer_disputes/distributor_disputes
   aggregates (recovered $, disputed $, per-disputed rates), OR
   derive from the C2 verification doc if already recorded there
2. Checkout main, reseed back to Group D, verify 2,399,045 rows
3. Write GROUP-D-VERIFICATION.md (use GROUP-C2-VERIFICATION.md as
   template; §1 = 8 judgment calls from causal repo HANDOFF.md;
   include distributor strong per-channel flag as known observation)
4. Write DRIFT-LEDGER.md Group D section (disputes before→after,
   evidence 12,711→34,743, recovered $ old→new, note 44% restatement)
5. Update causal repo PLAN.md Group D entry
6. STOP at gate — push only at Shawn's acceptance

---

## 2026-06-12 (wrap) — Group D implementation committed, verification pending

**Started from:** C2 accepted; GO on Group D (evidence quality + dispute
outcomes, both channels in one treatment).

**Did:** Group D implementation complete and committed locally (WIP —
unverified, mid-group). §2.5 weakest-link evidence tiers from real
fulfillment factors; §2.4 tier-conditioned outcomes; tier-conditioned
dispute selection (the brand triages by winnability) across ALL written
deductions both channels; evidence rows mirror factor states (POD state
persisted via was_submitted/notes); distributor_disputes gains an
evidence_quality column (DDL); constants frozen after an analytic
calibration dry-run against the certified C2 state
(cinderhaven-causal-fulfillment/verification/calibrate_groupD.py):
expected combined scenario (a) 16.49% of deduction dollars, retailer
dispute rate 40.0% (legacy 40%), distributor 37.2%. Two permanent dbt
tests written (outcome→evidence-assessment linkage with weakest-link
bounds; per-tier recovery ±2pts of curve). Key data findings: flat-rate
disputing cannot reach the 16.5% endpoint (caps ~15.0% even at a 50%
rate) — evidence-correlated selection is structurally required;
product_master_history is EMPTY in the certified state and its 0–4
score scale doesn't match the §2.5 thresholds, so the DQ factor uses
the 40–95 defect-profile score of the order's largest-line_total SKU.

**State:** NOT verified, but run1 reseed COMPLETED clean just before
wrap (282.5s; replica is on the unverified run1 state). Realized
counts landed on calibration: retailer_disputes 7,756 (tiers
3,316/3,515/925 S/M/W), retailer_dispute_evidence 34,743,
distributor_disputes 926 (478/343/105); deductions unchanged
(20,002 / 2,423). Nothing pushed (mid-group rule). Guard expectation
unchanged: 7/10 with the same 3 count REDs (no dispute checks in the
guard).

**Next:** Fresh session: (1) re-run `scripts\seed_all.py` from scratch
(POSTGRES_PASSWORD=postgres, local Docker replica), (2) write
verify_groupD.py + run all gates, (3) reseed ×2 determinism +
checksums vs groupC2-run1 (expect exactly 3 changed tables:
retailer_disputes, retailer_dispute_evidence, distributor_disputes),
(4) dbt build, guard, (5) GROUP-D-VERIFICATION.md (§1 judgment calls
listed in the causal repo's HANDOFF.md; post-fix mix derivation must
be explicit) + DRIFT-LEDGER.md Group D section, (6) stop at gate.
Full cold-start detail in the causal repo's HANDOFF.md.

---

## 2026-06-12 19:00 (wrap)

**Started from:** Group C accepted; C2 (distributor parallel) queued
with cold-start notes in the causal repo.

**Did:** Group C2 shipped (1bb5d0a) and verified — every gate on the
first calibration: short+late 0.318% of distributor shipped $ (band
0.2–0.45), total 0.975% (0.7–1.1), linkage 100% (permanent dbt test),
kept rows identical to the cent, 38/41 tables byte-identical to the
Group C state, determinism 41/41, dbt 431/431, guard 7/10 with exactly
the 3 expected count REDs (distributor 160→678 new). The open
late-trigger question resolved as the 12-day order-to-door window —
Shawn ACCEPTED C2 and APPROVED the window rule as implemented.
Decisions recorded in the causal repo (acceptance/window rule;
standing push-at-every-acceptance rule). Both repos pushed.

**State:** Replica certified on Group C2
(cinderhaven-causal-fulfillment/verification/groupC2-run1-checksums.txt).
Both wholesale channels causal on operational money. Prod untouched,
guard-vs-prod green. Both repos synced with origin.

**Next:** Group D in a fresh session — GO is given. Evidence quality +
dispute outcomes, both channels in one treatment; verification per the
approved decomposition plus the scenario amendment (per-tier ±2pts;
both endpoints as scenarios: current mix ≈16.5%, post-fix mix ≈65%,
each ±2pts). Cold-start notes in the causal repo's HANDOFF.md.

---

## 2026-06-12 — Phase 3 Group C2 complete (causal distributor chargebacks + deductions)

**What changed:** Distributor parallel of Group C. Distributor
short_ship/late_delivery chargebacks and deductions are now triggered
by real distributor_shipment_lines events (streams
FULFILLMENT_SEED+11/+12); late = delivery beyond the 12-day
order-to-door window (distributor orders have no requested_ship_date —
rule choice flagged in the causal repo's GROUP-C2-VERIFICATION.md). No
receiving_discrepancy category distributor-side (no receipt lines per
design §1.6). Quality-linked chargebacks (damaged/pricing_error) and
the three non-operational deduction types ride the legacy stream
unchanged; legacy generators still run verbatim for stream
preservation. Permanent dbt linkage test added; stale distributor
staging descriptions refreshed.

**Verification:** component 0.318% of distributor shipped $ (proposed
band 0.2–0.45), total 0.975% (0.7–1.1) — first calibration; linkage
100% (400+183 cb, 892+290 event deductions); kept rows identical to
the cent; 38/41 tables byte-identical to the Group C state (exactly
the 3 intended distributor money tables); determinism 41/41; dbt
431/431; guard-vs-replica 7/10 with exactly the 3 expected count REDs
(distributor 160→678 new); all dollar checks green; prod untouched.

**State:** Replica certified on Group C2. Drift ledger updated in the
causal repo. Both wholesale channels now causal on operational money.

**Next:** Shawn's review of C2 (the 12-day window rule is the
judgment call), then Group D — causal evidence quality + dispute
outcomes across both channels.

---

## 2026-06-12 23:50 (wrap)

**Started from:** Groups A–B accepted; GO on Group C (causal
chargebacks + deductions, first canon-divergence commit).

**Did:** Group C shipped (fbdaf3b) and verified — every gate on the
first calibration: compliance 1.444% of shipped $, short+late 0.701%,
100% linkage (5,604/5,604, permanent dbt test), Path A and kept
deduction types byte-identical, 36/41 tables identical to the Group B
rollback state, determinism 41/41, dbt 430/430, guard 8/10 with
exactly the 2 expected count REDs. Drift ledger opened in the causal
repo. Shawn accepted Group C and directed **Group C2** — distributor
operational money tables go causal BEFORE Group D (decision in causal
repo DECISIONS.md).

**State:** Replica certified on Group C
(cinderhaven-causal-fulfillment/verification/groupC-run1-checksums.txt
is the C2 baseline). Prod untouched, guard-vs-prod green. Distributor
money seeders still legacy — C2 territory.

**Next:** Group C2 in a fresh session — cold-start notes in the causal
repo's HANDOFF.md (scope, seed streams +11/+12, no requested_ship_date
on distributor orders so the late-trigger rule needs a decision,
distributor band proposal from §1.6).

---

## 2026-06-12 — Phase 3 Group C complete (causal chargebacks + deductions)

**What changed:** First canon-divergence commit. Retailer
short_ship/late_delivery chargebacks and deductions are now triggered
by real Group B fulfillment events; NEW receiving_discrepancy
chargeback category from damage/quality receipt lines (decision #2 —
separate, never folded); Path A data-defect chargebacks unchanged to
the cent (281/$279,330). Legacy generators still run verbatim for
stream preservation; replaced rows are filtered at write time and the
event-driven rows ride FULFILLMENT_SEED+3/+4. Permanent dbt linkage
test added.

**Verification:** compliance 1.444% of shipped $ (band 1.0–1.5),
short+late 0.701% (band 0.5–0.8), all-reason $231K/yr (~$230K design
target) — in band on the first calibration; linkage 100% (5,604/5,604
operational chargebacks join to triggering events); kept deduction
types byte-identical (10,809/$1,032,702), deduction $ −2.2%; 36/41
tables byte-identical to the Group B rollback state (5 intended
changes); determinism 41/41; dbt 430/430; guard-vs-replica 8/10 with
exactly the 2 expected count REDs (677→5,885; 837→6,045), all dollar
checks green; prod untouched.

**State:** Replica on Group C state, fully verified. Drift ledger open
at cinderhaven-causal-fulfillment/verification/DRIFT-LEDGER.md (resolves
at the Phase 4 relock). Event-driven deductions undisputed until Group
D (declared intermediate state). Disputes/evidence/claims drift is
subtractive-only.

**Next:** Shawn's go on Group D — causal evidence quality + dispute
outcomes (§2.5 weakest-link tiers on EVIDENCE_SEED, §2.4 outcome curve,
endpoints as scenarios per decision #4).

---

## 2026-06-12 17:30 (wrap)

**Started from:** Phase 1 design doc at the hard gate awaiting Shawn's review.

**Did:** Gate cleared (6 decisions). Phase 2 complete: mart COGS fix (a6b4d20), rate_map fix + interim trade relock $3.4M/10.5%→$3.7M/11.3% (6e05e33), 4 dbt plausibility assertions (8c41c84), PDHA 12/18→12/36 (e7ce057), COGS ratios in WTMCF (4428f95) + CPA (81e1c34). Phase 3 decomposed into six gated groups; Group A schema+constants (fe62b4d) and Group B causal fulfillment events (0eb21ad) shipped with byte-identical stream-preservation proofs.

**State:** Replica certified on Group B — guard 10/10, dbt 427/427, determinism 41/41, portfolio fill 91.98%, money tables byte-identical to pre-causal state. Rollback point in cinderhaven-causal-fulfillment/verification/. Money seeders (remittances/deductions/disputes/chargebacks) still legacy.

**Next:** Shawn's go on Group C — causal operational chargebacks + deductions. First canon-divergence commit; drift ledger starts. Arc tracking lives in cinderhaven-causal-fulfillment (PLAN.md + HANDOFF.md there are current).

---

## 2026-06-12 17:27

**What changed:** Phase 3 Groups A and B complete — fulfillment schema + frozen causal-model constants (fe62b4d), then causal shipment events: per-line shortfalls on §2.1 fill targets, per-retailer timing, receipt lines, distributor parallel (0eb21ad). Stopped at the Group C gate.

**Why:** Causal-fulfillment arc Phase 3: orders ≠ shipments must originate in the platform data itself, with money tables untouched until Group C makes them causal.

**State:** Replica certified on Group B state — guard 10/10, dbt 427/427, determinism 41/41, portfolio fill 91.98% with every retailer within ±0.64pt of target. 35/41 tables byte-identical to pre-causal state including every money table (chargebacks exactly 677+160). Rollback point: cinderhaven-causal-fulfillment/verification/groupB-certified-state-checksums.txt. Seeders for remittances/deductions/disputes/chargebacks still legacy — Group C territory.

**Next:** Shawn's go on Group C — causal operational chargebacks + deductions. First canon-divergence commit; drift ledger starts there.

---

## 2026-06-12 15:48

**What changed:** Phase 2 bugfixes complete — mart case-pack COGS fix, check_canonical rate_map fix with interim trade relock, and 4 dbt plausibility assertions here; PDHA annualization and COGS-ratio fixes landed in three sibling repos.

**Why:** Phase 2 of the causal-fulfillment arc (design approved by Shawn this morning). Small SQL/Python fixes with large credibility exposure, fixed before any new generation.

**State:** Guard 10/10 PASS, dbt build 396/396, all repos pushed. Trade canon relocked $3.4M/10.5% → $3.7M/11.3% (old values in SUPERSEDES) — pending Shawn's review. Docker replica running. Seeders untouched.

**Next:** Shawn reviews Phase 2 (especially the trade relock). Then Phase 3: causal fulfillment model in the seeders per CAUSAL_FULFILLMENT_DESIGN.md.

---

## 2026-06-12 12:28

**What changed:** Wrote cinderhaven-plausibility-audit.md — read-only plausibility audit of every canonical figure, recomputed on a freeze-guard-certified local replica.

**Why:** check_canonical.py proves figures haven't drifted; this audit asked whether they describe a coherent company. Five REGENERATE-grade findings needed recording before any fix work.

**State:** Audit complete: 6 PLAUSIBLE / 7 RELABEL / 5 REGENERATE. Headliners: $458K/yr product-data cost is a 2× window error (36-mo total annualized as 18; true attributable ~$51–93K/yr); three irreconcilable fill-rate universes (platform 100% / OTIF 95–86% / short-ship 69%); mart_channel_contribution case-pack COGS bug (−522% margins); check_canonical rate_map prices Kroger+Sprouts at the 7% fallback (~$285K/yr understated); $91K channel delta rests on inverted COGS assumptions. Fly.io SSOT untouched; local Docker replica stopped but volume kept. Replica certification: seed 1,940,140 rows → dbt 392/392 PASS → guard 10/10 PASS.

**Next:** Pick fix order from the report's priority list — recommended start: PDHA $458K recomputation (arithmetic error in the most-cited figure), then the two platform bugs (mart COGS, guard rate_map).

---

## 2026-06-03 18:25

**Started from:** No active arc. Mart layer existed but consumers read raw.* instead.

**Did:** Added 5 consumer mart models (fct_chargebacks, dim_stores, fct_scan_data, fct_promotions, dim_retailer_requirements), expanded dim_products with 19 columns. Refactored Product Data Health Audit as first consumer — verified output parity. Audited 4 other consumers: CPA and C2C clean, RDR and RVDT need refactors.

**State:** All new models materialized (0 errors). Audit refactor complete and verified. Not pushed.

**Next:** RDR refactor — repoint from int_all_*/stg_retailer_* to fct_*/dim_* marts. May need new mart models for deduction_codes, dispute_evidence, pack_records, EDI requirements, post_audit_claims. Then RVDT refactor.

---

## Session — 2026-05-18 (session 8)

**Started from:** Previous schema had 23 generic tables with no channel isolation. Consumer projects couldn't reconcile across channels because everything was merged at staging.

**Did:** Greenfield rebuild of entire Postgres schema and dbt project.
- Rewrote raw DDL: 23 tables → 37 tables across 3 isolated pipelines (retailer, distributor, DTC) + shared
- Built 7 Python seed generators producing ~1M deterministic rows with realistic patterns (seasonal orders, delist-risk velocity, correlated deductions/disputes)
- Rebuilt all dbt layers: 37 staging views (142 tests), 5 intermediate views (27 tests), 22 mart tables (75 tests)
- Per-channel reconciliation marts (retailer, distributor, DTC) + mart_channel_contribution cross-channel rollup
- Full `dbt build`: 308/308 PASS
- Regenerated dbt docs for GitHub Pages
- Force-pushed to remote (superseded 4 stale data-integrity-arc commits)

**State:** Channel-isolated schema live in Postgres. All 64 models and 244 tests green. dbt docs updated. GitHub Pages will rebuild automatically. Branch protection re-enabled.

**Next:** Update consumer projects (7 repos) to use new channel-prefixed table names. Old names like stg_orders, stg_deductions, fct_orders are gone — replaced by stg_retailer_orders, stg_retailer_deductions, fct_retailer_orders, etc. Start in a new session.

---

## Session — 2026-05-16 (session 7)

**Started from:** Both arcs complete, no active work. Repo public but missing CI, setup docs, and presentation polish.

**Did:** Full four-phase audit (baseline, internal review, landscape scan, synthesis). Executed 7 improvement moves: GitHub Actions CI, .env.example, requirements.txt, portable dbt path, 2 custom generic test macros + 3 singular tests, README badges. Wrote AUDIT.md and logged decisions.

**State:** All audit moves complete. CI green. dbt docs live at msshawnp.github.io/cinderhaven-data-platform/. Custom tests parse clean (not yet run against live DB). No active arc.

**Next:** No active arc. Options: (1) run custom tests against Fly.io Postgres to confirm pass, (2) start data-hygiene portfolio piece using cinderhaven-data-dirty, (3) address dbt deprecation warnings about test argument syntax.

---

## Session — 2026-05-15 (session 6)

**Phase:** Dirty dataset arc — complete.
**Goal:** Execute dirty dataset generator plan — build cinderhaven-data-dirty repo with 6 root-cause degraders.
**Completed:**
- U1+U2: Pipeline framework + RC1 Excel/CSV damage with P0 cascade fix (sku_whitespace)
- U3: RC2 governance decay (near-duplicate SKUs, temporal drift, casing)
- U4: RC3 retailer integration gaps + RC4 ETL pipeline failures
- U5: RC5 manual process errors + RC6 business process gaps
- U6: README, defect manifest generator, 18 tests (all passing)
- GitHub repo created and pushed: MsShawnP/cinderhaven-data-dirty (private)
- Feature branch merged to main, default branch set
- Plan status flipped to completed
- 2 decisions logged, 2 failures logged
**Tried, didn't work:**
- Plan's cascade model assumed UPC/GTIN damage breaks joins — actually all downstream tables join on `sku`. Fixed with sku_whitespace defect.
- UPDATE week_ending hit UNIQUE constraint — fixed with UPDATE OR IGNORE.
- PowerShell inline Python with SQL `||` operator caused parser errors — used temp .py files.
**State:** Dirty dataset arc fully shipped. Both arcs (platform + dirty dataset) complete.
**Next concrete action:** No active arc. User chooses next work (data-hygiene portfolio piece, or other).
**Blockers:** None.

---

## Session — 2026-05-13 (session 5)

**Phase:** All 6 phases complete. Arc nearly done.
**Goal:** Fix Dagster UI, complete Phase 5, execute full Phase 6.
**Completed:**
- P5.3 DONE: Dagster schedule + asset graph verified in UI
  - Root cause of empty graph: Dagster launched from repo root but
    cinderhaven_orchestration package lives under orchestration/. Fixed
    by adding `--working-directory orchestration` to dagster dev args.
  - Daily schedule (6 AM UTC) visible on Automation page
  - 34 assets with full lineage rendered in Global Asset Lineage view
  - .claude/launch.json updated with the fix
- P6.1 DONE: Architecture diagram (Mermaid in docs/architecture.md + README)
- P6.2 DONE: dbt docs generated with 100% description coverage
  - 34/34 models described, 96/96 columns described
  - Site files (index.html + manifest.json + catalog.json) in docs/dbt-docs/
  - Needs: enable GitHub Pages in repo settings (Source: main, /docs folder)
- P6.3 DONE: Walkthrough article (docs/walkthrough.md)
  - Covers source contracts, staging conventions, crosswalk design,
    test philosophy, orchestration approach
- P6.4 DONE: Professional README with architecture diagram, repo structure,
  stack table, documentation links. Removed dbt scaffold boilerplate.
- Final validation: `dbt build` 166/166 PASS (34 models + 132 tests)
- 2 new decisions logged (Dagster working directory, manifest parse pattern)
**Tried, didn't work:** Nothing notable — one clean session.
**State:** All 19 plan tasks complete. `dbt build` green. Dagster running.
**Remaining for arc completion (user actions):**
1. Enable GitHub Pages: repo Settings → Pages → Source: main, /docs folder
2. Final review and flip repo to public
**Environment notes:**
- flyctl proxy is running (PID 12660) — will die on reboot
- Dagster dev was running on port 3000 — may need restart
- dbt.exe full path: C:\Users\mssha\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts\dbt.exe
- Must cd into cinderhaven/ and set POSTGRES_PASSWORD for dbt commands
**Next concrete action:** Enable GitHub Pages, review repo, flip public.
**Blockers:** None.

---

## Session — 2026-05-12 (continued, session 4)

**Phase:** Phases 3 and 4 complete. Ready for Phase 5 (Dagster).
**Goal:** Build full dbt pipeline — staging through marts.
**Completed:**
- P3.1 DONE: dbt project initialized (dbt-core 1.11.9, dbt-postgres 1.10.0)
  - profiles.yml at ~/.dbt/profiles.yml, uses env_var for password
  - dbt_project.yml: staging (views), intermediate (views), marts (tables)
  - dbt.exe at C:\Users\mssha\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts\dbt.exe
  - Must cd into cinderhaven/ dir before running dbt commands
  - Must set POSTGRES_PASSWORD env var and have flyctl proxy running
- P3.2 DONE: 23 sources defined (models/staging/sources.yml)
- P3.3 DONE: 23 staging models (views) — date casts, boolean conversions
- P3.4 DONE: 93 staging tests passing
- P4.1 DONE: 3 intermediate models
  - int_deduction_code_crosswalk (codes → rules → retailers)
  - int_product_retailers (SKU × retailer with pricing, margins, distribution)
  - int_retailer_payments (deductions → remittances → retailers → disputes)
- P4.2 DONE: 3 dimension tables (dim_products, dim_retailers, dim_deduction_reasons)
- P4.3 DONE: 5 fact tables (fct_orders, fct_shipments, fct_deductions, fct_chargebacks, fct_payments)
  - fct_orders unifies B2B + DTC (49,474 rows)
- P4.4 DONE: 132 total tests passing (93 staging + 6 intermediate + 33 mart)
  - Referential integrity: fct_orders.sku → dim_products, fct_*.retailer_id → dim_retailers
- Phases 1-4 fully complete
**Tried, didn't work:** Initial dispute outcome accepted_values wrong — fixed
  by checking actual data values in SQLite.
**State:** Full dbt pipeline running. 34 models, 132 tests, zero errors.
**Next concrete action:** P5.1 — Initialize Dagster project, integrate with dbt.
**Blockers:** None.

---

## Session — 2026-05-12 (continued, session 3)

**Phase:** Phase 2 — build it right (infrastructure + data generation)
**Goal:** Complete Phases 1 and 2 — ingestion, data generation, full load.
**Completed:**
- P1.3 DONE: Ingestion script built (scripts/ingest_sqlite_to_postgres.py)
  - Uses Postgres COPY for bulk loading, chunked with reconnection
  - Supports --resume to skip already-loaded tables
  - Required scaling Fly.io to 1GB for scan_data (1.1M rows), scaled back after
- P2.2 DONE: Shopify DTC orders generated (scripts/generate_shopify_orders.py)
  - 10,000 orders, 19,347 line items, $426k total DTC revenue
  - 3,610 unique customers, 2.8 avg orders/customer
  - 18-month window with seasonal patterns, discounts, fulfillment statuses
  - Two normalized tables: shopify_orders + shopify_order_lines
- P2.3 DONE: New Shopify tables loaded into Postgres raw schema
  - raw_schema.sql updated with DTC/e-commerce section
  - All 23 tables verified — 1,217,942 total rows
- Phases 1 and 2 fully complete
**Tried, didn't work:** 256MB Fly instance crashes under scan_data COPY load.
  Tried smaller batches (5k, 500 rows) — still crashed. Fixed by scaling to 1GB
  temporarily. See FAILURES.md.
**State:** All data in Postgres. Ready for Phase 3 (dbt).
**Next concrete action:** P3.1 — Initialize dbt project and configure connection.
**Blockers:** None.

---

## Session — 2026-05-12 (continued)

**Phase:** Phase 2 — build it right (infrastructure)
**Goal:** Begin infrastructure buildout — Postgres, raw schema, data audit.
**Completed:**
- P1.1 DONE: Postgres 17.7 provisioned on Fly.io (cinderhaven-db, iad region, shared-cpu-1x)
  - Database `cinderhaven` created, schema `raw` created
  - Verified: CREATE TABLE, INSERT, SELECT all working
  - Credentials saved to .env (gitignored)
- P1.2 DONE: Raw schema DDL written (sql/raw_schema.sql)
  - All 21 data tables mapped SQLite → Postgres with type annotations
  - Organized by domain: reference, pricing, distribution, transactions, sales, deductions
- P2.1 DONE: Data gap assessment written (docs/data-gap-assessment.md)
  - 21 of 21 tables ready to ingest as-is
  - 1 real gap: Shopify DTC orders (needs generation)
  - 1 partial gap: Payment records (remittances covers v1, defer)
  - 1 deferred by design: EDI (from EDI Pre-flight)
- Existing cinderhaven-data DB path confirmed: C:\Users\mssha\projects\active\cinderhaven-data\data\cinderhaven_product_master.db
- psycopg2-binary installed for Python ingestion
- Enabled remoteControlAtStartup in global settings
**Tried, didn't work:** Nothing notable.
**State:** Infrastructure up, schema designed, gaps assessed. Ready for P1.3.
**Next concrete action:** P1.3 — Build ingestion script (SQLite → Postgres raw schema).
**Blockers:** None.

---

## Session — 2026-05-12

**Phase:** Phase 1 — build the right thing (clarify complete, gates skipped)
**Goal:** Scaffold project and scope the build through /clarify.
**Completed:**
- Scaffolded project via /new-project (directory, state files, git, GitHub remote)
- Private repo at github.com/MsShawnP/cinderhaven-data-platform, tagged v0.1-foundation
- /clarify interview complete — locked in scope, quality bar, role split, deployment targets, data lifecycle
- PLAN.md written with full scope and definition of done
- Decomposed into 6 phases / 19 sub-tasks with dependencies and verification
- Skipped Heavy tier gstack gates — brief + /clarify provided sufficient rigor
- 3 decisions logged to DECISIONS.md
**Tried, didn't work:** Nothing notable — planning session, no code.
**State:** Project scaffolded, plan decomposed, ready to build.
**Next concrete action:** Start P1.1 — Provision Postgres on Fly.io.
**Blockers:** None. User needs Fly.io account access for P1.1.

---

## 2026-05-12 — Project initialized

**Started from:** New project setup via /new-project.

**Did:** Created repo, set up CLAUDE.md/DECISIONS.md/HANDOFF.md/PLAN.md/
FAILURES.md. Brainstorm brief completed — covers pain, portfolio gap,
technical spec, build estimate, and Cinderhaven integration plan.

**State:** Foundation in place. Stack not yet locked in. Ready for
/clarify to scope the first arc.

**Next:** Run /clarify to reach 95% confidence on scope, then
/office-hours and /plan-ceo-review (Heavy tier gates).

---
