#!/usr/bin/env python3
"""The single generator for group 9 - the P&L identity, working capital, the
borrowing base and the cash ledger.

WHY THIS EXISTS
---------------
Group 9's sourcing doc claimed "every number below is printed by the script that
writes the registry rows". No such script was ever in the repository. The 2026-09-11
audit found four registered rows the P&L had never read (A4.15, A9.16, A9.17,
A3.27) and a working capital that charged every deducted dollar twice - defects a
generator would have made visible, because a figure you cannot reproduce is a
figure nobody can check.

This file is now that generator, and it is the ONLY one. `add_group9.py` and
`doc_group9.py` are retired and must not be run against the restated P&L.

WHAT IT ENFORCES
----------------
Every figure below is computed from a registered anchor. The inputs that are NOT
derived are listed in INPUTS with their owner_signed date, so that the count of
free parameters is visible rather than buried. Six were unregistered before
2026-09-11; five are now signed or derived and D0 is signed with its band.

    python scripts/group9_ledger.py            # the report
    python scripts/group9_ledger.py --bands    # adds the sensitivity tables

A9.02 READS THE COSTS GROUP 11 REGISTERS (ruled 2026-09-14, on the 2026-09-12 rule that a registered
charge is read): A5.21's write-offs, Faire's commission and processing, the organic certificate and
Oregon's packaging fee. The recall cost is a draw at generation and is not in this P&L.
"""
import calendar
import math
import sys
from datetime import date, timedelta
from fractions import Fraction

# ---------------------------------------------------------------- registered rows
GROSS = [32.500, 40.625, 46.71875]        # A1.01 ladder, exact (owner, 2026-09-25: exact wins); group 10 reads this copy
GROSS_PRE = 25.0                         # A1.01 window start
S_DTC = 0.10                              # A8.01
TRADE = 0.14                              # A4.14 rate-card accrual
OPDED = [0.045, 0.0525, 0.060]            # A4.01
OVERSETTLE = 0.115                        # A4.15 midpoint, owner-signed; band 0.08-0.15
OVERSETTLE_ACHIEVABLE = 0.0               # A4.15 achievable: settlements within +/-2% of accrual, accrued at the
                                          # event. The band's midpoint, as OVERSETTLE is the current band's.
SETTLE_LAG = 45                           # A4.30 30-60 day lag, midpoint
COST_12 = 2.61                            # A3.01 fully loaded, 2025 base, owner-signed
COST_MANUFACTURED = 2.10                  # A3.01's MANUFACTURED cost, ingredient + packaging + conversion, the base
                                          # A3.29's rolled standard reads (U21: typed here, was read from A3.01's prose)
COST_18 = 3.55                            # A3.27
PRICE = {"Walmart": 4.40, "Kroger": 4.60, "WF": 5.00, "Regional": 4.60, "UNFI": 3.90,
         "KeHE": 4.00, "DPI": 4.10, "Sprouts": 4.85, "small": 4.60}   # A3.04, 2025 list
PRICE_CLUB = 11.30                        # A3.04 club twin
ASK = [0.0, 0.02, 0.03]                   # A3.22 list increase, Jan of each year. mirror-exempt: ASK[0], an unread pad.
                                          # _price_index reads ask[1], ask[2]; a Jan 2023 ask moves only 2022's price
GIVEBACK = 0.40                           # A3.22 EDLP give-back, Walmart only (A4.13)
SHARE = {"Walmart": [30, 31.5, 29.5], "Kroger": [22, 19, 16.5], "WF": [14, 12, 10],
         "Regional": [10, 9, 8], "UNFI": [12, 14, 16], "KeHE": [8, 9.5, 9],
         "DPI": [2, 0, 0], "small": [2, 1.5, 1.5], "Sprouts": [0, 3.5, 4],
         "Costco": [0, 0, 5.5]}           # A5.38, % of wholesale dollars. DPI ENDS AFTER y1 and its two points
                                          # move to KeHE from y2 (owner, 2026-09-15, item 5): KeHE closed on DPI
                                          # Specialty Foods on 2023-06-20, and DPI as a separate account ends
                                          # 2023-12-31 on an integration lag. A3.04 follows without an edit -- the
                                          # moved dollars price at KeHE's $4.00, not DPI's $4.10.
DAYS_TO_PAY = {"Walmart": 62, "Kroger": 38, "WF": 35, "Regional": 45, "UNFI": 25,
               "KeHE": 33, "DPI": 32, "small": 60, "Sprouts": 35, "Costco": 30}  # A9.11; small accounts
                                          # 70 -> 60 on A11.04's ruling: Faire pays on its 60-day payout
DAYS_DTC = 2                              # A9.11 card settlement
A916_WEIGHTS = dict(fruitveg=16, olive=7, sugar=5, glass=15, truck=7, labor=12)   # A9.16: % of fully loaded COGS
                                          # each series carries; the other 38% has no series and is held flat
A916_SERIES = dict(fruitveg=(246.44, 280.69, 292.09, 297.94), olive=(4470, 7710, 8860, 5465),
                   sugar=(35.74, 40.57, 38.22, 35.92), glass=(251.61, 278.42, 288.19, 298.72),
                   truck=(203.10, 186.19, 175.35, 179.44))   # A9.16: annual means 2022-2025 of the five series,
                                          # from their 12 months (owner, 2026-10-25, DECISIONS#u14)
A916_DEC = dict(fruitveg=(224.628, 265.225, 290.667, 293.704), sugar=(36.71, 36.52, 39.96, 36.64),
                glass=(240.583, 257.393, 273.954, 293.207))   # A9.16: each December 2021-2024, the price a 12-month
                                          # contract signed for the next year fixes
A916_CONTRACT = dict(share=40, ingredients=44, olive=7)   # A9.16: % of ingredient spend on 12-month contracts, the
                                          # ingredients' % of COGS, and olive oil's, which is spot
TARIFF = [0.0, 0.0, 0.07 * (0.10 * 124 + 0.15 * 147) / 365 + 0.03 * (0.25 * 84 + 0.50 * 211) / 365
          + 0.04 * 0.10 * 222 / 365]      # A9.17, DAY-WEIGHTED (owner, 2026-10-01): each action takes effect at
                                          # 12:01 a.m. on its date, so 2025 is weighted by days in force, end date
                                          # inclusive. Olive oil 7% of COGS: EO 14257's 10% 04-05..08-06 (124 days),
                                          # the EU framework's 15% 08-07..12-31 (147). Closures 3%: Proclamation
                                          # 10896's 25% 03-12..06-03 (84), 10947's 50% 06-04..12-31 (211), at full
                                          # value until Annex I is read. Spices 4%: 10% 04-05..11-12 (222), out
                                          # from 11-13 on EO 14360's annex (owner read it, 2026-11-02).
JAR_ONE_TIME, JAR_SS = 8.68, 7.64         # A8.02 realized price a jar: one-time orders, Subscribe & Save
SS_SHARE = [0.30, 0.35, 0.40]             # A8.02 S&S share of own-site dollars
DTC_COGS = [COST_12 * ((1 - SS_SHARE[t]) / JAR_ONE_TIME + SS_SHARE[t] / JAR_SS) for t in range(3)]
                                          # A8.11, per year (owner, 2026-09-25: exact wins): A3.01's cost over the
                                          # realized own-site jar, blended at A8.02's S&S share -- the blend
                                          # dtc_jars() uses. It was one 0.317 literal, y3's share applied to all three.
PAYMENT = 0.03                            # A8.11: card payment processing, share of own-site revenue
SHIPPING_ACHIEVABLE = 0.16                # A8.12's achievable net shipping, share of merchandise revenue
THREEPL_ACHIEVABLE = 0.14                 # A8.13's achievable 3PL and packaging, with a right-sized carton set
# ---------------------------------------------------------- A9.01, the opex ladder
# DERIVED 2026-09-18. It was `OPEX = [7.280, 8.452, 9.763]`, a hardcoded INPUT: about thirty
# magnitudes behind no cross-check, the largest unwatched surface in the package. Deriving it
# found three defects the literal had hidden - see DECISIONS#A9.01-derived.
#
# A9.05's BURDEN OPERATOR IS wage / 0.703, NOT wage x 1.4225. The row registers both and they are
# not the same operator. Every LOADED figure A9.05 publishes is the wage over the ECEC wage share:
# the bookkeeper is decisive, 49,210 / 0.703 = 70,000.00 exactly against 49,210 x 1.4225 = 70,001.23,
# and six of the seven registered LOADED figures separate the two the same way.
WAGE_SHARE = 0.703                        # A9.05: ECEC March 2025, wages as a share of compensation
ANALYST = (75000.0, 1485)                 # A9.08: a deductions analyst's base wage, $, and productive hours a year
DISPUTE_HOURS = 1.5                       # A9.08: hours a dispute takes (A4.12)
WAGE_INFLATION = 0.035                    # A9.05


def _cogs_level(k, i):
    """A9.16's price a series charges in year 2022 + i: the contracted share of the non-olive ingredients at the
    prior December, the rest at the year's mean; glass on its annual contract at the prior December; olive oil and
    freight at spot."""
    C, S = A916_CONTRACT, A916_SERIES
    if k == "glass":
        return A916_DEC[k][i]
    if k in A916_DEC:
        c = C["share"] * C["ingredients"] / 100.0 / (C["ingredients"] - C["olive"])
        return c * A916_DEC[k][i] + (1 - c) * S[k][i]
    return S[k][i]


def _cogs_index_yoy():
    """A9.16's COGS inflation by window year, DERIVED on its registered contract terms (owner, 2026-10-25,
    DECISIONS#u14): each series' move in what the brand pays, at its weight; conversion labor at A9.05's wage
    inflation; the unmapped 38% held flat. The spot index, every input at its year mean, was computed and rejected:
    it is not what the P&L charges."""
    W = A916_WEIGHTS
    return [(sum(W[k] * (_cogs_level(k, t + 1) / _cogs_level(k, t) - 1) for k in A916_SERIES)
             + W["labor"] * WAGE_INFLATION) / 100 for t in range(3)]


COGS_INDEX_YOY = _cogs_index_yoy()        # A9.16, contract-weighted; a rounded [0.06, 0.03, -0.01] until U14
WAGE = {"warehouse": 40000, "sales_mgr": 135160, "acct_mgr": 85000, "ops_planner": 80000,
        "controller": 110000, "bookkeeper": 47440, "clerk": 44000, "mktg_mgr": 90000,
        "dtc_coord": 55000, "ceo": 200000, "coo": 160000}   # A9.05 OES May 2023 medians and practitioner roles
# A9.04's non-production functions resolved to A9.05's roles; A9.04 registers the composition (owner,
# 2026-09-25: an input the generator reads is registered, never carried as "not a registered fact"). With
# each function drawing its own roles, it is the one mapping that reproduces A9.01's registered y1 and y2
# (2.271 / 2.350) and its own warehouse check (0.284 / 0.294 / 0.366); y3 follows it. Pool the sales,
# planning and marketing roles across those seats and six multisets reproduce y1 and y2. Production & QA
# (16 / 17 / 19) sits in A3.01's conversion cost, not here.
ROSTER = {
    "y12": [("warehouse", 5), ("sales_mgr", 1), ("acct_mgr", 3), ("ops_planner", 3),
            ("controller", 1), ("bookkeeper", 1), ("clerk", 1), ("mktg_mgr", 1),
            ("dtc_coord", 2), ("ceo", 1), ("coo", 1)],                      # 20 heads
    "y3":  [("warehouse", 6), ("sales_mgr", 1), ("acct_mgr", 4), ("ops_planner", 4),
            ("controller", 1), ("bookkeeper", 1), ("clerk", 2), ("mktg_mgr", 1),
            ("dtc_coord", 3), ("ceo", 1), ("coo", 1)],                      # 25 heads
}
WAREHOUSE_HEADS = [5, 5, 6]               # A9.04, the Establish check's numerator
BROKER_SHARE = [0.55, 0.52, 0.49]         # A9.09 broker-managed share of wholesale dollars. RESTATED
                                          # 2026-09-18 from 55 / 50 / 47: A5.38's DPI line ends after y1
                                          # (owner, 2026-09-15, item 5) and its two points move to KeHE.
                                          # A9.09 names DPI DIRECT and KeHE inside the broker-managed
                                          # natural channel, so two points of wholesale cross INTO
                                          # commission in y2 and y3. The pre-ruling series did not move.
                                          # A READING: A9.09 asserts the aggregate and never decomposes
                                          # the natural channel's broker-covered fraction, so the move is
                                          # taken at its full two points. OWED: that decomposition.
BROKER_RATE = 0.04                        # A9.09, on wholesale dollars. A9.09's denominator field says
                                          # "net invoiced (gross less off-invoice allowances)" but no
                                          # non-zero allowance reproduces its registered cost, and the
                                          # gross-wholesale base does, to the dollar. The words and the
                                          # arithmetic disagree; the arithmetic is what is registered.
BROKER_RETAINER = 2 * 2500 * 12           # A9.09, two brokers at $2,500 a month. Flat: at A9.05's 3.5%
                                          # the y2 line breaks A9.09's registered cost.
FREIGHT_PCT = 0.055                       # A5.24, outbound, FLAT (the 6.5% y3 ramp is retracted)
SUPPLIES_PCT = 0.002                      # A9.01: warehousing supplies, equipment and outside storage
GA_PCT = 0.032                            # A9.01's one practitioner line, decomposed below
GA_SPLIT = [("rent", 0.010), ("insurance", 0.004), ("software_it", 0.004), ("professional", 0.005),
            ("travel", 0.003), ("bad_debt", 0.002), ("other", 0.004)]    # A9.01: shares of gross, summing to GA_PCT
GA_RENT_WAREHOUSE = 0.60                  # A9.01: the warehouse share of the rent line
CAC = 52.0                                # A8.10 paid blended
PAID_SHARE = 0.40                         # A8.10 paid share of new customers
FIRST_ORDER_SHARE = [0.45, 0.42, 0.38]    # A8.02 first orders as a share of one-time orders
BRAND_MARKETING_PCT = 0.010               # A9.01's brand line. REGISTERED NOWHERE ELSE: 1.0% of gross
                                          # appears only inside A9.01's own value and the group-9 doc.
                                          # OWED: its own row, or a decision_ref that sizes it.
AOV = {"one_time": 42.0, "subscription": 28.0}          # A8.02 realized revenue an order
PICK, PER_UNIT, PACK_MATERIAL = 2.75, 0.45, 1.80        # A8.13 3PL, per order / per unit / per order
JARS_PER_ORDER = {"one_time": AOV["one_time"] / JAR_ONE_TIME, "subscription": AOV["subscription"] / JAR_SS}
                                          # A8.02, one jar count per order type: the realized AOV over the realized
                                          # jar, exact (4.8387 / 3.6649, printed 4.84 / 3.66). Typed as 4.84 / 3.66
                                          # until U4, it disagreed with DTC_COGS's cost over the same jar (owner,
                                          # 2026-09-25: exact wins), so 3PL and COGS read two jar counts
# ---- A11.31, FBA fulfilment. Tier A on the 2025 fee (owner, 2026-09-18), transcribed by the owner
# from Seller Central's "2026 US FBA fulfillment fee changes" page, which carries the 2025 and 2026
# non-peak schedules side by side: "FBA Non-Peak Fulfillment Fees (excluding apparel), January 15,
# 2025 - October 14, 2025". The working session that registered it could not read the page - every
# Amazon domain and the Internet Archive were refused by its network - so the figures are the owner's
# transcription, and a local session read the page and confirmed every figure on 2026-09-22 (A11.31).
FBA_2025 = {"1-1.25lb_under10": 4.22, "1-1.25lb_10to50": 4.99, "2.25-2.5lb": 6.05,
            "3-20lb_base": 6.92, "3-20lb_per_4oz_over_3lb": 0.08}
FBA_LOW_PRICE = 10.00                     # A11.31: the under-$10 column A3.18's $8.99 single takes
FBA_PEAK_UPLIFT = {"1-1.25lb_under10": 0.30, "1-1.25lb_10to50": 0.30, "2.25-2.5lb": 0.39,
                   "3-20lb_base": 0.54}   # A11.31, TIER B: the per-unit increase peak takes over non-peak,
                                          # measured on the 2026 columns and carried back to 2025 on Amazon's
                                          # own sentence that a peak card "will have the same per unit increase
                                          # over non-peak rates as last year". The 2025 peak card itself was
                                          # not read, so this is the statement's consequence and not a rate.
FBA_PEAK_DAYS = 92                        # A11.31: 15 October - 14 January, the days of it falling in a
                                          # calendar window year (78 + 14)
PACK_MIX = {1: 0.20, 2: 0.30, 3: 0.50}    # A11.03, owner-signed 2026-09-18: shares of Amazon JARS,
                                          # not of orders. 20% move as singles, 30% in 2-packs, 50% in 3-packs.
