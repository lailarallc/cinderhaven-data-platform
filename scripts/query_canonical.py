"""Query every canonical figure from the Postgres replica for Group F validation."""
import os

import psycopg2

conn = psycopg2.connect(host="localhost", port=5432, dbname="cinderhaven",
                        user="postgres", password=os.environ["POSTGRES_PASSWORD"])
cur = conn.cursor()

def f(v):
    return float(v) if v else 0.0

print("=== CHARGEBACK COUNTS ===")
cur.execute("SELECT COUNT(*) FROM raw.retailer_chargebacks")
ret_cb = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM raw.distributor_chargebacks")
dist_cb = cur.fetchone()[0]
print(f"Retailer: {ret_cb}")
print(f"Distributor: {dist_cb}")
print(f"Total: {ret_cb + dist_cb}")

print("\n=== CHARGEBACK BREAKDOWN BY REASON ===")
for table, label in [("retailer_chargebacks", "Retailer"),
                      ("distributor_chargebacks", "Distributor")]:
    cur.execute(f"SELECT reason, COUNT(*), SUM(amount) FROM raw.{table} "
                "GROUP BY reason ORDER BY reason")
    print(f"{label}:")
    total_amt = 0
    for row in cur.fetchall():
        total_amt += f(row[2])
        print(f"  {row[0]}: {row[1]} / ${f(row[2]):,.2f}")
    print(f"  TOTAL: ${total_amt:,.2f}")

print("\n=== TRAILING-52W SCAN REVENUE ===")
cur.execute("""
    WITH ranked_weeks AS (
        SELECT DISTINCT week_ending FROM raw.scan_data
        ORDER BY week_ending DESC LIMIT 52
    )
    SELECT SUM(sd.dollars_sold)
    FROM raw.scan_data sd
    WHERE sd.week_ending >= (SELECT MIN(week_ending) FROM ranked_weeks)
""")
rev = f(cur.fetchone()[0])
print(f"${rev:,.2f} = ${rev/1e6:.1f}M")

print("\n=== TRADE RATES (from sku_costs) ===")
cur.execute("""
    SELECT
        AVG(trade_spend_pct_walmart), AVG(trade_spend_pct_costco),
        AVG(trade_spend_pct_whole_foods), AVG(trade_spend_pct_sprouts),
        AVG(trade_spend_pct_kroger), AVG(trade_spend_pct_regional)
    FROM raw.sku_costs
""")
rates = cur.fetchone()
names = ["Walmart", "Costco", "Whole Foods", "Sprouts", "Kroger", "Regional"]
for name, rate in zip(names, rates):
    print(f"  {name}: {f(rate)*100:.1f}%")

print("\n=== CHANNEL REVENUE (trailing 52w) ===")
cur.execute("""
    WITH ranked_weeks AS (
        SELECT DISTINCT week_ending FROM raw.scan_data
        ORDER BY week_ending DESC LIMIT 52
    )
    SELECT r.name, SUM(sd.dollars_sold) AS rev
    FROM raw.scan_data sd
    JOIN raw.stores s ON sd.store_id = s.store_id
    JOIN raw.retailers r ON s.retailer_id = r.retailer_id
    WHERE sd.week_ending >= (SELECT MIN(week_ending) FROM ranked_weeks)
    GROUP BY r.name ORDER BY r.name
""")
channel_rev = {}
for name, rev_val in cur.fetchall():
    channel_rev[name] = f(rev_val)
    print(f"  {name}: ${f(rev_val):,.2f}")

print("\n=== STRUCTURAL TRADE (annual) ===")
rate_map = {
    "Walmart": f(rates[0]), "Costco": f(rates[1]),
    "Whole Foods": f(rates[2]), "Sprouts": f(rates[3]),
    "Kroger": f(rates[4]), "Regional Group": f(rates[5]),
}
structural = sum(channel_rev.get(ch, 0) * r for ch, r in rate_map.items())
total_rev = sum(channel_rev.values())
print(f"  Structural annual: ${structural:,.2f} = ${structural/1e6:.2f}M")
print(f"  Structural rate: {structural/total_rev*100:.1f}%")

