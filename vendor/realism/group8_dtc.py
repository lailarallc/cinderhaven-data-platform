#!/usr/bin/env python3
"""The generator for group 8 - the own-site DTC channel - and its one survivability test: whether the
card networks' monitoring programs (A8.05) ever identify the brand (A8.03).

WHAT IT DOES, ON THE RULINGS OF 2026-10-02
------------------------------------------
Group 8's own-site rows apply to A8.01's 10% less Amazon's share of it (owner, 2026-09-15, item 12), so every
count here starts from group9_ledger's dtc_orders() on own_site_dollars(). Nothing is re-derived: the ledger owns
the order counts, and this file owns what group 8 does with them - the month, the chargeback, the network.

Two owner rulings of 2026-10-02 set the test:
  - A ONE-MONTH DISPUTE LAG (A8.03, owner-signed). A chargeback lands in the month after its order. Mastercard's
    ECM ratio is this month's chargebacks over LAST month's transactions, so the lag tests ECM the way the network
    tests it; a same-month convention divided November's peak chargebacks by October's base volume and fired ECM
    every November - an artifact of mismatched months, not a finding. A spread over one to three months is the
    sourced form, if a card-network lag source is ever reached.
  - EACH NETWORK COUNTS ITS OWN DISPUTES (A8.21, owner-signed). VDMP and ECM test a network's chargebacks against
    that network's floor; a blended total trips a floor neither network applies. The card mix is Visa 55 /
    Mastercard 30 / Amex and Discover 15, band +/-10 on each, and the episode derives from it: if it falls below a
    count floor at that mix, that is the finding, not a reason to move the mix.

The months: A8.17 registers Nov-Dec at 2.2x the average month and February at 0.7x; the other nine months are
flat at the level that makes the twelve average 1, which puts Q4 at 43.06% of the year's orders - the share A8.17
prints. Peak-month orders dispute at A8.03's drift of 1.0-1.1% (fraud-heavy gift orders), every other month at
A8.04's 0.9%; both ends of the drift and both ends of the mix band are run.

    python scripts/group8_dtc.py            # the report, a second
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import group9_ledger as G  # noqa: E402

YEARS = (2023, 2024, 2025)                    # mirror-exempt: the window's calendar years, y1-y3, not figures

# ------------------------------------------------------------ A8.17, the month
PEAK_MONTHS = (11, 12)                        # mirror-exempt: calendar months, November and December, named in words
PEAK = 2.2                                    # A8.17: Nov-Dec orders at 2.2x the average month
FEB = 0.7                                     # A8.17: February at 0.7x
BASE = (12 - PEAK * len(PEAK_MONTHS) - FEB) / 9.0   # the other nine months, flat, so the twelve average 1
MONTH = {m: PEAK if m in PEAK_MONTHS else FEB if m == 2 else BASE for m in range(1, 13)}

# ------------------------------------------------------------ A8.04 / A8.03, the chargeback
CB_RATE = 0.009                               # A8.04: chargebacks per settled order, the year's non-peak months
CB_PEAK = (0.010, 0.0105, 0.011)              # A8.03: the peak rate, one a window year, drifting on fraud-heavy gift
                                              # orders (owner, 2026-10-13, DECISIONS#u18-rulings Q2)
LAG = 1                                       # A8.03: a chargeback lands the month after its order (owner, 2026-10-02)

# ------------------------------------------------------------ A8.21, the card mix (owner-signed 2026-10-02)
MIX = {"visa": 0.55, "mastercard": 0.30, "other": 0.15}   # A8.21: Amex and Discover together are "other"
MIX_BAND = 0.10                               # A8.21: ±10 points on each brand

# ------------------------------------------------------------ A8.05, the programs, effective-dated
VDMP = dict(ratio=0.009, count=100)           # A8.05: Visa VDMP 'standard' (transcribed: no source entry)
VDMP_LAST = "2025-05-31"                      # A8.05: VDMP's last day; VAMP from the next, 2025-06-01 on Visa's
                                              # fact sheet (owner, 2026-11-03, DECISIONS#u14)
VAMP_COUNT = 1500                             # A8.05: VAMP's floor from 2025-06-01, fraud reports AND disputes
ECM = dict(ratio=0.015, count=100)            # A8.05: Mastercard ECM; the ratio's denominator is the prior month

# ------------------------------------------------------------ A8.10 / A8.12 / A8.06, what the counts drive
CASE_RATES = (20.0, 22.0, 24.0)               # A8.09: A3.26's parcel case-rate band and its midpoint, $ a case
CARTON = 4.50                                 # A8.12: carton-and-dim overhead a parcel, carrier-billed, $
SHIP_CHARGE, UNDER_THRESHOLD = 7.95, 0.70     # A8.12 / A3.18: what a one-time order under $50 pays, and how many do
SURCHARGE = (0.12, 4.50)                      # A8.12: parcels drawing a surcharge, and its average, $
CARRIER_DISCOUNT = 0.30                       # A8.12's one sensitivity: a negotiated discount on the whole parcel


def orders(t):
    """A8.02's own-site order counts in window year t, read from the ledger."""
    return G.dtc_orders(t, G.own_site_dollars(t))


