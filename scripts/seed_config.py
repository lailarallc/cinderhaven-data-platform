"""Shared configuration for all Cinderhaven seed generators.

Defines the product catalog, retailers, distributors, and date windows
that every pipeline generator imports. Single source of truth for IDs,
names, and relationships.
"""
from __future__ import annotations

import os
import random
from datetime import date

# ── FROZEN (cinderhaven-data-v2) ────────────────────────────────────
# Editing any value below re-baselines the entire portfolio.
# Additive regens MUST NOT touch this block.
# Verified against Postgres SSOT 2026-06-04. See CINDERHAVEN_CANONICAL.md.
SEED = 42
WINDOW_START = date(2023, 1, 1)
WINDOW_END = date(2026, 1, 2)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"host=localhost port=5432 dbname=cinderhaven user=postgres password={os.environ.get('POSTGRES_PASSWORD', '')}"
)

# -- Retailers (5 contracted + 1 regional group) --

RETAILERS = [
    {"retailer_id": "RET-WALMART",    "name": "Walmart",      "dispute_portal_name": "RetailLink", "dispute_portal_url": "https://retaillink.walmart.com", "dispute_method": "portal"},
    {"retailer_id": "RET-COSTCO",     "name": "Costco",       "dispute_portal_name": "Costco Vendor Portal", "dispute_portal_url": "https://vendor.costco.com", "dispute_method": "portal"},
    {"retailer_id": "RET-WHOLEFOODS", "name": "Whole Foods",  "dispute_portal_name": "Whole Foods Vendor", "dispute_portal_url": "https://vendor.wholefoods.com", "dispute_method": "email"},
    {"retailer_id": "RET-SPROUTS",    "name": "Sprouts",      "dispute_portal_name": None, "dispute_portal_url": None, "dispute_method": "email"},
    {"retailer_id": "RET-KROGER",     "name": "Kroger",       "dispute_portal_name": "Kroger Vendor Net", "dispute_portal_url": "https://vendornet.kroger.com", "dispute_method": "portal"},
    {"retailer_id": "RET-REGIONAL",   "name": "Regional Group", "dispute_portal_name": None, "dispute_portal_url": None, "dispute_method": "email"},
]

# -- Distributors --

DISTRIBUTORS = [
    {"distributor_id": "DIST-UNFI",  "name": "UNFI",  "type": "national", "margin_pct": 0.22, "payment_terms_days": 30},
    {"distributor_id": "DIST-KEHE",  "name": "KeHE",  "type": "national", "margin_pct": 0.20, "payment_terms_days": 30},
    {"distributor_id": "DIST-DPI",   "name": "DPI Northwest", "type": "regional", "margin_pct": 0.18, "payment_terms_days": 21},
]

# -- Product lines (50 SKUs) --

PRODUCT_LINES = {
    "Artisan Sauces": [
        ("CHP-AS-001", "Smoky Chipotle BBQ Sauce", 8.99, 12, 2.10),
        ("CHP-AS-002", "Roasted Garlic Marinara", 7.49, 12, 1.85),
        ("CHP-AS-003", "Spicy Habanero Hot Sauce", 6.99, 24, 1.45),
        ("CHP-AS-004", "Sweet Thai Chili Sauce", 7.99, 12, 1.90),
        ("CHP-AS-005", "Classic Tomato Basil", 6.49, 12, 1.60),
        ("CHP-AS-006", "Balsamic Fig Glaze", 9.99, 12, 2.40),
        ("CHP-AS-007", "Lemon Herb Chimichurri", 8.49, 12, 2.00),
        ("CHP-AS-008", "Mango Jalapeño Salsa", 6.99, 12, 1.55),
        ("CHP-AS-009", "Truffle Mushroom Sauce", 11.99, 12, 3.20),
        ("CHP-AS-010", "Carolina Gold BBQ", 8.49, 12, 2.05),
    ],
    "Pantry Staples": [
        ("CHP-PS-001", "Stone Ground Mustard", 5.99, 12, 1.30),
        ("CHP-PS-002", "Wildflower Honey", 9.99, 12, 2.80),
        ("CHP-PS-003", "Apple Cider Vinegar", 6.49, 12, 1.40),
        ("CHP-PS-004", "Extra Virgin Olive Oil", 12.99, 6, 4.50),
        ("CHP-PS-005", "Sea Salt Blend", 4.99, 24, 0.90),
        ("CHP-PS-006", "Cracked Black Pepper", 5.49, 24, 1.00),
        ("CHP-PS-007", "Smoked Paprika", 5.99, 24, 1.10),
        ("CHP-PS-008", "Italian Seasoning Blend", 4.49, 24, 0.85),
        ("CHP-PS-009", "Maple Syrup Grade A", 11.49, 12, 3.50),
        ("CHP-PS-010", "Raw Agave Nectar", 7.99, 12, 2.20),
    ],
    "Specialty Condiments": [
        ("CHP-SC-001", "Bourbon Bacon Jam", 9.99, 12, 2.60),
        ("CHP-SC-002", "Caramelized Onion Spread", 8.49, 12, 2.15),
        ("CHP-SC-003", "Pickled Jalapeño Relish", 6.99, 12, 1.50),
        ("CHP-SC-004", "Sun-Dried Tomato Tapenade", 8.99, 12, 2.30),
        ("CHP-SC-005", "Roasted Red Pepper Hummus", 5.99, 12, 1.35),
        ("CHP-SC-006", "Artichoke Spinach Dip", 7.49, 12, 1.95),
        ("CHP-SC-007", "Everything Bagel Spread", 6.99, 12, 1.55),
        ("CHP-SC-008", "Herb Compound Butter", 7.99, 6, 2.40),
        ("CHP-SC-009", "Raspberry Chipotle Glaze", 8.99, 12, 2.25),
        ("CHP-SC-010", "Lemon Curd", 7.49, 12, 1.80),
    ],
    "Dried Goods": [
        ("CHP-DG-001", "Wild Rice Blend", 7.99, 12, 1.85),
        ("CHP-DG-002", "Quinoa Medley", 8.49, 12, 2.00),
        ("CHP-DG-003", "Steel Cut Oats", 5.49, 24, 1.10),
        ("CHP-DG-004", "Organic Lentils", 4.99, 24, 0.95),
        ("CHP-DG-005", "Sun-Dried Tomatoes", 9.99, 12, 2.60),
        ("CHP-DG-006", "Roasted Chickpeas", 6.49, 12, 1.40),
        ("CHP-DG-007", "Trail Mix Premium", 8.99, 12, 2.30),
        ("CHP-DG-008", "Dried Mango Slices", 7.49, 12, 1.75),
        ("CHP-DG-009", "Coconut Flakes Unsweetened", 5.99, 12, 1.25),
        ("CHP-DG-010", "Mixed Nut Butter Granola", 9.49, 12, 2.45),
    ],
    "Snack Bites": [
        ("CHP-SB-001", "Dark Chocolate Sea Salt Bites", 6.99, 24, 1.50),
        ("CHP-SB-002", "Almond Butter Protein Bites", 7.99, 24, 1.80),
        ("CHP-SB-003", "Coconut Cashew Clusters", 8.49, 12, 2.10),
        ("CHP-SB-004", "Spicy Sriracha Crackers", 4.99, 24, 0.95),
        ("CHP-SB-005", "Rosemary Olive Oil Crisps", 5.49, 24, 1.05),
        ("CHP-SB-006", "Honey Walnut Bites", 7.49, 12, 1.70),
        ("CHP-SB-007", "Cheddar Herb Popcorn", 4.49, 24, 0.85),
        ("CHP-SB-008", "Maple Pecan Clusters", 8.99, 12, 2.25),
        ("CHP-SB-009", "Everything Seasoning Pretzels", 5.99, 24, 1.15),
        ("CHP-SB-010", "Tahini Date Energy Bites", 7.99, 12, 1.90),
    ],
}

