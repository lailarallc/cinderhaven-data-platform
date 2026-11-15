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
    notes                   TEXT,
    -- Headline-surface category (spec DECISIONS 2026-09-02; plan U8). Rendered
    -- on public pages in place of the name.
    banner_type             TEXT NOT NULL CHECK (banner_type IN
                                ('national retailer', 'regional retailer', 'club retailer', 'natural retailer'))
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
    triggered_by_field      TEXT,
    -- N8 (03:97, plan U8): the order and shipment a chargeback answers to. NULL
    -- until U11 makes chargebacks event-driven.
    order_id                TEXT REFERENCES raw.retailer_orders(order_id),
    shipment_id             TEXT REFERENCES raw.retailer_shipments(shipment_id)
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
    payment_terms_days      INTEGER,
    banner_type             TEXT NOT NULL CHECK (banner_type = 'distributor')
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
    amount                  NUMERIC(10,2) NOT NULL,
    order_id                TEXT REFERENCES raw.distributor_orders(order_id),       -- N8, as the retailer table
    shipment_id             TEXT REFERENCES raw.distributor_shipments(shipment_id)
);
CREATE INDEX idx_distributor_chargebacks_distributor ON raw.distributor_chargebacks(distributor_id);

-- ============================================================
-- DTC PIPELINE — SHOPIFY (6 tables, and G4's two subscription tables)
-- ============================================================

-- G4 (plan U8): the subscriptions the window's subscription orders carry (U10
-- writes them) and the cancellations with their reason (disaster 1's, U11).
CREATE TABLE raw.shopify_subscriptions (
    subscription_id         TEXT PRIMARY KEY,
    email                   TEXT NOT NULL,
    sku                     TEXT REFERENCES raw.product_master(sku),
    interval_days           INTEGER,
    started_date            DATE NOT NULL,
    status                  TEXT NOT NULL CHECK (status IN ('active', 'paused', 'cancelled'))
);

CREATE TABLE raw.shopify_subscription_cancellations (
    cancellation_id         TEXT PRIMARY KEY,
    subscription_id         TEXT NOT NULL UNIQUE REFERENCES raw.shopify_subscriptions(subscription_id),
    cancelled_date          DATE NOT NULL,
    reason                  TEXT NOT NULL
);

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
    fulfillment_cost        NUMERIC(10,2) NOT NULL DEFAULT 0,
    -- G4: set on a subscription order, NULL on a one-time order (group 8's two types).
    subscription_id         TEXT REFERENCES raw.shopify_subscriptions(subscription_id)
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

-- ============================================================
-- ORIGIN-R7 WRITE TARGETS (plan U8): N22, N35, N37, N17, N11
-- Schema only. U13 writes the in-window channel rows, U11 the two scripted
-- disasters' rows, Phase 4 the additive halves. G4's tables sit with the DTC
-- pipeline above; R6's raw.po_revisions is U10's.
-- ============================================================

-- N22 / N37: the brand's marketplace accounts, Amazon (3P Seller Central with
-- FBA, A11.01) and Faire. Marketplace events resolve against these, never a listing.
CREATE TABLE raw.marketplace_accounts (
    marketplace_account_id  TEXT PRIMARY KEY,
    marketplace             TEXT NOT NULL CHECK (marketplace IN ('amazon', 'faire')),
    name                    TEXT NOT NULL,
    banner_type             TEXT NOT NULL CHECK (banner_type = 'marketplace')
);

-- N22: Amazon orders and order lines at SKU grain (seed_costing and the margin mart cost by SKU).
CREATE TABLE raw.amazon_orders (
    order_id                TEXT PRIMARY KEY,
    marketplace_account_id  TEXT NOT NULL REFERENCES raw.marketplace_accounts(marketplace_account_id),
    order_date              DATE NOT NULL,
    total_units             INTEGER NOT NULL,
    total_value             NUMERIC(12,2) NOT NULL
);
CREATE INDEX idx_amazon_orders_date ON raw.amazon_orders(order_date);

CREATE TABLE raw.amazon_order_lines (
    order_id                TEXT NOT NULL REFERENCES raw.amazon_orders(order_id),
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    quantity                INTEGER NOT NULL,
    unit_price              NUMERIC(8,2) NOT NULL,
    line_total              NUMERIC(10,2) NOT NULL,
    PRIMARY KEY (order_id, sku)
);

-- N22: one row per charge, group 9's seven marketplace_fees(t) components (A11.22,
-- A11.30, A11.31). Per-order fees carry their order; monthly fees carry none.
-- No vendor chargebacks and no shortage claims: a 3P brand has neither (A11.01).
CREATE TABLE raw.amazon_fees (
    fee_id                  TEXT PRIMARY KEY,
    marketplace_account_id  TEXT NOT NULL REFERENCES raw.marketplace_accounts(marketplace_account_id),
    order_id                TEXT REFERENCES raw.amazon_orders(order_id),
    fee_type                TEXT NOT NULL CHECK (fee_type IN
                                ('referral', 'fba_fulfillment', 'returnless_refund',
                                 'storage', 'inbound_placement', 'advertising', 'selling_plan')),
    fee_date                DATE NOT NULL,
    amount                  NUMERIC(10,2) NOT NULL,
    CHECK ((order_id IS NOT NULL) = (fee_type IN ('referral', 'fba_fulfillment', 'returnless_refund')))
);
CREATE INDEX idx_amazon_fees_order ON raw.amazon_fees(order_id);