def new_customers(t):
    """A8.02: first orders as a share of one-time orders."""
    return G.FIRST_ORDER_SHARE[t] * orders(t)["one_time"]


def monthly_orders():
    """Own-site orders by (year, month), the window plus December 2022 at y1's level - the one month before the
    window whose chargebacks the lag lands inside it. Registered history does not give 2022's own-site count."""
    out = {}
    for t, y in enumerate(YEARS):
        total = sum(orders(t).values())
        for m in range(1, 13):
            out[(y, m)] = total / 12.0 * MONTH[m]
    out[(YEARS[0] - 1, 12)] = sum(orders(0).values()) / 12.0 * MONTH[12]
    return out


def _prior(y, m, k=1):
    m -= k
    while m < 1:
        y, m = y - 1, m + 12
    return y, m


def peak_rate(y):
    """A8.03: the peak rate of the order's year -- the drift, one rate a window year; December 2022's orders, which the
    lag lands in January 2023, take y1's."""
    return CB_PEAK[YEARS.index(y)] if y in YEARS else CB_PEAK[0]


def chargebacks():
    """Chargebacks filed in each window month, all brands: last month's orders at that month's rate, the peak months at
    their year's point on A8.03's drift."""
    o = monthly_orders()
    out = {}
    for y in YEARS:
        for m in range(1, 13):
            py, pm = _prior(y, m, LAG)
            out[(y, m)] = o[(py, pm)] * (peak_rate(py) if pm in PEAK_MONTHS else CB_RATE)
    return out


def network_test(mix_visa, mix_mc):
    """Each program, each month, on its own network's disputes. Returns the months each fires, and the largest
    count and ratio each program sees in its effective window."""
    o, cb = monthly_orders(), chargebacks()
    vdmp, ecm = [], []
    v_max = dict(count=0.0, ratio=0.0)
    m_max = dict(count=0.0, ratio=0.0)
    vamp_max = 0.0
    for (y, m), c in sorted(cb.items()):
        visa, mc = c * mix_visa, c * mix_mc
        if (y, m) <= tuple(int(x) for x in VDMP_LAST.split("-")[:2]):
            ratio = visa / (o[(y, m)] * mix_visa)              # Visa: this month's disputes over this month's sales
            v_max = dict(count=max(v_max["count"], visa), ratio=max(v_max["ratio"], ratio))
            if ratio >= VDMP["ratio"] and visa >= VDMP["count"]:
                vdmp.append((y, m))
        else:
            vamp_max = max(vamp_max, visa)                     # disputes only: fraud reports are registered nowhere
        ratio = mc / (o[_prior(y, m)] * mix_mc)                # Mastercard: over the PRIOR month's sales
        m_max = dict(count=max(m_max["count"], mc), ratio=max(m_max["ratio"], ratio))
        if ratio >= ECM["ratio"] and mc >= ECM["count"]:
            ecm.append((y, m))
    return dict(vdmp=vdmp, ecm=ecm, visa_max=v_max, mc_max=m_max, vamp_disputes_max=vamp_max)


def corners():
    """The test on A8.03's drift at both ends of A8.21's mix band and the signed mix: Visa share -> result. Mastercard's
    share moves with Visa's in the opposite direction, so the 'other' 15 holds. The peak rate is no longer a corner:
    it is one rate a window year (owner, 2026-10-13)."""
    out = {}
    for dv in (-MIX_BAND, 0.0, MIX_BAND):
        out[MIX["visa"] + dv] = network_test(MIX["visa"] + dv, MIX["mastercard"] - dv)
    return out


def q4_share():
    """A8.17: Q4's share of the year's orders, on the registered month shape."""
    return sum(MONTH[m] for m in (10, 11, 12)) / 12.0


def active_subscribers(t):
    """A8.06: the active base, one S&S order a month each."""
    return orders(t)["subscription"] / 12.0


def paid_marketing(t):
    """A8.10: new customers x the paid share x the blended CAC, $ - the paid part of the ledger's marketing()."""
    return new_customers(t) * G.PAID_SHARE * G.CAC


