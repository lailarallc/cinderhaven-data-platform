-- Canonical value gathering — READ ONLY.
--
-- Emits `metric.basis.period|value` lines for reference/canonical_values.yml.
-- Every figure carries BOTH a basis and a period, because tools "fail" against
-- canonical when they are measuring a different window, not a different number.
--
-- PERIOD DEFINITIONS (canonical, anchored on a single data-end date):
--   cy2023        2023-01-01 .. 2023-12-31
--   cy2024        2024-01-01 .. 2024-12-31
--   cy2025        2025-01-01 .. 2025-12-31   <- THE DEFAULT for unqualified "annual"
--   trailing_12m  identical to cy2025 in this dataset
--   trailing_24m  2024-01-01 .. 2025-12-31
--   trailing_36m  2023-01-01 .. 2025-12-31
--   full          each source table's own min..max, reported per table below
--
-- Run: psql -tA -f sql/canonical_gather.sql

\pset footer off

WITH p(period, d0, d1) AS (VALUES
  ('cy2023',       DATE '2023-01-01', DATE '2023-12-31'),
  ('cy2024',       DATE '2024-01-01', DATE '2024-12-31'),
  ('cy2025',       DATE '2025-01-01', DATE '2025-12-31'),
  ('trailing_12m', DATE '2025-01-01', DATE '2025-12-31'),
  ('trailing_24m', DATE '2024-01-01', DATE '2025-12-31'),
  ('trailing_36m', DATE '2023-01-01', DATE '2025-12-31')
),
-- distinct (period, sku, store) actually scanned — precomputed once so the
-- void anti-join does not rescan 1.3M rows per period
scanned AS (
  SELECT p.period, s.sku, s.store_id
  FROM p JOIN raw.scan_data s ON s.week_ending BETWEEN p.d0 AND p.d1
  GROUP BY 1,2,3
)

-- ── REVENUE ────────────────────────────────────────────────────────
SELECT 'revenue.retail_scan.'||p.period||'|'||COALESCE(SUM(s.dollars_sold),0)::numeric(16,2)
FROM p LEFT JOIN raw.scan_data s ON s.week_ending BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'revenue.wholesale_retailer.'||p.period||'|'||COALESCE(SUM(o.total_value),0)::numeric(16,2)
FROM p LEFT JOIN raw.retailer_orders o ON o.po_date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'revenue.wholesale_distributor.'||p.period||'|'||COALESCE(SUM(o.total_value),0)::numeric(16,2)
FROM p LEFT JOIN raw.distributor_orders o ON o.po_date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'revenue.b2b_invoiced.'||p.period||'|'||(
  COALESCE((SELECT SUM(total_value) FROM raw.retailer_orders WHERE po_date BETWEEN p.d0 AND p.d1),0)
+ COALESCE((SELECT SUM(total_value) FROM raw.distributor_orders WHERE po_date BETWEEN p.d0 AND p.d1),0))::numeric(16,2)
FROM p
UNION ALL
SELECT 'revenue.dtc_gross.'||p.period||'|'||COALESCE(SUM(o.total),0)::numeric(16,2)
FROM p LEFT JOIN raw.shopify_orders o ON o.created_at::date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'revenue.combined_invoiced.'||p.period||'|'||(
  COALESCE((SELECT SUM(total_value) FROM raw.retailer_orders WHERE po_date BETWEEN p.d0 AND p.d1),0)
+ COALESCE((SELECT SUM(total_value) FROM raw.distributor_orders WHERE po_date BETWEEN p.d0 AND p.d1),0)
+ COALESCE((SELECT SUM(total) FROM raw.shopify_orders WHERE created_at::date BETWEEN p.d0 AND p.d1),0))::numeric(16,2)
FROM p
UNION ALL
SELECT 'revenue.gross_payments_retailer.'||p.period||'|'||COALESCE(SUM(r.gross_amount),0)::numeric(16,2)
FROM p LEFT JOIN raw.retailer_remittances r ON r.received_date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'revenue.gross_payments_distributor.'||p.period||'|'||COALESCE(SUM(r.gross_amount),0)::numeric(16,2)
FROM p LEFT JOIN raw.distributor_remittances r ON r.received_date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'revenue.net_collected_retailer.'||p.period||'|'||COALESCE(SUM(r.net_amount),0)::numeric(16,2)
FROM p LEFT JOIN raw.retailer_remittances r ON r.received_date BETWEEN p.d0 AND p.d1 GROUP BY p.period

