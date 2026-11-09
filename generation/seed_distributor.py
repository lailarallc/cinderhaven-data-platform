"""Seed generator for the distributor pipeline.

Tables generated (50 SKUs, 3-year window):
  - distributor_orders (~9,000 orders)
  - distributor_order_lines (~40,000 lines)
  - distributor_shipments (~9,000)
  - distributor_shipment_lines (~40,000)
  - distributor_remittances (~110)
  - distributor_deductions (~2,500)
  - distributor_disputes (~470)
  - distributor_chargebacks (~670)

Requires seed_shared.py to have been run first (distributors, products exist).

Usage:
    python generation/seed_distributor.py
"""
from __future__ import annotations

import io
import math
import psycopg2
from collections import defaultdict
from datetime import date, timedelta

from seed_config import (
    ALL_SKUS, DATABASE_URL, DISTRIBUTORS, CARRIERS,
    DISPUTE_OUTCOMES, SEASONALITY,
    WINDOW_START, WINDOW_END, init_rng, WHOLESALE_MULT,
    compute_defect_profile, DEFECT_SEED,
    FULFILLMENT_SEED, DISTRIBUTOR_FILL_TARGET, Q4_FILL_DIP,
    DISTRIBUTOR_SHORTFALL_MIX, EVIDENCE_DQ_STRONG_MIN,
    DIST_DELIVERY_WINDOW_DAYS,
    DIST_SHORT_SHIP_CB_ASSESS, DIST_SHORT_SHIP_CB_RATE,
    DIST_LATE_CB_ASSESS, DIST_LATE_CB_RATE, DIST_CHARGEBACK_CLAMP,
    DIST_SHORT_SHIP_DED_ASSESS, DIST_SHORT_SHIP_DED_RATE,
    DIST_SHORT_SHIP_DED_CLAMP, DIST_LATE_DED_ASSESS, DIST_LATE_DED_RATE,
    DIST_LATE_DED_CLAMP,
    EVIDENCE_SEED, EVIDENCE_DQ_WEAK_MAX, EVIDENCE_OUTCOME_WEIGHTS,
    PARTIAL_RECOVERY_RANGE, DIST_FILING_DELAY_P,
    DIST_DISPUTE_PROPENSITY, LABOR_HOURS_BY_TIER, DISPUTE_CLOSE_DAYS,
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


DISTRIBUTOR_VOLUME_WEIGHT = {
    "DIST-UNFI": 1.2,
    "DIST-KEHE": 1.0,
    "DIST-DPI": 0.7,
}

# distributor_id -> seed_config key (fill targets)
DISTRIBUTOR_KEY = {
    "DIST-UNFI": "unfi",
    "DIST-KEHE": "kehe",
    "DIST-DPI": "dpi",
}

def generate_orders_and_lines(rng):
    orders = []
    lines = []
    order_num = 0

    current = WINDOW_START
    while current <= WINDOW_END:
        month_mult = SEASONALITY.get(current.month, 1.0)
        for dist in DISTRIBUTORS:
            weight = DISTRIBUTOR_VOLUME_WEIGHT.get(dist["distributor_id"], 1.0)
            orders_this_week = int(rng.gauss(20, 5) * month_mult * weight)
            orders_this_week = max(4, orders_this_week)

            for _ in range(orders_this_week):
                order_num += 1
                order_id = f"DO-{order_num:06d}"
                po_number = f"DPO-{dist['distributor_id'][-4:]}-{order_num:06d}"
                po_date = current + timedelta(days=rng.randint(0, 6))
                if po_date > WINDOW_END:
                    continue

                n_lines = rng.choices([2, 3, 5, 8, 10], weights=[10, 25, 35, 20, 10])[0]
                chosen_skus = rng.sample(ALL_SKUS, min(n_lines, len(ALL_SKUS)))

                total_units = 0
                total_value = 0.0
                order_lines = []

                key = dist["name"].lower().replace(" ", "_")
                if key == "dpi_northwest":
                    key = "dpi"
                mult = WHOLESALE_MULT.get(key, 0.45)

                for sku_info in chosen_skus:
                    units = rng.choices(
                        [48, 72, 144, 240, 360],
                        weights=[15, 30, 30, 15, 10]
                    )[0]
                    unit_price = round(sku_info["msrp"] * mult, 2)
                    line_total = round(units * unit_price, 2)

                    total_units += units
                    total_value += line_total
                    order_lines.append((
                        order_id, sku_info["sku"], units, unit_price, line_total,
                    ))

                orders.append((
                    order_id, dist["distributor_id"], po_number, str(po_date),
                    total_units, round(total_value, 2),
                ))
                lines.extend(order_lines)

        current += timedelta(weeks=1)

    return orders, lines


# Unit loss on a constrained order — same line mechanics as the retailer
# pipeline (3% zero-fill + 97% × uniform(0.03, 0.12) on 75% of lines
# → 0.077 expected loss per constrained order).
EXPECTED_CONSTRAINED_LOSS = 0.077

# §1.6 targets are annual; same Q4 compensation as the retailer pipeline
# (Q4 carries ~23% of annual units).
Q4_ANNUAL_COMP = 0.23 * Q4_FILL_DIP

LTL_CARRIERS = ("LTL Freight", "R+L Carriers")


def _shortfall_reason(fill_rng, sku, carrier, defect, eligible_share):
    """Weighted §1.6 reason draw (allocation-heavy distributor mix) with
    the same causal couplings and eligibility compensation as the
    retailer pipeline — see seed_retailer.py._shortfall_reason."""
    mix = DISTRIBUTOR_SHORTFALL_MIX
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


def generate_shipments(rng, orders, lines_by_order, fill_rng, defect,
                       eligible_share):
    """One shipment per order, shorted per-line by the causal model.

    Main-rng draws keep their original count, order, AND values — the
    distributor timing model is unchanged by design (§1.6: simpler
    channel, no receipt documents, flexible windows). Only units_shipped
    changes, computed from the per-line allocation on the isolated
    fill_rng = Random(FULFILLMENT_SEED + 10) stream.
    """
    shipments = []
    shipment_lines = []

    for i, order in enumerate(orders):
        order_id = order[0]
        dist_key = DISTRIBUTOR_KEY[order[1]]
        po_date = date.fromisoformat(order[3])
        ship_date = po_date + timedelta(days=rng.randint(1, 4))
        delivery_date = ship_date + timedelta(days=rng.randint(2, 10))
        carrier = rng.choice(CARRIERS)

        fill_target = DISTRIBUTOR_FILL_TARGET[dist_key] + Q4_ANNUAL_COMP
        if po_date.month in (11, 12):
            fill_target -= Q4_FILL_DIP
        p_constrained = min(0.95, (1.0 - fill_target) / EXPECTED_CONSTRAINED_LOSS)
        constrained = fill_rng.random() < p_constrained

        order_line_rows = []
        for sku, units in lines_by_order[order_id]:
            shipped = units
            reason = None
            if constrained and fill_rng.random() < 0.75:
                if fill_rng.random() < 0.03:
                    shipped = 0
                else:
                    shipped = units - math.ceil(units * fill_rng.uniform(0.03, 0.12))
                reason = _shortfall_reason(fill_rng, sku, carrier, defect,
                                           eligible_share)
            order_line_rows.append([sku, units, shipped, reason])

        if order_line_rows and all(l[2] == 0 for l in order_line_rows):
            biggest = max(order_line_rows, key=lambda l: l[1])
            biggest[2] = max(1, math.ceil(biggest[1] * 0.4))

        units_shipped = sum(l[2] for l in order_line_rows)
        shipment_id = f"DS-{i+1:06d}"

        shipments.append((
            shipment_id, order_id, str(ship_date),
            str(delivery_date) if delivery_date <= WINDOW_END else None,
            carrier, units_shipped,
        ))
        for sku, units, shipped, reason in order_line_rows:
            shipment_lines.append((shipment_id, sku, units, shipped, reason))

    return shipments, shipment_lines


def generate_remittances(rng, orders):
    """Legacy rng draws preserved verbatim (stream preservation). The
    deduction_rate draw is a dummy — Group E replaces the amounts with
    causal reconstruction in finalize_remittances. Returns rem_meta
    mapping rem_id -> (distributor_id, year, month)."""
    by_dist_month = defaultdict(list)
    for order in orders:
        dist_id = order[1]
        po_date = date.fromisoformat(order[3])
        month_key = (dist_id, po_date.year, po_date.month)
        by_dist_month[month_key].append(order)

    remittances = []
    rem_num = 0
    remittance_order_map = {}
    rem_meta = {}

    for (did, year, month), month_orders in sorted(by_dist_month.items()):
        rem_num += 1
        rem_id = f"DREM-{rem_num:04d}"
        gross = sum(float(o[5]) for o in month_orders)
        deduction_rate = rng.uniform(0.05, 0.12)
        total_ded = round(gross * deduction_rate, 2)
        net = round(gross - total_ded, 2)
        received = date(year, month, 1) + timedelta(days=rng.randint(28, 60))
        if received > WINDOW_END:
            received = WINDOW_END

        remittances.append((
            rem_id, did, str(received),
            round(gross, 2), round(net, 2), total_ded,
        ))
        rem_meta[rem_id] = (did, year, month)
        for o in month_orders:
            remittance_order_map[o[0]] = rem_id

    return remittances, remittance_order_map, rem_meta


def finalize_remittances(rem_rng, legacy_rows, rem_meta, deductions, chargebacks):
    """Group E: causal remittance reconstruction (§3.3) — distributor.

    Same constraints as retailer finalize_remittances (see seed_retailer.py).
    Distributor deduction amount is at index [5], chargeback amount at [4].
    """
    ded_by_rem = defaultdict(float)
    for d in deductions:
        if d[3]:
            ded_by_rem[d[3]] += float(d[5])

    cb_by_pm = defaultdict(float)
    for cb in chargebacks:
        cb_by_pm[(cb[1], cb[0])] += float(cb[4])

    final = []
    agg_known = 0.0
    agg_shortfall = 0.0

    for row in legacy_rows:
        rem_id, dist_id = row[0], row[1]
        received_date = row[2]
        gross = float(row[3])

        did, year, month = rem_meta[rem_id]
        key = DISTRIBUTOR_KEY[dist_id]

        itemized = round(max(0.0, ded_by_rem.get(rem_id, 0.0)), 2)
        trade = round(max(0.0, TRADE_SPEND_PCT[key] * gross), 2)
        month_str = str(date(year, month, 1))
        cb = round(max(0.0, cb_by_pm.get((dist_id, month_str), 0.0)), 2)
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
            rem_id, dist_id, received_date,
            round(gross, 2), net, total_deductions,
            trade, cb, timing_residual,
        ))

    return final, agg_known, agg_shortfall


