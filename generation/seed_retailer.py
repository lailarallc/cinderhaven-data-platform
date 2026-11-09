"""Seed generator for the retailer pipeline.

Tables generated (50 SKUs, 3-year window):
  - retailer_orders (~46,000 orders)
  - retailer_order_lines (~185,000 lines)
  - retailer_shipments (~46,000) + retailer_shipment_lines (~189,000)
  - retailer_receipt_lines (~189,000)
  - retailer_remittances (~220)
  - retailer_deductions (~20,000 — legacy stream + event-driven short/late)
  - retailer_disputes (~4,200)
  - retailer_dispute_evidence (~12,600)
  - retailer_chargebacks (~5,500 — Path A data-defect + event-driven)
  - retailer_post_audit_claims (~230)
  - retailer_pack_records (~46,000)

Requires seed_shared.py to have been run first (retailers, products, stores exist).

Usage:
    python generation/seed_retailer.py
"""
from __future__ import annotations

import io
import math
import psycopg2
from datetime import date, timedelta

from seed_config import (
    ALL_SKUS, DATABASE_URL, RETAILERS, CARRIERS, DEDUCTION_TYPES,
    DISPUTE_OUTCOMES, EVIDENCE_TYPES, SEASONALITY,
    WINDOW_START, WINDOW_END, init_rng, compute_defect_profile,
    DEFECT_SEED,
    FULFILLMENT_SEED, RETAILER_FILL_TARGET, Q4_FILL_DIP,
    SHORTFALL_REASON_MIX, RECEIVING_DISCREPANCY_RATE,
    RECEIVING_DISCREPANCY_MIX, RETAILER_TRANSIT_DAYS,
    RETAILER_OTIF_WINDOW_DAYS,
    INTERNAL_ONTIME_TARGET, EVIDENCE_DQ_STRONG_MIN,
    SHORT_SHIP_CB_ASSESS_BASE, CB_AUTO_DEDUCT_LIFT, SHORT_SHIP_CB_RATE,
    LATE_CB_ASSESS, LATE_CB_RATE, RECEIVING_CB_ASSESS,
    RECEIVING_CB_FEE_MULT, CHARGEBACK_CLAMP,
    SHORT_SHIP_DED_ASSESS, SHORT_SHIP_DED_RATE, SHORT_SHIP_DED_CLAMP,
    LATE_DED_ASSESS, LATE_DED_RATE, LATE_DED_CLAMP,
    EVIDENCE_SEED, EVIDENCE_DQ_WEAK_MAX, EVIDENCE_OUTCOME_WEIGHTS,
    PARTIAL_RECOVERY_RANGE, RET_POD_STATE_P, RET_FILING_DELAY_P,
    PACK_VERIFICATION_TIER, RET_DISPUTE_PROPENSITY, LABOR_HOURS_BY_TIER,
    DISPUTE_METHOD_PHONE_P, DISPUTE_CLOSE_DAYS,
    TRADE_SPEND_PCT, REMITTANCE_RESIDUAL_TARGET, REMITTANCE_SEED,
)


COPY_CHUNK_SIZE = 50_000

def copy_rows(cur, table: str, columns: list[str], rows: list[tuple]):
    cols = ", ".join(columns)
    sql = f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT text, NULL '\\N')"
    for start in range(0, len(rows), COPY_CHUNK_SIZE):
        chunk = rows[start:start + COPY_CHUNK_SIZE]
        buf = io.StringIO()
        for row in chunk:
            line = "\t".join("\\N" if v is None else str(v) for v in row)
            buf.write(line + "\n")
        buf.seek(0)
        cur.copy_expert(sql, buf)


RETAILER_VOLUME_WEIGHT = {
    "RET-WALMART": 1.3,
    "RET-COSTCO": 0.8,
    "RET-WHOLEFOODS": 1.0,
    "RET-KROGER": 1.2,
    "RET-SPROUTS": 0.9,
    "RET-REGIONAL": 0.7,
}

# retailer_id -> seed_config key (fill targets, mixes, transit profiles)
RETAILER_KEY = {
    "RET-WALMART": "walmart",
    "RET-COSTCO": "costco",
    "RET-WHOLEFOODS": "whole_foods",
    "RET-SPROUTS": "sprouts",
    "RET-KROGER": "kroger",
    "RET-REGIONAL": "regional",
}

def generate_orders_and_lines(rng):
    """Generate retailer orders and their line items."""
    orders = []
    lines = []
    order_num = 0

    current = WINDOW_START
    while current <= WINDOW_END:
        month_mult = SEASONALITY.get(current.month, 1.0)
        for ret in RETAILERS:
            weight = RETAILER_VOLUME_WEIGHT.get(ret["retailer_id"], 1.0)
            orders_this_week = int(rng.gauss(50, 10) * month_mult * weight)
            orders_this_week = max(8, orders_this_week)

            for _ in range(orders_this_week):
                order_num += 1
                order_id = f"RO-{order_num:06d}"
                po_number = f"PO-{ret['retailer_id'][-3:]}-{order_num:06d}"
                po_date = current + timedelta(days=rng.randint(0, 6))
                if po_date > WINDOW_END:
                    continue

                n_lines = rng.choices([2, 3, 4, 5, 7], weights=[10, 25, 35, 20, 10])[0]
                chosen_skus = rng.sample(ALL_SKUS, min(n_lines, len(ALL_SKUS)))

                total_units = 0
                total_value = 0.0
                order_lines = []

                for sku_info in chosen_skus:
                    units = rng.choices(
                        [24, 48, 72, 96, 144],
                        weights=[15, 30, 30, 15, 10]
                    )[0]
                    key = ret["name"].lower().replace(" ", "_")
                    if key == "regional_group":
                        key = "regional"
                    from seed_config import WHOLESALE_MULT
                    mult = WHOLESALE_MULT.get(key, 0.52)
                    unit_price = round(sku_info["msrp"] * mult, 2)
                    line_total = round(units * unit_price, 2)

                    total_units += units
                    total_value += line_total
                    order_lines.append((
                        order_id, sku_info["sku"], units, unit_price, line_total,
                    ))

                ship_date = po_date + timedelta(days=rng.randint(1, 5))
                orders.append((
                    order_id, ret["retailer_id"], po_number, str(po_date),
                    str(ship_date), total_units, round(total_value, 2),
                ))
                lines.extend(order_lines)

        current += timedelta(weeks=1)

    return orders, lines


# Unit loss on a capacity-constrained order under the line mechanics in
# generate_shipments (3% zero-fill + 97% × uniform(0.03, 0.12) on 75% of
# lines → 0.077 expected loss per constrained order). Used to back out
# the constrained-order probability from the §2.1 fill targets.
EXPECTED_CONSTRAINED_LOSS = 0.077

# §2.1 targets are annual figures. Q4 months dip Q4_FILL_DIP below the
# base rate and carry ~23% of annual units (SEASONALITY-weighted,
# measured), so the base rate sits 0.23 x dip above target for the
# annual blend to land on target.
Q4_ANNUAL_COMP = 0.23 * Q4_FILL_DIP

# LTL carriers see more pickup-delay and pre-load damage shortfalls (§1.4)
LTL_CARRIERS = ("LTL Freight", "R+L Carriers")


