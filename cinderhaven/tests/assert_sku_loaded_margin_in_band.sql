-- SKUs whose fully loaded margin falls outside the plausible band for a
-- specialty food SKU (-50% to +90% of gross revenue).
--
-- Exists because int_loaded_contribution_by_sku multiplied order-line
-- units by case_pack_qty until 2026-09-28, inflating COGS 6-24x per SKU:
-- every SKU read -246% to -934% loaded margin and all structural tests
-- passed. The same bug in mart_channel_contribution was found by the
-- plausibility audit, fixed in a6b4d20, and guarded afterward by
-- assert_channel_contribution_margin_in_band (8c41c84). This test guards
-- the per-SKU model the same way.
--
-- The band is wide on purpose: a loss-making SKU after trade spend and
-- deductions is plausible; losing more than half its revenue is not.

select
    sku,
    gross_revenue,
    total_cogs,
    loaded_contribution,
    loaded_margin_pct
from {{ ref('int_loaded_contribution_by_sku') }}
where loaded_margin_pct is not null
  and (
      loaded_margin_pct < -0.50
      or loaded_margin_pct > 0.90
  )
