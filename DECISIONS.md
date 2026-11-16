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

### 2026-11-09 — Truth exemptions: four file lists, and the aggregates allowed out of truth
- **Decision:** Two kinds of exemption from the truth quarantine, pinned
  separately. Adding to either needs an entry here, not a test edit.
- **Kind 1, code that names truth (file paths, never directories):**
  - AST gate (`tests/test_truth_gate.py` `AST_EXEMPT`): empty. Every
    writer lives in `generation/`, outside every scan root.
  - Text scan (`TEXT_SCAN_EXEMPT`): `sql/truth_schema.sql` and
    `sql/truth_roles.sql`, whose job is to name the tables, plus
    `cinderhaven/models/counterfactual/mart_counterfactual.sql`.
  - dbt lineage walk and compiled-SQL scan
    (`quarantine/dbt_lineage.py` `DBT_EXEMPT`):
    `cinderhaven/models/counterfactual/mart_counterfactual.sql`, named now,
    built in Phase 4 (N38) in its own schema under a narrower grant than
    `public_marts`. Data flows one way, and only this mart may cross.
  - Import ban (`tests/test_import_ban.py` `IMPORT_BAN_EXEMPT`): empty; U5
    adds its two registry readers by path, each with its own entry.
- **Kind 2, aggregates allowed out of truth (an aggregate of truth is
  truth; nothing else leaves):**
  - the populated yes/no that `public.truth_populated()` returns;
  - `mart_counterfactual`, under its own grant (Phase 4);
  - the scoring harness spec 04 places in the platform, when one is built:
    outside every root, or in list 1 by an entry here;
  - Lift Math's `ACCURACY_VIEW`, a consumer-side file with no platform
    counterpart.
- **Why:** Plan U4 (spec repo). The Lift Math pattern: an exemption costs a
  visible line and a decision, never a quiet edit. A list of files and a
  list of permitted aggregates are not one set, so they are pinned apart.
- **Scope:** `quarantine/`, `tests/test_truth_gate.py`,
  `tests/test_import_ban.py`, `tests/test_dbt_lineage.py`.
- **Do not:** exempt a directory; exempt a file to get past prose that names
  a truth table (reword it); build the needle by concatenation to get past
  the gate.

### 2026-11-15 — Import-ban exemption 1 of 2: `scripts/vendor_realism.py`; the spec gate travels in the bundle
- **Decision:** `scripts/vendor_realism.py` enters the import ban's list 4
  (`IMPORT_BAN_EXEMPT`) by path. It writes `vendor/realism/` and reads its
  MANIFEST to name what a re-vendor moved; it imports no seeder and reads no
  truth. The bundle also carries the spec gate, `scripts/check_anchors.py`, as
  `vendor/realism/check_anchors.py`, hashed in the MANIFEST like the registry.
- **Why:** Plan U5 (spec repo). The script's whole job is the bundle, so it
  cannot sit outside the ban's reach any other way; an explicit file is the
  form the U4 doctrine allows. The spec gate travels because U5's first-order
  arm must compute a row's fingerprint by the spec gate's rule
  (`figure_fingerprint`), "never a copy that can drift"; a byte-identical copy
  at the vendored commit, hashed, cannot drift, and the seeder-prints arm reads
  a row's printed figures through the same module. The plan listed the
  registry, enums and MANIFEST only; this adds one file to that list.
- **Scope:** `scripts/vendor_realism.py`, `vendor/realism/`,
  `tests/test_import_ban.py`, `.gitattributes` (the bundle is stored byte for
  byte; `-text`).
- **Do not:** edit any file under `vendor/realism/`; re-vendor instead, from a
  clean spec checkout whose gate is CLEAN.

