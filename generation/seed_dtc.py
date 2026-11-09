"""Seed generator for the DTC (Shopify) pipeline.

Tables generated:
  - shopify_orders (~12,000 orders)
  - shopify_order_lines (~20,000 lines)
  - shopify_transactions (~12,000)
  - shopify_payouts (~100 bi-weekly payouts)
  - shopify_refunds (~600)
  - shopify_chargebacks (~80)

Requires seed_shared.py to have been run first (products exist).

Usage:
    python generation/seed_dtc.py
"""
from __future__ import annotations

import hashlib
import io
import psycopg2
from datetime import date, datetime, timedelta

from collections import defaultdict

from seed_config import (
    ALL_SKUS, DATABASE_URL, SEASONALITY,
    WINDOW_START, WINDOW_END, init_rng,
    DTC_COST_SEED, SKU_PACKAGING,
    DTC_FULFILLMENT_RATE_BY_QUARTER, DTC_FULFILLMENT_WEIGHT_MULT,
    DTC_PLATFORM_FEE_RATE,
    DTC_RETURN_RATE_GLASS, DTC_RETURN_RATE_NON_GLASS,
    DTC_REFUND_REASONS_GLASS, DTC_REFUND_REASONS_NON_GLASS,
)

US_STATES = [
    "CA", "NY", "TX", "FL", "IL", "PA", "OH", "GA", "NC", "MI",
    "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MO", "MD", "WI",
]
STATE_WEIGHTS = [
    15, 12, 11, 10, 8, 7, 6, 6, 5, 5,
    5, 4, 4, 4, 4, 3, 3, 3, 3, 3,
]

DISCOUNT_CODES = [
    ("WELCOME10", 0.10, 0.08),
    ("HOLIDAY15", 0.15, 0.05),
    ("PANTRY20", 0.20, 0.03),
    ("FREESHIP", 0.00, 0.06),
    (None, 0.00, 0.78),
]

FIRST_NAMES = [
    "Emma", "Liam", "Olivia", "Noah", "Ava", "James", "Sophia", "Oliver",
    "Isabella", "Benjamin", "Mia", "Elijah", "Charlotte", "Lucas", "Amelia",
    "Mason", "Harper", "Logan", "Evelyn", "Alexander",
]
LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Wilson",
    "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee",
]


def copy_rows(cur, table: str, columns: list[str], rows: list[tuple]):
    buf = io.StringIO()
    for row in rows:
        line = "\t".join("\\N" if v is None else str(v) for v in row)
        buf.write(line + "\n")
    buf.seek(0)
    cols = ", ".join(columns)
    sql = f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT text, NULL '\\N')"
    cur.copy_expert(sql, buf)


def make_email(first, last, rng):
    domain = rng.choice(["gmail.com", "yahoo.com", "outlook.com", "icloud.com", "proton.me"])
    suffix = rng.randint(1, 999)
    return f"{first.lower()}.{last.lower()}{suffix}@{domain}"


