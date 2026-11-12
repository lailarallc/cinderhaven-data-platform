# Cinderhaven Data Platform — Failure Log

What was attempted that didn't work, why it didn't work, and what was
tried next.

Lower bar than DECISIONS.md — capture failures even when they didn't
produce a durable rule. The whole point: future-you (or future-Claude)
shouldn't re-attempt dead ends because the lesson got lost.

---

## Format

### YYYY-MM-DD — [One-line failure description]

**Attempted:** [What was tried]

**Why it didn't work:** [Concrete reason, not "it broke." If the
failure mode was technical, name the specific issue. If the failure
mode was scope or approach, name that.]

**What we tried instead:** [The next attempt, which may also have
failed and may have its own entry below]

**Status:** Resolved / open / abandoned

**Tags:** [keywords for future text-search]

---

## Entries

### 2026-07-02 — flyctl ssh console -C "sh -c \"...\$VAR...\"" silently corrupts inline secrets

**Attempted:** Passing a password through nested shell layers inline —
`flyctl ssh console -C "sh -c \"...\$OPERATOR_PASSWORD...\""` — to run an
`ALTER ROLE ... WITH PASSWORD` on the remote Postgres.

**Why it didn't work:** the escaping required to survive
(my Bash tool's shell) → (flyctl's `-C` arg) → (remote `sh -c`) → (psql
`-c` argument) is fragile enough that a single missing backslash causes
silent corruption, not a visible error. Twice, `$VAR` inside the nested
quotes got mis-expanded (once evaluated locally against an unset local
variable, once passed through empty) and Postgres accepted it as a valid
`ALTER ROLE`, just with an empty password — masked by a NOTICE
(`empty string is not a valid password, clearing password`) that's easy
to miss in a wall of connection output. Net effect: two full password
resets that silently made a role *less* authenticatable, not more.

**What we tried instead:** stopped constructing SQL inline. Wrote the
`ALTER ROLE` statement to a local file, uploaded it with
`flyctl ssh sftp put` (using `MSYS_NO_PATHCONV=1` and a `//data/...`
remote path to dodge Git Bash's path-conversion mangling), then ran it
with a plain `flyctl ssh console -C "psql -f /data/....sql"` — one shell
layer, no variable interpolation, no quoting risk. Worked cleanly, no
NOTICE. Same file-based pattern used for a `PGPASSFILE`-based auth test
afterward, for the same reason.

**Status:** Resolved (as a technique — use file upload, not inline
`-C "sh -c \"...\$VAR...\""`, for any future secret-bearing remote
command on this or similar Fly machines).

**Tags:** flyctl, ssh, shell-quoting, secrets, sftp, fly-postgres

### 2026-07-02 — cinderhaven-db pg health check PROVEN unrepairable in place

**Attempted:** One final, careful in-place repair round after two prior
sessions' failed theories: confirmed `flypgadmin` role exists and has a
password (not a missing-role issue), confirmed none of the 3 tracked
secrets (`OPERATOR_PASSWORD`, `SU_PASSWORD`, `REPL_PASSWORD`) currently
authenticate as it, realigned it to `OPERATOR_PASSWORD` via a clean
file-uploaded `ALTER ROLE` (see the shell-quoting entry above), then
independently verified — via a `PGPASSFILE`-based test and a byte-level
comparison of the live checker process's own `/proc/<pid>/environ` — that
the DB-level password is correct AND identical to what the checker
process has in its own environment.

**Why it didn't work:** the checker (`start_admin_server` on port 5500,
serving `/flycheck/pg`) still rejected the connection with the identical
`flypgadmin` auth error immediately after, using a credential proven
correct by every external test available. This rules out "wrong secret,"
"stale env," and "needs a restart" as explanations — the checker isn't
authenticating with the plain env-var password the way a normal libpq
client does. Something else (cached SCRAM state, a different internal
credential source, or a bug in this postgres-flex build) is involved,
and it's outside anything reachable via SQL or `flyctl secrets set`.

**What we tried instead:** Stopped. Per explicit instruction, did not
escalate to provisioning a fresh Fly Postgres app + 6-app `DATABASE_URL`
cutover as part of this close-out task. Documented as a scoped future
task in HANDOFF.md and the `cinderhaven-db-pg-health-check-blocked`
memory file instead.

