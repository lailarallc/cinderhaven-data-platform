-- Operational chargebacks (short_ship, late_delivery,
-- receiving_discrepancy) that do not join back to a triggering
-- fulfillment event. Phase 3 Group C generates every operational
-- chargeback FROM a shipment or receipt event; a row with no matching
-- event means the causal chain broke (a regression to the pre-causal
-- pattern, where operational chargebacks were independent random
-- draws).
--
-- Join rules mirror the generator (generation/seed_retailer.py,
-- generate_operational_chargebacks):
--   short_ship            -> a shorted shipment line, same retailer +
--                            SKU, chargeback month = ship month
--   late_delivery         -> a shipment delivered past the retailer
--                            MABD window (requested ship + max transit
--                            + OTIF window), same retailer, SKU on its
--                            shipped lines, chargeback month = delivery
--                            month
--   receiving_discrepancy -> a carrier_damage / quality_rejection
--                            receipt line, same retailer + SKU,
--                            chargeback month = delivery month
--
-- The MABD values mirror RETAILER_TRANSIT_DAYS (upper bound) +
-- RETAILER_OTIF_WINDOW_DAYS in generation/seed_config.py (frozen block).
-- Path A data-defect chargebacks (label_fine, damaged, pricing_error)
-- are out of scope: they are triggered by product-data defects
-- (triggered_by_field), not fulfillment events.

with operational as (
    select chargeback_id, chargeback_month, retailer_id, reason, sku
    from {{ ref('stg_retailer_chargebacks') }}
    where reason in ('short_ship', 'late_delivery', 'receiving_discrepancy')
),

mabd as (
    select * from (values
        ('RET-WALMART', 3, 0),
        ('RET-KROGER', 3, 1),
        ('RET-COSTCO', 4, 2),
        ('RET-WHOLEFOODS', 5, 1),
        ('RET-SPROUTS', 4, 1),
        ('RET-REGIONAL', 6, 2)
    ) as t (retailer_id, max_transit_days, otif_window_days)
),

short_ship_events as (
    select distinct
        o.retailer_id,
        sl.sku,
        date_trunc('month', s.ship_date)::date as event_month
    from {{ ref('stg_retailer_shipment_lines') }} sl
    inner join {{ ref('stg_retailer_shipments') }} s
        on s.shipment_id = sl.shipment_id
    inner join {{ ref('stg_retailer_orders') }} o
        on o.order_id = s.order_id
    where sl.shortfall_reason is not null
),

late_events as (
    select distinct
        o.retailer_id,
        sl.sku,
        date_trunc('month', s.delivery_date)::date as event_month
    from {{ ref('stg_retailer_shipments') }} s
    inner join {{ ref('stg_retailer_orders') }} o
        on o.order_id = s.order_id
    inner join mabd m
        on m.retailer_id = o.retailer_id
    inner join {{ ref('stg_retailer_shipment_lines') }} sl
        on sl.shipment_id = s.shipment_id
       and sl.units_shipped > 0
    where s.delivery_date is not null
      and s.delivery_date
          > o.requested_ship_date + m.max_transit_days + m.otif_window_days
),

receiving_events as (
    select distinct
        o.retailer_id,
        rl.sku,
        date_trunc('month', s.delivery_date)::date as event_month
    from {{ ref('stg_retailer_receipt_lines') }} rl
    inner join {{ ref('stg_retailer_shipments') }} s
        on s.shipment_id = rl.shipment_id
    inner join {{ ref('stg_retailer_orders') }} o
        on o.order_id = s.order_id
    where rl.discrepancy_reason in ('carrier_damage', 'quality_rejection')
      and s.delivery_date is not null
)

select op.chargeback_id, op.chargeback_month, op.retailer_id, op.reason, op.sku
from operational op
where not exists (
        select 1 from short_ship_events e
        where op.reason = 'short_ship'
          and e.retailer_id = op.retailer_id
          and e.sku = op.sku
          and e.event_month = op.chargeback_month
    )
  and not exists (
        select 1 from late_events e
        where op.reason = 'late_delivery'
          and e.retailer_id = op.retailer_id
          and e.sku = op.sku
          and e.event_month = op.chargeback_month
    )
  and not exists (
        select 1 from receiving_events e
        where op.reason = 'receiving_discrepancy'
          and e.retailer_id = op.retailer_id
          and e.sku = op.sku
          and e.event_month = op.chargeback_month
    )