def generate_orders_and_lines(rng):
    orders = []
    lines = []
    order_num = 1000

    # Build a customer pool for repeat purchases
    customers = []
    for _ in range(4000):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        email = make_email(first, last, rng)
        state = rng.choices(US_STATES, weights=STATE_WEIGHTS)[0]
        customers.append((email, first, last, state))

    current = WINDOW_START
    while current <= WINDOW_END:
        month_mult = SEASONALITY.get(current.month, 1.0)
        orders_this_week = int(rng.gauss(115, 20) * month_mult)
        orders_this_week = max(30, orders_this_week)

        for _ in range(orders_this_week):
            order_num += 1
            customer = rng.choice(customers)
            email, first, last, state = customer

            order_id = f"SO-{order_num:07d}"
            order_date = datetime.combine(current, datetime.min.time()) + timedelta(
                days=rng.randint(0, 6),
                hours=rng.randint(6, 23),
                minutes=rng.randint(0, 59),
            )
            if order_date.date() > WINDOW_END:
                continue

            # Pick discount
            code, depth, _ = rng.choices(DISCOUNT_CODES, weights=[d[2] for d in DISCOUNT_CODES])[0]

            n_items = rng.choices([1, 2, 3, 4], weights=[40, 35, 18, 7])[0]
            chosen_skus = rng.sample(ALL_SKUS, min(n_items, len(ALL_SKUS)))

            subtotal = 0.0
            order_lines = []
            for sku_info in chosen_skus:
                qty = rng.choices([1, 2, 3], weights=[60, 30, 10])[0]
                unit_price = sku_info["msrp"]
                line_total = round(qty * unit_price, 2)
                subtotal += line_total
                order_lines.append((
                    order_id, sku_info["sku"], sku_info["product_name"],
                    qty, unit_price, line_total,
                ))

            discount_amount = round(subtotal * depth, 2) if code and code != "FREESHIP" else 0.0
            shipping = 0.0 if (code == "FREESHIP" or subtotal > 75) else round(rng.uniform(5.99, 9.99), 2)
            tax_rate = rng.uniform(0.04, 0.10)
            tax = round((subtotal - discount_amount) * tax_rate, 2)
            total = round(subtotal - discount_amount + shipping + tax, 2)

            financial = rng.choices(
                ["paid", "paid", "paid", "refunded", "partially_refunded"],
                weights=[85, 5, 5, 3, 2]
            )[0]
            fulfillment = rng.choices(
                ["fulfilled", "fulfilled", "unfulfilled", "partial"],
                weights=[88, 5, 5, 2]
            )[0]

            orders.append((
                order_id, order_num, str(order_date), email,
                financial, fulfillment,
                round(subtotal, 2), shipping, tax, total,
                code, discount_amount,
            ))
            lines.extend(order_lines)

        current += timedelta(weeks=1)

    return orders, lines


def generate_transactions(rng, orders):
    txns = []
    gateways = ["shopify_payments", "shopify_payments", "paypal", "stripe"]
    cards = ["visa", "mastercard", "amex", "discover"]

    for i, order in enumerate(orders):
        order_id = order[0]
        order_date = order[2]
        total = float(order[9])
        fee_rate = rng.uniform(0.025, 0.035)
        fee = round(total * fee_rate, 2)
        net = round(total - fee, 2)

        txns.append((
            f"TXN-{i+1:07d}", order_id, order_date,
            total, fee, net,
            rng.choice(gateways), rng.choice(cards),
        ))
    return txns


def generate_payouts(rng, transactions):
    """Bi-weekly payouts grouping transactions."""
    by_period = defaultdict(list)
    for txn in transactions:
        txn_date = datetime.fromisoformat(txn[2]).date()
        period_start = txn_date - timedelta(days=txn_date.weekday())
        bi_week = period_start - timedelta(days=period_start.day % 14)
        by_period[bi_week].append(txn)

    payouts = []
    payout_num = 0
    for period, period_txns in sorted(by_period.items()):
        payout_num += 1
        gross = sum(float(t[3]) for t in period_txns)
        fees = sum(float(t[4]) for t in period_txns)
        net = round(gross - fees, 2)
        payout_date = period + timedelta(days=rng.randint(14, 18))
        if payout_date > WINDOW_END:
            payout_date = WINDOW_END

        payouts.append((
            f"PO-{payout_num:05d}", str(payout_date),
            round(gross, 2), round(fees, 2), round(net, 2), "paid",
        ))
    return payouts


