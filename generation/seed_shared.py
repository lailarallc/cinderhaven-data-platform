"""Seed generator for shared/cross-channel tables.

Tables generated:
  - product_master (30 SKUs)
  - sku_costs (30 rows, per-channel pricing)
  - retailers (6 retailers)
  - distributors (3 distributors)
  - sku_distributors (SKU-distributor mapping)
  - stores (~640 locations)
  - distribution_log (SKU-store authorizations)
  - price_history (wholesale price changes)
  - promotions (promotional events)

Usage:
    python generation/seed_shared.py
"""
from __future__ import annotations

import io
import psycopg2
from datetime import date, timedelta

from seed_config import (
    ALL_SKUS, DATABASE_URL, DISTRIBUTORS, PRODUCT_LINES,
    RETAILERS, RETAILER_STORE_COUNTS, REGIONS, STATES_BY_REGION,
    VOLUME_TIERS, WHOLESALE_MULT, TRADE_SPEND_PCT,
    WINDOW_START, WINDOW_END, DEDUCTION_TYPES, SEASONALITY,
    SKU_ARCHETYPES, ARCHETYPE_DISTRIBUTION,
    init_rng, compute_defect_profile,
)


def copy_rows(cur, table: str, columns: list[str], rows: list[tuple]):
    buf = io.StringIO()
    for row in rows:
        line = "\t".join("\\N" if v is None else str(v) for v in row)
        buf.write(line + "\n")
    buf.seek(0)
    cols = ", ".join(columns)
    sql = f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT text, NULL '\\N')"
    cur.copy_expert(sql, buf)


def seed_product_master(cur, rng):
    cols = [
        "sku", "product_name", "product_line", "subcategory", "gtin14", "upc",
        "case_pack_qty", "unit_weight_lbs", "case_weight_lbs",
        "case_length_in", "case_width_in", "case_height_in",
        "msrp", "brand_owner", "country_of_origin", "last_updated",
    ]

    defect = compute_defect_profile()

    rows = []
    for i, p in enumerate(ALL_SKUS):
        sku = p["sku"]
        dp = defect[sku]
        missing = dp["missing_fields"]

        # Main rng calls preserved exactly (same consumption pattern as before)
        unit_wt = round(rng.uniform(0.4, 2.0), 4)
        cpq = p["case_pack_qty"]
        case_wt = round(unit_wt * cpq * 1.05, 4)
        case_len = round(rng.uniform(10, 18), 2)
        case_wid = round(rng.uniform(8, 14), 2)
        case_ht = round(rng.uniform(6, 12), 2)

        rows.append((
            sku, p["product_name"], p["product_line"],
            None if missing.get("subcategory") else p["product_line"],
            dp["gtin14"], dp["upc"], cpq,
            None if missing.get("unit_weight_lbs") else unit_wt,
            None if missing.get("case_weight_lbs") else case_wt,
            None if missing.get("case_length_in") else case_len,
            None if missing.get("case_width_in") else case_wid,
            None if missing.get("case_height_in") else case_ht,
            p["msrp"],
            None if missing.get("brand_owner") else "Cinderhaven Provisions",
            None if missing.get("country_of_origin") else "USA",
            "2025-01-15",
        ))
    copy_rows(cur, "raw.product_master", cols, rows)
    print(f"  product_master: {len(rows)} rows")
    return rows