def generate_deductions(rng, orders, remittance_map):
    """Legacy deduction stream — kept verbatim for stream preservation.

    ~20% of orders draw 1-2 deductions of random type. Since Group C2
    the caller discards the short_ship/late_delivery rows from this
    output (the draws still happen, so the main rng stays byte-stable)
    and replaces them with generate_event_deductions; the other three
    types (pricing_error, promo_billback, damaged — §1.6: distributor
    discrepancies arrive via deductions) ship exactly as drawn here.
    """
    dist_ded_types = ["short_ship", "pricing_error", "promo_billback", "damaged", "late_delivery"]
    deductions = []
    ded_num = 0

    for order in orders:
        if rng.random() > 0.20:
            continue
        order_id = order[0]
        dist_id = order[1]
        po_date = date.fromisoformat(order[3])
        order_value = float(order[5])
        rem_id = remittance_map.get(order_id)

        n_deds = rng.choices([1, 2], weights=[80, 20])[0]
        for _ in range(n_deds):
            ded_num += 1
            ded_type = rng.choice(dist_ded_types)
            amount = round(order_value * rng.uniform(0.02, 0.10), 2)
            ded_date = po_date + timedelta(days=rng.randint(20, 50))
            if ded_date > WINDOW_END:
                continue

            deductions.append((
                f"DD-{ded_num:06d}", dist_id, order_id, rem_id,
                ded_type, amount, str(ded_date),
            ))

    return deductions