# Flatten for easy access: list of (sku, name, msrp, case_pack, cogs)
ALL_SKUS = []
for line, products in PRODUCT_LINES.items():
    for sku, name, msrp, case_pack, cogs in products:
        ALL_SKUS.append({
            "sku": sku,
            "product_name": name,
            "product_line": line,
            "msrp": msrp,
            "case_pack_qty": case_pack,
            "cogs_per_unit": cogs,
        })

# -- Retailer store counts and volume tiers --

RETAILER_STORE_COUNTS = {
    "RET-WALMART": 180,
    "RET-COSTCO": 60,
    "RET-WHOLEFOODS": 120,
    "RET-SPROUTS": 90,
    "RET-KROGER": 150,
    "RET-REGIONAL": 40,
}

# Club-channel stores (Costco) move 2.5x the units per location vs grocery.
CHANNEL_VELOCITY_MULT = {
    "RET-WALMART": 1.0,
    "RET-COSTCO": 2.5,
    "RET-WHOLEFOODS": 1.0,
    "RET-SPROUTS": 1.0,
    "RET-KROGER": 1.0,
    "RET-REGIONAL": 1.0,
}

VOLUME_TIERS = ["high", "medium", "low"]
REGIONS = ["Northeast", "Southeast", "Midwest", "West", "Southwest"]
STATES_BY_REGION = {
    "Northeast": ["NY", "NJ", "PA", "CT", "MA", "NH", "VT", "ME", "RI"],
    "Southeast": ["FL", "GA", "NC", "SC", "VA", "TN", "AL", "MS", "LA"],
    "Midwest": ["IL", "OH", "MI", "IN", "WI", "MN", "IA", "MO", "KS"],
    "West": ["CA", "WA", "OR", "CO", "AZ", "NV", "UT", "HI"],
    "Southwest": ["TX", "NM", "OK", "AR"],
}

CARRIERS = ["FedEx", "UPS", "USPS", "LTL Freight", "R+L Carriers"]

DEDUCTION_TYPES = [
    "short_ship", "promo_billback", "slotting", "late_delivery",
    "label_fine", "pallet_fine", "spoilage", "damaged", "pricing_error",
]

DISPUTE_OUTCOMES = ["won", "lost", "partial", "pending"]
EVIDENCE_TYPES = ["BOL", "POD", "invoice", "ASN", "pack_photo", "label_scan", "price_confirmation"]

SEASONALITY = {
    1: 0.75, 2: 0.80, 3: 0.90, 4: 0.95, 5: 1.00, 6: 1.00,
    7: 0.95, 8: 0.90, 9: 1.05, 10: 1.10, 11: 1.35, 12: 1.45,
}

# ── FROZEN (cinderhaven-data-v2) ────────────────────────────────────
# These economic constants drive cited portfolio figures.
# Editing re-baselines the entire portfolio.
# Additive regens MUST NOT touch this block.

# Wholesale pricing multipliers (off MSRP)
# Retailers buy at ~50-65% of MSRP depending on channel
WHOLESALE_MULT = {
    "walmart": 0.50,
    "costco": 0.48,
    "whole_foods": 0.58,
    "sprouts": 0.55,
    "kroger": 0.52,
    "regional": 0.52,
    "unfi": 0.45,
    "kehe": 0.46,
    "dpi": 0.44,
    "dtc": 1.00,  # DTC sells at MSRP
}

