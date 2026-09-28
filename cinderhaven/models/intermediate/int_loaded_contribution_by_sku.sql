-- Grain: one row per SKU (retailer channel only, 2024-2027 window)
-- Full loaded contribution = gross_revenue minus COGS, trade spend,
-- chargebacks, and prorated deductions.
-- COGS formula: units_ordered * cogs_per_unit. units_ordered is already in
-- units (priced per unit at order-line generation); multiplying by
-- case_pack_qty inflated COGS 6-24x per SKU. Same fix as a6b4d20 in
-- mart_channel_contribution.

with order_lines as (
    select
        ol.order_id,
        ol.sku,
        ol.units_ordered,
        ol.line_total,
        o.retailer_id
    from {{ ref('stg_retailer_order_lines') }} ol
    inner join {{ ref('stg_retailer_orders') }} o on ol.order_id = o.order_id
),

product_master as (
    select sku, product_line
    from {{ ref('stg_product_master') }}
),

sku_costs as (
    select sku, cogs_per_unit
    from {{ ref('stg_sku_costs') }}
),

-- Actual promo events are the authoritative trade spend source
trade_spend as (
    select
        sku,
        sum(promo_cost) as total_promo_cost
    from {{ ref('stg_promotions') }}
    group by sku
),

chargebacks as (
    select
        sku,
        sum(chargeback_amount) as total_chargebacks
    from {{ ref('stg_retailer_chargebacks') }}
    group by sku
),

-- Prorate order-level deductions to SKUs by each SKU's revenue share in the order
order_revenue_shares as (
    select
        order_id,
        sku,
        line_total,
        sum(line_total) over (partition by order_id) as order_total
    from {{ ref('stg_retailer_order_lines') }}
),

allocated_deductions as (
    select
        r.sku,
        sum(
            d.deduction_amount
            * (r.line_total / nullif(r.order_total, 0))
        ) as total_allocated_deductions
    from order_revenue_shares r
    inner join {{ ref('stg_retailer_deductions') }} d on r.order_id = d.order_id
    group by r.sku
),

revenue_by_sku as (
    select
        sku,
        -- holds units, not cases (the column name is historical)
        sum(units_ordered)                               as total_cases_ordered,
        sum(line_total)                                  as gross_revenue
    from order_lines
    group by sku
)

select
    r.sku,
    pm.product_line,
    r.total_cases_ordered,
    r.gross_revenue,

    -- COGS: units ordered × cost per unit
    r.total_cases_ordered * sc.cogs_per_unit                            as total_cogs,

    coalesce(ts.total_promo_cost, 0)                                    as trade_spend,
    coalesce(cb.total_chargebacks, 0)                                   as total_chargebacks,
    coalesce(ad.total_allocated_deductions, 0)                          as allocated_deductions,

    -- Loaded contribution
    r.gross_revenue
        - (r.total_cases_ordered * sc.cogs_per_unit)
        - coalesce(ts.total_promo_cost, 0)
        - coalesce(cb.total_chargebacks, 0)
        - coalesce(ad.total_allocated_deductions, 0)                    as loaded_contribution,

    -- Per-unit loaded contribution (per individual unit sold, not per case)
    case
        when r.total_cases_ordered > 0
        then round((
            r.gross_revenue
                - (r.total_cases_ordered * sc.cogs_per_unit)
                - coalesce(ts.total_promo_cost, 0)
                - coalesce(cb.total_chargebacks, 0)
                - coalesce(ad.total_allocated_deductions, 0)
        )::numeric / (r.total_cases_ordered), 4)
        else null
    end                                                                  as loaded_contribution_per_unit,

    -- Margin rate for scoring percentile calibration
    case
        when r.gross_revenue > 0
        then round((
            r.gross_revenue
                - (r.total_cases_ordered * sc.cogs_per_unit)
                - coalesce(ts.total_promo_cost, 0)
                - coalesce(cb.total_chargebacks, 0)
                - coalesce(ad.total_allocated_deductions, 0)
        )::numeric / r.gross_revenue, 4)
        else null
    end                                                                  as loaded_margin_pct

from revenue_by_sku r
inner join product_master pm on r.sku = pm.sku
inner join sku_costs sc      on r.sku = sc.sku
left join  trade_spend ts    on r.sku = ts.sku
left join  chargebacks cb    on r.sku = cb.sku
left join  allocated_deductions ad on r.sku = ad.sku