def generate_disputes(rng, deductions):
    disputes = []
    disp_num = 0

    for ded in deductions:
        if rng.random() > 0.35:
            continue
        disp_num += 1
        ded_date = date.fromisoformat(ded[6])
        filed = ded_date + timedelta(days=rng.randint(3, 25))
        if filed > WINDOW_END:
            continue

        outcome = rng.choices(DISPUTE_OUTCOMES, weights=[25, 30, 30, 15])[0]
        ded_amount = float(ded[5])
        if outcome == "won":
            recovered = ded_amount
        elif outcome == "partial":
            recovered = round(ded_amount * rng.uniform(0.25, 0.70), 2)
        elif outcome == "pending":
            recovered = None
        else:
            recovered = 0.0

        closed = None
        if outcome != "pending":
            closed = filed + timedelta(days=rng.randint(14, 75))
            if closed > WINDOW_END:
                closed = None

        labor = round(rng.uniform(0.25, 3.0), 2)

        disputes.append((
            f"DDISP-{disp_num:05d}", ded[0], str(filed),
            outcome, recovered, str(closed) if closed else None, labor,
        ))

    return disputes


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
    """One uniform draw -> filing delay in days across the (≤30, 31-60,
    61-90) buckets — same mapping as the retailer pipeline."""
    a, b, c = p
    if u < a:
        return 1 + int(u / a * 30)
    if u < a + b:
        return 31 + int((u - a) / b * 30)
    return 61 + int((u - a - b) / c * 30)