TRADE_SPEND_PCT = {  # drives structural trade cost ($9.7M/36mo after 2026-06-12 rate_map relock)
    "walmart": 0.12,
    "costco": 0.10,
    "whole_foods": 0.08,
    "sprouts": 0.09,
    "kroger": 0.10,
    "regional": 0.07,
    "unfi": 0.05,
    "kehe": 0.05,
    "dpi": 0.05,
    "dtc": 0.03,
}

# ── Causal fulfillment model (frozen 2026-06-12) ──────────────────
# Per CAUSAL_FULFILLMENT_DESIGN.md (Shawn-approved). Consumed by the
# Phase 3 seeder groups B-E; isolated RNG streams so they cannot
# disturb the SEED=42 / DEFECT_SEED=300 generation paths.

FULFILLMENT_SEED = 400   # shortfall allocation, receiving discrepancies
EVIDENCE_SEED = 500      # evidence assembly, outcome conditioning

# Design §2.1 — per-retailer unit fill-rate targets (realistic specialty
# food ranges: 7-15% of shipments fail in-full with 5-10% shortfall severity,
# yielding 85-93% in-full rate and 83-88% OTIF).
RETAILER_FILL_TARGET = {
    "walmart": 0.991,
    "kroger": 0.992,
    "costco": 0.993,
    "whole_foods": 0.994,
    "sprouts": 0.993,
    "regional": 0.995,
}
# Design §1.6 — distributors fill 2-3 points above the retailer portfolio
DISTRIBUTOR_FILL_TARGET = {"unfi": 0.995, "kehe": 0.995, "dpi": 0.996}
# Design §2.1 — fill drops during the Nov-Dec seasonal peak, in points
Q4_FILL_DIP = 0.004

# Design §1.4 — shortfall-reason mix per retailer (shares of shortage units)
SHORTFALL_REASON_MIX = {
    "walmart":     {"allocation": 0.65, "production": 0.18, "carrier": 0.10, "data_defect": 0.07},
    "kroger":      {"allocation": 0.60, "production": 0.20, "carrier": 0.12, "data_defect": 0.08},
    "costco":      {"allocation": 0.55, "production": 0.22, "carrier": 0.13, "data_defect": 0.10},
    "whole_foods": {"allocation": 0.35, "production": 0.20, "carrier": 0.20, "data_defect": 0.25},
    "sprouts":     {"allocation": 0.35, "production": 0.30, "carrier": 0.20, "data_defect": 0.15},
    "regional":    {"allocation": 0.35, "production": 0.20, "carrier": 0.25, "data_defect": 0.20},
}
# Design §1.6 — distributor shortfalls skew toward allocation
DISTRIBUTOR_SHORTFALL_MIX = {
    "allocation": 0.68, "production": 0.17, "carrier": 0.10, "data_defect": 0.05,
}

# Design §1.5 — receiving-discrepancy rate per retailer (share of shipment lines).
# Tuned to realistic CPG ranges (0.6-1.0%) so the shipment-level received-complete rate
# (receipt lines, used by the OTIF pipeline) lands in the 85-93% target band.
RECEIVING_DISCREPANCY_RATE = {
    "walmart": 0.006,
    "whole_foods": 0.006,
    "kroger": 0.005,
    "sprouts": 0.005,
    "costco": 0.004,
    "regional": 0.004,
}
# Design §1.5 — discrepancy-reason mix; Whole Foods skews to quality rejection
RECEIVING_DISCREPANCY_MIX = {
    "default":     {"carrier_damage": 0.50, "receiving_miscount": 0.30, "quality_rejection": 0.20},
    "whole_foods": {"carrier_damage": 0.40, "receiving_miscount": 0.25, "quality_rejection": 0.35},
}

# Design §2.2 — per-retailer transit-day ranges (delivery = ship + transit).
# Replaces the uniform 1-7 day draw that produced identical 71% lateness
# across all six retailers (plausibility audit §2.6 realism finding).
RETAILER_TRANSIT_DAYS = {
    "walmart": (1, 3),
    "kroger": (1, 3),
    "costco": (2, 4),
    "whole_foods": (2, 5),
    "sprouts": (2, 4),
    "regional": (3, 6),
}

# Design §2.2 — OTIF timing: retailer on-time window (days); internal ±1
RETAILER_OTIF_WINDOW_DAYS = {
    "walmart": 0,
    "kroger": 1,
    "costco": 2,
    "whole_foods": 1,
    "sprouts": 1,
    "regional": 2,
}
INTERNAL_OTIF_TOLERANCE_DAYS = 1
INTERNAL_ONTIME_TARGET = 0.96  # share of shipments departing inside the internal window

# Design §2.4 — evidence tier -> dispute outcome distributions
EVIDENCE_OUTCOME_WEIGHTS = {
    "strong":   {"won": 0.45, "partial": 0.35, "lost": 0.10, "pending": 0.10},
    "moderate": {"won": 0.15, "partial": 0.25, "lost": 0.40, "pending": 0.20},
    "weak":     {"won": 0.05, "partial": 0.15, "lost": 0.55, "pending": 0.25},
}
# Partial outcomes recover a uniform fraction of the deduction
# (midpoints 0.57 / 0.48 / 0.53 per the design's effective-rate math)
PARTIAL_RECOVERY_RANGE = {
    "strong":   (0.40, 0.74),
    "moderate": (0.28, 0.68),
    "weak":     (0.33, 0.73),
}
# Design §2.5 — evidence factor thresholds (weakest link sets the tier)
EVIDENCE_DQ_STRONG_MIN = 75       # data quality score at/above -> strong factor
EVIDENCE_DQ_WEAK_MAX = 50         # below -> weak factor
EVIDENCE_FILING_STRONG_DAYS = 30  # filed within -> strong factor
EVIDENCE_FILING_MODERATE_DAYS = 60

