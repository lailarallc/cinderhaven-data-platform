with source as (
    select * from {{ source('raw', 'retailers') }}
)

select
    retailer_id,
    name as retailer_name,
    dispute_portal_name,
    dispute_portal_url,
    dispute_method,
    notes,
    banner_type
from source