def assemble_evidence(asm_rng, deductions, ship_by_order, ev_sku_by_order,
                      defect):
    """§2.5 factor states per written deduction — the §1.6 reduced set.

    Distributors carry no ASN fields and no pack records, so the
    weakest-link composite runs over three factors: POD (pure data —
    a delivery confirmation exists inside the window, no retrieval
    randomness on this simpler channel), product data quality (defect-
    profile score of the order's largest-line_total SKU, ties
    sku-ascending), and filing timeliness (drawn delay; distributor
    deductions carry no dispute_deadline column, so the delay is
    uncapped). Exactly one asm_rng = Random(EVIDENCE_SEED+10) draw per
    deduction, in write order.
    """
    states = []
    for d in deductions:
        u_fil = asm_rng.random()
        pod = "strong" if ship_by_order[d[2]][3] is not None else "weak"
        dq = _dq_tier(defect[ev_sku_by_order[d[2]]]["quality_score"])
        delay = _filing_delay(u_fil, DIST_FILING_DELAY_P)
        fil = ("strong" if delay <= 30
               else "moderate" if delay <= 60 else "weak")
        states.append({"tier": _weakest(pod, dq, fil), "pod": pod,
                       "dq": dq, "fil": fil, "delay": delay})
    return states


def generate_causal_disputes(sel_rng, out_rng, deductions, evidence_states):
    """Disputes with §2.5-derived evidence tiers and §2.4 tier-
    conditioned outcomes (Group D) — the distributor parallel. Every
    written deduction is a candidate; selection rides sel_rng =
    Random(EVIDENCE_SEED+12) at one draw per deduction; outcome,
    partial-fraction, closure, and labor draws ride out_rng =
    Random(EVIDENCE_SEED+11) for written disputes only. The tier is
    persisted in the new evidence_quality column so tier-conditioned
    recovery is queryable in the warehouse, matching the retailer
    table."""
    disputes = []
    disp_num = 0
    for d, ev in zip(deductions, evidence_states):
        if sel_rng.random() >= DIST_DISPUTE_PROPENSITY[ev["tier"]]:
            continue
        ded_date = date.fromisoformat(d[6])
        filed = ded_date + timedelta(days=ev["delay"])
        if filed > WINDOW_END:
            continue
        disp_num += 1
        tier = ev["tier"]

        w = EVIDENCE_OUTCOME_WEIGHTS[tier]
        outcome = out_rng.choices(list(w.keys()), weights=list(w.values()))[0]
        amount = float(d[5])
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
            lo_c, hi_c = DISPUTE_CLOSE_DAYS["distributor"]
            closed = filed + timedelta(days=out_rng.randint(lo_c, hi_c))
            if closed > WINDOW_END:
                closed = None

        lo_l, hi_l = LABOR_HOURS_BY_TIER[tier]
        labor = round(out_rng.uniform(lo_l, hi_l), 2)

        disputes.append((
            f"DDISP-{disp_num:05d}", d[0], str(filed), tier, outcome,
            recovered, str(closed) if closed else None, labor,
        ))
    return disputes


def _month_floor(d: date) -> str:
    """First-of-month string, the chargeback table's month grain."""
    return str(date(d.year, d.month, 1))