# Design §3.3 + decision #3 — intentional unclassified remittance residual.
# The canonical figure states the ACHIEVED classification rate, not this target.
REMITTANCE_RESIDUAL_TARGET = 0.02
REMITTANCE_SEED = 600   # Group E: isolated stream for residual fraction draws

# Design §2.3 (Group C) — operational chargeback enforcement.
# Triggering events: per-line shipment shortfalls, deliveries beyond the
# retailer MABD window (requested ship + max transit + OTIF window,
# reusing RETAILER_TRANSIT_DAYS / RETAILER_OTIF_WINDOW_DAYS above), and
# receiving discrepancies (carrier_damage / quality_rejection only —
# decision #2 keeps receiving_discrepancy a separate category, never
# folded into shortage chargebacks; receiving_miscount feeds short_ship
# deductions instead, per design §3.1).
# p(assess) = share of triggering events the retailer's compliance
# program converts to a chargeback. Short-ship assessment lifts where
# raw.retailer_rules.auto_deduct is true (Walmart, Kroger in seeded
# rules). Fine = rate × event dollar value, clamped. Assessment rates
# unchanged from the original calibration — fewer shortfall events
# naturally produce proportionally fewer chargebacks.
SHORT_SHIP_CB_ASSESS_BASE = {
    "walmart": 0.52, "kroger": 0.48, "costco": 0.35,
    "whole_foods": 0.45, "sprouts": 0.40, "regional": 0.25,
}
CB_AUTO_DEDUCT_LIFT = 1.25
SHORT_SHIP_CB_RATE = {
    "walmart": 0.14, "kroger": 0.13, "costco": 0.10,
    "whole_foods": 0.12, "sprouts": 0.10, "regional": 0.08,
}
LATE_CB_ASSESS = {
    "walmart": 0.85, "kroger": 0.70, "costco": 0.50,
    "whole_foods": 0.60, "sprouts": 0.55, "regional": 0.30,
}
LATE_CB_RATE = {
    "walmart": 0.15, "kroger": 0.12, "costco": 0.08,
    "whole_foods": 0.12, "sprouts": 0.11, "regional": 0.06,
}
RECEIVING_CB_ASSESS = {
    "walmart": 0.26, "kroger": 0.22, "costco": 0.16,
    "whole_foods": 0.28, "sprouts": 0.20, "regional": 0.12,
}
RECEIVING_CB_FEE_MULT = 1.2  # discrepant value + 20% dock-handling fee
CHARGEBACK_CLAMP = {
    "short_ship": (50.0, 2500.0),
    "late_delivery": (75.0, 1500.0),
    "receiving_discrepancy": (25.0, 2000.0),
}

# Group C — event-driven short-ship / late deductions (design §3.1:
# amounts proportional to the shorted / shipped value). Receiving
# miscounts deduct the exact discrepant value (AP short-pays the
# invoice/receipt mismatch at face value, no rate or clamp). Rates are
# calibrated so total deduction dollars stay in the §4.2 operational-
# waste neighborhood (~$480K/yr) — the event-driven rows replace the
# legacy random short_ship/late_delivery draws at similar dollar scale.
SHORT_SHIP_DED_ASSESS = 0.90
SHORT_SHIP_DED_RATE = 0.062
SHORT_SHIP_DED_CLAMP = (20.0, 1500.0)
LATE_DED_ASSESS = 0.70
LATE_DED_RATE = 0.03
LATE_DED_CLAMP = (25.0, 500.0)

# Design §1.6 (Group C2) — distributor operational enforcement.
# Triggering events: per-line shipment shortfalls and deliveries beyond
# the distributor's order-to-door window (po_date + window days; there
# is no requested_ship_date on distributor orders, so the window is the
# observable MABD analog — only the slowest ~8% of deliveries qualify).
# No receipt lines on this channel (§1.6: discrepancies arrive via
# deductions), so there is NO receiving_discrepancy category here.
# "Flexible delivery windows" is encoded as a generous window plus low
# assessment probabilities, not zero enforcement. Calibrated below the
# retailer §2.3 bands: short-ship + late 0.2–0.45% of distributor
# shipped $; total compliance 0.7–1.1% with the kept quality-linked
# chargebacks (damaged / pricing_error) unchanged.
DIST_DELIVERY_WINDOW_DAYS = 12
DIST_SHORT_SHIP_CB_ASSESS = {"unfi": 0.40, "kehe": 0.35, "dpi": 0.25}
DIST_SHORT_SHIP_CB_RATE = {"unfi": 0.10, "kehe": 0.09, "dpi": 0.07}
DIST_LATE_CB_ASSESS = {"unfi": 0.30, "kehe": 0.25, "dpi": 0.15}
DIST_LATE_CB_RATE = {"unfi": 0.06, "kehe": 0.05, "dpi": 0.04}
DIST_CHARGEBACK_CLAMP = {
    "short_ship": (40.0, 2000.0),
    "late_delivery": (50.0, 1200.0),
}
DIST_SHORT_SHIP_DED_ASSESS = 0.85
DIST_SHORT_SHIP_DED_RATE = 0.06
DIST_SHORT_SHIP_DED_CLAMP = (20.0, 1200.0)
DIST_LATE_DED_ASSESS = 0.45
DIST_LATE_DED_RATE = 0.025
DIST_LATE_DED_CLAMP = (20.0, 400.0)