-- ── VOLUME ─────────────────────────────────────────────────────────
UNION ALL
SELECT 'volume.units_scan.'||p.period||'|'||COALESCE(SUM(s.units_sold),0)::text
FROM p LEFT JOIN raw.scan_data s ON s.week_ending BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'volume.units_b2b.'||p.period||'|'||(
  COALESCE((SELECT SUM(total_units) FROM raw.retailer_orders WHERE po_date BETWEEN p.d0 AND p.d1),0)
+ COALESCE((SELECT SUM(total_units) FROM raw.distributor_orders WHERE po_date BETWEEN p.d0 AND p.d1),0))::text
FROM p
UNION ALL
SELECT 'volume.cases_b2b.'||p.period||'|'||COALESCE(ROUND(SUM(ol.units_ordered::numeric/NULLIF(pm.case_pack_qty,0)),0),0)::text
FROM p LEFT JOIN raw.retailer_orders o ON o.po_date BETWEEN p.d0 AND p.d1
       LEFT JOIN raw.retailer_order_lines ol ON ol.order_id=o.order_id
       LEFT JOIN raw.product_master pm ON pm.sku=ol.sku GROUP BY p.period
UNION ALL
SELECT 'volume.orders_b2b.'||p.period||'|'||(
  COALESCE((SELECT COUNT(*) FROM raw.retailer_orders WHERE po_date BETWEEN p.d0 AND p.d1),0)
+ COALESCE((SELECT COUNT(*) FROM raw.distributor_orders WHERE po_date BETWEEN p.d0 AND p.d1),0))::text
FROM p
UNION ALL
SELECT 'volume.orders_dtc.'||p.period||'|'||COALESCE(COUNT(o.order_id),0)::text
FROM p LEFT JOIN raw.shopify_orders o ON o.created_at::date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'volume.scan_weeks.'||p.period||'|'||COALESCE(COUNT(DISTINCT s.week_ending),0)::text
FROM p LEFT JOIN raw.scan_data s ON s.week_ending BETWEEN p.d0 AND p.d1 GROUP BY p.period

-- ── UNIVERSE ───────────────────────────────────────────────────────
UNION ALL
SELECT 'universe.skus_selling.'||p.period||'|'||COALESCE(COUNT(DISTINCT s.sku),0)::text
FROM p LEFT JOIN raw.scan_data s ON s.week_ending BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'universe.stores_selling.'||p.period||'|'||COALESCE(COUNT(DISTINCT s.store_id),0)::text
FROM p LEFT JOIN raw.scan_data s ON s.week_ending BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'universe.store_sku_pairs_selling.'||p.period||'|'||COALESCE(COUNT(DISTINCT (s.sku||'~'||s.store_id)),0)::text
FROM p LEFT JOIN raw.scan_data s ON s.week_ending BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'universe.skus_total.all_time|'||(SELECT COUNT(*) FROM raw.product_master)::text
UNION ALL
SELECT 'universe.product_lines.all_time|'||(SELECT COUNT(DISTINCT product_line) FROM raw.product_master)::text
UNION ALL
SELECT 'universe.stores_total.all_time|'||(SELECT COUNT(*) FROM raw.stores)::text
UNION ALL
SELECT 'universe.retailers.all_time|'||(SELECT COUNT(*) FROM raw.retailers)::text
UNION ALL
SELECT 'universe.distributors.all_time|'||(SELECT COUNT(*) FROM raw.distributors)::text

