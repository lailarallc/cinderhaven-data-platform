with chargebacks as (
    select * from {{ ref('stg_retailer_chargebacks') }}
),

retailers as (
    select retailer_id, retailer_name, banner_type from {{ ref('stg_retailers') }}
)

select
    cb.chargeback_id,
    cb.sku,
    r.retailer_name as retailer,
    r.banner_type,
    cb.chargeback_amount as amount,
    cb.reason,
    to_char(cb.chargeback_month, 'YYYY-MM') as month,
    cb.triggered_by_field

from chargebacks cb
inner join retailers r on cb.retailer_id = r.retailer_id