# Design §2.5 / §3.2 (Group D) — causal evidence assembly, dispute
# selection, and tier-conditioned outcomes, both wholesale channels.
# Evidence tier = weakest link across the §2.5 factors. Retailer
# factors: POD (drawn below, persisted in the dispute-evidence rows),
# ASN (shipments.asn_sent/asn_sent_late), pack verification
# (pack_records.pack_verification per PACK_VERIFICATION_TIER), product
# data quality (defect-profile score of the order's largest-line_total
# SKU, ties broken sku-ascending, vs EVIDENCE_DQ_* above), and filing
# timeliness (drawn delay, clipped to the deduction's dispute_deadline
# when one exists). Distributor factors per §1.6's simpler channel:
# POD (delivery_date present), data quality, filing (no deadline
# column, uncapped) — no ASN fields or pack records exist there.
# Streams: EVIDENCE_SEED+0 retailer assembly (2 draws/deduction:
# POD state, filing delay), +1 retailer outcomes, +2 retailer dispute
# selection (1 draw/deduction); +10/+11/+12 the distributor parallels
# (assembly = 1 filing draw/deduction). Selection rides its own stream
# so outcome recalibration can never move who gets disputed.
# Calibrated 2026-06-12 with an analytic dry-run against the frozen
# Group C2 deduction state (cinderhaven-causal-fulfillment/
# verification/calibrate_groupD.py): expected blended recovery 16.49%
# of combined wholesale deduction dollars (canonical endpoint 16.5%),
# retailer dispute rate 40.0% (legacy 40%), distributor 37.2%
# (legacy 35%).
RET_POD_STATE_P = {            # (clean, partial, missing) by carrier class
    "parcel": (0.92, 0.05, 0.03),
    "ltl": (0.80, 0.12, 0.08),  # LTL paperwork is messier
}
RET_FILING_DELAY_P = (0.78, 0.16, 0.06)   # P(file ≤30d, 31-60d, 61-90d)
DIST_FILING_DELAY_P = (0.78, 0.16, 0.06)
PACK_VERIFICATION_TIER = {     # §2.5 row 3; weight_check reads as
    "scan_verified": "strong",  # instrument-verified (flagged in the
    "weight_check": "strong",   # Group D verification doc §1)
    "manual_count": "moderate",
}
# Tier-conditioned dispute propensity — the brand triages by
# winnability (share of deductions disputed, by evidence tier).
RET_DISPUTE_PROPENSITY = {"strong": 0.88, "moderate": 0.36, "weak": 0.16}
DIST_DISPUTE_PROPENSITY = {"strong": 0.45, "moderate": 0.35, "weak": 0.25}
LABOR_HOURS_BY_TIER = {        # weak evidence costs more hours to work
    "strong": (0.25, 2.5),
    "moderate": (0.5, 3.5),
    "weak": (1.0, 5.0),
}
DISPUTE_METHOD_PHONE_P = 0.08  # else the retailer's dispute_method
DISPUTE_CLOSE_DAYS = {"retailer": (14, 90), "distributor": (14, 75)}
# ── END FROZEN BLOCK ───────────────────────────────────────────────

# ── SCENARIO SUPPORT ──────────────────────────────────────────────
# "baseline" = canonical v2, read by all portfolio pieces.
# "distressed" = v1-style operational mess, consumed ONLY by
# trade-spend-diagnostic. Controlled by env var; default is baseline.
SCENARIO = os.environ.get("CINDERHAVEN_SCENARIO", "baseline")

DISTRESSED_DEDUCTION_TYPES = DEDUCTION_TYPES + ["vague"]

VAGUE_TEMPLATES = [
    "Code {code}: {label}",
    "Promo allowance",
    "Marketing chargeback",
    "Audit adjustment",
    "Misc deduction — see invoice",
    "Cash discount take-down",
    "Slotting reconciliation",
    "Trade spend true-up",
    "Allowance reconciliation",
    "Compliance fee",
]
# ── END SCENARIO SUPPORT ─────────────────────────────────────────

# ── QUADRANT ARCHETYPE ASSIGNMENTS ──────────────────────────────
# Drives distribution breadth (ACV%) and velocity (SPPD) variance
# for the Spin Rate quadrant chart. NOT frozen — can be adjusted
# without re-baselining portfolio financials.

SKU_ARCHETYPES = {
    # Stars: wide distribution + high velocity (upper-right quadrant)
    "CHP-AS-001": "star",
    "CHP-AS-002": "star",
    "CHP-AS-006": "star",
    "CHP-PS-002": "star",
    "CHP-PS-009": "star",
    "CHP-SC-001": "star",
    "CHP-DG-007": "star",
    "CHP-SB-001": "star",

    # Hidden Gems: narrow distribution + high velocity (upper-left)
    "CHP-AS-009": "hidden_gem",
    "CHP-PS-004": "hidden_gem",
    "CHP-SC-002": "hidden_gem",
    "CHP-SC-009": "hidden_gem",
    "CHP-DG-005": "hidden_gem",
    "CHP-SB-003": "hidden_gem",
    "CHP-SB-008": "hidden_gem",

    # Wide but Dead: wide distribution + low velocity (lower-right)
    "CHP-PS-005": "wide_dead",
    "CHP-PS-006": "wide_dead",
    "CHP-PS-008": "wide_dead",
    "CHP-DG-003": "wide_dead",
    "CHP-DG-004": "wide_dead",
    "CHP-SB-004": "wide_dead",
    "CHP-SB-007": "wide_dead",

    # Question Marks: narrow distribution + low velocity (lower-left)
    "CHP-AS-008": "question",
    "CHP-SC-006": "question",
    "CHP-SC-007": "question",
    "CHP-DG-006": "question",
    "CHP-DG-009": "question",
    "CHP-SB-009": "question",

    # At-Risk: moderate distribution + declining velocity
    "CHP-AS-010": "at_risk",
    "CHP-SC-010": "at_risk",
    "CHP-SB-010": "at_risk",

    # Fading: above-median velocity declining over time (watchlist candidates)
    "CHP-PS-001": "fading",
    "CHP-DG-002": "fading",
    "CHP-SB-002": "fading",
}

