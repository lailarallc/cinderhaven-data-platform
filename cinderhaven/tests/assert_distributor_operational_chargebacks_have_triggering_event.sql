-- Distributor operational chargebacks (short_ship, late_delivery)
-- that do not join back to a triggering fulfillment event. Phase 3
-- Group C2 generates every distributor operational chargeback FROM a
-- shipment event; a row with no matching event means the causal chain
-- broke (a regression to the pre-causal pattern, where operational
-- chargebacks were independent random draws).
--
-- Join rules mirror the generator (generation/seed_distributor.py,
-- generate_operational_chargebacks):
--   short_ship    -> a shorted shipment line, same distributor + SKU,
--                    chargeback month = ship month
--   late_delivery -> a shipment delivered beyond the order-to-door
--                    window (po_date + 12 days; distributor orders
--                    carry no requested_ship_date, so the window is
--                    the observable MABD analog), same distributor,
--                    SKU on its shipped lines, chargeback month =
--                    delivery month
--
-- The 12-day window mirrors DIST_DELIVERY_WINDOW_DAYS in
-- generation/seed_config.py (frozen block). There is no
-- receiving_discrepancy category on this channel (design §1.6: no
-- receipt lines — distributor discrepancies arrive via deductions).
-- The kept quality-linked chargebacks (damaged, pricing_error) are out
-- of scope: they are quality-weighted legacy draws, not fulfillment
-- events.

with operational as (
    select chargeback_id, chargeback_month, distributor_id, reason, sku
    from {{ ref('stg_distributor_chargebacks') }}
    where reason in ('short_ship', 'late_delivery')
),

short_ship_events as (
    select distinct
        o.distributor_id,
        sl.sku,
        date_trunc('month', s.ship_date)::date as event_month
    from {{ ref('stg_distributor_shipment_lines') }} sl
    inner join {{ ref('stg_distributor_shipments') }} s
        on s.shipment_id = sl.shipment_id
    inner join {{ ref('stg_distributor_orders') }} o
        on o.order_id = s.order_id
    where sl.shortfall_reason is not null
),

late_events as (
    select distinct
        o.distributor_id,
        sl.sku,
        date_trunc('month', s.delivery_date)::date as event_month
    from {{ ref('stg_distributor_shipments') }} s
    inner join {{ ref('stg_distributor_orders') }} o
        on o.order_id = s.order_id
    inner join {{ ref('stg_distributor_shipment_lines') }} sl
        on sl.shipment_id = s.shipment_id
       and sl.units_shipped > 0
    where s.delivery_date is not null
      and s.delivery_date > o.po_date + 12
)

select op.chargeback_id, op.chargeback_month, op.distributor_id, op.reason, op.sku
from operational op
where not exists (
        select 1 from short_ship_events e
        where op.reason = 'short_ship'
          and e.distributor_id = op.distributor_id
          and e.sku = op.sku
          and e.event_month = op.chargeback_month
    )
  and not exists (
        select 1 from late_events e
        where op.reason = 'late_delivery'
          and e.distributor_id = op.distributor_id
          and e.sku = op.sku
          and e.event_month = op.chargeback_month
    )