def generate_refunds(cost_rng, orders, lines):
    """Packaging-aware refund generation on isolated RNG stream."""
    order_lines_map = defaultdict(list)
    for line in lines:
        order_id, sku = line[0], line[1]
        line_total = float(line[5])
        order_lines_map[order_id].append((sku, line_total))

    refunds = []
    ref_num = 0

    for order in orders:
        order_id = order[0]
        items = order_lines_map.get(order_id, [])
        total_value = sum(lt for _, lt in items)

        if total_value > 0:
            glass_value = sum(lt for sku, lt in items
                              if SKU_PACKAGING.get(sku) == "glass")
            glass_pct = glass_value / total_value
        else:
            glass_pct = 0.0

        glass_rate = cost_rng.uniform(*DTC_RETURN_RATE_GLASS)
        non_glass_rate = cost_rng.uniform(*DTC_RETURN_RATE_NON_GLASS)
        refund_rate = glass_pct * glass_rate + (1 - glass_pct) * non_glass_rate

        if cost_rng.random() > refund_rate:
            continue

        ref_num += 1
        order_date = datetime.fromisoformat(order[2])
        refund_date = order_date + timedelta(days=cost_rng.randint(3, 30))
        if refund_date.date() > WINDOW_END:
            continue

        total = float(order[9])
        if cost_rng.random() < 0.7:
            refund_amount = total
        else:
            refund_amount = round(total * cost_rng.uniform(0.20, 0.80), 2)

        if glass_pct > 0.5:
            reason = cost_rng.choice(DTC_REFUND_REASONS_GLASS)
        else:
            reason = cost_rng.choice(DTC_REFUND_REASONS_NON_GLASS)

        refunds.append((
            f"REF-{ref_num:05d}", order_id, str(refund_date),
            refund_amount, reason,
        ))
    return refunds


def generate_chargebacks(rng, orders):
    """~0.5% of orders get a chargeback."""
    cbs = []
    cb_num = 0
    reasons = ["fraudulent", "product_not_received", "not_as_described", "duplicate_charge"]
    outcomes = ["won", "lost", "lost", "pending"]

    for order in orders:
        if rng.random() > 0.005:
            continue
        cb_num += 1
        order_id = order[0]
        order_date = datetime.fromisoformat(order[2])
        cb_date = order_date + timedelta(days=rng.randint(15, 90))
        if cb_date.date() > WINDOW_END:
            continue

        total = float(order[9])

        cbs.append((
            f"CB-{cb_num:05d}", order_id, str(cb_date.date()),
            total, rng.choice(reasons), rng.choice(outcomes),
        ))
    return cbs


def compute_fulfillment_costs(cost_rng, orders, lines):
    """Per-order fulfillment cost: base rate × weight multiplier."""
    sku_to_product_line = {s["sku"]: s["product_line"] for s in ALL_SKUS}

    order_lines_map = defaultdict(list)
    for line in lines:
        order_id, sku = line[0], line[1]
        line_total = float(line[5])
        order_lines_map[order_id].append((sku, line_total))

    costs = {}
    for order in orders:
        order_id = order[0]
        order_date = datetime.fromisoformat(order[2])
        quarter = (order_date.month - 1) // 3 + 1
        total = float(order[9])

        base_lo, base_hi = DTC_FULFILLMENT_RATE_BY_QUARTER[quarter]
        base_rate = cost_rng.uniform(base_lo, base_hi)

        items = order_lines_map.get(order_id, [])
        if items:
            total_value = sum(lt for _, lt in items)
            weighted_mult = 0.0
            for sku, lt in items:
                pl = sku_to_product_line.get(sku)
                if pl and pl in DTC_FULFILLMENT_WEIGHT_MULT:
                    mult_lo, mult_hi = DTC_FULFILLMENT_WEIGHT_MULT[pl]
                    mult = cost_rng.uniform(mult_lo, mult_hi)
                    weighted_mult += mult * (lt / total_value)
            costs[order_id] = round(total * base_rate * weighted_mult, 2)
        else:
            costs[order_id] = round(total * base_rate, 2)

    return costs


