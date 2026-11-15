-- N22 (plan U8): one row per Amazon charge by fee type, for
-- mart_channel_contribution's Amazon row. order_id is set on per-order fees only.
with source as (
    select * from {{ source('raw', 'amazon_fees') }}
)

select
    fee_id,
    marketplace_account_id,
    order_id,
    fee_type,
    fee_date,
    amount as fee_amount
from source