**Status:** Open (by design — not worth pursuing further without a real
infra change or Fly support)

**Tags:** fly-postgres, flypgadmin, health-check, credentials, postgres-flex

### 2026-07-02 — cinderhaven-db flypgadmin credential fixes don't survive restart

**Attempted:** Two independent theories to fix the `pg` health check,
which authenticates as the `flypgadmin` role: (1) `ALTER ROLE flypgadmin
WITH PASSWORD` via direct SQL to match `OPERATOR_PASSWORD`; (2) set a new
`SU_PASSWORD` secret expecting postgres-flex to reconcile `flypgadmin` to
it on boot.

**Why it didn't work:** (1) verified working immediately via psql, but
the long-running checker process (`start_admin_server`/`start_monitor`)
kept failing with the same auth error even right after, and a
`/proc/<pid>/environ` check post-restart showed a different
`OPERATOR_PASSWORD` value than expected — something resets or bypasses
the SQL-level change. (2) `SU_PASSWORD` secret propagated correctly to
the machine env (confirmed via `printenv`), but `flypgadmin` still didn't
authenticate with it, and no boot-reconcile log fired for it at all
(unlike the `postgres`/`OPERATOR_PASSWORD` case, which did log a WARN and
did resolve permanently).

**What we tried instead:** Nothing further — stopped per explicit
instruction after the second theory failed, rather than attempt a third.
Recommended path: rebuild `cinderhaven-db` fresh from the platform
pipeline, or escalate to Fly support, rather than continue guessing at
undocumented credential-reconciliation behavior.

**Status:** Open

**Tags:** fly-postgres, flypgadmin, health-check, credentials, postgres-flex

### 2026-06-13 — Deferred remittance INSERT caused FK violation on deductions

**Attempted:** In Group E, deferred writing remittances to the DB
until after finalize_remittances() computed causal amounts (which needs
deduction and chargeback data). Deductions were inserted before
remittances existed.

**Why it didn't work:** retailer_deductions has a FK constraint on
remittance_id → retailer_remittances. Inserting deductions before
remittances violates the constraint. Circular dependency: remittances
need deduction data for causal amounts, but deductions need remittance
rows for FK satisfaction.

**What we tried instead:** Insert skeleton remittances with placeholder
amounts (0 for trade/chargebacks/residual, legacy values for
net/total_deductions) immediately after generation. After deductions
and chargebacks exist, finalize_remittances() computes causal amounts
and UPDATEs each remittance row in place. FK satisfied throughout.

**Status:** Resolved

**Tags:** FK, circular-dependency, remittances, deductions, Group E, seeder

---

### 2026-06-13 — Unicode box-drawing characters fail on Windows cp1252 console

**Attempted:** Used ═══ and ≥ characters in classification rate
headline print statements in seed_retailer.py and seed_distributor.py.

**Why it didn't work:** Windows console uses cp1252 encoding by
default. Box-drawing characters (═) and math symbols (≥, –) are not in
cp1252, causing UnicodeEncodeError on print().

**What we tried instead:** Replaced with ASCII equivalents: === for
═══, >= for ≥, - for –. Seed output prints cleanly on all Windows
consoles.

**Status:** Resolved

**Tags:** unicode, cp1252, windows, console, encoding, print

---

### 2026-06-12 — pgrep-based process monitor false-fired under MSYS on Windows

**Attempted:** Watch the long-running seed_all.py reseed with a
pgrep-based monitor loop (`until ! kill -0 $(pgrep -f "seed_all.py")`)
as a completion signal, alongside the harness's own background-task
notification.

**Why it didn't work:** Under MSYS bash on Windows, `pgrep -f` does not
reliably see the Windows-native python3.13 process command line, so the
check matched nothing and the monitor reported "process exited"
immediately while the seed was still running. The real process was
visible via PowerShell `Get-Process python*`.

**What we tried instead:** Trusted the background-task completion
notification alone (it fired correctly when the seed finished), with a
scheduled wakeup as the only fallback. Verified liveness once via
PowerShell when the false signal arrived.

**Status:** Resolved (workflow lesson: on this machine, don't build
process watchers on pgrep; use the harness notification or PowerShell
process queries)