PACK_LB = {1: 1.08, 2: 2.40, 3: 3.55}     # A2.08's 1.08 lb filled unit for the single; the 2- and 3-pack
                                          # weights are the owner's, and are above the bare jar sum
                                          # (2.16, 3.24) by the multipack's own packaging, which A2 does
                                          # not register. FEES USE THE GREATER OF UNIT AND DIMENSIONAL
                                          # WEIGHT; a 12 oz glass jar's dim weight is about 0.26 lb, below
                                          # A2.08's 1.08, so unit weight governs and no dim calculation enters.
REFERRAL_BY_PACK = {1: 0.08, 2: 0.15, 3: 0.15}   # A11.22: 8% at $15.00 or less, 15% above. At A3.18's
                                          # $8.99 a jar a single is under and both packs are over.
FBA_STORAGE_UNIT = 0.05                   # A11.31, Tier B: monthly storage a unit at A9.12's days of supply
FBA_INBOUND_UNIT = 0.27                   # A11.31, Tier B: inbound placement a unit
RETURNLESS_SHARE = 0.02                   # A11.31, Tier B: returnless refunds, share of Amazon orders. READ
                                          # as the order's revenue lost, since a returnless refund forgoes
                                          # both the unit and the sale.
SHIPPING_NET = [0.250, 0.261, 0.272]      # A8.12 net DTC shipping, share of merchandise revenue. A9.01's
                                          # freight line carries the DTC parcel inside A5.24's 5.5% of gross;
                                          # FBA fulfilment INCLUDES delivery, so the Amazon share of that
                                          # parcel is carved out or the channel pays for delivery twice.
ACOS = 0.25                               # A11.30 Amazon advertising, share of Amazon sales. OWNER-SIGNED
                                          # 2026-09-18 at the midpoint of the 20-30% band, which the row
                                          # carries beside the point.
ACOS_BAND = (0.20, 0.30)                  # A11.30's ACoS band, share of Amazon sales: A11.32's window band runs both
                                          # ends (U21: typed here, was read from A11.30's prose)
DIO = [58, 60, 62]                        # A9.12
DAYS_RAW_PACK = 20                        # A9.12 raw and packaging
DPO = 32                                  # A9.11
BUILD_PCT = 0.40                          # A9.12, owner-signed
RESIDUALS = [0.20, 0.29, 0.38]            # A9.15 open deduction residuals
BILLBACK_MCB = 0.090                      # A4.31 share of gross deducted from remittances

# costs group 11 registers, read into A9.02 (ruled 2026-09-14)
WRITE_OFF = [0.015, 0.020, 0.025]         # A5.21: 1.5% -> 2.5% of average inventory value at COGS, y2 the midpoint
FAIRE_SPLIT = {"marketplace": 0.40, "direct_program": 0.10, "direct": 0.50}   # A11.04, owner-signed 2026-09-15
                                          # (item 7): 40% through the Faire marketplace, 10% Faire Direct, 50% direct.
                                          # The marketplace share pays A3.20's commission; Faire Direct pays 0%
                                          # commission and DOES pay processing, which Faire's dated announcement of
                                          # 2023-05-17 works as a Faire Direct example; the direct half pays neither.
FAIRE_ORDER = 450.0                       # A5.02 restated on the same ruling: small-account orders are the tier's
                                          # dollars over a Faire-typical order of about $450, not 120 pallet drops
FAIRE_COMMISSION = 0.15                   # A3.20: reorders throughout; first orders too from 2023-07-05
FAIRE_PROCESSING = (0.019, 0.30)          # A3.20: 60-day payout, share of subtotal + $ an order, from 2023-07-05
FAIRE_TERMS_FROM = (date(2023, 7, 5) - date(2023, 1, 1)).days   # A3.20: days of y1 before 2023-07-05, when
                                          # Faire charged no processing fee -- counted from the date, never typed
FAIRE_DAYS_BEFORE = 30                    # A3.20: the free 30-day payout before 2023-07-05 - the pre-window balance's terms
SMALL_ORDERS_ASSERTED = [120, 120, 120]   # A5.02's asserted count, retired 2026-09-15 (item 7); kept to print beside
                                          # what now derives, because the one-pallet objection rested on it.
                                          # mirror-exempt: retired, printed beside the derived count as history (A5.02)
AMAZON_SHARE = [0.30, 0.35, 0.40]         # A11.01, owner-signed 2026-09-15 (item 12): Amazon's share of A8.01's 10%,
                                          # 30% in y1 rising to 40% in y3, y2 the midpoint as the package takes a
                                          # stated start and end (A5.11, A5.21, A5.25, A7.12)
AMAZON_PRICE = 8.99                       # A3.18's DTC everyday price. A READING: the ladder is untouched (item 12),
                                          # and A8.16's welcome codes are an own-site program, so no code discount
AMAZON_REFERRAL = (0.08, 0.15)            # A11.22: 8% of the whole price at $15.00 or less, 15% above. A single jar at
                                          # A3.18's $8.99 takes 8%; A11.03's 2- and 3-packs cross $15 and take 15%.
                                          # A11.03's pack mix is owner-signed (2026-09-18) and A9.01's marketplace
                                          # line reads the referral BLENDED over it; the floor is the retired reading
AMAZON_PLAN = 39.99 * 12                  # A11.22: the Professional selling plan, a year
ORGANIC_SHARE = 0.20                      # A2.18: organic claim on ~20% of SKUs - a count standing in for sales
IN_HOUSE_SKUS = 26 / 39.0                 # A11.09: in-house share of the non-club catalogue, 26 of 39 (group 2)
TILTH_TIERS = [(10.0, 9000, 5000), (15.0, 12000, 7000), (20.0, 14000, 10000)]   # A11.09: $M ceiling, Retail, Wholesale
INSPECTION = (13, 72.0)                   # A11.09: billable hours for a full annual inspection, the midpoint of the research's
                                          # 10-16, x Tilth's $/hour; travel time and expenses unregistered
FACILITY_FEE = 300.0                      # A11.09: $ a year for each facility listed under one master certificate, the
                                          # brand's one facility included (U4, owner). Was read as charged per EXTRA
                                          # facility only, so a one-facility certificate paid none (2026-09-14 audit)
OCCSP = (0.75, 750, 2)                    # A11.09: share, $ cap per scope, window years whose reimbursement lands.
                                          # mirror-exempt: OCCSP[2], a count of window years; A11.09 prints that none lands in 2025
OREGON_POP = 0.01254                      # A11.25: Oregon's share of the U.S. population in 2024, the reported
                                          # year (Census Vintage 2025, A11.10's source). 2023's and 2025's were
                                          # carried here unread; they stay registered in A11.10's source
WALMART_OREGON = (27, 3560)               # A11.25: Oregon Supercenters (Walmart, as of 2024-02-05) over U.S. (10-K, 2024-01-31)
UNIT_LB = PACK_LB[1]                      # A2.08's 1.08 lb filled unit (owner, 2026-09-28): the single's weight, one
                                          # value with PACK_LB[1]. It derived as 13/12 (1.0833) from a ~13 lb case,
                                          # which no row registers
NET_CONTENTS_LB = 12 / 16.0               # A2.08: a 12 oz unit's contents, 0.75 lb, which no packaging fee reads
GLASS_RATE = 0.11                         # A11.10: CAA's 2025 glass rate, $ a pound. TIER B, EFFECTIVE-DATED to 2025
                                          # (owner, 2026-09-15, item 6): it is the class average for glass and ceramics
                                          # in CAA's webinar deck of 2025-05-29, not a line rate, and CAA's 2025 line
                                          # rates sit on a login-only portal
GLASS_RATE_2026 = 0.10                    # A11.10: CAA's first DATED schedule, published 2025-10-29: glass bottles and jars.
                                          # Printed beside the window figure, never applied to it (A1.07's Do-not)
METRIC_TON_LB = 2204.62                   # mirror-exempt: pounds per metric ton, a unit conversion, not a figure
PRIME_MONTHLY = [[7.50, 7.74, 7.82, 8.00, 8.23, 8.25, 8.29, 8.50, 8.50, 8.50, 8.50, 8.50],
                 [8.50, 8.50, 8.50, 8.50, 8.50, 8.50, 8.50, 8.50, 8.30, 8.00, 7.81, 7.65],
                 [7.50, 7.50, 7.50, 7.50, 7.50, 7.50, 7.50, 7.50, 7.38, 7.23, 7.00, 6.83]]
                                          # A9.14: FRED MPRIME as published, % a year, Jan..Dec of 2023 / 2024 / 2025
SPREAD = 0.015                            # A9.14: prime + 1.5%, the practitioner spread
PRIME_PLUS = [sum(m) / 12 / 100 + SPREAD for m in PRIME_MONTHLY]   # the all-in rate on each year's EXACT mean (owner,
                                          # 2026-09-30): the ledger reads the published months, never a rounded mean
UNUSED_FEE = 0.00375                      # A9.14
ACTUAL_360 = 365.0 / 360.0                # A9.14 day count. mirror-exempt: the ACT/360 convention, printed as 365/360
COMMITMENT = [3.0, 4.5, 4.5]              # A9.14, upsized Q1 y2
INV_SUBLIMIT = 1.5                        # A9.14
INELIGIBLE_90D = 0.08                     # A9.14
AVAIL_HARD = 0.25                         # A9.14 minimum excess availability
SPRING_PCT = 0.10                         # A9.14 springing FCCR trigger
AMENDMENT_FEE = 0.0075                    # A9.14, 0.50% of the $1.5M commitment increase
FORBEARANCE_FEE = 0.01125                 # A9.14, 0.25% of the $4.5M commitment
DEFAULT_BUMP = 0.02                       # A9.14, +200bp on breach

# ------------------------------------------------------------------- free inputs
INPUTS = [
    ("D0, net standing draw at window start", "1.0 (band 0.5-1.5)", "owner-signed 2026-09-11"),
    ("maintenance capex", "0.30", "owner-signed 2026-09-11"),
    ("owner tax distribution rate", "0.35 of positive pre-tax income", "owner-signed 2026-09-11"),
    ("Q4 build, share of finished goods", "0.40", "owner-signed on A9.12"),
    ("peak month", "first half of November", "DERIVED: DPO after the last build receipt, DSO before the first Q4 collection"),
    ("finished-goods share of DIO", "(DIO - 20) / DIO", "DERIVED from A9.12"),
]
D0 = 1.0                     # A9.13: the net standing draw at window start, $M, owner-signed (band 0.5-1.5)
CAPEX = 0.30                 # A9.13: maintenance capex, $M a year, owner-signed
DISTRIB = 0.35               # A9.13: owner tax distributions, share of positive pre-tax income, owner-signed
ELAPSED = 10.5 / 12          # A9.12: the low point, the first half of November -- 10.5 of 12 months elapsed


def _price_index(ask, giveback):
    """Realized price level by year, relative to the 2025 base list (A3.04).

    The literals are integers so the index takes the type it is given: floats here, and the exact Fractions
    group 10's shelf ladder solves in (FAILURES 2026-09-22, a rounding rule is solved exactly). For float
    inputs the result is bit-identical to the 1.0 it replaced."""
    out = {}
    for k in list(PRICE) + ["Costco"]:
        r = (1 - giveback) if k == "Walmart" else 1
        cum = [1, 1 + ask[1] * r, (1 + ask[1] * r) * (1 + ask[2] * r)]
        out[k] = [c / cum[2] for c in cum]     # back-cast: 2025 is the base
    return out


def own_site_dollars(year):
    """A8.01's 10% less Amazon's share of it (owner, 2026-09-15, item 12): DTC and the marketplace together
    are the 10%, so group 8's own-site rows apply to the remainder."""
    return GROSS[year] * S_DTC * 1e6 * (1 - AMAZON_SHARE[year])


def amazon_dollars(year):
    """Amazon's share of A8.01's 10%, owner-signed at 30% rising to 40%. On top of nothing and carved from
    nothing: the 10% is unchanged, so the 2026-09-02 rule that new revenue never comes out of the six
    retailers is untouched - what moves is which rows read which part of it."""
    return GROSS[year] * S_DTC * 1e6 * AMAZON_SHARE[year]


def dtc_jars(year):
    """A8.02's jars, the OWN-SITE unit count: the own-site dollars split by order type, each at its own
    realized price. Amazon's units are amazon_units(); together they are the consumer-channel units the
    catalogue draw spreads over every live SKU."""
    return own_site_dollars(year) * ((1 - SS_SHARE[year]) / JAR_ONE_TIME + SS_SHARE[year] / JAR_SS)


def amazon_units(year):
    """Amazon's units: its dollars at A3.18's everyday price. A READING - the price ladder is untouched and
    A8.16's welcome codes are an own-site program, so a marketplace jar carries no code discount. A11.03's
    multipacks are listings of the same UPC, so they change the referral rate, not the unit count."""
    return amazon_dollars(year) / AMAZON_PRICE


def amazon_fees(year):
    """A11.22's referral fee at the 8% floor, its band, and the Professional plan, $M. The floor and the band are the
    RETIRED reading, kept as the dated record of what the P&L read before 2026-09-18 (A11.01); the plan is current.

    The referral rate is a band: A11.22 registers 8% of the whole price at $15.00 or less and 15% above. Since
    2026-09-18 the P&L reads it BLENDED over A11.03's owner-signed single-versus-multipack mix, with the plan and
    A11.31's FBA fulfilment and storage, through marketplace_fees() -- A9.01's marketplace line. Group 11 prints this
    function's output as the record; nothing that prices the window reads it."""
    dollars = amazon_dollars(year)
    return dict(referral=dollars * AMAZON_REFERRAL[0] / 1e6, plan=AMAZON_PLAN / 1e6,
                band=[dollars * r / 1e6 + AMAZON_PLAN / 1e6 for r in AMAZON_REFERRAL],
                total=(dollars * AMAZON_REFERRAL[0] + AMAZON_PLAN) / 1e6)


def units_by_account(t, ask=None, giveback=GIVEBACK):
    """A5.38's wholesale dollars over A3.04's realized prices: units by account in year t; Costco in jars."""
    ask = ASK if ask is None else ask
    f = _price_index(ask, giveback)
    w = GROSS[t] * (1 - S_DTC) * 1e6
    out = dict((k, SHARE[k][t] / 100.0 * w / (PRICE[k] * f[k][t])) for k in PRICE)
    out["Costco"] = SHARE["Costco"][t] / 100.0 * w / (PRICE_CLUB * f["Costco"][t]) * 2
    return out


def small_dollars(t):
    """The small-account tier's wholesale dollars, A5.38's share of the wholesale line."""
    return GROSS[t] * (1 - S_DTC) * SHARE["small"][t] / 100.0 * 1e6


def small_orders(t):
    """A5.02 restated on the owner's ruling of 2026-09-15 (item 7): the tier's dollars over a Faire-typical
    order of about $450, not 120 pallet-sized drops. The split does not enter - a direct order is the same
    size as a marketplace one until a row says otherwise, which is a READING."""
    return small_dollars(t) / FAIRE_ORDER


def faire_fees(t):
    """A3.20's commission and processing on the tier's Faire dollars, $M, on the split the owner signed
    2026-09-15 (item 7).

    The marketplace 40% pays the 15% commission and processing. FAIRE DIRECT'S 10% PAYS PROCESSING BUT NO
    COMMISSION: its 0% commission and the processing that reaches it are both in the Brand Terms, and that
    processing reaches Faire Direct orders is dated by Faire's announcement of 2023-05-17, which works a
    Faire Direct example. The direct 50% pays neither. Processing begins 2023-07-05, so y1 pays it on the
    days after. What a first order pays above a reorder - 25% before 2023-07-05, the $10 new-customer fee
    after - is left out: no row counts new retailers."""
    dollars, orders = small_dollars(t), small_orders(t)
    on_faire = FAIRE_SPLIT["marketplace"] + FAIRE_SPLIT["direct_program"]
    live = 1 - FAIRE_TERMS_FROM / 365.0 if t == 0 else 1.0
    commission = dollars * FAIRE_SPLIT["marketplace"] * FAIRE_COMMISSION
    processing = live * (dollars * on_faire * FAIRE_PROCESSING[0] + orders * on_faire * FAIRE_PROCESSING[1])
    return (commission + processing) / 1e6


def organic_certificate(t):
    """A11.09 at Oregon Tilth's Retail class - the in-house share puts co-packed organic sales under half -
    on the stand-in sales tier, one facility at Tilth's $300 facility fee, the annual inspection at the research's
    billable hours and Tilth's rate (travel time and expenses unregistered), less OCCSP where it lands inside the
    window, $M. OCCSP's $750 cap binds above a $1,000 base, so the facility fee does not change the reimbursement."""
    sales = GROSS[t] * ORGANIC_SHARE
    tier = next(x for x in TILTH_TIERS if sales <= x[0])
    fee = tier[1] if IN_HOUSE_SKUS > 0.5 else tier[2]
    occsp = min(OCCSP[0] * fee, OCCSP[1]) if t < OCCSP[2] else 0.0
    inspection = INSPECTION[0] * INSPECTION[1]
    facility = FACILITY_FEE
    return dict(sales=sales, fee=fee, inspection=inspection, facility=facility, occsp=occsp,
                net=(fee + facility + inspection - occsp) / 1e6)


