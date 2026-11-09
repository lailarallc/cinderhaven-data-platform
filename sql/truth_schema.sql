-- truth: what actually happened. QUARANTINED (plan U4; spec 04, 06).
--
-- Written by cinderhaven_generator only; read by cinderhaven_validator only.
-- The reader and dbt roles hold no USAGE here. Requires sql/truth_roles.sql.
-- Rebuilt from DDL on every run, like every other generated schema.
--
-- No cross-schema FOREIGN KEYs (see costing_schema.sql: DROP SCHEMA raw CASCADE
-- would silently drop them). Links to raw are by id, checked by the suites.
--
-- The writers arrive later: U9 (price waterfall rows), U11 (injection,
-- corruption, promo, outage, defect rows), U7 (the suites that read them).

DROP SCHEMA IF EXISTS truth CASCADE;
CREATE SCHEMA truth;

-- R7: every injected operational error, its cost, and whether it was ever
-- detected (spec 06). detected_date NULL means never detected: the point.
CREATE TABLE truth.injection_ledger (
    injection_id             SERIAL PRIMARY KEY,
    -- U9's clamp and loss-leader rows are price_integrity; U7's R7 suite excludes them by name.
    row_class                TEXT NOT NULL CHECK (row_class IN ('injected_error', 'price_integrity')),
    occurred_date            DATE NOT NULL,
    actor                    TEXT NOT NULL CHECK (actor IN ('cinderhaven_staff', 'retailer', 'distributor',
                                 'carrier', 'dtc_customer', 'system', 'supplier')),
    actor_detail             TEXT,
    error_type               TEXT NOT NULL,
    entity_type              TEXT NOT NULL,
    entity_id                TEXT NOT NULL,
    magnitude                NUMERIC(14,4),
    expected_cost            NUMERIC(12,2),
    detected_date            DATE,
    -- A6.09's mix: raw.error_events' values plus undetected; NULL while unresolved at window end.
    resolution               TEXT CHECK (resolution IN ('corrected', 'corrected_after_consequence',
                                 'disputed_won', 'disputed_partial', 'disputed_lost', 'written_off', 'undetected')),
    error_event_id           INTEGER,           -- raw.error_events.error_id when detected
    -- R10's counterfactual layer (spec 01). preventable_by is A6.14's closed set;
    -- nullable until U11 rules whether rows outside the deduction buckets carry one.
    preventable_by           TEXT CHECK (preventable_by IN ('item_setup_preflight', 'three_way_match',
                                 'deduction_validation', 'edi_reconciliation', 'receiving_audit',
                                 'po_acknowledgment', 'price_book_governance', 'none')),
    -- A6.12's ratio, cost when caught by the named control / cost when not caught
    -- (expected_cost), floored at 0.02: catching costs labor. Dollars are derived
    -- at read (cost_if_caught * expected_cost), never stored (owner, 2026-11-09).
    cost_if_caught           NUMERIC(5,4) CHECK (cost_if_caught >= 0.02),
    benchmark_detection_rate NUMERIC(5,4) CHECK (benchmark_detection_rate >= 0
                                 AND benchmark_detection_rate < 1),               -- A6.13, per control
    CHECK (detected_date IS NULL OR detected_date >= occurred_date)
);

-- R7's corruption pass: a correct record damaged in transit (spec 06). Scored
-- separately from injection_ledger.
CREATE TABLE truth.corruption_ledger (
    corruption_id       SERIAL PRIMARY KEY,
    root_cause          TEXT NOT NULL,
    target_table        TEXT NOT NULL,
    target_column       TEXT,
    row_key             TEXT NOT NULL,
    original_value      TEXT,
    corrupted_value     TEXT,
    cascade_parent_id   INTEGER REFERENCES truth.corruption_ledger (corruption_id),
    applied_order       INTEGER NOT NULL
);

-- R8: the promo response the overlay used to hold, by component (spec 04).
CREATE TABLE truth.promo_events (
    promo_event_id  SERIAL PRIMARY KEY,
    sku             TEXT NOT NULL,
    retailer_id     TEXT NOT NULL,
    store_id        TEXT,
    week_ending     DATE NOT NULL,
    component       TEXT NOT NULL CHECK (component IN ('baseline', 'lift', 'dip', 'transfer', 'noise')),
    units           NUMERIC(14,4) NOT NULL,
    dollars         NUMERIC(14,2)
);

-- N11 / A7.14: planted availability episodes, plus U11's scripted one (spec 03).
CREATE TABLE truth.outage_episodes (
    episode_id      SERIAL PRIMARY KEY,
    store_id        TEXT NOT NULL,
    sku             TEXT NOT NULL,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    cause           TEXT NOT NULL,
    scripted        BOOLEAN NOT NULL DEFAULT false,
    CHECK (end_date >= start_date)
);

-- The DEFECT_SEED profile, persisted (spec 03:158): one row per defect.
CREATE TABLE truth.defect_ledger (
    defect_id       SERIAL PRIMARY KEY,
    sku             TEXT NOT NULL,
    defect_type     TEXT NOT NULL,
    field_name      TEXT,
    effective_from  DATE,
    effective_to    DATE
);

-- U18 Q3: one row per chain stage, keyed to the breach.
CREATE TABLE truth.consequence_chains (
    chain_id            INTEGER NOT NULL,
    stage_seq           INTEGER NOT NULL,
    account_id          TEXT NOT NULL,
    sku                 TEXT,
    metric              TEXT NOT NULL,
    breach_period_start DATE NOT NULL,
    breach_period_end   DATE NOT NULL,
    stage               TEXT NOT NULL,
    stage_date          DATE NOT NULL,
    cause               TEXT NOT NULL,
    PRIMARY KEY (chain_id, stage_seq)
);

-- Ownership (owned sequences follow their table) and grants travel with the schema: the generator owns and writes,
-- the validator reads, nobody else has USAGE.
DO $$
DECLARE t record;
BEGIN
    EXECUTE 'ALTER SCHEMA truth OWNER TO cinderhaven_generator';
    FOR t IN SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'truth' AND c.relkind IN ('r', 'p') LOOP
        EXECUTE format('ALTER %s truth.%I OWNER TO cinderhaven_generator',
                       'TABLE', t.relname);
    END LOOP;
END $$;
REVOKE ALL ON SCHEMA truth FROM PUBLIC;
GRANT USAGE ON SCHEMA truth TO cinderhaven_validator;
GRANT SELECT ON ALL TABLES IN SCHEMA truth TO cinderhaven_validator;
