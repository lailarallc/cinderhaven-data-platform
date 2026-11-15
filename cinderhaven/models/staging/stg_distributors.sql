with source as (
    select * from {{ source('raw', 'distributors') }}
)

select
    distributor_id,
    name as distributor_name,
    type as distributor_type,
    margin_pct,
    payment_terms_days,
    banner_type
from source