ARCHETYPE_DISTRIBUTION = {
    "star":       (0.50, 0.65),
    "hidden_gem": (0.05, 0.15),
    "wide_dead":  (0.40, 0.55),
    "question":   (0.06, 0.18),
    "at_risk":    (0.25, 0.40),
    "fading":     (0.25, 0.40),
    "moderate":   (0.20, 0.35),
}

ARCHETYPE_VELOCITY_MULT = {
    "star":       (2.5, 3.5),
    "hidden_gem": (3.0, 5.0),
    "wide_dead":  (0.25, 0.55),
    "question":   (0.35, 0.75),
    "at_risk":    (1.8, 2.5),
    "fading":     (2.2, 3.0),
    "moderate":   (0.9, 1.8),
}
# ── END QUADRANT ARCHETYPES ─────────────────────────────────────

# ── SKU-LEVEL SEASONAL PROFILES ──────────────────────────────────
# Replaces the uniform SEASONALITY with per-SKU monthly multipliers.
# Each profile shape is month → raw multiplier (unnormalized).
# At import time, profiles are scaled so their annual mean matches
# the uniform SEASONALITY mean — this preserves annual totals while
# redistributing velocity across quarters.
# NOT frozen — can be adjusted without re-baselining portfolio
# financials (annual envelope unchanged, only quarterly shape moves).

SEASONAL_PROFILE_SHAPES = {
    "grilling": {
        1: 0.65, 2: 0.70, 3: 0.85, 4: 1.05, 5: 1.30, 6: 1.40,
        7: 1.35, 8: 1.25, 9: 1.00, 10: 0.85, 11: 0.70, 12: 0.65,
    },
    "baking": {
        1: 0.90, 2: 0.85, 3: 0.80, 4: 0.75, 5: 0.70, 6: 0.65,
        7: 0.65, 8: 0.70, 9: 0.95, 10: 1.20, 11: 1.50, 12: 1.65,
    },
    "snack_flat": {
        1: 0.90, 2: 0.92, 3: 0.95, 4: 0.98, 5: 1.00, 6: 1.02,
        7: 1.00, 8: 0.98, 9: 1.02, 10: 1.05, 11: 1.10, 12: 1.12,
    },
    "gift_spike": {
        1: 0.50, 2: 0.60, 3: 0.70, 4: 0.80, 5: 0.85, 6: 0.85,
        7: 0.80, 8: 0.85, 9: 1.00, 10: 1.20, 11: 1.70, 12: 2.00,
    },
    "emerging": {
        1: 0.70, 2: 0.75, 3: 0.80, 4: 0.85, 5: 0.90, 6: 0.95,
        7: 1.00, 8: 1.05, 9: 1.10, 10: 1.15, 11: 1.20, 12: 1.25,
    },
    "pantry_staple": {
        1: 0.92, 2: 0.93, 3: 0.95, 4: 0.97, 5: 1.00, 6: 1.00,
        7: 0.98, 8: 0.97, 9: 1.00, 10: 1.03, 11: 1.10, 12: 1.15,
    },
}

SKU_SEASONAL_PROFILE = {
    "CHP-AS-001": "grilling",      # Smoky Chipotle BBQ Sauce
    "CHP-AS-002": "grilling",      # Roasted Garlic Marinara
    "CHP-AS-003": "grilling",      # Spicy Habanero Hot Sauce
    "CHP-AS-004": "grilling",      # Sweet Thai Chili Sauce
    "CHP-AS-005": "grilling",      # Classic Tomato Basil
    "CHP-AS-006": "gift_spike",    # Balsamic Fig Glaze
    "CHP-AS-007": "grilling",      # Lemon Herb Chimichurri
    "CHP-AS-008": "grilling",      # Mango Jalapeño Salsa
    "CHP-AS-009": "gift_spike",    # Truffle Mushroom Sauce
    "CHP-AS-010": "grilling",      # Carolina Gold BBQ

    "CHP-PS-001": "pantry_staple", # Stone Ground Mustard
    "CHP-PS-002": "gift_spike",    # Wildflower Honey
    "CHP-PS-003": "pantry_staple", # Apple Cider Vinegar
    "CHP-PS-004": "pantry_staple", # Extra Virgin Olive Oil
    "CHP-PS-005": "pantry_staple", # Sea Salt Blend
    "CHP-PS-006": "pantry_staple", # Cracked Black Pepper
    "CHP-PS-007": "baking",        # Smoked Paprika
    "CHP-PS-008": "baking",        # Italian Seasoning Blend
    "CHP-PS-009": "baking",        # Maple Syrup Grade A
    "CHP-PS-010": "pantry_staple", # Raw Agave Nectar

    "CHP-SC-001": "gift_spike",    # Bourbon Bacon Jam
    "CHP-SC-002": "gift_spike",    # Caramelized Onion Spread
    "CHP-SC-003": "grilling",      # Pickled Jalapeño Relish
    "CHP-SC-004": "gift_spike",    # Sun-Dried Tomato Tapenade
    "CHP-SC-005": "grilling",      # Roasted Red Pepper Hummus
    "CHP-SC-006": "emerging",      # Artichoke Spinach Dip
    "CHP-SC-007": "emerging",      # Everything Bagel Spread
    "CHP-SC-008": "gift_spike",    # Herb Compound Butter
    "CHP-SC-009": "gift_spike",    # Raspberry Chipotle Glaze
    "CHP-SC-010": "pantry_staple", # Lemon Curd

    "CHP-DG-001": "baking",        # Wild Rice Blend
    "CHP-DG-002": "pantry_staple", # Quinoa Medley
    "CHP-DG-003": "baking",        # Steel Cut Oats
    "CHP-DG-004": "pantry_staple", # Organic Lentils
    "CHP-DG-005": "grilling",      # Sun-Dried Tomatoes
    "CHP-DG-006": "snack_flat",    # Roasted Chickpeas
    "CHP-DG-007": "snack_flat",    # Trail Mix Premium
    "CHP-DG-008": "snack_flat",    # Dried Mango Slices
    "CHP-DG-009": "baking",        # Coconut Flakes Unsweetened
    "CHP-DG-010": "emerging",      # Mixed Nut Butter Granola

    "CHP-SB-001": "gift_spike",    # Dark Chocolate Sea Salt Bites
    "CHP-SB-002": "emerging",      # Almond Butter Protein Bites
    "CHP-SB-003": "gift_spike",    # Coconut Cashew Clusters
    "CHP-SB-004": "snack_flat",    # Spicy Sriracha Crackers
    "CHP-SB-005": "snack_flat",    # Rosemary Olive Oil Crisps
    "CHP-SB-006": "gift_spike",    # Honey Walnut Bites
    "CHP-SB-007": "snack_flat",    # Cheddar Herb Popcorn
    "CHP-SB-008": "gift_spike",    # Maple Pecan Clusters
    "CHP-SB-009": "snack_flat",    # Everything Seasoning Pretzels
    "CHP-SB-010": "emerging",      # Tahini Date Energy Bites
}

