-- costing schema — additive cost side and balance sheet.
--
-- REBUILT WITH THE REST (plan U2): seed_all.py's DDL step applies this file
-- with raw, truth and copack's tables, so every rebuild recreates `costing`
-- empty and seed_costing.py refills it from the regenerated raw. The drop
-- guard (sql/drop_guard.sql) refuses a populated `costing` unless
-- force_recreate.
--
-- NO CROSS-SCHEMA FOREIGN KEYS. `DROP SCHEMA raw CASCADE` silently drops FK
-- constraints that live in this schema while leaving the tables and their rows
-- intact; orphan rows are accepted from that moment on. Verified empirically
-- 2026-07-29. sku / store_id / shipment_id integrity is enforced in the
-- generator and asserted by tests/test_costing_integrity.sql.
--
-- Every stored total is GENERATED ALWAYS ... STORED, so it cannot diverge from
-- its parts. CHECK is reserved for invariants that are not pure functions.

DROP SCHEMA IF EXISTS costing CASCADE;
CREATE SCHEMA costing;

CREATE TABLE costing.dim_suppliers (
    supplier_id        text PRIMARY KEY,
    supplier_name      text NOT NULL,
    supplier_type      text NOT NULL,
    product_line       text,
    payment_terms_days int  NOT NULL CHECK (payment_terms_days > 0),
    terms_code         text NOT NULL,
    discount_pct       numeric(5,4) NOT NULL DEFAULT 0,
    discount_days      int,
    onboarded_date     date NOT NULL,
    CHECK (supplier_type IN ('copacker','ingredient','packaging','freight')),
    CHECK ((discount_pct = 0) = (discount_days IS NULL))
);

-- standard_cost_per_unit is set ONCE at launch from raw.sku_costs.cogs_per_unit
-- and never revised. That staleness is the mechanism: PPV is the whole gap
-- between the frozen standard and rising actual cost.
CREATE TABLE costing.fct_product_costs (
    sku                        text NOT NULL,
    cost_period                date NOT NULL,
    units_basis                bigint NOT NULL CHECK (units_basis >= 0),

    standard_cost_per_unit     numeric(10,4) NOT NULL CHECK (standard_cost_per_unit > 0),
    ingredient_cost_per_unit   numeric(10,4) NOT NULL CHECK (ingredient_cost_per_unit >= 0),
    packaging_cost_per_unit    numeric(10,4) NOT NULL CHECK (packaging_cost_per_unit  >= 0),
    conversion_cost_per_unit   numeric(10,4) NOT NULL CHECK (conversion_cost_per_unit >= 0),
    freight_in_cost_per_unit   numeric(10,4) NOT NULL CHECK (freight_in_cost_per_unit >= 0),
    overhead_per_unit          numeric(10,4) NOT NULL CHECK (overhead_per_unit        >= 0),

    manufactured_cost_per_unit numeric(12,4) GENERATED ALWAYS AS
        (ingredient_cost_per_unit + packaging_cost_per_unit + conversion_cost_per_unit) STORED,
    loaded_cost_at_standard    numeric(12,4) GENERATED ALWAYS AS
        (standard_cost_per_unit + freight_in_cost_per_unit + overhead_per_unit) STORED,
    fully_loaded_cost_per_unit numeric(12,4) GENERATED ALWAYS AS
        (ingredient_cost_per_unit + packaging_cost_per_unit + conversion_cost_per_unit
         + freight_in_cost_per_unit + overhead_per_unit) STORED,
    purchase_price_variance    numeric(18,4) GENERATED ALWAYS AS
        ((ingredient_cost_per_unit + packaging_cost_per_unit + conversion_cost_per_unit
          - standard_cost_per_unit) * units_basis) STORED,

    freight_class            int  NOT NULL,
    density_lb_per_cuft      numeric(8,4),
    dims_complete            boolean NOT NULL,
    freight_penalty_per_unit numeric(10,4) NOT NULL DEFAULT 0 CHECK (freight_penalty_per_unit >= 0),

    PRIMARY KEY (sku, cost_period),
    CHECK (dims_complete = (density_lb_per_cuft IS NOT NULL)),
    CHECK (NOT dims_complete OR freight_penalty_per_unit = 0)
);

CREATE TABLE costing.fct_production_runs (
    run_id          text PRIMARY KEY,
    sku             text NOT NULL,
    supplier_id     text NOT NULL REFERENCES costing.dim_suppliers(supplier_id),
    scheduled_date  date NOT NULL,
    completed_date  date NOT NULL,
    units_produced  int  NOT NULL CHECK (units_produced > 0),
    run_reason      text NOT NULL CHECK (run_reason IN ('reorder_point','build_ahead','launch_build')),
    CHECK (completed_date >= scheduled_date)
);

CREATE TABLE costing.dim_inventory_lots (
    lot_code       text PRIMARY KEY,
    sku            text NOT NULL,
    run_id         text NOT NULL REFERENCES costing.fct_production_runs(run_id),
    produced_date  date NOT NULL,
    expiry_date    date NOT NULL,
    units_produced int  NOT NULL CHECK (units_produced > 0),
    CHECK (expiry_date > produced_date)
);