def oregon():
    """A11.10 derived: 2024 units into Oregon, the tonnage test, and the fee CAA invoices in 2025.

    Walmart's authorized doors spread as its Supercenters do (Walmart national, A7.22); Kroger's and
    Whole Foods' authorized regions do not reach Oregon (A7.22); DTC jars and small-account units at
    Oregon's population share; UNFI and KeHE at population share, since the slotted DCs are not named.
    DPI'S LINE ENDS AFTER y1 (owner, 2026-09-15, item 5), so 2024 - the reported year - carries none of it: KeHE
    closed on DPI on 2023-06-20 and the volume moves into KeHE's line, where it is already at population share.
    KeHE's own locations page carries Portland and Tualatin, and Tualatin was DPI's, so the transition raises the
    brand's Oregon exposure at KeHE rather than removing it; no source read still names the DC that serves an
    Oregon retailer, so the share stays the reading it was. AMAZON IS A SEPARATE LINE HERE, not part of DTC: item 12
    split A8.01's 10% into own-site and marketplace, and a marketplace unit shipped to an Oregon consumer is placed
    into Oregon by the brand exactly as an own-site one is - the brand is the producer under ORS 459A.866 either way.
    Leaving it inside DTC would have silently dropped it when the split landed. The weight is the ruling's 1.08 lb and, beside it, that
    less a unit's 12 oz of contents - the packaging a fee reads, WHICH IS THE ONE A9.02 NOW READS (item 3)."""
    u = units_by_account(1)
    share = OREGON_POP
    into = dict(Walmart=u["Walmart"] * WALMART_OREGON[0] / float(WALMART_OREGON[1]),
                DTC=dtc_jars(1) * share, Amazon=amazon_units(1) * share, small=u["small"] * share,
                distributors=(u["UNFI"] + u["KeHE"]) * share, DPI=u["DPI"] * share)
    units_in = sum(into.values())
    out = dict(into=into, units=units_in)
    for label, lb in (("ruled", UNIT_LB), ("packaging", UNIT_LB - NET_CONTENTS_LB)):
        pounds = units_in * lb
        out[label] = dict(lb=lb, pounds=pounds, tons=pounds / METRIC_TON_LB, fee=pounds * GLASS_RATE / 1e6,
                          obligated=pounds / METRIC_TON_LB >= 1.0,
                          tons_without_distributors=(units_in - into["distributors"] - into["DPI"]) * lb / METRIC_TON_LB)
    return out


def group11_costs(cogs):
    """The five lines A9.02 reads from group 11, $M by window year.

    Oregon's first invoice, on 2024 supply, lands in 2025 ON THE PACKAGING WEIGHT (owner, 2026-09-15, item 3):
    both of A2.08's weights stand, each in its place - the packaging, 0.33 lb, is what an EPR fee reads, and
    the filled unit, 1.08 lb, is what FBA's weight bands read. They are different quantities, so there is no
    conflict.

    FOUR LINES, NOT FIVE. Amazon's referral fee and Professional plan MOVED OUT on 2026-09-18, into A9.01's
    opex ladder as `marketplace_fees()` (owner). They are a cost of selling the channel, beside the own site's
    3PL, and they are not double counted: this block no longer carries them."""
    ore = oregon()
    rows = []
    for t in range(3):
        write_off = WRITE_OFF[t] * cogs[t] * DIO[t] / 365
        rows.append(dict(write_off=write_off, faire=faire_fees(t), organic=organic_certificate(t)["net"],
                         oregon=ore["packaging"]["fee"] if t == 2 else 0.0))
        rows[-1]["total"] = sum(rows[-1].values())
    return rows


def loaded(role):
    """A9.05's loaded cost per FTE: the OES or practitioner wage over the ECEC wage share."""
    return WAGE[role] / WAGE_SHARE


def _wage_level(t):
    """A9.05's 3.5%/yr, compounding from y1. y1 carries the quoted loaded rates UN-INFLATED, which
    A9.01's own warehouse check establishes: 5 x 56,899.00 = 284,495 = the 0.284 it registers."""
    return (1 + WAGE_INFLATION) ** t


def payroll():
    """A9.01 line 1: A9.04's non-production heads at A9.05's loaded costs, $M by window year."""
    base = [sum(loaded(r) * n for r, n in ROSTER[k]) for k in ("y12", "y12", "y3")]
    return [base[t] * _wage_level(t) / 1e6 for t in range(3)]


def warehouse_payroll():
    """The warehouse slice of payroll, which the Establish check reads rather than charges twice."""
    return [WAREHOUSE_HEADS[t] * loaded("warehouse") * _wage_level(t) / 1e6 for t in range(3)]


def broker():
    """A9.01 line 2: A9.09's commission on broker-managed wholesale dollars, plus both retainers."""
    return [GROSS[t] * (1 - S_DTC) * BROKER_SHARE[t] * BROKER_RATE + BROKER_RETAINER / 1e6
            for t in range(3)]


def dtc_orders(t, dollars):
    """A8.02's order counts: consumer dollars split by order type, each at its own realized AOV."""
    return dict(one_time=dollars * (1 - SS_SHARE[t]) / AOV["one_time"],
                subscription=dollars * SS_SHARE[t] / AOV["subscription"])


CARRIER_CLAIMS = (0.75, 0.026, 35.0)      # A8.15: the unfiled share of eligible incidents, the eligible rate
                                          # (damage 2.2% + loss 0.4% of parcels) and the average recovery, $
TICKETS = (0.08, 6.0)                     # A8.18: tickets per order, and the cost of one, $


def unfiled_claims(t):
    """A8.15's unfiled carrier-claim dollars in window year t, $, on A8.02's OWN-SITE orders.

    OWN-SITE, NOT THE WHOLE 10% (owner, 2026-09-29): Amazon's orders ship through FBA on Amazon's carrier
    contracts (A11.01), so a claim on one is Amazon's, not the brand's -- the carve-out `threepl()` and
    `amazon_parcel_in_freight()` already make. WATCHED, NOT PRINTED BY HAND (the watched-or-priced rule): the row
    printed these as "$60734.375K", dollars with a thousands suffix, because nothing computed them."""
    orders = sum(dtc_orders(t, own_site_dollars(t)).values())
    unfiled, rate, recovery = CARRIER_CLAIMS
    return unfiled * rate * orders * recovery


def service_tickets(t):
    """A8.18's customer-service tickets in window year t and what they cost, $, on the same own-site orders as
    A8.15: Amazon takes its own orders' customer service (owner, 2026-09-29)."""
    tickets = TICKETS[0] * sum(dtc_orders(t, own_site_dollars(t)).values())
    return tickets, tickets * TICKETS[1]


def marketing():
    """A9.01 line 3: A8.10's paid acquisition plus the brand line, $M.

    THE BASE IS A8.01'S OWN-SITE REMAINDER (owner, 2026-10-01). A11.30 registers what Amazon's own advertising
    costs, so A8.10's $52 blended CAC charged on Amazon's customers as well counted Amazon's acquisition twice;
    the paid programme now buys own-site customers and A11.30 buys Amazon's. The loss narrows because a cost was
    counted twice, not because anything improved. Until 2026-10-01 the base was the whole 10%, marketplace
    included (owner, 2026-09-18: "a $52 blended CAC buys a customer for the brand, not for a storefront"), with
    A11.30 on top. The brand line stays on gross.
    """
    out = []
    for t in range(3):
        one = dtc_orders(t, own_site_dollars(t))["one_time"]
        paid = one * FIRST_ORDER_SHARE[t] * PAID_SHARE * CAC
        out.append(paid / 1e6 + GROSS[t] * BRAND_MARKETING_PCT)
    return out


def threepl():
    """A9.01 line 6: A8.13's pick, per-unit and packaging rates on OWN-SITE orders only, $M.

    OWN-SITE, NOT THE WHOLE 10% (owner, 2026-09-18, on A8.01's "group 8's own-site rows apply to the
    remainder"). A11.01 decides Amazon is 3P Seller Central WITH FBA, so Amazon fulfils its own orders
    and the brand's 3PL never touches them. The registered 0.582 / 0.739 / 0.864 was computed on the
    whole 10%, before item 12 gave Amazon its place, and reproduced on no construction of A8.13's
    rates: pick-and-pack alone gives 0.580 / 0.738 / 0.863 and adding A8.13's storage gives
    0.589 / 0.746 / 0.871, with the registered figure between the two and equal to neither.

    A8.13'S STORAGE IS NOT CHARGED HERE. Its $18 per pallet-month on ~40 pallets is outside storage,
    which A9.01's warehousing line already carries by name at 0.2% of gross - seven to eleven times
    its size. Charging it here would repeat the double count A9.01's own history records twice.
    """
    out = []
    for t in range(3):
        o = dtc_orders(t, own_site_dollars(t))
        rate = dict((k, PICK + JARS_PER_ORDER[k] * PER_UNIT + PACK_MATERIAL) for k in o)
        out.append(sum(o[k] * rate[k] for k in o) / 1e6)
    return out


def dtc_contribution():
    """A8.11's own-site contribution before marketing, by the row's own construction (owner, 2026-10-01: derive
    it exact): the product margin, 1 - DTC_COGS, less A8.12's net shipping at the $22 case rate, A8.13's 3PL and
    packaging share of own-site revenue, and payment. CURRENT by window year; ACHIEVABLE in y3, at A8.12's 16% and
    A8.13's 14% with the margin unmoved. A9.02's achievable reads the y3 step between the two.

    Until U4 these were typed as (0.19, 0.34), the row's practitioner figures, which reproduced only on the margin
    rounded to 68%; on the exact margin the construction gives 19.6% and 35.3%."""
    current = [1 - DTC_COGS[t] - SHIPPING_NET[t] - threepl()[t] * 1e6 / own_site_dollars(t) - PAYMENT
               for t in range(3)]
    achievable = 1 - DTC_COGS[2] - SHIPPING_ACHIEVABLE - THREEPL_ACHIEVABLE - PAYMENT
    return dict(current=current, achievable=achievable)


def fba_pack_fee(jars):
    """A11.31's 2025 non-peak fee for a pack of `jars`, and the band it lands in.

    Only the three bands the owner transcribed are encoded, and each pack asserts into the band it
    was quoted against, so a changed pack weight fails here rather than silently taking a rate that
    was never read. The rest of the card is NOT registered.

    EXACT, NO TOLERANCE (2026-09-23). The weight is the rational it was written as - 3.55 lb is 71/20,
    not the double below it - and the step count is an integer ceil of it. The rule was
    `ceil(over / 0.25 - 1e-9)`, the tolerance class FAILURES 2026-09-22 retires: an epsilon in a rounding
    rule is a free parameter, and a pack exactly on a 4 oz boundary is the case it decides.
    """
    lb = Fraction(str(PACK_LB[jars]))
    if 1 <= lb <= Fraction("1.25"):
        band = "1-1.25lb_under10" if AMAZON_PRICE < FBA_LOW_PRICE else "1-1.25lb_10to50"
        return FBA_2025[band], band
    if Fraction("2.25") <= lb <= Fraction("2.5"):
        return FBA_2025["2.25-2.5lb"], "2.25-2.5lb"
    if 3 <= lb <= 20:
        steps = math.ceil((lb - 3) * 4)                # $0.08 per 4 oz, part increments round up
        return FBA_2025["3-20lb_base"] + steps * FBA_2025["3-20lb_per_4oz_over_3lb"], "3-20lb"
    raise ValueError("pack of %d jars at %.2f lb falls in no transcribed band" % (jars, lb))


def fba_peak_per_jar():
    """A11.31's peak fee a jar, and the uplift over non-peak. $3.153 a jar, +$0.209.

    TIER B, AND ONE STEP REMOVED FROM THE CARD. The 2026 peak column gives the uplift; Amazon's own
    sentence on the same page carries it back - a peak card "will have the same per unit increase over
    non-peak rates as last year". So the 2025 peak is the 2025 non-peak plus those uplifts, which is a
    consequence of a dated statement rather than a rate anybody read. The 2025 peak card is still owed.
    """
    out = {}
    for n in PACK_MIX:
        base, band = fba_pack_fee(n)
        out[n] = base + FBA_PEAK_UPLIFT[band if band != "3-20lb" else "3-20lb_base"]
    peak = sum(PACK_MIX[n] * out[n] / n for n in PACK_MIX)
    return peak, out, peak - fba_per_jar()[0]


def fba_peak_cost(t):
    """The peak uplift on the units that ship inside the window, $M.

    THE SEASONAL SHARE IS A READING: no registered row gives Amazon's units by month, so the peak
    window's 92 days are taken at their share of the year. A1.09 sizes the channel and A9.12's Q4
    build is an inventory figure, not a sales one, so neither supplies a seasonality. If Amazon's
    units are Q4-weighted - and a gift-season grocery item plausibly is - this understates the
    charge, and the row says so rather than reaching for a curve nothing registers.
    """
    return amazon_units(t) * fba_peak_per_jar()[2] * (FBA_PEAK_DAYS / 365.0) / 1e6


def fba_per_jar():
    """A11.31's fulfilment fee per JAR, weighted by A11.03's owner-signed pack mix.

    THE MIX IS OVER JARS, NOT ORDERS: 20 / 30 / 50 of the units move as singles, 2-packs and 3-packs,
    so a pack's fee is divided by its jars before weighting. Single $4.22; 2-pack $6.05 = $3.03 a jar;
    3-pack $7.16 = $2.39 a jar; weighted $2.94.

    THE MIX RESTS ON A RULING THAT RETIRES A11.03's OWN WORDING (owner, 2026-09-18). A11.03 registered
    the packs as VIRTUAL BUNDLES, and an Amazon virtual bundle ships its components separately: every
    jar would take the single's $4.22 and the single's 8% referral, so the fee would be $4.22 a jar
    flat and the referral would stay at its floor. These are single-ASIN multipacks with their own
    FNSKU, which is what A11.22 has always assumed when it says a two-pack crosses $15 and pays 15%
    on its whole price - the two rows had contradicted each other since 2026-09-12 and the ruling
    resolves it in A11.22's favour. The alternative is priced in `bundle_alternative()` and printed
    beside this, never folded into it.
    """
    per_pack = dict((n, fba_pack_fee(n)[0]) for n in PACK_MIX)
    return sum(PACK_MIX[n] * per_pack[n] / n for n in PACK_MIX), per_pack


def referral_blend():
    """A11.22's referral rate blended over A11.03's mix, by DOLLARS.

    Every jar carries A3.18's $8.99, so a jar's share of dollars is its share of units and the blend
    is the mix-weighted rate: 0.20 x 8% + 0.80 x 15% = 13.6%. THIS RETIRES A11.22's 8% FLOOR, which
    was read only because the mix was unregistered; the band it published beside the floor retires
    with it, because a blend over a signed mix is a figure and not a range.
    """
    return sum(PACK_MIX[n] * REFERRAL_BY_PACK[n] for n in PACK_MIX)


def bundle_alternative(t):
    """What the marketplace line would cost if A11.03's virtual-bundle wording stood, $M.

    Printed beside the signed figure, never applied to it (the A1.07 Do-not). Each jar is picked and
    charged alone: the single's $4.22 and the single's 8% referral.
    """
    units = amazon_units(t)
    return dict(fulfilment=units * FBA_2025["1-1.25lb_under10"] / 1e6,
                referral=amazon_dollars(t) * REFERRAL_BY_PACK[1] / 1e6)


def amazon_parcel_in_freight(t):
    """The DTC parcel A5.24's freight line carries on Amazon's dollars, $M - carved out because FBA
    fulfilment INCLUDES delivery (owner, 2026-09-18). Without this the channel pays for delivery
    twice: once inside the 5.5% of gross, once inside A11.31's fee.

    A READING, and the alternative is an order of magnitude apart: A8.12's net shipping rate is
    measured on own-site order sizes and is net of what customers pay at A3.18's threshold, and an
    Amazon order pays the brand no shipping at all. Carving at A5.24's flat 5.5% of the Amazon
    dollars instead would remove 0.0536 / 0.0782 / 0.103 $M rather than this. A8.12's rate is used
    because the quantity being removed is a PARCEL cost, not an average of parcel and truckload:
    decomposing the freight line at A8.12's rate leaves wholesale freight at about 3.3% of wholesale
    dollars, which is the shape a truckload programme has.
    """
    return amazon_dollars(t) * SHIPPING_NET[t] / 1e6


