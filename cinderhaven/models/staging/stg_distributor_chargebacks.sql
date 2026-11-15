with source as (
    select * from {{ source('raw', 'distributor_chargebacks') }}
)

select
    chargeback_id,
    month as chargeback_month,
    distributor_id,
    reason,
    sku,
    amount as chargeback_amount,
    order_id,
    shipment_id
from source
