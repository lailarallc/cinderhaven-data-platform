"""Seed the additive cost side and balance sheet into the `costing` schema.

ADDITIVE ONLY. Reads from `raw` and `public_staging`; writes only to `costing`.
No existing table is modified, and `costing` survives seed_all.py's teardown of
`raw`.

Every demand-dependent value is DERIVED from raw.scan_data at generation time:
inventory build-ahead, production run timing, the ingredient scale effect,
stockout placement and copack invoice timing. Re-running after a demand-curve
change (seasonality, growth reshape) is a re-run, not a rewrite.

Stable and hardcoded: freight rates by NMFC class, shelf life by product line,
supplier payment terms, lot-to-store allocation policy.

Usage:
    DATABASE_URL=... python scripts/seed_costing.py
"""
from __future__ import annotations

import os
import random
import sys
from collections import defaultdict
from datetime import date, timedelta

import psycopg2
import psycopg2.extras

import prod_guard

# Isolated RNG stream — cannot cascade into trade/count generation.
SEED = 800

WINDOW_START = date(2023, 1, 1)
WINDOW_END = date(2026, 1, 2)

# ── Stable constants ────────────────────────────────────────────────

# Shelf life by product line, months. Shelf-stable specialty food norms:
# high-acid hot-fill sauces and acidified spreads ~18mo; vinegar/honey/oil/
# syrup ~24mo; dried goods carrying fats ~12mo; fat-forward snack items ~9mo.
# NOTE: general food-industry ranges, not a cited category database. Validate
# before these appear in a demo as sourced figures.
SHELF_LIFE_MONTHS = {
    "Artisan Sauces": 18,
    "Pantry Staples": 24,
    "Specialty Condiments": 18,
    "Dried Goods": 12,
    "Snack Bites": 9,
}

# NMFC density breaks (lb/cuft) -> freight class. Standard 18-class scale.
NMFC_BREAKS = [
    (50.0, 50), (35.0, 55), (30.0, 60), (22.5, 65), (15.0, 70),
    (13.5, 85), (12.0, 92.5), (10.5, 100), (9.0, 110), (8.0, 125),
    (7.0, 150), (6.0, 175),
]
NMFC_DEFAULT_CLASS = 175      # fallback when case dimensions are missing
NMFC_FLOOR_CLASS = 250
FREIGHT_BASE_RATE_PER_CWT = 18.00   # scaled to the anchor; shape only

# Supplier payment terms
COPACK_TERMS = 30
PACKAGING_TERMS = 45
FREIGHT_TERMS = 21

# Inventory policy
LEAD_TIME_DAYS = 35
SAFETY_DAYS = 18
COVERAGE_WEEKS = 28
LAUNCH_BUILD_WEEKS = 22

# Cost drift ramp: frozen standard vs rising actual. Linear across the window,
# calibrated so yearly mean PPV lands at -5.6% / +0.2% / +6.1% of standard.
DRIFT_START = -0.085
DRIFT_END = 0.090

OVERHEAD_PCT_OF_REVENUE = 0.010

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"host=localhost port=5432 dbname=cinderhaven user=postgres "
    f"password={os.environ.get('POSTGRES_PASSWORD', '')}",
)


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def freight_class_for(density):
    if density is None:
        return NMFC_DEFAULT_CLASS, False
    for lo, cls in NMFC_BREAKS:
        if density >= lo:
            return cls, True
    return NMFC_FLOOR_CLASS, True


# ── Load ────────────────────────────────────────────────────────────