-- ── COST AND MARGIN ────────────────────────────────────────────────
UNION ALL
SELECT 'cogs.standard.'||p.period||'|'||COALESCE(SUM(c.units_basis*c.standard_cost_per_unit),0)::numeric(16,2)
FROM p LEFT JOIN costing.fct_product_costs c ON c.cost_period BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'cogs.manufactured_actual.'||p.period||'|'||COALESCE(SUM(c.units_basis*c.manufactured_cost_per_unit),0)::numeric(16,2)
FROM p LEFT JOIN costing.fct_product_costs c ON c.cost_period BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'cogs.loaded_actual.'||p.period||'|'||COALESCE(SUM(c.units_basis*c.fully_loaded_cost_per_unit),0)::numeric(16,2)
FROM p LEFT JOIN costing.fct_product_costs c ON c.cost_period BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'cogs.loaded_standard.'||p.period||'|'||COALESCE(SUM(c.units_basis*c.loaded_cost_at_standard),0)::numeric(16,2)
FROM p LEFT JOIN costing.fct_product_costs c ON c.cost_period BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'cost.freight_in.'||p.period||'|'||COALESCE(SUM(c.units_basis*c.freight_in_cost_per_unit),0)::numeric(16,2)
FROM p LEFT JOIN costing.fct_product_costs c ON c.cost_period BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'cost.overhead.'||p.period||'|'||COALESCE(SUM(c.units_basis*c.overhead_per_unit),0)::numeric(16,2)
FROM p LEFT JOIN costing.fct_product_costs c ON c.cost_period BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'cost.ppv.'||p.period||'|'||COALESCE(SUM(c.purchase_price_variance),0)::numeric(16,2)
FROM p LEFT JOIN costing.fct_product_costs c ON c.cost_period BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'margin.loaded_actual_pct.'||p.period||'|'||ROUND(100.0*(1 -
   COALESCE((SELECT SUM(units_basis*fully_loaded_cost_per_unit) FROM costing.fct_product_costs WHERE cost_period BETWEEN p.d0 AND p.d1),0)
 / NULLIF(COALESCE((SELECT SUM(total_value) FROM raw.retailer_orders WHERE po_date BETWEEN p.d0 AND p.d1),0)
        + COALESCE((SELECT SUM(total_value) FROM raw.distributor_orders WHERE po_date BETWEEN p.d0 AND p.d1),0)
        + COALESCE((SELECT SUM(total) FROM raw.shopify_orders WHERE created_at::date BETWEEN p.d0 AND p.d1),0),0)),2)::text
FROM p
UNION ALL
SELECT 'margin.loaded_standard_pct.'||p.period||'|'||ROUND(100.0*(1 -
   COALESCE((SELECT SUM(units_basis*loaded_cost_at_standard) FROM costing.fct_product_costs WHERE cost_period BETWEEN p.d0 AND p.d1),0)
 / NULLIF(COALESCE((SELECT SUM(total_value) FROM raw.retailer_orders WHERE po_date BETWEEN p.d0 AND p.d1),0)
        + COALESCE((SELECT SUM(total_value) FROM raw.distributor_orders WHERE po_date BETWEEN p.d0 AND p.d1),0)
        + COALESCE((SELECT SUM(total) FROM raw.shopify_orders WHERE created_at::date BETWEEN p.d0 AND p.d1),0),0)),2)::text
FROM p
UNION ALL
SELECT 'margin.ppv_pct_of_standard.'||p.period||'|'||ROUND(100.0*
   COALESCE((SELECT SUM(purchase_price_variance) FROM costing.fct_product_costs WHERE cost_period BETWEEN p.d0 AND p.d1),0)
 / NULLIF((SELECT SUM(units_basis*standard_cost_per_unit) FROM costing.fct_product_costs WHERE cost_period BETWEEN p.d0 AND p.d1),0),2)::text
FROM p

-- margin lines 1-3 are all-time (their sources carry no period dimension)
UNION ALL
SELECT 'margin.gross_at_standard_pct.all_time|'||
  (SELECT ROUND(100.0*SUM(gross_margin)/SUM(gross_revenue),2) FROM public_marts.mart_channel_contribution)::text
UNION ALL
SELECT 'margin.contribution_commercial_pct.all_time|'||
  (SELECT ROUND(100.0*SUM(contribution_margin)/SUM(gross_revenue),2) FROM public_marts.mart_channel_contribution)::text
UNION ALL
SELECT 'margin.gross_at_landed_pct.all_time|'||(
  SELECT ROUND(100.0*(1 - SUM(v.u*c.landed_cost_per_unit)/NULLIF((SELECT SUM(gross_revenue) FROM public_marts.mart_channel_contribution),0)),2)
  FROM (SELECT sku, SUM(units_basis) u FROM costing.fct_product_costs GROUP BY 1) v
  JOIN raw.sku_costs c USING (sku))::text
UNION ALL
SELECT 'margin.sku_loaded_min_pct.all_time|'||(SELECT ROUND(MIN(100.0*(1-s.c/(s.u*d.wholesale_price))),2) FROM
  (SELECT sku, SUM(units_basis*fully_loaded_cost_per_unit) c, SUM(units_basis) u FROM costing.fct_product_costs GROUP BY 1) s
  JOIN public_marts.dim_products d USING (sku) WHERE s.u>0)::text
UNION ALL
SELECT 'margin.sku_loaded_max_pct.all_time|'||(SELECT ROUND(MAX(100.0*(1-s.c/(s.u*d.wholesale_price))),2) FROM
  (SELECT sku, SUM(units_basis*fully_loaded_cost_per_unit) c, SUM(units_basis) u FROM costing.fct_product_costs GROUP BY 1) s
  JOIN public_marts.dim_products d USING (sku) WHERE s.u>0)::text