def generate_operational_chargebacks(cb_rng, orders, shipments,
                                     lines_by_shipment, price_by_order_sku):
    """Distributor operational chargebacks triggered by real shipment
    events (Group C2). Replaces the legacy unconditional short_ship /
    late_delivery draws. Two causal categories, both riding cb_rng =
    Random(FULFILLMENT_SEED+11):

      short_ship — a shipment with shorted lines draws one assessment
        at the distributor's p(assess). Fine = rate × shorted value,
        clamped. SKU = largest-shortfall line; month = ship month.
      late_delivery — delivery beyond the order-to-door window
        (po_date + DIST_DELIVERY_WINDOW_DAYS; distributor orders carry
        no requested_ship_date, so the window is the observable MABD
        analog — design §1.6's "flexible delivery windows" encoded as a
        generous window + low assessment, not zero enforcement). Fine =
        rate × shipped value. SKU = largest shipped-value line; month =
        delivery month.

    NO receiving_discrepancy category on this channel: there are no
    receipt lines (§1.6 — distributors report discrepancies via
    deductions; the legacy damaged rows remain that record).

    Draw discipline: cb_rng draws happen only for triggering events, in
    shipment order, so the stream is a pure function of the frozen
    Group B fulfillment state. Shipments delivered after the data
    window (delivery_date NULL) cannot trigger delivery-side
    assessments.
    """
    order_by_id = {o[0]: o for o in orders}
    rows_short, rows_late = [], []

    for s in shipments:
        shipment_id, order_id = s[0], s[1]
        order = order_by_id[order_id]
        dist_id = order[1]
        key = DISTRIBUTOR_KEY[dist_id]
        slines = lines_by_shipment[shipment_id]

        shorted = [(sku, uo, us) for sku, uo, us, reason in slines
                   if reason is not None]
        if shorted:
            if cb_rng.random() < DIST_SHORT_SHIP_CB_ASSESS[key]:
                shorted_value = sum(
                    (uo - us) * price_by_order_sku[(order_id, sku)]
                    for sku, uo, us in shorted)
                cb_sku = max(
                    shorted,
                    key=lambda l: (l[1] - l[2]) * price_by_order_sku[(order_id, l[0])],
                )[0]
                lo, hi = DIST_CHARGEBACK_CLAMP["short_ship"]
                amount = round(min(hi, max(lo, DIST_SHORT_SHIP_CB_RATE[key] * shorted_value)), 2)
                ship_date = date.fromisoformat(s[2])
                rows_short.append((_month_floor(ship_date), dist_id,
                                   "short_ship", cb_sku, amount))

        if s[3] is not None:
            delivery = date.fromisoformat(s[3])
            po_date = date.fromisoformat(order[3])
            if delivery > po_date + timedelta(days=DIST_DELIVERY_WINDOW_DAYS):
                if cb_rng.random() < DIST_LATE_CB_ASSESS[key]:
                    shipped_value = sum(
                        us * price_by_order_sku[(order_id, sku)]
                        for sku, _uo, us, _r in slines)
                    shipped_lines = [(sku, us) for sku, _uo, us, _r in slines
                                     if us > 0]
                    cb_sku = max(
                        shipped_lines,
                        key=lambda l: l[1] * price_by_order_sku[(order_id, l[0])],
                    )[0]
                    lo, hi = DIST_CHARGEBACK_CLAMP["late_delivery"]
                    amount = round(min(hi, max(lo, DIST_LATE_CB_RATE[key] * shipped_value)), 2)
                    rows_late.append((_month_floor(delivery), dist_id,
                                      "late_delivery", cb_sku, amount))

    return rows_short + rows_late


