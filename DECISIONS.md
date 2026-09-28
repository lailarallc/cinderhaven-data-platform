# Cinderhaven Data Platform — Decisions Log

Permanent record of choices that should survive session turnover.
If a decision is reversed, strike it through and add the replacement
below — don't delete.

---

## Format

Each entry:
- **Date** — when decided
- **Decision** — one sentence, imperative voice
- **Why** — the reasoning, including what was tried and rejected
- **Scope** — what this applies to (file, chunk, deliverable, or "global")
- **Do not** — explicit anti-instructions, if any

---

## Infrastructure & Ops

### 2026-07-02 — Stop guessing at cinderhaven-db's flypgadmin credential; rebuild or escalate instead
- **Why:** Two independent, researched theories for how the `pg`
  health-check role (`flypgadmin`) gets its password set on boot
  (`OPERATOR_PASSWORD` reconcile, then `SU_PASSWORD` reconcile) both
  failed on the real machine. The mechanism postgres-flex actually uses
  here isn't understood, and further SQL/secrets experiments on a
  production DB with live app traffic aren't worth the risk for a
  monitoring-only check. See FAILURES.md 2026-07-02 entry.
- **Scope:** cinderhaven-db (Fly.io Postgres) `pg` health check
  specifically. Does not apply to the app-facing `postgres` role, which
  is confirmed fine.
- **Do not:** Attempt a third credential-alignment theory via
  `ALTER ROLE` or `flyctl secrets set` on this machine. Next step is
  either rebuilding cinderhaven-db fresh from the platform seed pipeline
  (consistent credentials from birth) or a Fly support ticket.

---

## Architecture & Pipeline

### ~~2026-05-12 — Keep stack unlocked until /clarify completes~~
- ~~**Why:** Brief proposes Postgres + dbt + Dagster but user wants to
  confirm tooling through research, not assumption.~~
- ~~**Scope:** Global~~
- ~~**Do not:** Commit to specific tools in scaffolding or early code.~~
- **Superseded by:** Stack confirmed during /clarify (2026-05-12).

### 2026-05-12 — Portfolio impressiveness wins over pragmatism when they conflict
- **Why:** The platform's primary job is to impress technical reviewers.
  When a tool (e.g., Dagster) adds work but adds portfolio signal, include
  it. When a shortcut saves time but looks like a shortcut, don't take it.
- **Scope:** Global — applies to every build vs. skip decision.
- **Do not:** Cut a visible component to save time unless it genuinely
  doesn't add reviewer signal.

### 2026-05-12 — Hosted artifacts are the showpiece, not clone-and-run
- **Why:** Technical reviewers browse repos, read docs, and scan diagrams.
  Almost none clone and run a data platform locally. dbt docs on GitHub
  Pages and Dagster screenshots prove the platform is real without requiring
  Docker or cross-platform setup.
- **Scope:** Global — deployment and documentation strategy.
- **Do not:** Spend time on Dockerfiles or cross-platform testing for v1.

---

## Data & Schema

### 2026-06-12 — Preserve main-rng draw sequences with dummy draws; new randomness on isolated sub-streams
- **Why:** The seeders consume one sequential rng per pipeline, so any
  added/removed draw shifts every downstream table. Group B proved the
  pattern: keep every legacy draw in place (dummy-draw where the value is
  superseded — the idiom generate_chargebacks already used) and put all new
  randomness on dedicated Random(FULFILLMENT_SEED+k) instances (400 fill /
  401 receipts / 402 timing / 410 distributor fill). Result: 35/41 tables
  byte-identical through a major shipment rewrite, every money table intact.
- **Scope:** All seeder changes, Groups C–E especially. Allocate a fresh
  sub-stream per concern; never let two concerns share one.
- **Do not:** Remove a "dummy" draw because it looks unused — it is load-
  bearing for stream position. Do not draw from the main rng in new code.