def marketplace_fees(t):
    """A9.01's Amazon line -- A11.22's referral and plan, A11.31's FBA fees, A11.30's advertising -- on A11.01's share
    of A8.01's 10%, $M.

    MOVED HERE FROM A9.02's group-11 cost block on 2026-09-18 (owner). The referral fee and the
    Professional plan are the marketplace's cost of selling, which is what `threepl()` is for the own
    site; carrying one in opex and the other beside it made the two channels' fulfilment costs
    incomparable. It is a MOVE, not an addition - `group11_costs()` no longer carries the line.

    FBA FULFILMENT IS READ FROM 2026-09-18 (A11.31), closing what was the package's largest known
    omission on the cost side. The 2025 non-peak card gives the per-band fee and A11.03's owner-signed
    pack mix decides which band a unit takes, so the two gaps that blocked it - no rate card read, no
    registered mix - close together. The referral fee blends over the same mix at 13.6% and A11.22's
    8% floor retires with it.

    STILL OWED, and named rather than absorbed: the 2023 and 2024 rates, which are Amazon's earlier
    dated change pages and are back-dated from 2025 at Tier B until they are fetched; the 2025 peak card,
    which fba_peak_per_jar derives from the 2026 column at Tier B; and Amazon's units by month, for which
    fba_peak_cost takes the peak window's days at their share of the year, a reading. Storage, inbound
    placement and returnless refunds are read, at Tier B.
    """
    dollars, units = amazon_dollars(t), amazon_units(t)
    per_jar, per_pack = fba_per_jar()
    out = dict(referral=dollars * referral_blend() / 1e6,
               plan=AMAZON_PLAN / 1e6,
               fulfilment=units * per_jar / 1e6 + fba_peak_cost(t),
               peak=fba_peak_cost(t),
               storage=units * FBA_STORAGE_UNIT / 1e6,
               inbound=units * FBA_INBOUND_UNIT / 1e6,
               returnless=dollars * RETURNLESS_SHARE / 1e6,
               advertising=dollars * ACOS / 1e6,
               per_jar=per_jar, per_pack=per_pack, rate=referral_blend(),
               alternative=bundle_alternative(t))
    out["total"] = sum(out[k] for k in ("referral", "plan", "fulfilment", "storage", "inbound",
                                        "returnless", "advertising"))
    return out


def opex():
    """A9.01, line by line, $M by window year. Every line is a registered row times a registered base.

    The ladder is an OUTPUT. It was an input until 2026-09-18, and the three things that hid behind
    the literal are in DECISIONS#A9.01-derived: a payroll y3 that rounds to 2.896 and not the
    registered 2.895 (the seven registered lines sum to 9.762 against a registered total of 9.763,
    so the restatement closes the gap rather than opening one); a broker share that never followed
    A5.38's DPI move; and marketing and 3PL still standing on the pre-item-12 DTC base.
    """
    lines = [("payroll", payroll()), ("broker", broker()), ("marketing", marketing()),
             ("freight", [GROSS[t] * FREIGHT_PCT - amazon_parcel_in_freight(t) for t in range(3)]),
             ("warehousing", [GROSS[t] * SUPPLIES_PCT for t in range(3)]),
             ("dtc_3pl", threepl()),
             ("marketplace", [marketplace_fees(t)["total"] for t in range(3)]),
             ("g_and_a", [GROSS[t] * GA_PCT for t in range(3)])]
    total = [sum(v[t] for _, v in lines) for t in range(3)]
    return dict(lines=lines, total=total,
                pct=[total[t] / GROSS[t] * 100 for t in range(3)],
                ga=dict((k, [GROSS[t] * s for t in range(3)]) for k, s in GA_SPLIT))


def establish_check(net):
    """A9.01's plausibility on the warehouse: payroll + warehouse rent + supplies over NET revenue.

    A CHECK AND NOT A LINE. Charging Establish's 2.13% beside the lines it benchmarks is how the
    warehouse came to be counted three times in the first draft (A9.01's own history).

    THE DENOMINATOR IS A9.02's NET REVENUE. A9.01 registers 2.06 / 1.89 / 1.98%, which divides by
    gross less trade and operational deductions ONLY - it omits A4.15's trade over-settlement, which
    A9.02 books. The package has one net revenue and this is it, so the shares are 2.10 / 1.93 / 2.02%
    and the headroom under Establish's 2.13 is 0.03 / 0.20 / 0.11 points, not 0.07 / 0.24 / 0.15.
    Born inconsistent rather than drifted: the Establish figures and OVERSETTLE entered in one commit.
    The verdict - satisfied in every year - survives; the published margin does not.
    """
    O = opex()
    rent = dict(GA_SPLIT)["rent"]
    num = [warehouse_payroll()[t] + GA_RENT_WAREHOUSE * GROSS[t] * rent + GROSS[t] * SUPPLIES_PCT
           for t in range(3)]
    return dict(num=num, pct=[num[t] / net[t] * 100 for t in range(3)],
                benchmark=2.13, ga_rent=[GROSS[t] * rent for t in range(3)], opex_total=O["total"])


def _cost_index():
    """Unit cost level by year relative to the 2025 base (A9.16), before tariff."""
    lvl = [1.0]
    for g in COGS_INDEX_YOY:
        lvl.append(lvl[-1] * (1 + g))
    return [lvl[i + 1] / lvl[3] for i in range(3)]


# ------------------------------------------------------------ A4.16 / A4.17 / A4.29, slotting and free-fill (U18 Q5)
SLOT_KROGER_DIVISION = 10000.0            # A4.16: $ per new SKU per Kroger division, the band midpoint, 2025 dollars
                                          # held flat across the window (owner-signed 2026-10-14)
SLOT_REGIONAL = 3500.0                    # A4.16: $ per new SKU at Regional, the band midpoint
SLOT_SETTLE = (0.50, 0.30, 0.20)          # A4.29: deducted from first invoices / invoiced / in kind, Kroger and Regional
FREE_FILL_CASES = 1                       # A4.17: one case per store per new SKU at the free-fill accounts
KROGER_DIVISIONS = 6                      # A7.06: Kroger's authorized divisions, each slotting a new SKU (A4.16)


def slotting(t, unit_cost):
    """A4.16 / A4.17 / A4.29's slotting and free-fill in window year t, $M (owner, 2026-10-14, DECISIONS#u18-rulings
    Q5: the Amazon-fees pattern - a cost the data carries and the P&L never charges is a wrong EBITDA).

    New SKUs: every launch is authorized at the three launch accounts (A7.09's launches a year, group 11); Regional
    grows by range extension, A7.26's authorizations differenced; Sprouts enters in y2 with its whole set (A7.26 at
    A7.04's first Sprouts doors); the distributors carry every launch at their served doors. Kroger slots a new SKU in
    each of A7.06's divisions; Walmart charges none and Costco none. A4.29 settles Kroger's and Regional's dollars -
    the deducted share a `slotting` deduction row outside A4.05's ten (so outside A4.01's and A4.14's rates), the
    invoiced share an expense, the in-kind share product at cost. A4.17's free-fill, at wholesale, is the natural
    accounts' and distributors' whole slotting cost, so no case is counted twice."""
    import group10_floors as F           # F imports this module at load; imported here so load order holds
    launches = F.LAUNCHES_PER_YEAR
    auth = F.AUTH_ALL
    kroger = launches * SLOT_KROGER_DIVISION * KROGER_DIVISIONS
    regional = SLOT_REGIONAL * (max(0, auth["Regional"][t] - auth["Regional"][t - 1]) if t else 0)
    cash = kroger + regional
    deducted, invoiced = cash * SLOT_SETTLE[0], cash * SLOT_SETTLE[1]
    in_kind = SLOT_SETTLE[2] * (kroger * unit_cost / PRICE["Kroger"] + regional * unit_cost / PRICE["Regional"])
    case = F.CASE_UNITS
    wf = launches * F.RETAIL_DOORS["WF"][t] * FREE_FILL_CASES * case * PRICE["WF"]
    sprouts_new = auth["Sprouts"][t] if t and not F.RETAIL_DOORS["Sprouts"][t - 1] else 0
    sprouts = sprouts_new * F.RETAIL_DOORS["Sprouts"][t] * FREE_FILL_CASES * case * PRICE["Sprouts"]
    dist = [k for k in ("UNFI", "KeHE", "DPI") if SHARE[k][t]]
    dist_price = sum(SHARE[k][t] * PRICE[k] for k in dist) / sum(SHARE[k][t] for k in dist)
    # the doors that take a new SKU, not every door the distributors serve (owner, 2026-10-14): A7.26's per-door
    # authorization at the independents over the catalogue, times A7.04's doors - the average SKU's doors
    taking = F.AUTH_ALL["independents"][t] * F.A704_DOORS["independents"][t] / float(F.SKUS)
    distributors = launches * taking * FREE_FILL_CASES * case * dist_price
    free_fill = wf + sprouts + distributors
    out = dict(kroger=kroger, regional=regional, deducted=deducted, invoiced=invoiced, in_kind=in_kind,
               wf=wf, sprouts=sprouts, distributors=distributors, free_fill=free_fill)
    out = dict((k, v / 1e6) for k, v in out.items())
    out["total"] = out["deducted"] + out["invoiced"] + out["in_kind"] + out["free_fill"]
    return out


def pnl(ask=None, giveback=GIVEBACK, oversettle=OVERSETTLE, opded=None):
    ask = ASK if ask is None else ask
    opded = OPDED if opded is None else opded      # A4.01's line; achievable() runs it at A6.15's pool
    f = _price_index(ask, giveback)
    idx = _cost_index()
    prev = [GROSS_PRE] + GROSS[:2]
    over = [oversettle * TRADE * (GROSS[t] * (1 - SETTLE_LAG / 365) + prev[t] * SETTLE_LAG / 365)
            for t in range(3)]
    op = opex()["total"]
    cogs, ratio, eb, net, slot = [], [], [], [], []
    for t in range(3):
        c12 = COST_12 * idx[t] * (1 + TARIFF[t])
        c18 = COST_18 * idx[t] * (1 + TARIFF[t])
        w = sum(SHARE[k][t] / 100.0 * c12 / (PRICE[k] * f[k][t]) for k in PRICE)
        w += SHARE["Costco"][t] / 100.0 * (2 * c18) / (PRICE_CLUB * f["Costco"][t])
        S = slotting(t, c12)              # A4.29: deduction and free-fill off net, in-kind into COGS, invoiced an expense
        cg = GROSS[t] * (1 - S_DTC) * w + GROSS[t] * S_DTC * DTC_COGS[t] * idx[t] * (1 + TARIFF[t]) + S["in_kind"]
        nr = GROSS[t] * (1 - TRADE - opded[t]) - over[t] - S["deducted"] - S["free_fill"]
        cogs.append(cg); ratio.append(w * 100); net.append(nr); slot.append(S)
        eb.append(nr - cg - op[t] - S["invoiced"])
    g11 = group11_costs(cogs)
    eb = [eb[t] - g11[t]["total"] for t in range(3)]
    return dict(over=over, net=net, cogs=cogs, ratio=ratio, ebitda=eb, index=idx, group11=g11,
                opex=op, slotting=slot)


def achievable(tier="full"):
    """A9.02's ACHIEVABLE, y3: the P&L run at three registered achievable endpoints, $M. Derived 2026-09-23 on the
    owner's ruling: "derive it or retire it" (DECISIONS#restating-the-21).

    DEDUCTIONS on the line pnl() charges, which is A4.01 alone. A6.15's well-run pool is on the bucket
    pool A4.01 + A4.31; A4.31's invalid trade claims are all bucket 1 and sit in trade (DECISIONS#A9.14,
    dilution counts A4.31 once), not in A4.01's line, so their bucket-1 residual comes off A6.15's pool
    before it replaces OPDED. Subtracting the whole pool from 6.0 charges the line a residual it never
    carried; subtracting it from 6.54 credits the line with dollars it never charged.

    SETTLEMENT at A4.15's achievable. DTC at A8.11's: a change in own-site contribution, entered as a line,
    because the P&L spreads DTC's cost over COGS, freight and 3PL and A8.11's achievable does not say which moves.
    A8.01's share is held at 10%, not its 15% achievable. No broker clawback: A9.09 registers none.

    The terms enter three separate lines and none reads another, so the marginals add to the joint result.
    `tier` is A6.15's, and both are printed: the decision says the two tiers are not collapsed.
    """
    import group10_floors as F           # F imports this module at load; imported here so load order holds
    y = 2
    W = F.well_run_pool()
    a431 = F.INVALID_TRADE * 100.0 * (1 - F.F_ACHIEVABLE * F.R1_ACHIEVABLE)
    pool = W["total"][tier] - a431
    current = pnl()["ebitda"][y]
    ded = pnl(opded=OPDED[:y] + [pool / 100.0])["ebitda"][y]
    both = pnl(opded=OPDED[:y] + [pool / 100.0], oversettle=OVERSETTLE_ACHIEVABLE)["ebitda"][y]
    contribution = dtc_contribution()
    dtc = own_site_dollars(y) * (contribution["achievable"] - contribution["current"][y]) / 1e6
    terms = [("deductions", ded - current), ("settlement", both - ded), ("dtc", dtc)]
    total = both + dtc
    # OWED, where A4.31's dollars sit in trade: in A4.15's excess, settlement at accrual clears the residual A6.15
    # keeps, so the line runs at the whole pool; A6.15's recovery on A4.31 is what a line in A4.14's accrual omits
    excess = pnl(opded=OPDED[:y] + [W["total"][tier] / 100.0], oversettle=OVERSETTLE_ACHIEVABLE)["ebitda"][y] + dtc
    return dict(tier=tier, pool=pool, a431_residual=a431, current=current, terms=terms, ebitda=total,
                pct=total / GROSS[y] * 100, terms_pct=[(k, v / GROSS[y] * 100) for k, v in terms],
                pct_if_excess=excess / GROSS[y] * 100, a431_recovery=F.INVALID_TRADE * 100.0 - a431)


def dso():
    """A9.11 identity: wholesale days blended with DTC, plus the open residual in days."""
    whole = [sum(SHARE[k][t] / 100.0 * DAYS_TO_PAY[k] for k in DAYS_TO_PAY) for t in range(3)]
    resid_days = [RESIDUALS[t] / GROSS[t] * 365 for t in range(3)]
    blended = [(1 - S_DTC) * whole[t] + S_DTC * DAYS_DTC + resid_days[t] for t in range(3)]
    return whole, resid_days, blended


def working_capital(cogs):
    import group10_floors as F           # F imports this module at load; imported here so load order holds
    # A4.08's current recovery per bucket-pool dollar, exact: the series group10_floors.recovery() publishes. It was
    # typed here as RECOVERY = [0.053, 0.043, 0.039] and was left behind when A4.08 moved on 2026-09-21 (U4)
    recovery = F.filing_cascade()["current"]
    _, _, d = dso()
    ar = [GROSS[t] * d[t] / 365 for t in range(3)]
    inv = [cogs[t] * DIO[t] / 365 for t in range(3)]
    ap = [cogs[t] * DPO / 365 for t in range(3)]
    fg_share = [(DIO[t] - DAYS_RAW_PACK) / DIO[t] for t in range(3)]
    fg = [fg_share[t] * inv[t] for t in range(3)]
    build = [BUILD_PCT * fg[t] for t in range(3)]
    accrual = [(BILLBACK_MCB + OPDED[t]) * GROSS[t] * (d[t] - RESIDUALS[t] / GROSS[t] * 365) / 365
               for t in range(3)]
    resid_net = [RESIDUALS[t] * (1 - recovery[t]) for t in range(3)]
    nwc = [ar[t] + inv[t] - ap[t] - accrual[t] - resid_net[t] for t in range(3)]
    c0 = cogs[0] * GROSS_PRE / GROSS[0]
    # The pre-window balance reads the terms in force at its date: Faire's free 30-day payout (A3.20), and only on
    # the half of the tier that is on Faire at all. The split the owner signed 2026-09-15 (item 7) puts 40% on the
    # marketplace and 10% on Faire Direct; the direct 50% was never on Faire's payout clock. WHAT THE DIRECT HALF
    # PAYS ON IS NOW OWED: A9.11 reads the tier's 60 days off Faire's payout, which the split makes a blend struck
    # from one of its two parts.
    on_faire = FAIRE_SPLIT["marketplace"] + FAIRE_SPLIT["direct_program"]
    d_pre = d[0] - (1 - S_DTC) * SHARE["small"][0] / 100.0 * on_faire * (DAYS_TO_PAY["small"] - FAIRE_DAYS_BEFORE)
    nwc_pre = (GROSS_PRE * d_pre / 365 + c0 * DIO[0] / 365 - c0 * DPO / 365
               - (BILLBACK_MCB + OPDED[0]) * GROSS_PRE * (d_pre - RESIDUALS[0] / GROSS[0] * 365) / 365
               - RESIDUALS[0] * (1 - recovery[0]))
    return dict(ar=ar, inv=inv, ap=ap, fg_share=fg_share, fg=fg, build=build,
                accrual=accrual, resid_net=resid_net, nwc=nwc, nwc_pre=nwc_pre, dso=d)


def borrowing_base(wc):
    dil = [BILLBACK_MCB + OPDED[t] for t in range(3)]
    adv = [0.85 - (dil[t] - 0.05) for t in range(3)]
    dtc_ar = [S_DTC * GROSS[t] * DAYS_DTC / 365 for t in range(3)]
    elig = [(wc["ar"][t] - RESIDUALS[t] - dtc_ar[t]) * (1 - INELIGIBLE_90D) for t in range(3)]
    fg_peak = [(1 + BUILD_PCT) * wc["fg"][t] for t in range(3)]
    inv_leg = [min(0.5 * fg_peak[t], INV_SUBLIMIT) for t in range(3)]
    return dict(dilution=dil, advance=adv, eligible=elig, inv_leg=inv_leg,
                base=[adv[t] * elig[t] + inv_leg[t] for t in range(3)])