print("\n=== OPERATIONAL WASTE ===")
cur.execute("SELECT SUM(amount) FROM raw.retailer_deductions "
            "WHERE deduction_type != 'promo_billback'")
ret_waste = f(cur.fetchone()[0])
cur.execute("SELECT COALESCE(SUM(amount), 0) FROM raw.distributor_deductions "
            "WHERE deduction_type != 'promo_billback'")
dist_waste = f(cur.fetchone()[0])
op_waste_36 = ret_waste + dist_waste
op_waste_annual = op_waste_36 / 3
print(f"  Retailer (36mo): ${ret_waste:,.2f}")
print(f"  Distributor (36mo): ${dist_waste:,.2f}")
print(f"  Total (36mo): ${op_waste_36:,.2f}")
print(f"  Annual: ${op_waste_annual:,.2f} = ~${op_waste_annual/1e3:.0f}K/yr")

all_in = structural + op_waste_annual
print(f"\n=== ALL-IN TRADE ===")
print(f"  All-in annual: ${all_in:,.2f} = ${all_in/1e6:.1f}M/yr")
print(f"  All-in rate: {all_in/total_rev*100:.1f}%")
print(f"  Op waste rate: {op_waste_annual/total_rev*100:.1f}%")

print(f"\n=== DEDUCTION TOTALS ===")
cur.execute("SELECT COUNT(*), SUM(amount) FROM raw.retailer_deductions")
r = cur.fetchone()
ret_ded_count, ret_ded_amt = r[0], f(r[1])
print(f"  Retailer: {ret_ded_count:,} rows, ${ret_ded_amt:,.2f}")
cur.execute("SELECT COUNT(*), SUM(amount) FROM raw.distributor_deductions")
r = cur.fetchone()
dist_ded_count, dist_ded_amt = r[0], f(r[1])
print(f"  Distributor: {dist_ded_count:,} rows, ${dist_ded_amt:,.2f}")
total_ded = ret_ded_amt + dist_ded_amt
print(f"  Combined: {ret_ded_count + dist_ded_count:,} rows, ${total_ded:,.2f}")

print(f"\n=== DEDUCTION BREAKDOWN BY TYPE ===")
for table, label in [("retailer_deductions", "Retailer"),
                      ("distributor_deductions", "Distributor")]:
    cur.execute(f"SELECT deduction_type, COUNT(*), SUM(amount) "
                f"FROM raw.{table} GROUP BY deduction_type "
                "ORDER BY SUM(amount) DESC")
    print(f"{label}:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[1]:,} / ${f(row[2]):,.2f}")

print(f"\n=== DISPUTE TOTALS ===")
cur.execute("SELECT COUNT(d.dispute_id), SUM(d.recovered_amount), SUM(ded.amount) "
            "FROM raw.retailer_disputes d "
            "JOIN raw.retailer_deductions ded ON d.deduction_id = ded.deduction_id")
r = cur.fetchone()
ret_recov, ret_disp_amt = f(r[1]), f(r[2])
print(f"  Retailer: {r[0]:,} disputes, recovered ${ret_recov:,.2f}, "
      f"disputed ${ret_disp_amt:,.2f}")
if r[0] > 0:
    print(f"    Recovery per disputed $: {ret_recov/ret_disp_amt*100:.1f}%")

cur.execute("SELECT COUNT(d.dispute_id), SUM(d.recovered_amount), SUM(ded.amount) "
            "FROM raw.distributor_disputes d "
            "JOIN raw.distributor_deductions ded ON d.deduction_id = ded.deduction_id")
r = cur.fetchone()
dist_recov, dist_disp_amt = f(r[1]), f(r[2])
print(f"  Distributor: {r[0]:,} disputes, recovered ${dist_recov:,.2f}, "
      f"disputed ${dist_disp_amt:,.2f}")