def load_inputs(cur):
    cur.execute("""
        SELECT p.sku, p.product_line, p.case_pack_qty, p.case_weight_lbs,
               p.case_length_in, p.case_width_in, p.case_height_in,
               c.cogs_per_unit, c.landed_cost_per_unit
        FROM raw.product_master p JOIN raw.sku_costs c USING (sku)
        ORDER BY p.sku
    """)
    products = {r["sku"]: dict(r) for r in cur.fetchall()}

    # Weekly demand SHAPE from scan_data — the derivation backbone.
    cur.execute("""
        SELECT sku, week_ending, SUM(units_sold)::bigint AS units
        FROM raw.scan_data GROUP BY 1,2 ORDER BY 1,2
    """)
    demand = defaultdict(dict)
    for r in cur.fetchall():
        demand[r["sku"]][r["week_ending"]] = int(r["units"])

    # Shipped units per sku — inventory is drawn down by shipments, so the scan
    # shape is rescaled to shipped volume.
    cur.execute("""
        SELECT sku, SUM(units)::bigint AS units FROM (
            SELECT ol.sku, SUM(ol.units_ordered) AS units
            FROM public_staging.stg_retailer_order_lines ol GROUP BY 1
            UNION ALL
            SELECT ol.sku, SUM(ol.units_ordered) FROM public_staging.stg_distributor_order_lines ol GROUP BY 1
            UNION ALL
            SELECT ol.sku, SUM(ol.quantity) FROM public_staging.stg_shopify_order_lines ol GROUP BY 1
        ) x GROUP BY sku
    """)
    shipped = {r["sku"]: int(r["units"]) for r in cur.fetchall()}

    # Shipped units per sku-MONTH. This is the COGS basis: cost flows with
    # actual shipments, not with sell-through. The scan curve drives inventory
    # timing (below), not the cost basis.
    cur.execute("""
        SELECT sku, date_trunc('month', d)::date AS mo, SUM(u)::bigint AS units FROM (
            SELECT ol.sku, o.po_date AS d, ol.units_ordered AS u
            FROM public_staging.stg_retailer_order_lines ol
            JOIN public_staging.stg_retailer_orders o USING (order_id)
            UNION ALL
            SELECT ol.sku, o.po_date, ol.units_ordered
            FROM public_staging.stg_distributor_order_lines ol
            JOIN public_staging.stg_distributor_orders o USING (order_id)
            UNION ALL
            SELECT ol.sku, o.created_at::date, ol.quantity
            FROM public_staging.stg_shopify_order_lines ol
            JOIN public_staging.stg_shopify_orders o USING (order_id)
        ) x GROUP BY 1,2
    """)
    units_by_month = defaultdict(dict)
    for r in cur.fetchall():
        units_by_month[r["sku"]][r["mo"]] = int(r["units"])

    # Stockout anchors: sku-weeks where active store coverage drops (the
    # internal scan gaps and went-dark events already in the data).
    cur.execute("""
        WITH pair_weeks AS (
            SELECT sku, store_id, week_ending FROM raw.scan_data
        ),
        cov AS (
            SELECT sku, week_ending, COUNT(DISTINCT store_id) AS stores
            FROM pair_weeks GROUP BY 1,2
        ),
        med AS (
            SELECT sku, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY stores) AS m
            FROM cov GROUP BY sku
        )
        SELECT c.sku, c.week_ending
        FROM cov c JOIN med m USING (sku)
        WHERE c.stores < m.m * 0.85
        ORDER BY 1,2
    """)
    stockout_weeks = defaultdict(set)
    for r in cur.fetchall():
        stockout_weeks[r["sku"]].add(r["week_ending"])

    # The DIO cause: SKUs hit hardest by the 2024 deauthorization wave. These
    # carry the over-production slug that never cleared.
    cur.execute("""
        SELECT sku, COUNT(*) AS deauths
        FROM raw.distribution_log
        WHERE deauthorized_date BETWEEN '2024-01-01' AND '2024-12-31'
        GROUP BY sku ORDER BY deauths DESC LIMIT 8
    """)
    slug_skus = [r["sku"] for r in cur.fetchall()]

    cur.execute("SELECT store_id, retailer_id FROM raw.stores ORDER BY store_id")
    stores = [(r["store_id"], r["retailer_id"]) for r in cur.fetchall()]

    cur.execute("""
        SELECT s.shipment_id, s.ship_date, o.retailer_id
        FROM raw.retailer_shipments s JOIN raw.retailer_orders o USING (order_id)
        ORDER BY s.ship_date, s.shipment_id
    """)
    shipments = [dict(r) for r in cur.fetchall()]

    return products, demand, shipped, units_by_month, stockout_weeks, slug_skus, stores, shipments


# ── Suppliers ───────────────────────────────────────────────────────

def build_suppliers(products):
    lines = sorted({p["product_line"] for p in products.values()})
    rows = []
    for i, line in enumerate(lines, 1):
        rows.append((
            f"SUP-COPACK-{i:02d}", f"{line.split()[0]} Co-Pack Partners",
            "copacker", line, COPACK_TERMS, "Net 30", 0, None, date(2022, 10, 1),
        ))
    rows.append(("SUP-PKG-01", "Cascade Packaging Group", "packaging", None,
                 PACKAGING_TERMS, "2/10 Net 45", 0.02, 10, date(2022, 11, 1)))
    rows.append(("SUP-FRT-01", "Meridian Freight Systems", "freight", None,
                 FREIGHT_TERMS, "Net 21", 0, None, date(2022, 11, 15)))
    return rows