def generate_event_deductions(ded_rng, orders, shipments, lines_by_shipment,
                              price_by_order_sku, remittance_map, start_num):
    """Short-ship and late-delivery deductions driven by fulfillment
    events (Group C2). The caller discards the legacy random draws for
    these two types; every other deduction type still comes off the
    untouched legacy stream. Amounts are proportional to the event's
    dollar value (design §3.1):

      short_ship — rate × shorted value per shorted shipment (p=0.85:
        distributors short-pay incomplete POs slightly less reflexively
        than retail compliance programs).
      late_delivery — small admin fee proportional to order value for
        deliveries beyond the order-to-door window (same rule as the
        chargebacks, drawn independently on this stream).

    Rides ded_rng = Random(FULFILLMENT_SEED+12). IDs continue the
    legacy DD-______ sequence from start_num so the two populations
    stay distinguishable by position but uniform in format.
    """
    order_by_id = {o[0]: o for o in orders}
    rows = []
    ded_num = start_num

    def _append(dist_id, order_id, ded_type, amount, ded_date):
        nonlocal ded_num
        if ded_date > WINDOW_END:
            return
        ded_num += 1
        rem_id = remittance_map.get(order_id)
        rows.append((
            f"DD-{ded_num:06d}", dist_id, order_id, rem_id,
            ded_type, round(amount, 2), str(ded_date),
        ))

    for s in shipments:
        shipment_id, order_id = s[0], s[1]
        order = order_by_id[order_id]
        dist_id = order[1]
        slines = lines_by_shipment[shipment_id]
        ship_date = date.fromisoformat(s[2])
        delivery = date.fromisoformat(s[3]) if s[3] else None

        shorted = [(sku, uo, us) for sku, uo, us, reason in slines
                   if reason is not None]
        if shorted and ded_rng.random() < DIST_SHORT_SHIP_DED_ASSESS:
            shorted_value = sum(
                (uo - us) * price_by_order_sku[(order_id, sku)]
                for sku, uo, us in shorted)
            lo, hi = DIST_SHORT_SHIP_DED_CLAMP
            amount = min(hi, max(lo, DIST_SHORT_SHIP_DED_RATE * shorted_value))
            anchor = delivery if delivery else ship_date
            _append(dist_id, order_id, "short_ship", amount,
                    anchor + timedelta(days=ded_rng.randint(15, 45)))

        if delivery is not None:
            po_date = date.fromisoformat(order[3])
            if delivery > po_date + timedelta(days=DIST_DELIVERY_WINDOW_DAYS):
                if ded_rng.random() < DIST_LATE_DED_ASSESS:
                    lo, hi = DIST_LATE_DED_CLAMP
                    amount = min(hi, max(lo, DIST_LATE_DED_RATE * float(order[5])))
                    _append(dist_id, order_id, "late_delivery", amount,
                            delivery + timedelta(days=ded_rng.randint(15, 40)))

    return rows


def generate_chargebacks(rng):
    """Legacy chargeback loop — kept verbatim for stream preservation;
    the caller keeps only its damaged / pricing_error rows (Group C2).

    SKU distribution is quality-weighted (lower score → more
    chargebacks) using an isolated defect_rng stream; the dummy main-rng
    draws preserve the seed=200 sequence exactly. Rows whose reason
    lands on short_ship/late_delivery are discarded by the caller and
    replaced by generate_operational_chargebacks (the draws still
    happen, so both streams stay byte-stable for everything downstream).
    """
    defect = compute_defect_profile()
    defect_rng = init_rng(DEFECT_SEED + 2)

    sku_list = [p["sku"] for p in ALL_SKUS]
    weights = [(101 - defect[s]["quality_score"]) ** 3.5 for s in sku_list]

    reasons = ["short_ship", "pricing_error", "damaged", "late_delivery"]
    rows = []
    current = WINDOW_START
    while current <= WINDOW_END:
        month_date = date(current.year, current.month, 1)
        for dist in DISTRIBUTORS:
            n_cbs = rng.randint(0, 3)
            for _ in range(n_cbs):
                # Dummy call: preserve main rng stream exactly
                rng.choice(ALL_SKUS)
                reason = rng.choice(reasons)
                amount = round(rng.uniform(100, 3000), 2)
                # Actual SKU from quality-weighted draw (isolated stream)
                sku = defect_rng.choices(sku_list, weights=weights)[0]
                rows.append((str(month_date), dist["distributor_id"], reason, sku, amount))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return rows