-- N22: the brand's own offer's Buy Box share by SKU and week (A11.02).
CREATE TABLE raw.amazon_buy_box (
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    week_ending             DATE NOT NULL,
    buy_box_share           NUMERIC(5,4) NOT NULL CHECK (buy_box_share BETWEEN 0 AND 1),
    PRIMARY KEY (sku, week_ending)
);

-- N22: third-party sellers' listings of the brand's SKUs (disaster 1's week 2).
CREATE TABLE raw.amazon_3p_listings (
    listing_id              TEXT PRIMARY KEY,
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    seller_name             TEXT NOT NULL,
    listed_date             DATE NOT NULL,
    delisted_date           DATE,
    listed_price            NUMERIC(8,2) NOT NULL,
    units_listed            INTEGER
);

-- N35: MAP from year 3 (A3.12); the monitor of 3P listed price against DTC from
-- year 1, extended in year 3 to DTC price against MAP (owner, 2026-11-15); the
-- flagged violations are the monitor's output, each keyed to its reading and a DTC order.
CREATE TABLE raw.map_policy (
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    effective_date          DATE NOT NULL,
    map_price               NUMERIC(8,2) NOT NULL,
    PRIMARY KEY (sku, effective_date)
);

CREATE TABLE raw.map_price_monitor (
    reading_id              TEXT PRIMARY KEY,
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    reading_date            DATE NOT NULL,
    basis                   TEXT NOT NULL CHECK (basis IN ('3p_vs_dtc', 'dtc_vs_map')),
    observed_price          NUMERIC(8,2) NOT NULL,  -- 3P listed price, or the DTC price
    reference_price         NUMERIC(8,2) NOT NULL,  -- the DTC price, or MAP
    listing_id              TEXT REFERENCES raw.amazon_3p_listings(listing_id),
    map_effective_date      DATE,
    fired                   BOOLEAN NOT NULL,
    FOREIGN KEY (sku, map_effective_date) REFERENCES raw.map_policy(sku, effective_date),
    CHECK ((basis = 'dtc_vs_map') = (map_effective_date IS NOT NULL)),
    CHECK (reading_date >= map_effective_date)
);

-- A violation exists only under a policy in effect: its MAP's (sku, effective_date)
-- is a foreign key, and the violation falls on or after it.
CREATE TABLE raw.map_violations (
    violation_id            TEXT PRIMARY KEY,
    reading_id              TEXT NOT NULL REFERENCES raw.map_price_monitor(reading_id),
    order_id                TEXT NOT NULL REFERENCES raw.shopify_orders(order_id),
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    violation_date          DATE NOT NULL,
    observed_price          NUMERIC(8,2) NOT NULL,
    map_effective_date      DATE NOT NULL,
    FOREIGN KEY (sku, map_effective_date) REFERENCES raw.map_policy(sku, effective_date),
    CHECK (violation_date >= map_effective_date)
);

-- N37: the small-account tier, a channel of its own (owner, 2026-10-09): its own
-- accounts and order-to-cash tables, and no raw.retailers row.
CREATE TABLE raw.small_accounts (
    small_account_id        TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    account_type            TEXT NOT NULL,
    origin                  TEXT NOT NULL CHECK (origin IN ('inbound', 'broker', 'faire', 'converted_from_dtc')),
    dtc_customer_id         TEXT,  -- the converted account's Shopify customer; no DTC customer table in the window
    rep                     TEXT,
    price_tier              TEXT NOT NULL,
    moq_cases               INTEGER,
    freight_policy          TEXT,
    payment_terms_days      INTEGER,
    first_order_date        DATE,
    last_order_date         DATE,
    banner_type             TEXT NOT NULL CHECK (banner_type = 'independent'),
    -- A converted account names its DTC customer and the rep who converted it; no other account has a DTC customer.
    CHECK (CASE WHEN origin = 'converted_from_dtc' THEN dtc_customer_id IS NOT NULL AND rep IS NOT NULL
                ELSE dtc_customer_id IS NULL END)
);

-- 05's order-level R6 columns; U13's writer fills them on insert, at revision zero.
CREATE TABLE raw.small_account_orders (
    order_id                TEXT PRIMARY KEY,
    small_account_id        TEXT NOT NULL REFERENCES raw.small_accounts(small_account_id),
    ordering_channel        TEXT NOT NULL CHECK (ordering_channel IN ('faire_marketplace', 'faire_direct', 'direct')),
    po_date                 DATE NOT NULL,
    requested_ship_date     DATE,
    total_units             INTEGER NOT NULL,
    total_value             NUMERIC(12,2) NOT NULL,
    freight_amount          NUMERIC(10,2) NOT NULL DEFAULT 0,
    handling_amount         NUMERIC(10,2) NOT NULL DEFAULT 0,
    order_status            TEXT NOT NULL CHECK (order_status IN
                                ('open', 'revised', 'partially_cancelled', 'cancelled', 'shipped')),
    cancelled_date          DATE,
    cancelled_by            TEXT
);
CREATE INDEX idx_small_account_orders_account ON raw.small_account_orders(small_account_id);
CREATE INDEX idx_small_account_orders_po_date ON raw.small_account_orders(po_date);

-- 05's line columns; units_acknowledged is NULL for the non-EDI shops (A5.20).
CREATE TABLE raw.small_account_order_lines (
    order_id                    TEXT NOT NULL REFERENCES raw.small_account_orders(order_id),
    sku                         TEXT NOT NULL REFERENCES raw.product_master(sku),
    units_originally_requested  INTEGER NOT NULL,
    units_current               INTEGER NOT NULL,
    units_acknowledged          INTEGER,
    revision_count              INTEGER NOT NULL DEFAULT 0,
    is_cancelled                BOOLEAN NOT NULL DEFAULT FALSE,
    unit_price                  NUMERIC(8,2) NOT NULL,
    line_total                  NUMERIC(10,2) NOT NULL,
    PRIMARY KEY (order_id, sku)
);

CREATE TABLE raw.small_account_shipments (
    shipment_id             TEXT PRIMARY KEY,
    order_id                TEXT NOT NULL REFERENCES raw.small_account_orders(order_id),
    ship_date               DATE NOT NULL,
    delivery_date           DATE,
    carrier                 TEXT,
    units_shipped           INTEGER NOT NULL
);
CREATE INDEX idx_small_account_shipments_order ON raw.small_account_shipments(order_id);

CREATE TABLE raw.small_account_shipment_lines (
    shipment_id                 TEXT NOT NULL REFERENCES raw.small_account_shipments(shipment_id),
    sku                         TEXT NOT NULL REFERENCES raw.product_master(sku),
    units_originally_requested  INTEGER NOT NULL,
    units_shipped               INTEGER NOT NULL,
    shortfall_reason            TEXT,
    PRIMARY KEY (shipment_id, sku)
);

CREATE TABLE raw.small_account_receipt_lines (
    shipment_id             TEXT NOT NULL,
    sku                     TEXT NOT NULL,
    units_received          INTEGER NOT NULL,
    discrepancy_reason      TEXT,
    PRIMARY KEY (shipment_id, sku),
    FOREIGN KEY (shipment_id, sku)
        REFERENCES raw.small_account_shipment_lines(shipment_id, sku)
);

-- Faire pays the brand net of its commission and processing (A3.20); direct accounts pay in full.
CREATE TABLE raw.small_account_remittances (
    remittance_id           TEXT PRIMARY KEY,
    small_account_id        TEXT NOT NULL REFERENCES raw.small_accounts(small_account_id),
    ordering_channel        TEXT NOT NULL CHECK (ordering_channel IN ('faire_marketplace', 'faire_direct', 'direct')),
    received_date           DATE NOT NULL,
    gross_amount            NUMERIC(12,2) NOT NULL,
    fees_amount             NUMERIC(10,2) NOT NULL DEFAULT 0,
    net_amount              NUMERIC(12,2) NOT NULL
);
CREATE INDEX idx_small_account_remittances_account ON raw.small_account_remittances(small_account_id);

-- N22: A11.02's 3P/FBA event types and the Faire channel-conflict complaint
-- (disaster 2), keyed to the brand's marketplace account.
CREATE TABLE raw.marketplace_events (
    event_id                TEXT PRIMARY KEY,
    marketplace_account_id  TEXT NOT NULL REFERENCES raw.marketplace_accounts(marketplace_account_id),
    event_date              DATE NOT NULL,
    event_type              TEXT NOT NULL CHECK (event_type IN
                                ('fba_lost_damaged_reimbursement', 'customer_return_refund',
                                 'buy_box_loss', 'channel_conflict_complaint')),
    sku                     TEXT REFERENCES raw.product_master(sku),
    small_account_id        TEXT REFERENCES raw.small_accounts(small_account_id),  -- the complaining shop
    amount                  NUMERIC(10,2),
    resolution              TEXT,
    notes                   TEXT
);

-- N17: the invoice between a shipment and its remittance (03:81), keyed to exactly
-- one channel's shipment, as raw.po_revisions keys exactly one channel's order (05).
CREATE TABLE raw.invoices (
    invoice_id                  TEXT PRIMARY KEY,
    retailer_shipment_id        TEXT REFERENCES raw.retailer_shipments(shipment_id),
    distributor_shipment_id     TEXT REFERENCES raw.distributor_shipments(shipment_id),
    small_account_shipment_id   TEXT REFERENCES raw.small_account_shipments(shipment_id),
    invoice_date                DATE NOT NULL,
    terms                       TEXT NOT NULL,
    due_date                    DATE NOT NULL,
    invoice_amount              NUMERIC(12,2) NOT NULL,
    CHECK (num_nonnulls(retailer_shipment_id, distributor_shipment_id, small_account_shipment_id) = 1),
    CHECK (due_date >= invoice_date)
);

-- N11: the out-of-stock flag at SKU x store x week (03:99). Which episodes were
-- planted is quarantined (U4); nothing in raw references it.
CREATE TABLE raw.store_week_oos (
    sku                     TEXT NOT NULL REFERENCES raw.product_master(sku),
    store_id                TEXT NOT NULL REFERENCES raw.stores(store_id),
    week_ending             DATE NOT NULL,
    out_of_stock            BOOLEAN NOT NULL,
    PRIMARY KEY (sku, store_id, week_ending)
);

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
-- pg_dump reads each serial's sequence: the reader's dump needs SELECT on them.
GRANT SELECT ON ALL SEQUENCES IN SCHEMA raw TO cinderhaven_reader;