def seed_sku_costs(cur, rng):
    cols = [
        "sku", "cogs_per_unit", "landed_cost_per_unit", "wholesale_price",
        "wholesale_walmart", "wholesale_costco", "wholesale_whole_foods",
        "wholesale_sprouts", "wholesale_regional",
        "wholesale_unfi", "wholesale_kehe", "wholesale_dtc",
        "trade_spend_pct_walmart", "trade_spend_pct_costco",
        "trade_spend_pct_whole_foods", "trade_spend_pct_sprouts",
        "trade_spend_pct_kroger", "trade_spend_pct_regional",
        "trade_spend_pct_unfi", "trade_spend_pct_kehe", "trade_spend_pct_dtc",
    ]
    rows = []
    for p in ALL_SKUS:
        msrp = p["msrp"]
        cogs = p["cogs_per_unit"]
        landed = round(cogs * rng.uniform(1.10, 1.25), 2)
        base_wholesale = round(msrp * 0.52, 2)
        rows.append((
            p["sku"], cogs, landed, base_wholesale,
            round(msrp * WHOLESALE_MULT["walmart"], 2),
            round(msrp * WHOLESALE_MULT["costco"], 2),
            round(msrp * WHOLESALE_MULT["whole_foods"], 2),
            round(msrp * WHOLESALE_MULT["sprouts"], 2),
            round(msrp * WHOLESALE_MULT["regional"], 2),
            round(msrp * WHOLESALE_MULT["unfi"], 2),
            round(msrp * WHOLESALE_MULT["kehe"], 2),
            round(msrp * WHOLESALE_MULT["dtc"], 2),
            TRADE_SPEND_PCT["walmart"],
            TRADE_SPEND_PCT["costco"],
            TRADE_SPEND_PCT["whole_foods"],
            TRADE_SPEND_PCT["sprouts"],
            TRADE_SPEND_PCT["kroger"],
            TRADE_SPEND_PCT["regional"],
            TRADE_SPEND_PCT["unfi"],
            TRADE_SPEND_PCT["kehe"],
            TRADE_SPEND_PCT["dtc"],
        ))
    copy_rows(cur, "raw.sku_costs", cols, rows)
    print(f"  sku_costs: {len(rows)} rows")


def seed_retailers(cur):
    cols = ["retailer_id", "name", "dispute_portal_name", "dispute_portal_url", "dispute_method", "notes"]
    rows = [(r["retailer_id"], r["name"], r["dispute_portal_name"],
             r["dispute_portal_url"], r["dispute_method"], None) for r in RETAILERS]
    copy_rows(cur, "raw.retailers", cols, rows)
    print(f"  retailers: {len(rows)} rows")


def seed_distributors(cur):
    cols = ["distributor_id", "name", "type", "margin_pct", "payment_terms_days"]
    rows = [(d["distributor_id"], d["name"], d["type"], d["margin_pct"],
             d["payment_terms_days"]) for d in DISTRIBUTORS]
    copy_rows(cur, "raw.distributors", cols, rows)
    print(f"  distributors: {len(rows)} rows")


def seed_sku_distributors(cur, rng):
    cols = ["sku", "distributor_id"]
    rows = []
    for p in ALL_SKUS:
        n_dists = rng.choice([1, 1, 2, 2, 3])
        chosen = rng.sample([d["distributor_id"] for d in DISTRIBUTORS], min(n_dists, len(DISTRIBUTORS)))
        for did in chosen:
            rows.append((p["sku"], did))
    copy_rows(cur, "raw.sku_distributors", cols, rows)
    print(f"  sku_distributors: {len(rows)} rows")


def seed_stores(cur, rng):
    cols = ["store_id", "retailer_id", "chain_name", "region", "state", "volume_tier"]
    rows = []
    for ret in RETAILERS:
        rid = ret["retailer_id"]
        count = RETAILER_STORE_COUNTS[rid]
        for i in range(count):
            region = rng.choice(REGIONS)
            state = rng.choice(STATES_BY_REGION[region])
            tier = rng.choices(VOLUME_TIERS, weights=[25, 50, 25])[0]
            store_id = f"{rid}-S{i+1:04d}"
            rows.append((store_id, rid, ret["name"], region, state, tier))
    copy_rows(cur, "raw.stores", cols, rows)
    print(f"  stores: {len(rows)} rows")
    return rows