def consequences(sprung):
    """A9.14's breach terms, priced against the spring set the ledger itself produces.

    y1's spring is cured by the Q1 y2 amendment, so its fee lands in y2 and the stub
    between the November y1 peak and that cure carries no default rate here -- daily_ledger()
    dates and prices it (U16). A spring in y2 or y3 cannot be cured by a further upsize,
    because the base will not support one (A9.14), so it is forborne: the forbearance fee,
    and the default rate for that year.

    The default-rate figure is an UPPER BOUND on this annual ledger. The breach begins when
    availability crosses the trigger, which daily_ledger() dates.
    """
    amend = [0.0, AMENDMENT_FEE if sprung[0] else 0.0, 0.0]
    forb = [0.0, 0.0, 0.0]
    bump = [0.0, 0.0, 0.0]
    for t in (1, 2):
        if sprung[t]:
            forb[t] = FORBEARANCE_FEE
            bump[t] = DEFAULT_BUMP
    return amend, forb, bump


def ledger(eb, wc, base, d0=D0, capex=CAPEX, distrib=DISTRIB, call=None):
    """The cash ledger. `call` is A10.19's equity call, read from group 10 and None here (U8, owner, 2026-10-06):
    dict(size=$M, year=window year index, elapsed=share of that year elapsed when it lands). It pays the draw down
    from that date, so it lowers the year-end draw, the year's average balance for the rest of the year, and the
    November peak only when it lands before it. Without it the ledger is the line's own, and the gap it prints is
    the finding."""
    on_line = (DPO + sum(wc["dso"]) / 3) / 365.0      # build sits on the line DPO + DSO
    trigger = [max(SPRING_PCT * COMMITMENT[t], AVAIL_HARD) for t in range(3)]
    I = [0.15, 0.25, 0.32]
    sprung = [False, False, False]
    for _ in range(400):
        amend, forb, bump = consequences(sprung)
        draw, ends, newI, dist, cfo, before = d0, [], [], [], [], []
        for t in range(3):
            x = eb[t] - capex - I[t]
            dd = distrib * max(0.0, x)
            dist.append(dd); cfo.append(x - dd)
            growth = wc["nwc"][t] - (wc["nwc_pre"] if t == 0 else wc["nwc"][t - 1])
            c = call["size"] if call and t == call["year"] else 0.0
            pre = draw + growth - (x - dd)
            end = pre - c
            avg = (draw + pre) / 2 + wc["build"][t] * on_line - (c * (1 - call["elapsed"]) if c else 0.0)
            newI.append(avg * (PRIME_PLUS[t] + bump[t]) * ACTUAL_360
                        + max(COMMITMENT[t] - avg, 0) * UNUSED_FEE + amend[t] + forb[t])
            ends.append(end); before.append(pre); draw = end
        draw, peak = d0, []
        for t in range(3):
            early = call["size"] if call and t == call["year"] and call["elapsed"] < ELAPSED else 0.0
            peak.append(draw + ELAPSED * (before[t] - draw) + wc["build"][t] - early); draw = ends[t]
        avail = [min(COMMITMENT[t], base["base"][t]) - peak[t] for t in range(3)]
        newsprung = [avail[t] < trigger[t] for t in range(3)]
        if newsprung == sprung and max(abs(a - b) for a, b in zip(I, newI)) < 1e-12:
            break
        sprung = newsprung
        I = newI
    else:
        raise RuntimeError("ledger did not converge")
    fccr = [(eb[t] - capex - dist[t]) / I[t] for t in range(3)]
    avgbal = [(([d0] + ends)[t] + before[t]) / 2 + wc["build"][t] * on_line
              - (call["size"] * (1 - call["elapsed"]) if call and t == call["year"] else 0.0) for t in range(3)]
    return dict(cfo=cfo, ends=ends, interest=I, peak=peak, avail=avail, trigger=trigger,
                fccr=fccr, springs=[t + 1 for t in range(3) if sprung[t]],
                spring=next((t + 1 for t in range(3) if sprung[t]), None),
                amend=amend, forb=forb, bump=bump, on_line=on_line,
                bump_cost=[bump[t] * avgbal[t] * ACTUAL_360 for t in range(3)],
                stub=DEFAULT_BUMP * peak[0] * (75.0 / 365.0))


def handoff(base, L, cogs):
    """What group 10 inherits: what binds, and the DPO ladder that funds the shortfall.

    y1 is short against the COMMITMENT only - the base carries it - so the remedy is a
    bigger commitment and the gap until it lands is payment timing. From y2 the need
    passes the BASE as well, and no upsize is a remedy.
    """
    short = [-a for a in L["avail"]]
    return dict(short=short,
                binds=["commitment" if COMMITMENT[t] < base["base"][t] else "base" for t in range(3)],
                vs_base=[L["peak"][t] - base["base"][t] for t in range(3)],
                dpo_days=[short[t] / (cogs[t] / 365) for t in range(3)],
                dpo_to=[DPO + short[t] / (cogs[t] / 365) for t in range(3)],
                ap_run=[c / 24 for c in cogs])


# ------------------------------------------------------------ U16: the daily ledger (owner, 2026-10-21)
# The same transactions as ledger(), on a calendar. ledger() stays the source for the annual FLOWS (EBITDA, capex,
# distributions), and the daily sums reconcile to them at $1K. The daily ledger is the source for BALANCES: Dec 31 is
# a position, emergent from the transactions, and ledger()'s year-end figures are annual-mean readings printed beside
# it (owner, 2026-10-21: "a CFO reads year-end as a Dec 31 position, not an annual mean"). Interest, the peak and
# availability are the daily ledger's own readings (U18's fifth free input).
A719_INDEX = [0.983, 0.917, 0.995, 0.969, 1.027, 0.990, 1.022, 1.023, 0.981, 1.014, 1.020, 1.060]   # A7.19 monthly
AP_RUN_DAYS = (1, 16)                     # A9.11: the AP run, the 1st and 16th
TRIM_YEARS = (2022, 2023, 2024, 2025)     # mirror-exempt: the pre-window year (balances only), then y1-y3
FIRST_PAYDAY = date(2022, 1, 7)           # mirror-exempt: a calendar date, the payroll phase the owner signed
                                          # 2026-10-21 (DAILY_INPUTS), not a registry row's figure
PAY_PERIOD = 14                           # mirror-exempt: biweekly in days, U18's signed cadence (DAILY_INPUTS), not
                                          # a registry row's figure
UPSIZE_DAY = date(2024, 1, 1)             # U18 (owner, 2026-10-20): A9.14's upsize on the first day of y2
COPACK_SHARE = 0.30                       # A5.22: the co-packer share of volume, read as its share of purchases
HOLD_MISSES = 2                           # A10.07: the credit hold at 2 missed AP runs
LATE_FEE_MONTH = 0.015                    # A10.07: the late fee, a month, from 30 days past due
AP_TIMING = "nearest"                     # A9.11, owner-signed 2026-10-21: each invoice at the run nearest its 32nd day
DAILY_INPUTS = [
    ("payroll cadence", "biweekly, 26 runs a year", "owner-signed 2026-10-20 (U18)"),
    ("A9.14's upsize day", "the first day of y2", "owner-signed 2026-10-20 (U18)"),
    ("a part-held run's order", "oldest invoices paid first", "owner-signed 2026-10-20 (U18)"),
    ("release terms", "past-due paid; next order cash-in-advance, no deposit", "owner-signed 2026-10-20 (U18)"),
    ("flow reconciliation", "$1K on EBITDA, capex, distributions", "owner-signed 2026-10-20 (U18); flows only, 2026-10-21"),
    ("AP timing", "the run nearest each invoice's 32nd day", "owner-signed 2026-10-21: DERIVED from A9.11's DPO 32"),
    ("payroll phase", "first payday Friday 7 January 2022", "owner-signed 2026-10-21"),
    ("inventory ramp", "base linear to DIO; build up Aug-Sep, down Oct-Dec", "owner-signed 2026-10-21"),
    ("seasonal shapes", "wholesale and Amazon A7.19; own site A8.17", "owner-signed 2026-10-21"),
]


def _month_shape(index, y):
    """Each day's share of calendar year y on a twelve-month index: a month's weight spread over its days."""
    tot = float(sum(index))
    out, d = [], date(y, 1, 1)
    while d.year == y:
        out.append(index[d.month - 1] / tot / calendar.monthrange(y, d.month)[1])
        d += timedelta(1)
    return out


def _ap_run(d, timing=None):
    """The AP run that pays an invoice whose DPO day is d: the run nearest it (A9.11, owner-signed 2026-10-21; the
    earlier on a tie), or the run before or after it, the band's other two readings."""
    timing = AP_TIMING if timing is None else timing
    back = d
    while back.day not in AP_RUN_DAYS:
        back -= timedelta(1)
    fwd = d
    while fwd.day not in AP_RUN_DAYS:
        fwd += timedelta(1)
    if timing == "before":
        return back
    if timing == "after":
        return fwd
    return back if (d - back) <= (fwd - d) else fwd