_UNIFORM_SEASONALITY_MEAN = sum(SEASONALITY.values()) / 12


def _normalize_seasonal_profiles():
    """Scale each profile so its annual mean matches the uniform SEASONALITY mean."""
    normalized = {}
    for name, shape in SEASONAL_PROFILE_SHAPES.items():
        raw_mean = sum(shape.values()) / 12
        scale = _UNIFORM_SEASONALITY_MEAN / raw_mean
        normalized[name] = {m: round(v * scale, 4) for m, v in shape.items()}
    return normalized


SEASONAL_PROFILES = _normalize_seasonal_profiles()


def get_sku_seasonal(sku: str, month: int) -> float:
    """Return the normalized seasonal multiplier for a SKU in a given month."""
    profile_name = SKU_SEASONAL_PROFILE.get(sku, "pantry_staple")
    return SEASONAL_PROFILES[profile_name][month]

# ── END SEASONAL PROFILES ────────────────────────────────────────

# ── DTC COST LAYERS (isolated RNG stream, seed=700) ──────────────
# Shipping/fulfillment, packaging-aware returns, platform fees.
# Isolated from SEED=42 order generation so existing order data is
# unchanged. Only DTC cost columns are affected.
DTC_COST_SEED = 700

# SKU packaging type — drives return/damage rates in seed_dtc.py
SKU_PACKAGING = {
    # Artisan Sauces: all glass bottles/jars
    "CHP-AS-001": "glass", "CHP-AS-002": "glass", "CHP-AS-003": "glass",
    "CHP-AS-004": "glass", "CHP-AS-005": "glass", "CHP-AS-006": "glass",
    "CHP-AS-007": "glass", "CHP-AS-008": "glass", "CHP-AS-009": "glass",
    "CHP-AS-010": "glass",
    # Pantry Staples: glass for liquids/jars, non-glass for dry spices
    "CHP-PS-001": "glass",      # Stone Ground Mustard (jar)
    "CHP-PS-002": "glass",      # Wildflower Honey (jar)
    "CHP-PS-003": "glass",      # Apple Cider Vinegar (bottle)
    "CHP-PS-004": "glass",      # Extra Virgin Olive Oil (bottle)
    "CHP-PS-005": "non_glass",  # Sea Salt Blend (canister)
    "CHP-PS-006": "non_glass",  # Cracked Black Pepper (grinder)
    "CHP-PS-007": "non_glass",  # Smoked Paprika (tin)
    "CHP-PS-008": "non_glass",  # Italian Seasoning Blend (pouch)
    "CHP-PS-009": "glass",      # Maple Syrup Grade A (bottle)
    "CHP-PS-010": "glass",      # Raw Agave Nectar (bottle)
    # Specialty Condiments: mostly glass jars, a few plastic tubs
    "CHP-SC-001": "glass",      # Bourbon Bacon Jam (jar)
    "CHP-SC-002": "glass",      # Caramelized Onion Spread (jar)
    "CHP-SC-003": "glass",      # Pickled Jalapeño Relish (jar)
    "CHP-SC-004": "glass",      # Sun-Dried Tomato Tapenade (jar)
    "CHP-SC-005": "non_glass",  # Roasted Red Pepper Hummus (tub)
    "CHP-SC-006": "non_glass",  # Artichoke Spinach Dip (tub)
    "CHP-SC-007": "glass",      # Everything Bagel Spread (jar)
    "CHP-SC-008": "non_glass",  # Herb Compound Butter (tub)
    "CHP-SC-009": "glass",      # Raspberry Chipotle Glaze (bottle)
    "CHP-SC-010": "glass",      # Lemon Curd (jar)
    # Dried Goods: all pouches/bags
    "CHP-DG-001": "non_glass", "CHP-DG-002": "non_glass",
    "CHP-DG-003": "non_glass", "CHP-DG-004": "non_glass",
    "CHP-DG-005": "non_glass", "CHP-DG-006": "non_glass",
    "CHP-DG-007": "non_glass", "CHP-DG-008": "non_glass",
    "CHP-DG-009": "non_glass", "CHP-DG-010": "non_glass",
    # Snack Bites: all bags/pouches
    "CHP-SB-001": "non_glass", "CHP-SB-002": "non_glass",
    "CHP-SB-003": "non_glass", "CHP-SB-004": "non_glass",
    "CHP-SB-005": "non_glass", "CHP-SB-006": "non_glass",
    "CHP-SB-007": "non_glass", "CHP-SB-008": "non_glass",
    "CHP-SB-009": "non_glass", "CHP-SB-010": "non_glass",
}

