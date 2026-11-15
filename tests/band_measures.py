"""What every band test measured, at every run seed (owner, 2026-11-14).

A band test passes or fails; U7 needs the value it tested. Each entry below
measures what one band test measures, one row per key (a tier, a channel, a
partner, a SKU, or the whole world), with that key's band as the test types it
today. The multi-seed runner saves these rows for every seed whose models built,
including a seed whose dbt tests failed, so U7 can restate each seed-0-tuned
band from its spread across the 30 seeds (spec:DECISIONS#u2-guard-trips).

Each query restates its test's arithmetic; `tests/test_band_measures.py` pins
that every band test has an entry and, on the harness, that the keys out of
band here are exactly the rows the test itself returns.
"""
from __future__ import annotations

# name -> (the test it measures, SQL returning key, value, lo, hi)
MEASURES: dict[str, tuple[str, str]] = {
    "dispute_recovery_rate": ("cinderhaven/tests/assert_dispute_recovery_rates_in_band.sql", """
        with curve(tier, expected_rate) as (values ('strong', 0.65), ('moderate', 0.27), ('weak', 0.13)),
        disputed as (
            select disp.evidence_quality, disp.recovered_amount, ded.deduction_amount
            from public_staging.stg_retailer_disputes disp
            join public_staging.stg_retailer_deductions ded on ded.deduction_id = disp.deduction_id
            union all
            select disp.evidence_quality, disp.recovered_amount, ded.deduction_amount
            from public_staging.stg_distributor_disputes disp
            join public_staging.stg_distributor_deductions ded on ded.deduction_id = disp.deduction_id)
        select b.tier, b.rate, c.expected_rate - 0.03, c.expected_rate + 0.03
        from (select evidence_quality as tier,
                     sum(coalesce(recovered_amount, 0)) / nullif(sum(deduction_amount), 0) as rate
              from disputed group by evidence_quality) b
        join curve c on c.tier = b.tier"""),
    "channel_contribution_margin": ("cinderhaven/tests/assert_channel_contribution_margin_in_band.sql", """
        select channel, contribution_margin / gross_revenue, 0.05, 0.85
        from public_marts.mart_channel_contribution where gross_revenue > 0"""),
    "fill_rate": ("cinderhaven/tests/assert_fill_rate_in_band.sql", """
        with f as (
            select o.retailer_id as partner_id, sum(o.total_units) as ordered, sum(s.units_shipped) as shipped
            from public_staging.stg_retailer_orders o
            join public_staging.stg_retailer_shipments s on o.order_id = s.order_id group by o.retailer_id
            union all
            select o.distributor_id, sum(o.total_units), sum(s.units_shipped)
            from public_staging.stg_distributor_orders o
            join public_staging.stg_distributor_shipments s on o.order_id = s.order_id group by o.distributor_id)
        select partner_id, shipped::numeric / ordered, 0.85, 1.0 from f where ordered > 0"""),
    "sku_loaded_margin": ("cinderhaven/tests/assert_sku_loaded_margin_in_band.sql", """
        select sku, loaded_margin_pct, -0.50, 0.90
        from public_intermediate.int_loaded_contribution_by_sku where loaded_margin_pct is not null"""),
    "trade_leakage_rate": ("cinderhaven/tests/assert_trade_leakage_rate_in_band.sql", """
        with l as (
            select (select sum(deduction_amount) from public_marts.fct_retailer_deductions)
                 + (select sum(deduction_amount) from public_marts.fct_distributor_deductions)
                 + (select sum(chargeback_amount) from public_staging.stg_retailer_chargebacks)
                 + (select sum(chargeback_amount) from public_staging.stg_distributor_chargebacks) as leakage,
                   (select sum(total_value) from public_staging.stg_retailer_orders)
                 + (select sum(total_value) from public_staging.stg_distributor_orders) as invoiced)
        select 'wholesale', leakage / invoiced, 0.01, 0.09 from l where invoiced > 0"""),
    "supplier_invoices_vs_cogs": ("tests/test_costing_integrity.sql", """
        with t as (select (select sum(invoice_amount) from costing.fct_supplier_invoices) as invoices,
                          (select sum(units_basis * manufactured_cost_per_unit)
                           from costing.fct_product_costs) as cogs)
        select 'all', (invoices - cogs) / nullif(cogs, 0), -0.02, 0.02 from t"""),
}


def measure(conn) -> dict[str, dict[str, list]]:
    """{measure: {key: [value, lo, hi]}} on the instance `conn` reads."""
    out: dict[str, dict[str, list]] = {}
    with conn.cursor() as cur:
        for name, (_, sql) in MEASURES.items():
            cur.execute(sql)
            out[name] = {str(k): [None if v is None else float(v), float(lo), float(hi)]
                         for k, v, lo, hi in cur.fetchall()}
    return out


def out_of_band(measures: dict[str, dict[str, list]]) -> dict[str, list[str]]:
    """{measure: keys outside their band}, measures with none left out."""
    out = {}
    for name, rows in measures.items():
        bad = sorted(k for k, (v, lo, hi) in rows.items() if v is None or not lo <= v <= hi)
        if bad:
            out[name] = bad
    return out


def spread(entries: list[dict]) -> dict[str, dict[str, dict]]:
    """U7's work list from saved seed entries: per measure and key, the observed
    min and max across the seeds that measured it, and the seeds out of band."""
    out: dict[str, dict[str, dict]] = {}
    for e in entries:
        for name, rows in (e.get("measures") or {}).items():
            for key, (v, lo, hi) in rows.items():
                s = out.setdefault(name, {}).setdefault(key, {"min": None, "max": None, "band": [lo, hi],
                                                             "seeds": 0, "out_of_band_seeds": []})
                s["seeds"] += 1
                if v is None or not lo <= v <= hi:
                    s["out_of_band_seeds"].append(e["seed"])
                if v is not None:
                    s["min"] = v if s["min"] is None else min(s["min"], v)
                    s["max"] = v if s["max"] is None else max(s["max"], v)
    return out