-- ── WORKING CAPITAL ────────────────────────────────────────────────
UNION ALL
SELECT 'workingcapital.avg_inventory_value.'||p.period||'|'||COALESCE((
  SELECT ROUND(AVG(v),2) FROM (SELECT snapshot_date, SUM(value_at_actual) v FROM costing.fct_inventory_snapshot
   WHERE snapshot_date BETWEEN p.d0 AND p.d1 GROUP BY 1) x),0)::text
FROM p
UNION ALL
SELECT 'workingcapital.dio_days.'||p.period||'|'||COALESCE(ROUND(
  (SELECT AVG(v) FROM (SELECT snapshot_date, SUM(value_at_actual) v FROM costing.fct_inventory_snapshot
    WHERE snapshot_date BETWEEN p.d0 AND p.d1 GROUP BY 1) x)
  / NULLIF((SELECT SUM(units_basis*fully_loaded_cost_per_unit) FROM costing.fct_product_costs
            WHERE cost_period BETWEEN p.d0 AND p.d1),0)
  * ((p.d1-p.d0)+1), 1),0)::text
FROM p
UNION ALL
SELECT 'workingcapital.dpo_days.'||p.period||'|'||COALESCE((
  SELECT ROUND(AVG(paid_date-invoice_date),1) FROM costing.fct_supplier_invoices
  WHERE invoice_date BETWEEN p.d0 AND p.d1),0)::text
FROM p
UNION ALL
SELECT 'workingcapital.dso_days.'||p.period||'|'||COALESCE((
  SELECT ROUND(SUM(o.total_value*(r.received_date-o.po_date))/NULLIF(SUM(o.total_value),0),2)
  FROM raw.retailer_orders o
  JOIN raw.retailer_remittances r ON r.retailer_id=o.retailer_id
   AND r.received_date BETWEEN (make_date(EXTRACT(YEAR FROM o.po_date)::int, EXTRACT(MONTH FROM o.po_date)::int,1)+25)
                           AND (make_date(EXTRACT(YEAR FROM o.po_date)::int, EXTRACT(MONTH FROM o.po_date)::int,1)+55)
  WHERE o.po_date BETWEEN p.d0 AND p.d1),0)::text
FROM p

-- ── DEDUCTIONS AND TRADE ───────────────────────────────────────────
UNION ALL
SELECT 'deductions.retailer_total.'||p.period||'|'||COALESCE(SUM(d.amount),0)::numeric(16,2)
FROM p LEFT JOIN raw.retailer_deductions d ON d.deduction_date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'deductions.retailer_rows.'||p.period||'|'||COALESCE(COUNT(d.deduction_id),0)::text
FROM p LEFT JOIN raw.retailer_deductions d ON d.deduction_date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'deductions.distributor_total.'||p.period||'|'||COALESCE(SUM(d.amount),0)::numeric(16,2)
FROM p LEFT JOIN raw.distributor_deductions d ON d.deduction_date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'deductions.promo_billback.'||p.period||'|'||COALESCE(SUM(d.amount) FILTER (WHERE d.deduction_type='promo_billback'),0)::numeric(16,2)
FROM p LEFT JOIN raw.retailer_deductions d ON d.deduction_date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'deductions.operational_waste_ex_billback.'||p.period||'|'||COALESCE(SUM(d.amount) FILTER (WHERE d.deduction_type<>'promo_billback'),0)::numeric(16,2)
FROM p LEFT JOIN raw.retailer_deductions d ON d.deduction_date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'trade.structural_allowance.'||p.period||'|'||COALESCE(SUM(r.trade_allowance),0)::numeric(16,2)
FROM p LEFT JOIN raw.retailer_remittances r ON r.received_date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'trade.promotional_spend.'||p.period||'|'||COALESCE(SUM(pr.promo_cost),0)::numeric(16,2)
FROM p LEFT JOIN raw.promotions pr ON pr.start_week BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'chargebacks.retailer_amount.'||p.period||'|'||COALESCE(SUM(cb.amount),0)::numeric(16,2)
FROM p LEFT JOIN raw.retailer_chargebacks cb ON cb.month::date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'chargebacks.retailer_count.'||p.period||'|'||COALESCE(COUNT(cb.chargeback_id),0)::text
FROM p LEFT JOIN raw.retailer_chargebacks cb ON cb.month::date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'chargebacks.retailer_count.all_time|'||(SELECT COUNT(*) FROM raw.retailer_chargebacks)::text
UNION ALL
SELECT 'chargebacks.distributor_count.all_time|'||(SELECT COUNT(*) FROM raw.distributor_chargebacks)::text
UNION ALL
SELECT 'recoveries.retailer_amount.'||p.period||'|'||COALESCE((SELECT SUM(recovered_amount) FROM raw.retailer_disputes
  WHERE filed_date BETWEEN p.d0 AND p.d1),0)::numeric(16,2) FROM p

