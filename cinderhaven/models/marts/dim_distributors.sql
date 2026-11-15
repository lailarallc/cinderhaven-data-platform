with distributors as (
    select * from {{ ref('stg_distributors') }}
),

sku_counts as (
    select distributor_id, count(distinct sku) as sku_count
    from {{ ref('stg_sku_distributors') }}
    group by distributor_id
),

order_summary as (
    select
        distributor_id,
        count(*) as total_orders,
        sum(total_value) as total_order_value,
        min(po_date) as first_order_date,
        max(po_date) as last_order_date
    from {{ ref('stg_distributor_orders') }}
    group by distributor_id
)

select
    d.distributor_id,
    d.distributor_name,
    d.distributor_type,
    d.margin_pct,
    d.payment_terms_days,
    d.banner_type,
    coalesce(sc.sku_count, 0) as sku_count,
    coalesce(os.total_orders, 0) as total_orders,
    coalesce(os.total_order_value, 0) as total_order_value,
    os.first_order_date,
    os.last_order_date

from distributors d
left join sku_counts sc on d.distributor_id = sc.distributor_id
left join order_summary os on d.distributor_id = os.distributor_id
