with retailers as (
    select * from {{ ref('stg_retailers') }}
),

store_counts as (
    select retailer_id, count(*) as store_count
    from {{ ref('stg_stores') }}
    group by retailer_id
),

order_summary as (
    select
        retailer_id,
        count(*) as total_orders,
        sum(total_value) as total_order_value,
        min(po_date) as first_order_date,
        max(po_date) as last_order_date
    from {{ ref('stg_retailer_orders') }}
    group by retailer_id
)

select
    r.retailer_id,
    r.retailer_name,
    r.dispute_portal_name,
    r.dispute_portal_url,
    r.dispute_method,
    r.banner_type,
    coalesce(sc.store_count, 0) as store_count,
    coalesce(os.total_orders, 0) as total_orders,
    coalesce(os.total_order_value, 0) as total_order_value,
    os.first_order_date,
    os.last_order_date

from retailers r
left join store_counts sc on r.retailer_id = sc.retailer_id
left join order_summary os on r.retailer_id = os.retailer_id