-- ── DISTRIBUTION ───────────────────────────────────────────────────
UNION ALL
SELECT 'distribution.authorizations.'||p.period||'|'||COALESCE(COUNT(dl.sku),0)::text
FROM p LEFT JOIN raw.distribution_log dl ON dl.authorized_date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'distribution.deauthorizations.'||p.period||'|'||COALESCE(COUNT(dl.sku),0)::text
FROM p LEFT JOIN raw.distribution_log dl ON dl.deauthorized_date BETWEEN p.d0 AND p.d1 GROUP BY p.period
UNION ALL
SELECT 'distribution.authorized_store_skus_active.'||p.period||'|'||(
  SELECT COUNT(*) FROM raw.distribution_log
  WHERE authorized_date <= p.d1 AND (deauthorized_date IS NULL OR deauthorized_date > p.d1))::text
FROM p
UNION ALL
-- VOID (distribution proxy; NOT ACV — true ACV needs all-commodity store volume,
-- which is not in this warehouse). A void = a store-SKU pair authorized at any
-- point DURING the period that recorded no scan in the period. The correlated
-- subquery is anchored on p, so every period emits a value including 0 (absent
-- and zero must never look alike).
SELECT 'distribution.voids_authorized_not_scanned.'||p.period||'|'||(
  SELECT COUNT(*) FROM raw.distribution_log dl
  LEFT JOIN scanned sc ON sc.period=p.period AND sc.sku=dl.sku AND sc.store_id=dl.store_id
  WHERE dl.authorized_date <= p.d1 AND (dl.deauthorized_date IS NULL OR dl.deauthorized_date >= p.d0)
    AND sc.sku IS NULL)::text
FROM p
UNION ALL
-- DEFECT FIX: denominator is now pairs authorized DURING the period (overlap),
-- a superset of pairs that sold, so the ratio cannot exceed 100%. The previous
-- "authorized at period end" denominator excluded pairs sold-then-deauthorized,
-- producing 103-105% readings.
SELECT 'distribution.pct_authorized_selling.'||p.period||'|'||ROUND(100.0*
  (SELECT COUNT(*) FROM scanned sc WHERE sc.period=p.period)
 / NULLIF((SELECT COUNT(*) FROM raw.distribution_log dl
   WHERE dl.authorized_date <= p.d1 AND (dl.deauthorized_date IS NULL OR dl.deauthorized_date >= p.d0)),0)::numeric,2)::text
FROM p

ORDER BY 1;