def contribution_per_order(kind, case_rate, discount=0.0):
    """A8.11's contribution before marketing on one order, $: the AOV less COGS at A3.01's cost a jar, A8.12's net
    parcel at the case rate (less `discount` on the carrier-billed parcel), A8.13's 3PL and packaging, and payment."""
    aov, jars = G.AOV[kind], G.JARS_PER_ORDER[kind]
    parcel = ((CARTON + case_rate / 12.0 * jars) * (1 - discount)
              - (UNDER_THRESHOLD * SHIP_CHARGE if kind == "one_time" else 0.0))
    threepl = G.PICK + G.PER_UNIT * jars + G.PACK_MATERIAL
    return aov - jars * G.COST_12 - parcel - threepl - G.PAYMENT * aov


def channel_pnl(t, case_rate, discount=0.0):
    """A8.10: the own-site channel's contribution less paid marketing in window year t, $."""
    o = orders(t)
    return (o["one_time"] * contribution_per_order("one_time", case_rate, discount)
            + o["subscription"] * contribution_per_order("subscription", case_rate, discount) - paid_marketing(t))


def surcharges(t):
    """A8.12: unrecovered dimensional and handling surcharges on own-site parcels, $."""
    return SURCHARGE[0] * sum(orders(t).values()) * SURCHARGE[1]


def chargebacks_by_network():
    """Chargebacks filed in each window month by network, at A8.21's signed mix: chargebacks() on A8.03's drift, one
    peak rate a window year (U18 Q2), split Visa / Mastercard / other. A seeder reads it; no row prints it."""
    return dict((net, dict(("%d-%02d" % ym, c * share) for ym, c in sorted(chargebacks().items())))
                for net, share in MIX.items())


# ------------------------------------------------------------ U21, the entry function
def _printed_restated_21():
    """The values the gate's _restated_21_figures reads, keyed (anchor, label) as its entries name them."""
    d8o = [orders(t) for t in range(3)]
    d8c = corners()
    return [
        ('A8.02', "A8.02's own-site orders: one-time, S&S, then total, the row and group 8's doc",
         [o[k] for k in ("one_time", "subscription") for o in d8o] + [sum(o.values()) for o in d8o]),
        ('A8.02', "A8.02's new customers, the row and group 8's doc",
         [new_customers(t) for t in range(3)]),
        ('A8.03', "A8.03's own-site orders a month",
         [sum(o.values()) / 12 for o in d8o]),
        ('A8.03', "A8.03's chargebacks a month at A8.04's rate",
         [sum(o.values()) / 12 * CB_RATE for o in d8o]),
        ('A8.03', "A8.03's peak-month chargebacks on the drift",
         [sum(o.values()) / 12 * PEAK * CB_PEAK[t] for t, o in enumerate(d8o)]),
        ('A8.03', "A8.03's Visa ratio in its worst month",
         [d8c[MIX["visa"]]["visa_max"]["ratio"] * 100]),
        ('A8.03', "A8.03's most Visa disputes VDMP sees at the signed mix",
         [d8c[MIX["visa"]]["visa_max"]["count"]]),
        ('A8.03', "A8.03's most Visa disputes VDMP sees at the band's worst corner, the watched near-miss",
         [d8c[MIX["visa"] + MIX_BAND]["visa_max"]["count"]]),
        ('A8.03', "A8.03's Mastercard ratio at most",
         [d8c[MIX["visa"]]["mc_max"]["ratio"] * 100]),
        ('A8.03', "A8.03's most Visa disputes VAMP sees",
         [max(c["vamp_disputes_max"] for c in d8c.values())]),
        ('A8.06', "A8.06's active own-site subscribers",
         [active_subscribers(t) for t in range(3)]),
        ('A8.10', "A8.10's paid spend, $K",
         [paid_marketing(t) / 1e3 for t in range(3)]),
        ('A8.10', "A8.10's y1 channel P&L across A3.26's band, $K",
         [channel_pnl(0, c) / 1e3 for c in CASE_RATES]),
        ('A8.10', "A8.10's y1 channel P&L at $22: one-time, S&S, paid spend, the result, $K",
         [d8o[0]["one_time"] * contribution_per_order("one_time", 22.0) / 1e3,
          d8o[0]["subscription"] * contribution_per_order("subscription", 22.0) / 1e3,
          paid_marketing(0) / 1e3, channel_pnl(0, 22.0) / 1e3]),
        ('A8.12', "A8.12's carrier-discount sensitivity: the S&S order, then the y1 P&L, $ and $K",
         [contribution_per_order("subscription", 22.0, CARRIER_DISCOUNT),
          channel_pnl(0, 22.0, CARRIER_DISCOUNT) / 1e3]),
        ('A8.12', "A8.12's unrecovered surcharges, $K",
         [surcharges(t) / 1e3 for t in range(3)]),
        ('A8.17', "A8.17's flat month, then Q4's share of the year",
         [BASE, q4_share() * 100]),
    ]


