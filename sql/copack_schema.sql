-- copack: the co-packer tables (plan U2), ported from production-demand-forecast's
-- db/schema_copack.sql, same columns in the same order.
--
-- TABLE-SCOPED. The schema is created if absent and never dropped: that repo
-- writes its own forecast snapshot tables into copack (db/precompute_forecast.py),
-- which this file neither creates nor drops. Only the five tables below are
-- dropped and recreated.
--
-- Demo reference date: 2025-11-01. Line A (shared): Artisan Sauces + top 5
-- Specialty Condiments. Line B (dedicated): the rest.
CREATE SCHEMA IF NOT EXISTS copack;

DROP TABLE IF EXISTS copack.co_packers, copack.production_lines, copack.sku_production_config,
                     copack.production_schedule, copack.sku_inventory;

-- One Cinderhaven co-packer.
CREATE TABLE copack.co_packers (
    co_packer_id   TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    location       TEXT,
    notes          TEXT
);

-- Two lines at the co-packer facility.
CREATE TABLE copack.production_lines (
    line_id                TEXT PRIMARY KEY,
    co_packer_id           TEXT NOT NULL,
    line_name              TEXT NOT NULL,
    product_line_affinity  TEXT,
    notes                  TEXT
);

-- One row per SKU: which line, lead time, minimum run.
CREATE TABLE copack.sku_production_config (
    sku              TEXT PRIMARY KEY,
    line_id          TEXT NOT NULL,
    lead_time_weeks  INTEGER NOT NULL,
    min_run_cases    INTEGER NOT NULL,
    notes            TEXT
);

-- Booked production runs. scheduled_week is an ISO date string.
CREATE TABLE copack.production_schedule (
    run_id           TEXT PRIMARY KEY,
    sku              TEXT NOT NULL,
    line_id          TEXT NOT NULL,
    scheduled_week   TEXT NOT NULL,
    quantity_cases   INTEGER NOT NULL,
    status           TEXT NOT NULL DEFAULT 'booked'
);

-- On-hand inventory as of 2025-11-01, calibrated for the forecast's stockout story.
CREATE TABLE copack.sku_inventory (
    sku           TEXT PRIMARY KEY,
    as_of_date    TEXT NOT NULL,
    on_hand_cases INTEGER NOT NULL DEFAULT 0,
    notes         TEXT
);

-- Grants travel with the DDL (plan U4; roles in sql/truth_roles.sql). Dropping
-- a table takes its grants with it, so every rebuild restates them on the five
-- tables it recreated: the generator owns them; dbt, the reader and the
-- validator read them. The schema's owner is not changed (writer repos keep
-- writing their own tables; owner, 2026-11-11).
ALTER TABLE copack.co_packers OWNER TO cinderhaven_generator;
ALTER TABLE copack.production_lines OWNER TO cinderhaven_generator;
ALTER TABLE copack.sku_production_config OWNER TO cinderhaven_generator;
ALTER TABLE copack.production_schedule OWNER TO cinderhaven_generator;
ALTER TABLE copack.sku_inventory OWNER TO cinderhaven_generator;
GRANT USAGE ON SCHEMA copack TO cinderhaven_dbt, cinderhaven_reader, cinderhaven_validator;
GRANT SELECT ON copack.co_packers, copack.production_lines, copack.sku_production_config,
                copack.production_schedule, copack.sku_inventory
    TO cinderhaven_dbt, cinderhaven_reader, cinderhaven_validator;