def _shortfall_reason(fill_rng, mix, sku, carrier, defect, eligible_share):
    """Weighted §1.4 reason draw with two causal couplings: LTL carriers
    skew toward carrier shortfalls, and data_defect can only fire for SKUs
    whose data quality score is below the strong threshold (a SKU with
    clean data cannot be rejected for bad data).

    Because only `eligible_share` of SKUs can carry a data_defect short,
    eligible SKUs get the data weight scaled by (1-w)/(e-w) so the
    realized portfolio share still lands on the §1.4 mix; ineligible SKUs
    redistribute the data weight proportionally across the other reasons.
    Exactly one fill_rng draw either way — fill outcomes are unaffected.
    """
    w = dict(mix)
    if carrier in LTL_CARRIERS:
        w["carrier"] = w["carrier"] * 1.5
    w_d = mix["data_defect"]
    if defect[sku]["quality_score"] < EVIDENCE_DQ_STRONG_MIN:
        w["data_defect"] = w_d * (1.0 - w_d) / (eligible_share - w_d)
    else:
        w["data_defect"] = 0.0
    reasons = list(w.keys())
    return fill_rng.choices(reasons, weights=[w[r] for r in reasons])[0]


def generate_shipments(rng, orders, lines_by_order, fill_rng, timing_rng,
                       defect, eligible_share):
    """One shipment per order, shorted per-line by the causal model.

    Main-rng draw count and order are preserved EXACTLY — the legacy
    delivery offset is still drawn (then discarded) — so every generator
    after this one (remittances, deductions, disputes, evidence,
    chargebacks, post-audit claims, pack records) sees an unchanged
    stream and reproduces byte-identically. All fulfillment randomness
    rides isolated streams: fill_rng = Random(FULFILLMENT_SEED) for
    shortfall allocation, timing_rng = Random(FULFILLMENT_SEED+2) for
    ship/delivery timing.
    """
    shipments = []
    shipment_lines = []
    key_by_shipment = {}

    for i, order in enumerate(orders):
        order_id = order[0]
        retailer_key = RETAILER_KEY[order[1]]
        requested_ship = date.fromisoformat(order[4])

        # -- main-stream draws: identical count and order to the legacy
        # generator. The delivery offset is a dummy draw: delivery now
        # comes from timing_rng (same pattern as generate_chargebacks'
        # dummy draws).
        rng.randint(1, 7)
        carrier = rng.choice(CARRIERS)
        asn_sent = rng.random() < 0.85
        asn_late = asn_sent and rng.random() < 0.10

        # -- fulfillment: §2.1 fill targets with Q4 dip, applied through
        # a constrained-order model — shorts concentrate in a minority of
        # orders (allocation cuts hit whole POs) rather than dusting
        # every order with small shorts.
        fill_target = RETAILER_FILL_TARGET[retailer_key] + Q4_ANNUAL_COMP
        if requested_ship.month in (11, 12):
            fill_target -= Q4_FILL_DIP
        p_constrained = min(0.95, (1.0 - fill_target) / EXPECTED_CONSTRAINED_LOSS)
        constrained = fill_rng.random() < p_constrained

        mix = SHORTFALL_REASON_MIX[retailer_key]
        order_line_rows = []
        for sku, units in lines_by_order[order_id]:
            shipped = units
            reason = None
            if constrained and fill_rng.random() < 0.75:
                if fill_rng.random() < 0.03:
                    shipped = 0
                else:
                    shipped = units - math.ceil(units * fill_rng.uniform(0.03, 0.12))
                reason = _shortfall_reason(fill_rng, mix, sku, carrier,
                                           defect, eligible_share)
            order_line_rows.append([sku, units, shipped, reason])

        # A constrained order never vanishes entirely: full-order
        # cancellation is not part of the §1.4 model, so if every line
        # was cut to zero, partially restore the largest one.
        if order_line_rows and all(l[2] == 0 for l in order_line_rows):
            biggest = max(order_line_rows, key=lambda l: l[1])
            biggest[2] = max(1, math.ceil(biggest[1] * 0.4))

        units_shipped = sum(l[2] for l in order_line_rows)

        # -- timing: ~96% ship on the requested date (internal on-time),
        # delivery rides per-retailer transit instead of a uniform 1-7.
        if timing_rng.random() < INTERNAL_ONTIME_TARGET:
            ship_date = requested_ship
        else:
            ship_date = requested_ship + timedelta(days=timing_rng.randint(1, 2))
        t_lo, t_hi = RETAILER_TRANSIT_DAYS[retailer_key]
        delivery_date = ship_date + timedelta(days=timing_rng.randint(t_lo, t_hi))

        shipment_id = f"RS-{i+1:06d}"
        key_by_shipment[shipment_id] = retailer_key
        pallets = max(1, units_shipped // 48)

        shipments.append((
            shipment_id, order_id, str(ship_date),
            str(delivery_date) if delivery_date <= WINDOW_END else None,
            carrier, f"BOL-{i+1:06d}",
            units_shipped, pallets, asn_sent, asn_late,
        ))
        for sku, units, shipped, reason in order_line_rows:
            shipment_lines.append((shipment_id, sku, units, shipped, reason))

    return shipments, shipment_lines, key_by_shipment


def generate_receipt_lines(receipt_rng, shipment_lines, key_by_shipment):
    """What the retailer reports receiving, per shipment line (§1.5).

    Rides its own stream (Random(FULFILLMENT_SEED+1)) so later changes to
    shipment generation cannot shift receiving outcomes. Zero-shipped
    lines receive zero with no discrepancy draw — nothing arrived at the
    dock to miscount.
    """
    rows = []
    for shipment_id, sku, _units_ordered, units_shipped, _reason in shipment_lines:
        if units_shipped == 0:
            rows.append((shipment_id, sku, 0, None))
            continue
        key = key_by_shipment[shipment_id]
        if receipt_rng.random() >= RECEIVING_DISCREPANCY_RATE[key]:
            rows.append((shipment_id, sku, units_shipped, None))
            continue
        mix = RECEIVING_DISCREPANCY_MIX.get(key, RECEIVING_DISCREPANCY_MIX["default"])
        reasons = list(mix.keys())
        reason = receipt_rng.choices(reasons, weights=[mix[r] for r in reasons])[0]
        if reason == "carrier_damage":
            missing = max(1, math.ceil(units_shipped * receipt_rng.uniform(0.05, 0.25)))
        elif reason == "receiving_miscount":
            missing = receipt_rng.randint(1, max(1, units_shipped // 10))
        else:  # quality_rejection
            missing = max(1, math.ceil(units_shipped * receipt_rng.uniform(0.10, 0.40)))
        rows.append((shipment_id, sku, max(0, units_shipped - missing), reason))
    return rows


def generate_remittances(rng, orders):
    """Group orders into monthly remittances per retailer.

    Legacy rng draws preserved verbatim (stream preservation). The
    deduction_rate draw is a dummy — Group E replaces the amounts with
    causal reconstruction in finalize_remittances. Returns rem_meta
    mapping rem_id -> (retailer_id, year, month) for chargeback matching.
    """
    from collections import defaultdict
    by_retailer_month = defaultdict(list)
    for order in orders:
        retailer_id = order[1]
        po_date = date.fromisoformat(order[3])
        month_key = (retailer_id, po_date.year, po_date.month)
        by_retailer_month[month_key].append(order)

    remittances = []
    rem_num = 0
    remittance_order_map = {}
    rem_meta = {}

    for (rid, year, month), month_orders in sorted(by_retailer_month.items()):
        rem_num += 1
        rem_id = f"RREM-{rem_num:04d}"
        gross = sum(float(o[6]) for o in month_orders)
        deduction_rate = rng.uniform(0.08, 0.18)
        total_ded = round(gross * deduction_rate, 2)
        net = round(gross - total_ded, 2)
        received = date(year, month, 1) + timedelta(days=rng.randint(25, 55))
        if received > WINDOW_END:
            received = WINDOW_END
        fmt = rng.choice(["EDI 820", "PDF", "CSV", "portal_export"])
        clarity = rng.choice(["clear", "clear", "moderate", "vague"])

        remittances.append((
            rem_id, rid, str(received), fmt,
            round(gross, 2), round(net, 2), total_ded, clarity,
        ))
        rem_meta[rem_id] = (rid, year, month)
        for o in month_orders:
            remittance_order_map[o[0]] = (rem_id, total_ded / len(month_orders))

    return remittances, remittance_order_map, rem_meta


def finalize_remittances(rem_rng, legacy_rows, rem_meta, deductions, chargebacks):
    """Group E: causal remittance reconstruction (§3.3).

    Replaces legacy random haircuts with:
      net = gross − itemized − trade − chargebacks_applied − residual

    Constraint #1 — residual is the balancing term, not an independent draw.
    Constraint #2 — option (b): residual fraction drawn from gauss(2%, 0.5%)
      then clamped to [1%, 3%]. total_deductions is computed after the clamp,
      so the identity net = gross − total_deductions holds by construction
      (no component needs to absorb a difference).
    Constraint #3 — each component ≥ 0 per row, enforced explicitly.
    """
    from collections import defaultdict

    ded_by_rem = defaultdict(float)
    for d in deductions:
        if d[3]:
            ded_by_rem[d[3]] += float(d[6])

    cb_by_pm = defaultdict(float)
    for cb in chargebacks:
        cb_by_pm[(cb[1], cb[0])] += float(cb[4])

    final = []
    agg_known = 0.0
    agg_shortfall = 0.0

    for row in legacy_rows:
        rem_id, retailer_id = row[0], row[1]
        received_date, fmt = row[2], row[3]
        gross = float(row[4])
        clarity = row[7]

        rid, year, month = rem_meta[rem_id]
        key = RETAILER_KEY[retailer_id]

        itemized = round(max(0.0, ded_by_rem.get(rem_id, 0.0)), 2)
        trade = round(max(0.0, TRADE_SPEND_PCT[key] * gross), 2)
        month_str = str(date(year, month, 1))
        cb = round(max(0.0, cb_by_pm.get((retailer_id, month_str), 0.0)), 2)
        known = itemized + trade + cb

        r_raw = rem_rng.gauss(REMITTANCE_RESIDUAL_TARGET, 0.005)
        r = max(0.01, min(0.03, r_raw))
        timing_residual = round(known * r / (1.0 - r), 2) if known > 0 else 0.0
        timing_residual = max(0.0, timing_residual)

        total_deductions = round(itemized + trade + cb + timing_residual, 2)
        net = round(gross - total_deductions, 2)

        if net < 0:
            trade = round(max(0.0, trade + net), 2)
            total_deductions = round(itemized + trade + cb + timing_residual, 2)
            net = round(gross - total_deductions, 2)

        agg_known += (itemized + trade + cb)
        agg_shortfall += total_deductions

        final.append((
            rem_id, retailer_id, received_date, fmt,
            round(gross, 2), net, total_deductions, clarity,
            trade, cb, timing_residual,
        ))

    return final, agg_known, agg_shortfall


def generate_deductions(rng, orders, remittance_map, deduction_codes_by_retailer):
    """Legacy deduction stream — kept verbatim for stream preservation.

    ~25% of orders draw 1-3 deductions of random type. Since Group C the
    caller discards the short_ship/late_delivery rows from this output
    (the draws still happen, so the main rng stays byte-stable) and
    replaces them with generate_event_deductions; the other seven types
    ship exactly as drawn here.
    """
    deductions = []
    ded_num = 0

    for order in orders:
        if rng.random() > 0.25:
            continue
        order_id = order[0]
        retailer_id = order[1]
        po_date = date.fromisoformat(order[3])
        order_value = float(order[6])

        rem_info = remittance_map.get(order_id)
        rem_id = rem_info[0] if rem_info else None

        n_deds = rng.choices([1, 1, 2, 3], weights=[60, 20, 15, 5])[0]
        for _ in range(n_deds):
            ded_num += 1
            ded_type = rng.choice(DEDUCTION_TYPES)
            amount = round(order_value * rng.uniform(0.02, 0.15), 2)
            ded_date = po_date + timedelta(days=rng.randint(20, 60))
            if ded_date > WINDOW_END:
                continue
            deadline = ded_date + timedelta(days=rng.choice([30, 45, 60, 90]))

            codes = deduction_codes_by_retailer.get(retailer_id, [])
            matching = [c for c in codes if c[4] == ded_type]
            code_id = matching[0][0] if matching else None

            if ded_type == "slotting":
                ded_deadline = None
            elif deadline <= WINDOW_END + timedelta(days=90):
                ded_deadline = str(deadline)
            else:
                ded_deadline = None

            deductions.append((
                f"RD-{ded_num:06d}", retailer_id, order_id, rem_id,
                ded_type, code_id, amount, str(ded_date),
                ded_deadline,
                rng.random() < 0.03,
            ))

    return deductions


def generate_disputes(rng, deductions):
    """~40% of deductions get disputed."""
    disputes = []
    disp_num = 0

    for ded in deductions:
        if rng.random() > 0.40:
            continue
        disp_num += 1
        ded_id = ded[0]
        ded_date = date.fromisoformat(ded[7])
        filed = ded_date + timedelta(days=rng.randint(1, 30))
        if filed > WINDOW_END:
            continue

        outcome = rng.choices(DISPUTE_OUTCOMES, weights=[30, 25, 30, 15])[0]
        ded_amount = float(ded[6])
        if outcome == "won":
            recovered = ded_amount
        elif outcome == "partial":
            recovered = round(ded_amount * rng.uniform(0.20, 0.80), 2)
        elif outcome == "pending":
            recovered = None
        else:
            recovered = 0.0

        closed = None
        if outcome != "pending":
            closed = filed + timedelta(days=rng.randint(14, 90))
            if closed > WINDOW_END:
                closed = None

        labor = round(rng.uniform(0.25, 4.0), 2)
        quality = rng.choice(["strong", "strong", "moderate", "weak"])
        method = rng.choice(["portal", "email", "phone"])

        if ded[4] == "slotting":
            continue

        disputes.append((
            f"RDISP-{disp_num:05d}", ded_id, str(filed), method,
            quality, outcome, recovered,
            str(closed) if closed else None, labor,
        ))

    return disputes


def generate_dispute_evidence(rng, disputes):
    """2-4 evidence items per dispute."""
    evidence = []
    for disp in disputes:
        dispute_id = disp[0]
        n_items = rng.randint(2, 4)
        chosen_types = rng.sample(EVIDENCE_TYPES, min(n_items, len(EVIDENCE_TYPES)))
        for etype in chosen_types:
            submitted = rng.random() < 0.80
            required = rng.random() < 0.60
            fmt = rng.choice(["PDF", "PNG", "CSV", "EDI"])
            evidence.append((
                dispute_id, etype, submitted, required, fmt, None,
            ))
    return evidence


# ── Group D: §2.5 evidence tiers + §2.4 tier-conditioned outcomes ──

TIER_BY_RANK = ("strong", "moderate", "weak")
TIER_RANK = {t: i for i, t in enumerate(TIER_BY_RANK)}


def _weakest(*tiers: str) -> str:
    """§2.5 composite rule: the tier is the minimum across all factors."""
    return TIER_BY_RANK[max(TIER_RANK[t] for t in tiers)]


def _dq_tier(score: int) -> str:
    """§2.5 data-quality factor on the 40-95 defect-profile score."""
    if score >= EVIDENCE_DQ_STRONG_MIN:
        return "strong"
    if score < EVIDENCE_DQ_WEAK_MAX:
        return "weak"
    return "moderate"


def _filing_delay(u: float, p: tuple) -> int:
    """Map one uniform draw to a filing delay in days: piecewise across
    the (≤30, 31-60, 61-90) buckets with the given probabilities, then
    uniform within the bucket. Single draw keeps the assembly stream at
    a fixed two draws per deduction."""
    a, b, c = p
    if u < a:
        return 1 + int(u / a * 30)
    if u < a + b:
        return 31 + int((u - a) / b * 30)
    return 61 + int((u - a - b) / c * 30)


def assemble_evidence(asm_rng, deductions, ship_by_order, pack_ver_by_order,
                      ev_sku_by_order, defect):
    """§2.5 factor states + weakest-link tier per written deduction.

    Deterministic factors come from the fulfillment data: ASN from the
    order's shipment, pack verification from its pack record, data
    quality from the defect-profile score of the order's largest-
    line_total SKU (ties sku-ascending — the dossier centers on the
    highest-dollar product on the PO). Two factors ride asm_rng =
    Random(EVIDENCE_SEED), exactly two draws per deduction in write
    order: the POD retrieval state (carrier-class probabilities; a
    shipment with no in-window delivery confirmation forces missing)
    and the filing delay (clipped to the deduction's dispute_deadline —
    the team files inside the window when one is stated, so >60-day
    filings only occur against 90-day or open deadlines).
    """
    states = []
    for d in deductions:
        order_id = d[2]
        s = ship_by_order[order_id]
        carrier, asn_sent, asn_late = s[4], s[8], s[9]
        u_pod = asm_rng.random()
        u_fil = asm_rng.random()

        if s[3] is None:
            pod = "weak"  # no delivery confirmation inside the window
        else:
            pc, pp, _ = RET_POD_STATE_P[
                "ltl" if carrier in LTL_CARRIERS else "parcel"]
            pod = ("strong" if u_pod < pc
                   else "moderate" if u_pod < pc + pp else "weak")

        asn = ("strong" if asn_sent and not asn_late
               else "moderate" if asn_sent else "weak")
        pack_ver = pack_ver_by_order.get(order_id)
        pack = PACK_VERIFICATION_TIER.get(pack_ver, "weak")
        dq = _dq_tier(defect[ev_sku_by_order[order_id]]["quality_score"])

        delay = _filing_delay(u_fil, RET_FILING_DELAY_P)
        if d[8] is not None:
            deadline_days = (date.fromisoformat(d[8])
                             - date.fromisoformat(d[7])).days
            delay = min(delay, deadline_days)
        fil = ("strong" if delay <= 30
               else "moderate" if delay <= 60 else "weak")

        states.append({
            "tier": _weakest(pod, asn, pack, dq, fil),
            "pod": pod, "asn": asn, "pack": pack, "dq": dq, "fil": fil,
            "delay": delay, "asn_sent": asn_sent, "pack_ver": pack_ver,
        })
    return states


def _evidence_rows(out_rng, dispute_id, ded_type, ev):
    """Evidence items mirroring the assembled §2.5 factor states. The
    POD row persists the drawn POD state in the data (submitted unless
    missing; notes='partial' when partial) so the dbt assessment can
    recompute the POD factor from the warehouse. The ASN row exists
    only when an ASN was actually sent — you cannot submit a document
    that was never produced."""
    rows = [(dispute_id, "invoice", True, True,
             out_rng.choice(["PDF", "EDI"]), None)]
    pod_required = ded_type in ("short_ship", "late_delivery",
                                "damaged", "spoilage")
    rows.append((dispute_id, "POD", ev["pod"] != "weak", pod_required,
                 "PDF", "partial" if ev["pod"] == "moderate" else None))
    if ev["asn_sent"]:
        rows.append((dispute_id, "ASN", True, False, "EDI", None))
    pack_type = ("label_scan" if ev["pack_ver"] == "scan_verified"
                 else "pack_photo")
    rows.append((dispute_id, pack_type, True, False,
                 out_rng.choice(["PNG", "PDF"]), None))
    if ded_type in ("short_ship", "late_delivery"):
        rows.append((dispute_id, "BOL", True, True, "PDF", None))
    if ded_type == "pricing_error":
        rows.append((dispute_id, "price_confirmation", True, True,
                     out_rng.choice(["PDF", "CSV"]), None))
    return rows


def generate_causal_disputes(sel_rng, out_rng, deductions, evidence_states,
                             method_by_retailer):
    """Disputes with §2.5-derived evidence tiers and §2.4 tier-
    conditioned outcomes (Group D). Replaces the legacy flat draw
    entirely — every written deduction, legacy-stream and event-driven,
    is a dispute candidate.

    Selection: the brand triages by winnability — each deduction is
    disputed at its tier's RET_DISPUTE_PROPENSITY. Selection rides
    sel_rng = Random(EVIDENCE_SEED+2) at exactly one draw per
    deduction, so outcome recalibration can never change who gets
    disputed. Outcomes, partial-recovery fractions, closure timing,
    tier-conditioned labor hours, filing method, and evidence-row
    formats ride out_rng = Random(EVIDENCE_SEED+1) and draw only for
    written disputes. Filing dates come from the assembly delay;
    disputes filed past the data window are skipped (legacy rule).
    """
    disputes, ev_rows = [], []
    disp_num = 0
    for d, ev in zip(deductions, evidence_states):
        if sel_rng.random() >= RET_DISPUTE_PROPENSITY[ev["tier"]]:
            continue
        ded_date = date.fromisoformat(d[7])
        filed = ded_date + timedelta(days=ev["delay"])
        if filed > WINDOW_END:
            continue
        disp_num += 1
        dispute_id = f"RDISP-{disp_num:05d}"
        tier = ev["tier"]

        w = EVIDENCE_OUTCOME_WEIGHTS[tier]
        outcome = out_rng.choices(list(w.keys()), weights=list(w.values()))[0]
        amount = float(d[6])
        if outcome == "won":
            recovered = amount
        elif outcome == "partial":
            lo, hi = PARTIAL_RECOVERY_RANGE[tier]
            recovered = round(amount * out_rng.uniform(lo, hi), 2)
        elif outcome == "pending":
            recovered = None
        else:
            recovered = 0.0

        closed = None
        if outcome != "pending":
            lo_c, hi_c = DISPUTE_CLOSE_DAYS["retailer"]
            closed = filed + timedelta(days=out_rng.randint(lo_c, hi_c))
            if closed > WINDOW_END:
                closed = None

        lo_l, hi_l = LABOR_HOURS_BY_TIER[tier]
        labor = round(out_rng.uniform(lo_l, hi_l), 2)
        method = ("phone" if out_rng.random() < DISPUTE_METHOD_PHONE_P
                  else method_by_retailer.get(d[1]) or "email")

        ev = _evidence_rows(out_rng, dispute_id, d[4], ev)
        if d[4] == "slotting":
            continue

        disputes.append((
            dispute_id, d[0], str(filed), method, tier, outcome,
            recovered, str(closed) if closed else None, labor,
        ))
        ev_rows.extend(ev)
    return disputes, ev_rows


def _month_floor(d: date) -> str:
    """First-of-month string, the chargeback table's month grain."""
    return str(date(d.year, d.month, 1))


def _is_late(key: str, requested_ship: date, delivery: date) -> bool:
    """Delivery beyond the retailer's MABD window (Group C trigger rule).

    MABD = requested ship date + the retailer's maximum normal transit
    (RETAILER_TRANSIT_DAYS upper bound) + its OTIF window. A shipment
    that left on the requested date can never trip this; only the
    timing_rng late-ship tail (~4%) can, which is what makes the
    chargeback causal rather than statistical.
    """
    t_hi = RETAILER_TRANSIT_DAYS[key][1]
    window = RETAILER_OTIF_WINDOW_DAYS[key]
    return delivery > requested_ship + timedelta(days=t_hi + window)


def generate_operational_chargebacks(cb_rng, orders, shipments,
                                     lines_by_shipment, receipt_lines,
                                     key_by_shipment, price_by_order_sku,
                                     auto_deduct):
    """Operational chargebacks triggered by real fulfillment events (Group C).

    Replaces the legacy unconditional short_ship/late_delivery draws.
    Three causal categories, all riding cb_rng = Random(FULFILLMENT_SEED+3):

      short_ship — a shipment with shorted lines draws one assessment at
        the retailer's p(assess), lifted where raw.retailer_rules has
        auto_deduct for short_ship (Walmart, Kroger). Fine = rate ×
        shorted value, clamped. SKU = largest-shortfall line; month =
        ship month.
      late_delivery — delivery beyond the MABD window (_is_late). Fine =
        rate × shipped value. SKU = largest shipped-value line; month =
        delivery month.
      receiving_discrepancy — NEW category (decision #2: separate, never
        folded into shortage chargebacks). Per receipt line with
        carrier_damage / quality_rejection; fine = discrepant value ×
        handling multiplier. SKU = the line's SKU; month = delivery
        month. receiving_miscount does not charge back — it short-pays
        as a deduction (design §3.1).

    Draw discipline: cb_rng draws happen only for triggering events, in
    shipment then receipt-line order, so the stream is a pure function
    of the frozen Group B fulfillment state. Shipments delivered after
    the data window (delivery_date NULL) cannot trigger delivery-side
    assessments.
    """
    order_by_id = {o[0]: o for o in orders}
    shipment_by_id = {s[0]: s for s in shipments}
    rows_short, rows_late, rows_recv = [], [], []

    for s in shipments:
        shipment_id, order_id = s[0], s[1]
        key = key_by_shipment[shipment_id]
        order = order_by_id[order_id]
        retailer_id = order[1]
        slines = lines_by_shipment[shipment_id]

        shorted = [(sku, uo, us) for sku, uo, us, reason in slines
                   if reason is not None]
        if shorted:
            p = SHORT_SHIP_CB_ASSESS_BASE[key]
            if auto_deduct.get((retailer_id, "short_ship")):
                p *= CB_AUTO_DEDUCT_LIFT
            if cb_rng.random() < p:
                shorted_value = sum(
                    (uo - us) * price_by_order_sku[(order_id, sku)]
                    for sku, uo, us in shorted)
                cb_sku = max(
                    shorted,
                    key=lambda l: (l[1] - l[2]) * price_by_order_sku[(order_id, l[0])],
                )[0]
                lo, hi = CHARGEBACK_CLAMP["short_ship"]
                amount = round(min(hi, max(lo, SHORT_SHIP_CB_RATE[key] * shorted_value)), 2)
                ship_date = date.fromisoformat(s[2])
                rows_short.append((_month_floor(ship_date), retailer_id,
                                   "short_ship", cb_sku, amount, None))

        if s[3] is not None:
            delivery = date.fromisoformat(s[3])
            requested = date.fromisoformat(order[4])
            if _is_late(key, requested, delivery):
                if cb_rng.random() < LATE_CB_ASSESS[key]:
                    shipped_value = sum(
                        us * price_by_order_sku[(order_id, sku)]
                        for sku, _uo, us, _r in slines)
                    shipped_lines = [(sku, us) for sku, _uo, us, _r in slines
                                     if us > 0]
                    cb_sku = max(
                        shipped_lines,
                        key=lambda l: l[1] * price_by_order_sku[(order_id, l[0])],
                    )[0]
                    lo, hi = CHARGEBACK_CLAMP["late_delivery"]
                    amount = round(min(hi, max(lo, LATE_CB_RATE[key] * shipped_value)), 2)
                    rows_late.append((_month_floor(delivery), retailer_id,
                                      "late_delivery", cb_sku, amount, None))

    for shipment_id, sku, units_received, reason in receipt_lines:
        if reason not in ("carrier_damage", "quality_rejection"):
            continue
        s = shipment_by_id[shipment_id]
        if s[3] is None:
            continue
        key = key_by_shipment[shipment_id]
        if cb_rng.random() < RECEIVING_CB_ASSESS[key]:
            order_id = s[1]
            retailer_id = order_by_id[order_id][1]
            units_shipped = next(
                us for l_sku, _uo, us, _r in lines_by_shipment[shipment_id]
                if l_sku == sku)
            value = (units_shipped - units_received) * price_by_order_sku[(order_id, sku)]
            lo, hi = CHARGEBACK_CLAMP["receiving_discrepancy"]
            amount = round(min(hi, max(lo, RECEIVING_CB_FEE_MULT * value)), 2)
            delivery = date.fromisoformat(s[3])
            rows_recv.append((_month_floor(delivery), retailer_id,
                              "receiving_discrepancy", sku, amount, None))

    return rows_short + rows_late + rows_recv


def generate_event_deductions(ded_rng, orders, shipments, lines_by_shipment,
                              receipt_lines, key_by_shipment,
                              price_by_order_sku, remittance_map,
                              deduction_codes_by_retailer, start_num):
    """Short-ship and late-delivery deductions driven by fulfillment
    events (Group C). The caller discards the legacy random draws for
    these two types; every other deduction type still comes off the
    untouched legacy stream. Amounts are proportional to the event's
    dollar value (design §3.1):

      short_ship — rate × shorted value per shorted shipment (p=0.90:
        retailers nearly always short-pay an incomplete PO), plus the
        EXACT discrepant value for every receiving miscount (AP
        short-pays the invoice/receipt mismatch at face value — no rate,
        no clamp, no assessment gate).
      late_delivery — small admin fee proportional to order value for
        deliveries beyond the MABD window (same _is_late rule as the
        chargebacks, drawn independently on this stream).

    Rides ded_rng = Random(FULFILLMENT_SEED+4). IDs continue the legacy
    RD-______ sequence from start_num so the two populations stay
    distinguishable by position but uniform in format.
    """
    order_by_id = {o[0]: o for o in orders}
    shipment_by_id = {s[0]: s for s in shipments}
    rows = []
    ded_num = start_num

    def _append(retailer_id, order_id, ded_type, amount, ded_date):
        nonlocal ded_num
        if ded_date > WINDOW_END:
            return
        ded_num += 1
        deadline = ded_date + timedelta(days=ded_rng.choice([30, 45, 60, 90]))
        codes = deduction_codes_by_retailer.get(retailer_id, [])
        matching = [c for c in codes if c[4] == ded_type]
        code_id = matching[0][0] if matching else None
        rem_info = remittance_map.get(order_id)
        rem_id = rem_info[0] if rem_info else None
        rows.append((
            f"RD-{ded_num:06d}", retailer_id, order_id, rem_id,
            ded_type, code_id, round(amount, 2), str(ded_date),
            str(deadline) if deadline <= WINDOW_END + timedelta(days=90) else None,
            ded_rng.random() < 0.03,
        ))

    for s in shipments:
        shipment_id, order_id = s[0], s[1]
        key = key_by_shipment[shipment_id]
        order = order_by_id[order_id]
        retailer_id = order[1]
        slines = lines_by_shipment[shipment_id]
        ship_date = date.fromisoformat(s[2])
        delivery = date.fromisoformat(s[3]) if s[3] else None

        shorted = [(sku, uo, us) for sku, uo, us, reason in slines
                   if reason is not None]
        if shorted and ded_rng.random() < SHORT_SHIP_DED_ASSESS:
            shorted_value = sum(
                (uo - us) * price_by_order_sku[(order_id, sku)]
                for sku, uo, us in shorted)
            lo, hi = SHORT_SHIP_DED_CLAMP
            amount = min(hi, max(lo, SHORT_SHIP_DED_RATE * shorted_value))
            anchor = delivery if delivery else ship_date
            _append(retailer_id, order_id, "short_ship", amount,
                    anchor + timedelta(days=ded_rng.randint(15, 45)))

        if delivery is not None:
            requested = date.fromisoformat(order[4])
            if _is_late(key, requested, delivery):
                if ded_rng.random() < LATE_DED_ASSESS:
                    lo, hi = LATE_DED_CLAMP
                    amount = min(hi, max(lo, LATE_DED_RATE * float(order[6])))
                    _append(retailer_id, order_id, "late_delivery", amount,
                            delivery + timedelta(days=ded_rng.randint(15, 40)))

    for shipment_id, sku, units_received, reason in receipt_lines:
        if reason != "receiving_miscount":
            continue
        s = shipment_by_id[shipment_id]
        if s[3] is None:
            continue
        order_id = s[1]
        retailer_id = order_by_id[order_id][1]
        units_shipped = next(
            us for l_sku, _uo, us, _r in lines_by_shipment[shipment_id]
            if l_sku == sku)
        value = (units_shipped - units_received) * price_by_order_sku[(order_id, sku)]
        if value <= 0:
            continue
        delivery = date.fromisoformat(s[3])
        _append(retailer_id, order_id, "short_ship", value,
                delivery + timedelta(days=ded_rng.randint(10, 30)))

    return rows


def generate_chargebacks(rng):
    """Legacy chargeback loop — kept verbatim for stream preservation;
    the caller keeps only its Path A output (Group C).

    SKU distribution is quality-weighted (lower score → more chargebacks)
    using an isolated defect_rng stream. Reason assignment is conditional:
    data-quality reasons (label_fine, damaged, pricing_error) only fire
    for SKUs with the corresponding defect — those rows carry
    triggered_by_field and ARE the Path A pattern, unchanged. Rows whose
    defect_rng reason lands on short_ship/late_delivery are discarded by
    the caller and replaced by generate_operational_chargebacks (the
    draws still happen, so both the main rng and defect_rng streams stay
    byte-stable for everything downstream).

    reason_defect_map mirrors product-data-health-audit/R/02_build_frames.R
    lines 356-366 (excluding weight_implausible and ows_incomplete which
    are not generated at seed time).
    """
    defect = compute_defect_profile()
    defect_rng = init_rng(DEFECT_SEED + 1)

    # Quality-weighted SKU selection: weight = (101 - score)^3.5
    sku_list = [p["sku"] for p in ALL_SKUS]
    weights = [(101 - defect[s]["quality_score"]) ** 3.5 for s in sku_list]

    REASON_DEFECT_CONDITIONS = {
        "label_fine": lambda d: not d["gtin_valid"],
        "damaged": lambda d: (
            d["missing_fields"].get("case_length_in")
            or d["missing_fields"].get("case_width_in")
            or d["missing_fields"].get("case_height_in")
            or d["missing_fields"].get("case_weight_lbs")
        ),
        "pricing_error": lambda d: (
            d["missing_fields"].get("brand_owner")
            or d["missing_fields"].get("country_of_origin")
        ),
    }

    REASON_TRIGGER_FIELDS = {
        "label_fine": lambda d, r: r.choice(
            [f for f in ["gtin_valid", "upc_valid"] if not d["gtin_valid"]]
        ),
        "damaged": lambda d, r: r.choice(
            [f for f, k in [
                ("missing_case_dims", "case_length_in"),
                ("missing_case_dims", "case_width_in"),
                ("missing_case_dims", "case_height_in"),
                ("missing_case_weight", "case_weight_lbs"),
            ] if d["missing_fields"].get(k)]
        ),
        "pricing_error": lambda d, r: r.choice(
            [f for f, k in [
                ("missing_brand_owner", "brand_owner"),
                ("missing_country", "country_of_origin"),
            ] if d["missing_fields"].get(k)]
        ),
    }

    rows = []
    reasons_all = ["short_ship", "late_delivery", "label_fine", "damaged", "pricing_error"]
    current = WINDOW_START
    while current <= WINDOW_END:
        month_date = date(current.year, current.month, 1)
        for ret in RETAILERS:
            n_cbs = rng.randint(1, 5)
            for _ in range(n_cbs):
                rng.choice(ALL_SKUS)
                rng.choice(reasons_all)
                amount = round(rng.uniform(50, 2000), 2)
                sku = defect_rng.choices(sku_list, weights=weights)[0]
                dp = defect[sku]
                valid_reasons = ["short_ship", "late_delivery"]
                for r, cond in REASON_DEFECT_CONDITIONS.items():
                    if cond(dp):
                        valid_reasons.append(r)
                reason = defect_rng.choice(valid_reasons)
                triggered_by = None
                if reason in REASON_TRIGGER_FIELDS:
                    triggered_by = REASON_TRIGGER_FIELDS[reason](dp, defect_rng)
                rows.append((str(month_date), ret["retailer_id"], reason, sku, amount, triggered_by))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return rows


def generate_post_audit_claims(rng, deductions):
    """~2% of deductions become post-audit claims."""
    claims = []
    claim_num = 0
    auditors = ["Naviga", "PRGX", "Retail Solutions Inc", "CoStar Group"]
    claim_types = ["pricing", "promotion", "allowance", "new_item", "freight"]

    for ded in deductions:
        if rng.random() > 0.02:
            continue
        claim_num += 1
        ded_date = date.fromisoformat(ded[7])
        lookback = rng.choice([6, 12, 18, 24])
        period_start = ded_date - timedelta(days=lookback * 30)
        period_end = ded_date

        claims.append((
            f"PAC-{claim_num:04d}", ded[0],
            rng.choice(auditors),
            str(period_start), str(period_end),
            rng.choice(claim_types), lookback,
        ))
    return claims


def generate_pack_records(rng, orders, shipments):
    """One pack record per order/shipment pair."""
    rows = []
    ship_map = {s[1]: s for s in shipments}
    for order in orders:
        order_id = order[0]
        ship = ship_map.get(order_id)
        if not ship:
            continue
        ship_id = ship[0]
        ship_date = ship[2]
        units = order[5]
        pick_error = rng.random() < 0.03
        packed = units if not pick_error else units - rng.randint(1, max(1, units // 10))
        verification = rng.choice(["scan_verified", "manual_count", "weight_check"])
        scannable = rng.random() < 0.95
        fmt = rng.choice(["photo", "scan_log", "checklist"])

        rows.append((
            order_id, ship_id, ship_date,
            units, packed, verification, scannable, fmt,
        ))
    return rows


def main():
    print("Connecting to Postgres...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    rng = init_rng(seed=100)

    # Load existing deduction codes for FK references
    cur.execute("SELECT code_id, retailer_id, code, name, deduction_type FROM raw.retailer_deduction_codes")
    all_codes = cur.fetchall()
    from collections import defaultdict
    codes_by_retailer = defaultdict(list)
    for row in all_codes:
        codes_by_retailer[row[1]].append(row)

    # Compliance enforcement flags (Group C): retailers whose rules
    # auto-deduct a violation type assess short-ship chargebacks at a
    # lifted rate.
    cur.execute("SELECT retailer_id, deduction_type, auto_deduct FROM raw.retailer_rules")
    auto_deduct = {(r[0], r[1]): r[2] for r in cur.fetchall()}

    print("\nGenerating retailer orders and lines...")
    orders, lines = generate_orders_and_lines(rng)
    copy_rows(cur, "raw.retailer_orders",
              ["order_id", "retailer_id", "po_number", "po_date",
               "requested_ship_date", "total_units", "total_value"],
              orders)
    print(f"  retailer_orders: {len(orders)} rows")

    copy_rows(cur, "raw.retailer_order_lines",
              ["order_id", "sku", "units_ordered", "unit_price", "line_total"],
              lines)
    print(f"  retailer_order_lines: {len(lines)} rows")

    print("Generating shipments...")
    # Isolated fulfillment streams (design §6.2): they cannot disturb the
    # main seed=100 stream, and each concern gets its own sub-stream so
    # later groups cannot shift earlier outputs.
    fill_rng = init_rng(FULFILLMENT_SEED)         # shortfall allocation
    receipt_rng = init_rng(FULFILLMENT_SEED + 1)  # receiving discrepancies
    timing_rng = init_rng(FULFILLMENT_SEED + 2)   # ship/delivery timing
    defect = compute_defect_profile()
    # Share of SKUs that can carry a data_defect short (DQ below strong);
    # orders sample SKUs uniformly, so the SKU-count share is the
    # unit-weighted eligibility.
    eligible_share = sum(
        1 for p in ALL_SKUS
        if defect[p["sku"]]["quality_score"] < EVIDENCE_DQ_STRONG_MIN
    ) / len(ALL_SKUS)

    lines_by_order = defaultdict(list)
    for order_id, sku, units, _price, _total in lines:
        lines_by_order[order_id].append((sku, units))

    shipments, shipment_lines, key_by_shipment = generate_shipments(
        rng, orders, lines_by_order, fill_rng, timing_rng, defect,
        eligible_share)
    copy_rows(cur, "raw.retailer_shipments",
              ["shipment_id", "order_id", "ship_date", "delivery_date",
               "carrier", "bol_number", "units_shipped", "pallets_shipped",
               "asn_sent", "asn_sent_late"],
              shipments)
    print(f"  retailer_shipments: {len(shipments)} rows")

    copy_rows(cur, "raw.retailer_shipment_lines",
              ["shipment_id", "sku", "units_ordered", "units_shipped",
               "shortfall_reason"],
              shipment_lines)
    print(f"  retailer_shipment_lines: {len(shipment_lines)} rows")

    print("Generating receipt lines...")
    receipt_lines = generate_receipt_lines(receipt_rng, shipment_lines,
                                           key_by_shipment)
    copy_rows(cur, "raw.retailer_receipt_lines",
              ["shipment_id", "sku", "units_received", "discrepancy_reason"],
              receipt_lines)
    print(f"  retailer_receipt_lines: {len(receipt_lines)} rows")

    print("Generating remittance skeletons...")
    legacy_remittances, rem_map, rem_meta = generate_remittances(rng, orders)
    skeleton_rows = [
        (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], 0, 0, 0)
        for r in legacy_remittances
    ]
    copy_rows(cur, "raw.retailer_remittances",
              ["remittance_id", "retailer_id", "received_date", "format",
               "gross_amount", "net_amount", "total_deductions", "clarity",
               "trade_allowance", "chargebacks_applied", "timing_residual"],
              skeleton_rows)
    print(f"  remittance skeletons: {len(legacy_remittances)} (placeholder amounts; finalized in Group E)")

    # ── Group C: causal money tables ─────────────────────────────────
    # Every legacy generator below still runs on the main rng with its
    # ORIGINAL input list, so the seed=100 stream stays byte-stable all
    # the way through pack records. The causal replacement happens in
    # what gets WRITTEN: legacy short_ship/late_delivery rows (and their
    # dependent disputes/evidence/claims) are filtered out and the
    # event-driven rows ride isolated streams (FULFILLMENT_SEED+3/+4).
    cb_rng = init_rng(FULFILLMENT_SEED + 3)   # operational chargeback assessment
    ded_rng = init_rng(FULFILLMENT_SEED + 4)  # event-driven deductions

    lines_by_shipment = defaultdict(list)
    for sid, sku, units_ordered, units_shipped, reason in shipment_lines:
        lines_by_shipment[sid].append((sku, units_ordered, units_shipped, reason))
    price_by_order_sku = {(order_id, sku): price
                          for order_id, sku, _units, price, _total in lines}

    print("Generating deductions...")
    legacy_deductions = generate_deductions(rng, orders, rem_map, codes_by_retailer)
    removed_ded_ids = {d[0] for d in legacy_deductions
                       if d[4] in ("short_ship", "late_delivery")}
    kept_deductions = [d for d in legacy_deductions if d[0] not in removed_ded_ids]
    max_legacy_num = max(int(d[0].split("-")[1]) for d in legacy_deductions)
    event_deductions = generate_event_deductions(
        ded_rng, orders, shipments, lines_by_shipment, receipt_lines,
        key_by_shipment, price_by_order_sku, rem_map, codes_by_retailer,
        max_legacy_num)
    deductions = kept_deductions + event_deductions
    copy_rows(cur, "raw.retailer_deductions",
              ["deduction_id", "retailer_id", "order_id", "remittance_id",
               "deduction_type", "code_id", "amount", "deduction_date",
               "dispute_deadline", "is_post_audit"],
              deductions)
    print(f"  retailer_deductions: {len(deductions)} rows "
          f"({len(kept_deductions)} legacy + {len(event_deductions)} event-driven; "
          f"{len(removed_ded_ids)} legacy short_ship/late_delivery replaced)")

    print("Generating disputes...")
    # ── Group D: the legacy dispute and evidence generators still run
    # verbatim on the main rng (the chargeback, post-audit-claim, and
    # pack-record draws that follow depend on their stream position),
    # but their output is fully replaced: every written deduction —
    # legacy-stream and event-driven, both populations — gets §2.5
    # weakest-link evidence assembly and §2.4 tier-conditioned outcomes
    # on isolated EVIDENCE_SEED streams. The causal sets are written
    # after pack records exist (evidence assembly reads pack
    # verification states).
    legacy_disputes = generate_disputes(rng, legacy_deductions)
    print(f"  legacy dispute stream preserved "
          f"({len(legacy_disputes)} candidate rows, replaced by Group D)")

    print("Generating dispute evidence...")
    legacy_evidence = generate_dispute_evidence(rng, legacy_disputes)
    print(f"  legacy evidence stream preserved "
          f"({len(legacy_evidence)} candidate rows, replaced by Group D)")

    print("Generating chargebacks...")
    legacy_cb = generate_chargebacks(rng)
    path_a_cb = [r for r in legacy_cb if r[5] is not None]
    event_cb = generate_operational_chargebacks(
        cb_rng, orders, shipments, lines_by_shipment, receipt_lines,
        key_by_shipment, price_by_order_sku, auto_deduct)
    chargebacks = path_a_cb + event_cb
    copy_rows(cur, "raw.retailer_chargebacks",
              ["month", "retailer_id", "reason", "sku", "amount", "triggered_by_field"],
              chargebacks)
    print(f"  retailer_chargebacks: {len(chargebacks)} rows "
          f"({len(path_a_cb)} Path A data-defect + {len(event_cb)} event-driven; "
          f"{len(legacy_cb) - len(path_a_cb)} legacy operational replaced)")

    # ── Group E: causal remittance reconstruction (§3.3) ────────────
    rem_rng = init_rng(REMITTANCE_SEED)
    print("Finalizing remittances (Group E)...")
    final_remittances, ret_known, ret_shortfall = finalize_remittances(
        rem_rng, legacy_remittances, rem_meta, deductions, chargebacks)
    for row in final_remittances:
        cur.execute(
            """UPDATE raw.retailer_remittances
               SET net_amount = %s, total_deductions = %s,
                   trade_allowance = %s, chargebacks_applied = %s,
                   timing_residual = %s
               WHERE remittance_id = %s""",
            (row[5], row[6], row[8], row[9], row[10], row[0]))

    ret_classif = ret_known / ret_shortfall * 100 if ret_shortfall > 0 else 100
    ret_residual_pct = (ret_shortfall - ret_known) / ret_shortfall * 100 if ret_shortfall > 0 else 0
    print(f"  retailer_remittances: {len(final_remittances)} rows")
    print(f"\n  === Classification rate: {ret_classif:.2f}% (target >=97%) ===")
    print(f"  === Residual: {ret_residual_pct:.2f}% of shortfall (target 1-3%) ===\n")

    print("Generating post-audit claims...")
    legacy_pac = generate_post_audit_claims(rng, legacy_deductions)
    pac = [c for c in legacy_pac if c[1] not in removed_ded_ids]
    copy_rows(cur, "raw.retailer_post_audit_claims",
              ["claim_id", "deduction_id", "auditor_name",
               "audit_period_start", "audit_period_end",
               "claim_type", "lookback_months"],
              pac)
    print(f"  retailer_post_audit_claims: {len(pac)} rows")

    print("Generating pack records...")
    pack = generate_pack_records(rng, orders, shipments)
    copy_rows(cur, "raw.retailer_pack_records",
              ["order_id", "shipment_id", "pack_date",
               "units_picked", "units_packed", "pack_verification",
               "label_scannable", "evidence_format"],
              pack)
    print(f"  retailer_pack_records: {len(pack)} rows")

    # ── Group D: causal evidence + disputes ──────────────────────────
    # Isolated streams (design §6.2): assembly, outcomes, and selection
    # each ride their own sequence so recalibrating one concern cannot
    # shift the others.
    asm_rng = init_rng(EVIDENCE_SEED)       # POD state + filing delay
    out_rng = init_rng(EVIDENCE_SEED + 1)   # outcomes/closure/labor/formats
    sel_rng = init_rng(EVIDENCE_SEED + 2)   # tier-conditioned selection

    ship_by_order = {s[1]: s for s in shipments}
    pack_ver_by_order = {p[0]: p[5] for p in pack}
    lines_by_order_full = defaultdict(list)
    for line in lines:
        lines_by_order_full[line[0]].append(line)
    ev_sku_by_order = {
        oid: sorted(ls, key=lambda l: (-l[4], l[1]))[0][1]
        for oid, ls in lines_by_order_full.items()
    }
    method_by_retailer = {r["retailer_id"]: r["dispute_method"]
                          for r in RETAILERS}

    print("Generating causal evidence + disputes (Group D)...")
    evidence_states = assemble_evidence(
        asm_rng, deductions, ship_by_order, pack_ver_by_order,
        ev_sku_by_order, defect)
    disputes, evidence = generate_causal_disputes(
        sel_rng, out_rng, deductions, evidence_states, method_by_retailer)
    copy_rows(cur, "raw.retailer_disputes",
              ["dispute_id", "deduction_id", "filed_date", "filing_method",
               "evidence_quality", "outcome", "recovered_amount",
               "closed_date", "labor_hours"],
              disputes)
    tier_counts = {t: 0 for t in TIER_BY_RANK}
    for disp in disputes:
        tier_counts[disp[4]] += 1
    print(f"  retailer_disputes: {len(disputes)} rows "
          f"({len(deductions)} deduction candidates; tiers "
          f"{tier_counts['strong']}/{tier_counts['moderate']}/"
          f"{tier_counts['weak']} S/M/W)")
    copy_rows(cur, "raw.retailer_dispute_evidence",
              ["dispute_id", "evidence_type", "was_submitted",
               "was_required", "format", "notes"],
              evidence)
    print(f"  retailer_dispute_evidence: {len(evidence)} rows")

    conn.commit()
    print("\nRetailer pipeline committed.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
