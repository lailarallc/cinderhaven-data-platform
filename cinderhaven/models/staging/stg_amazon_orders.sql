-- N22 (plan U8): Amazon orders at SKU grain, for the costing bases and the marts
-- that roll channel revenue up.
with orders as (
    select * from {{ source('raw', 'amazon_orders') }}
),

lines as (
    select * from {{ source('raw', 'amazon_order_lines') }}
)

select
    l.order_id,
    o.marketplace_account_id,
    o.order_date,
    l.sku,
    l.quantity,
    l.unit_price,
    l.line_total
from lines l
inner join orders o on l.order_id = o.order_id
