-- N37 (plan U8): small-account orders at SKU grain, for the marts that roll
-- channel revenue up. units_acknowledged is NULL for the non-EDI shops (A5.20).
with orders as (
    select * from {{ source('raw', 'small_account_orders') }}
),

lines as (
    select * from {{ source('raw', 'small_account_order_lines') }}
)

select
    l.order_id,
    o.small_account_id,
    o.ordering_channel,
    o.po_date,
    o.order_status,
    l.sku,
    l.units_originally_requested,
    l.units_current,
    l.units_acknowledged,
    l.is_cancelled,
    l.unit_price,
    l.line_total
from lines l
inner join orders o on l.order_id = o.order_id