if r[0] > 0:
    print(f"    Recovery per disputed $: {dist_recov/dist_disp_amt*100:.1f}%")

total_recov = ret_recov + dist_recov
total_disp = ret_disp_amt + dist_disp_amt
print(f"  Combined recovery per all deduction $: {total_recov/total_ded*100:.2f}%")
print(f"  Combined recovery per disputed $: {total_recov/total_disp*100:.2f}%")

# Dispute tier breakdown
print(f"\n=== DISPUTE TIER BREAKDOWN ===")
for dtable, dedtable, label in [
    ("retailer_disputes", "retailer_deductions", "Retailer"),
    ("distributor_disputes", "distributor_deductions", "Distributor"),
]:
    cur.execute(f"SELECT d.evidence_quality, COUNT(*), SUM(d.recovered_amount), "
                f"SUM(ded.amount) FROM raw.{dtable} d "
                f"JOIN raw.{dedtable} ded ON d.deduction_id = ded.deduction_id "
                f"GROUP BY d.evidence_quality ORDER BY d.evidence_quality")
    print(f"{label}:")
    for row in cur.fetchall():
        tier_recov = f(row[2])
        tier_disp = f(row[3])
        rate = tier_recov / tier_disp * 100 if tier_disp > 0 else 0
        print(f"  {row[0]}: {row[1]:,} disputes, recovered ${tier_recov:,.2f} "
              f"/ disputed ${tier_disp:,.2f} = {rate:.1f}%")

print(f"\n=== REMITTANCE FIGURES ===")
cur.execute("SELECT COUNT(*), SUM(gross_amount), SUM(net_amount), "
            "SUM(total_deductions), SUM(trade_allowance), "
            "SUM(chargebacks_applied), SUM(timing_residual) "
            "FROM raw.retailer_remittances")
r = cur.fetchone()
ret_gross, ret_net = f(r[1]), f(r[2])
ret_ded_rem, ret_trade_rem = f(r[3]), f(r[4])
ret_cb_applied, ret_residual = f(r[5]), f(r[6])
print(f"  Retailer remittances: {r[0]} rows")
print(f"    Gross: ${ret_gross:,.2f}")
print(f"    Net: ${ret_net:,.2f}")
print(f"    Deductions: ${ret_ded_rem:,.2f}")
print(f"    Trade allowance: ${ret_trade_rem:,.2f}")
print(f"    Chargebacks applied: ${ret_cb_applied:,.2f}")
print(f"    Timing residual: ${ret_residual:,.2f}")
shortfall_ret = ret_gross - ret_net
classified_ret = shortfall_ret - ret_residual
if shortfall_ret > 0:
    print(f"    Total shortfall: ${shortfall_ret:,.2f}")
    print(f"    Classification rate: {classified_ret/shortfall_ret*100:.1f}%")
    print(f"    Residual rate: {ret_residual/shortfall_ret*100:.1f}%")
    print(f"    Net/Gross: {ret_net/ret_gross*100:.2f} cents per dollar")

cur.execute("SELECT COUNT(*), SUM(gross_amount), SUM(net_amount), "
            "SUM(total_deductions), SUM(trade_allowance), "
            "SUM(chargebacks_applied), SUM(timing_residual) "
            "FROM raw.distributor_remittances")
r = cur.fetchone()
dist_gross, dist_net = f(r[1]), f(r[2])
dist_ded_rem, dist_trade_rem = f(r[3]), f(r[4])
dist_cb_applied, dist_residual = f(r[5]), f(r[6])
print(f"  Distributor remittances: {r[0]} rows")
print(f"    Gross: ${dist_gross:,.2f}")
print(f"    Net: ${dist_net:,.2f}")
print(f"    Deductions: ${dist_ded_rem:,.2f}")
print(f"    Trade allowance: ${dist_trade_rem:,.2f}")
print(f"    Chargebacks applied: ${dist_cb_applied:,.2f}")
print(f"    Timing residual: ${dist_residual:,.2f}")
shortfall_dist = dist_gross - dist_net
classified_dist = shortfall_dist - dist_residual
if shortfall_dist > 0:
    print(f"    Total shortfall: ${shortfall_dist:,.2f}")
    print(f"    Classification rate: {classified_dist/shortfall_dist*100:.1f}%")
    print(f"    Residual rate: {dist_residual/shortfall_dist*100:.1f}%")
    print(f"    Net/Gross: {dist_net/dist_gross*100:.2f} cents per dollar")