# ── Product costs ───────────────────────────────────────────────────

def build_product_costs(products, demand, shipped, units_by_month, revenue_total):
    """sku x month. Freight from weight/class, anchored to the landed total."""
    months = []
    m = month_start(WINDOW_START)
    while m < WINDOW_END:
        months.append(m)
        m = add_months(m, 1)

    # Units per sku-month = actual shipments. COGS follows goods sold, not
    # sell-through; the scan curve drives inventory timing instead.
    units = units_by_month

    # Freight shape: weight-derived, per unit.
    raw_freight = {}
    for sku, p in products.items():
        cpq = p["case_pack_qty"] or 12
        wt = float(p["case_weight_lbs"]) if p["case_weight_lbs"] is not None else None
        dims = all(p[k] is not None for k in ("case_length_in", "case_width_in", "case_height_in"))
        density = None
        if dims and wt:
            cuft = (float(p["case_length_in"]) * float(p["case_width_in"])
                    * float(p["case_height_in"])) / 1728.0
            density = wt / cuft if cuft > 0 else None
        cls, complete = freight_class_for(density)
        eff_wt = wt if wt else 22.0          # median case weight fallback
        # Class differentiation is superlinear: low-density freight is penalised
        # more than proportionally, which is how NMFC pricing actually behaves.
        per_unit = (eff_wt / cpq) * (FREIGHT_BASE_RATE_PER_CWT * (cls / 100.0) ** 1.6) / 100.0
        raw_freight[sku] = {
            "per_unit": per_unit, "class": cls, "density": density,
            "dims_complete": complete and wt is not None,
        }

    # Anchor: total weight-derived freight must equal the existing
    # landed-minus-cogs total, so blended margin stays consistent with what is
    # already published. Per-SKU divergence from landed_cost_per_unit is correct
    # and expected -- weight is not cost.
    anchor_total = sum(
        float(products[s]["landed_cost_per_unit"] - products[s]["cogs_per_unit"]) * shipped.get(s, 0)
        for s in products
    )
    modelled_total = sum(raw_freight[s]["per_unit"] * shipped.get(s, 0) for s in products)
    fscale = anchor_total / modelled_total if modelled_total else 1.0
    for s in raw_freight:
        raw_freight[s]["per_unit"] *= fscale

    # Freight penalty attributable to missing case dimensions: what the default
    # class costs above the portfolio median class. This is the dollar cost of a
    # master-data defect.
    complete_classes = sorted(v["class"] for v in raw_freight.values() if v["dims_complete"])
    median_cls = complete_classes[len(complete_classes) // 2] if complete_classes else 100
    for s, v in raw_freight.items():
        if not v["dims_complete"]:
            ratio = (v["class"] - median_cls) / v["class"] if v["class"] else 0
            v["penalty"] = max(0.0, v["per_unit"] * ratio)
        else:
            v["penalty"] = 0.0

    # Ingredient scale effect: higher-volume SKUs get better pricing. Derived
    # from actual volumes, so it re-ranks if demand changes.
    vols = {s: shipped.get(s, 1) for s in products}
    median_vol = sorted(vols.values())[len(vols) // 2] or 1
    scale_adj = {}
    for s, v in vols.items():
        import math
        scale_adj[s] = max(-0.03, min(0.03, -0.012 * math.log((v or 1) / median_vol)))

    # Overhead is absorbed inversely to volume: short runs carry more handling,
    # QA and changeover cost per unit than long ones. Total is held constant, so
    # this reallocates rather than adds.
    overhead_total = revenue_total * OVERHEAD_PCT_OF_REVENUE
    ov_weight = {s: (median_vol / max(1, vols[s])) ** 1.0 for s in products}
    ov_denom = sum(ov_weight[s] * shipped.get(s, 0) for s in products) or 1
    ov_rate = overhead_total / ov_denom
    overhead_by_sku = {s: ov_rate * ov_weight[s] for s in products}

    rows = []
    n_months = len(months)
    for sku, p in sorted(products.items()):
        std = float(p["cogs_per_unit"])
        f = raw_freight[sku]
        for i, mo in enumerate(months):
            drift = DRIFT_START + (DRIFT_END - DRIFT_START) * (i / max(1, n_months - 1))
            actual = std * (1.0 + drift + scale_adj[sku])
            # Split manufactured into its three parts. Packaging is the
            # cost-proportional component (which is what the legacy landed
            # uplift actually behaved like); conversion is co-pack labour.
            ingredient = round(actual * 0.55, 4)
            packaging = round(actual * 0.25, 4)
            conversion = round(actual - ingredient - packaging, 4)
            rows.append((
                sku, mo, units[sku].get(mo, 0),
                round(std, 4), ingredient, packaging, conversion,
                round(f["per_unit"], 4), round(overhead_by_sku[sku], 4),
                int(f["class"]) if float(f["class"]).is_integer() else int(f["class"]),
                round(f["density"], 4) if f["density"] is not None else None,
                f["dims_complete"], round(f["penalty"], 4),
            ))
    return rows, months, units, raw_freight


# ── Inventory simulation ────────────────────────────────────────────

def simulate(products, demand, shipped, stockout_weeks, slug_skus, rng):
    """Walk weekly inventory per SKU. Runs fire on reorder-point crossing;
    run size is forward-looking coverage, so build-ahead emerges from whatever
    the demand curve says."""
    weeks = sorted({w for d in demand.values() for w in d})
    runs, lots, balances, snaps = [], [], [], []
    run_n = lot_n = 0

    for sku, p in sorted(products.items()):
        wk = demand.get(sku, {})
        if not wk:
            continue
        tot = sum(wk.values()) or 1
        scale = shipped.get(sku, 0) / tot
        dem = {w: wk.get(w, 0) * scale for w in weeks}
        shelf_days = SHELF_LIFE_MONTHS[p["product_line"]] * 30
        avg_daily = (sum(dem.values()) / max(1, len(weeks))) / 7.0

        outs = stockout_weeks.get(sku, set())
        # Replenishment blackout: skip reordering in the lead-time window ahead
        # of each anchored coverage-collapse week, so on-hand depletes to zero
        # at exactly the weeks scan_data already shows going dark.
        lead_weeks = max(1, LEAD_TIME_DAYS // 7)
        widx = {w: i for i, w in enumerate(weeks)}
        suppress_idx = set()
        for ow in outs:
            oi = widx.get(ow)
            if oi is not None:
                suppress_idx.update(range(max(0, oi - lead_weeks - 2), oi + 1))

        on_hand = 0.0
        pipeline = []          # (arrival_week_index, units, run_id)
        open_lots = []         # [lot_code, units_remaining, expiry]

        # Launch build: initial stocking run before the window opens.
        init = sum(list(dem.values())[:LAUNCH_BUILD_WEEKS])
        run_n += 1; lot_n += 1
        rid, lc = f"RUN-{run_n:05d}", f"LOT-{lot_n:05d}"
        runs.append((rid, sku, None, WINDOW_START - timedelta(days=LEAD_TIME_DAYS),
                     WINDOW_START, max(1, int(init)), "launch_build"))
        lots.append((lc, sku, rid, WINDOW_START, WINDOW_START + timedelta(days=shelf_days), max(1, int(init))))
        open_lots.append([lc, float(max(1, int(init))), WINDOW_START + timedelta(days=shelf_days)])
        on_hand = float(max(1, int(init)))

        for wi, w in enumerate(weeks):
            for arr in [x for x in pipeline if x[0] == wi]:
                on_hand += arr[1]
                lot_n += 1
                lc2 = f"LOT-{lot_n:05d}"
                lots.append((lc2, sku, arr[2], w, w + timedelta(days=shelf_days), int(arr[1])))
                open_lots.append([lc2, float(arr[1]), w + timedelta(days=shelf_days)])
            pipeline = [x for x in pipeline if x[0] != wi]

            d = dem.get(w, 0.0)
            # Stockouts are caused by suppressed replenishment (below), not by
            # consuming stock. Unmet demand is lost, never written off, so
            # production still reconciles to sales plus inventory change.
            take = min(on_hand, d)
            on_hand -= take

            # FEFO draw
            rem = take
            open_lots.sort(key=lambda x: x[2])
            for L in open_lots:
                if rem <= 0:
                    break
                use = min(L[1], rem)
                L[1] -= use
                rem -= use
            open_lots = [L for L in open_lots if L[1] > 0.5]

            reorder = avg_daily * LEAD_TIME_DAYS + avg_daily * SAFETY_DAYS
            incoming = sum(x[1] for x in pipeline)
            if on_hand + incoming < reorder and wi not in suppress_idx:
                fwd = sum(dem.get(x, 0.0) for x in weeks[wi:wi + COVERAGE_WEEKS])
                size = max(int(fwd), int(avg_daily * 30))
                if sku in slug_skus and date(2024, 1, 1) <= w <= date(2024, 6, 30):
                    size = int(size * 2.4)      # over-production ahead of a
                                                # retailer launch that underperformed
                run_n += 1
                rid = f"RUN-{run_n:05d}"
                lead_w = max(1, LEAD_TIME_DAYS // 7)
                runs.append((rid, sku, None, w, w + timedelta(days=LEAD_TIME_DAYS), size,
                             "build_ahead" if fwd > avg_daily * 7 * COVERAGE_WEEKS else "reorder_point"))
                pipeline.append((wi + lead_w, float(size), rid))

            for L in open_lots:
                balances.append((w, L[0], sku, int(L[1])))
            snaps.append((w, sku, int(on_hand), int(sum(x[1] for x in pipeline)), avg_daily * 7 / 7.0))

    return runs, lots, balances, snaps


def main():
    rng = random.Random(SEED)
    prod_guard.check(DATABASE_URL)  # refuses a fly tunnel to production
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("Loading inputs from raw + staging ...")
    products, demand, shipped, ubm, outs, slug, stores, shipments = load_inputs(cur)

    cur.execute("""
        SELECT (SELECT SUM(total_value) FROM public_staging.stg_retailer_orders)
             + (SELECT SUM(total_value) FROM public_staging.stg_distributor_orders)
             + (SELECT SUM(total) FROM public_staging.stg_shopify_orders) AS rev
    """)
    revenue_total = float(cur.fetchone()["rev"])

    print("Executing costing DDL ...")
    ddl = open(os.path.join(os.path.dirname(__file__), "..", "sql", "costing_schema.sql")).read()
    cur.execute(ddl)

    print("Building suppliers ...")
    sup = build_suppliers(products)
    psycopg2.extras.execute_values(cur, """
        INSERT INTO costing.dim_suppliers (supplier_id, supplier_name, supplier_type,
            product_line, payment_terms_days, terms_code, discount_pct, discount_days, onboarded_date)
        VALUES %s""", sup)
    copack_by_line = {r[3]: r[0] for r in sup if r[2] == "copacker"}

    print("Building product costs ...")
    pc, months, units, freight = build_product_costs(products, demand, shipped, ubm, revenue_total)
    psycopg2.extras.execute_values(cur, """
        INSERT INTO costing.fct_product_costs (sku, cost_period, units_basis,
            standard_cost_per_unit, ingredient_cost_per_unit, packaging_cost_per_unit,
            conversion_cost_per_unit, freight_in_cost_per_unit, overhead_per_unit,
            freight_class, density_lb_per_cuft, dims_complete, freight_penalty_per_unit)
        VALUES %s""", pc, page_size=1000)

    print("Simulating inventory ...")
    runs, lots, balances, snaps = simulate(products, demand, shipped, outs, slug, rng)
    runs = [(r[0], r[1], copack_by_line[products[r[1]]["product_line"]], r[3], r[4], r[5], r[6]) for r in runs]
    psycopg2.extras.execute_values(cur, """
        INSERT INTO costing.fct_production_runs (run_id, sku, supplier_id,
            scheduled_date, completed_date, units_produced, run_reason) VALUES %s""",
        runs, page_size=1000)
    psycopg2.extras.execute_values(cur, """
        INSERT INTO costing.dim_inventory_lots (lot_code, sku, run_id, produced_date,
            expiry_date, units_produced) VALUES %s""", lots, page_size=1000)

    # cost lookup for snapshot valuation
    cost_by = {(r[0], r[1]): (r[3], r[4] + r[5] + r[6] + r[7] + r[8]) for r in pc}
    snap_rows = []
    for w, sku, oh, it, dr in snaps:
        k = (sku, month_start(w))
        std, act = cost_by.get(k, (0, 0))
        snap_rows.append((w, sku, oh, it, std, act, round(dr, 4)))
    psycopg2.extras.execute_values(cur, """
        INSERT INTO costing.fct_inventory_snapshot (snapshot_date, sku, units_on_hand,
            units_in_transit, standard_cost_at_snapshot, actual_cost_at_snapshot,
            demand_rate_units_per_day) VALUES %s""", snap_rows, page_size=5000)
    psycopg2.extras.execute_values(cur, """
        INSERT INTO costing.fct_lot_balances (snapshot_date, lot_code, sku, units_remaining)
        VALUES %s ON CONFLICT DO NOTHING""", balances, page_size=5000)

    print("Building supplier invoices ...")
    inv = []
    n = 0
    for rid, sku, sid, sched, comp, u, reason in runs:
        k = (sku, month_start(comp))
        std, act = cost_by.get(k, (0, 0))
        mfg = cost_by.get(k, (0, 0))[1]
        # copack invoices the manufactured cost -- they ARE the COGS
        pcm = [r for r in pc if r[0] == sku and r[1] == month_start(comp)]
        man = (pcm[0][4] + pcm[0][5] + pcm[0][6]) if pcm else float(products[sku]["cogs_per_unit"])
        goods = round(u * man, 2)
        n += 1
        terms = COPACK_TERMS
        due = comp + timedelta(days=terms)
        # modelled +/-2% causes
        surcharge = round(goods * rng.uniform(0.004, 0.018), 2) if rng.random() < 0.35 else 0
        moq = round(rng.uniform(150, 600), 2) if u < 4000 else 0
        credit = round(goods * rng.uniform(0.003, 0.02), 2) if rng.random() < 0.18 else 0
        # AP scatter, with a visible stretch during pre-peak build months
        stretch = 12 if comp.month in (10, 11, 12) else 0
        paid = due + timedelta(days=int(rng.gauss(2 + stretch, 6)))
        inv.append((f"SINV-{n:06d}", sid, rid, comp, due, paid, "copack",
                    goods, surcharge, moq, credit))
    psycopg2.extras.execute_values(cur, """
        INSERT INTO costing.fct_supplier_invoices (invoice_id, supplier_id, run_id,
            invoice_date, due_date, paid_date, invoice_type, goods_amount,
            freight_surcharge, moq_fee, short_ship_credit) VALUES %s""", inv, page_size=1000)

    print("Allocating lots to stores ...")
    ship_by_month = defaultdict(list)
    for s in shipments:
        ship_by_month[month_start(s["ship_date"])].append(s)
    stores_by_ret = defaultdict(list)
    for sid_, rid_ in stores:
        stores_by_ret[rid_].append(sid_)

    ls, seen = [], set()
    lots_by_sku = defaultdict(list)
    for lc, sku, rid, pd_, ed, u in lots:
        lots_by_sku[sku].append((pd_, lc, u))
    for sku in lots_by_sku:
        lots_by_sku[sku].sort()
    for mo, sl in sorted(ship_by_month.items()):
        for s in sl[:40]:
            for sku in rng.sample(sorted(products), 3):
                cand = [x for x in lots_by_sku[sku] if x[0] <= s["ship_date"]]
                if not cand:
                    continue
                lc = cand[-1][1]
                st = stores_by_ret.get(s["retailer_id"]) or []
                if not st:
                    continue
                stq = rng.choice(st)
                key = (lc, s["shipment_id"], stq)
                if key in seen:
                    continue
                seen.add(key)
                ls.append((lc, s["shipment_id"], stq, sku, rng.randint(6, 60), s["ship_date"]))
    psycopg2.extras.execute_values(cur, """
        INSERT INTO costing.fct_lot_shipments (lot_code, shipment_id, store_id, sku, units, ship_date)
        VALUES %s ON CONFLICT DO NOTHING""", ls, page_size=2000)

    conn.commit()
    for t in ("dim_suppliers", "fct_product_costs", "fct_production_runs",
              "dim_inventory_lots", "fct_lot_balances", "fct_inventory_snapshot",
              "fct_lot_shipments", "fct_supplier_invoices"):
        cur.execute(f"SELECT count(*) AS n FROM costing.{t}")
        print(f"  costing.{t:28s} {cur.fetchone()['n']:>10,}")
    cur.close(); conn.close()
    print("Done.")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    main()