### 2026-11-15 — Import-ban exemption 2 of 2: `scripts/check_anchor_coverage.py`; the key table's calls
- **Decision:** `scripts/check_anchor_coverage.py`, the coverage gate
  `generation/seed_all.py` runs first, enters list 4 by path. It reads the
  bundle and the seeders' source, never their runtime values, and never
  truth. The key table, `seed_config.COVERAGE_KEYS`, lists all 116 numeric
  module constants: 15 exempt (random seeds, the run seed's stride, two COPY
  chunk sizes, an exit code), 1 keyed (`EVIDENCE_OUTCOME_WEIGHTS` to A4.07,
  which prints it "from code"), 100 owed (U9 22, U10 23, U11 29, U13 15,
  U15 11). Constants typed as a call or as arithmetic on a name
  (`date(...)`, `0.23 * Q4_FILL_DIP`) are outside the scope, by the spec
  gate's own reading.
- **Session calls, for the owner's review (fork policy):**
  - Owed units follow each unit's Modify lines in the plan; where none names
    a constant, the unit whose scope covers it (disputes and evidence to
    U13's filing capacity; chargeback and deduction assessment to U11's
    A6.22; seeder fill, transit and builds to U10).
  - copack's three fixture constants (`_COPACK_LINE_RULES`,
    `COPACK_PRODUCTION_SCHEDULE`, `COPACK_SKU_INVENTORY`, ported in U2) are
    owed to U15 (runs from U16's daily ledger). No unit names them; they are
    figures (units per run, stock), so exempt would hide them.
  - Only one constant is keyed. Single numbers match dozens of rows by
    coincidence (a 30 or a 0.9 is printed somewhere), so a key is written
    only where the row governs the constant and prints it.
- **Pre-window value (owner, 2026-11-15; U18 partition row 1481).** Not a
  blanket y1 rule, three cases in order: (1) a row that registers a start
  value (A1.01's $25M, A9.13's opening draw): that governs; (2) a row
  constant across y1-y3: that constant; (3) a row that trends with no start
  value: `seed_config.value_in_effect` raises `PreWindowUnruled` naming the
  row and the reader, and the owner rules it at that first read. A key
  table `start` must be a value its row prints (seeder-prints arm). No keyed
  constant is dated today, so nothing reaches case 3 on the platform.
  Group 11's case-3 reads are listed in spec DECISIONS#pre-window-value.
- **Reviewed (owner, 2026-11-15):** the session calls above and vendoring the
  spec gate are accepted.
- **Scope:** `scripts/check_anchor_coverage.py`, `generation/seed_config.py`
  (`COVERAGE_KEYS`, `value_in_effect`), `generation/seed_all.py` (step 0),
  `tests/test_anchor_coverage.py`, `tests/test_import_ban.py`.
- **Do not:** add a key because a value happens to appear in a row; key a
  constant to the row that governs it, or owe it.

### 2026-11-15 — U8: the origin-R7 write targets get schema; five owner rulings at U8's start
- **Decision:** `sql/raw_schema.sql` gains the six write targets plan U8 names
  (N22, N35, N37, G4, N17, N11), `banner_type` on every account table, and
  N8's chargeback keys. Schema only: every new table is empty until U13, U10
  and U11 write it.
- **Owner rulings (2026-11-15; U18 partition rows routed to U8):**
  1. *07:170:* N35's year-3 flag is A3.12's monitor output, the monitor
     extended to a y3 DTC-vs-MAP check. Each `raw.map_violations` row links to
     its monitor reading and to the DTC order.
  2. *06:162 against 03:172:* freight, labour allocation, inventory write-off
     and lost sales reconcile on the ledger alone. N18, N23's labour tables
     and N27 stay in Phase 4. Unlike Amazon's fees and slotting, the P&L
     already charges these costs, so no canonical figure is short.
  3. *`banner_type`:* a seventh value, `independent`, for the small accounts;
     marketplace accounts carry `marketplace`. The column goes on the
     marketplace-account table and on each N37 account.
  4. *A6.23's remaining background streams* (N14's documents, N17's invoices
     beyond the disasters', G4's fulfilment, claim and fraud tables, the
     `dtc_customer` base) are out of the window. A6.23's stream list and
     A6.04's rate pairs are restated to what the window generates (spec side).
  5. *A11.04's account count and order frequency* stay owed to U13.
  Already ruled: A11.02's Buy Box share, 95% outside disaster 1 and 0% in the
  undercut weeks (spec DECISIONS#u18-rulings, 2026-10-20).
- **Session calls, for the owner's review (fork policy):**
  - *Value spelling.* The six banner types are stored as the 2026-09-02
    ruling prints them (`national retailer`, `regional retailer`, `club
    retailer`, `natural retailer`, `distributor`, `marketplace`), lower case
    with a space, because the column is rendered text. Each table's CHECK
    admits only its own values: retailers the four retailer types,
    distributors `distributor`, marketplace accounts `marketplace`, N37
    accounts `independent`.
  - *Table names* follow the plan's staging names and the channel prefixes
    already in `raw`: `marketplace_accounts`, `amazon_orders`,
    `amazon_order_lines`, `amazon_fees`, `amazon_buy_box`,
    `amazon_3p_listings`, `marketplace_events`; `map_policy`,
    `map_price_monitor`, `map_violations`; `small_accounts`,
    `small_account_orders`, `_order_lines`, `_shipments`, `_shipment_lines`,
    `_receipt_lines`, `_remittances`; `shopify_subscriptions`,
    `shopify_subscription_cancellations`; `invoices`; `store_week_oos`.
  - *Pre-policy violations are rejected by a key, not a date.* A violation
    carries its MAP's `(sku, effective_date)` as a foreign key to
    `map_policy` and must fall on or after it. No window date is typed into
    the DDL; A3.12's year-3 date reaches it through the policy row.
  - *N37 gets shipment lines*, which the plan's list leaves out: receipt lines
    key to them in the retailer pattern, and 05's decomposition test sums
    shipped per order line, which needs SKU-grain shipments.
  - *N37 orders carry freight and handling amounts.* 07's week-14 invoice is
    priced at A3.17's landed band (unit + freight + handling); without them
    the cascade row has nowhere to land.
  - *N37's `cancelled_by` takes no CHECK.* 05 codes it `retailer` /
    `cinderhaven`, and whether the ordering party on a non-retailer order
    keeps the `retailer` code is 05's open question; U10 rules it.
  - *`dtc_customer_id` has no foreign key.* Ruling 4 keeps the
    `dtc_customer` base out of the window, so the converted account carries
    the Shopify customer key (U11 writes it) without a table to reference.
  - *Invoices are channel-neutral*, keyed to exactly one shipment (retailer,
    distributor or N37) by the exactly-one CHECK 05 uses on
    `po_revisions`: disaster 1's affected invoices are retailer invoices,
    disaster 2's are N37's.
  - *The N11 flag is SKU × store × week*, not store × week: the drained
    stores are out of one SKU, and a store-week flag derives from it.
  - *Marketplace event types* are A11.02's four: FBA lost and damaged
    reimbursement, customer return and refund, Buy Box loss, plus disaster
    2's channel-conflict complaint. Inventory fees are fee rows, not events.
  - *Empty write targets do not fail the run.* `seed_all.verify_counts`
    fails on any empty table, so `seed_all.AWAITING_WRITER` names each U8
    table and the unit that writes it. U13 writes the marketplace accounts,
    Amazon's orders, lines and fees, and every N37 table. U10 writes the
    subscriptions. U11 writes the cancellations, the Buy Box readings, the 3P
    listings, marketplace events, the three MAP tables, invoices and the OOS
    flag. MAP policy is not named in the plan's writer list, so it goes to
    U11, whose violations need it. Each writer removes its entries in the
    change that writes them.
  - *G4's tables carry the `shopify_` prefix* of the DTC pipeline they sit in.
    `subscription_id` on `raw.shopify_orders` is not carried into
    `stg_shopify_orders`, because the plan's file list does not name that
    model. Group 8's subscription/one-time count reads it when U10 fills it.
  - *The drop guard's reference stays at `934785e`* (deploy-costing.yml),
    because production still holds the pre-U8 tables. The harness test's
    reference is today's DDL, the one its world is built from, and empty write
    targets are not "populated". Once U12 rebuilds production on this DDL, the
    guard's column arm would refuse every U8 column unless U12 moves
    `RAW_REFERENCE_COMMIT` in the same change.
- **Scope:** `sql/raw_schema.sql`, `generation/seed_config.py`,
  `generation/seed_shared.py`, the staging, intermediate and mart models plan
  U8 names, `tests/test_r7_write_targets.py`.
- **Do not:** give the small-account tier a `raw.retailers` row, or add a
  vendor chargeback or shortage-claim table for Amazon (A11.01's 3P model).

### 2026-11-15 — `AWAITING_WRITER` only shrinks; the vendored bundle carries each unit's DONE status
- **Decision (owner, 2026-11-15):** `seed_all.AWAITING_WRITER` is an
  exceptions list, and exceptions here only shrink.
  `tests/test_awaiting_writer.py` freezes the list as U8 merged it (21
  tables) and fails in three cases:
  - a table is added to the list;
  - a table's writer changes;
  - in the DB tier, a listed table is still empty when its writer unit reads
    DONE.
- **Session call, for the owner's review:** the platform held no unit
  status, so `scripts/vendor_realism.py` now derives `unit_status.json` from
  the regen plan at the vendored commit. Each unit gets its status date and
  whether the status starts with DONE ("Done in substance" and "Code
  complete" do not count). Only that is vendored, never the plan's prose,
  because canonical-drift scans `vendor/`. A spec checkout without the plan
  is refused. Re-vendored at spec `6b5a663` (gate CLEAN; `anchors.yml`
  moved, for A6.04 and A6.23). The coverage gate is CLEAN.
- **Reviewed (owner, 2026-11-15):** the `unit_status.json` call is accepted.
  This re-vendor merged under the standing rule: a vendored copy of a merged
  spec commit is not a registry change (entry above).
- **Scope:** `generation/seed_all.py`, `scripts/vendor_realism.py`,
  `vendor/realism/`, `tests/test_awaiting_writer.py`,
  `tests/test_vendor_realism.py`.
- **Do not:** add a table to `AWAITING_WRITER` or widen the ceiling in the
  test. A new schema-first table needs its own owner ruling.

### 2026-11-15 — U15: the spec generators wired in; owner rulings at its start; session calls
- **Owner rulings at U15's start (2026-11-15; spec `DECISIONS#u15-rulings`,
  spec `42bbbff`):** 1449, Test A, was already ruled (trial 0 decides);
  1398, the mature hazard: the figure stands and the "inside 5–8%" text is
  corrected; 1448, A3.21's `pricing_error` rate, is routed to U10's start,
  carrying 14.62% of count at A10.17's means against A3.21's 2–4%.
- **The bundle:** `vendor/realism/` at spec `42bbbff` (gate CLEAN): the
  registry, its enums, the spec gate, the four generators and `outputs.json`
  from the gate's own `--export`. The MANIFEST adds the memo key as
  `memo_sha256` (the spec gate's cache key, recomputed by the loader from
  the vendored copies; named for what it is, a digest, after the gitleaks
  hook read a `*_key` field as an API key) and
  trial 0's digest. `scripts/vendor_realism.py` is the one procedure: it
  stages every file, runs the slow recompute on the staged bytes in a fresh
  process (groups 8 and 9 recomputed; 10 and 11 on the memo's factor; a
  fresh solve), and installs nothing unless it holds.
- **Session calls, for the owner's review (fork policy):**
  - *The memo key and trial digest live in the MANIFEST, not `outputs.json`.*
    The spec gate's `--export` writes `{commit, generators}` only; the
    vendor step adds both, computed by the loader's own functions.
  - *The seed-time replay calls `catalogue_draws(trials=1, replay=0)`, not
    group 11's `outputs()`.* `outputs()` recomputes every printed value;
    the replay alone takes 12 s and equals the exported `trial` exactly.
  - *The paid-date rule binds to the generator, not the plan's prose.* The
    plan says "the first AP run on or after its due date"; group 9's
    `_ap_run` pays at the run nearest the invoice's DPO day (A9.11,
    owner-signed 2026-10-21), which can fall before the due date. U18 Q8
    binds A10.07 exactly to the ledger, so `seed_costing.plan` calls
    `_ap_run` through the bundle.
  - *A part-held run on whole invoices.* At each run the platform pays its
    queue oldest first up to the ledger's paid share, (due − held) / due; the
    first invoice that does not fit waits whole, with every newer one. An
    invoice whose run falls after the schedule's last is paid at its run.
  - *Terms through the bundle:* co-packers read A9.11's co-packer terms (30;
    the value does not move); `COPACK_TERMS` leaves `COVERAGE_KEYS`.
    ~~The packaging supplier reads A9.11's glass terms (45).~~ Struck by the
    owner, 2026-11-15 ("a guess wearing a rule's clothes"): `PACKAGING_TERMS`
    stays typed and owed (rulings below).
  - *U4's ban names the four generators by bare module name.* A scan-root
    `import group11_compliance` passed it; the trial names which SKUs the
    world declines.
  - *The literal test ships with an owed list* (22 values and 10 series in
    today's seeders, owed to U9 and U10), only ever shrinking, keyed by file
    and value; a hit beyond it fails. Significant figures follow the plan:
    400, 1200 and 2000 have one or two, so A7.04's round door counts in
    `seed_config.py` are not caught as single values (they are not typed as
    a series in plan order either).
  - *Parity routes as data:* `tests/acceptance/parity_routes.json` routes
    all 651 keys (1 arm here, 142 owed arms pre-registered with class,
    assertion and writer, 177 to another suite, 331 read by no seeder). An
    owed arm whose writer the vendored plan marks DONE fails.
- **The four findings, RULED (owner, 2026-11-15, relayed verbatim through the
  U3 session):**
  1. *Hold the paid-date rule.* "The rule is right; the invoices underneath
     it are wrong, and U9 rebuilds them." It stays built and OFF
     (`seed_costing.PAID_DATES_FROM_LEDGER = False`): the AP scatter writes
     paid dates, and the baseline does not move. Its arm is red by design
     (strict xfail on the switch); a test fails once U9 is DONE with the
     switch still off. U9's Depends-on gains "turn on the paid-date rule; no
     invoice past the ledger's worst days" (spec plan).
  2. *The 142 owed arms are accepted on one condition:* a list that only
     shrinks, each tied to the unit that creates its columns, each becoming
     SQL when that unit lands. `OWED_CEILING` in the parity suite (U7 8,
     U9 86, U10 43, U13 5) is tested.
  3. *A10.07's exact ladder and the held co-packer's slipped runs* go in
     U9's Depends-on (spec plan).
  4. *The nine keys:* group 8's three DTC fee constants to U10; the two drift
     constants to U9; copack's three fixtures to U10, with an owner ruling at
     U10's start (derive the booked runs from the co-packed share and A5.29's
     run floor, or register them). `FREIGHT_TERMS`: A5.24 does not print
     freight terms, so it is a registry row owed, not "no unit".
     `PACKAGING_TERMS` likewise. Both are owed to U9 (the gate requires a
     window unit; U9 owns the supplier rows and the freight constants), the
     why naming the missing row. That routing is a session call.
  - On the fork calls: the `memo_sha256` rename and the paid-date rule
    (`_ap_run`, the generator's rule) stand.
- **The findings as raised** (kept for the record):
  - *The owed arms are pre-registered as assertions, not SQL.* Most read
    columns that do not exist yet (`raw.stores` has no banner or year;
    `raw.shopify_chargebacks` no network). SQL on columns the writer has not
    named would be a guess, so each writer writes its arm with the shape.
  - *A10.07's ladder and the held co-packer's slip need U9.* Invoice dollars
    equal the ledger's only on U9's COGS, and the held co-packer is A5.30's,
    which U9 builds; until then U15 writes paid dates only, no slipped run.
  - *On today's invoices the rule writes a y2 tail the ledger does not
    hold.* The platform's 294 copack invoices are lumpy (median $110K,
    largest $662K) and do not follow the ledger's daily purchases. Days past
    terms by invoice year, worst / mean: 10 / 2.0 (y1), 164 / 26.2 (y2),
    9 / 3.5 (y3). The ledger's own worst is about 48 in y2 (A10.07, the
    line's own cash), and its y1 holds barely show. Paying the invoice that
    crosses the line (or rounding it at half) still leaves 90 days in y2, so
    the rule is not the cause; the invoices are. The strict rule stays (it
    never pays past the ledger's line). Owner: ship U15's paid dates now, or
    hold the paid-date change until U9's invoices.
  - *Nine `COVERAGE_KEYS` stay owed to U15* with no U15 landing in the plan:
    group 8's three DTC fee constants (U10's `seed_dtc.py`), the two drift
    constants (U9's COGS), `FREIGHT_TERMS` (no row) and copack's three
    fixtures (no generator output carries per-SKU copack runs).
- **Scope:** `scripts/vendor_realism.py`, `vendor/realism/`,
  `generation/realism_bundle.py`, `generation/seed_costing.py`,
  `generation/seed_config.py` (`COVERAGE_KEYS`), `quarantine/truth_gate.py`,
  `tests/test_vendor_realism.py`, `tests/test_realism_bundle.py`,
  `tests/fixtures/bundle/`, `tests/acceptance/`.
- **Do not:** import a group module or read `vendor/realism/` outside
  `generation/realism_bundle.py`; solve the account factor at seed time;
  draw a paid date.

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

### 2026-11-15 — canonical-drift allows "$32.5M" in the vendored registry only (session call)

- **Why:** `fe3baf6` (U5) turned main's canonical-drift job red. `vendor/realism/anchors.yml`
  prints A1.02's y1 gross as $32.5M; the token collides with the retired pre-reseed
  scan-revenue form in `reference/canonical_values.json`. The bundle is hashed byte for
  byte (U5), so the platform cannot edit it. Fixed in `dfbd88f`.
- **Scope:** `.canonical-allowlist`, one line: `$32.5M @ vendor/realism/anchors.yml`.
- **Do not:** skip `vendor/realism/` whole, or allow a token across files; each further
  collision gets its own token-and-file line. Run `scripts/check_canonical_drift.py`
  before any merge that re-vendors the registry: CI's `ci.yml` does not run it.
- **Review:** fork-policy call, for the owner's after-the-fact review.

### 2026-11-15 — A re-vendor of a merged spec commit is not a registry change (owner)

- **Ruling (owner, 2026-11-15):** "registry values are never covered" (the merge rule, global
  CLAUDE.md) means changes to the spec's rows or signatures. A vendored copy of a spec commit
  already on spec main, verified by hash against its MANIFEST, is not a registry change and
  merges under the standing rule.
- **Why:** the copy changes nothing; the MANIFEST's sha256 proves it is the same registry.
- **Scope:** `vendor/realism/`, `scripts/vendor_realism.py`; the U5 merge (`fe3baf6`) and
  `u8-followups` (spec `6b5a663`).
- **Do not:** merge a re-vendor of a spec commit that is not on spec main, or one whose files
  do not hash to that commit; those still need the owner's word. A change to a spec row or
  signature is never covered.
- **Owner:** Shawn, ruled 2026-11-15.

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