def seed_distribution_log(cur, rng, stores):
    cols = ["sku", "store_id", "authorized_date", "deauthorized_date"]
    rows = []

    sku_auth_rate = {}
    for p in ALL_SKUS:
        archetype = SKU_ARCHETYPES.get(p["sku"], "moderate")
        low, high = ARCHETYPE_DISTRIBUTION[archetype]
        sku_auth_rate[p["sku"]] = rng.uniform(low, high)

    for store in stores:
        store_id = store[0]
        for p in ALL_SKUS:
            sku = p["sku"]
            if rng.random() < sku_auth_rate[sku]:
                auth_date = WINDOW_START + timedelta(days=rng.randint(0, 180))
                deauth = None
                if rng.random() < 0.08:
                    deauth = auth_date + timedelta(days=rng.randint(90, 500))
                    if deauth > WINDOW_END:
                        deauth = None
                rows.append((sku, store_id, str(auth_date), str(deauth) if deauth else None))
    copy_rows(cur, "raw.distribution_log", cols, rows)
    print(f"  distribution_log: {len(rows)} rows")


def seed_price_history(cur, rng):
    cols = ["sku", "retailer_id", "effective_date", "wholesale_price"]
    rows = []
    for p in ALL_SKUS:
        for ret in RETAILERS:
            rid = ret["retailer_id"]
            key = ret["name"].lower().replace(" ", "_")
            if key == "regional_group":
                key = "regional"
            mult = WHOLESALE_MULT.get(key, 0.52)
            base_price = round(p["msrp"] * mult, 2)
            rows.append((p["sku"], rid, str(WINDOW_START), base_price))
            if rng.random() < 0.35:
                change_date = WINDOW_START + timedelta(days=rng.randint(180, 600))
                if change_date <= WINDOW_END:
                    new_price = round(base_price * rng.uniform(1.02, 1.08), 2)
                    rows.append((p["sku"], rid, str(change_date), new_price))
    copy_rows(cur, "raw.price_history", cols, rows)
    print(f"  price_history: {len(rows)} rows")


def seed_promotions(cur, rng):
    cols = ["promo_id", "sku", "retailer_id", "start_week", "end_week",
            "discount_depth_pct", "promo_type", "promo_cost", "funding_mechanism"]
    promo_types = ["TPR", "BOGO", "endcap", "ad_circular", "digital_coupon"]
    funding = ["scan_based", "off_invoice", "billback", "MCB"]
    rows = []
    promo_num = 0
    for p in ALL_SKUS:
        n_promos = rng.randint(1, 4)
        for _ in range(n_promos):
            promo_num += 1
            rid = rng.choice(RETAILERS)["retailer_id"]
            start_offset = rng.randint(0, 650)
            start = WINDOW_START + timedelta(days=start_offset)
            start = start - timedelta(days=start.weekday())  # align to Monday
            dur_weeks = rng.choice([1, 2, 2, 4, 4])
            end = start + timedelta(weeks=dur_weeks) - timedelta(days=1)
            if end > WINDOW_END:
                continue
            depth = round(rng.uniform(0.05, 0.30), 4)
            cost = round(rng.uniform(200, 5000), 2)
            rows.append((
                f"PROMO-{promo_num:04d}", p["sku"], rid,
                str(start), str(end), depth,
                rng.choice(promo_types), cost, rng.choice(funding),
            ))
    copy_rows(cur, "raw.promotions", cols, rows)
    print(f"  promotions: {len(rows)} rows")


def seed_retailer_rules(cur, rng):
    cols = ["retailer_id", "deduction_type", "dispute_window_days", "auto_deduct",
            "evidence_required", "typical_recovery_rate", "notes"]
    rows = []
    for ret in RETAILERS:
        for dt in DEDUCTION_TYPES:
            window = rng.choice([30, 45, 60, 90])
            auto = rng.random() < 0.3
            recovery = round(rng.uniform(0.15, 0.75), 4)
            evidence = rng.choice(["BOL + POD", "invoice + ASN", "pack photo", "price confirmation", "all"])
            rows.append((ret["retailer_id"], dt, window, auto, evidence, recovery, None))
    copy_rows(cur, "raw.retailer_rules", cols, rows)
    print(f"  retailer_rules: {len(rows)} rows")