def compute_platform_fees(cost_rng, transactions):
    """Per-transaction Shopify platform fee (separate from payment processing)."""
    fees = {}
    for txn in transactions:
        txn_id = txn[0]
        order_amount = float(txn[3])
        rate = cost_rng.uniform(*DTC_PLATFORM_FEE_RATE)
        fees[txn_id] = round(order_amount * rate, 2)
    return fees


def main():
    print("Connecting to Postgres...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    rng = init_rng(seed=300)
    cost_rng = init_rng(seed=DTC_COST_SEED)

    print("\nGenerating Shopify orders and lines...")
    orders, lines = generate_orders_and_lines(rng)

    print("Computing DTC cost layers (seed=%d)..." % DTC_COST_SEED)
    fulfillment_costs = compute_fulfillment_costs(cost_rng, orders, lines)

    orders_with_costs = []
    for order in orders:
        order_id = order[0]
        fc = fulfillment_costs.get(order_id, 0.0)
        orders_with_costs.append(order + (fc,))

    copy_rows(cur, "raw.shopify_orders",
              ["order_id", "order_number", "created_at", "email",
               "financial_status", "fulfillment_status",
               "subtotal", "shipping_cost", "total_tax", "total",
               "discount_code", "discount_amount", "fulfillment_cost"],
              orders_with_costs)
    print(f"  shopify_orders: {len(orders_with_costs)} rows")

    copy_rows(cur, "raw.shopify_order_lines",
              ["order_id", "sku", "product_name", "quantity", "unit_price", "line_total"],
              lines)
    print(f"  shopify_order_lines: {len(lines)} rows")

    print("Generating transactions...")
    txns = generate_transactions(rng, orders)
    platform_fees = compute_platform_fees(cost_rng, txns)

    txns_with_fees = []
    for txn in txns:
        txn_id = txn[0]
        pf = platform_fees.get(txn_id, 0.0)
        txns_with_fees.append(
            txn[:4] + (txn[4], pf, txn[5]) + txn[6:]
        )

    copy_rows(cur, "raw.shopify_transactions",
              ["transaction_id", "order_id", "transaction_date",
               "order_amount", "processing_fee", "platform_fee",
               "net_amount", "gateway", "card_brand"],
              txns_with_fees)
    print(f"  shopify_transactions: {len(txns_with_fees)} rows")

    print("Generating payouts...")
    payouts = generate_payouts(rng, txns)
    copy_rows(cur, "raw.shopify_payouts",
              ["payout_id", "payout_date", "gross_amount",
               "fees_amount", "net_amount", "status"],
              payouts)
    print(f"  shopify_payouts: {len(payouts)} rows")

    print("Generating refunds (packaging-aware)...")
    refunds = generate_refunds(cost_rng, orders, lines)
    copy_rows(cur, "raw.shopify_refunds",
              ["refund_id", "order_id", "refund_date", "refund_amount", "reason"],
              refunds)
    print(f"  shopify_refunds: {len(refunds)} rows")

    print("Generating chargebacks...")
    cbs = generate_chargebacks(rng, orders)
    copy_rows(cur, "raw.shopify_chargebacks",
              ["chargeback_id", "order_id", "chargeback_date",
               "chargeback_amount", "reason", "outcome"],
              cbs)
    print(f"  shopify_chargebacks: {len(cbs)} rows")

    total_revenue = sum(float(o[9]) for o in orders)
    total_fc = sum(fulfillment_costs.values())
    total_pf = sum(platform_fees.values())
    total_refunds = sum(float(r[3]) for r in refunds)
    print(f"\n  DTC cost layer summary:")
    print(f"    Fulfillment: ${total_fc:,.0f} ({total_fc/total_revenue*100:.1f}% of revenue)")
    print(f"    Platform fees: ${total_pf:,.0f} ({total_pf/total_revenue*100:.1f}% of revenue)")
    print(f"    Refunds: ${total_refunds:,.0f} ({total_refunds/total_revenue*100:.1f}% of revenue)")

    conn.commit()
    print("\nDTC pipeline committed.")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