def daily_ledger(call=None, d0=D0, capex=CAPEX, ap_timing=None):
    """Group 9's cash on a daily clock, 1 January y1 to 31 December y3, from the rows ledger() reads.

    `call` is (size $M, date) for A10.19's note; None is the line's own ledger, the uncapped stretch that dates the
    hold. The pre-window year runs on GROSS_PRE only to give 31 December y0 its balances; the draw is set to D0 there.
    Invoices collect at each account's days to pay (A9.11), Faire's on-platform half at 30 days before 2023-07-05
    (A3.20); deductions leave at remittance (A4.31 + A4.01); residuals stay open for A9.15's days of gross. Inventory
    holds A9.12's DIO, its base moving across the year to the year's level, with the +40% finished-goods build in
    August-September sold through Q4. Purchases invoice daily and are scheduled to the AP run nearest DPO 32; a run
    pays oldest first up to the line (U18). Payroll pays every 14 days. Interest accrues daily at the month's prime
    plus 1.5% (A9.14) and is paid at month end."""
    import group10_floors as F           # F imports this module at load; imported here so load order holds
    from group8_dtc import MONTH as A817  # group 8 imports this module; read lazily (U16)
    P = pnl()
    wc = working_capital(P["cogs"])
    rec = F.filing_cascade()["current"]
    pay = payroll()
    # A5.22's co-packed share split by A5.30; glass is not split from materials, because no row registers its share
    # of COGS, so materials carry net 30 (U16's scope names the simplification)
    suppliers = (("co-pack larger", COPACK_SHARE * F.COPACK_LARGER),
                 ("co-pack smaller", COPACK_SHARE * (1 - F.COPACK_LARGER)), ("materials", 1 - COPACK_SHARE))
    fee_at, priority_at, hold_at = F.SUPPLIER_DAYS
    supplier_lines = (priority_at, fee_at, hold_at)
    if any(DISTRIB * max(0.0, P["ebitda"][t] - capex) for t in range(3)):
        raise RuntimeError("a positive pre-tax year needs a distribution date, and no row registers one")
    c0 = P["cogs"][0] * GROSS_PRE / GROSS[0]
    on_faire = FAIRE_SPLIT["marketplace"] + FAIRE_SPLIT["direct_program"]
    faire_from = date(2023, 1, 1) + timedelta(FAIRE_TERMS_FROM)
    days, yi = [], []
    for y in TRIM_YEARS:
        d = date(y, 1, 1)
        while d.year == y:
            days.append(d); yi.append(y - 2023)
            d += timedelta(1)
    n = len(days)
    ws = sum((_month_shape(A719_INDEX, y) for y in TRIM_YEARS), [])
    os_ = sum((_month_shape([A817[m] for m in range(1, 13)], y) for y in TRIM_YEARS), [])
    t_of = lambda i: max(yi[i], 0)                                   # the pre-window year reads y1's rates
    gross_of = lambda i: GROSS_PRE if yi[i] < 0 else GROSS[yi[i]]
    # ---- invoices by collection lag, and the open-invoice balance each leaves
    open_inv, ded_open = [0.0] * n, [0.0] * n
    gross_day = [0.0] * n
    resid_bal = [0.0] * n
    for i in range(n):
        t, g = t_of(i), gross_of(i)
        w = g * (1 - S_DTC)
        own = g * S_DTC * (1 - AMAZON_SHARE[t]) * os_[i]
        amz = g * S_DTC * AMAZON_SHARE[t] * ws[i]
        parts = [(w * SHARE[k][t] / 100.0 * ws[i], DAYS_TO_PAY[k]) for k in SHARE if k != "small"]
        sm = w * SHARE["small"][t] / 100.0 * ws[i]
        faire_lag = FAIRE_DAYS_BEFORE if days[i] < faire_from else DAYS_TO_PAY["small"]
        parts += [(sm * on_faire, faire_lag), (sm * (1 - on_faire), DAYS_TO_PAY["small"]),
                  (own + amz, DAYS_DTC)]
        gross_day[i] = sum(a for a, _ in parts)
        ded = BILLBACK_MCB + OPDED[t]
        for a, lag in parts:
            for j in range(i, min(i + lag, n)):
                open_inv[j] += a
                ded_open[j] += a * ded
    for i in range(n):                                               # A9.15's residual, days of gross, fractional
        t = t_of(i)
        lag = RESIDUALS[t] / GROSS[t] * 365
        whole = int(lag)
        resid_bal[i] = sum(gross_day[j] for j in range(max(0, i - whole + 1), i + 1))
        if i - whole >= 0:
            resid_bal[i] += (lag - whole) * gross_day[i - whole]
    dtc_open = [0.0] * n
    for i in range(n):
        g, t = gross_of(i), t_of(i)
        a = g * S_DTC * ((1 - AMAZON_SHARE[t]) * os_[i] + AMAZON_SHARE[t] * ws[i])
        for j in range(i, min(i + DAYS_DTC, n)):
            dtc_open[j] += a
    shape = [gross_day[i] / gross_of(i) for i in range(n)]
    # ---- inventory, purchases, payroll accrual
    cogs_y = lambda y: c0 if y < 0 else P["cogs"][y]
    inv, fg = [0.0] * n, [0.0] * n
    for i in range(n):
        y, t, d = yi[i], t_of(i), days[i]
        start = cogs_y(y - 1) * DIO[max(y - 1, 0)] / 365 if y > -1 else c0 * DIO[0] / 365
        end = cogs_y(y) * DIO[t] / 365
        ny = 366 if calendar.isleap(d.year) else 365
        frac = (d - date(d.year, 1, 1)).days / float(ny - 1)
        base = start + frac * (end - start) if y > -1 else end
        fgs = (DIO[t] - DAYS_RAW_PACK) / float(DIO[t])
        b = BUILD_PCT * fgs * base
        if 8 <= d.month <= 9:
            build = b * ((d - date(d.year, 8, 1)).days + 1) / 61.0
        elif d.month >= 10:
            build = b * (1 - ((d - date(d.year, 10, 1)).days + 1) / 92.0)
        else:
            build = 0.0
        inv[i] = base + build
        fg[i] = fgs * base + build
    relief = [cogs_y(yi[i]) * shape[i] for i in range(n)]
    purchase = [relief[i] + inv[i] - (inv[i - 1] if i else inv[0]) for i in range(n)]
    payday = set()
    d = FIRST_PAYDAY
    while d <= days[-1]:
        payday.add(d); d += timedelta(PAY_PERIOD)
    pay_day_rate = [(pay[t_of(i)] / (366 if calendar.isleap(days[i].year) else 365)) for i in range(n)]
    accr = [0.0] * n
    for i in range(n):
        accr[i] = 0.0 if days[i] in payday else (accr[i - 1] if i else 0.0) + pay_day_rate[i]
    # ---- the EBITDA a day earns, and the cash it spends outside working capital
    S = P["slotting"]
    eb_day = [0.0] * n
    for i in range(n):
        y = yi[i]
        if y < 0:
            continue
        ny = 366 if calendar.isleap(days[i].year) else 365
        flat = (P["opex"][y] + S[y]["invoiced"] + P["group11"][y]["total"]) / ny
        eb_day[i] = (P["net"][y] - P["cogs"][y]) * shape[i] - flat
    # ---- the daily run, from 31 December y0
    i0 = days.index(date(2023, 1, 1))
    nwc_x = lambda i: (open_inv[i] + resid_bal[i] + inv[i] - ded_open[i]
                       - (1 - rec[t_of(i)]) * resid_bal[i] - accr[i])    # every balance but AP
    queue = []                                                       # [invoice day, run, supplier, amount, misses]
    for i in range(i0):
        run = _ap_run(days[i] + timedelta(DPO), ap_timing)
        for s, sh in suppliers:
            queue.append([days[i], run, s, purchase[i] * sh, 0])
    queue = [q for q in queue if q[1] > days[i0 - 1]]
    ap_pre = sum(q[3] for q in queue)
    draw, accrued = d0, 0.0
    sprung, spring_day, bump_from = [False] * 3, [None] * 3, [None] * 3
    cert = None
    out = dict(day=[], draw=[], avail=[], line=[], ap=[], late=[], past=[], late_fee=[0.0, 0.0, 0.0], run_detail=[],
               interest=[0.0, 0.0, 0.0], held=[], runs=[],
               supplier={}, eb=[0.0, 0.0, 0.0], capex=[0.0, 0.0, 0.0], fees=[0.0, 0.0, 0.0], over_line=0.0)
    cia_until = {}
    for s, _ in suppliers:
        out["supplier"][s] = dict(first=[dict() for _ in range(3)], hold=None, release=None, misses=0, cia=0.0,
                                  max_past=[0, 0, 0])

    def base_on(i):
        t = t_of(i)
        dil = BILLBACK_MCB + OPDED[t]
        elig = (open_inv[i] - dtc_open[i]) * (1 - INELIGIBLE_90D)      # AR less residuals and DTC (A9.14)
        return (0.85 - (dil - 0.05)) * elig + min(0.5 * fg[i], INV_SUBLIMIT)

    cert = base_on(i0 - 1)
    next_cert = None
    for i in range(i0, n):
        d, t = days[i], yi[i]
        commit = COMMITMENT[0] if d < UPSIZE_DAY else COMMITMENT[1]
        line = min(commit, cert)
        trig = max(SPRING_PCT * commit, AVAIL_HARD)
        x = eb_day[i] - capex / (366 if calendar.isleap(d.year) else 365)
        out["eb"][t] += eb_day[i]
        out["capex"][t] += capex / (366 if calendar.isleap(d.year) else 365)
        draw += -x + (nwc_x(i) - nwc_x(i - 1)) - purchase[i]       # a purchase is AP until its run pays it
        if d == UPSIZE_DAY and sprung[0]:
            draw += AMENDMENT_FEE; out["fees"][t] += AMENDMENT_FEE
        if call and d == call[1]:
            out["call_held"] = sum(q[3] for q in queue if q[1] < d)
            draw -= call[0]
        for s, sh in suppliers:
            amt = purchase[i] * sh
            if cia_until.get(s) and d < cia_until[s]:                  # the order after a release, paid in advance
                draw += amt; out["supplier"][s]["cia"] += amt
            else:
                queue.append([d, _ap_run(d + timedelta(DPO), ap_timing), s, amt, 0])
        if d.day in AP_RUN_DAYS:
            due = sorted((q for q in queue if q[1] <= d), key=lambda q: q[0])
            room = max(0.0, line - draw)
            paid_by = dict((s, 0.0) for s, _ in suppliers)
            has_due = set(q[2] for q in due)
            due_amt = sum(q[3] for q in due)
            for day in sorted(set(q[0] for q in due)):                 # oldest first; one day's invoices pro rata
                batch = [q for q in due if q[0] == day]
                tot = sum(q[3] for q in batch)
                share = min(1.0, room / tot) if tot > 0 else 0.0
                for q in batch:
                    p = q[3] * share
                    q[3] -= p; room -= p; draw += p; paid_by[q[2]] += p
                if share < 1.0:
                    break
            held = sum(q[3] for q in due if q[3] > 1e-12)
            paid_days = [q[0] for q in due if q[3] <= 1e-12]
            held_days = [q[0] for q in due if q[3] > 1e-12]
            # what a part-held run held and paid, so the gate can see oldest-first and the line exhausted (U16)
            out["run_detail"].append(dict(day=d, due=due_amt, held=held, room=room, line=line,
                                          newest_paid=max(paid_days) if paid_days else None,
                                          oldest_held=min(held_days) if held_days else None))
            queue = [q for q in queue if q[3] > 1e-12]
            out["runs"].append((d, due_amt, due_amt - held))
            if held > 1e-9:
                out["held"].append((d, held))
            for s in has_due:                                         # a run the supplier receives nothing from
                if paid_by[s] <= 1e-12:
                    out["supplier"][s]["misses"] += 1
                elif not any(q[2] == s and q[1] <= d for q in queue):
                    out["supplier"][s]["misses"] = 0
        # supplier lines: days past co-packer / ingredient net 30 on the oldest open invoice
        for s, _ in suppliers:
            rec_s = out["supplier"][s]
            open_s = [q for q in queue if q[2] == s and q[1] <= d]
            past = max([(d - q[0]).days - F.SUPPLIER_TERMS["co-packers"] for q in open_s] or [0])
            rec_s["max_past"][t] = max(rec_s["max_past"][t], past)
            for name, at in zip(("priority", "fee", "hold"), supplier_lines):
                if past >= at and name not in rec_s["first"][t]:
                    rec_s["first"][t][name] = d
            if rec_s["misses"] >= HOLD_MISSES and "hold" not in rec_s["first"][t]:
                rec_s["first"][t]["hold"] = d
            if rec_s["hold"] is None and "hold" in rec_s["first"][t]:
                rec_s["hold"] = rec_s["first"][t]["hold"]
            if rec_s["hold"] and rec_s["release"] is None and rec_s["hold"] < d and not open_s:
                # release on the past-due paid; the next order on cash-in-advance, no deposit (A10.07, U18): the
                # supplier's invoices from the day after release to its next AP run, paid the day they are raised
                rec_s["release"] = d
                cia_until[s] = _ap_run(d + timedelta(1), "after")
        # interest: the month's prime + 1.5%, ACTUAL/360, plus the default rate from the dated spring
        bump = DEFAULT_BUMP if bump_from[t] and d >= bump_from[t] else 0.0
        rate = PRIME_MONTHLY[t][d.month - 1] / 100 + SPREAD + bump
        day_int = max(draw, 0.0) * rate / 360 + max(commit - draw, 0.0) * UNUSED_FEE / 365
        accrued += day_int; out["interest"][t] += day_int
        if (d + timedelta(1)).month != d.month:
            draw += accrued; accrued = 0.0
        avail = line - draw
        out["over_line"] = max(out["over_line"], -avail)
        if not sprung[t] and avail < trig - 1e-9:                     # A10.19's cushion sizes the y3 peak ON the trigger
            sprung[t], spring_day[t], bump_from[t] = True, d, d + timedelta(1)
            if t >= 1:
                draw += FORBEARANCE_FEE; out["fees"][t] += FORBEARANCE_FEE
        # the borrowing-base certificate: monthly, weekly once the line has sprung (A9.14)
        if (d + timedelta(1)).month != d.month or (sprung[t] and d.weekday() == 4):
            cert = base_on(i)
        out["day"].append(d); out["draw"].append(draw); out["avail"].append(avail); out["line"].append(line)
        out["ap"].append(sum(q[3] for q in queue))
        out["late"].append(sum(q[3] for q in queue if q[1] <= d))     # held past its run: the stretch
        # A10.07's late fee, 1.5% a month from 30 days past due: a READING, not charged (no P&L line carries it)
        out["late_fee"][t] += sum(q[3] for q in queue if (d - q[0]).days - F.SUPPLIER_TERMS["co-packers"]
                                  >= supplier_lines[1]) * LATE_FEE_MONTH * 12 / 365
        out["past"].append(max([(d - q[0]).days - F.SUPPLIER_TERMS["co-packers"] for q in queue if q[1] <= d]
                               or [0]))
    out["interest"] = [out["interest"][t] + out["fees"][t] for t in range(3)]     # interest and fees, as ledger()'s
    # the y1 stub: the default rate from y1's dated spring to the Q1 y2 cure (A9.14), which ledger() leaves unmodelled
    stub = 0.0
    if spring_day[0]:
        for k, d in enumerate(out["day"]):
            if spring_day[0] < d < UPSIZE_DAY:
                stub += max(out["draw"][k], 0.0) * DEFAULT_BUMP / 360
    ends = [out["draw"][max(k for k, d in enumerate(out["day"]) if d.year == 2023 + t)] for t in range(3)]
    dec31 = [max(k for k, d in enumerate(days) if d.year == 2023 + t) for t in range(3)]
    k_of = dict((d, k) for k, d in enumerate(out["day"]))
    out.update(ends=ends, springs=spring_day, stub=stub, wc=wc,
               dec31=[dict(ar=open_inv[i] + resid_bal[i], inv=inv[i], ap=out["ap"][k_of[days[i]]],
                           accrual=ded_open[i], resid_net=(1 - rec[t_of(i)]) * resid_bal[i], payroll=accr[i])
                      for i in dec31],
               pre=dict(ar=open_inv[i0 - 1] + resid_bal[i0 - 1], inv=inv[i0 - 1], ap=ap_pre,
                        accrual=ded_open[i0 - 1], resid_net=(1 - rec[0]) * resid_bal[i0 - 1], payroll=accr[i0 - 1]),
               fg=dict((days[i], fg[i]) for i in range(n)), cogs=P["cogs"])
    return out


def daily_events(L):
    """What the daily ledger dates: per year, the peak day, and the first Q4 run the collections since the last
    run cover (the trough day, U18); the hold and its release by supplier."""
    need = [L["draw"][k] + L["late"][k] for k in range(len(L["day"]))]   # the draw plus the stretch it rests on
    out = []
    for t in range(3):
        ks = [k for k, d in enumerate(L["day"]) if d.year == 2023 + t]
        peak = max(ks, key=lambda k: need[k])
        runs = [k for k in ks if L["day"][k].day in AP_RUN_DAYS and L["day"][k].month >= 10]
        covered = next((L["day"][b] for a, b in zip(runs, runs[1:]) if need[b] < need[a]), None)
        out.append(dict(peak_day=L["day"][peak], peak=need[peak], draw_at_peak=L["draw"][peak],
                        min_avail=min(L["avail"][k] for k in ks), trough_run=covered))
    return out


# ------------------------------------------------------------ U21, the entry function
# outputs() is what the gate checks and the platform's seeders import, one object (regen plan U21). Each _printed_*
# function carries the values one gate function's entries read, (anchor, label, value), the label the entry's own;
# _values() is the shared work they read, once a process. The gate reads none of this module's internals.
_MEMO = {}


def _values():
    """This generator's share of the work the printed entries read (the gate's _group11_compute until U21), by the
    names the entries use."""
    if "values" in _MEMO:
        return _MEMO["values"]
    P = pnl()
    OP = opex()
    EST = establish_check(P["net"])
    wc = working_capital(P["cogs"])
    bb = borrowing_base(wc)
    Lg = ledger(P["ebitda"], wc, bb)
    H = handoff(bb, Lg, P["cogs"])
    gaps = []
    for kw in (dict(d0=0.5), dict(d0=1.5), dict(capex=0.15), dict(capex=0.45)):
        gaps.append(-ledger(P["ebitda"], wc, bb, **kw)["avail"][2])
    for kw in (dict(ask=[0, 0.01, 0.02], giveback=0.50), dict(ask=[0, 0.03, 0.04], giveback=0.30)):
        p2 = pnl(**kw)
        w2 = working_capital(p2["cogs"])
        gaps.append(-ledger(p2["ebitda"], w2, borrowing_base(w2))["avail"][2])
    lo, hi = -0.5, 0.5
    for _ in range(60):
        mid = (lo + hi) / 2
        if pnl(oversettle=mid)["ebitda"][2] > 0:
            lo = mid
        else:
            hi = mid
    _MEMO["values"] = dict(
        inspection_hours=INSPECTION[0],
        costs=P["group11"],
        ebitda=P["ebitda"],
        ebitda_pct=[P["ebitda"][t] / GROSS[t] * 100 for t in range(3)],
        gap=-Lg["avail"][2],
        gap_band=[min(gaps), max(gaps)],
        dso=wc["dso"],
        ar=wc["ar"],
        nwc=wc["nwc"],
        nwc_pre=wc["nwc_pre"],
        growth=[wc["nwc"][t] - (wc["nwc_pre"] if t == 0 else wc["nwc"][t - 1]) for t in range(3)],
        collateral=bb["base"][0] - Lg["peak"][0],
        dpo_days=H["dpo_days"],
        dpo_to=H["dpo_to"],
        short=H["short"],
        run_share=H["short"][0] / H["ap_run"][0] * 100,
        ap_run=H["ap_run"][0],
        invoice_days=H["short"][0] / (GROSS[0] / 365),
        upsize=COMMITMENT[1] / bb["base"][0] * 100,
        vs_base=H["vs_base"],
        y3_zero=(lo + hi) / 2,
        gross_2024=GROSS[1],
        gross_y3=GROSS[2],
        opex=dict(lines=dict(OP["lines"]), total=OP["total"], pct=OP["pct"], ga=OP["ga"],
                 establish=EST["num"], establish_pct=EST["pct"],
                 warehouse_payroll=warehouse_payroll(), ga_rent=EST["ga_rent"],
                 amazon_fee=[marketplace_fees(t)["referral"] + marketplace_fees(t)["plan"]
                             for t in range(3)],
                 advertising=[marketplace_fees(t)["advertising"] for t in range(3)],
                 broker_share=BROKER_SHARE, acos=ACOS,
                 fba=[marketplace_fees(t)["fulfilment"] for t in range(3)],
                 referral=[marketplace_fees(t)["referral"] for t in range(3)],
                 parcel_carve=[amazon_parcel_in_freight(t) for t in range(3)],
                 per_jar=fba_per_jar()[0],
                 per_pack=[fba_per_jar()[1][n] for n in sorted(PACK_MIX)],
                 fba_non_peak=[amazon_units(t) * fba_per_jar()[0] / 1e6 for t in range(3)],
                 peak=[marketplace_fees(t)["peak"] for t in range(3)],
                 peak_per_jar=fba_peak_per_jar()[0]),
        oregon=oregon(),
        organic=[organic_certificate(t) for t in range(3)],
    )
    return _MEMO["values"]


def _printed_a901_opex(V):
    """The values the gate's _a901_opex_figures reads, keyed (anchor, label) as its entries name them."""
    op = V['opex']
    L = op["lines"]
    tot, pct = op["total"], op["pct"]
    return [
        ('A9.01', 'A9.01 non-production payroll',
         L["payroll"]),
        ('A9.01', 'A9.01 broker commission and retainers',
         L["broker"]),
        ('A9.01', 'A9.01 marketing',
         L["marketing"]),
        ('A9.01', 'A9.01 outbound freight',
         L["freight"]),
        ('A9.01', 'A9.01 warehousing supplies',
         L["warehousing"]),
        ('A9.01', 'A9.01 DTC 3PL, own-site orders',
         L["dtc_3pl"]),
        ('A9.01', 'A9.01 marketplace',
         L["marketplace"]),
        ('A9.01', 'A9.01 G&A',
         L["g_and_a"]),
        ('A9.01', "A11.31's FBA fulfilment, peak uplift included",
         op["fba"]),
        ('A11.31', "A11.31's FBA fulfilment at the non-peak rate, which the row publishes beside it",
         op["fba_non_peak"]),
        ('A9.01', "A11.31's peak charge on the window's days",
         op["peak"]),
        ('A9.01', "A11.31's peak fee a jar",
         [op["peak_per_jar"]]),
        ('A11.31', "A11.31's fee a jar, weighted over A11.03's mix",
         [op["per_jar"]]),
        ('A11.31', "A11.31's three pack fees, single / 2-pack / 3-pack",
         op["per_pack"]),
        ('A9.01', "A11.22's referral blended over A11.03's mix, $M",
         op["referral"]),
        ('A11.22', "A11.22's referral blended over A11.03's mix, $K",
         [r * 1e3 for r in op["referral"]]),
        ('A9.01', 'the Amazon parcel carved out of the freight line',
         op["parcel_carve"]),
        ('A9.01', "the carve at A5.24's flat rate, the reading not applied",     # DECISIONS#u17-start
         [amazon_dollars(t) * FREIGHT_PCT / 1e6 for t in range(3)]),
        ('A9.01', 'A9.01 total opex and its share of gross',
         tot + pct),
        ('A9.01', "A9.01 total opex and its share of gross y1 -> y3, group 9's P&L block",
         tot + [pct[0], pct[2]]),
        ('A9.01', "A9.01's marketing line and its share of gross y1 -> y3, group 9's P&L block",
         L["marketing"] + [L["marketing"][0] / GROSS[0] * 100, L["marketing"][2] / GROSS[2] * 100]),
        ('A9.01', "A9.01's payroll line and its share of gross y1 -> y3, group 9's P&L block",
         L["payroll"] + [L["payroll"][0] / GROSS[0] * 100, L["payroll"][2] / GROSS[2] * 100]),
        ('A9.01', "A9.01's Establish check and its shares of net revenue",
         op["establish"] + op["establish_pct"]),
        ('A9.01', "A9.01's warehouse payroll, the Establish numerator's first term",
         op["warehouse_payroll"]),
        ('A9.01', "A9.01's Establish shares, group 9's doc",
         op["establish_pct"]),
        ('A9.01', "A11.30's advertising, A9.01 and its own row",
         op["advertising"]),
        ('A11.30', "A11.30's ACoS point",
         [op["acos"] * 100]),
        ('A9.09', "A9.09's broker-managed share, restated on A5.38's DPI move",
         [s * 100 for s in op["broker_share"]]),
    ]