# Quarterly fulfillment cost as % of order total (base rate before
# weight multiplier). Q4 is highest due to carrier surcharges and
# insulated holiday packaging.
DTC_FULFILLMENT_RATE_BY_QUARTER = {
    1: (0.185, 0.205),
    2: (0.175, 0.195),
    3: (0.185, 0.205),
    4: (0.210, 0.235),
}

# Weight multiplier per product line — glass/heavy items cost more to ship
DTC_FULFILLMENT_WEIGHT_MULT = {
    "Artisan Sauces":       (1.10, 1.25),
    "Pantry Staples":       (0.95, 1.10),
    "Specialty Condiments": (1.05, 1.20),
    "Dried Goods":          (0.80, 0.90),
    "Snack Bites":          (0.75, 0.85),
}

# Shopify platform transaction fee (on top of payment processing)
DTC_PLATFORM_FEE_RATE = (0.020, 0.028)

# Packaging-aware return/damage rates (probability per order containing
# that packaging type). Applied per-order weighted by glass/non-glass
# SKU value in the order.
DTC_RETURN_RATE_GLASS = (0.055, 0.075)
DTC_RETURN_RATE_NON_GLASS = (0.020, 0.035)

DTC_REFUND_REASONS_GLASS = [
    "breakage_in_transit", "breakage_in_transit", "transit_damage",
    "defective", "customer_request",
]
DTC_REFUND_REASONS_NON_GLASS = [
    "customer_request", "customer_request", "wrong_item",
    "not_as_described", "quality_issue",
]
# ── END DTC COST LAYERS ──────────────────────────────────────────


def init_rng(seed: int = SEED) -> random.Random:
    """Create a seeded RNG for deterministic generation."""
    return random.Random(seed)


# ── DEFECT PROFILE (isolated RNG stream, seed=300) ────────────────
# Changes here CANNOT cascade into trade/deduction/chargeback-count
# generation because the defect_rng is a separate stream.
DEFECT_SEED = 300
GTIN_INVALID_RATE = 0.20  # ~20% of SKUs get corrupted check digit

MISSING_RATES = {
    "case_length_in": 0.12,
    "case_width_in": 0.12,
    "case_height_in": 0.12,
    "unit_weight_lbs": 0.08,
    "case_weight_lbs": 0.08,
    "brand_owner": 0.02,
    "country_of_origin": 0.03,
    "subcategory": 0.10,
}


def _gtin14_check_digit(digits_13: str) -> str:
    """Compute GS1 check digit for a 13-digit GTIN-14 prefix."""
    total = 0
    for i, d in enumerate(digits_13):
        weight = 3 if i % 2 == 0 else 1
        total += int(d) * weight
    return str((10 - total % 10) % 10)


def compute_defect_profile(seed: int = DEFECT_SEED) -> dict:
    """Deterministic defect profile for all 50 SKUs.

    Returns {sku: {gtin14, upc, gtin_valid, missing_fields, quality_score}}
    where quality_score is 0-100 (mean ~70, range 40-95).

    Called by seed_shared (to populate product_master) and by
    seed_retailer/seed_distributor (to weight chargeback distribution).
    Same seed → same result everywhere.
    """
    rng = init_rng(seed)
    profile = {}

    for i, p in enumerate(ALL_SKUS):
        sku = p["sku"]

        # Valid GTIN-14: indicator "0" + company prefix "061414" + 6-digit item ref + check
        prefix_13 = f"0061414{i:06d}"
        check = _gtin14_check_digit(prefix_13)
        valid_gtin = prefix_13 + check

        # Corrupt ~20% by flipping the check digit
        is_gtin_valid = rng.random() >= GTIN_INVALID_RATE
        if is_gtin_valid:
            gtin14 = valid_gtin
        else:
            bad_check = str((int(check) + rng.randint(1, 9)) % 10)
            gtin14 = prefix_13 + bad_check

        upc = gtin14[1:]  # UPC-13 = GTIN-14 without indicator digit

        # Field missingness per MISSING_RATES
        missing_fields = {}
        for field, rate in MISSING_RATES.items():
            missing_fields[field] = rng.random() < rate

        # Quality score: calibrated to mean ~70, range 40-95
        score = 82
        if not is_gtin_valid:
            score -= rng.randint(20, 35)
        n_missing = sum(1 for v in missing_fields.values() if v)
        score -= n_missing * rng.randint(6, 12)
        score += rng.randint(-3, 5)
        score = max(40, min(95, score))

        profile[sku] = {
            "gtin14": gtin14,
            "upc": upc,
            "gtin_valid": is_gtin_valid,
            "missing_fields": missing_fields,
            "quality_score": score,
        }

    return profile
# ── END DEFECT PROFILE ────────────────────────────────────────────