-- ── DATA WINDOWS (the empty-tab defect class) ──────────────────────
\echo '--- DATA WINDOWS ---'
SELECT 'window.scan_data|'||MIN(week_ending)||'|'||MAX(week_ending)||'|'||COUNT(*) FROM raw.scan_data
UNION ALL SELECT 'window.promotions|'||MIN(start_week)||'|'||MAX(end_week)||'|'||COUNT(*) FROM raw.promotions
UNION ALL SELECT 'window.distribution_authorized|'||MIN(authorized_date)||'|'||MAX(authorized_date)||'|'||COUNT(*) FROM raw.distribution_log
UNION ALL SELECT 'window.distribution_deauthorized|'||MIN(deauthorized_date)||'|'||MAX(deauthorized_date)||'|'||COUNT(deauthorized_date) FROM raw.distribution_log
UNION ALL SELECT 'window.retailer_orders|'||MIN(po_date)||'|'||MAX(po_date)||'|'||COUNT(*) FROM raw.retailer_orders
UNION ALL SELECT 'window.distributor_orders|'||MIN(po_date)||'|'||MAX(po_date)||'|'||COUNT(*) FROM raw.distributor_orders
UNION ALL SELECT 'window.shopify_orders|'||MIN(created_at::date)||'|'||MAX(created_at::date)||'|'||COUNT(*) FROM raw.shopify_orders
UNION ALL SELECT 'window.retailer_deductions|'||MIN(deduction_date)||'|'||MAX(deduction_date)||'|'||COUNT(*) FROM raw.retailer_deductions
UNION ALL SELECT 'window.distributor_deductions|'||MIN(deduction_date)||'|'||MAX(deduction_date)||'|'||COUNT(*) FROM raw.distributor_deductions
UNION ALL SELECT 'window.retailer_remittances|'||MIN(received_date)||'|'||MAX(received_date)||'|'||COUNT(*) FROM raw.retailer_remittances
UNION ALL SELECT 'window.distributor_remittances|'||MIN(received_date)||'|'||MAX(received_date)||'|'||COUNT(*) FROM raw.distributor_remittances
UNION ALL SELECT 'window.retailer_chargebacks|'||MIN(month::date)||'|'||MAX(month::date)||'|'||COUNT(*) FROM raw.retailer_chargebacks
UNION ALL SELECT 'window.retailer_disputes|'||MIN(filed_date)||'|'||MAX(filed_date)||'|'||COUNT(*) FROM raw.retailer_disputes
UNION ALL SELECT 'window.costing_product_costs|'||MIN(cost_period)||'|'||MAX(cost_period)||'|'||COUNT(*) FROM costing.fct_product_costs
UNION ALL SELECT 'window.costing_inventory_snapshot|'||MIN(snapshot_date)||'|'||MAX(snapshot_date)||'|'||COUNT(*) FROM costing.fct_inventory_snapshot
UNION ALL SELECT 'window.costing_supplier_invoices|'||MIN(invoice_date)||'|'||MAX(invoice_date)||'|'||COUNT(*) FROM costing.fct_supplier_invoices
-- THE THREE DATA TAILS — "end of data" is not one date. A cross-table query
-- that assumes a single max date will silently drop whichever table extends
-- past it. Name all three explicitly.
UNION ALL SELECT 'window.tail_scan|'||MAX(week_ending)||'||' FROM raw.scan_data
UNION ALL SELECT 'window.tail_orders|'||GREATEST(
   (SELECT MAX(po_date) FROM raw.retailer_orders),
   (SELECT MAX(po_date) FROM raw.distributor_orders),
   (SELECT MAX(created_at::date) FROM raw.shopify_orders))||'||'
UNION ALL SELECT 'window.tail_supplier_invoices|'||MAX(invoice_date)||'||' FROM costing.fct_supplier_invoices
ORDER BY 1;