def seed_retailer_requirements(cur, rng):
    cols = ["retailer_id", "field", "required", "notes"]
    fields = ["gtin14", "upc", "brand_owner", "country_of_origin", "unit_weight",
              "case_dimensions", "serving_size", "allergen_statement", "nutrition_facts",
              "product_image", "sds_sheet"]
    rows = []
    for ret in RETAILERS:
        for f in fields:
            req = rng.random() < 0.7
            rows.append((ret["retailer_id"], f, req, None))
    copy_rows(cur, "raw.retailer_requirements", cols, rows)
    print(f"  retailer_requirements: {len(rows)} rows")


def seed_retailer_deduction_codes(cur, rng):
    cols = ["code_id", "retailer_id", "code", "name", "deduction_type", "is_published"]
    code_names = {
        "short_ship": ["Short Ship", "Quantity Variance", "Under-delivery"],
        "promo_billback": ["Promo Billback", "Ad Allowance", "Scan Rebate"],
        "slotting": ["Slotting Fee", "New Item Fee", "Shelf Placement"],
        "late_delivery": ["Late Delivery", "MABD Violation", "Appointment Miss"],
        "label_fine": ["Label Non-Compliance", "UPC Error", "Label Defect"],
        "pallet_fine": ["Pallet Violation", "Ti-Hi Error", "Pallet Overhang"],
        "spoilage": ["Spoilage", "Short Date", "Expired Product"],
        "damaged": ["Damaged Goods", "Transit Damage", "Warehouse Damage"],
        "pricing_error": ["Pricing Variance", "Invoice Mismatch", "Cost Discrepancy"],
    }
    rows = []
    code_num = 0
    for ret in RETAILERS:
        for dt, names in code_names.items():
            n_codes = rng.randint(1, len(names))
            for name in rng.sample(names, n_codes):
                code_num += 1
                code = f"{ret['retailer_id'][-3:]}-{dt[:3].upper()}-{code_num:03d}"
                rows.append((
                    f"DC-{code_num:04d}", ret["retailer_id"], code,
                    name, dt, rng.random() < 0.8,
                ))
    copy_rows(cur, "raw.retailer_deduction_codes", cols, rows)
    print(f"  retailer_deduction_codes: {len(rows)} rows")
    return rows


def seed_retailer_edi_requirements(cur, rng):
    cols = ["retailer_id", "category", "requirement", "penalty_if_violated",
            "is_verified", "source_url"]
    categories = {
        "ASN": ["Must send ASN within 24hrs of ship", "ASN must include SSCC-18", "PO number required on ASN"],
        "Label": ["GS1-128 label required", "SSCC barcode on each pallet", "Retailer-specific label template"],
        "Routing": ["Must use approved carriers", "Appointment scheduling required", "MABD compliance"],
        "Documentation": ["BOL must accompany shipment", "Packing list required", "Certificate of insurance"],
    }
    penalties = ["$500 per violation", "$250 chargeback", "shipment refused", "vendor scorecard impact", None]
    rows = []
    for ret in RETAILERS:
        for cat, reqs in categories.items():
            for req in reqs:
                if rng.random() < 0.7:
                    rows.append((
                        ret["retailer_id"], cat, req,
                        rng.choice(penalties), rng.random() < 0.6, None,
                    ))
    copy_rows(cur, "raw.retailer_edi_requirements", cols, rows)
    print(f"  retailer_edi_requirements: {len(rows)} rows")


def main():
    print("Connecting to Postgres...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    rng = init_rng()

    print("\nSeeding shared tables:")
    seed_product_master(cur, rng)
    seed_sku_costs(cur, rng)
    seed_retailers(cur)
    seed_distributors(cur)
    seed_sku_distributors(cur, rng)
    stores = seed_stores(cur, rng)

    print("\nSeeding retailer reference tables:")
    seed_retailer_rules(cur, rng)
    seed_retailer_requirements(cur, rng)
    deduction_codes = seed_retailer_deduction_codes(cur, rng)
    seed_retailer_edi_requirements(cur, rng)

    print("\nSeeding shared cross-channel tables:")
    seed_distribution_log(cur, rng, stores)
    seed_price_history(cur, rng)
    seed_promotions(cur, rng)

    conn.commit()
    print("\nShared tables committed.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
