with retailers as (
    select * from {{ ref('stg_retailers') }}
),

distributors as (
    select * from {{ ref('stg_distributors') }}
)

select
    retailer_id as partner_id,
    retailer_name as name,
    'retailer' as channel_type,
    banner_type,
    dispute_portal_name,
    dispute_portal_url,
    dispute_method,
    notes
from retailers

union all

select
    distributor_id as partner_id,
    distributor_name as name,
    'distributor' as channel_type,
    banner_type,
    null as dispute_portal_name,
    null as dispute_portal_url,
    null as dispute_method,
    null as notes
from distributors