### 2026-06-12 — Calibrate generation constants from measured generated data, not theory
- **Why:** The theoretical constrained-order loss (0.46) and an
  uncompensated Q4 dip undershot every fill target ~1pt annually. Measuring
  realized loss (0.467/0.474) and Q4 unit share (23%) from an actual run,
  then folding the measurements in, landed all nine partners within ±0.64pt
  in one iteration. Same pattern for the data_defect eligibility share (46%).
- **Scope:** Any seeder constant that backs a target band (Groups C–E:
  chargeback rates, evidence mixes, residual sizing).
- **Do not:** Tune by guess-and-rerun. Measure the mechanism, derive the
  constant, document the measurement in the verification record.

### 2026-06-12 — §2.1 fill targets are annual figures
- **Why:** Q4 carries ~23% of annual units, so a base rate equal to target
  with a Q4 dip below it lands the annual blend under target. The base rate
  carries +0.23 × Q4_FILL_DIP so the annual figure is the target and the
  Q4 dip stays visible per retailer (the design's seasonal story).
- **Scope:** Fill verification in Groups B–F and the Phase 4 canonical
  derivations — "fill rate" with no qualifier means the annual unit rate.
- **Do not:** Re-baseline targets as non-Q4 steady-state rates without a
  design-doc amendment and Shawn's approval.

### ~~2026-05-12 — Scale Fly.io machine temporarily for bulk ingestion, then scale back~~
- ~~**Why:** The shared-cpu-1x (256MB) Fly.io Postgres machine crashes under
  bulk COPY loads — specifically scan_data (1.1M rows). Scaling to 1GB for
  the load and back to 256MB after is cheaper and faster than engineering
  around the memory limit with micro-batches or alternative upload paths.~~
- ~~**Scope:** Ingestion — applies any time a full reload is needed.~~
- ~~**Do not:** Leave the machine at 1GB permanently. Scale up, load, scale
  down. The steady-state workload (dbt transforms, queries) fits in 256MB.~~
- **Superseded by:** 2026-06-14 volume extension (below).

### 2026-06-14 — Fly.io volume permanently extended to 3GB
- **Why:** The causal fulfillment model (2.4M rows, 41 tables) plus dbt
  mart materializations requires ~1GB of Postgres storage. The original 1GB
  volume hit 99% utilization after seeding, leaving no room for WAL files or
  CREATE TABLE AS operations — Postgres crashed and couldn't restart. 3GB
  gives comfortable headroom (currently 33% utilized).
- **Scope:** Fly.io cinderhaven-db app, vol_vjyeldw37mqxegpv.
- **Do not:** Shrink back to 1GB. The dataset is permanently larger now.
  Machine memory (2GB) is adequate — the bottleneck was disk, not RAM.

### 2026-05-12 — Use Postgres COPY with chunked reconnection for ingestion
- **Why:** Row-by-row INSERT (via execute_batch) was too slow and connection-
  heavy over the Fly.io proxy tunnel. COPY is 10-50x faster for bulk loading.
  Reconnecting between 25k-row chunks prevents any single transaction from
  overwhelming the server. Script supports --resume to skip already-loaded
  tables after partial failures.
- **Scope:** scripts/ingest_sqlite_to_postgres.py
- **Do not:** Switch back to execute_batch. If chunk size needs tuning,
  adjust CHUNK_ROWS, don't change the COPY approach.

### 2026-05-12 — dbt layer structure: staging (views) → intermediate (views) → marts (tables)
- **Why:** Views for staging and intermediate keep storage minimal on the
  256MB Fly.io instance — only mart tables materialize. This is standard
  dbt practice: views rebuild instantly, tables persist for query performance.
  Custom schemas (public_staging, public_intermediate, public_marts) keep
  the namespace clean for docs and lineage.
- **Scope:** cinderhaven/dbt_project.yml materialization config.
- **Do not:** Materialize staging as tables unless query performance requires
  it (unlikely at this data volume).

### 2026-05-12 — fct_orders unifies B2B and DTC into a single fact table
- **Why:** Downstream consumers (Contract-to-Cash, revenue analysis) need
  a single order grain regardless of channel. The B2B path (orders +
  order_lines) and DTC path (shopify_orders + shopify_order_lines) share
  the same shape: line_id, order_id, sku, quantity, unit_price, line_total.
  A channel column distinguishes them. This avoids duplicating every
  downstream query.
- **Scope:** cinderhaven/models/marts/fct_orders.sql
- **Do not:** Split into fct_b2b_orders and fct_dtc_orders unless a
  consumer genuinely needs different grains.

### 2026-05-12 — Shopify DTC as two normalized tables, not a flat Shopify CSV export
- **Why:** Shopify exports are a single flat CSV with denormalized line items.
  We split into shopify_orders (10k headers) and shopify_order_lines (19k lines)
  to match the existing orders/order_lines pattern. This makes the dbt staging
  layer consistent — same header/line shape for both B2B and DTC channels.
- **Scope:** Data generation + raw schema (shopify_orders, shopify_order_lines).
- **Do not:** Flatten into a single wide table. The normalized shape is
  intentional for downstream joins and the order-to-cash mart.

### 2026-05-12 — cinderhaven-data repo is bootstrap source; platform becomes permanent home
- **Why:** The platform should be the single source of truth. cinderhaven-data
  (SQLite + generation scripts) bootstraps the initial load. Once the platform
  is live, cinderhaven-data goes dormant. Existing consumer projects stay on
  SQLite submodules for now — migration is future work, not v1.
- **Scope:** Data lifecycle — ingestion strategy, consumer migration plan.
- **Do not:** Build ongoing sync between SQLite and Postgres. One-time
  ingestion (or scripted re-ingestion), not continuous replication.

### 2026-06-03 — Consumer projects read marts only; staging/intermediate are internal to dbt
- **Why:** Staging and intermediate models are implementation details of the dbt project — they can be renamed, restructured, or removed without notice. The mart layer (dim_*/fct_*) is the contracted API surface. Reading below it couples consumers to dbt internals. Confirmed during the Product Data Health Audit refactor: switching from raw.* to marts.* produced identical analytical output with fewer transforms in the consumer.
- **Scope:** All projects that read from the Cinderhaven Data Platform. Applies to new consumers and refactors of existing ones.
- **Do not:** Read from raw.*, public_staging.stg_*, or public_intermediate.int_* in consumer code. If a consumer needs data that only exists at staging/intermediate, the fix is to promote it to a mart model in the platform — not to reach into the internals.

---

## Orchestration

### 2026-05-13 — Dagster requires --working-directory pointing to orchestration/
- **Why:** `dagster dev -m cinderhaven_orchestration.definitions` resolves modules
  from the CWD. When launched from the repo root, Python can't find the
  `cinderhaven_orchestration` package because it lives under `orchestration/`.
  Adding `--working-directory orchestration` fixes the import. Without this,
  the Dagster webserver starts but the code location fails to load (empty
  asset graph, repeated "Error loading repository location" warnings).
- **Scope:** .claude/launch.json, any Dagster launch command.
- **Do not:** Move the orchestration package to the repo root or install it
  as a pip package just to avoid the flag. The explicit working directory
  keeps the project structure clean.

### 2026-05-13 — dbt manifest parsed at Dagster load time via DbtCliResource.cli(["parse"])
- **Why:** dagster-dbt needs the dbt manifest.json to build the asset graph.
  Parsing at module load time (in assets.py) ensures the manifest is always
  fresh — no stale artifact to maintain. The parse runs once when Dagster
  starts, not on every materialization. This is the dagster-dbt recommended
  pattern.
- **Scope:** orchestration/cinderhaven_orchestration/assets.py
- **Do not:** Check in a static manifest.json or use a pre-built manifest
  path. The parse-at-load pattern keeps the graph in sync with the dbt project.

---

## Dirty Dataset

### 2026-05-15 — SKU whitespace damage is the real cascade path, not UPC/GTIN

- **Why:** The plan's central narrative assumed corrupting UPC/GTIN would cascade
  into join failures downstream. In reality, all downstream tables (scan_data,
  order_lines, orders, deductions) join on `sku`, not `upc`/`gtin14`. UPC/GTIN
  damage only affects the product_master table itself. The fix: RC1 adds a
  `sku_whitespace` defect that introduces trailing/leading spaces on `sku` in
  scan_data and order_lines, creating real orphan records (22K+ at moderate).
- **Scope:** cinderhaven-data-dirty — RC1 cascade design.
- **Do not:** Assume UPC/GTIN corruption alone proves join damage in demos.
  Always demonstrate via SKU-based orphan queries.

### 2026-05-15 — Dirty dataset lives in a separate repo, fully isolated

- **Why:** The dirty generators have no shared code with the clean data repo or
  the platform repo. Separate repo keeps concerns clean: clean data stays
  pristine, platform stays focused on infrastructure, dirty data is a standalone
  tool. No submodules, no cross-imports. The only connection is the clean SQLite
  file path passed as `--input`.
- **Scope:** Repository structure — cinderhaven-data-dirty.
- **Do not:** Add degrader code to cinderhaven-data or cinderhaven-data-platform.

---

## CI & DevEx

### 2026-05-16 — CI validates project structure (dbt parse), not full build

- **Why:** A full `dbt build` in CI would require a live Postgres
  instance with loaded data — complex to provision in GitHub Actions
  and brittle. `dbt parse` validates all model references, Jinja
  compilation, and schema correctness without a database connection.
  This catches real errors (broken refs, invalid YAML, syntax issues)
  while staying fast and free.
- **Scope:** .github/workflows/ci.yml
- **Do not:** Add a Postgres service container unless a specific model
  bug requires integration testing in CI. The production `dbt build`
  runs against Fly.io Postgres locally.

### 2026-05-16 — Use shutil.which for dbt executable, not hardcoded path

- **Why:** The original `project.py` hardcoded a Windows App Store
  Python path. Any reviewer reading that file sees "built on one
  machine" instead of "production infrastructure." `shutil.which("dbt")`
  resolves the correct binary on any platform where dbt is installed.
- **Scope:** orchestration/cinderhaven_orchestration/project.py
- **Do not:** Add platform-detection logic or multiple fallback paths.
  If dbt isn't on PATH, the error from Dagster is clear enough.

### ~~2026-05-17 — mart_channel_contribution COGS must be channel-aware~~

- ~~**Why:** fct_orders unifies B2B and DTC into one table, but the
  quantity column has different semantics per channel. B2B quantity is
  cases (needs case_pack_qty × cogs_per_unit). DTC quantity is
  individual units from Shopify (needs cogs_per_unit only). A uniform
  formula either under-counts B2B COGS (3.4%) or inflates DTC (457%).
  The fix: `CASE WHEN channel = 'DTC' THEN quantity * cogs_per_unit
  ELSE quantity * case_pack_qty * cogs_per_unit END`.~~
- ~~**Scope:** cinderhaven/models/marts/mart_channel_contribution.sql —
  and any future mart that computes COGS from fct_orders × dim_products.~~
- ~~**Do not:** Apply case_pack_qty uniformly across channels. Any new
  COGS calculation must check channel first.~~
- **Superseded by:** 2026-09-28 — Order-line quantities are units in
  every channel (Reversed / Superseded, below). Retired 2026-09-28: the
  premise "B2B quantity is cases" is false for the current seeder.

### 2026-06-13 — Recovery metrics use two denominators; never pair 16% with 65%
- **Why:** 16% is recovery per all deduction dollars (exposure diagnostic).
  42% and 65% are both per disputed dollars (fix story — baseline vs strong-
  evidence ceiling). The old "16% → 65%" narrative paired figures with
  different denominators, implying a single rate moving from bad to good.
  Option C restatement (DECISIONS.md in causal repo) replaces the narrative
  with two separately denominated metrics and an explicit usage rule in
  CINDERHAVEN_CANONICAL.md §4.5 approved phrasings.
- **Scope:** Every downstream piece that cites deduction recovery — approved
  phrasings, case studies, website copy.
- **Do not:** Cite 65% without 42% as baseline. Never pair 16% with 65%
  (different denominators). The 16% stands alone as the exposure diagnostic.

### 2026-06-13 — Restate lifecycle target from 80–85¢ to 85–87¢; canonical figure 86¢
- **Why:** The 80–85¢ range was set before trade spend rates locked in
  seed_config.py (Walmart 12%, Costco 10%, Whole Foods 8%, Sprouts 9%,
  Kroger 10%, Regional 7%; distributors all 5%). Group E lifecycle
  waterfall shows trade spend dominates at 9.53% of gross; fulfillment
  costs (short_ship + late_delivery) flow through correctly at 0.52%.
  The 86¢ figure is the honest mechanical result. Previous 83¢ was a
  uniform-draw artifact — no causal decomposition backed it.
- **Scope:** CINDERHAVEN_CANONICAL.md lifecycle figure, any downstream
  consumer that references the lifecycle target.
- **Do not:** Adjust trade spend percentages to force the old target.
  The rates are calibrated to real CPG benchmarks; the target follows
  the data, not the other way around.

---

## Visualization

[Chart conventions, palette decisions, interactivity choices]

---

## Output Formats

[Decisions about deliverable formats, structure, organization]

---

### 2026-06-28 — Slotting deductions are non-disputable; exclude from dispute generation
- **Why:** Slotting is a negotiated cost of shelf access — a contractual fee, not an operational error. It is never disputable. All other deduction types (short_ship, promo_billback, late_delivery, label_fine, pallet_fine, spoilage, damaged, pricing_error) have legitimate dispute paths and remain disputable.
- **Scope:** `seed_retailer.py` — both `generate_disputes()` (legacy) and `generate_causal_disputes()` (causal). Distributor pipeline unaffected (distributors don't generate slotting deductions).
- **Implementation rule:** Slotting deductions must run through the full dispute generation logic (consuming every RNG draw) but skip the INSERT. This preserves the random stream for all non-slotting deductions. Never filter slotting before the loop or `continue` before RNG draws — both break the stream.
- **Do not:** Add other deduction types to the exclusion list without explicit approval. promo_billback is disputable (brands dispute unauthorized promo rates).

---

## Writing & Voice

[Voice, style, terminology decisions specific to this project]

---

## Reversed / Superseded

When a decision is overturned:
1. Strike through the original entry above (don't delete)
2. Add a new entry below with the replacement decision
3. Note the link in both directions

This preserves the history of why something is the way it is.

### 2026-09-28 — Order-line quantities are units in every channel; never multiply them by case_pack_qty

- **Why:** The seeders write `units_ordered` as units priced per unit
  (seed_retailer.py draws 24–144 units at `msrp × WHOLESALE_MULT`;
  seed_distributor.py draws 48–360 units priced the same way), so COGS
  is `units_ordered × cogs_per_unit`. The 2026-05-17 entry (above, struck) said B2B quantity
  is cases. a6b4d20 (2026-06-12) removed the case-pack multiplier from
  mart_channel_contribution, but the 05-17 entry was never retired and
  int_loaded_contribution_by_sku kept the multiplier until 2026-09-28.
  It overstated COGS 6–24x per SKU (~13.45x across the portfolio) and
  put every SKU's loaded margin at -246% to -934% in
  sku-rationalization-framework, which published "all margins negative"
  as a finding. All structural tests passed both times.
- **Scope:** Every model that computes COGS or margin from order-line
  units (retailer, distributor, DTC).
- **Do not:** Multiply order-line units by case_pack_qty. Use
  case_pack_qty only to convert units to cases (divide, as
  canonical_gather.sql `volume.cases_b2b` does). Give any new COGS or
  margin model a plausibility band test
  (assert_channel_contribution_margin_in_band,
  assert_sku_loaded_margin_in_band).
- **Supersedes:** 2026-05-17 — mart_channel_contribution COGS must be
  channel-aware.