def outputs():
    """U21's entry function: what the gate checks and the seeders read, one object (regen plan U21).

    `printed` holds every value the registry prints from this generator, keyed by the anchor id that prints it and
    then by the gate entry that reads it, at full precision. `series` holds the generation-path series a seeder reads
    and no row prints, keyed by the function that computes them: own-site orders by month and order type, December
    2022 included for the chargeback lag, and chargebacks by month and network."""
    printed = {}
    for anchor, label, value in _printed_restated_21():
        printed.setdefault(anchor, {})[label] = value
    by_type = dict((k, {}) for k in ("one_time", "subscription"))
    for (y, m), _ in sorted(monthly_orders().items()):
        o = orders(YEARS.index(y) if y in YEARS else 0)
        for k in by_type:
            by_type[k]["%d-%02d" % (y, m)] = o[k] / 12.0 * MONTH[m]
    return dict(printed=printed, series=dict(monthly_orders=by_type, chargebacks_by_network=chargebacks_by_network()))


def main():
    print("GROUP 8 - the own-site channel (A8.01's 10% less Amazon's share)")
    for t, y in enumerate(YEARS):
        o = orders(t)
        print("  %d  own-site $%.3fM  one-time %s  S&S %s  total %s  new customers %s"
              % (y, G.own_site_dollars(t) / 1e6, "{:,.0f}".format(o["one_time"]), "{:,.0f}".format(o["subscription"]),
                 "{:,.0f}".format(sum(o.values())), "{:,.0f}".format(new_customers(t))))
    print("\nA8.17  base month %.4fx; Q4 share %.2f%%" % (BASE, q4_share() * 100))
    for t, y in enumerate(YEARS):
        total = sum(orders(t).values())
        print("A8.03  %d  orders a month %s, peak %s; chargebacks a month at 0.9%% %.0f; peak at %.2f%% %.0f"
              % (y, "{:,.0f}".format(total / 12), "{:,.0f}".format(total / 12 * PEAK), total / 12 * CB_RATE,
                 CB_PEAK[t] * 100, total / 12 * PEAK * CB_PEAK[t]))
    print("\nA8.03 x A8.05 x A8.21  lag %d month; each network on its own disputes" % LAG)
    for v, res in sorted(corners().items()):
        print("  Visa %.0f%%  VDMP fires %s (max Visa disputes %.1f, ratio %.2f%%)  ECM fires %s "
              "(max %.1f, ratio %.2f%%)  VAMP disputes max %.1f of %d"
              % (v * 100, res["vdmp"] or "never", res["visa_max"]["count"], res["visa_max"]["ratio"] * 100,
                 res["ecm"] or "never", res["mc_max"]["count"], res["mc_max"]["ratio"] * 100,
                 res["vamp_disputes_max"], VAMP_COUNT))
    print()
    for t, y in enumerate(YEARS):
        print("A8.06  %d  active subscribers %s" % (y, "{:,.0f}".format(active_subscribers(t))))
    for t, y in enumerate(YEARS):
        print("A8.10  %d  paid marketing $%.1fK = %.1f%% of own-site revenue"
              % (y, paid_marketing(t) / 1e3, paid_marketing(t) / G.own_site_dollars(t) * 100))
    print("A8.10  y1 channel P&L at $20 / $22 / $24 a case: %s"
          % " / ".join("$%+.1fK" % (channel_pnl(0, c) / 1e3) for c in CASE_RATES))
    print("A8.10  per order at $22: one-time $%.2f, S&S $%+.2f"
          % (contribution_per_order("one_time", 22.0), contribution_per_order("subscription", 22.0)))
    print("A8.12  with a %.0f%% carrier discount at $22: S&S $%+.2f an order, y1 channel P&L $%+.1fK"
          % (CARRIER_DISCOUNT * 100, contribution_per_order("subscription", 22.0, CARRIER_DISCOUNT),
             channel_pnl(0, 22.0, CARRIER_DISCOUNT) / 1e3))
    print("A8.12  unrecovered surcharges %s" % " / ".join("$%.1fK" % (surcharges(t) / 1e3) for t in range(3)))


if __name__ == "__main__":
    main()
