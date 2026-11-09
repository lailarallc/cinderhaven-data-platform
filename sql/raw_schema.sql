-- Cinderhaven Data Platform: Raw Schema DDL (v2 — channel-isolated pipelines)
-- 41 tables across 3 isolated pipelines (retailer, distributor, DTC) + shared.
-- Schema: raw (landing zone, source-of-record)
--
-- Greenfield rebuild — no migration from v1. DROP CASCADE and recreate.

DROP SCHEMA IF EXISTS raw CASCADE;
CREATE SCHEMA raw;

-- ============================================================
-- SHARED TABLES (legitimately cross-channel)
-- ============================================================

CREATE TABLE raw.product_master (
    sku                     TEXT PRIMARY KEY,
    product_name            TEXT NOT NULL,
    product_line            TEXT NOT NULL,
    subcategory             TEXT,
    gtin14                  TEXT,
    upc                     TEXT,
    case_pack_qty           INTEGER NOT NULL,
    unit_weight_lbs         NUMERIC(8,4),
    case_weight_lbs         NUMERIC(8,4),
    case_length_in          NUMERIC(8,2),
    case_width_in           NUMERIC(8,2),
    case_height_in          NUMERIC(8,2),
    msrp                    NUMERIC(8,2) NOT NULL,
    brand_owner             TEXT,
    country_of_origin       TEXT,
    last_updated            TEXT
);

-- Point-in-time data quality history (one row per SKU per monthly snapshot).
-- Used by the chargeback prediction model to reconstruct data quality state
-- at shipment time (snapshot_date <= ship_date ORDER BY snapshot_date DESC LIMIT 1).
CREATE TABLE raw.product_master_history (
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    snapshot_date           DATE NOT NULL,
    gtin14_present          BOOLEAN NOT NULL,
    upc_present             BOOLEAN NOT NULL,
    case_dims_present       BOOLEAN NOT NULL,
    case_weight_present     BOOLEAN NOT NULL,
    data_quality_score      INTEGER NOT NULL,
    PRIMARY KEY (sku, snapshot_date)
);
CREATE INDEX idx_pmh_sku_date ON raw.product_master_history(sku, snapshot_date DESC);

CREATE TABLE raw.sku_costs (
    sku                         TEXT PRIMARY KEY REFERENCES raw.product_master(sku),
    cogs_per_unit               NUMERIC(8,2) NOT NULL,
    landed_cost_per_unit        NUMERIC(8,2) NOT NULL,
    wholesale_price             NUMERIC(8,2) NOT NULL,
    wholesale_walmart           NUMERIC(8,2),
    wholesale_costco            NUMERIC(8,2),
    wholesale_whole_foods       NUMERIC(8,2),
    wholesale_sprouts           NUMERIC(8,2),
    wholesale_regional          NUMERIC(8,2),
    wholesale_unfi              NUMERIC(8,2),
    wholesale_kehe              NUMERIC(8,2),
    wholesale_dtc               NUMERIC(8,2),
    trade_spend_pct_walmart     NUMERIC(5,4),
    trade_spend_pct_costco      NUMERIC(5,4),
    trade_spend_pct_whole_foods NUMERIC(5,4),
    trade_spend_pct_sprouts     NUMERIC(5,4),
    trade_spend_pct_kroger      NUMERIC(5,4),
    trade_spend_pct_regional    NUMERIC(5,4),
    trade_spend_pct_unfi        NUMERIC(5,4),
    trade_spend_pct_kehe        NUMERIC(5,4),
    trade_spend_pct_dtc         NUMERIC(5,4)
);

-- ============================================================
-- RETAILER PIPELINE (16 tables)
-- ============================================================

CREATE TABLE raw.retailers (
    retailer_id             TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    dispute_portal_name     TEXT,
    dispute_portal_url      TEXT,
    dispute_method          TEXT,
    notes                   TEXT
);