def _printed_restated_21(V):
    """The values the gate's _restated_21_figures reads, keyed (anchor, label) as its entries name them."""
    P = pnl()
    wc = working_capital(P["cogs"])
    bb = borrowing_base(wc)
    Lg = ledger(P["ebitda"], wc, bb)
    prime = [sum(m) / 12 for m in PRIME_MONTHLY]
    ebp, eb3 = V["ebitda_pct"], V["ebitda"][2]
    corners = [pnl(ask=[0, 0.01, 0.02], giveback=0.50), pnl(ask=[0, 0.03, 0.04], giveback=0.30)]
    band = [c["ebitda"][t] / GROSS[t] * 100 for c in corners for t in range(3)]
    Af, Ac = achievable("full"), achievable("controls")
    pf, pc = dict(Af["terms_pct"]), dict(Ac["terms_pct"])
    tf, tc = dict(Af["terms"]), dict(Ac["terms"])
    res, line = Af["a431_residual"], OPDED[2] * 100
    own = own_site_dollars(2) / 1e6
    _contribution = dtc_contribution()
    dtc = [_contribution["current"][2] * 100, _contribution["achievable"] * 100]
    op = V["opex"]
    one_time = PICK + JARS_PER_ORDER["one_time"] * PER_UNIT + PACK_MATERIAL
    uplift = [(sum(units_by_account(t).values()) / sum(units_by_account(t, ask=[0, 0, 0]).values()) - 1) * 100
              for t in (0, 1)]
    gp = [P["net"][t] - P["cogs"][t] for t in range(3)]
    cyc = [wc["dso"][t] + DIO[t] - DPO for t in range(3)]
    whole = dso()[0]
    return [
        ('A9.02', "A9.02's COGS, $M, the row and group 9's P&L block",
         P["cogs"]),
        ('A9.13', "A9.13's working-capital growth by component, y2 then y3",
         [abs(working_capital(P["cogs"])[k][t] - working_capital(P["cogs"])[k][t - 1]) for t in (1, 2)
          for k in ("ar", "inv", "ap", "accrual", "resid_net")]),
        ('A9.02', "A9.02's slotting deducted, free-fill, then net revenue, the row",
         [s["deducted"] for s in P["slotting"]] + [s["free_fill"] for s in P["slotting"]] + P["net"]),
        ('A9.02', "A9.02's slotting deducted, free-fill, then net revenue, group 9's P&L block",
         [s["deducted"] for s in P["slotting"]] + [s["free_fill"] for s in P["slotting"]] + P["net"]),
        ('A9.02', "A9.02's slotting invoiced, the row and group 9's P&L block",
         [s["invoiced"] for s in P["slotting"]]),
        ('A9.02', "A9.02's wholesale COGS ratio, the row and A3.02's copy",
         P["ratio"]),
        ('A9.02', "A9.02's wholesale COGS ratio, group 9's P&L block",
         P["ratio"]),
        ('A9.02', "A9.02's price band, EBITDA % of gross at the low corner then the high, the row and group 9's doc",
         band),
        ('A9.02', "y3 EBITDA at every point of the price band, A9.02 and group 9's doc",
         [ebp[2]]),
        ('A9.02', "EBITDA as a percent of gross, group 9's A9.02 paragraph",
         ebp),
        ('A9.02', "the y3 funding gap's band, A9.02",
         V["gap_band"]),
        ('A9.02', "A9.02's achievable, settlement then own-site DTC, then the total at each tier against y3 EBITDA",
         [pf["settlement"], tf["settlement"], dtc[1], dtc[0], own, own / GROSS[2] * 100, pf["dtc"], tf["dtc"],
          S_DTC * 100, Af["ebitda"], Af["pct"], Ac["ebitda"], Ac["pct"], abs(eb3), ebp[2]]),
        ('A9.02', "A9.02's achievable, owed: A4.31's residual, the full tier if A4.31 sits in A4.15's excess, and A6.15's recovery on A4.31",
         [res, Af["pct_if_excess"], Af["a431_recovery"]]),
        ('A9.13', "A9.02's achievable against current, then its deduction and settlement points of all its points, A9.13 and group 9's doc",
         [Af["pct"], ebp[2], pf["deductions"] + pf["settlement"], sum(pf.values())]),
        ('A9.13', "A9.14's +200bp default-rate charge, y2 and y3, A9.13",
         Lg["bump_cost"][1:]),
        ('A9.14', "A9.14's +200bp default-rate charge, y2 and y3, group 9's doc and the A9.14 fees marker",
         Lg["bump_cost"][1:]),
        ('A9.13', 'the y3 gap at capex 0.15 / 0.30 / 0.45, A9.13',
         [-ledger(P["ebitda"], wc, bb, capex=c)["avail"][2] for c in (0.15, CAPEX, 0.45)]),
        ('A9.13', "the y3 funding gap and its band, A9.13 and group 9's doc",
         [V["gap"]] + V["gap_band"]),
        ('A9.13', 'the y1 exceedance absorbed by payment timing: $M, days of COGS, share of an AP run, the run, days of invoicing',
         [V["short"][0], V["dpo_days"][0], V["run_share"], V["ap_run"], V["invoice_days"]]),
        ('A9.13', "the ladder group 10 inherits: days of COGS, then DPO, A9.13 and group 9's doc",
         V["dpo_days"] + V["dpo_to"]),
        ('A9.13', 'the peak need over the base in y2 and y3, A9.13',
         V["vs_base"][1:]),
        ('A9.13', "the loan under the base at the y1 peak, A9.13 and group 9's doc",
         [V["collateral"]]),
        ('A9.14', "A9.14's prime annual means, each the mean of its year's published months, the row and group 9's doc",
         prime),
        ('A9.14', "A9.14's prime annual means, the row's figure field",
         prime),
        ('A9.14', "A9.14's prime annual means, group 9's sources table",
         prime),
        ('A9.14', "A9.14's prime annual means, its sources entry",
         prime),
        ('A9.14', "A9.14's all-in rate, each year's mean plus the spread, the row and group 9's doc",
         [x * 100 for x in PRIME_PLUS]),
        ('A9.13', "A9.13's FCCR, the row and group 9's doc",
         Lg["fccr"]),
        ('A9.13', "A9.13's y1 FCCR where group 9's doc prints it alone",
         Lg["fccr"][:1]),
        ('A9.13', "A9.13's accrual in unpaid invoices, then the residual net of recovery, the row and group 9's doc",
         wc["accrual"] + wc["resid_net"]),
        ('A9.12', "A9.12's Q4 build, +40% of finished goods, the row and group 9's doc",
         wc["build"]),
        ('A9.12', "A9.12's inventory at COGS, then AP, the row and group 9's doc",
         wc["inv"] + wc["ap"]),
        ('A9.12', "A9.12's finished goods, the row",
         wc["fg"]),
        ('A9.02', "A9.02's gross profit, net revenue less COGS, the row and group 9's doc",
         [P["net"][t] - P["cogs"][t] for t in range(3)]),
        # A9.11's DSO on the filers' basis, receivables over NET sales (owner, 2026-11-06, DECISIONS#u14)
        ('A9.11', "A9.11's DSO on net sales, the filers' basis",
         [V["dso"][t] * GROSS[t] / P["net"][t] for t in range(3)]),
        ('A11.31', "A11.31's fee a jar against A3.18's price, and its share of it, the plausibility anchor",
         [op["per_jar"], AMAZON_PRICE, op["per_jar"] / AMAZON_PRICE * 100]),
        ('A11.31', "A8.13's own-site 3PL on a one-time order and a jar, and A8.12's y1 parcel rate, in A11.31's plausibility anchor",
         [one_time, JARS_PER_ORDER["one_time"], one_time / JARS_PER_ORDER["one_time"],
          SHIPPING_NET[0] * 100]),
        ('A3.01', 'EBITDA at the 2025 base, A3.01',
         ebp),
        ('A3.02', "A3.02's fully loaded cost over gross by channel, the row and group 3's doc",
         [COST_12 / PRICE[k] * 100 for k in ("WF", "Sprouts", "Kroger", "Walmart", "UNFI", "KeHE", "DPI")]
         + [2 * COST_18 / PRICE_CLUB * 100, DTC_COGS[2] * 100]),
        ('A3.04', "A3.04's back-cast unit uplift, y1 and y2",
         uplift),
        ('A3.04', "A3.04's back-cast unit uplift, whole then to one decimal, the correction marker",
         [uplift[0], uplift[0], uplift[1], uplift[1]]),
        ('A9.01', "A9.01's copy of A9.02's EBITDA % of gross and A9.13's y3 funding gap",
         ebp + [V["gap"]]),
        ('A8.15', "A8.15's unfiled carrier-claim dollars, $K",
         [unfiled_claims(t) / 1e3 for t in range(3)]),
        ('A8.18', "A8.18's tickets, then their cost $K",
         [service_tickets(t)[0] for t in range(3)] + [service_tickets(t)[1] / 1e3 for t in range(3)]),
        ('A10.07', "A10.07's hold-cut fit: the co-packers' share",
         [COPACK_SHARE * 100]),
        ('A10.07', "A10.07's hold-cut fit: the materials' share",
         [(1 - COPACK_SHARE) * 100]),
        ('A9.12', "A9.12's cash conversion cycle, DSO + DIO - DPO, the row",
         cyc),
        ('A9.12', "A9.12's cash conversion cycle y1 -> y3, group 9's doc",
         [cyc[0], cyc[2]]),
        ('A9.12', "A9.12's trough: the mean DSO at which Q4 collects",
         [sum(wc["dso"]) / 3]),
        ('A9.12', "A9.12's build on the line, in months",
         [Lg["on_line"] * 12]),
        ('A9.14', "A9.14's finished goods at the November peak",
         [(1 + BUILD_PCT) * x for x in wc["fg"]]),
        ('A9.14', "A9.14's sizing: the projected y2 base, and the margin the $4.5M commitment clears it by",
         [bb["base"][1], (bb["base"][1] - COMMITMENT[1]) / bb["base"][1] * 100]),
        ('A9.14', "A9.14's sizing, the November y1 amendment's present note: the y2 base, the margin, the upsize against the base examined, that base",
         [bb["base"][1], (bb["base"][1] - COMMITMENT[1]) / bb["base"][1] * 100, V["upsize"], bb["base"][0]]),
        ('A9.14', "A9.14's base examined at the November y1 peak",
         [bb["base"][0]]),
        ('A9.14', "A9.14's y3 base",
         [bb["base"][2]]),
        ('A9.14', "A9.14's November-peak base by year, group 9's doc",
         bb["base"]),
        ('A9.14', "A9.14's November y1 peak need, the row",
         [Lg["peak"][0]]),
        ('A9.14', "A9.14's November y1 peak need, group 9's doc",
         [Lg["peak"][0]]),
        ('A9.14', "the peak need against the base from y2, A9.14 and group 9's doc",
         [Lg["peak"][1], bb["base"][1], Lg["peak"][2], bb["base"][2]]),
        ('A9.13', "A9.13's cash from operations",
         Lg["cfo"]),
        ('A9.13', "A9.13's standing draw at year end",
         Lg["ends"]),
        ('A9.13', "A9.13's interest and fees",
         Lg["interest"]),
        ('A9.13', "A9.13's peak need",
         Lg["peak"]),
        ('A9.13', "A9.13's excess availability",
         Lg["avail"]),
        ('A9.13', "A9.13's y1 commitment shortfall: the peak need, the base, the collateral unused",
         [Lg["peak"][0], bb["base"][0], bb["base"][0] - Lg["peak"][0]]),
        ('A9.02', "A9.02's EBITDA as a percent of gross, the row",
         ebp),
        ('A9.02', "A9.02's copy of A9.01's opex",
         P["opex"]),
        ('A9.02', "A9.02's gross profit as a share of gross, y1 -> y3",
         [gp[0] / GROSS[0] * 100, gp[2] / GROSS[2] * 100]),
        ('A9.02', "A9.02's gross profit and its shares of gross and net y1 -> y3, group 9's P&L block",
         gp + [gp[0] / GROSS[0] * 100, gp[2] / GROSS[2] * 100, gp[0] / P["net"][0] * 100,
               gp[2] / P["net"][2] * 100]),
        ('A9.02', "A9.02's EBITDA and its share of gross, group 9's P&L block",
         V["ebitda"] + ebp),
        ('A9.02', "A9.02's EBITDA share of gross, group 9's headline",
         ebp),
        ('A9.02', "group 11's costs, group 9's A9.02 paragraph",
         [c["total"] for c in P["group11"]]),
        ('A11.12', "A11.12's write-offs as A9.02 reads them, group 9's doc",
         [c["write_off"] for c in P["group11"]]),
        ('A9.02', "A9.02's DTC COGS by year",
         [x * 100 for x in DTC_COGS]),
        ('A9.02', "A9.02's derivation of A8.11's contribution: y3 margin, shipping, fulfilment, payment, achievable, current y3",
         [(1 - DTC_COGS[2]) * 100, SHIPPING_ACHIEVABLE * 100, THREEPL_ACHIEVABLE * 100, PAYMENT * 100,
          dtc[1], dtc[0]]),
        ('A9.11', "A9.11's mix-weighted wholesale days, then blended at A8.01's DTC share",
         list(whole) + [(1 - S_DTC) * w + S_DTC * DAYS_DTC for w in whole]),
        ('A9.09', "A9.09's broker-managed share, group 9's doc",
         [s * 100 for s in BROKER_SHARE]),
        ('A9.09', "A9.09's broker cost, the row and group 9's doc",
         broker()),
        ('A8.11', "A8.11's DTC COGS by window year",
         [x * 100 for x in DTC_COGS]),
        ('A8.11', "A8.11's blended product margin y1 -> y3, the row and group 8's doc",
         [(1 - DTC_COGS[t]) * 100 for t in (0, 2)]),
        ('A8.11', "A8.11's contribution before marketing y1 -> y3, group 8's doc",
         [_contribution["current"][0] * 100, _contribution["current"][2] * 100]),
        ('A8.11', "A8.11's contribution before marketing y1 -> y3, group 8's opening summary",
         [_contribution["current"][0] * 100, _contribution["current"][2] * 100]),
        ('A8.11', "A8.11's achievable contribution, group 8's doc",
         [dtc[1]]),
    ]



def _printed_group11(V):
    """The values the gate's group11_figures reads, keyed (anchor, label) as its entries name them."""
    return [
        ('A9.02', 'EBITDA, $M, A9.02 (the row writes the sign before the dollar sign; the percent series carries it)',
         [abs(e) for e in V["ebitda"]]),
        ('A9.02', 'EBITDA, $M',
         V["ebitda"]),
        ('A11.01', "Amazon's fees the P&L reads, $K",
         [f * 1e3 for f in V["opex"]["amazon_fee"]]),
        ('A9.02', 'EBITDA, its share of gross, the gap and its band, the decision',
         V["ebitda"] + V["ebitda_pct"] + [V["gap"]]
         + V["gap_band"]),
        ('A9.13', 'the y3 funding gap, doc',
         [V["gap"]]),
        ('A9.13', 'the y3 funding gap, the undated-sources decision',
         [V["gap"]]),
        ('A9.02', 'y1 EBITDA, the undated-sources decision',
         [V["ebitda"][0]]),
        ('A11.09', 'the organic inspection hours',
         [V["inspection_hours"]]),
        ('A11.09', 'the organic inspection dollars',
         [V["inspection_hours"] * 72.0]),
        ('A11.04', 'DSO, A9.11 at the ruled 60 days',
         V["dso"]),
        ('A9.12', 'AR on the restated DSO',
         V["ar"]),
        ('A9.13', 'NWC, the pre-window balance, then its growth, A9.13',
         V["nwc"] + [V["nwc_pre"]] + V["growth"]),
        ('A9.13', "NWC and the pre-window balance, group 9's doc",
         V["nwc"] + [V["nwc_pre"]]),
        ('A9.13', 'collateral unused behind the y1 draw',
         [V["collateral"]]),
        ('A9.13', 'the y1 shortfall in days, share of an AP run, the run, days of invoicing',
         [V["dpo_days"][0], V["run_share"], V["ap_run"], V["invoice_days"]]),
        ('A9.14', 'the upsize against the base examined',
         [V["upsize"]]),
        ('A9.14', 'the base passed from y2, unfunded',
         V["vs_base"][1:]),
        ('A9.02', 'EBITDA at the 2025 base, the markers',
         V["ebitda_pct"]),
        ('A9.02', 'y3 EBITDA at every point of the band',
         [V["ebitda_pct"][2]]),
        ('A4.15', "the y3 zero crossing in A4.15's band",
         [V["y3_zero"] * 100]),
        ('A9.13', 'the y1 exceedance in $M',
         [V["short"][0]]),
        ('A9.13', 'the collateral in $K, the marker',
         [V["collateral"] * 1000]),
        ('A9.13', 'the ladder, DPO, and the base passed from y2, the marker',
         V["dpo_days"] + V["dpo_to"] + V["vs_base"][1:]),
        ('A9.14', "the gap, its band, then y1's exceedance and days, the A9.14 fees marker",
         [V["gap"]] + V["gap_band"] + [V["short"][0] * 1000, V["dpo_days"][0]]),
        ('A10.17', 'the gap and its band, the A10.17 bands marker',
         [V["gap"]] + V["gap_band"]),
        ('A11.25', 'A11.25 revenue test, 2024 gross $M',
         [V["gross_2024"]]),
        ('A9.02', 'EBITDA is a loss in every window year',
         all(e < 0 for e in V["ebitda"])),
    ]