-- ── PRODUCERS FOLDED IN BY U19 (2026-11-15) ─────────────────────────
-- Each key below was in canonical_values.yml with no producer here. Folded
-- in so verify_canonical.py compares every numeric key to the world.
--   price_history.*    counts, as observed 2026-08-01.
--   revenue.retail_scan.ttm_through_2025_12_27
--                      week_ending > MAX(week_ending) - 365 days (53 buckets).
--   trade.*            check_canonical.py's definitions: structural = each
--                      contracted retailer's trailing-52-week scan revenue at
--                      its average raw.sku_costs rate; operational waste =
--                      every non-promo_billback deduction, retailer and
--                      distributor, over the 36-month corpus, divided by 3
--                      (stored under the label trailing_365d).
--   fulfillment.*      otif-blind-spot's scoring (scripts/02_export_json.py):
--                      periods by po_date; on time = delivery_date <=
--                      requested_ship_date + the retailer's MABD days
--                      (otif_config.py), else is_on_time; in full = units
--                      received >= units ordered, received falling back to
--                      shipped and ordered to the PO's total_units when the
--                      line aggregate is missing or zero; each rate rounded
--                      to four places, then x100.
--   Not produced, and so failing verify_canonical.py until a producer is
--   named: trade.all_in_total.trailing_36m (3 x the annual all-in gives
--   10669827.87 against the yml's .88; no definition tried reproduces it) and
--   revenue.defect_sku_ttm (PDHA's R validators define the 27-SKU set).
WITH fp(period, d0, d1) AS (VALUES
  ('cy2023',       DATE '2023-01-01', DATE '2023-12-31'),
  ('cy2024',       DATE '2024-01-01', DATE '2024-12-31'),
  ('cy2025',       DATE '2025-01-01', DATE '2025-12-31'),
  ('trailing_12m', DATE '2025-01-01', DATE '2025-12-31'),
  ('trailing_24m', DATE '2024-01-01', DATE '2025-12-31'),
  ('trailing_36m', DATE '2023-01-01', DATE '2025-12-31'),
  ('full_corpus',  DATE '1900-01-01', DATE '2999-12-31')
),
mabd(retailer_id, days) AS (VALUES
  ('RET-WALMART', 3), ('RET-KROGER', 4), ('RET-COSTCO', 6), ('RET-WHOLEFOODS', 6), ('RET-SPROUTS', 5),
  ('RET-REGIONAL', 8)
),
sl AS (SELECT shipment_id, SUM(units_ordered) uo, SUM(units_shipped) us
       FROM public_marts.fct_retailer_shipment_lines GROUP BY 1),
rl AS (SELECT shipment_id, SUM(units_received) ur FROM public_marts.fct_retailer_receipt_lines GROUP BY 1),
ship AS (
  SELECT s.retailer_id, o.po_date,
         COALESCE(NULLIF(sl.uo, 0), NULLIF(o.total_units, 0), 0) AS uo,
         COALESCE(sl.us, 0) AS us,
         COALESCE(NULLIF(rl.ur, 0), COALESCE(sl.us, 0)) AS ur,
         CASE WHEN s.requested_ship_date IS NOT NULL AND s.delivery_date IS NOT NULL
              THEN s.delivery_date <= s.requested_ship_date + COALESCE(m.days, 5)
              ELSE COALESCE(s.is_on_time, false) END AS on_time
  FROM public_marts.fct_retailer_shipments s
  JOIN public_marts.fct_retailer_orders o ON o.order_id = s.order_id
  LEFT JOIN sl ON sl.shipment_id = s.shipment_id
  LEFT JOIN rl ON rl.shipment_id = s.shipment_id
  LEFT JOIN mabd m ON m.retailer_id = s.retailer_id
),
scored AS (SELECT *, (uo <= 0 OR ur >= uo) AS in_full FROM ship),
f AS (
  SELECT fp.period,
         ROUND(SUM(sc.us)::numeric / NULLIF(SUM(sc.uo), 0), 4) AS fill,
         ROUND(AVG((sc.on_time AND sc.in_full)::int) FILTER (WHERE sc.retailer_id = 'RET-WALMART'), 4) AS otif_wm,
         ROUND(AVG(sc.on_time::int) FILTER (WHERE sc.retailer_id = 'RET-WALMART'), 4) AS ot_wm,
         ROUND(AVG(sc.in_full::int) FILTER (WHERE sc.retailer_id = 'RET-WALMART'), 4) AS if_wm,
         ROUND(AVG((sc.on_time AND sc.in_full)::int), 4) AS otif_all,
         COUNT(*) FILTER (WHERE sc.retailer_id = 'RET-WALMART') AS n_wm,
         COUNT(*) AS n_all
  FROM fp JOIN scored sc ON sc.po_date BETWEEN fp.d0 AND fp.d1
  GROUP BY fp.period
),
w AS (SELECT DISTINCT week_ending FROM raw.scan_data ORDER BY week_ending DESC LIMIT 52),
rev52 AS (SELECT r.name, SUM(sd.dollars_sold) AS rev
          FROM raw.scan_data sd JOIN raw.stores st ON st.store_id = sd.store_id
          JOIN raw.retailers r ON r.retailer_id = st.retailer_id
          WHERE sd.week_ending >= (SELECT MIN(week_ending) FROM w) GROUP BY r.name),
rate AS (SELECT AVG(trade_spend_pct_walmart) wm, AVG(trade_spend_pct_costco) co, AVG(trade_spend_pct_whole_foods) wf,
                AVG(trade_spend_pct_sprouts) sp, AVG(trade_spend_pct_kroger) kr, AVG(trade_spend_pct_regional) rg
         FROM raw.sku_costs),
tr AS (
  SELECT (SELECT SUM(rev) FROM rev52) AS rev,
         (SELECT SUM(rev52.rev * CASE rev52.name WHEN 'Walmart' THEN rate.wm WHEN 'Costco' THEN rate.co
                 WHEN 'Whole Foods' THEN rate.wf WHEN 'Sprouts' THEN rate.sp WHEN 'Kroger' THEN rate.kr
                 WHEN 'Regional Group' THEN rate.rg END) FROM rev52, rate) AS struct,
         ((SELECT COALESCE(SUM(amount), 0) FROM raw.retailer_deductions WHERE deduction_type != 'promo_billback')
        + (SELECT COALESCE(SUM(amount), 0) FROM raw.distributor_deductions WHERE deduction_type != 'promo_billback'))
          / 3.0 AS waste
)
SELECT 'price_history.row_count|'||(SELECT COUNT(*) FROM raw.price_history)::text
UNION ALL
SELECT 'price_history.baseline.rows|'||(SELECT COUNT(*) FROM raw.price_history WHERE effective_date = DATE '2023-01-01')::text
UNION ALL
SELECT 'revenue.retail_scan.ttm_through_2025_12_27|'||(
  SELECT SUM(dollars_sold) FROM raw.scan_data
  WHERE week_ending > (SELECT MAX(week_ending) FROM raw.scan_data) - 365)::numeric(16,2)
UNION ALL SELECT 'trade.structural_annual.trailing_52w|'||ROUND(struct, 2)::text FROM tr
UNION ALL SELECT 'trade.op_waste_annual.trailing_365d|'||ROUND(waste, 2)::text FROM tr
UNION ALL SELECT 'trade.all_in_annual.trailing_52w|'||ROUND(struct + waste, 2)::text FROM tr
UNION ALL SELECT 'trade.structural_rate_pct.trailing_52w|'||ROUND(100 * struct / rev, 2)::text FROM tr
UNION ALL SELECT 'trade.op_waste_rate_pct.trailing_52w|'||ROUND(100 * waste / rev, 2)::text FROM tr
UNION ALL SELECT 'trade.all_in_rate_pct.trailing_52w|'||ROUND(100 * (struct + waste) / rev, 2)::text FROM tr
UNION ALL SELECT 'fulfillment.fill_rate_internal_pct.'||period||'|'||(100 * fill)::numeric(6,2)::text FROM f
UNION ALL SELECT 'fulfillment.otif_walmart_pct.'||period||'|'||(100 * otif_wm)::numeric(6,2)::text FROM f
UNION ALL SELECT 'fulfillment.on_time_walmart_pct.'||period||'|'||(100 * ot_wm)::numeric(6,2)::text FROM f
UNION ALL SELECT 'fulfillment.in_full_walmart_pct.'||period||'|'||(100 * if_wm)::numeric(6,2)::text FROM f
UNION ALL SELECT 'fulfillment.otif_portfolio_pct.'||period||'|'||(100 * otif_all)::numeric(6,2)::text FROM f
UNION ALL SELECT 'fulfillment.gap_walmart_pts.'||period||'|'||(100 * (fill - otif_wm))::numeric(6,2)::text FROM f
UNION ALL SELECT 'fulfillment.shipments.walmart_full_corpus|'||n_wm::text FROM f WHERE period = 'full_corpus'
UNION ALL SELECT 'fulfillment.shipments.all_retailers_full_corpus|'||n_all::text FROM f WHERE period = 'full_corpus'
;

-- ── CANON KEYS FOR TYPED FIGURES (U19, 2026-11-15) ──────────────────
-- Figures consumers print that had no key: the all-time retailer
-- deduction total and count (held only in a data_windows string), the
-- cross-channel deduction backlog and count (int_all_deductions, as
-- retailer-deduction-recovery prints them), and the payment lifecycle in
-- cents per invoiced dollar (net / gross remitted x100; retailer,
-- distributor, and the two combined). Each data_windows row count is also
-- a figure: verify_canonical.py reads it from that table's window line as
-- rows.<table>.all_time.
SELECT 'deductions.retailer_total.all_time|'||(SELECT SUM(amount) FROM raw.retailer_deductions)::numeric(16,2)
UNION ALL
SELECT 'deductions.retailer_rows.all_time|'||(SELECT COUNT(*) FROM raw.retailer_deductions)::text
UNION ALL
SELECT 'deductions.cross_channel_total.all_time|'||(SELECT SUM(deduction_amount) FROM public_intermediate.int_all_deductions)::numeric(16,2)
UNION ALL
SELECT 'deductions.cross_channel_rows.all_time|'||(SELECT COUNT(*) FROM public_intermediate.int_all_deductions)::text
UNION ALL
SELECT 'lifecycle.retailer_cents_per_dollar.all_time|'||
  (SELECT ROUND(100.0 * SUM(net_amount) / SUM(gross_amount), 2) FROM public_marts.fct_retailer_payments)::text
UNION ALL
SELECT 'lifecycle.distributor_cents_per_dollar.all_time|'||
  (SELECT ROUND(100.0 * SUM(net_amount) / SUM(gross_amount), 2) FROM public_marts.fct_distributor_payments)::text
UNION ALL
SELECT 'lifecycle.wholesale_cents_per_dollar.all_time|'||(SELECT ROUND(100.0 *
  ((SELECT SUM(net_amount) FROM public_marts.fct_retailer_payments) + (SELECT SUM(net_amount) FROM public_marts.fct_distributor_payments))
  / ((SELECT SUM(gross_amount) FROM public_marts.fct_retailer_payments) + (SELECT SUM(gross_amount) FROM public_marts.fct_distributor_payments)), 2))::text
;