CREATE TABLE raw.retailer_rules (
    retailer_id             TEXT NOT NULL REFERENCES raw.retailers(retailer_id),
    deduction_type          TEXT NOT NULL,
    dispute_window_days     INTEGER,
    auto_deduct             BOOLEAN NOT NULL DEFAULT FALSE,
    evidence_required       TEXT,
    typical_recovery_rate   NUMERIC(5,4),
    notes                   TEXT,
    PRIMARY KEY (retailer_id, deduction_type)
);

CREATE TABLE raw.retailer_requirements (
    retailer_id             TEXT NOT NULL REFERENCES raw.retailers(retailer_id),
    field                   TEXT NOT NULL,
    required                BOOLEAN NOT NULL DEFAULT FALSE,
    notes                   TEXT,
    PRIMARY KEY (retailer_id, field)
);

CREATE TABLE raw.retailer_deduction_codes (
    code_id                 TEXT PRIMARY KEY,
    retailer_id             TEXT NOT NULL REFERENCES raw.retailers(retailer_id),
    code                    TEXT NOT NULL,
    name                    TEXT NOT NULL,
    deduction_type          TEXT NOT NULL,
    is_published            BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE raw.retailer_edi_requirements (
    retailer_id             TEXT NOT NULL REFERENCES raw.retailers(retailer_id),
    category                TEXT NOT NULL,
    requirement             TEXT NOT NULL,
    penalty_if_violated     TEXT,
    is_verified             BOOLEAN NOT NULL DEFAULT FALSE,
    source_url              TEXT,
    PRIMARY KEY (retailer_id, category, requirement)
);

CREATE TABLE raw.retailer_orders (
    order_id                TEXT PRIMARY KEY,
    retailer_id             TEXT NOT NULL REFERENCES raw.retailers(retailer_id),
    po_number               TEXT NOT NULL,
    po_date                 DATE NOT NULL,
    requested_ship_date     DATE,
    total_units             INTEGER NOT NULL,
    total_value             NUMERIC(12,2) NOT NULL
);
CREATE INDEX idx_retailer_orders_retailer ON raw.retailer_orders(retailer_id);
CREATE INDEX idx_retailer_orders_po_date ON raw.retailer_orders(po_date);

CREATE TABLE raw.retailer_order_lines (
    order_id                TEXT NOT NULL REFERENCES raw.retailer_orders(order_id),
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    units_ordered           INTEGER NOT NULL,
    unit_price              NUMERIC(8,2) NOT NULL,
    line_total              NUMERIC(10,2) NOT NULL,
    PRIMARY KEY (order_id, sku)
);

CREATE TABLE raw.retailer_remittances (
    remittance_id           TEXT PRIMARY KEY,
    retailer_id             TEXT NOT NULL REFERENCES raw.retailers(retailer_id),
    received_date           DATE NOT NULL,
    format                  TEXT,
    gross_amount            NUMERIC(12,2) NOT NULL,
    net_amount              NUMERIC(12,2) NOT NULL,
    total_deductions        NUMERIC(12,2) NOT NULL,
    clarity                 TEXT,
    trade_allowance         NUMERIC(12,2) NOT NULL,
    chargebacks_applied     NUMERIC(12,2) NOT NULL,
    timing_residual         NUMERIC(12,2) NOT NULL
);
CREATE INDEX idx_retailer_remittances_retailer ON raw.retailer_remittances(retailer_id);

CREATE TABLE raw.retailer_deductions (
    deduction_id            TEXT PRIMARY KEY,
    retailer_id             TEXT NOT NULL REFERENCES raw.retailers(retailer_id),
    order_id                TEXT REFERENCES raw.retailer_orders(order_id),
    remittance_id           TEXT REFERENCES raw.retailer_remittances(remittance_id),
    deduction_type          TEXT NOT NULL,
    code_id                 TEXT REFERENCES raw.retailer_deduction_codes(code_id),
    amount                  NUMERIC(10,2) NOT NULL,
    deduction_date          DATE NOT NULL,
    dispute_deadline        DATE,
    is_post_audit           BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX idx_retailer_deductions_retailer ON raw.retailer_deductions(retailer_id);
CREATE INDEX idx_retailer_deductions_date ON raw.retailer_deductions(deduction_date);

CREATE TABLE raw.retailer_disputes (
    dispute_id              TEXT PRIMARY KEY,
    deduction_id            TEXT NOT NULL REFERENCES raw.retailer_deductions(deduction_id),
    filed_date              DATE,
    filing_method           TEXT,
    evidence_quality        TEXT NOT NULL,
    outcome                 TEXT NOT NULL,
    recovered_amount        NUMERIC(10,2),
    closed_date             DATE,
    labor_hours             NUMERIC(6,2) NOT NULL
);

CREATE TABLE raw.retailer_dispute_evidence (
    evidence_id             SERIAL PRIMARY KEY,
    dispute_id              TEXT NOT NULL REFERENCES raw.retailer_disputes(dispute_id),
    evidence_type           TEXT NOT NULL,
    was_submitted           BOOLEAN NOT NULL DEFAULT FALSE,
    was_required            BOOLEAN NOT NULL DEFAULT FALSE,
    format                  TEXT,
    notes                   TEXT
);

CREATE TABLE raw.retailer_shipments (
    shipment_id             TEXT PRIMARY KEY,
    order_id                TEXT NOT NULL REFERENCES raw.retailer_orders(order_id),
    ship_date               DATE NOT NULL,
    delivery_date           DATE,
    carrier                 TEXT,
    bol_number              TEXT,
    units_shipped           INTEGER NOT NULL,
    pallets_shipped         INTEGER,
    asn_sent                BOOLEAN NOT NULL DEFAULT FALSE,
    asn_sent_late           BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX idx_retailer_shipments_order ON raw.retailer_shipments(order_id);

-- Per-SKU shipment detail: what was ordered vs. what actually shipped.
-- shortfall_reason is NULL when the line shipped complete.
CREATE TABLE raw.retailer_shipment_lines (
    shipment_id             TEXT NOT NULL REFERENCES raw.retailer_shipments(shipment_id),
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    units_ordered           INTEGER NOT NULL,
    units_shipped           INTEGER NOT NULL,
    shortfall_reason        TEXT,
    PRIMARY KEY (shipment_id, sku)
);

-- What the retailer says they received (may differ from shipped).
-- discrepancy_reason is NULL when the receipt matches the shipment.
CREATE TABLE raw.retailer_receipt_lines (
    shipment_id             TEXT NOT NULL,
    sku                     TEXT NOT NULL,
    units_received          INTEGER NOT NULL,
    discrepancy_reason      TEXT,
    PRIMARY KEY (shipment_id, sku),
    FOREIGN KEY (shipment_id, sku)
        REFERENCES raw.retailer_shipment_lines(shipment_id, sku)
);

CREATE TABLE raw.retailer_chargebacks (
    chargeback_id           SERIAL PRIMARY KEY,
    month                   DATE NOT NULL,
    retailer_id             TEXT NOT NULL REFERENCES raw.retailers(retailer_id),
    reason                  TEXT NOT NULL,
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    amount                  NUMERIC(10,2) NOT NULL,
    triggered_by_field      TEXT
);
CREATE INDEX idx_retailer_chargebacks_retailer ON raw.retailer_chargebacks(retailer_id);

CREATE TABLE raw.retailer_post_audit_claims (
    claim_id                TEXT PRIMARY KEY,
    deduction_id            TEXT NOT NULL REFERENCES raw.retailer_deductions(deduction_id),
    auditor_name            TEXT,
    audit_period_start      DATE,
    audit_period_end        DATE,
    claim_type              TEXT,
    lookback_months         INTEGER
);

CREATE TABLE raw.retailer_pack_records (
    pack_record_id          SERIAL PRIMARY KEY,
    order_id                TEXT NOT NULL REFERENCES raw.retailer_orders(order_id),
    shipment_id             TEXT REFERENCES raw.retailer_shipments(shipment_id),
    pack_date               DATE NOT NULL,
    units_picked            INTEGER NOT NULL,
    units_packed            INTEGER NOT NULL,
    pack_verification       TEXT NOT NULL,
    label_scannable         BOOLEAN NOT NULL DEFAULT TRUE,
    evidence_format         TEXT
);

-- ============================================================
-- DISTRIBUTOR PIPELINE (8 tables)
-- ============================================================

CREATE TABLE raw.distributors (
    distributor_id          TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    type                    TEXT NOT NULL,
    margin_pct              NUMERIC(5,4),
    payment_terms_days      INTEGER
);

CREATE TABLE raw.sku_distributors (
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    distributor_id          TEXT NOT NULL REFERENCES raw.distributors(distributor_id),
    PRIMARY KEY (sku, distributor_id)
);

CREATE TABLE raw.distributor_orders (
    order_id                TEXT PRIMARY KEY,
    distributor_id          TEXT NOT NULL REFERENCES raw.distributors(distributor_id),
    po_number               TEXT NOT NULL,
    po_date                 DATE NOT NULL,
    total_units             INTEGER NOT NULL,
    total_value             NUMERIC(12,2) NOT NULL
);
CREATE INDEX idx_distributor_orders_distributor ON raw.distributor_orders(distributor_id);
CREATE INDEX idx_distributor_orders_po_date ON raw.distributor_orders(po_date);

CREATE TABLE raw.distributor_order_lines (
    order_id                TEXT NOT NULL REFERENCES raw.distributor_orders(order_id),
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    units_ordered           INTEGER NOT NULL,
    unit_price              NUMERIC(8,2) NOT NULL,
    line_total              NUMERIC(10,2) NOT NULL,
    PRIMARY KEY (order_id, sku)
);

CREATE TABLE raw.distributor_remittances (
    remittance_id           TEXT PRIMARY KEY,
    distributor_id          TEXT NOT NULL REFERENCES raw.distributors(distributor_id),
    received_date           DATE NOT NULL,
    gross_amount            NUMERIC(12,2) NOT NULL,
    net_amount              NUMERIC(12,2) NOT NULL,
    total_deductions        NUMERIC(12,2) NOT NULL,
    trade_allowance         NUMERIC(12,2) NOT NULL,
    chargebacks_applied     NUMERIC(12,2) NOT NULL,
    timing_residual         NUMERIC(12,2) NOT NULL
);
CREATE INDEX idx_distributor_remittances_distributor ON raw.distributor_remittances(distributor_id);

CREATE TABLE raw.distributor_deductions (
    deduction_id            TEXT PRIMARY KEY,
    distributor_id          TEXT NOT NULL REFERENCES raw.distributors(distributor_id),
    order_id                TEXT REFERENCES raw.distributor_orders(order_id),
    remittance_id           TEXT REFERENCES raw.distributor_remittances(remittance_id),
    deduction_type          TEXT NOT NULL,
    amount                  NUMERIC(10,2) NOT NULL,
    deduction_date          DATE NOT NULL
);
CREATE INDEX idx_distributor_deductions_distributor ON raw.distributor_deductions(distributor_id);

CREATE TABLE raw.distributor_disputes (
    dispute_id              TEXT PRIMARY KEY,
    deduction_id            TEXT NOT NULL REFERENCES raw.distributor_deductions(deduction_id),
    filed_date              DATE,
    -- Group D: §2.5 weakest-link tier (POD / data quality / filing
    -- timeliness — the §1.6 reduced factor set; no ASN or pack records
    -- on this channel). Persisted so tier-conditioned outcomes are
    -- queryable in the warehouse, matching the retailer table.
    evidence_quality        TEXT NOT NULL,
    outcome                 TEXT NOT NULL,
    recovered_amount        NUMERIC(10,2),
    closed_date             DATE,
    labor_hours             NUMERIC(6,2) NOT NULL
);

CREATE TABLE raw.distributor_shipments (
    shipment_id             TEXT PRIMARY KEY,
    order_id                TEXT NOT NULL REFERENCES raw.distributor_orders(order_id),
    ship_date               DATE NOT NULL,
    delivery_date           DATE,
    carrier                 TEXT,
    units_shipped           INTEGER NOT NULL
);
CREATE INDEX idx_distributor_shipments_order ON raw.distributor_shipments(order_id);

-- Per-SKU shipment detail (distributor channel). No receipt lines:
-- distributors report discrepancies via deductions, not receiving docs.
CREATE TABLE raw.distributor_shipment_lines (
    shipment_id             TEXT NOT NULL REFERENCES raw.distributor_shipments(shipment_id),
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    units_ordered           INTEGER NOT NULL,
    units_shipped           INTEGER NOT NULL,
    shortfall_reason        TEXT,
    PRIMARY KEY (shipment_id, sku)
);

CREATE TABLE raw.distributor_chargebacks (
    chargeback_id           SERIAL PRIMARY KEY,
    month                   DATE NOT NULL,
    distributor_id          TEXT NOT NULL REFERENCES raw.distributors(distributor_id),
    reason                  TEXT NOT NULL,
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    amount                  NUMERIC(10,2) NOT NULL
);
CREATE INDEX idx_distributor_chargebacks_distributor ON raw.distributor_chargebacks(distributor_id);

-- ============================================================
-- DTC PIPELINE — SHOPIFY (6 tables)
-- ============================================================

CREATE TABLE raw.shopify_orders (
    order_id                TEXT PRIMARY KEY,
    order_number            INTEGER NOT NULL,
    created_at              TIMESTAMP NOT NULL,
    email                   TEXT NOT NULL,
    financial_status        TEXT NOT NULL,
    fulfillment_status      TEXT,
    subtotal                NUMERIC(10,2) NOT NULL,
    shipping_cost           NUMERIC(10,2) NOT NULL DEFAULT 0,
    total_tax               NUMERIC(10,2) NOT NULL DEFAULT 0,
    total                   NUMERIC(10,2) NOT NULL,
    discount_code           TEXT,
    discount_amount         NUMERIC(10,2) NOT NULL DEFAULT 0,
    fulfillment_cost        NUMERIC(10,2) NOT NULL DEFAULT 0
);
CREATE INDEX idx_shopify_orders_created ON raw.shopify_orders(created_at);

CREATE TABLE raw.shopify_order_lines (
    order_id                TEXT NOT NULL REFERENCES raw.shopify_orders(order_id),
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    product_name            TEXT NOT NULL,
    quantity                INTEGER NOT NULL,
    unit_price              NUMERIC(8,2) NOT NULL,
    line_total              NUMERIC(10,2) NOT NULL,
    PRIMARY KEY (order_id, sku)
);

CREATE TABLE raw.shopify_transactions (
    transaction_id          TEXT PRIMARY KEY,
    order_id                TEXT NOT NULL REFERENCES raw.shopify_orders(order_id),
    transaction_date        TIMESTAMP NOT NULL,
    order_amount            NUMERIC(10,2) NOT NULL,
    processing_fee          NUMERIC(10,2) NOT NULL,
    platform_fee            NUMERIC(10,2) NOT NULL DEFAULT 0,
    net_amount              NUMERIC(10,2) NOT NULL,
    gateway                 TEXT,
    card_brand              TEXT
);
CREATE INDEX idx_shopify_transactions_order ON raw.shopify_transactions(order_id);

CREATE TABLE raw.shopify_payouts (
    payout_id               TEXT PRIMARY KEY,
    payout_date             DATE NOT NULL,
    gross_amount            NUMERIC(12,2) NOT NULL,
    fees_amount             NUMERIC(10,2) NOT NULL,
    net_amount              NUMERIC(12,2) NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'paid'
);

CREATE TABLE raw.shopify_refunds (
    refund_id               TEXT PRIMARY KEY,
    order_id                TEXT NOT NULL REFERENCES raw.shopify_orders(order_id),
    refund_date             TIMESTAMP NOT NULL,
    refund_amount           NUMERIC(10,2) NOT NULL,
    reason                  TEXT
);
CREATE INDEX idx_shopify_refunds_order ON raw.shopify_refunds(order_id);

CREATE TABLE raw.shopify_chargebacks (
    chargeback_id           TEXT PRIMARY KEY,
    order_id                TEXT NOT NULL REFERENCES raw.shopify_orders(order_id),
    chargeback_date         DATE NOT NULL,
    chargeback_amount       NUMERIC(10,2) NOT NULL,
    reason                  TEXT,
    outcome                 TEXT
);

-- ============================================================
-- SHARED: STORES + DISTRIBUTION + PRICING + PROMOTIONS
-- ============================================================

CREATE TABLE raw.stores (
    store_id                TEXT PRIMARY KEY,
    retailer_id             TEXT NOT NULL REFERENCES raw.retailers(retailer_id),
    chain_name              TEXT NOT NULL,
    region                  TEXT,
    state                   TEXT,
    volume_tier             TEXT
);
CREATE INDEX idx_stores_retailer ON raw.stores(retailer_id);

CREATE TABLE raw.distribution_log (
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    store_id                TEXT NOT NULL REFERENCES raw.stores(store_id),
    authorized_date         DATE NOT NULL,
    deauthorized_date       DATE,
    PRIMARY KEY (sku, store_id, authorized_date)
);

CREATE TABLE raw.price_history (
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    retailer_id             TEXT NOT NULL REFERENCES raw.retailers(retailer_id),
    effective_date          DATE NOT NULL,
    wholesale_price         NUMERIC(8,2) NOT NULL,
    PRIMARY KEY (sku, retailer_id, effective_date)
);

CREATE TABLE raw.promotions (
    promo_id                TEXT PRIMARY KEY,
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    retailer_id             TEXT NOT NULL REFERENCES raw.retailers(retailer_id),
    start_week              DATE NOT NULL,
    end_week                DATE NOT NULL,
    discount_depth_pct      NUMERIC(5,4) NOT NULL,
    promo_type              TEXT,
    promo_cost              NUMERIC(10,2),
    funding_mechanism       TEXT
);

CREATE TABLE raw.scan_data (
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    store_id                TEXT NOT NULL REFERENCES raw.stores(store_id),
    week_ending             DATE NOT NULL,
    units_sold              INTEGER NOT NULL,
    dollars_sold            NUMERIC(10,2) NOT NULL,
    PRIMARY KEY (sku, store_id, week_ending)
);
CREATE INDEX idx_scan_data_store ON raw.scan_data(store_id);
CREATE INDEX idx_scan_data_week ON raw.scan_data(week_ending);

-- Ownership (owned sequences follow their table) and grants travel with the schema (plan U4; roles in sql/truth_roles.sql):
-- DROP SCHEMA raw CASCADE takes its grants with it, so every rebuild restates them.
DO $$
DECLARE t record;
BEGIN
    EXECUTE 'ALTER SCHEMA raw OWNER TO cinderhaven_generator';
    FOR t IN SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'raw' AND c.relkind IN ('r', 'p') LOOP
        EXECUTE format('ALTER %s raw.%I OWNER TO cinderhaven_generator',
                       'TABLE', t.relname);
    END LOOP;
END $$;
GRANT USAGE ON SCHEMA raw TO cinderhaven_dbt, cinderhaven_reader, cinderhaven_validator;
GRANT SELECT ON ALL TABLES IN SCHEMA raw TO cinderhaven_dbt, cinderhaven_reader, cinderhaven_validator;