def main():
    print("Connecting to Postgres...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    rng = init_rng(seed=200)

    print("\nGenerating distributor orders and lines...")
    orders, lines = generate_orders_and_lines(rng)
    copy_rows(cur, "raw.distributor_orders",
              ["order_id", "distributor_id", "po_number", "po_date",
               "total_units", "total_value"],
              orders)
    print(f"  distributor_orders: {len(orders)} rows")

    copy_rows(cur, "raw.distributor_order_lines",
              ["order_id", "sku", "units_ordered", "unit_price", "line_total"],
              lines)
    print(f"  distributor_order_lines: {len(lines)} rows")

    print("Generating shipments...")
    # Isolated fulfillment stream (design §6.2); offset from the retailer
    # pipeline's sub-streams so the channels never share a sequence.
    fill_rng = init_rng(FULFILLMENT_SEED + 10)
    defect = compute_defect_profile()
    eligible_share = sum(
        1 for p in ALL_SKUS
        if defect[p["sku"]]["quality_score"] < EVIDENCE_DQ_STRONG_MIN
    ) / len(ALL_SKUS)

    lines_by_order = defaultdict(list)
    for order_id, sku, units, _price, _total in lines:
        lines_by_order[order_id].append((sku, units))

    shipments, shipment_lines = generate_shipments(
        rng, orders, lines_by_order, fill_rng, defect, eligible_share)
    copy_rows(cur, "raw.distributor_shipments",
              ["shipment_id", "order_id", "ship_date", "delivery_date",
               "carrier", "units_shipped"],
              shipments)
    print(f"  distributor_shipments: {len(shipments)} rows")

    copy_rows(cur, "raw.distributor_shipment_lines",
              ["shipment_id", "sku", "units_ordered", "units_shipped",
               "shortfall_reason"],
              shipment_lines)
    print(f"  distributor_shipment_lines: {len(shipment_lines)} rows")

    print("Generating remittance skeletons...")
    legacy_remittances, rem_map, rem_meta = generate_remittances(rng, orders)
    skeleton_rows = [
        (r[0], r[1], r[2], r[3], r[4], r[5], 0, 0, 0)
        for r in legacy_remittances
    ]
    copy_rows(cur, "raw.distributor_remittances",
              ["remittance_id", "distributor_id", "received_date",
               "gross_amount", "net_amount", "total_deductions",
               "trade_allowance", "chargebacks_applied", "timing_residual"],
              skeleton_rows)
    print(f"  remittance skeletons: {len(legacy_remittances)} (placeholder amounts; finalized in Group E)")

    # ── Group C2: causal distributor money tables ────────────────────
    # Every legacy generator below still runs on the main rng with its
    # ORIGINAL input list, so the seed=200 stream stays byte-stable.
    # The causal replacement happens in what gets WRITTEN: legacy
    # short_ship/late_delivery rows (and the disputes attached to those
    # deductions) are filtered out and the event-driven rows ride
    # isolated streams (FULFILLMENT_SEED+11/+12).
    cb_rng = init_rng(FULFILLMENT_SEED + 11)   # operational chargeback assessment
    ded_rng = init_rng(FULFILLMENT_SEED + 12)  # event-driven deductions

    lines_by_shipment = defaultdict(list)
    for sid, sku, units_ordered, units_shipped, reason in shipment_lines:
        lines_by_shipment[sid].append((sku, units_ordered, units_shipped, reason))
    price_by_order_sku = {(order_id, sku): price
                          for order_id, sku, _units, price, _total in lines}

    print("Generating deductions...")
    legacy_deductions = generate_deductions(rng, orders, rem_map)
    removed_ded_ids = {d[0] for d in legacy_deductions
                       if d[4] in ("short_ship", "late_delivery")}
    kept_deductions = [d for d in legacy_deductions if d[0] not in removed_ded_ids]
    max_legacy_num = max(int(d[0].split("-")[1]) for d in legacy_deductions)
    event_deductions = generate_event_deductions(
        ded_rng, orders, shipments, lines_by_shipment, price_by_order_sku,
        rem_map, max_legacy_num)
    deductions = kept_deductions + event_deductions
    copy_rows(cur, "raw.distributor_deductions",
              ["deduction_id", "distributor_id", "order_id", "remittance_id",
               "deduction_type", "amount", "deduction_date"],
              deductions)
    print(f"  distributor_deductions: {len(deductions)} rows "
          f"({len(kept_deductions)} legacy + {len(event_deductions)} event-driven; "
          f"{len(removed_ded_ids)} legacy short_ship/late_delivery replaced)")

    print("Generating disputes...")
    # ── Group D: the legacy dispute generator still runs verbatim on
    # the main rng (the chargeback draws that follow depend on its
    # stream position), but its output is fully replaced: every written
    # deduction — kept legacy types and event-driven rows alike — gets
    # §2.5 evidence assembly and §2.4 tier-conditioned outcomes on
    # isolated EVIDENCE_SEED streams (+10 assembly, +11 outcomes,
    # +12 selection — the distributor parallels of the retailer
    # +0/+1/+2).
    legacy_disputes = generate_disputes(rng, legacy_deductions)
    print(f"  legacy dispute stream preserved "
          f"({len(legacy_disputes)} candidate rows, replaced by Group D)")

    asm_rng_ev = init_rng(EVIDENCE_SEED + 10)   # filing delay
    out_rng_ev = init_rng(EVIDENCE_SEED + 11)   # outcomes/closure/labor
    sel_rng_ev = init_rng(EVIDENCE_SEED + 12)   # tier-conditioned selection

    ship_by_order = {s[1]: s for s in shipments}
    lines_by_order_full = defaultdict(list)
    for line in lines:
        lines_by_order_full[line[0]].append(line)
    ev_sku_by_order = {
        oid: sorted(ls, key=lambda l: (-l[4], l[1]))[0][1]
        for oid, ls in lines_by_order_full.items()
    }

    print("Generating causal evidence + disputes (Group D)...")
    evidence_states = assemble_evidence(
        asm_rng_ev, deductions, ship_by_order, ev_sku_by_order, defect)
    disputes = generate_causal_disputes(
        sel_rng_ev, out_rng_ev, deductions, evidence_states)
    copy_rows(cur, "raw.distributor_disputes",
              ["dispute_id", "deduction_id", "filed_date",
               "evidence_quality", "outcome", "recovered_amount",
               "closed_date", "labor_hours"],
              disputes)
    tier_counts = {t: 0 for t in TIER_BY_RANK}
    for disp in disputes:
        tier_counts[disp[3]] += 1
    print(f"  distributor_disputes: {len(disputes)} rows "
          f"({len(deductions)} deduction candidates; tiers "
          f"{tier_counts['strong']}/{tier_counts['moderate']}/"
          f"{tier_counts['weak']} S/M/W)")

    print("Generating chargebacks...")
    legacy_cb = generate_chargebacks(rng)
    kept_cb = [r for r in legacy_cb if r[2] in ("damaged", "pricing_error")]
    event_cb = generate_operational_chargebacks(
        cb_rng, orders, shipments, lines_by_shipment, price_by_order_sku)
    chargebacks = kept_cb + event_cb
    copy_rows(cur, "raw.distributor_chargebacks",
              ["month", "distributor_id", "reason", "sku", "amount"],
              chargebacks)
    print(f"  distributor_chargebacks: {len(chargebacks)} rows "
          f"({len(kept_cb)} quality-linked legacy + {len(event_cb)} event-driven; "
          f"{len(legacy_cb) - len(kept_cb)} legacy operational replaced)")

    # ── Group E: causal remittance reconstruction (§3.3) ────────────
    dist_rem_rng = init_rng(REMITTANCE_SEED + 10)
    print("Finalizing remittances (Group E)...")
    final_remittances, dist_known, dist_shortfall = finalize_remittances(
        dist_rem_rng, legacy_remittances, rem_meta, deductions, chargebacks)
    for row in final_remittances:
        cur.execute(
            """UPDATE raw.distributor_remittances
               SET net_amount = %s, total_deductions = %s,
                   trade_allowance = %s, chargebacks_applied = %s,
                   timing_residual = %s
               WHERE remittance_id = %s""",
            (row[4], row[5], row[6], row[7], row[8], row[0]))
    dist_classif = dist_known / dist_shortfall * 100 if dist_shortfall > 0 else 100
    dist_residual_pct = (dist_shortfall - dist_known) / dist_shortfall * 100 if dist_shortfall > 0 else 0
    print(f"  distributor_remittances: {len(final_remittances)} rows")
    print(f"\n  === Classification rate: {dist_classif:.2f}% (target >=97%) ===")
    print(f"  === Residual: {dist_residual_pct:.2f}% of shortfall (target 1-3%) ===\n")

    conn.commit()
    print("\nDistributor pipeline committed.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