def _printed_generator(V):
    """The values the gate's check_generator_figures reads, keyed (anchor, label) as its entries name them."""
    P = pnl()
    wc = working_capital(P["cogs"])
    bb = borrowing_base(wc)
    return [
        ('A9.13', 'net working capital',
         wc["nwc"]),
        ('A9.14', 'borrowing base',
         bb["base"]),
    ]


def _printed_amazon_basis(V):
    """A3.29's rolled standard and A11.32's two bases and the gap between them (owner, 2026-10-12), as the gate's
    _amazon_basis_figures reads them. The mart costs a jar at A3.29's standard, A3.01's manufactured cost rolled once
    at _cost_index()'s 2023 level, to the cent; the P&L costs it at A3.01's landed cost at A9.16's index and A9.17's
    tariff, as pnl() does. The window band runs A11.30's ACoS band, high ACoS first."""
    from decimal import Decimal, ROUND_HALF_UP
    idx = _cost_index()
    std = float((Decimal(repr(COST_MANUFACTURED)) * Decimal(repr(idx[0]))).quantize(Decimal("0.01"),
                                                                                    rounding=ROUND_HALF_UP))
    landed = [COST_12 * idx[t] * (1 + TARIFF[t]) for t in range(3)]
    dollars = [amazon_dollars(t) for t in range(3)]
    units = [amazon_units(t) for t in range(3)]

    def fees(acos):
        global ACOS
        saved, ACOS = ACOS, acos
        try:
            return [marketplace_fees(t)["total"] * 1e6 for t in range(3)]
        finally:
            ACOS = saved

    f = fees(ACOS)

    def margin(cost, t):
        return (1 - f[t] / dollars[t] - units[t] * cost[t] / dollars[t]) * 100

    def pooled(fs):
        return (1 - sum(fs) / sum(dollars) - sum(units) * std / sum(dollars)) * 100

    gap = [(landed[t] - std) * units[t] for t in range(3)]
    return [
        ('A3.29', "A3.29's rolled standard, the mart's cost a jar",
         [std]),
        ('A11.32', "A11.32 on the mart's basis, by window year",
         [margin([std] * 3, t) for t in range(3)]),
        ('A11.32', "A11.32 over the window, the mart's all-time row",
         [pooled(f)]),
        ('A11.32', "A11.32's window band, from A11.30's ACoS band",
         [pooled(fees(ACOS_BAND[1])), pooled(fees(ACOS_BAND[0]))]),
        ('A11.32', "A11.32 on the P&L's basis, by window year",
         [margin(landed, t) for t in range(3)]),
        ('A11.32', "A11.32's gap, landed less standard on Amazon's units, points of Amazon sales",
         [gap[t] / dollars[t] * 100 for t in range(3)]),
        ('A11.32', "A11.32's gap in dollars, $K",
         [g / 1e3 for g in gap]),
    ]


LEDGER_PRINTED = ("day", "draw", "avail", "line", "ap", "late", "eb", "capex", "run_detail", "held", "springs")


def outputs():
    """U21's entry function: what the gate checks and the seeders read, one object (regen plan U21).

    `printed` holds every value the registry prints from this generator, keyed by the anchor id that prints it and
    then by the gate entry that reads it, at full precision. Beside the entries: marketplace_fees(t)'s seven
    components by year, which U13 writes as N22's fee rows; U16's daily ledger, on the line's own cash (the run that
    dates the hold) and with A10.19's note in it (the data's cash), each with the series the gate reads; and the
    AP-run schedule the noted ledger pays, which group 10 renders into group 9's sourcing doc."""
    import group10_floors as F           # F imports this module at load; imported here so load order holds
    V = _values()
    printed = {}
    for fn in (_printed_a901_opex, _printed_restated_21, _printed_amazon_basis, _printed_group11, _printed_generator):
        for anchor, label, value in fn(V):
            printed.setdefault(anchor, {})[label] = value
    fees = [marketplace_fees(t) for t in range(3)]
    printed["A9.01"]["marketplace_fees(t)'s seven components by year, $M"] = dict(
        (k, [f[k] for f in fees]) for k in ("referral", "plan", "fulfilment", "storage", "inbound", "returnless",
                                            "advertising"))
    own, noted = F._daily(), F.equity_call()["after"]
    printed["A9.13"]["the daily ledger on the line's own cash"] = dict((k, own[k]) for k in LEDGER_PRINTED)
    printed["A9.13"]["the daily ledger, A10.19's note in it"] = dict((k, noted[k]) for k in LEDGER_PRINTED)
    printed.setdefault("A9.11", {})["the AP-run schedule, A10.19's note in it, $M"] = [
        dict(day=r["day"], due=r["due"], paid=r["due"] - r["held"], held=r["held"]) for r in noted["run_detail"]]
    return dict(printed=printed)


def _f(v, p=3):
    return " / ".join(("%+." + str(p) + "f") % x if x < 0 else ("%." + str(p) + "f") % x for x in v)


def main():
    P = pnl()
    O = opex()
    EST = establish_check(P["net"])
    wc = working_capital(P["cogs"])
    bb = borrowing_base(wc)
    L = ledger(P["ebitda"], wc, bb)
    whole, resid_days, d = dso()

    print("FREE INPUTS (everything else is computed)")
    for name, val, status in INPUTS:
        print("   %-42s %-32s %s" % (name, val, status))

    print("\nA9.01  opex, line by line, $M   (DERIVED 2026-09-18; was a hardcoded input)")
    for name, vals in O["lines"]:
        print("   %-21s %s" % (name, _f(vals)))
    print("   %-21s %s   = %s%% of gross" % ("TOTAL", _f(O["total"]), _f(O["pct"], 1)))
    print("   G&A decomposed        %s" %
          "  ".join("%s %s" % (k, _f(O["ga"][k], 3)) for k, _ in GA_SPLIT[:3]))
    print("   %-21s %s" % ("",
          "  ".join("%s %s" % (k, _f(O["ga"][k], 3)) for k, _ in GA_SPLIT[3:])))
    M = [marketplace_fees(t) for t in range(3)]
    pj, pp = fba_per_jar()
    for lbl, k in (("FBA fulfilment", "fulfilment"), ("referral", "referral"), ("advertising", "advertising"),
                   ("storage", "storage"), ("inbound placement", "inbound"), ("returnless refunds", "returnless"),
                   ("Professional plan", "plan")):
        print("      %-19s %s" % (lbl, _f([m[k] for m in M], 4)))
    print("   FBA a jar $%.4f  (single $%.2f, 2-pack $%.2f = $%.2f a jar, 3-pack $%.2f = $%.2f a jar;"
          " A11.03 mix %s)" % (pj, pp[1], pp[2], pp[2] / 2, pp[3], pp[3] / 3,
                               " / ".join("%.0f%%" % (PACK_MIX[n] * 100) for n in sorted(PACK_MIX))))
    print("   referral blended %.1f%% over the same mix (A11.22's 8%% floor retires)" % (M[0]["rate"] * 100))
    print("   ALTERNATIVE, printed not applied: at A11.03's retired virtual-bundle wording, fulfilment %s"
          " and referral %s" % (_f([m["alternative"]["fulfilment"] for m in M], 4),
                                _f([m["alternative"]["referral"] for m in M], 4)))
    print("   freight carve-out     %s   A8.12's parcel on Amazon's dollars, removed because FBA delivers"
          % _f([amazon_parcel_in_freight(t) for t in range(3)], 4))
    print("   OWED: the peak (Oct 15 - Jan 14) uplift on Q4 units, and the 2023-24 cards")
    print("   Establish check       %s = %s%% of NET vs %.2f%% (A5.24) - satisfied, headroom %s pt" %
          (_f(EST["num"]), _f(EST["pct"], 2), EST["benchmark"],
           _f([EST["benchmark"] - x for x in EST["pct"]], 2)))

    print("\nA9.02  P&L identity, $M")
    print("   gross                 %s" % _f(GROSS))
    print("   trade accrued 14%%     %s" % _f([TRADE * g for g in GROSS]))
    print("   trade over-settled    %s   (A4.15 at %.1f%%, %d-day lag)" % (_f(P["over"]), OVERSETTLE * 100, SETTLE_LAG))
    print("   operational deductions%s" % _f([OPDED[t] * GROSS[t] for t in range(3)]))
    print("   net revenue           %s" % _f(P["net"]))
    print("   COGS                  %s   (wholesale ratio %s%%)" % (_f(P["cogs"]), _f(P["ratio"], 2)))
    print("   opex                  %s   = %s%% of gross" % (_f(P["opex"]), _f(O["pct"], 1)))
    print("   group 11's costs      %s   (write-offs %s + Faire %s + organic certificate %s + Oregon %s)" %
          (_f([r["total"] for r in P["group11"]], 4), _f([r["write_off"] for r in P["group11"]], 4),
           _f([r["faire"] for r in P["group11"]], 4), _f([r["organic"] for r in P["group11"]], 4),
           _f([r["oregon"] for r in P["group11"]], 4)))
    print("   EBITDA                %s   = %s%% of gross" %
          (_f(P["ebitda"]), _f([P["ebitda"][t] / GROSS[t] * 100 for t in range(3)], 2)))

    print("\nA9.11  DSO identity")
    print("   wholesale mix-weighted days to pay   %s" % _f(whole, 2))
    print("   blended with DTC at %.0f%% x %d days  " % (S_DTC * 100, DAYS_DTC), end="")
    print("%s" % _f([(1 - S_DTC) * whole[t] + S_DTC * DAYS_DTC for t in range(3)], 2))
    print("   plus open residuals in days of gross %s" % _f(resid_days, 2))
    print("   DSO on gross                         %s" % _f(d, 2))

    print("\nA9.12  working capital, $M")
    print("   AR %s | inventory %s | AP %s" % (_f(wc["ar"]), _f(wc["inv"]), _f(wc["ap"])))
    print("   finished-goods share of DIO %s%%  -> FG %s, Q4 build %s" %
          (_f([x * 100 for x in wc["fg_share"]], 1), _f(wc["fg"]), _f(wc["build"])))
    print("   less deductions already charged in EBITDA: accrual %s, residual net of recovery %s" %
          (_f(wc["accrual"]), _f(wc["resid_net"])))
    print("   NWC %s  (pre-window %.3f)  growth %s" %
          (_f(wc["nwc"]), wc["nwc_pre"],
           _f([wc["nwc"][t] - (wc["nwc_pre"] if t == 0 else wc["nwc"][t - 1]) for t in range(3)])))

    print("\nA9.14  borrowing base, $M")
    print("   dilution %s%% -> advance %s%%" %
          (_f([x * 100 for x in bb["dilution"]], 2), _f([x * 100 for x in bb["advance"]], 1)))
    print("   eligible AR %s | inventory leg %s | base %s vs commitment %s" %
          (_f(bb["eligible"]), _f(bb["inv_leg"]), _f(bb["base"]), _f(COMMITMENT, 1)))

    print("\nA9.13  ledger, $M")
    print("   cash from operations %s" % _f(L["cfo"]))
    print("   standing draw at year end %s | interest and fees %s" % (_f(L["ends"]), _f(L["interest"])))
    print("   peak need (%.3f of the year elapsed, build on the line %.3f of a year) %s" %
          (ELAPSED, L["on_line"], _f(L["peak"])))
    print("   excess availability %s | springing trigger %s" % (_f(L["avail"]), _f(L["trigger"], 2)))
    print("   FCCR %s vs 1.10x -> springs in y%s and fails every time"
          % (_f(L["fccr"], 2), ", y".join(str(y) for y in L["springs"])))
    print("   y3 funding gap %+.2f" % L["avail"][2])
    print("")
    print("A9.14  breach consequences, read into the fee line (not asserted beside it)")
    print("   amendment fee    %s   0.50%% of the $1.5M increase, once, on the Q1 y2 cure of the y1 spring"
          % _f(L["amend"], 5))
    print("   forbearance fee  %s   0.25%% of the $4.5M commitment, each year forborne" % _f(L["forb"], 5))
    print("   default +200bp   %s   UPPER BOUND -- daily_ledger() dates the springs (U16),"
          % _f(L["bump_cost"], 4))
    print("                    %s   because the breach begins when availability crosses the trigger, not 1 January"
          % (" " * 21))
    print("   the y1 stub to the Q1 y2 cure: ~%.3f at 200bp over ~75 days on this ledger; daily_ledger() dates and"
          " prices it" % L["stub"])

    D = daily_ledger()
    ev = daily_events(D)
    k31 = [max(k for k, d in enumerate(D["day"]) if d.year == 2023 + t) for t in range(3)]
    print("")
    print("A9.13  the daily ledger (U16), the line's own cash, beside the annual means above")
    print("   flows: EBITDA %s (annual %s) | capex %s" % (_f(D["eb"]), _f(P["ebitda"]), _f(D["capex"])))
    print("   Dec 31 draw %s | stretch %s | need %s   (annual year end %s)"
          % (_f([D["draw"][k] for k in k31]), _f([D["late"][k] for k in k31]),
             _f([D["draw"][k] + D["late"][k] for k in k31]), _f(L["ends"])))
    print("   Dec 31 AR %s | AP %s   (annual means %s | %s)"
          % (_f([x["ar"] for x in D["dec31"]]), _f([x["ap"] for x in D["dec31"]]), _f(wc["ar"]), _f(wc["ap"])))
    print("   need peaks %s on %s; first Q4 run need falls: %s"
          % (_f([e["peak"] for e in ev]), " / ".join(str(e["peak_day"]) for e in ev),
             " / ".join(str(e["trough_run"]) for e in ev)))
    print("   interest and fees %s (annual %s) | late-fee reading %s"
          % (_f(D["interest"]), _f(L["interest"]), _f(D["late_fee"])))
    print("   springs %s | y1 stub at +200bp %.4f | part-held runs %d, the first %s"
          % (" / ".join(str(s) for s in D["springs"]), D["stub"], len(D["held"]), D["held"][0][0]))

    H = handoff(bb, L, P["cogs"])
    print("")
    print("GROUP 10 INHERITANCE  (the y1 amendment, then the collateral ceiling)")
    print("   shortfall against the line     %s" % _f(H["short"]))
    print("   what binds                     %s" % " / ".join(H["binds"]))
    print("   peak need less the base        %s   (negative = collateral to spare)" % _f(H["vs_base"]))
    print("   DPO stretch that funds it      %s days  -> DPO %d becomes %s"
          % (_f(H["dpo_days"], 2), DPO, _f(H["dpo_to"], 1)))
    print("   one semi-monthly AP run        %s   (y1 shortfall is %.1f%% of one run, %.2f days of invoicing)"
          % (_f(H["ap_run"]), 100 * H["short"][0] / H["ap_run"][0], H["short"][0] / (GROSS[0] / 365)))
    print("   springing trigger y1 / from the Q1 y2 upsize   %.2f / %.2f" % (L["trigger"][0], L["trigger"][1]))

    if "--bands" in sys.argv:
        print("\nBANDS")
        for lbl, kw in (("D0 0.5", dict(d0=0.5)), ("D0 1.0", dict(d0=1.0)), ("D0 1.5", dict(d0=1.5)),
                        ("capex 0.15", dict(capex=0.15)), ("capex 0.45", dict(capex=0.45)),
                        ("distributions 0", dict(distrib=0.0))):
            q = ledger(P["ebitda"], wc, bb, **kw)
            print("   %-18s y3 gap %+6.2f | springs y%-4s | FCCR %s" %
                  (lbl, q["avail"][2], q["spring"], _f(q["fccr"], 2)))
        for lbl, kw in (("over-settle 8%", dict(oversettle=0.08)), ("over-settle 15%", dict(oversettle=0.15)),
                        ("ask 1/2, give 50%", dict(ask=[0, 0.01, 0.02], giveback=0.50)),
                        ("ask 3/4, give 30%", dict(ask=[0, 0.03, 0.04], giveback=0.30))):
            p2 = pnl(**kw)
            w2 = working_capital(p2["cogs"])
            b2 = borrowing_base(w2)
            q = ledger(p2["ebitda"], w2, b2)
            print("   %-18s y3 gap %+6.2f | springs y%-4s | EBITDA %s" %
                  (lbl, q["avail"][2], q["spring"], _f(p2["ebitda"])))


if __name__ == "__main__":
    main()