**Tags:** msys, pgrep, windows, background-tasks, monitoring, seed_all

---

### 2026-06-12 — Theoretical fill calibration undershot targets by ~1pt annually

**Attempted:** Back the constrained-order probability out of the §2.1 fill
targets using a theoretical expected-loss constant (0.46) and apply the Q4
dip as a plain target reduction in Nov/Dec.

**Why it didn't work:** Two compounding effects. Q4 months carry ~23% of
annual units (SEASONALITY-weighted), so dipping Q4 below an uncompensated
base drags the annual blend ~0.9pt under target. And the realized per-order
loss was 0.467 (retailer) / 0.474 (distributor), not 0.46 — distributor
lines run larger and cut deeper. Combined: annual fills 0.8–1.5pt low.

**What we tried instead:** Measured both quantities from the generated data
and folded them in: per-channel EXPECTED_CONSTRAINED_LOSS from realized
shorted-order loss, and base rate = target + 0.23 × Q4_FILL_DIP. Annual
fills landed within ±0.64pt of every target on the next run.

**Status:** Resolved

**Tags:** fill rate, calibration, Q4, seasonality, constrained order, Group B

---

### 2026-06-12 — data_defect shortfall share landed at half the §1.4 mix

**Attempted:** Draw shortfall reasons from the §1.4 per-retailer mixes,
then reassign data_defect to allocation when the SKU's data quality score
was ≥ 75 (clean-data SKUs can't have data-defect shorts).

**Why it didn't work:** Only 23/50 SKUs (46%) are eligible, so the
reassignment halved the realized data_defect share (Whole Foods .108 vs
the approved .25) and inflated allocation.

**What we tried instead:** Exact compensation — eligible SKUs carry the
data weight scaled by (1−w)/(e−w), ineligible SKUs redistribute it
proportionally across the other reasons. Same single RNG draw either way,
so fills were untouched. WF data_defect landed at .246 vs .25.

**Status:** Resolved

**Tags:** shortfall reason, mix, data_defect, eligibility, compensation, Group B

---

### 2026-06-12 — .venv pip.exe shim dead; install via python -m pip

**Attempted:** `.venv/Scripts/pip.exe install -r requirements.txt` to
restore the platform venv (dbt etc.).

**Why it didn't work:** pip.exe produced no output and did nothing — a
stale shim (venv created from a since-updated base Python). dbt.exe was
also absent because the venv had no packages at all.

**What we tried instead:** `.venv\Scripts\python.exe -m pip install -r
requirements.txt` — installed cleanly (dbt-core 1.11.11, dbt-postgres
1.10.0).

**Status:** Resolved

**Tags:** venv, pip, dbt, windows, environment

---

### 2026-05-15 — Plan's cascade model assumed UPC/GTIN damage breaks joins

**Attempted:** Design RC1 (Excel/CSV damage) around corrupting UPC and GTIN14
fields, expecting this to cascade into orphan records when downstream tables
(scan_data, order_lines) JOIN back to product_master.

**Why it didn't work:** All downstream tables join on `sku`, not `upc` or
`gtin14`. UPC/GTIN columns only exist in product_master. Corrupting them
creates data quality issues within that table but zero cascade effect on joins.

**What we tried instead:** Added `sku_whitespace` defect type to RC1 — injects
trailing/leading whitespace on `sku` values in scan_data and order_lines. This
creates real orphan records on `LEFT JOIN product_master pm ON sd.sku = pm.sku`
because `'SKU-001 ' != 'SKU-001'`. Produces 22K+ orphans at moderate severity.

**Status:** Resolved

**Tags:** dirty-dataset, cascade, joins, sku, upc, gtin, rc1

---

### 2026-05-15 — UPDATE week_ending hits UNIQUE constraint on shifted dates

**Attempted:** `UPDATE scan_data SET week_ending = date(week_ending, '+1 day')`
for RC4 ETL pipeline failures — shifting week-ending dates by one day for
target retailers to simulate reporting discrepancies.

**Why it didn't work:** scan_data has a UNIQUE constraint on
`(sku, store_id, week_ending)`. Shifting a date +1 day can collide with an
existing row that already has that (sku, store_id, next_week) combination,
causing `sqlite3.IntegrityError`.

**What we tried instead:** Changed to `UPDATE OR IGNORE scan_data SET ...`
so collisions are silently skipped. The skipped rows don't get shifted, which
is acceptable — the defect still affects most target rows and the skip rate
is low.

**Status:** Resolved

**Tags:** dirty-dataset, sqlite, unique-constraint, week-ending, rc4

---

### 2026-05-12 — Fly.io shared-cpu-1x (256MB) crashes during scan_data ingestion

**Attempted:** Load 1.1M-row scan_data table into Postgres via proxy tunnel.
Tried three approaches at 256MB: (1) execute_batch with 5000-row batches,
(2) COPY with 50,000-row chunks, (3) COPY with 5,000-row chunks and
per-chunk reconnection. All three crashed the Postgres process — "server
closed the connection unexpectedly."

**Why it didn't work:** The 256MB shared instance runs out of memory during
sustained write operations. The COPY command, WAL writes, and transaction
log together exceed available RAM on scan_data's volume. Smaller tables
(up to 30k rows) load fine at 256MB.

**What we tried instead:** Scaled machine to 1GB temporarily
(`flyctl machine update --memory 1024`), loaded with 25k-row COPY chunks,
scaled back to 256MB. Completed in ~4.5 minutes for all 21 tables.

**Status:** Resolved

**Tags:** fly.io, postgres, memory, ingestion, scan_data, COPY, OOM

---

### 2026-05-17 — mart_channel_contribution COGS was 3.4% instead of ~50-60%

**Attempted:** `sum(o.quantity * p.cogs_per_unit)` in
mart_channel_contribution.sql — treating quantity as individual units.

**Why it didn't work:** fct_orders.quantity for B2B is *cases*, not
individual units. cogs_per_unit is per individual unit. Missing the
case_pack_qty multiplier produced COGS at 3.4% of revenue instead of
the expected 50-60% for wholesale CPG.

**What we tried instead:** Added `p.case_pack_qty` multiplier. Then
discovered a second bug: DTC quantity is individual units (from Shopify),
so applying case_pack_qty uniformly inflated DTC COGS to 457%. Final
fix is channel-aware: `case when o.channel = 'DTC' then quantity *
cogs_per_unit else quantity * case_pack_qty * cogs_per_unit end`.

**Status:** Resolved

**Tags:** dbt, cogs, mart, case-pack, dtc, channel-contribution, units

---

### 2026-11-11 — An owner's production action was recorded done on the owner's word, unchecked

**Attempted:** U4's production apply (`scripts/apply_truth_roles.py --apply`)
is the owner's to run. On 2026-11-10 the message "apply done" arrived in
chat, and the session recorded it as fact without reading production: U4's
status in the spec plan ("The owner applied `sql/truth_roles.sql` to
production on 2026-11-10", spec `d684a92`), a comment in
`verify-production-figures.yml` ("since the owner's apply on 2026-11-10"), a
comment in Dagster's `assets.py`, the commit message of `6a2acbb`, and the
session's reports. It then shipped the two superuser checks that depend on
the apply.

**Why it didn't work:** The apply had never run. Two dispatches of
verify-production-figures failed on `password authentication failed for
user "cinderhaven_ci_reader"` (runs 42878682480, 42894133549), which
Postgres also returns for a login that does not exist, so neither failure
settled it. A read of production on 2026-11-11 (`rotate_and_place.py`'s
state print) showed 0 of 4 group roles and neither login. The secret
(`POSTGRES_PASSWORD`, last updated 2026-07-13) and `~/.dbt/profiles.yml`
(`user: postgres`, last modified 2026-07-13) had also never changed, and
both were readable from metadata before the checks shipped.

**What we tried instead:** The records are restated with a dated correction
(spec plan U4 status, DECISIONS#u4-custody-shape, spec HANDOFF, this
repo's HANDOFF, the two code comments). The apply is now part of
`scripts/rotate_and_place.ps1`, which reads production's state first and
prints it, so the record can come from that print.

**Rule (scoped to the surface, not this repro):** An owner's production
action is recorded done, and anything that depends on it lands, only after
a read of production shows it. The surfaces that record it: plan unit
status lines, DECISIONS entries, HANDOFF entries, code and workflow
comments, commit messages, and session reports. The reads that count: the
catalog (`pg_roles` for roles and logins, `pg_namespace` and `pg_class` for
owners, `has_*_privilege` for grants), `gh secret list` for a secret's
update time, and the file itself for a local config (its `user:` line and
modification time, never the password). The owner's word, relayed or
typed, schedules the read; it is not the read.

**Status:** Resolved (records corrected; the apply is still to run)

**Tags:** owner action, production, verification, apply_truth_roles, U4, custody

---

### 2026-11-11 — A check that refuses a superuser shipped before the login it requires existed

**Attempted:** Dagster's `assert_scoped_login` and the superuser check in
`verify-production-figures.yml` landed in `6a2acbb` (2026-11-10), after the
unverified "apply done" (entry above). The ordering rule was "login first,
check second"; the login did not exist.

**Why it didn't work:** Both checks refuse what production still has.
`verify-production-figures` failed closed on both dispatches. Dagster's
check would have refused every build since 2026-11-10, because `~/.dbt`
still names `postgres`, a superuser. It caused no outage only because
nothing runs Dagster's schedule on this machine: no daemon, no scheduled
task, no `DAGSTER_HOME`, and no dbt invocation through `~/.dbt` since
`6a2acbb` (every "Refusing to build" line in `cinderhaven/logs/dbt.log` is
the harness's own test login). The "daily build" has not been a running
thing; the last builds through `~/.dbt` are manual ones in logs rotated on
Jul 6 and Nov 9.

**What we tried instead:** The checks stay (they fail closed, which is
their job); the apply that they wait on runs through
`rotate_and_place.ps1`. Whether Dagster's schedule should run at all is a
separate question for the owner.

**Status:** Open until the apply runs and both checks pass in production

**Tags:** Dagster, ordering, login first, superuser check, near-miss

---

### 2026-11-11 — A commit landed with a red test because the chain checked `tail`'s exit code

**Attempted:** `1489a32` (U2, the copack port) was committed and pushed from
one chain: `python tests/harness.py test | tail -1 && git add ... && git commit ...`.
The harness returns pytest's exit code, but in a pipeline the shell reports
the last command's, and `tail -1` exits 0.

**Why it didn't work:** One fast test failed
(`test_every_seeder_lives_in_generation_and_none_in_scripts` still expected
10 seeders; the port makes 11). `tail` printed the failure line, the chain
read 0, and the commit went out. CI for `1489a32` failed (run 43108437564).
`dc5ac0c` fixed the count; CI for it passed (run 43108679806).

**What we tried instead:** The fix was committed only after pytest's own
exit code was read, unpiped.

**Rule (scoped to the surface, not this repro):** A test command that gates
anything runs unpiped, or under `set -o pipefail`, so its exit code is the
test runner's. The surfaces: a commit or push chained after a test run, a
background run whose exit line is the evidence, a harness `characterize` or
`test` call, `pytest`, `dbt build`/`dbt test`, and any CI step that pipes
test output (`| tee`, `| tail`, `| grep`). Output may be trimmed for
reading only in a separate command, after the exit code has been read. Also
in CLAUDE.md under "How to work the project".

**Status:** Resolved

**Tags:** exit code, pipefail, pipe, commit gate, U2, test tier

---

### 2026-06-03 — dbt --select without + prefix misses upstream dependencies

**Attempted:** `dbt run --select dim_products fct_chargebacks dim_stores fct_scan_data fct_promotions dim_retailer_requirements` to materialize new/modified mart models.

**Why it didn't work:** dim_products depends on int_product_retailers and int_product_distributors (intermediate views). dim_stores depends on stg_stores (staging view). Without the `+` prefix, dbt only materializes the named models, not their upstream dependencies. If those views don't already exist in the database, the mart models fail with "relation does not exist."

**What we tried instead:** `dbt run --select +dim_products +dim_stores +fct_scan_data +fct_chargebacks +fct_promotions +dim_retailer_requirements` — the `+` prefix includes all upstream ancestors. 19 models materialized (13 staging views, 2 intermediate views, 4 mart tables), 0 errors.

**Status:** Resolved

**Tags:** dbt, select, dependencies, upstream, materialization

---

### 2026-05-17 — contract-to-cash headline showed 114 cents per dollar (impossible)

**Attempted:** export_json.py computed "cents per dollar" as
`net_payments / orders_invoiced`, where orders came from fct_orders
filtered by order_date and payments from fct_payments filtered by
received_date, both over CY2025.

**Why it didn't work:** Payment lag means payments received in CY2025
include payments for orders placed in late 2024. The two date filters
capture different cohorts — $16.3M invoiced but $21.6M received,
producing a ratio > 1.0 (114.4 cents per dollar received for every
dollar invoiced).

**What we tried instead:** Changed denominator from orders-based
`b2b_invoiced` to payments-based `pay["b2b_gross"]` so both sides of
the ratio come from the same remittance records. Ratio is now 86.8
cents per dollar — internally consistent. Headline changed from
"invoiced" to "collected" to match.

**Status:** Resolved

**Tags:** temporal-mismatch, cohort, contract-to-cash, date-filter, payments

---

### 2026-06-14 — Fly.io 1GB volume exhausted during dbt build (Postgres crash loop)

**Attempted:** `dbt build` against Fly.io Postgres after seeding 2.4M rows (41 tables). First with --threads 4 (OOM crash), then --threads 1 (disk exhaustion). The serialized build filled the 1GB volume to 99% (13MB free) during fct_scan_data materialization (CREATE TABLE AS on 1.4M rows). Postgres crashed and couldn't restart — WAL recovery requires free disk space.

**Why it didn't work:** The causal fulfillment model nearly doubled the dataset (1.1M → 2.4M rows). After seeding, the volume was already at ~850MB. dbt's TABLE materialization creates a full copy of the data (CREATE TABLE AS), which temporarily doubles table storage before dropping the old version. 1GB was never viable for a 2.4M-row dataset with dbt materializations.

**What we tried instead:** Extended volume from 1GB to 3GB via `flyctl volumes extend vol_vjyeldw37mqxegpv --size 3`. Postgres recovered on restart (WAL replay succeeded with free disk). dbt build completed cleanly with --threads 1 (437/437 tests pass). Volume now at 33% utilization — comfortable headroom.

**Status:** Resolved

**Tags:** fly.io, postgres, disk, volume, dbt, materialization, crash-loop, WAL

---

### 2026-06-30 — Full fleet regen in one session triggered two context compactions

**Attempted:** Run all 9 downstream repo exports, baked SQLite rebuilds, xfail removal, test suites, and commits in a single session.

**Why it didn't work:** Volume of background jobs + output inspection + file edits across 9 repos consumed context faster than the work could be verified and committed. Hit compaction twice without completing a single commit.

**What we tried instead:** (next session) Split regen across sessions by repo group — batch 3-4 repos per session, commit each batch before moving on.

**Status:** Open — regen still incomplete as of 2026-06-30.

**Tags:** context-compaction, fleet-regen, session-management, downstream-repos

---

### 2026-06-28 — Filtering slotting deductions before or inside dispute loop both break RNG stream

**Attempted:** Two approaches to exclude slotting from dispute generation: (1) `if d[4] == "slotting": continue` before the first `sel_rng.random()` draw, (2) pre-loop filter `candidates = [d for d in deductions if d[4] != "slotting"]`. Both produced identical results — 14.5% recovery / 50.9% win rate vs canonical 16.16% / 41.80%.

**Why it didn't work:** Both approaches skip the RNG draws for slotting deductions. Since each deduction consumes multiple conditional draws (selection, outcome, partial recovery fraction, close date, labor, evidence rows), skipping any deduction shifts the entire draw sequence for all subsequent deductions. Pre-loop filter and in-loop continue are mechanically equivalent — neither consumes draws for the skipped deductions.

**What we tried instead:** Let slotting deductions run through the FULL dispute generation logic — consume every RNG draw, build the dispute object — but skip only the INSERT (append to output list). This preserves the RNG stream byte-identical to the pre-fix baseline for all non-slotting deductions.

**Status:** Resolved — third approach works. Note: canonical 16%/42% still shift to ~14.7%/~50% because those rates were computed WITH slotting disputes in the population. This is a compositional effect, not an RNG issue.

**Tags:** rng, determinism, seed, dispute, slotting, random-stream-preservation