combined_gross = ret_gross + dist_gross
combined_net = ret_net + dist_net
total_shortfall = (shortfall_ret + shortfall_dist)
total_residual = ret_residual + dist_residual
total_trade = ret_trade_rem + dist_trade_rem
total_ded_applied = ret_ded_rem + dist_ded_rem
total_cb_applied = ret_cb_applied + dist_cb_applied

print(f"\n=== LIFECYCLE (combined wholesale) ===")
print(f"  Combined gross: ${combined_gross:,.2f}")
print(f"  Combined net: ${combined_net:,.2f}")
print(f"  Combined shortfall: ${total_shortfall:,.2f}")
print(f"  Combined classification: "
      f"{(total_shortfall - total_residual)/total_shortfall*100:.1f}%")
print(f"  Combined residual: {total_residual/total_shortfall*100:.1f}%")
print(f"  Wholesale cents per dollar: {combined_net/combined_gross*100:.2f}c")

print(f"\n=== LIFECYCLE WATERFALL (wholesale) ===")
print(f"  Trade allowance: ${total_trade:,.2f} "
      f"({total_trade/combined_gross*100:.2f}% of gross)")
print(f"  Deductions applied: ${total_ded_applied:,.2f} "
      f"({total_ded_applied/combined_gross*100:.2f}% of gross)")
print(f"  Chargebacks applied: ${total_cb_applied:,.2f} "
      f"({total_cb_applied/combined_gross*100:.2f}% of gross)")
print(f"  Timing residual: ${total_residual:,.2f} "
      f"({total_residual/combined_gross*100:.2f}% of gross)")
total_leakage = total_trade + total_ded_applied + total_cb_applied + total_residual
print(f"  Total leakage: ${total_leakage:,.2f} "
      f"({total_leakage/combined_gross*100:.2f}% of gross)")
print(f"  Net: ${combined_net:,.2f} "
      f"({combined_net/combined_gross*100:.2f} cents per dollar)")

# Shipped $ for compliance rate
print(f"\n=== SHIPPED WHOLESALE $ ===")
cur.execute("SELECT SUM(s.units_shipped * ol.unit_price) "
            "FROM raw.retailer_shipments s "
            "JOIN raw.retailer_order_lines ol ON s.order_id = ol.order_id")
ret_shipped = f(cur.fetchone()[0])
cur.execute("SELECT SUM(s.units_shipped * ol.unit_price) "
            "FROM raw.distributor_shipments s "
            "JOIN raw.distributor_order_lines ol ON s.order_id = ol.order_id")
dist_shipped = f(cur.fetchone()[0])
print(f"  Retailer shipped $: ${ret_shipped:,.2f}")
print(f"  Distributor shipped $: ${dist_shipped:,.2f}")

# Fill rates
print(f"\n=== FILL RATES ===")
cur.execute("SELECT SUM(units_shipped)::float / SUM(units_ordered) "
            "FROM raw.retailer_shipment_lines")
ret_fill = f(cur.fetchone()[0])
print(f"  Retailer portfolio fill: {ret_fill*100:.2f}%")
cur.execute("SELECT SUM(units_shipped)::float / SUM(units_ordered) "
            "FROM raw.distributor_shipment_lines")
dist_fill = f(cur.fetchone()[0])
print(f"  Distributor portfolio fill: {dist_fill*100:.2f}%")

conn.close()