-- Time backbone for short-dated inventory. Without this, lot composition at a
-- past snapshot is unrecomputable.
CREATE TABLE costing.fct_lot_balances (
    snapshot_date   date NOT NULL,
    lot_code        text NOT NULL REFERENCES costing.dim_inventory_lots(lot_code),
    sku             text NOT NULL,
    units_remaining int  NOT NULL CHECK (units_remaining >= 0),
    PRIMARY KEY (snapshot_date, lot_code)
);

CREATE TABLE costing.fct_inventory_snapshot (
    snapshot_date             date NOT NULL,
    sku                       text NOT NULL,
    units_on_hand             int  NOT NULL CHECK (units_on_hand    >= 0),
    units_in_transit          int  NOT NULL CHECK (units_in_transit >= 0),
    standard_cost_at_snapshot numeric(10,4) NOT NULL,
    actual_cost_at_snapshot   numeric(10,4) NOT NULL,
    demand_rate_units_per_day numeric(12,4) NOT NULL CHECK (demand_rate_units_per_day >= 0),

    value_at_standard numeric(20,4) GENERATED ALWAYS AS (units_on_hand * standard_cost_at_snapshot) STORED,
    value_at_actual   numeric(20,4) GENERATED ALWAYS AS (units_on_hand * actual_cost_at_snapshot)   STORED,
    days_of_supply    numeric(14,2) GENERATED ALWAYS AS
        (units_on_hand / NULLIF(demand_rate_units_per_day, 0)) STORED,
    is_stockout       boolean       GENERATED ALWAYS AS (units_on_hand = 0) STORED,

    PRIMARY KEY (snapshot_date, sku)
);
-- units_within_30d_exp intentionally absent: it is a rollup of fct_lot_balances
-- joined to dim_inventory_lots.expiry_date. Derived, not stored.

-- shipment_id references raw.retailer_shipments(shipment_id) logically; no FK,
-- per the isolation note above. store_id is a MODELLED DC-to-store allocation,
-- not an observed fact -- raw.retailer_shipments ships to a retailer DC and
-- carries no store_id.
CREATE TABLE costing.fct_lot_shipments (
    lot_code    text NOT NULL REFERENCES costing.dim_inventory_lots(lot_code),
    shipment_id text NOT NULL,
    store_id    text NOT NULL,
    sku         text NOT NULL,
    units       int  NOT NULL CHECK (units > 0),
    ship_date   date NOT NULL,
    PRIMARY KEY (lot_code, shipment_id, store_id)
);

CREATE TABLE costing.fct_supplier_invoices (
    invoice_id        text PRIMARY KEY,
    supplier_id       text NOT NULL REFERENCES costing.dim_suppliers(supplier_id),
    run_id            text REFERENCES costing.fct_production_runs(run_id),
    invoice_date      date NOT NULL,
    due_date          date NOT NULL,
    paid_date         date,
    invoice_type      text NOT NULL CHECK (invoice_type IN ('copack','freight','packaging')),

    goods_amount      numeric(14,2) NOT NULL CHECK (goods_amount      >= 0),
    freight_surcharge numeric(14,2) NOT NULL DEFAULT 0 CHECK (freight_surcharge >= 0),
    moq_fee           numeric(14,2) NOT NULL DEFAULT 0 CHECK (moq_fee           >= 0),
    short_ship_credit numeric(14,2) NOT NULL DEFAULT 0 CHECK (short_ship_credit >= 0),

    invoice_amount numeric(14,2) GENERATED ALWAYS AS
        (goods_amount + freight_surcharge + moq_fee - short_ship_credit) STORED,
    -- negative = paid early, e.g. taking a 2/10 discount
    days_vs_terms  int GENERATED ALWAYS AS ((paid_date - due_date)) STORED,

    CHECK (due_date >= invoice_date)
);

CREATE INDEX idx_inv_snapshot_date ON costing.fct_inventory_snapshot(snapshot_date);
CREATE INDEX idx_lot_balances_date ON costing.fct_lot_balances(snapshot_date);
CREATE INDEX idx_supplier_inv_date ON costing.fct_supplier_invoices(invoice_date);
CREATE INDEX idx_product_costs_per ON costing.fct_product_costs(cost_period);

-- Ownership (owned sequences follow their table) and grants travel with the schema (plan U4; roles in sql/truth_roles.sql):
-- DROP SCHEMA costing CASCADE takes its grants with it, so every rebuild restates them.
DO $$
DECLARE t record;
BEGIN
    EXECUTE 'ALTER SCHEMA costing OWNER TO cinderhaven_generator';
    FOR t IN SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'costing' AND c.relkind IN ('r', 'p') LOOP
        EXECUTE format('ALTER %s costing.%I OWNER TO cinderhaven_generator',
                       'TABLE', t.relname);
    END LOOP;
END $$;
GRANT USAGE ON SCHEMA costing TO cinderhaven_dbt, cinderhaven_reader, cinderhaven_validator;
GRANT SELECT ON ALL TABLES IN SCHEMA costing TO cinderhaven_dbt, cinderhaven_reader, cinderhaven_validator;
-- pg_dump reads each serial's sequence: the reader's dump needs SELECT on them.
GRANT SELECT ON ALL SEQUENCES IN SCHEMA costing TO cinderhaven_reader;
