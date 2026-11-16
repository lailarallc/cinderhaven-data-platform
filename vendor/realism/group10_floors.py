#!/usr/bin/env python3
"""The generator for group 10 - survivability floors, tolerances, consequence chains.

WHY THIS EXISTS
---------------
Group 10 is consolidation. Almost nothing here is a new magnitude: the floors,
the fine rates, the performance means and the cadences are all registered in
groups 4, 5, 7 and 9, and group 10's job is to say what happens when they are
crossed. A row that says "a consequence follows" without a count is the shape
group 9 published four times and retracted four times. So every count below is
computed, and the handful of genuinely free inputs are listed in INPUTS where
they can be counted rather than buried.

The first thing it does is REPRODUCE A5.17. That row states the share of months
Walmart's scorecard falls below target, and it is derivable from A5.11's annual
means, A5.17's own dispersion parameters and A5.16's effective-dated targets.
Reproducing it is how we know the model underneath A10.03 and A10.08 is the one
the package already committed to, rather than a second model with the same shape.

    python scripts/group10_floors.py            # the report
    python scripts/group10_floors.py --checks    # adds the cross-checks to other groups
"""
import calendar
import itertools
import math
import os
import random
import sys
from datetime import date, timedelta
from fractions import Fraction
from statistics import NormalDist

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import group9_ledger as G  # noqa: E402

NORM = NormalDist()

# ---------------------------------------------------------------- registered rows
GROSS = G.GROSS                       # A1.01 ladder, via group 9: one transcription, not two (U4). This module typed its
                                      # own 46.719 beside group 9's until the exact 46.71875 landed (owner, 2026-09-25)
S_DTC = 0.10                         # A8.01
# A5.38, as FRACTIONS of wholesale. NOT a second copy: group 9 holds the one transcription of the
# registry row and this derives from it (ruled 2026-09-17). The two had diverged - this module still
# carried KeHE 8/7.5/7 and DPI 2/2/2, the mix from before the owner registered KeHE's acquisition of
# DPI on 2026-09-15 - and nothing caught it, because both copies summed to 100 in every year and the
# gate's cross-check asks whether the ROWS match the GENERATOR, never whether the generator matches
# the registry (FAILURES 2026-09-17). check_anchors.py now checks that mirror directly.
SHARE = dict((k, [x / 100.0 for x in v]) for k, v in G.SHARE.items())   # A5.38, via group 9

ONTIME = [87.0, 84.5, 82.0]           # A5.11, y2 the midpoint per A5.17
A512_Y1 = dict(rr=3.0, cr=2.0, ff=3.5)    # A5.12 y1, % of original units: retailer and Cinderhaven reductions,
                                          # fill failure
A512_Y3 = dict(rr=4.0, cr=3.5, ff=5.5)    # A5.12 y3, the same three

# A5.12's fifth term, retailer_increase (owner, 2026-10-06), is NOT pinned: it is sized as a ratio to its pinned
# sibling rr on registered rows alone, against what rr holds - the retailer's cuts at A5.04's median depth and its
# line and order cancels at full depth - with the initiator split from A5.03 (DECISIONS#retailer-increase).
A508_MIX = dict(cut=45, date_change=30, increase=10, cancel_line=10, cancel_order=5)   # A5.08, % of revision rows
A503_RETAILER = (65, 55)              # A5.03, the retailer's % of revisions, y1 / y3
A503_ORDER_CANCEL_RETAILER = 70       # A5.03, the retailer's % of whole-order cancels
CUT_DEPTH = (0.10, 0.25, 0.50)        # A5.04, low / median / high
A504_INCREASE = (20, 50)              # A5.04, an increase as % of the line, low / high


def _a512_ri(rr, y):
    """retailer_increase, % of original units, EXACT: rr x (increase units / retailer-reduction units per revision
    row). Every increase is the retailer's (A5.10 has no Cinderhaven increase code); each row weighs one line's
    units_before; the retailer's share of the other line-level rows is what A5.03's share leaves after its increases
    and order cancels; date changes move no units."""
    m = dict((k, Fraction(v)) for k, v in A508_MIX.items())
    order = m["cancel_order"] * Fraction(A503_ORDER_CANCEL_RETAILER, 100)
    other = (A503_RETAILER[y] - m["increase"] - order) / (m["cut"] + m["date_change"] + m["cancel_line"])
    up = m["increase"] * Fraction(sum(A504_INCREASE), 2) / 100
    down = other * (m["cut"] * Fraction(str(CUT_DEPTH[1])) + m["cancel_line"]) + order
    return Fraction(str(rr)) * up / down


A512_Y1["ri"] = _a512_ri(A512_Y1["rr"], 0)   # 84/131, 0.641%
A512_Y3["ri"] = _a512_ri(A512_Y3["rr"], 1)   # 112/111, 1.009%


def _a512_fill(c):
    """A5.12's two per-line fill metrics on its components, EXACT, in %: internal fill = 1 - ff / (100 - rr - cr + ri),
    retailer-scored in-full = 1 - (cr + ff) / (100 - rr + ri). The retailer's increases raise both bases."""
    rr, cr, ff = (Fraction(str(c[k])) for k in ("rr", "cr", "ff"))
    ri = c["ri"]
    return 100 * (1 - ff / (100 - rr - cr + ri)), 100 * (1 - (cr + ff) / (100 - rr + ri))


# A5.11's internal fill and retailer-scored in-full DERIVE from A5.12's endpoints, exactly, and y2 is their midpoint
# per A5.17 (owner, 2026-09-25: exact wins). Typed until U4 as A5.11's one-decimal prints, 96.3 / 95.2 / 94.1 and
# 94.3 / 92.45 / 90.6; y1's in-full is 9150/97 and does not terminate, so only a computed value is exact.
_A512 = (_a512_fill(A512_Y1), _a512_fill(A512_Y3))
A511_INTERNAL = [float(_A512[0][0]), float((_A512[0][0] + _A512[1][0]) / 2), float(_A512[1][0])]
INFULL = [float(_A512[0][1]), float((_A512[0][1] + _A512[1][1]) / 2), float(_A512[1][1])]
SD_INFULL, SD_ONTIME = 2.5, 4.0       # A5.17 monthly dispersion, practitioner

# A5.16, effective-dated: 98/98 to 2024-02-29, then in-full 95 / prepaid on-time 90.
# The window is calendar (A9.03), so y2 blends 2 months old / 10 months new -- counted from the date, never typed.
A516_EFFECTIVE = "2024-03-01"
MONTHS_IN_YEAR = 12                   # mirror-exempt: a calendar constant, the months in a year, not a figure
_Y2_OLD_MONTHS = int(A516_EFFECTIVE[5:7]) - 1
TARGETS = [  # A5.16: (months, in-full target, on-time target) per window year
    [(MONTHS_IN_YEAR, 98.0, 98.0)],
    [(_Y2_OLD_MONTHS, 98.0, 98.0), (MONTHS_IN_YEAR - _Y2_OLD_MONTHS, 95.0, 90.0)],
    [(MONTHS_IN_YEAR, 95.0, 90.0)],
]
WM_FINE = 0.03                        # A5.16, 3% of non-compliant case value
FINE_SHORT = {"UNFI": 0.02, "KeHE": 0.03, "Costco": 0.03}   # A5.15, % of shorted value
KROGER_PER_DAY = 500.0                # A5.15, $ per day past a 2-day window
REGIONAL_LATE = (100.0, 250.0)        # A5.15, $ per late PO
POS = {"Walmart": [416, 572, 832], "Kroger": [156, 156, 156], "WF": [78, 78, 78],
       "Sprouts": [0, 52, 52], "Regional": [104, 104, 104], "Costco": [0, 0, 36],
       "UNFI": [260, 260, 260], "KeHE": [208, 260, 260], "DPI": [26, 0, 0],
       "small": [int(round(G.small_orders(y))) for y in range(3)]}   # A5.02; DPI ends after y1 with its A5.38
                                      # line (owner, 2026-09-15, item 5), and the small tier's count now DERIVES
                                      # from its dollars over a Faire-typical order (item 7), replacing 120. Walmart's
                                      # y3 is A5.32's 16 DCs weekly and KeHE's fifth DC orders weekly from y2 (U4):
                                      # 728 and 208 were on 14 and 4 DCs, left behind when A5.32 moved on 2026-09-24
A537_LINES = {"Walmart": 8, "Kroger": 10, "WF": 12, "Sprouts": 10, "Regional": 8, "Costco": 2, "UNFI": 16,
              "KeHE": 14, "DPI": 10, "small": 4}   # A5.37: mean lines per PO by account
A513_SPLIT = 0.08                     # A5.13: share of POs shipped in two at the distributors, the natural accounts
A513_SPLIT_ACCOUNTS = ("UNFI", "KeHE", "DPI", "WF", "Sprouts", "Regional")   # and Regional: A5.13's split accounts
A110_RETAILERS = ("Walmart", "Kroger", "WF", "Regional", "Sprouts", "Costco")   # A1.10's retailer roster, and the
A110_DISTRIBUTORS = ("UNFI", "KeHE", "DPI")                                      # distributors beside it (A5.20)
DCS = {"UNFI": 5, "KeHE": [4, 5, 5], "Costco": 4, "Kroger": 6, "WF": 3, "Sprouts": 2,
       "Regional": 2, "DPI": [1, 0, 0]}   # A5.32. KeHE ABSORBS THE BRAND'S DPI SHIP-TO POINT from y2 - a READING of
                                      # "A5.32 follows" (item 5): KeHE closed on DPI on 2023-06-20 and its own
                                      # locations page carries Tualatin, which was DPI's, so the volume ships to the
                                      # same building under a new name and the count of ship-to points is conserved


def dcs(d, y):
    """A5.32's ship-to points for an account in window year y. Most are flat; KeHE's and DPI's move when
    KeHE absorbs DPI, so a value may be a per-year list."""
    v = DCS[d]
    return v[y] if isinstance(v, (list, tuple)) else v
WM_DCS = [8, 11, 16]                  # A5.32; y3 16 (owner, 2026-09-24): Walmart runs ~110 stores a DC, so <=145
STOCKOUT = [0.04, 0.055, 0.07]         # A5.21, share of SKU-weeks; y2 the midpoint
SKUS = 39                             # A2.01 restated 2026-09-12: 39 at window start, club
                                      # packs created with Costco's y3 acceptance
CLUB_ACCEPTED = 2                     # A7.26 Costco rotation, from Q2 y3
ACTIVE_SKUS = [39, 39, 41]            # A10.08: the catalogue actually live, by window year
VELOCITY_INDEX = [85.0, 77.5, 70.0]   # A7.12 grocery and mass, y2 the midpoint
VELOCITY_FLOOR = {"Kroger": 60.0, "WF": 50.0, "Sprouts": 55.0}   # A7.12, % of category avg
OPDED = [0.045, 0.0525, 0.060]        # A4.01
# A4.31, DERIVED from 2026-10-19 (owner, DECISIONS#u18-rulings Q6): invalid trade claims as a share of billback and
# MCB dollars are A4.18's phantom and double-funded events at their band midpoints, dollar-weighted as events, plus
# A4.33's wrong-rate billbacks, each overbilling by A4.13's spread between the billed and the authorized rate type.
# It was an asserted 6% (0.54% of gross), which A4.18's own midpoints already exceeded.
A418_PHANTOM = (0.03, 0.06)           # A4.18: phantom promotions, share of events
A418_DOUBLE = (0.02, 0.04)            # A4.18: double-funding, share of events
A413_BILLBACK = (0.10, 0.20)          # A4.13: billback rate on promoted units, the billed type
A413_MCB = (0.10, 0.15)               # A4.13: MCB rate via distributors on promoted units, the authorized type
WRONG_RATE = 0.02                     # A4.33: share of billbacks billed at a rate type other than the authorized one
INVALID_SHARE = (sum(A418_PHANTOM) / 2 + sum(A418_DOUBLE) / 2
                 + WRONG_RATE * (sum(A413_BILLBACK) - sum(A413_MCB)) / sum(A413_MCB))
INVALID_TRADE = INVALID_SHARE * G.BILLBACK_MCB   # A4.31's invalid share of gross, per A4.08's pool
A405_OTIF_SHARE = 0.05                # A4.05, late/OTIF share AFTER the 2026-09-12 rebalance
# SIGMA_VELOCITY -- A10.16's catalogue multiplier, read from A7.03's distribution: the spread WITHIN a carried set
# (ruled 2026-09-14) -- is DERIVED at the foot of this module, from A7.03's EXACT y3 velocity (owner, 2026-09-22):
# scan_identity() has to exist before it can be read. It was a literal 0.953, solved from a rounded 2.94.
# A7.03's spread is measured over DOOR-SKU-WEEKS, so it pools store and week variation with the SKU's own
# (owner, 2026-09-15, ruling 3). An account review reads account-averaged velocity, where both average out:
#     sigma_total^2 = catalogue + SKU x account + door + week
# The door and week components are owner-signed on scanner-data plausibility; the account factor derives
# against what is left. SIGMA_ACCOUNT, derived with SIGMA_VELOCITY at the foot of the module, is the target the
# solve closes to - not the whole spread, which would attribute store and week noise to accounts.
SIGMA_DOOR = 0.55                     # A11.27, owner-signed 2026-09-15: band 0.50-0.60, midpoint taken
SIGMA_WEEK = 0.30                     # A11.28, owner-signed 2026-09-15: "about 0.3 log-sd"
SIGMA_DOOR_BAND = (0.50, 0.60)        # A11.27's signed band: printed as a sensitivity, not a range the solve
                                      # runs over


def account_target(door=SIGMA_DOOR, week=SIGMA_WEEK):
    """A7.03's spread less the door and week components: what a carried set spreads at the ACCOUNT."""
    return math.sqrt(SIGMA_VELOCITY ** 2 - door ** 2 - week ** 2)


A703_TOP_QUINTILE = 8.0               # A7.03: the top quintile's 6-10 u/s/w, its midpoint. The y3 MEAN beside it
                                      # is derived at the foot of the module, never transcribed (owner, 2026-09-22)
RUNS_A, RUNS_C = 10.0, 3.5            # A5.28, A items 8-12 runs/yr, C items 3-4
AUTH = {"Walmart": [6, 7, 8], "Kroger": [10, 11, 11], "WF": [14, 14, 15],
        "Regional": [8, 9, 10], "Sprouts": [12, 12, 12], "Costco": [2, 2, 2]}   # A7.26
LATE_MEAN = {"Walmart": 1.2, "Kroger": 1.5, "Regional": 2.5}   # A10.11: geometric mean days past each account's
                                      # window, owner-signed practitioner (2026-10-01; Kroger's 1.5 since 2026-09-12).
                                      # Walmart's MABD window is tight, so its mean is short; Regional's is loose.
                                      # Every other account takes Kroger's until a window is registered for it
LATE_CANCEL_DAYS = 5                  # A5.07: beyond this it is a cancel, not a fine -- at EVERY account (owner,
                                      # 2026-09-25), inside A5.07's 1.0% retailer cancellation rate
CASE_UNITS = 12                       # A2.05 pack
MAPE = [0.38, 0.415, 0.45]            # A5.25, Cinderhaven SKU-month, y2 the midpoint
WAL_MODULAR_QUINTILE = 0.20           # A7.12, bottom quintile of the modular at reset
TRIALS = 60000                        # mirror-exempt: the draw's sample size, not a figure; seeded, so it reproduces
SEED = 20260912                       # mirror-exempt: the RNG seed, not a figure

# A10.17, per-type mean deduction amount in dollars, owner-signed practitioner. THE BAND IS THE CHECK ON THE MEAN
# (owner, 2026-10-13, DECISIONS#u18-rulings): a signed mean must lie inside its own signed p10-p90. Seven do and are
# typed here; late/OTIF, pricing_error and overage did not (their signed $300, $900 and $400 are history in A10.17) and
# take their band's log-normal mean, computed below A1017_BAND as A1017_MEAN.
A1017_SIGNED = {"short_ship": 450, "damaged_unsaleables": 350,
                "spoilage_shortdated": 600, "receiving_miscount": 150,
                "label_pallet_asn": 250, "post_audit": 3000, "other": 400}
# A4.05's dollar shares after the 2026-09-12 rebalance.
A405_SHARE = {"short_ship": 26, "late_otif": 5, "damaged_unsaleables": 15,
              "spoilage_shortdated": 9, "receiving_miscount": 8, "label_pallet_asn": 10,
              "pricing_error": 11, "post_audit": 6, "overage": 1, "other": 9}
# A4.32, the three-bucket split WITHIN each A4.05 deduction type, as % of that type's dollars:
# b1 retailer error, b2 Cinderhaven-caused, b3 structural. Registered starting weights.
A432_WEIGHTS = {"short_ship": (5, 45, 50), "late_otif": (3, 57, 40), "damaged_unsaleables": (8, 22, 70),
                "spoilage_shortdated": (5, 40, 55), "receiving_miscount": (40, 20, 40),
                "label_pallet_asn": (3, 67, 30), "pricing_error": (35, 40, 25),
                "post_audit": (25, 25, 50), "overage": (20, 60, 20), "other": (10, 15, 75)}


def bucket_split():
    """A4.32: A4.05's type mix crossed with A4.32's within-type weights.

    Registered as a derived row 2026-09-17. It had carried '~12 / 38 / 50' over the operational pool
    and '~20 / 35 / 45' over the bucket pool with nothing computing either, which is the shape A4.09
    was found in - a derived row no generator emits is invisible to the gate (FAILURES 2026-09-17).

    OPERATIONAL is A4.05's pool, the types above. BUCKET adds A4.31's invalid trade claims, which are
    all bucket 1, on top; A4.31 is a share of GROSS and A4.01 is the operational pool as a share of
    gross, so the two combine at their registered y3 rates.
    """
    op = [sum(A405_SHARE[k] * A432_WEIGHTS[k][b] / 100.0 for k in A405_SHARE) for b in range(3)]
    inv = INVALID_TRADE / OPDED[2] * 100.0          # A4.31 as % of the operational pool, y3
    total = 100.0 + inv
    bucket = [(op[0] + inv) / total * 100.0, op[1] / total * 100.0, op[2] / total * 100.0]
    return dict(operational=op, bucket=bucket, invalid_pct_of_operational=inv)


def largest_remainder(shares, total):
    """A2.09's integer rule: proportions are targets, integers by largest-remainder rounding. ONE definition --
    A6.06's published mix and A2.09's catalogue counts both read it (group 11 aliases it).

    EXACT, NO FLOAT (owner, 2026-09-23: the exactness rule has no exception). Each share becomes the rational it
    was written as, so two remainders that are equal ARE equal, and an exact tie goes to the category listed
    first -- the stable sort's order, which the float version reached only where its rounding noise let it.
    """
    raw = dict((k, Fraction(str(v)) * total / 100) for k, v in shares.items())
    out = dict((k, math.floor(v)) for k, v in raw.items())
    for k in sorted(raw, key=lambda k: -(raw[k] - out[k]))[:total - sum(out.values())]:
        out[k] += 1
    return out


def within_bucket_mix():
    """A6.06: the within-bucket dollar mix of the OPERATIONAL pool, by deduction type.

    Registered as derived 2026-09-17, for the same reason as A4.32. Each type's contribution to a
    bucket is its A4.05 share times its A4.32 weight; the mix is those contributions normalised
    within the bucket. NOT asserted separately - a second decomposition would drift from the first,
    which is exactly what A4.32's own row says and what nothing was checking.
    """
    op = bucket_split()["operational"]
    out, ints = {}, {}
    for b, name in enumerate(("b1", "b2", "b3")):
        # exact: A4.05's shares and A4.32's weights are integers, so every contribution is a rational
        contrib = dict((k, Fraction(A405_SHARE[k] * A432_WEIGHTS[k][b], 100)) for k in A405_SHARE)
        exact = dict((k, v / sum(contrib.values()) * 100) for k, v in contrib.items())
        out[name] = dict((k, float(v)) for k, v in exact.items())
        # A2.09's integer rule, applied here too: proportions are the truth and the published
        # integers are largest-remainder rounded, so they sum to 100 rather than to 99 or 102.
        ints[name] = largest_remainder(exact, 100)
    return dict(mix=out, published=ints, pool_share=op)


A919_MEAN, A919_MEDIAN = 600.0, 360.0   # A9.19 as first registered, for the comparison. mirror-exempt: retired,
                                        # printed in A9.19's history beside the derived mean and median
A919_SIGMA_HELD = 1.0108                  # the sigma held until A10.17's bands existed; kept
                                          # only as the comparison the report prints. mirror-exempt: retired,
                                          # printed beside the current sigma as history (A9.19)

# A10.17 within-type bands, p10-p90, owner-signed. The ratio p90/p10 sets each type's sigma; each type's LOCATION is its
# signed mean where that mean lies inside the band. Until 2026-10-13 location never moved, and three signed means sat
# outside their own bands; a mean below its p10 or above its p90 is impossible for the log-normal the row claims, so
# those three take the band's log-normal mean (owner, 2026-10-13). Reading all ten bands as absolute stays rejected.
A1017_BAND = {"short_ship": (150, 1500), "late_otif": (400, 2500),
              "damaged_unsaleables": (150, 600), "spoilage_shortdated": (200, 800),
              "receiving_miscount": (50, 400), "label_pallet_asn": (250, 1500),
              "pricing_error": (150, 400), "post_audit": (1000, 8000),
              "overage": (50, 300), "other": (100, 2000)}
P10_P90_Z = 2 * 1.2815515655446004       # mirror-exempt: a normal z-distance, p10 to p90, a mathematical constant;
                                         # ln(p90/p10) = 2.563 sigma for a log-normal


def band_mean(k):
    """A10.17: the log-normal mean of type k's p10-p90 band, read as absolute: median at the geometric midpoint, sigma
    from the width, mean = median x exp(sigma^2 / 2)."""
    lo, hi = A1017_BAND[k]
    sg = math.log(hi / float(lo)) / P10_P90_Z
    return math.sqrt(lo * hi) * math.exp(sg * sg / 2.0)


A1017_MEAN = dict((k, A1017_SIGNED[k] if k in A1017_SIGNED else band_mean(k)) for k in A1017_BAND)
assert all(A1017_BAND[k][0] <= A1017_MEAN[k] <= A1017_BAND[k][1] for k in A1017_MEAN), "a mean outside its band"

# A10.18 rationalization inputs
LAUNCHES, LAUNCHES_PER_YEAR = 9, 3       # A7.09: 9 launches over the window, 3 a year
LAUNCHES_AFTER_Y1 = LAUNCHES - LAUNCHES_PER_YEAR   # y2 and y3's six, derived (A7.09)
RETAILERS_BAND = (2, 4)                   # A7.09: each launch authorized at 2-4 retailers
RETAILERS_PER_LAUNCH = tuple(range(RETAILERS_BAND[0], RETAILERS_BAND[1] + 1))   # every whole count in the band
AUTH_ALL = {"Walmart": [6, 7, 8], "Kroger": [10, 11, 11], "WF": [14, 14, 15],
            "Regional": [8, 9, 10], "Sprouts": [12, 12, 12], "Costco": [2, 2, 2],
            "independents": [6, 7, 7]}   # A7.26: its door-SKU totals, 33,136 / 47,075 / 61,021, put Whole
                                         # Foods' 15 and Regional's 10 in y3, so y2 carries 14 and 9
A906_DISPUTE_FTE = (0.45, 0.45, 0.50)   # A9.06: the clerk's dispute FTE by window year, the FTE DISPUTE_CAPACITY buys
DISPUTE_CAPACITY = [394.0, 394.0, 437.0]  # A9.06, disputes a year at A4.12's 1.5 h
DPO = 32                              # A9.11
SUPPLIER_TERMS = {"ingredients": 30, "glass": 45, "co-packers": 30}   # A9.11
COPACK_LARGER = 0.70                  # A5.30, share of co-packed volume
PROD_LEAD_WEEKS = (6, 8)              # A5.29, co-pack: a co-packer hold slips by it (owner, 2026-10-21,
                                      # DECISIONS#u16-lead-time; was the in-house 2-3 weeks)

# ------------------------------------------------------------------- free inputs
INPUTS = [
    ("A10.02 tolerance lines, nine rows", "target - 5 where only a target is published",
     "owner-signed; drop is A5.17's registered rule"),
    ("A10.05 clubs served across the four depots", "see CLUBS below", "owner-signed practitioner"),
    ("A10.05 sell-through thresholds", "75% by wk 10 tolerance, <60% drop", "owner-signed"),
    ("A10.06 commercial-viability floor", "1 case / DC / week over 13 weeks", "owner-signed"),
    ("A10.07 supplier day thresholds", "fee 30, priority 15, hold 45", "owner-signed"),
    ("Walmart on-time / in-full overlap", "INDEPENDENT", "owner-signed 2026-09-12 as the assumption"),
    ("Kroger days past the window", "geometric, mean 1.5, capped at A5.07's 5",
     "owner-signed 2026-09-12"),
    ("A10.16 velocity dispersion sigma", "derived from A7.03's exact y3 velocity and its top quintile: the catalogue "
     "multiplier", "ruled 2026-09-14: the spread within a carried set, the account factor carrying the rest; "
     "2026-09-22: from the exact mean, never the printed one"),
    ("A10.16 authorization rule", "forecast-ranked on A5.25's error, sticky",
     "registered in A10.16"),
]
CLUBS = 130                     # A10.05: clubs served across A5.32's 4 depots, owner practitioner
SELL_THROUGH = (0.75, 0.60)     # A10.05: Costco sell-through, tolerance by week 10, drop
VIABILITY_CASES = 1.0           # A10.06: cases / DC / week over 13 weeks
SUPPLIER_DAYS = (30, 15, 45)    # A10.07: late fee from, priority loss at, credit hold at


def sigma_from_mape(mape):
    """The forecast-noise sigma implied by A5.25's MAPE.

    MAPE is E|forecast/actual - 1|, so for a multiplicative log-normal error with
    no bias it pins sigma. A5.25's +8% systematic over-forecast is UNIFORM in this
    model and therefore ranking-neutral - it cannot move which SKUs are authorized.
    Its promoted-SKU differential (+10-15%) is not modelled and is flagged.
    """
    def mad(sg, n=4000):
        tot = 0.0
        for i in range(1, n):
            tot += abs(math.exp(sg * NORM.inv_cdf(i / float(n))) - 1.0)
        return tot / (n - 1)
    lo, hi = 0.01, 3.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if mad(mid) < mape:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def authorization_draw(sigma=None, trials=TRIALS):
    """A10.16's exits: authorize on FORECAST, measure the floor on ACTUAL.

    A retailer authorizes at item setup, before velocity exists, so it ranks on a
    forecast carrying A5.25's error; it measures actuals at review. Forecast noise
    therefore promotes some genuinely slow SKUs into the authorized set, and those
    are the ones that cross a floor in fact.

    AUTHORIZATION IS STICKY, which is the whole mechanism. A7.26's per-door counts
    GROW, so an item is authorized once and kept until a floor removes it - the
    delist risk concentrates on the SKUs added at review. Re-selecting the set each
    year instead makes the two-consecutive-review test almost never fire, because
    the noise that promoted a slow SKU is redrawn before the second strike; that
    was the first version of this function and it understated the exits eightfold.

    Two floors count toward the exits: A7.12's Kroger floor of 60% of category
    average, and Walmart's bottom quintile of the modular at reset. The second was
    missing from the earlier tally entirely.

    THE INDEX IS NORMALISED TO THE AUTHORIZED SET (ruled 2026-09-14): a SKU's index is
    the brand index times its multiplier over the mean multiplier of the set the account
    carries, so the carried items average the brand index, as A7.03's identity requires.
    The version before scaled by a multiplier whose mean of 1 ran over the whole catalogue
    while the account carried the top of it - a second count of the same units - and gave
    0.785 delists. A SKU's velocity at the account carries its account factor (owner,
    2026-09-14), which the retailer cannot forecast: it ranks on the catalogue velocity and
    measures the floor on velocity at the account.

    THE PRE-PERIOD'S REVIEW IS SIMULATED (owner, 2026-09-15, item 4): A10.16 takes the ruling the owner
    already applied to A10.09 and A10.06. The window used to open with every account's strike count at zero,
    so NOTHING could be removed before the second in-window review and every review on 1 January was a
    "first review" - the same start-up artifact the other two rows had retired. 2022 is now reviewed first,
    on y1's index and y1's authorized counts (the reading group 11 takes for the pre-period), STRIKES IN
    PROGRESS CARRY into y1, and the pre-period's own exits are reported separately: they shape the
    window-start authorized set, and they are NOT window exits, so they do not count toward R4 (item 2).

    WALMART REMOVES AT THE FIRST RESET, NOT THE SECOND (A7.12). The earlier version ran the two-consecutive
    test for both accounts; A7.12 gives Kroger's floor "two consecutive reviews" and Walmart's bottom
    quintile "at each reset", which is one strike. Group 11's launch rules already read it that way, so the
    two mechanisms disagreed about the same floor - recorded in group 11's findings and fixed here.
    """
    sigma = sigma or SIGMA_VELOCITY
    acct = account_sigma()
    sf = [sigma_from_mape(m) for m in MAPE]
    cut_mod = math.exp(math.log(100.0) - SIGMA_VELOCITY ** 2 / 2
                       + SIGMA_VELOCITY * NORM.inv_cdf(WAL_MODULAR_QUINTILE))   # the modular carries A7.03's within-set spread
    strikes_needed = {"Kroger": 2, "Walmart": 1}      # A7.12: two consecutive reviews / the quintile at reset
    rng = random.Random(SEED)
    out = {"Kroger": dict(below=[0.0] * 3, exits=0.0, pre_exits=0.0, carried=0.0, floor=VELOCITY_FLOOR["Kroger"]),
           "Walmart": dict(below=[0.0] * 3, exits=0.0, pre_exits=0.0, carried=0.0, floor=cut_mod)}
    for _ in range(trials):
        z = [rng.gauss(0, 1) for _ in range(SKUS)]
        v = [[math.exp(math.log(VELOCITY_INDEX[t]) - sigma ** 2 / 2 + sigma * zi) for zi in z]
             for t in range(3)]
        eps = dict((name, [math.exp(-acct * acct / 2 + acct * rng.gauss(0, 1)) for _ in range(SKUS)])
                   for name in ("Kroger", "Walmart"))
        for name in ("Kroger", "Walmart"):
            floor, need_strikes = out[name]["floor"], strikes_needed[name]
            auth, dead, strikes = set(), set(), {}
            for t in (-1, 0, 1, 2):                      # -1 is 2022, the pre-period, on y1's index and counts
                y = max(t, 0)
                need = AUTH[name][y] - len(auth)
                if need > 0:
                    avail = [i for i in range(SKUS) if i not in auth and i not in dead]
                    fc = sorted(avail, key=lambda i: -(v[y][i] * math.exp(rng.gauss(0, sf[y]))))
                    auth |= set(fc[:need])
                at = dict((i, v[y][i] * eps[name][i]) for i in auth)
                set_mean = sum(at.values()) / len(auth) / VELOCITY_INDEX[y]
                below = set(i for i in auth if at[i] / set_mean < floor)
                if t >= 0:
                    out[name]["below"][t] += len(below)
                for i in list(auth):
                    strikes[i] = strikes.get(i, 0) + 1 if i in below else 0
                    if strikes[i] >= need_strikes:
                        auth.discard(i)
                        dead.add(i)
                        out[name]["pre_exits" if t < 0 else "exits"] += 1
                if t < 0:
                    out[name]["carried"] += sum(1 for i in auth if strikes.get(i, 0))
    for name in out:
        out[name]["below"] = [x / trials for x in out[name]["below"]]
        for k in ("exits", "pre_exits", "carried"):
            out[name][k] /= trials
    out["sf"] = sf
    out["total_exits"] = out["Kroger"]["exits"] + out["Walmart"]["exits"]
    out["total_pre_exits"] = out["Kroger"]["pre_exits"] + out["Walmart"]["pre_exits"]
    out["total_carried"] = out["Kroger"]["carried"] + out["Walmart"]["carried"]
    return out


def deduction_amounts():
    """A10.17: counts by type from A4.05's shares over the per-type means.

    count_t = share_t / mean_t, so the OVERALL mean is 1 / sum(share_t / mean_t) and
    depends on the type MEANS alone - it is robust to whatever within-type bands are
    registered later. The MEDIAN and therefore sigma are NOT: point masses per type
    carry BETWEEN-type dispersion only, so the sigma below is a FLOOR.
    """
    assert sum(A405_SHARE.values()) == 100, sum(A405_SHARE.values())
    cnt = dict((k, A405_SHARE[k] / 100.0 / A1017_MEAN[k]) for k in A405_SHARE)
    total = sum(cnt.values())
    mean = 1.0 / total
    order = sorted(A405_SHARE, key=lambda k: A1017_MEAN[k])
    cum, median = 0.0, None
    for k in order:
        cum += cnt[k]
        if median is None and cum >= total / 2:
            median = float(A1017_MEAN[k])
    return dict(count=cnt, total=total, mean=mean, median=median, order=order,
                sigma=math.sqrt(2 * math.log(mean / median)))


def a1017_absolute_bands():
    """A10.17's REJECTED reading of its within-type bands as ABSOLUTE p10-p90 amounts, which the row and group 10's doc
    print beside the width reading they keep: each type's median at its band's geometric midpoint and its sigma from the
    band's width, so its mean is no longer the signed one; each type's count is A4.05's dollar share over that mean; the
    mixture's mean, median and equivalent sigma follow as deduction_mixture() takes them. A counterfactual printed
    beside a causal claim is a derived companion; moved here from the gate 2026-09-23."""
    parts, count = [], {}
    for k in A405_SHARE:
        lo, hi = A1017_BAND[k]
        mu, sg = (math.log(lo) + math.log(hi)) / 2.0, math.log(hi / float(lo)) / P10_P90_Z
        count[k] = A405_SHARE[k] / 100.0 / math.exp(mu + sg * sg / 2.0)
        parts.append((k, mu, sg, lo, hi))
    total = sum(count.values())
    parts = [(k, count[k] / total, mu, sg, lo, hi) for k, mu, sg, lo, hi in parts]
    mean = sum(A405_SHARE.values()) / 100.0 / total
    median = _mixture_quantile(parts, 0.5)
    return dict(mean=mean, median=median, sigma=math.sqrt(2.0 * math.log(mean / median)))


def deduction_mixture():
    """A10.17 with its within-type bands: the mixture's mean, median and sigma.

    Each type is log-normal with its SIGNED mean and a sigma from its band's width,
    weighted by its share of deduction COUNT. The mean is exact and unchanged by the
    bands. The median is solved on the mixture's CDF by bisection rather than drawn,
    so it carries no sampling noise and reproduces to the digit.
    """
    A = deduction_amounts()
    parts = []
    for k in A405_SHARE:
        lo, hi = A1017_BAND[k]
        sg = math.log(hi / float(lo)) / P10_P90_Z
        mu = math.log(A1017_MEAN[k]) - sg * sg / 2
        parts.append((k, A["count"][k] / A["total"], mu, sg, lo, hi))

    def cdf(x):
        return sum(w * NORM.cdf((math.log(x) - mu) / sg) for _, w, mu, sg, _, _ in parts)

    lo_x, hi_x = 1.0, 1e6
    for _ in range(200):
        mid = math.sqrt(lo_x * hi_x)
        if cdf(mid) < 0.5:
            lo_x = mid
        else:
            hi_x = mid
    median = math.sqrt(lo_x * hi_x)
    mean = sum(w * math.exp(mu + sg * sg / 2) for _, w, mu, sg, _, _ in parts)
    return dict(parts=parts, mean=mean, median=median,
                sigma=math.sqrt(2 * math.log(mean / median)))


# A4.02's three-bucket split, the two buckets that reach A4.09's write-off; A4.07's recovery on
# filed bucket-1 dollars, current and achievable; and A4.06's achievable dollar-weighted filing.
# filing_cascade wrote 0.20, 0.35, 0.5125 and 0.15 inline; the names are added here without
# changing its arithmetic, so A4.09 and A4.08 cannot drift apart. A6.15's prevention is no longer
# a constant here: prevention() derives it below (2026-09-18).
B1_SHARE, B2_SHARE = 0.20, 0.35           # A4.02
R1_CURRENT, B2_SETTLE = 0.5125, 0.15      # A4.07 current; A4.08 bucket-2 settlement
R1_ACHIEVABLE = 0.568                     # A4.07 achievable
F_ACHIEVABLE = 0.90                       # A4.06 achievable, dollar-weighted on bucket 1

# A6.26's type -> control mapping: % of each type's BUCKET-2 dollars a control could have caught.
# Bucket-1 dollars carry deduction_validation entirely and are not in this vector. A6.26's own row
# prints the mapping, and the gate reads it there against this table.
A626_MAP = {"short_ship": {"po_acknowledgment": 30, "none": 70},
            "late_otif": {"po_acknowledgment": 30, "edi_reconciliation": 20, "none": 50},
            "label_pallet_asn": {"edi_reconciliation": 60, "item_setup_preflight": 40},
            "damaged_unsaleables": {"receiving_audit": 30, "none": 70},
            "spoilage_shortdated": {"item_setup_preflight": 20, "receiving_audit": 20, "none": 60},
            "pricing_error": {"price_book_governance": 90, "three_way_match": 10},
            "receiving_miscount": {"receiving_audit": 100},
            "post_audit": {"three_way_match": 70, "price_book_governance": 30},
            "overage": {"po_acknowledgment": 50, "receiving_audit": 50},
            "other": {"none": 100}}
# A6.13's benchmark_detection_rate per bucket-2 control, dollar basis; `none` catches nothing.
A613_RATE = {"item_setup_preflight": 0.90, "edi_reconciliation": 0.90, "po_acknowledgment": 0.75,
             "receiving_audit": 0.65, "three_way_match": 0.85, "price_book_governance": 0.85, "none": 0.0}
# A6.31's reachable part of `none`: the types group 5's supply-side levers touch. Damaged and other
# are structural at any competence - no registered lever reaches them.
SOP_REACHABLE = ("short_ship", "late_otif", "spoilage_shortdated")
A511_WELL_RUN = dict(internal=98.5, on_time=95.0)   # A5.11's well-run internal fill and on-time
SPOILAGE_REMOVAL = 0.60                   # A6.31, practitioner: A5.21 registers no achievable


def coverage():
    """A6.26: bucket-2 dollars by the control that could have caught them.

    A6.06's UNROUNDED within-bucket mix crossed with A626_MAP; the shares sum to 100. Registered as
    a generator output 2026-09-18. The row had carried po_acknowledgment 13.8 ... none 41.9, computed
    on A4.05's mix before the rebalance of 2026-09-12, and batch 4's restatement of A6.06 on
    2026-09-17 left it behind in the same commit: A6.06 was watched and this row was not
    (DECISIONS#check-downstream-of-your-own-fix).
    """
    mix = within_bucket_mix()["mix"]["b2"]
    share, none_by = {}, {}
    for t, m in A626_MAP.items():
        assert sum(m.values()) == 100, (t, m)
        for c, w in m.items():
            share[c] = share.get(c, 0.0) + mix[t] * w / 100.0
        if "none" in m:
            none_by[t] = mix[t] * m["none"] / 100.0
    reachable = sum(none_by[t] for t in SOP_REACHABLE)
    return dict(share=share, none_by=none_by, reachable=reachable, structural=share["none"] - reachable)


def sop_lever():
    """A6.31: the part of A6.26's REACHABLE `none` dollars that group 5's well-run endpoints remove.

    Per type, from registered endpoints: short_ship from A5.11's well-run internal fill (the fill
    failure a 98.5% internal fill leaves on A5.12's units_current base, against A5.12's y3 fill
    failure), late/OTIF from A5.11's on-time (the late share at the well-run 95 against the y3 82),
    spoilage at the practitioner 0.60.
    """
    C = coverage()
    base = 100.0 - A512_Y3["rr"] - A512_Y3["cr"] + float(A512_Y3["ri"])
    removal = {"short_ship": 1 - (100.0 - A511_WELL_RUN["internal"]) * base / 100.0 / A512_Y3["ff"],
               "late_otif": 1 - (100.0 - A511_WELL_RUN["on_time"]) / (100.0 - ONTIME[2]),
               "spoilage_shortdated": SPOILAGE_REMOVAL}
    points = sum(C["none_by"][t] * removal[t] for t in SOP_REACHABLE)
    return dict(removal=removal, points=points, weighted=points / C["reachable"])


def prevention():
    """A6.15's two tiers, as fractions of bucket-2 dollars: controls-only is A6.26's shares times
    A6.13's rates; full adds A6.31's points. Replaces the constant 0.473 / 0.705 this module carried,
    which went stale with A6.26 (2026-09-18)."""
    C, S = coverage(), sop_lever()
    controls = sum(C["share"][c] * A613_RATE[c] for c in C["share"]) / 100.0
    return dict(controls=controls, full=controls + S["points"] / 100.0)


def well_run_pool():
    """A6.15: residual deductions at a well-run brand by bucket, % of gross, at y3.

    ON THE REGISTERED y3 BUCKET POOL, A4.01 + A4.31. The row computed on that pool rounded to 6.5, so
    its bucket 2 (2.275) disagreed with A4.09's on the same dollars (2.289); the owner ruled on
    2026-09-18 that one pool serves every row that reads it. Bucket 1 at A4.06's achievable filing on
    A4.07's achievable recovery; bucket 2 cut by each tier's prevention; bucket 3 held, because A4.02
    defines it as structural and no registered mechanism reduces it.
    """
    pool = (OPDED[2] + INVALID_TRADE) * 100.0
    cur = [B1_SHARE * pool, B2_SHARE * pool, (1 - B1_SHARE - B2_SHARE) * pool]
    P = prevention()
    b1 = cur[0] * (1 - F_ACHIEVABLE * R1_ACHIEVABLE)
    b2 = dict((k, cur[1] * (1 - p)) for k, p in P.items())
    total = dict((k, b1 + b2[k] + cur[2]) for k in P)
    return dict(pool=pool, current=cur, b1=b1, b2=b2, total=total, prevention=P,
                b2_share=dict((k, b2[k] / total[k] * 100.0) for k in P))


def _mixture_cdf(parts, x):
    lx = math.log(x)
    return sum(w * NORM.cdf((lx - mu) / sg) for _, w, mu, sg, _, _ in parts)


def _mixture_quantile(parts, p):
    """x with mixture CDF(x) = p, bisected in log space -- deduction_mixture's own shape."""
    lo, hi = 1.0, 1e7
    for _ in range(200):
        mid = math.sqrt(lo * hi)
        if _mixture_cdf(parts, mid) < p:
            lo = mid
        else:
            hi = mid
    return math.sqrt(lo * hi)


def top_dollar_share(q, M=None):
    """Dollar share held by the TOP q fraction BY COUNT of A10.17's amount MIXTURE.

    RULED 2026-09-21, DECISIONS#A9.19-is-a-mixture. The retired form was
    `Phi(sigma - Phi^-1(1 - q))`, the Lorenz share of a SINGLE log-normal, evaluated at
    deduction_mixture()'s EQUIVALENT sigma -- back-solved from `sqrt(2 ln(mean / median))`,
    an identity exact for one log-normal and a SURROGATE for a mixture. A10.17's amounts are
    ten per-type log-normals, and the mean-median-matched single carries the LIGHTER upper
    tail, so it understated concentration by more the deeper into the tail it reached:
    -1.9 / -3.0 / -3.6% relative at the filed q. A9.19's sigma stays a published SUMMARY
    STATISTIC of the mixture and is no longer an input to this curve.

    Exact, not drawn: solve the mixture CDF for the count cut, then sum each part's mean
    above it by weight, since E[X 1{X > x}] = exp(mu + sg^2/2) * (1 - Phi((ln x - mu - sg^2) / sg)).
    A 400,000-draw simulation of the mixture agrees to four decimals; the check carries it
    (check_anchors.check_closed_forms).
    """
    M = M or deduction_mixture()
    lx = math.log(_mixture_quantile(M["parts"], 1 - q))
    return sum(w * math.exp(mu + sg * sg / 2) * (1 - NORM.cdf((lx - mu - sg * sg) / sg))
               for _, w, mu, sg, _, _ in M["parts"]) / M["mean"]


def filing_cascade(sigma=None):
    """A9.06's rates and A4.08's current recovery, from the mean and A10.17's MIXTURE.

    `sigma` selects the RETIRED single-log-normal reading of the same amounts, and exists
    for the one caller that prints what the ruling moved. None -- the default, and what
    every consumer takes -- is the registered model.
    """
    mean = deduction_amounts()["mean"]
    cnt = [pool(t) * 1e6 / mean for t in range(3)]
    by_count = [DISPUTE_CAPACITY[t] / cnt[t] for t in range(3)]
    M = deduction_mixture()
    by_dollar = [top_dollar_share(q, M) if sigma is None
                 else NORM.cdf(sigma - NORM.inv_cdf(1 - q)) for q in by_count]
    current = [0.20 * d * 0.5125 + 0.35 * d * 0.15 for d in by_dollar]
    return dict(count=cnt, by_count=by_count, by_dollar=by_dollar, current=current)



def fte_for_count_rate(rate=0.25):
    """A4.06: the dispute FTE a count filing rate needs on A9.06's capacity -- the rate over the rate the capacity files,
    times the FTE that files it. 25% is the vendor band's midpoint A4.06 tests. Moved here from the gate 2026-09-23 (owner:
    "a gate that computes figures is a second generator")."""
    fc = filing_cascade()
    return [rate / fc["by_count"][t] * A906_DISPUTE_FTE[t] for t in range(3)]

def write_off(sigma=None):
    """A4.09: write-off = UNRECOVERED BUCKET 1 + ALL OF BUCKET 2, as a share of gross.

    Registered 2026-09-17 as a derived row after the signing sitting found its one number stale.
    The row had carried a recovered bucket-1 share of 0.31, which implies a dollar filing rate of
    60.5% - the retired first-draft figure A4.06 itself calls "asserted, none of them derived". It
    never followed A4.08's restatement of 2026-09-12, and nothing caught it because A4.09 is a
    two_endpoint row that no generator emitted, so the gate could not see it (FAILURES 2026-09-17).

    CURRENT reads A4.06's derived dollar filing rate through A4.07's recovery, which is the same
    path A4.08's current takes, so the two cannot drift. ACHIEVABLE takes A4.08's achievable pair
    the same way: bucket 1 at A4.06's 90% filing on A4.07's 0.568, and bucket 2 reduced by A6.15's
    prevention rather than recovered - prevented dollars never arise, so they never write off.
    """
    f = filing_cascade(sigma)["by_dollar"]
    share = [OPDED[t] + INVALID_TRADE for t in range(3)]          # A4.01 + A4.31, of gross
    recovered_b1 = [f[t] * R1_CURRENT for t in range(3)]
    current = [share[t] * (B1_SHARE * (1 - recovered_b1[t]) + B2_SHARE) for t in range(3)]
    ach_b1 = B1_SHARE * (1 - F_ACHIEVABLE * R1_ACHIEVABLE)
    achievable = dict((k, share[2] * (ach_b1 + B2_SHARE * (1 - p))) for k, p in prevention().items())
    return dict(current=current, achievable=achievable, pool_share=share, recovered_b1=recovered_b1,
                retired_recovered_b1=0.31)


def recovery(sigma=None):
    """A4.08: recovered per bucket-pool dollar, both endpoints on one base, and the y3 deltas.

    CURRENT is filing_cascade's. ACHIEVABLE is bucket 1 at A4.06's achievable filing on A4.07's
    achievable recovery plus bucket 2 at A6.15's prevention - the terms write_off() takes away, so
    recovered plus written off is buckets 1 and 2 in both states. The deltas are priced on the y3
    bucket pool, A4.01 + A4.31, at A1.01's y3 gross. Registered 2026-09-18: the achievable pair and
    the deltas were carried in prose with nothing computing them.
    """
    cur = filing_cascade(sigma)["current"]
    ach = dict((k, B1_SHARE * F_ACHIEVABLE * R1_ACHIEVABLE + B2_SHARE * p) for k, p in prevention().items())
    share = OPDED[2] + INVALID_TRADE
    delta = dict((k, ach[k] - cur[2]) for k in ach)
    return dict(current=cur, achievable=ach, delta=delta, pool_usd=share * GROSS[2],
                delta_usd=dict((k, delta[k] * share * GROSS[2]) for k in ach),
                delta_pct=dict((k, delta[k] * share * 100.0) for k in ach))


def rationalization():
    """A10.18: one-in-one-out at the account, and why it is not the product gate.

    A new authorization at review takes a slot; the retailer frees one by cutting the
    brand's lowest-velocity-index authorized item unless the account's net count
    grows. So account-level cuts = gross new authorizations - net growth.

    THE LEVEL IS THE FINDING. R4's gate ("6 launches, 3 exits") sits on
    product_master_history and feeds the sku-rationalization DiD: it counts a SKU
    leaving the CATALOGUE. A rationalization cut at one account, or a velocity-floor
    delist, removes a SKU from ONE shelf and ends its scans only if it was the last
    one. Summing account-level cuts with product-level exits counts one SKU's exit at
    two levels.
    """
    net = sum(v[2] - v[0] for v in AUTH_ALL.values())
    rows = []
    for r in RETAILERS_PER_LAUNCH:
        gross = LAUNCHES_AFTER_Y1 * r
        rows.append(dict(per_launch=r, gross=gross, cuts=max(0, gross - net)))
    return dict(net=net, rows=rows)


def sigma_from_a703():
    """A10.16's sigma, read from A7.03's registered distribution.

    A7.03 states the SKU velocity distribution directly: log-normal around its y3 mean (the EXACT figure,
    derived by scan_identity() -- a printed 2.94 carried a rounding into every draw until 2026-09-22)
    u/s/w mean in y3 with a top quintile of 6-10. The top-quintile mean of a
    log-normal with arithmetic mean m is m * Phi(sigma - z_0.8) / 0.2, so the
    quintile's midpoint of 8 pins sigma with nothing else. It reproduces A7.03's
    tail band as a check: the bottom quintile comes out inside 0.3-0.8; A10.16 prints the figure, and the gate watches it there.

    WHY NOT THE CADENCE. The first version derived sigma from A5.28's run cadence,
    which A5.29's minimum economic run CENSORS: a slow SKU is held to a few runs a
    year however little it sells, so cadence compresses velocity at exactly the tail
    this row exists to size. That gave 0.4784 and an 8.5x top-to-bottom spread,
    which fails A2.10's own >=10x gate.
    """
    z = NORM.inv_cdf(0.8)
    lo, hi = 0.01, 4.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if A703_MEAN_Y3 * NORM.cdf(mid - z) / 0.2 < A703_TOP_QUINTILE:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


FORMAL_REVIEW = ["Walmart", "Kroger", "WF", "Sprouts", "Costco"]   # take launches, one-in-one-out
RANGE_EXTENSION = ["Regional", "independents"]                     # add on a pitch, no slot freed
LAUNCH_K = 3                                                        # A10.18: owner-signed, band 2-4
# REVIEWS_PER_YEAR is DELETED (owner, 2026-10-01): nothing read it. Kroger reviews twice a year (A7.10, in words), but
# only the annual category review runs A7.12's 60% floor, which is the one review authorization_draw() runs; the
# mid-year is a line review that adds and trims and registers no delist rule.


def rationalization_by_account(k=LAUNCH_K):
    """A10.18 per account: launches go to the top-k FORMAL-REVIEW accounts by revenue.

    A launch is pitched at every account's next review and authorized at the top-k
    formal-review accounts by A5.38 revenue rank; WF and UNFI are one natural leg.
    Accounts without formal line reviews - Regional, the distributor-served
    independents - grow by RANGE EXTENSION: existing SKUs added on a broker pitch with
    no slot to free, so A7.26's growth there creates no cut.
    """
    share = dict((a, SHARE[a]) for a in FORMAL_REVIEW)
    out = {}
    for y in (1, 2):
        ranked = sorted(FORMAL_REVIEW, key=lambda a: -(share[a][y] + (SHARE["UNFI"][y] if a == "WF" else 0)))
        for a in FORMAL_REVIEW:
            out.setdefault(a, [0, 0])
            if a in ranked[:k]:
                out[a][y - 1] += LAUNCHES_AFTER_Y1 // 2
    rows = {}
    for a in FORMAL_REVIEW:
        adds = out[a]
        net = [AUTH_ALL[a][1] - AUTH_ALL[a][0], AUTH_ALL[a][2] - AUTH_ALL[a][1]]
        cuts = [max(0, adds[i] - net[i]) for i in range(2)]
        rows[a] = dict(adds=adds, net=net, cuts=cuts, total=sum(cuts))
    for a in RANGE_EXTENSION:
        net = [AUTH_ALL[a][1] - AUTH_ALL[a][0], AUTH_ALL[a][2] - AUTH_ALL[a][1]]
        rows[a] = dict(adds=[0, 0], net=net, cuts=[0, 0], total=0)
    return rows


# ---------------------------------------------------------------- the catalogue, on group 2's recipes
# A2.01, group 2's line table: 20 recipes, 39 non-club sizes.
# A5.28 runs a recipe's 1-3 sizes as one campaign with size
# changeovers only, so A5.29's minimum economic run binds the RECIPE, not each size (ruled 2026-09-14).
RECIPES = ([("sauce", 2, "in")] * 6 + [("condiment jar", 2, "in")] * 2 + [("condiment tub", 2, "in")] * 2
           + [("oil", 2, "in"), ("honey", 2, "in"), ("maple", 2, "in"), ("spice", 1, "co")]
           + [("dried", 2, "co")] * 3 + [("snack", 2, "co")] * 3)          # (recipe, non-club sizes, mode)
SIZE_SLOTS = [(r, mode) for r, (_, sizes, mode) in enumerate(RECIPES) for _ in range(sizes)]   # the 39 sizes
NONCLUB_MODE = [mode for _, mode in SIZE_SLOTS]   # group 2: 26 in-house, 13 co-packed
CLUB_RECIPE = [0, 1, 2, 3, 4, 5, 6, 10, 17, 18, 19]   # mirror-exempt: indices into RECIPES, not figures. A2.04's
                                                      # designs on their recipes: six sauce twins, the condiment twin
                                                      # on a jar recipe, the oil, three snack 12-counts
CLUB_DESIGN_MODE = [RECIPES[r][2] for r in CLUB_RECIPE]   # A2.04: eleven club designs incl. the 33.8 fl oz oil;
                                                          # only the ones an account accepts exist. DERIVED from
                                                          # the recipes' modes (2026-09-28): it was typed as
                                                          # ["in"] * 8 + ["co"] * 3, and A2.04 prints no 8
# Group 2's line table, recipe kind by line (A2.01, A2.03). RECIPES names each recipe's kind but not its line, and A2.01's
# Test A reads lines. The gate mirrors this map against the doc's table. Moved here from the gate 2026-09-23.
A201_LINE = {"sauce": "Artisan Sauces", "condiment jar": "Specialty Condiments", "condiment tub": "Specialty Condiments",
             "oil": "Pantry Staples", "honey": "Pantry Staples", "maple": "Pantry Staples", "spice": "Pantry Staples",
             "dried": "Dried Goods", "snack": "Snack Bites"}


def test_a_rate():
    """A2.01's PPA Test A at window end, on the LADDER reading (owner, 2026-09-23): Costco accepts CLUB_ACCEPTED of the
    club designs, every set equally likely (the club forecasts are drawn i.i.d.), and the test passes when the set
    spans two lines. Counted over combinations, so a third accepted design moves the rate. Closed form, exact."""
    lines = [A201_LINE[RECIPES[r][0]] for r in CLUB_RECIPE]
    sets = list(itertools.combinations(range(len(lines)), CLUB_ACCEPTED))
    spans = sum(1 for c in sets if len(set(lines[i] for i in c)) >= 2)
    return dict(sets=len(sets), spans=spans, pass_pct=100.0 * spans / len(sets),
                fail_pct=100.0 * (len(sets) - spans) / len(sets))


RUN_FLOOR = {"in": 2 * 2000, "co": 2 * 5000}   # A5.29, two minimum economic runs a year, per recipe
# A7.04's AUTHORIZED doors carrying the brand -- ONE transcription (there were two, RETAIL_DOORS and A704_DOORS,
# with nothing comparing them). GROWN 2026-09-22 (owner, the level ruling, DECISIONS#A7.04-door-plan): the dollars
# A1.01 fixes put the measured velocity above three registered anchors, A7.28's share cannot close the gap at any
# value, so the doors were understated. The plan is the SMALLEST WHOLE-DOOR PLAN grown from the 2026-09-05 one
# that brings A7.03's y3 mean to A5.28's cadence floor, Sprouts capped at its 440-store universe and Costco (not
# measured) unchanged. CORRECTED 2026-09-22 (DECISIONS#A7.04-exact-integer-search): the rule had been written as
# "the smallest single FACTOR, each count rounded up", and no such factor exists -- two y3 lines need f > 9/8 and
# seven lines need f <= 9/8. The registered plan lived only inside math.ceil(d * f - 1e-9). The plan is found by
# exact integer search over the breakpoints n/d, no tolerance anywhere; the gate re-solves it the same way. The
# floor is a y3 constraint, so y1 and y2 are carried by the one growth step and are not minimised on their own.
A704_BASE = {"Walmart": [900, 1400, 2000], "Kroger": [1100, 1150, 1200], "WF": [400, 420, 450],
             "Regional": [80, 85, 90], "Sprouts": [0, 200, 400], "Costco": [0, 0, 60],
             "independents": [1400, 1800, 2200]}          # the 2026-09-05 plan the ruling scales
A704_UNIVERSE = {"Walmart": 3559, "Kroger": 2722, "WF": 535, "Sprouts": 440, "Costco": 614}   # A7.04's filed store
                                      # counts; Costco's 614 U.S. + PR warehouses read since U4 for its %ACV (not grown)
A704_SCALED = ("Walmart", "Kroger", "WF", "Regional", "Sprouts", "independents")
A704_DOORS = {"Walmart": [961, 1494, 2134],   # A7.04: authorized doors by banner, y1 / y2 / y3
               "Kroger": [1174, 1227, 1281], "WF": [427, 449, 481],
              "Regional": [86, 91, 97], "Sprouts": [0, 214, 427], "Costco": [0, 0, 60],
              "independents": [1494, 1921, 2347]}
RETAIL_DOORS = dict((k, A704_DOORS[k]) for k in ("Walmart", "Kroger", "WF", "Sprouts", "Costco", "Regional"))
CLUB_TWIN_PRICE = 11.30                                                # A3.04


def costco_annual_units():
    """A10.05's Costco volume: A5.38's y3 share of wholesale over three quarters, at
    A3.04's $11.30 club twin, annualized so it compares with an annual run floor."""
    units_3q = wholesale(2) * SHARE["Costco"][2] * 1e6 / CLUB_TWIN_PRICE
    return units_3q, units_3q * 52.0 / 39.0


RETAIL_ACCOUNTS =("Walmart", "Kroger", "WF", "Sprouts")
SET_ACCOUNTS = RETAIL_ACCOUNTS + ("Regional",)      # A5.38 lines that carry a set; Regional's by range extension
LAUNCH_ACCOUNTS = ("Walmart", "Kroger", "WF")       # A10.18: a launch is authorized at the top-3 formal-review accounts
DISTRIBUTORS = ("UNFI", "KeHE")
SHARE_ACCOUNTS = ("DPI", "small")                   # A5.38 lines with no set or DC floor registered
ACCOUNT_UNITS = [G.units_by_account(y) for y in range(3)]   # A5.38 dollars over A3.04's realized prices (ruled
                                                            # 2026-09-14): one unit series per account
SF = [sigma_from_mape(x) for x in MAPE]              # A5.25's forecast error, as A10.16 reads it



def club_week_dollars():
    """A10.05: Costco's dollars a club-week -- three quarters' units at the club twin, over the generator's own selling
    weeks and CLUBS. Moved here from the gate 2026-09-23."""
    u3, u_year = costco_annual_units()
    weeks = 52.0 * u3 / u_year
    return u3 * CLUB_TWIN_PRICE / (weeks * CLUBS)

def trial_rng(trial, stream="catalogue"):
    """One seeded stream per trial and purpose, so two readings of the catalogue share every draw they
    have in common (DECISIONS 2026-09-13)."""
    return random.Random("%d:%s:%d" % (SEED, stream, trial))


def account_factors(rng, s):
    """A SKU's velocity factor at each account that carries sets (owner, 2026-09-14): a flavor that moves at Whole
    Foods need not move at Walmart, and a retailer cannot forecast that before it sells. Mean 1, log-sd s; the
    normals are drawn whatever s is, so readings at different s share every draw."""
    return dict((a, math.exp(-s * s / 2 + s * rng.gauss(0, 1))) for a in SET_ACCOUNTS)


def fill(state, y, e, reserve=0):
    """A10.16's sticky authorization: an account carries a SKU until something removes it and fills a
    vacancy, or A7.26's growth, by ranking the SKUs it does not carry on a forecast with A5.25's error - of the
    catalogue velocity, since the account factor is unknown until the SKU sells there.
    `reserve` holds the year's growth at the launch accounts for launches (A10.18: growth frees a slot). A launch
    is authorized only at the launch accounts (A10.18), so the other accounts never add one."""
    for a in SET_ACCOUNTS:
        if not RETAIL_DOORS[a][y]:
            continue
        opening = not any(RETAIL_DOORS[a][:y])
        held = reserve and a in LAUNCH_ACCOUNTS and not opening and y > 0
        target = AUTH_ALL[a][y - 1] if held else AUTH_ALL[a][y]
        need = target - len(state["auth"][a])
        if need <= 0:
            continue
        cand = [i for i in sorted(state["live"]) if i not in state["auth"][a] and i not in state["gone"][a]
                and (a in LAUNCH_ACCOUNTS or i not in state["launches"])]
        cand.sort(key=lambda i: -(e[i] * math.exp(SF[y] * state["noise"][i][y])))
        state["auth"][a] |= set(cand[:need])


def dc_floor(state, y, e, exempt=()):
    """A10.06: a SKU below one case per DC per week is discontinued at that distributor's DCs, for good. The
    distributor's units are its A5.38 dollars over A3.04's price, split over the SKUs it still carries.
    Returns the SKU-DC pairs lost."""
    lost = 0
    for d in DISTRIBUTORS:
        carried = [i for i in sorted(state["live"]) if (d, i) not in state["dead"]]
        s = sum(e[i] for i in carried)
        per_dc = ACCOUNT_UNITS[y][d] / dcs(d, y)
        for i in carried:
            if i in exempt:
                continue
            if per_dc * e[i] / s / 52.0 / CASE_UNITS < VIABILITY_CASES:
                state["dead"].add((d, i))
                lost += dcs(d, y)
    return lost


def units(state, y, e):
    """Each live SKU's annual units. Every A5.38 line's units are its dollars over A3.04's realized price (ruled
    2026-09-14: the account's dollars are the ladder's split, units follow, velocity per account derives). An
    account with a set - Walmart, Kroger, Whole Foods, Sprouts, Regional - splits its units over the SKUs it carries
    in proportion to their velocity AT THAT ACCOUNT, the catalogue velocity times the SKU's account factor; UNFI and
    KeHE split theirs over the SKUs each still carries at its DCs; DPI and the small accounts, which register no
    set, and the consumer channel - A8.02's own-site jars and Amazon's units (A11.01, ruled 2026-09-15) - over
    every live SKU."""
    live = sorted(state["live"])
    sm = sum(e[i] for i in live)
    U = ACCOUNT_UNITS[y]
    flat = G.dtc_jars(y) + G.amazon_units(y) + sum(U[k] for k in SHARE_ACCOUNTS)
    out = dict((i, flat * e[i] / sm) for i in live)
    for d in DISTRIBUTORS:
        carried = [i for i in live if (d, i) not in state["dead"]]
        s = sum(e[i] for i in carried)
        for i in carried:
            out[i] += U[d] * e[i] / s
    for a in SET_ACCOUNTS:
        carried = [i for i in state["auth"][a] if i in state["live"]]
        if not RETAIL_DOORS[a][y] or not U.get(a) or not carried:
            continue
        s = sum(e[i] * state["eps"][i][a] for i in carried)
        for i in carried:
            out[i] += U[a] * e[i] * state["eps"][i][a] / s
    return out


def recipe_cull(state, vol, exempt=()):
    """A5.29's run floor on the recipe: a recipe whose live sizes sell fewer than two minimum runs a year together
    is discontinued, every size with it; a size too slow to run alone survives on its recipe-mates. A recipe with
    a size in its guaranteed-sale months is not reviewed. Returns the sizes discontinued."""
    by = {}
    for i in state["live"]:
        by.setdefault(state["recipe"][i], []).append(i)
    out = []
    for ids in by.values():
        if any(i in exempt for i in ids):
            continue
        if sum(vol[i] for i in ids) < RUN_FLOOR[state["mode"][ids[0]]]:
            out.extend(ids)
    return sorted(out)


def remove(state, ids):
    for i in ids:
        state["live"].discard(i)
        for a in SET_ACCOUNTS:
            state["auth"][a].discard(i)


def window_start(trial, sigma=None, pre=None, acct=None):
    """The catalogue on 2023-01-01, and the start-up artifact the brand had already removed.

    Draw the mature sizes' catalogue multipliers, account factors and forecast errors. A catalogue drawn that way
    carries recipes below A5.29's run floor at its first planning cycle, and pairs below A10.06's DC floor. The
    brand culled those recipes, and the distributors discontinued those pairs, the year before (ruled 2026-09-14):
    the FIRST draw's culled sizes and pairs are returned as the start-up figures, each culled mature size is redrawn
    in its slot until every recipe clears, and the window opens with that cycle's sub-floor pairs gone.

    `pre` holds the pre-period's launches still in the catalogue (group 11): each is a dict of id, m, mode, noise,
    eps, the accounts carrying it and the accounts that delisted or cut it, which do not take it back. Each takes a
    size slot of its production mode in group 2's recipe map, at random, and counts toward the 39; only the mature
    sizes are the start-up draw.
    """
    sigma = sigma or SIGMA_VELOCITY
    acct = account_sigma() if acct is None else acct
    pre = pre or []
    rng = trial_rng(trial)
    rng_eps = trial_rng(trial, "account")
    taken = []
    for p in pre:
        free = [k for k in range(SKUS) if k not in taken and SIZE_SLOTS[k][1] == p["mode"]]
        taken.append(rng.choice(free))
    slots = [k for k in range(SKUS) if k not in taken]
    n = len(slots)

    def draw():
        return (rng.lognormvariate(-sigma * sigma / 2, sigma), [rng.gauss(0, 1) for _ in range(3)],
                account_factors(rng_eps, acct))
    state = dict(m={}, noise={}, eps={}, mode={}, recipe={}, live=set(range(n)), dead=set(),
                 launches=set(p["id"] for p in pre),
                 auth=dict((a, set()) for a in SET_ACCOUNTS),
                 gone=dict((a, set(p["id"] for p in pre if a in p.get("gone", ()))) for a in SET_ACCOUNTS))
    for i, k in enumerate(slots):
        state["m"][i], state["noise"][i], state["eps"][i] = draw()
        state["recipe"][i], state["mode"][i] = SIZE_SLOTS[k]
    for p, k in zip(pre, taken):
        for key in ("m", "noise", "eps"):
            state[key][p["id"]] = p[key]
        state["recipe"][p["id"]], state["mode"][p["id"]] = SIZE_SLOTS[k]
        state["live"].add(p["id"])
    startup, redraws = None, 0
    while True:
        state["dead"] = set()
        state["auth"] = dict((a, set(p["id"] for p in pre if a in p["carried"])) for a in SET_ACCOUNTS)
        e = dict(state["m"])
        fill(state, 0, e)
        pairs = dc_floor(state, 0, e)
        vol = units(state, 0, e)
        cull = [i for i in recipe_cull(state, vol) if i < n]
        if startup is None:
            startup = dict(cull=len(cull), recipes=len(set(state["recipe"][i] for i in cull)), pairs=pairs)
        if not cull:
            break
        for i in cull:
            state["m"][i], state["noise"][i], state["eps"][i] = draw()
        redraws += len(cull)
        if redraws > 10000:
            raise RuntimeError("window start did not clear the run floor")
    cm = [rng.lognormvariate(-sigma * sigma / 2, sigma) for _ in range(len(CLUB_DESIGN_MODE))]
    cfc = [cm[j] * math.exp(rng.gauss(0, SF[2])) for j in range(len(cm))]
    state.update(redraws=redraws, club_m=cm, club_fc=cfc)
    return state, startup


def within_set_spread(sigma=None, acct=None, trials=1500):
    """What A7.03 measures: the log-sd of velocity relative to its carried set's mean, pooled over the four
    formal-review accounts' sets at A7.26's y3 counts and weighted by their y3 doors, on the window-start
    catalogue. Velocity at an account is the catalogue multiplier times the SKU's account factor."""
    w = wx = wxx = 0.0
    for trial in range(trials):
        state, _ = window_start(trial, sigma, acct=acct)
        e = dict(state["m"])
        for y in (1, 2):
            fill(state, y, e)
        for a in RETAIL_ACCOUNTS:
            carried = [e[i] * state["eps"][i][a] for i in state["auth"][a] if i in state["live"]]
            if not carried or not RETAIL_DOORS[a][2]:
                continue
            mean = sum(carried) / len(carried)
            for v in carried:
                x = math.log(v / mean)
                w += RETAIL_DOORS[a][2]
                wx += RETAIL_DOORS[a][2] * x
                wxx += RETAIL_DOORS[a][2] * x * x
    return math.sqrt(wxx / w - (wx / w) ** 2)


_SOLVED = {}


def single_multiplier_ceiling(grid=None, trials=600):
    """Step one of the owner's 2026-09-14 order: with the run floor on the recipe and no account factor, how far can
    widening the catalogue multiplier alone spread the carried sets? Returns each catalogue sigma's within-set
    spread and first-draw cull, None where the window never clears. The grid opens at the derived multiplier."""
    grid = grid or (SIGMA_VELOCITY, 1.25, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
    out = []
    for sg in grid:
        try:
            spread = within_set_spread(sg, 0.0, trials)
            cull = sum(window_start(t, sg, acct=0.0)[1]["cull"] for t in range(trials)) / float(trials)
            out.append((sg, spread, cull))
        except RuntimeError:
            out.append((sg, None, None))
    return out


def launch_free_sigma():
    """The factor's log-sd on the launch-free population: closing the gap to SIGMA_ACCOUNT on the window-start
    catalogue, with no launches, cuts or decline. Printed beside account_sigma(), not used. The ruling's 'about
    0.79' and revision 6's 0.788 were this same reading against the retired 0.953 target, before ruling 3
    (2026-09-15) took the door and week components out of it."""
    if "launch_free" not in _SOLVED:
        if within_set_spread(SIGMA_VELOCITY, 0.0) >= SIGMA_ACCOUNT:
            _SOLVED["launch_free"] = 0.0
        else:
            lo, hi = 0.0, 2.0
            for _ in range(18):
                mid = (lo + hi) / 2
                if within_set_spread(SIGMA_VELOCITY, mid) < SIGMA_ACCOUNT:
                    lo = mid
                else:
                    hi = mid
            _SOLVED["launch_free"] = (lo + hi) / 2
    return _SOLVED["launch_free"]


def account_sigma():
    """The SKU x account factor's log-sd (owner, 2026-09-14: signed as structure, its size derived): whatever closes
    the gap to A7.03's spread within the carried sets the window actually generates - launches, cuts and A2.09's decline
    included - so it is solved on group 11's draw (2026-09-14 audit). Imported lazily, because group 11 builds the
    window on this module; solved once a process."""
    if "acct" not in _SOLVED:
        import group11_compliance as L
        _SOLVED["acct"] = L.solve_account_factor()
    return _SOLVED["acct"]


def quarter(state, t, e, hook=None, exempt=(), reserve=0):
    """One quarter: A7.26's growth at a year's start, A10.06's DC floor, then A5.29's run floor on each
    live recipe's units. `hook(state, t, e)` runs after the DC floor and before units - group 11 applies the
    launch rules there - and returns SKUs to discontinue whatever their volume. Exempt SKUs are in their
    guaranteed-sale months. Returns (catalogue exits, SKU-DC pairs lost)."""
    y = t // 4
    if t and t % 4 == 0:
        fill(state, y, e, reserve)
    lost = dc_floor(state, y, e, exempt)
    forced = hook(state, t, e) if hook else []
    vol = units(state, y, e)
    state["vol"] = vol
    out = sorted(set(forced) | set(recipe_cull(state, vol, exempt)))
    remove(state, out)
    return out, lost


def club_exits(state):
    """A10.05's club packs: Costco takes the two designs it forecasts best, from Q2 y3, on its volume. A club pack
    runs in its recipe's campaign, so its recipe's live sizes count toward the floor with it."""
    _, costco_units = costco_annual_units()
    accepted = sorted(range(len(state["club_m"])), key=lambda j: -state["club_fc"][j])[:CLUB_ACCEPTED]
    share = sum(state["club_m"][j] for j in accepted)
    vol = state.get("vol", {})
    out = 0
    for j in accepted:
        mates = sum(vol.get(i, 0.0) for i in state["live"] if state["recipe"][i] == CLUB_RECIPE[j])
        out += costco_units * state["club_m"][j] / share + mates < RUN_FLOOR[CLUB_DESIGN_MODE[j]]
    return out


def catalogue_exits(trials=6000, sigma=None, acct=None):
    """A10.09's catalogue and A10.06's DC discontinuations, as ONE mechanism.

    Two registered floors act on the same SKUs and cannot be derived apart: A10.06's one case per DC per
    week, and A5.29's run floor - two minimum economic runs a year, on the recipe - at each planning cycle. A SKU
    cut at a DC loses that DC's volume, which is exactly what keeps the tail above the run floor.

    RESTATED 2026-09-14 (ruled): every A5.38 line's units are its dollars over price, velocity at an account carries
    the SKU's account factor, the run floor binds the recipe, and the window opens after the start-up cull
    (window_start). With no lifecycle - that is group 11's - the catalogue that clears the first cycle keeps its
    volume, so what remains in the window is whatever the growing environment removes.
    """
    sigma = sigma or SIGMA_VELOCITY
    acct = account_sigma() if acct is None else acct
    exits, pairs, club = [0.0] * 3, [0.0] * 3, 0.0
    cull = recipes = startup_pairs = redraws = mass = 0.0
    stats = dict((a, dict(sum=[0.0] * 3, minus_min=[0.0] * 3, n=[0.0] * 3, logsd=[0.0] * 3)) for a in RETAIL_ACCOUNTS)
    for trial in range(trials):
        state, startup = window_start(trial, sigma, acct=acct)
        cull += startup["cull"]
        recipes += startup["recipes"]
        startup_pairs += startup["pairs"]
        redraws += state["redraws"]
        mass += sum(state["m"].values())
        e = dict(state["m"])
        for t in range(12):
            y = t // 4
            if t % 4 == 0:
                if t:
                    fill(state, y, e)
                for a in RETAIL_ACCOUNTS:
                    carried = [state["m"][i] * state["eps"][i][a] for i in state["auth"][a] if i in state["live"]]
                    if carried:
                        logs = [math.log(v) for v in carried]
                        mu = sum(logs) / len(logs)
                        s = stats[a]
                        s["sum"][y] += sum(carried)
                        s["minus_min"][y] += sum(carried) - min(carried)
                        s["n"][y] += len(carried)
                        s["logsd"][y] += math.sqrt(sum((v - mu) ** 2 for v in logs) / max(len(logs) - 1, 1))
            gone, lost = quarter(state, t, e)
            exits[y] += len(gone)
            pairs[y] += lost
        club += club_exits(state)
    n = float(trials)
    active = dict((a, [y for y in range(3) if RETAIL_DOORS[a][y]]) for a in RETAIL_ACCOUNTS)
    return dict(startup_cull=cull / n, startup_recipes=recipes / n, startup_pairs=startup_pairs / n,
                redraws=redraws / n, sigma=sigma, acct=acct,
                mean_m=mass / n / SKUS, exits=[x / n for x in exits], pairs=[x / n for x in pairs], club=club / n,
                sets=dict((a, dict((k, [v / n if y in active[a] else 0.0 for y, v in enumerate(s[k])]) for k in s))
                          for a, s in stats.items()))


def velocity_sigma(target=None):
    """A10.16's sigma, from A5.28's A/B/C run cadence read as terciles.

    A items run 8-12 times a year and C items 3-4, so the A:C mean ratio is about
    2.86:1. Treating A/B/C as terciles of a log-normal velocity distribution pins
    sigma with no free parameter. Cadence is a PROXY: minimum run sizes and
    changeover economics compress it, so the true spread is at least this wide.
    The finding below does not turn on sigma, which is why that matters less than
    it looks.
    """
    target = target or (RUNS_A / RUNS_C)
    z1, z2 = NORM.inv_cdf(1 / 3.0), NORM.inv_cdf(2 / 3.0)
    lo, hi = 0.01, 4.0
    for _ in range(200):
        mid = (lo + hi) / 2
        top = (1 - NORM.cdf(z2 - mid)) / (1 / 3.0)
        bot = NORM.cdf(z1 - mid) / (1 / 3.0)
        if top / bot < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


A728_DISTRIBUTOR_REPORTING = 0.60     # A7.28: the share of distributor flow that reaches natural-channel
                                      # measurement, SPINS-PROJECTED (owner, 2026-09-22): what a brand's own
                                      # report shows. Owner-signed 2026-09-22, band 0.5-0.7, marked for U14 --
                                      # no published source measures it, and A7.28's whole series turns on it.
A730_WF_LEG_Y1 = 0.25                 # A7.30, owner-signed 2026-09-24, band 0.20-0.70: the share of UNFI's y1 dollars
                                      # that are Whole Foods-destined. No source states it. Later years DERIVE:
                                      # A5.38's points that leave Whole Foods direct reappear on the UNFI leg.


def wf_leg_share():
    """A7.30: the Whole Foods-destined share of UNFI's dollars, by window year (owner, 2026-09-24).

    y1 is the owner's point. Each later year adds the points A5.38 moves out of Whole Foods direct (14 -> 12 -> 10)
    to the leg and divides by UNFI's own line (12 -> 11 -> 10): 3 / 12, 5 / 11, 7 / 10 = 25 / 45.5 / 70%. The rule
    is the derivation; 30 / 35 was a guess and is not what A5.38 gives. EXACT: Fractions of the registered literals.
    """
    y1 = Fraction(str(A730_WF_LEG_Y1)) * Fraction(str(SHARE["UNFI"][0]))
    return [(y1 + Fraction(str(SHARE["WF"][0])) - Fraction(str(SHARE["WF"][t]))) / Fraction(str(SHARE["UNFI"][t]))
            for t in range(3)]


def reporting_weight(k, t):
    """A7.28's weight on an account's dollars in window year t: direct accounts in full, the distributors at 0.60,
    EXCEPT UNFI's Whole Foods leg (A7.30), which reaches Whole Foods doors that report in full (owner, 2026-09-24:
    the leg follows its dollars, numerator and denominator together; Whole Foods' doors already sit at 1.0)."""
    if k == "UNFI":
        phi = float(wf_leg_share()[t])
        return A728_DISTRIBUTOR_REPORTING + (1.0 - A728_DISTRIBUTOR_REPORTING) * phi
    return A728_DISTRIBUTOR_REPORTING if k in ("KeHE", "DPI") else 1.0


def live_door_sku_weeks(b, t):
    """A7.26 x A7.08 for banner b in window year t: doors carried over from the prior year are live all year, and
    only the INCREMENT is live for A7.08's share of it (owner, 2026-09-24; the row says new doors, and the generator
    had ramped every door). y1 has no prior year and every ramp is 1.0 there."""
    doors, a = A704_DOORS[b], AUTH_ALL[b][t] * 52
    ramp = A708_RAMP.get(b, [1.0, 1.0, 1.0])[t]
    carried = min(doors[t - 1], doors[t]) if t else doors[t]
    return carried * a + (doors[t] - carried) * a * ramp


A1018_TOPK = 3                        # A10.18, owner-signed, band 2-4: a launch is authorized at
                                      # the top-k formal-review accounts by A5.38 revenue rank


def assortment_ratio():
    """What a distributor-served door carries against a direct door, by A7.26 over A7.04.

    Computed 2026-09-22 for A7.28's ruling and NOT used as its weight. The owner asked whether
    A7.26 registers enough to derive the 60% reporting share as this ratio. It registers
    enough -- the ratio computes both door-weighted and unweighted -- but IT IS A DIFFERENT
    QUANTITY: A7.28's weight is the share of distributor flow that REPORTS to natural-channel
    measurement, which is about which doors report, and a door that reports is visible whatever
    its assortment. And A5.38's distributor dollars already reflect the narrower set an
    independent carries, so using this ratio as the weight would count assortment twice.

    Kept because it CORROBORATES the signed band: five of its six readings land inside 0.5-0.7, at the top, and door-weighted y2 lands above it.
    """
    direct = ("Walmart", "Kroger", "WF", "Regional", "Sprouts")   # A7.28's measured-direct list
    dw, uw = [], []
    for t_ in range(3):
        num = sum(A704_DOORS[a][t_] * AUTH_ALL[a][t_] for a in direct)
        den = sum(A704_DOORS[a][t_] for a in direct)
        dw.append(AUTH_ALL["independents"][t_] / (num / den))
        live = [AUTH_ALL[a][t_] for a in direct if A704_DOORS[a][t_] > 0]
        uw.append(AUTH_ALL["independents"][t_] / (sum(live) / float(len(live))))
    return dict(door_weighted=dw, unweighted=uw)


def syndicated_coverage():
    """A7.28: the share of wholesale dollars syndicated measurement can see.

    Registered 2026-09-21. The row reproduced exactly and nothing emitted or watched it.
    Direct-measured accounts in full, plus A728_DISTRIBUTOR_REPORTING of the distributor flow.
    Costco, the unreported distributor remainder, small accounts, DTC and the marketplace sit
    outside the denominator.

    INVARIANT TO THE DPI MOVE, and that is worth stating because it is not obvious: A5.38 ended
    DPI's line after y1 and moved its two points to KeHE, and both sit in the SAME 60%-reporting
    bucket, so the coverage series does not move at all.
    """
    direct_k = ("Walmart", "Kroger", "WF", "Sprouts", "Regional")
    dist_k = ("UNFI", "KeHE", "DPI")
    out = []
    for t_ in range(3):
        direct = sum(SHARE[k][t_] for k in direct_k) * 100.0
        dist = sum(SHARE[k][t_] for k in dist_k) * 100.0
        reported = sum(SHARE[k][t_] * reporting_weight(k, t_) for k in dist_k) * 100.0
        out.append(dict(direct=direct, distributor=dist, reported=reported, coverage=direct + reported))
    return out


# ---------------------------------------------------------------- group 7's scan identity, derived
# Registered as generator outputs 2026-09-22 on the owner's A7.07 ruling (DECISIONS#A7.07-shelf-steps).
# A3.08, A7.29, A7.03 and A7.07 carried worked series in prose that no generator computed; A7.29's y2 and y3
# were still on the account mix from before A5.38's DPI move of 2026-09-15.
A325_TARGET = {"Walmart": 30.0, "Kroger": 32.0, "Sprouts": 40.0, "WF": 42.0, "Regional": 35.0,
               "Costco": 13.0}                          # A3.25, owner-signed: each banner's target margin
A308_ENDINGS = {"WF": (0.99,), "Sprouts": (0.49, 0.99), "Kroger": (0.49, 0.99), "Regional": (0.49, 0.99),
                "Walmart": (0.48, 0.97, 0.98), "Costco": (0.99,)}   # A3.08's banner price-point endings
A328_TOLERANCE = 1.0                  # A3.28, owner-signed practitioner: points of margin below target a
                                      # retailer holds its ending through before it steps to the next one
A708_RAMP = {                                          # A7.08: share of the year a banner's doors are live
    "Walmart": [1.0, 0.85, 0.80], "Sprouts": [1.0, 0.60, 0.90], "Costco": [1.0, 1.0, 0.75],
    "independents": [1.0, 0.90, 0.90],
    # mirror-exempt: A708_RAMP['Walmart'][0], A708_RAMP['Sprouts'][0], A708_RAMP['Costco'][0], A708_RAMP['Costco'][1],
    # A708_RAMP['independents'][0] -- a year with no new doors is live all year by construction
}
A703_BAND = (1.0, 3.0)                # A7.03's plausibility band, units per SKU per store per week -- a
                                      # NATURAL-CHANNEL band, and it binds the natural channel only (owner,
                                      # 2026-09-22); grocery and mass take bands derived in channel_velocity()
A713_BARS = {"Walmart": 2.0, "Kroger": 1.5, "Sprouts": 1.2, "WF": 1.0, "Regional": 1.0,
             "independents": 0.8}                     # A7.13's 90-day bars, u/s/w; distributors' 0.8 on their doors.
                                                      # ONE transcription: group 11 reads it through F.
A306_CEILING = {"Walmart": 35.0, "Kroger": 35.0, "Sprouts": 46.0, "WF": 46.0, "Regional": 40.0,
                "Costco": 15.0}                       # A3.06's band tops, retailer margin %
CHANNELS = {"mass": (("Walmart",), ("Walmart",)),
            "grocery": (("Kroger", "Regional"), ("Kroger", "Regional")),
            "natural": (("WF", "Sprouts", "UNFI", "KeHE", "DPI"), ("WF", "Sprouts", "independents"))}
                                      # (A5.38 accounts, A7.04 banners): each channel's measured units over
                                      # its own measured doors, the same measured-over-measured rule as A7.03
BANNERS = ("WF", "Sprouts", "Kroger", "Regional", "Walmart", "Costco")
SHELF_OF = {"UNFI": "WF", "KeHE": "WF", "DPI": "WF"}   # A3.08: a distributor-served natural store buys at the
                                                      # natural list and prices as Whole Foods does


def _q(x):
    """A registered decimal as the exact rational it was written as: `str` recovers the literal, so 4.40 is 22/5
    and not the double nearest it. For registered constants only -- a computed float has no literal to recover."""
    return Fraction(str(x))


def _ladder(banner):
    return sorted(d + _q(e) for d in range(31) for e in A308_ENDINGS[banner])


def _margin(shelf, cost):
    return (shelf - cost) / shelf * 100


def retailer_cost(banner, t):
    """What the retailer pays for the 12 oz in window year t: A3.04's list back-cast through A3.22, Walmart on
    its realized increase. Costco is the club twin. A distributor-served store pays the natural list, WF's.
    EXACT: a Fraction, read by the shelf ladder alone."""
    f = G._price_index([_q(a) for a in G.ASK], _q(G.GIVEBACK))
    if banner == "Costco":
        return _q(G.PRICE_CLUB) * f["Costco"][t]
    return _q(G.PRICE[banner]) * f[banner][t]


def _shelf_exact(tol):
    """shelf_series' rule, solved in exact rationals: every comparison below is a claim the prose makes exactly.

    EXACT, NO TOLERANCE (2026-09-23). The rule read `p >= wholesale / (1 - target) - 1e-9` for "rounded UP to the
    next banner ending" and `q < shelf - 1e-9` for "one ending lower" -- the tolerance class FAILURES 2026-09-22
    retires. A shelf exactly on an ending is the case an epsilon decides, and nothing had chosen how."""
    out = {}
    for b in BANNERS:
        t_, lad = _q(A325_TARGET[b]), _ladder(b)
        cost = [retailer_cost(b, t) for t in range(3)]
        shelf = [None, None, min(p for p in lad if p >= cost[2] / (1 - t_ / 100))]
        for y in (2, 1):
            p = max(q for q in lad if q < shelf[y])
            forced = _margin(p, cost[y]) < t_ - tol
            held = _margin(p, cost[y - 1]) >= t_ - tol
            shelf[y - 1] = p if (forced and held) else shelf[y]
        out[b] = dict(shelf=shelf, cost=cost, margin=[_margin(shelf[t], cost[t]) for t in range(3)])
    return out


def shelf_series(tol=None):
    """A3.08 by window year, on the owner's ruling of 2026-09-22.

    The base year is A3.04's, 2025, where shelf is wholesale / (1 - A3.25's target) rounded UP to the next
    banner ending. Earlier years back-cast in steps: a retailer holds its ending through a list increase while
    its margin stays within A3.28's tolerance of target, and steps to the next ending when the shortfall
    exceeds it. So year y-1 sits one ending lower only if that lower ending was a held price in y-1 AND y's
    increase would have pushed it past the tolerance -- the step INTO y is then forced. Otherwise the retailer
    already stood at y's price. Where both readings reproduce the later year, the shelf back-casts with
    wholesale, which is the ruling's own phrase.

    Solved exactly in `_shelf_exact`; the figures leave here as floats, the form every reader takes.
    """
    tol = _q(A328_TOLERANCE) if tol is None else Fraction(tol)
    out = {}
    for b, s in _shelf_exact(tol).items():
        out[b] = dict(shelf=[float(x) for x in s["shelf"]], cost=[float(c) for c in s["cost"]],
                      margin=[float(m) for m in s["margin"]], steps=len(set(s["shelf"])) > 1,
                      above_ceiling=[float(max(0, m - _q(A306_CEILING[b]))) for m in s["margin"]])
    return out


def tolerance_window(tol=None):
    """The range of tolerance over which the step pattern at A3.28 holds, from the margin crossings that decide
    it. Each boundary is a target less a margin at some ending and some year's cost, so it is exact -- and is
    computed exactly, on the same Fractions the ladder is solved in."""
    tol = _q(A328_TOLERANCE) if tol is None else Fraction(tol)
    edges = set([Fraction(0), Fraction(10)])
    zero = _shelf_exact(Fraction(0))
    for b in BANNERS:
        t_, lad = _q(A325_TARGET[b]), _ladder(b)
        cost = [retailer_cost(b, t) for t in range(3)]
        top = zero[b]["shelf"][2]
        for p in [q for q in lad if top - 2 <= q <= top]:
            for t in range(3):
                e = t_ - _margin(p, cost[t])
                if 0 < e < 10:
                    edges.add(e)
    edges = sorted(edges)

    def pattern(x):
        return tuple(tuple(s["shelf"]) for s in _shelf_exact(x).values())
    here = pattern(tol)
    lo = max(e for e in edges if e <= tol)
    hi = min(e for e in edges if e > tol)
    while lo > 0 and pattern((lo + max(e for e in edges if e < lo)) / 2) == here:
        lo = max(e for e in edges if e < lo)
    while hi < 10 and pattern((hi + min(e for e in edges if e > hi)) / 2) == here:
        hi = min(e for e in edges if e > hi)
    return float(lo), float(hi)


def coverage_sensitivity(shares=(0.5, 0.7)):
    """A7.28's coverage at the ends of the signed 0.5-0.7 reporting band, the sensitivity the row prints beside the
    0.60. Moved into the generator 2026-09-24: it was computed by hand and went stale twice in one day."""
    global A728_DISTRIBUTOR_REPORTING
    saved, out = A728_DISTRIBUTOR_REPORTING, []
    try:
        for s in shares:
            A728_DISTRIBUTOR_REPORTING = s
            out.append([c["coverage"] for c in syndicated_coverage()])
    finally:
        A728_DISTRIBUTOR_REPORTING = saved
    return out


def markup_series():
    """A7.29 by window year: shelf over the brand's back-cast wholesale, weighted at A5.38 x A7.28's reporting.

    Two margins sit between the brand and a distributor-served shelf, so natural via UNFI, KeHE and DPI take
    WF's shelf over the distributor's own buy price."""
    S = shelf_series()
    f = G._price_index(G.ASK, G.GIVEBACK)
    direct = ("Walmart", "Kroger", "WF", "Sprouts", "Regional")
    by, weighted = {}, []
    for t in range(3):
        num = den = 0.0
        for k in direct + ("UNFI", "KeHE", "DPI"):
            w = SHARE[k][t] * reporting_weight(k, t)
            m = S[SHELF_OF.get(k, k)]["shelf"][t] / (G.PRICE[k] * f[k][t])
            by.setdefault(k, []).append(m)
            num, den = num + w * m, den + w
        weighted.append(num / den)
    return dict(by_account=by, weighted=weighted)


def scan_identity():
    """A7.03 and A7.07: velocity per MEASURED live door-SKU-week, in units, with dollars beside it.

    MEASURED OVER MEASURED (owner, 2026-09-22). The numerator is what syndicated measurement sees -- the direct
    accounts in full and A7.28's 0.60 of the distributor flow -- so the denominator is the same doors: A7.26's
    grid times A7.08's ramp, less Costco (club shares no POS) and with the distributor-served independents at
    the same 0.60. The first draft divided measured dollars by EVERY door in the grid.

    UNITS ARE WHOLESALE DOLLARS OVER WHOLESALE PRICE, account by account (A5.38 over A3.04's back-cast list),
    the same units group 9 computes. The shelf price cancels out of them: a shelf that holds while wholesale
    back-casts raises the markup exactly as much as it lowers units' price. So A3.08's series moves the DOLLAR
    reading and cannot move the unit one, and the unit reading is the headline -- velocity is a units quantity.
    """
    f = G._price_index(G.ASK, G.GIVEBACK)
    S = shelf_series()
    direct = ("Walmart", "Kroger", "WF", "Sprouts", "Regional")
    cov = [c["coverage"] / 100.0 for c in syndicated_coverage()]
    mk = markup_series()["weighted"]
    out = []
    for t in range(3):
        w = GROSS[t] * (1 - S_DTC) * 1e6
        units = dollars = 0.0
        for k in direct + ("UNFI", "KeHE", "DPI"):
            u = w * SHARE[k][t] * reporting_weight(k, t) / (G.PRICE[k] * f[k][t])
            units += u
            dollars += u * S[SHELF_OF.get(k, k)]["shelf"][t]
        live_all = live_meas = 0.0
        for b, doors in A704_DOORS.items():
            v = live_door_sku_weeks(b, t)
            live_all += v
            if b != "Costco":
                live_meas += v * (A728_DISTRIBUTOR_REPORTING if b == "independents" else 1.0)
        out.append(dict(wholesale=w / 1e6, coverage=cov[t], markup=mk[t], retail=dollars / 1e6,
                        retail_identity=w * cov[t] * mk[t] / 1e6, units=units / 1e6, live_all=live_all,
                        live_meas=live_meas, upw=units / live_meas, dpw=dollars / live_meas,
                        implied=units / (sum(A703_BAND) / 2 * 52), grid_meas=live_meas / 52,
                        implied_ratio=units / (sum(A703_BAND) / 2) / live_meas))
    for key in ("upw", "dpw", "units", "live_meas"):
        for t in (1, 2):
            out[t][key + "_vs_y1"] = (out[t][key] / out[0][key] - 1) * 100.0
    return out


A714_NOT_ON_SHELF = [0.09, 0.105, 0.12]   # A7.14: store-SKU-weeks not on shelf, 9% y1 -> 12% y3, y2 the midpoint
A714_EPISODE_DAYS = (5.0, 14.0, 0.25)      # A7.14: episode median 5 days, 25% beyond 14 (two weeks)
A714_US = (0.079, 0.28)                    # A7.14: GMA's U.S. out-of-stock rate, and its upstream-caused share
                                           # (Exhibit 2, 28%); the brand's rate above the U.S. one is supplier-caused


def supplier_share(t):
    """A7.14's supplier-caused share of the not-on-shelf weeks in window year t (owner, 2026-11-03, DECISIONS#u14):
    the U.S. average's upstream share plus every point of the brand's rate above the U.S. average."""
    us, up = A714_US
    r = A714_NOT_ON_SHELF[t]
    return (up * us + (r - us)) / r


def void_episodes():
    """A7.15's planted count: gap-weeks = A7.14's rate x A7.26's full grid (doors x authorized SKUs x 52); the
    supplier-caused share of them is planted as episodes, gap-weeks over the MEAN episode, which the log-normal's tail
    drags far above the 5-day median.

    Registered in a generator 2026-09-24. The row's figures had been computed in prose on the 2026-09-05 door
    plan and went stale when the plan grew. The rate per door-SKU does not depend on the doors; the counts do.
    Store-caused gaps run about a day (GMA Exhibit 8) and are not planted: a weekly grid cannot hold them, so they
    stay in the weekly not-on-shelf rate (owner, 2026-11-03, DECISIONS#u14).
    """
    med, tail, share = A714_EPISODE_DAYS
    sigma = math.log(tail / med) / NORM.inv_cdf(1 - share)
    mean_weeks = med * math.exp(sigma ** 2 / 2) / 7.0
    out = []
    for t in range(3):
        door_skus = sum(A704_DOORS[b][t] * AUTH_ALL[b][t] for b in A704_DOORS)
        gap = door_skus * 52 * A714_NOT_ON_SHELF[t]
        planted = gap * supplier_share(t)
        out.append(dict(gap_weeks=gap, planted_weeks=planted, episodes=planted / mean_weeks,
                        per_door_sku=planted / mean_weeks / door_skus, share=supplier_share(t),
                        sigma=sigma, mean_days=mean_weeks * 7))
    return out


def channel_velocity():
    """A7.03 by channel, with the band each channel is judged against (owner, 2026-09-22).

    A7.03's 1-3 u/s/w was written for natural-channel specialty sauces and binds the natural channel only.
    Grocery and mass take bands DERIVED from their own registered velocities: the location is the channel's
    door-weighted A7.13 90-day bar, and the width is the natural band's, upper = 3 x lower -- A10.17's move, width
    transfers and location stays with the registered figure. The natural band stays the registered 1-3. The blended
    figure prints beside them and is judged against none of them.
    """
    f = G._price_index(G.ASK, G.GIVEBACK)
    ratio = A703_BAND[1] / A703_BAND[0]
    out = {}
    for ch, (accts, banners) in CHANNELS.items():
        vel, bar = [], []
        for t in range(3):
            w = GROSS[t] * (1 - S_DTC) * 1e6
            units = sum(w * SHARE[k][t] * reporting_weight(k, t) / (G.PRICE[k] * f[k][t]) for k in accts)
            live = wbar = wd = 0.0
            for b in banners:
                rep = A728_DISTRIBUTOR_REPORTING if b == "independents" else 1.0
                d = A704_DOORS[b][t] * rep
                live += live_door_sku_weeks(b, t) * rep
                wbar, wd = wbar + d * A713_BARS[b], wd + d
            vel.append(units / live)
            bar.append(wbar / wd)
        # the location is each year's own bar, not y3's applied to all three (owner, 2026-09-24)
        bands = [(A703_BAND[0], A703_BAND[1]) if ch == "natural" else (bar[t], bar[t] * ratio) for t in range(3)]
        out[ch] = dict(velocity=vel, bar=bar, bands=bands,
                       breach=[(t, v) for t, v in enumerate(vel) if not bands[t][0] <= v <= bands[t][1]])
    return out


def rationalization_cuts():
    """A10.18: one-in-one-out at the formal-review accounts, per account and per review year.

    Registered 2026-09-21. The arithmetic closed in prose and no generator carried it.
    Each of A7.09's six launches after y1 is authorized at the top-k formal-review accounts, so
    each account takes k a year; the retailer frees a slot by cutting its lowest-velocity item
    UNLESS its own authorized count grew, which is A7.26's per-door authorizations differenced.

    Only the top-k accounts cut. Sprouts and Costco review formally and are not top-k, so they
    take no launch and free nothing; Regional and the independents have no formal line review,
    so their growth frees no slot either. An earlier version netted ALL accounts' growth against
    the launches and got 11 -- counting growth that frees no slot as though it offset one.
    """
    rows, total = [], 0.0
    for a in LAUNCH_ACCOUNTS:
        per = []
        for y in (1, 2):                       # the two review years after y1
            growth = AUTH[a][y] - AUTH[a][y - 1]
            per.append(dict(year=y + 1, taken=A1018_TOPK, growth=growth,
                            cut=A1018_TOPK - growth))
            total += A1018_TOPK - growth
        rows.append(dict(account=a, years=per, cuts=sum(p["cut"] for p in per)))
    return dict(accounts=rows, authorizations=LAUNCHES_AFTER_Y1 * A1018_TOPK, total=total)


def breadth_concurrency(k_story=3):
    """A10.08's breadth: how many SKUs are out in a month, as a DISTRIBUTION and not a mean.

    Registered 2026-09-21. The row published the MEAN (A5.21's stockout share across the live
    catalogue) and then called three concurrent "the y3 mode", which the same inputs do not
    support: each live SKU is out or not in a month, so the count is Binomial(active, stockout)
    and its mode is floor((n + 1) p), not the mean rounded up.

    The narrative around it survives -- a three-SKU story DOES sit beside the mode in y3, at
    23.2% against the mode's 23.7% -- and that is worth stating precisely rather than as the
    word "mode", because the two are different claims and only one of them is true.
    """
    out = []
    for t_ in range(3):
        n, p = ACTIVE_SKUS[t_], STOCKOUT[t_]
        pmf = [math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]
        # the row's rule, solved as stated and exactly (owner, 2026-09-23): the argmax of a float pmf picks between
        # two equal modes by rounding noise whenever (n + 1) p is a whole number; floor((n + 1) p) takes the upper
        mode = math.floor((n + 1) * _q(p))
        out.append(dict(n=n, p=p, mean=n * p, mode=mode, p_mode=pmf[mode],
                        p_story=pmf[k_story], p_at_least=sum(pmf[k_story:])))
    return out


def wf_fill_risk():
    """A10.04's Whole Foods consequence, against A10.02's registered 90 drop line.

    Registered 2026-09-21. A10.04 had SCRIPTED "fill below 90 for two quarters (y1 Q3-Q4)"
    with nothing computing it, and A10.02 -- which is in A10.04's own depends_on -- says in
    terms that a line the model cannot reach "is not a finding about the character" and that
    reading it as a risk "would overstate what the data does". The row had done exactly that.

    The distance is the honest quantity and the probabilities follow it: a quarter mean carries
    A5.17's monthly sd over sqrt(3), so the 90 line sits that many quarterly sd above the mean.
    A STATED pair of quarters (Q3-Q4) is p^2; ANY adjacent pair in the year is quarter_risk's
    year term, which counts the four-quarter strings rather than multiplying three overlapping
    pairs.
    """
    q_sd = SD_INFULL / math.sqrt(3.0)
    out = []
    for t_ in range(3):
        p, pair, year = quarter_risk(INFULL[t_], SD_INFULL, 90.0)
        out.append(dict(mean=INFULL[t_], sd_above=(INFULL[t_] - 90.0) / q_sd,
                        quarter=p, named_pair=pair, any_pair=year,
                        one_in_named=1.0 / pair, one_in_any=1.0 / year))
    return dict(q_sd=q_sd, years=out)


# ---- A10.13's coherence tolerances. Registered 2026-09-21: the row was in NO generator and
# NO gate check -- zero hits across all four files -- so its three numbers were prose with
# nothing deriving them, and check_depends_completeness could not reach it because its status
# is `decided` and not `derived`.
A421_UNITEMIZED = 0.20                # A4.21, unitemized AT ARRIVAL -- distinct from A4.05's
                                      # permanently-unclassified `other`, which is the other term
A1013_TRAILING_DAYS = 60              # A10.13, the in-flight window the tie-out is read over
A506_LEAD_MAX = {"Walmart": 7, "Kroger": 14, "UNFI": 10,         # A5.06, the TOP of each order -> requested-ship
                 "KeHE": 10, "Costco": 21}                       # range: a tolerance is a worst case. Walmart's 7 is
                                      # its processing days; its 10 is order-to-MABD, transit included (owner, 2026-10-05)
A502_PALLET = (96, 52.80)             # A5.02: one pallet, 96 cases at $52.80 a case -- the acceptance floor


def po_value(acct, t):
    """A5.02's plausibility: an account's mean PO value in window year t, $, and the pallets it fills -- A5.38's
    share of wholesale over A5.02's PO count. WATCHED (owner, 2026-09-29, the watched-or-priced rule): the row
    printed Walmart's at a 33% share after A5.38 had moved it to 29.5, because nothing computed the print."""
    dollars = G.GROSS[t] * (1 - G.S_DTC) * 1e6 * G.SHARE[acct][t] / 100.0 / POS[acct][t]
    return dollars, dollars / (A502_PALLET[0] * A502_PALLET[1])


A502_CYCLE_DAYS = {"Walmart": 7, "Kroger": 14, "UNFI": 7,        # A5.02's order cadence in days --
                   "KeHE": 7, "Costco": 30}                      # weekly, biweekly, monthly


def coherence_tolerances():
    """A10.13's three tolerances, each computed from the rows it already depends on.

    TIE-OUT: A4.05's permanently-unclassified `other` share, plus the in-flight unitemized
    share -- A4.21's 20% falling on the trailing 60 days, which is 60/365 of a year's pool.
    The two terms are different quantities and the row says so: one is unclassified AFTER
    itemization, the other unitemized AT ARRIVAL.

    LAG: the top of A5.06's lead-time range plus one A5.02 order cycle, per account. The top
    and not the midpoint, because a tolerance that the worst case breaches is not a tolerance.

    SPREAD: internal fill less retailer-scored in-full, per year, widened by A5.17's monthly
    in-full sd. The scored metric is at or below internal by A5.18's credit rules, so the gap
    is non-negative by construction and the lower edge is CLIPPED at zero rather than reported
    negative; equality is a defect, not a pass (A10.13), so zero is the floor and not a target.
    """
    tie_out = A405_SHARE["other"] / 100.0 + A421_UNITEMIZED * A1013_TRAILING_DAYS / 365.0
    lag = dict((k, A506_LEAD_MAX[k] + A502_CYCLE_DAYS[k]) for k in A506_LEAD_MAX)
    gap = [A511_INTERNAL[t] - INFULL[t] for t in range(3)]
    raw = (min(gap) - SD_INFULL, max(gap) + SD_INFULL)
    return dict(tie_out=tie_out, lag=lag, gap=gap, raw_band=raw,
                band=(max(0.0, raw[0]), raw[1]), gap_mean=sum(gap) / 3.0)


def below_floor(mean_index, floor, sigma):
    """Share below a floor, for a log-normal with that ARITHMETIC mean."""
    mu = math.log(mean_index) - sigma ** 2 / 2
    return NORM.cdf((math.log(floor) - mu) / sigma)


def floor_crossings(year, sigma=None):
    """Kroger floor crossings, on both readings of an unregistered selection rule.

    A7.12's floor is 60% of category average and its index is the BRAND MEAN.
    Whether an AUTHORIZED SKU can sit below the floor depends on how an account's
    assortment is chosen, and no row registers that rule. Both readings are
    returned because they bracket the answer and neither gives three.
    """
    sigma = sigma or SIGMA_VELOCITY
    p_all = below_floor(VELOCITY_INDEX[year], VELOCITY_FLOOR["Kroger"], sigma)
    k = AUTH["Kroger"][year]
    q = 1 - k / float(SKUS)
    p_auth = max(0.0, (p_all - q) / (k / float(SKUS))) if p_all > q else 0.0
    return dict(share_all=p_all, count_all=p_all * SKUS, authorized=k,
                share_auth=p_auth, count_auth=p_auth * k,
                cut_index=math.exp(math.log(VELOCITY_INDEX[year]) - sigma ** 2 / 2
                                   + sigma * NORM.inv_cdf(q)))


def viability_crossings(year, sigma=None):
    """UNFI and KeHE SKU-DC discontinuations against A10.06's 1 case/DC/week floor."""
    sigma = sigma or SIGMA_VELOCITY
    out = {}
    for name, price in (("UNFI", 3.90), ("KeHE", 4.00)):
        n_dcs = dcs(name, year)
        dollars = wholesale(year) * SHARE[name][year] * 1e6
        per_dc_week = dollars / n_dcs / 52.0 if n_dcs else 0.0
        cases = per_dc_week / (price * CASE_UNITS)
        per_sku = cases / SKUS
        ratio = VIABILITY_CASES / per_sku if per_sku else float("inf")
        p = below_floor(1.0, ratio, sigma) if per_sku else 1.0
        out[name] = dict(per_dc_week=per_dc_week, cases=cases, per_sku=per_sku, dcs=n_dcs,
                         ratio=ratio, share=p, pairs=p * SKUS * n_dcs)
    return out


def late_days(account):
    """E[days past the window | not cancelled] and the share of late POs NOT cancelled, for one account: geometric
    at A10.11's mean for the account, truncated at A5.07's cap.

    A5.09's push-outs are agreed reschedules, not lateness, so they are not reused. A shipment more than five days
    past its window is A5.07's retailer cancel, coded late_cancel (A5.10), at every account (owner, 2026-09-25 and
    2026-10-01), and earns no fine at all. Kroger's was the only distribution until U4 (`kroger_late_days`).
    """
    p = 1.0 / LATE_MEAN.get(account, LATE_MEAN["Kroger"])
    pk = [(1 - p) ** (k - 1) * p for k in range(1, LATE_CANCEL_DAYS + 1)]
    mass = sum(pk)
    return sum(k * pk[k - 1] for k in range(1, LATE_CANCEL_DAYS + 1)) / mass, mass


def late_cancels(year):
    """A5.07's late cancels by account in window year t: POs late on A5.11's on-time (the brand's shipments, one
    clock at every account) and past A5.07's cap on the account's lateness. They sit INSIDE A5.07's 1.0% retailer
    cancellation rate, not on top of it (owner, 2026-09-25), and carry A5.10's late_cancel code (owner, 2026-10-01)."""
    late = 1 - ONTIME[year] / 100.0
    by = dict((a, n[year] * late * (1 - late_days(a)[1])) for a, n in POS.items())
    return dict(by_account=by, total=sum(by.values()), share=sum(by.values()) / sum(n[year] for n in POS.values()))


# Figures U4 restated by hand get a function here and a gate watch in the same commit (DECISIONS 2026-09-24, "a
# figure restated by hand once gets a generator and a watch"): A9.15's deductions per invoice, A5.02's lines, the
# roster A5.20 and A4.27 count, A7.04's %ACV, A7.20's penetration and A9.08's hire-me return.
def invoices(year):
    """Invoices on A5.02's POs in window year t: one per PO, two for A5.13's split share at its split accounts."""
    return (sum(n[year] for n in POS.values())
            + A513_SPLIT * sum(POS[k][year] for k in A513_SPLIT_ACCOUNTS))


def deductions_per_invoice(year):
    """A9.15: A9.06's deduction count over the invoices on A5.02's POs (owner, ruling 14 of U4: the exact
    construction, per account, not A5.20's 856 factor of x1.05 rounded across the roster)."""
    return filing_cascade()["count"][year] / invoices(year)


def po_lines(year):
    """A5.02's order lines in window year t: each account's POs at A5.37's mean lines per PO."""
    return sum(POS[k][year] * A537_LINES[k] for k in POS)


A507_RATE = dict(order_retailer=0.010, order_cinderhaven=0.005)      # A5.07: order-level cancels, share of POs
A507_LINE_SPLIT = dict(line_retailer=60, line_cinderhaven=40)        # A5.07: line-level cancels by initiator, %
A507_PER_YEAR_EXPECTED = 3            # A5.07: a kind is floored per window year only where >= 3 are expected


def a507_line_rate(acct, kind):
    """A5.07's line-level cancel rate at an account, a share of its lines (owner, 2026-10-06). A5.08's mix is the
    registered quantity and the order-level rate holds the level: line-cancel rows run cancel_line / cancel_order of
    the order-cancel rows, spread over the account's A5.37 lines per PO. Expected line cancels are therefore twice
    the order cancels at every account, whatever its lines per PO; the rate is what varies."""
    per_po = sum(A507_RATE.values()) * A508_MIX["cancel_line"] / A508_MIX["cancel_order"]
    return per_po * A507_LINE_SPLIT[kind] / 100.0 / A537_LINES[acct]


def cancel_floor():
    """A5.07's acceptance floor, PROBABILISTIC (owner, 2026-10-05). Each kind of cancellation is floored per window
    year at an account only in the years its expected count there reaches A507_PER_YEAR_EXPECTED; everywhere else
    the floor is >= 1 over the window. A miss is a draw, not a defect, so the odds are printed beside the floor:
    the chance a correct generation shows none, (1 - rate)^n per year on A5.02's POs or A5.37's lines, and the
    product of the years over the window. The line-level rate is per account (a507_line_rate)."""
    out = {}
    for acct in POS:
        kinds = sorted(list(A507_RATE.items()) + [(k, a507_line_rate(acct, k)) for k in A507_LINE_SPLIT])
        for kind, rate in kinds:
            n = [POS[acct][t] * (A537_LINES[acct] if kind.startswith("line") else 1) for t in range(3)]
            expected = [rate * x for x in n]
            miss = [(1 - rate) ** x for x in n]
            window_miss = 1.0
            for m in miss:
                window_miss *= m
            out[(acct, kind)] = dict(expected=expected, per_year=[e >= A507_PER_YEAR_EXPECTED for e in expected],
                                     miss=miss, window_miss=window_miss)
    return out


A501_REVISED = {"grocery": 22, "mass": 18, "natural": 20, "club": 10, "distributors": 15, "small": 8}   # A5.01, % of POs
A501_CHANNEL = {"Kroger": "grocery", "Regional": "grocery", "Walmart": "mass", "WF": "natural", "Sprouts": "natural",
                "Costco": "club", "UNFI": "distributors", "KeHE": "distributors", "DPI": "distributors",
                "small": "small"}
A508_PER_LINE = {1: 75, 2: 18, 3: 7}    # A5.08: revisions per revised line, % of revised lines; 3+ read as 3
A508_INCREASE = A508_MIX["increase"]    # A5.08: increases, % of revision rows, every one retailer-initiated (A5.10)


def revision_presence():
    """05:154's miss odds (owner-signed 2026-10-20, DECISIONS#u18-rulings): the chance a correct generation shows no
    row of a revision leg at an account, under A5.07's probabilistic rule extended to revision presence. A revised PO
    (A5.01's share of A5.02's POs) carries A5.08's revisions-per-revised-line distribution of rows; each row is an
    increase at A5.08's share (all retailer-side), Cinderhaven-initiated at A5.03's share, or a retailer reduction
    (cut, line cancel or whole-order cancel) at what A5.03's retailer share leaves after its increases and order
    cancels (`_a512_ri`'s split). A5.03 runs y1 -> y3; y2 reads the midpoint. A leg is tested per window year where
    at least A507_PER_YEAR_EXPECTED rows are expected every live year, over the window elsewhere; `fail` is the chance
    the test fails on a correct run."""
    k = dict((n, w / 100.0) for n, w in A508_PER_LINE.items())
    rows_per_po = sum(n * w for n, w in k.items())
    retailer = [A503_RETAILER[0], sum(A503_RETAILER) / 2.0, A503_RETAILER[1]]
    order = A508_MIX["cancel_order"] * A503_ORDER_CANCEL_RETAILER / 100.0
    legs = {"increase": lambda t: A508_INCREASE / 100.0,
            "cinderhaven": lambda t: 1 - retailer[t] / 100.0,
            "retailer_reduction": lambda t: ((retailer[t] - A508_INCREASE - order)
                                             / (A508_MIX["cut"] + A508_MIX["date_change"] + A508_MIX["cancel_line"])
                                             * (A508_MIX["cut"] + A508_MIX["cancel_line"]) + order) / 100.0}
    out = {}
    for acct, ch in A501_CHANNEL.items():
        r = A501_REVISED[ch] / 100.0
        live = [t for t in range(3) if POS[acct][t]]
        for leg, q in legs.items():
            expected = [POS[acct][t] * r * rows_per_po * q(t) for t in live]
            miss = [(1 - r * (1 - sum(w * (1 - q(t)) ** n for n, w in k.items()))) ** POS[acct][t] for t in live]
            per_year = bool(live) and all(e >= A507_PER_YEAR_EXPECTED for e in expected)
            held = 1.0
            for m in miss:
                held *= (1 - m) if per_year else m
            out[(acct, leg)] = dict(years=live, expected=expected, miss=miss, per_year=per_year,
                                    fail=(1 - held) if per_year else held)
    return out


def roster(year):
    """The accounts A1.10 counts in window year t -- retailers and distributors with a share of wholesale (A5.38) --
    and the partners A5.20 sums from them."""
    r = sum(1 for k in A110_RETAILERS if SHARE[k][year] > 0)
    d = sum(1 for k in A110_DISTRIBUTORS if SHARE[k][year] > 0)
    return dict(retailers=r, distributors=d, partners=r + d)


A602_FIELDS = dict(mechanical=4, cognitive=2)   # A6.02: fields keyed on a manual order line, by kind
A602_RATES = dict(character=(0.4, 3.0), disciplined=(0.2, 2.0))   # A6.02: error % per mechanical, cognitive action
A632_EDI = (0.05, 0.1, 0.5)          # A6.32: EDI line error %, the band's low, the point, the band's high


def manual_line(desk, selection=False):
    """A6.02's manual line error, %, at a desk's per-action rates. `selection` reads choosing a UOM or a ship-to from
    a list as Panko's keystroke action, not his complex thought: the low end of the per-line band (owner,
    2026-10-25, DECISIONS#u14)."""
    mech, cog = A602_RATES[desk]
    cog = mech if selection else cog
    return (1 - (1 - mech / 100.0) ** A602_FIELDS["mechanical"] * (1 - cog / 100.0) ** A602_FIELDS["cognitive"]) * 100


def edi_ratio():
    """A6.02's manual-to-EDI line error ratio on A6.32's EDI rate (owner, 2026-10-23, DECISIONS#u14): the manual
    line at the point reading over A6.32's low, point and high; `band` is the widest the two bands allow, the
    selection reading over A6.32's high to the point reading over its low (owner, 2026-10-25). A band until the
    network pass gives the EDI rate and the reading a point."""
    out = {}
    for desk in A602_RATES:
        out[desk] = [manual_line(desk) / e for e in A632_EDI]
        out[desk + "_band"] = [manual_line(desk, True) / A632_EDI[2], manual_line(desk) / A632_EDI[0]]
    return out


def spread_floor_edi():
    """A6.16's manual-vs-EDI spread floor, derived (owner, 2026-10-25, DECISIONS#u14): A6.02's ratio at the top of
    A6.32's band, at the character's point reading. The fixed 20x it replaces failed inside A6.32's band."""
    return edi_ratio()["character"][2]


A701_WALMART = dict(sales=462.415, grocery=276.003, nm=25, sprouts=17.5)   # A7.01: Walmart U.S. net sales and its
                                      # filed grocery, $B (FY2025), a Neighborhood Market's grocery ACV $M, a Sprouts
                                      # box's $M
A704_WALMART_OTHER = dict(nm=671, discount=355, small=20)   # A7.04: Walmart U.S. units beside its Supercenters
A701_COSTCO_US = 184.143              # A7.01: Costco's U.S. segment total revenue, $B FY2024, membership fees in it
A704_WF_LOW = 500                     # A7.04: Whole Foods' U.S. stores at the band's low


def supercenter_acv(other=None):
    """A7.01's Supercenter grocery ACV, $M: Walmart U.S.'s filed grocery less its other formats, over the
    Supercenters (owner, 2026-10-23, DECISIONS#u14). The Discount stores take a Neighborhood Market's grocery ACV
    (reused, no row of their own); `other` sets theirs, and 0 gives the band's top. The 20 small formats are fuel
    stations and pharmacies and carry none."""
    W, U = A701_WALMART, A704_WALMART_OTHER
    other = W["nm"] if other is None else other
    return (W["grocery"] * 1e3 - U["nm"] * W["nm"] - U["discount"] * other) / A704_UNIVERSE["Walmart"]


def acv_share():
    """A7.04's y3 authorized doors as a share of each banner's filed universe, %. Walmart's doors are Supercenters,
    weighted by supercenter_acv() over the banner's grocery: `Walmart` at the ruled reading, `Walmart_top` with no
    grocery in the Discount stores. `WF_low` reads Whole Foods' band low."""
    out = dict((b, A704_DOORS[b][2] * 100.0 / A704_UNIVERSE[b]) for b in ("Kroger", "WF", "Sprouts", "Costco"))
    out["WF_low"] = A704_DOORS["WF"][2] * 100.0 / A704_WF_LOW
    grocery = A701_WALMART["grocery"] * 1e3
    out["Walmart"] = A704_DOORS["Walmart"][2] * supercenter_acv() * 100.0 / grocery
    out["Walmart_top"] = A704_DOORS["Walmart"][2] * supercenter_acv(0) * 100.0 / grocery
    return out


A720_PANEL = (131.4, 3.2)             # A7.20: U.S. households, millions (Census 2024), and the buying rate, units a
                                      # buyer a year


def penetration():
    """A7.20's panel identity in units, %: A7.03's measured units over A7.28's coverage, plus own-site jars and
    Amazon's units, over households x the buying rate."""
    S = scan_identity()
    return [(S[t]["units"] * 1e6 / S[t]["coverage"] + G.dtc_jars(t) + G.amazon_units(t))
            / (A720_PANEL[0] * 1e6 * A720_PANEL[1]) * 100 for t in range(3)]


def hire_return():
    """A9.08's hire-me-versus-hire-someone terms: the analyst's loaded cost (A9.05's wage-share operator), $ an hour,
    recovery per dispute-hour on bucket-1 disputes and at A4.07's achievable, and the bucket-1 multiple."""
    loaded = G.ANALYST[0] / G.WAGE_SHARE
    hourly = loaded / G.ANALYST[1]
    mean = deduction_mixture()["mean"]
    rate = dict(bucket1=mean * R1_CURRENT / G.DISPUTE_HOURS, achievable=mean * R1_ACHIEVABLE / G.DISPUTE_HOURS)
    return dict(loaded=loaded, hourly=hourly, rate=rate, multiple=rate["bucket1"] / hourly)


def phi(z):
    """Standard normal CDF, so the file carries no dependency for one function."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


# ------------------------------------------------------- the model, checked first
def months_below(mean, sd, year, metric):
    """Share of months the scored metric falls below the account's target.

    The target is effective-dated (A5.16), so a year can blend two targets. This
    is the function A5.17 states the output of; reproducing that output is the
    check that group 10 is extending the package's model rather than inventing a
    second one.
    """
    total, weighted = 0, 0.0
    for months, infull_t, ontime_t in TARGETS[year]:
        target = infull_t if metric == "infull" else ontime_t
        weighted += months * phi((target - mean) / sd)
        total += months
    return weighted / total


def reproduce_a517():
    """A5.17's published shares, recomputed from A5.11 + the dispersion + A5.16."""
    out = []
    for year in range(3):
        out.append((months_below(INFULL[year], SD_INFULL, year, "infull"),
                    months_below(ONTIME[year], SD_ONTIME, year, "ontime")))
    return out


def quarter_risk(mean, sd, line):
    """P(a quarter mean falls below a drop line), and the consecutive-pair risk.

    A drop line tested on two consecutive quarters is not tested on monthly
    dispersion: the quarter mean has sd / sqrt(3). A5.17 states the single-quarter
    answer for on-time ("about one time in five"); this returns it.
    """
    q_sd = sd / math.sqrt(3.0)
    p = phi((line - mean) / q_sd)
    pair = p * p
    # THE THREE PAIRS SHARE QUARTERS, SO THEIR COMPLEMENTS DO NOT MULTIPLY (corrected 2026-09-21).
    # This read `1 - (1 - pair) ** 3`, which treats (Q1,Q2), (Q2,Q3) and (Q3,Q4) as independent. They
    # are not: Q2 sits in two of them and Q3 in two. Counting the length-4 strings with no two adjacent
    # quarters below the line -- C(n-k+1, k) for k = 0, 1, 2 -- gives P(no adjacent pair) directly:
    #     q^4 + 4 p q^3 + 3 p^2 q^2
    # y3 is 9.8% and not the 10.8% the old form gave; a 4,000,000-draw Monte Carlo returns 0.09749.
    # THE GENERATOR AND THE PROSE HAD AGREED WITH EACH OTHER AND BOTH WERE WRONG, which is why no
    # cross-check could see it -- the figure checks compare the row to the generator, and here they
    # matched. Found by the nine-row signing verification (2026-09-21).
    q = 1.0 - p
    year = 1.0 - (q ** 4 + 4 * p * q ** 3 + 3 * p * p * q * q)
    return p, pair, year


# ---------------------------------------------------------------- A10.11 the fines
def wholesale(year):
    return GROSS[year] * (1 - S_DTC)


def noncompliant_share(year, reading):
    """Walmart's non-compliant CASE share, three readings of one unregistered fact.

    A5.17 settles the BASE - "fines apply to the non-compliant CASES every month
    regardless" - but not how lateness and shortfall overlap. The three readings
    span 18.0% to 27.4% in y3, and Walmart is two thirds of the fine total, so
    this is the single largest unpinned quantity in the group.

    A LATE CANCEL EARNS NO FINE AT ALL (owner, 2026-09-25 and 2026-10-01): a Walmart shipment past A5.07's cap on
    A10.11's Walmart lateness is Walmart's cancel and ships nothing, so it is neither late nor short. Only the late
    cases that ship, late x the share not cancelled, enter; on the signed independent reading that is
    late x kept + (1 - late) x short.
    """
    late, short = 1 - ONTIME[year] / 100.0, 1 - INFULL[year] / 100.0
    kept = late * late_days("Walmart")[1]
    if reading == "independent":
        return kept + (1 - late) * short
    if reading == "correlated":
        return max(kept, short)
    if reading == "exclusive":
        return kept + short
    raise ValueError(reading)


def fines(year, reading="independent", kroger_days=None):
    """Late/OTIF fine dollars by account, from each account's registered rate. A PO past A5.07's cap is a cancel at
    every account and ships nothing, so it carries neither a lateness fine nor a short-ship one (U4)."""
    w = wholesale(year)
    late, short = 1 - ONTIME[year] / 100.0, 1 - INFULL[year] / 100.0
    out = {}
    out["Walmart"] = WM_FINE * noncompliant_share(year, reading) * w * SHARE["Walmart"][year]
    for k, rate in FINE_SHORT.items():
        out[k] = rate * short * (1 - late * (1 - late_days(k)[1])) * w * SHARE[k][year]
    days, mass = late_days("Kroger") if kroger_days is None else (kroger_days, 1.0)
    out["Kroger"] = KROGER_PER_DAY * POS["Kroger"][year] * late * mass * days / 1e6
    out["Regional"] = (sum(REGIONAL_LATE) / 2) * POS["Regional"][year] * late * late_days("Regional")[1] / 1e6
    out["WF"] = 0.0            # A5.15: no published schedule, consequence is delist review
    out["Sprouts"] = 0.0       # A5.15: no OTIF fine; missed-appointment rate unregistered
    return out


def pool(year):
    """A4.05's denominator: A4.01's operational pool plus A4.31's invalid trade claims."""
    return (OPDED[year] + INVALID_TRADE) * GROSS[year]


def op_pool(year):
    """A4.05's type mix splits A4.01's operational pool alone, so the fines' share and ratio read it (owner,
    2026-11-06, U14 batch 8): A4.31's invalid trade claims sit outside the ten types."""
    return OPDED[year] * GROSS[year]


# ----------------------------------------------------------- A10.19 the equity call (U8, owner, 2026-10-06)
# A convertible note from the existing owners, coupon 8% PIK. Its DATE and SIZE are derived on U16's daily ledger
# (owner, 2026-10-22, DECISIONS#u16-daily-ledger), never typed. DATE: the first day of the month after the daily
# ledger's first credit hold on the line's own cash, the hold notice being the trigger - December 1 y2 at the signed
# AP rule; May 1 y3 at the band's other edge, each invoice paid at the run before its 32nd day. SIZE: the note that
# leaves A9.14's y3 springing trigger at the tightest day after it lands. The COUNTERFACTUAL is the latest first of a
# month at which the same note leaves the window no hold - November 1 y2, the CFO who calls a month earlier. August 1
# y3 (the annual interpolation, 2026-10-15), April 1 y3 (the Q2 counterfactual) and December y3 (2026-10-06) are
# history. The coupon compounds on each anniversary: interest in kind adds to principal (owner, 2026-10-22).
CALL_PIK = 8                          # A10.19: the note's coupon, % a year, PIK, owner-signed
D0_BAND = (0.5, 1.5)                  # A9.13: D0's signed band, $M
_CACHE = {}


def _first_of_next(d):
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


def _daily(d0=None, timing=None, call=None):
    """U16's daily ledger, once per argument set: every A10.19 and A10.07 figure reads these runs."""
    key = ("daily", d0, timing, call)
    if key not in _CACHE:
        _CACHE[key] = G.daily_ledger(call=call, d0=G.D0 if d0 is None else d0, ap_timing=timing)
    return _CACHE[key]


def holds(L):
    """Every day a supplier first reaches the credit hold, in order."""
    return sorted(set(f["hold"] for r in L["supplier"].values() for f in r["first"] if "hold" in f))


def hold_day(d0=None, timing=None):
    """The daily ledger's first credit hold on the line's own cash (no note), or None."""
    h = holds(_daily(d0, timing))
    return h[0] if h else None


def call_date(d0=None, timing=None):
    """A10.19's date: the first day of the month after the first hold notice."""
    return _first_of_next(hold_day(d0, timing))


def _tightest(L, when):
    """The least availability net of any stretch from `when` to 31 December y3."""
    return min(L["line"][k] - L["draw"][k] - L["late"][k] for k, d in enumerate(L["day"]) if d >= when)


def call_size(when, d0=None, timing=None):
    """The note that leaves A9.14's y3 springing trigger at the tightest day after it lands, by bisection."""
    key = ("size", when, d0, timing)
    if key not in _CACHE:
        trig = max(G.SPRING_PCT * G.COMMITMENT[2], G.AVAIL_HARD)
        lo, hi = 0.0, 20.0
        for _ in range(50):
            mid = (lo + hi) / 2
            if _tightest(G.daily_ledger(call=(mid, when), d0=G.D0 if d0 is None else d0, ap_timing=timing),
                         when) >= trig:
                hi = mid
            else:
                lo = mid
        _CACHE[key] = hi
    return _CACHE[key]


def note(size):
    """The note as issued (owner, 2026-10-27, DECISIONS#u14): the first three-figure amount, $M to the cent, at or above
    the bisected size, so the printed note always finances the window."""
    return math.ceil(round(size * 100, 9)) / 100.0


def pik(size, when):
    """The coupon by window year, $M: 8% a year accrued daily on principal, compounding on each anniversary."""
    out, principal, anniv = [0.0, 0.0, 0.0], size, date(when.year + 1, when.month, when.day)
    d = when
    while d < date(2026, 1, 1):
        if d == anniv:
            principal += principal * CALL_PIK / 100.0
            anniv = date(anniv.year + 1, anniv.month, anniv.day)
        ny = 366 if calendar.isleap(d.year) else 365
        if d.year >= 2023:
            out[d.year - 2023] += principal * CALL_PIK / 100.0 / ny
        d += timedelta(1)
    return out


def equity_call(d0=None, timing=None, when=None):
    """A10.19 at D0 = d0 and the AP timing given (the signed ones by default), landing on `when` (its derived date by
    default): the size, the daily ledger without and with the note, what the note pays off, the coupon by year."""
    when = call_date(d0, timing) if when is None else when
    size = note(call_size(call_date(d0, timing), d0, timing))
    before, after = _daily(d0, timing), _daily(d0, timing, (size, when))
    eb = G.pnl()["ebitda"]
    fixed = [eb[t] - G.CAPEX for t in range(3)]
    return dict(size=size, date=when, before=before, after=after, held=after.get("call_held", 0.0),
                cia=sum(r["cia"] for r in after["supplier"].values()), holds=holds(after),
                coupon=pik(size, when), tightest=_tightest(after, when),
                trigger=max(G.SPRING_PCT * G.COMMITMENT[2], G.AVAIL_HARD),
                fccr=[fixed[t] / after["interest"][t] for t in range(3)])


def ap_schedule_table():
    """The AP-run schedule U15's seeders read (U16): every run of the window on the data's own cash, A10.19's note in
    it - the run, what fell due, what it paid and what it held, $K. Printed in group 9's sourcing doc between its
    markers, and the gate compares the block to this text."""
    rows = ["| run | due $K | paid $K | held $K |", "|---|---|---|---|"]
    for r in equity_call()["after"]["run_detail"]:
        rows.append("| %s | %.0f | %.0f | %.0f |" % (r["day"], r["due"] * 1000, (r["due"] - r["held"]) * 1000,
                                                    r["held"] * 1000))
    return "\n".join(rows)


def equity_call_band():
    """A10.19 over D0's signed band, low then high: (date, size) at each end."""
    return [(call_date(d0), note(call_size(call_date(d0), d0))) for d0 in D0_BAND]


CALL_COST_POINTS = 1.5                # A10.19: the move in A9.16's 2023 cost level the band's sensitivity term reads,
                                      # points (owner, 2026-10-25)


def call_cost_sensitivity():
    """A10.19's cost-index term (owner, 2026-10-25, DECISIONS#u14): the note's move, $M, landing on its derived date,
    when A9.16's 2023 cost level is CALL_COST_POINTS higher, the 2024 move absorbing it and 2025 held."""
    if "cost_term" not in _CACHE:
        g = list(G.COGS_INDEX_YOY)
        g[1] = 1.0 / ((G._cost_index()[0] + CALL_COST_POINTS / 100.0) * (1 + g[2])) - 1
        saved, memo = G.COGS_INDEX_YOY, dict(G._MEMO)
        try:
            G.COGS_INDEX_YOY = g
            G._MEMO.clear()
            trig = max(G.SPRING_PCT * G.COMMITMENT[2], G.AVAIL_HARD)
            lo, hi = 0.0, 20.0
            for _ in range(50):
                mid = (lo + hi) / 2
                if _tightest(G.daily_ledger(call=(mid, CALL_DATE), d0=G.D0), CALL_DATE) >= trig:
                    hi = mid
                else:
                    lo = mid
        finally:
            G.COGS_INDEX_YOY = saved
            G._MEMO.clear()
            G._MEMO.update(memo)
        _CACHE["cost_term"] = hi - call_size(CALL_DATE)
    return _CACHE["cost_term"]


def counterfactual_date():
    """The latest first of a month, before the derived date, at which the same note leaves the window no hold."""
    size = note(call_size(CALL_DATE))
    d = CALL_DATE
    while True:
        d = date(d.year - (d.month == 1), (d.month - 2) % 12 + 1, 1)
        if not holds(_daily(call=(size, d))):
            return d


# ----------------------------------------------------------- A10.07 the supplier chain
def supplier_chain(L=None):
    """Days past terms per window year from an ANNUAL ledger (A9.13's line alone by default): the DPO stretch that
    funds each year's availability shortfall, against A9.11's terms. A9.13 prints it as its ladder, the annual-mean
    reading; A10.07's dated chain is daily_chain()'s (U16, 2026-10-22)."""
    P = G.pnl()
    wc = G.working_capital(P["cogs"])
    bb = G.borrowing_base(wc)
    L = G.ledger(P["ebitda"], wc, bb) if L is None else L
    stretch = [max(0.0, -L["avail"][t]) / (P["cogs"][t] / 365.0) for t in range(3)]
    fee_at, priority_at, hold_at = SUPPLIER_DAYS
    out = []
    for t in range(3):
        past = DPO + stretch[t] - SUPPLIER_TERMS["co-packers"]
        out.append(dict(stretch=stretch[t], dpo=DPO + stretch[t], past=past,
                        fee=past >= fee_at, priority=past >= priority_at, hold=past >= hold_at))
    return out, L


def daily_chain(L=None):
    """A10.07 on the daily ledger (the line's own by default): per year, the oldest unpaid invoice's worst days past
    terms and the day each consequence is first reached, by supplier."""
    L = _daily() if L is None else L
    sup = L["supplier"]
    return [dict(past=max(r["max_past"][t] for r in sup.values()),
                 first=dict((k, min([r["first"][t][k] for r in sup.values() if k in r["first"][t]] or [None]))
                            for k in ("priority", "fee", "hold")),
                 held=sorted(s for s, r in sup.items() if "hold" in r["first"][t]))
            for t in range(3)]


INHOUSE_LEAD_WEEKS = (2, 3)           # A5.29: in-house, ingredients on hand; a materials hold slips in-house runs
ALLOCATION_SHARE = 0.30               # A5.10: allocation_shortage's share of the Cinderhaven-initiated rows


def hold_cut_fit(L=None):
    """The hold's allocation_shortage cuts against the year's share of A5.12's cinderhaven_reduction (U18, owner,
    2026-10-20; net of cover, owner, 2026-10-22). At the first hold the held co-packers' A5.22 share slips by the
    co-pack lead and the materials' share by the in-house lead; finished goods on hand that day absorb the first days
    of each slip, and what is left is cut. Shares of a year's units."""
    L = _daily() if L is None else L
    h = hold_day()
    P = G.pnl()
    cover = L["fg"][h] / (P["cogs"][h.year - 2023] / 365.0)
    budget = ALLOCATION_SHARE * A512_Y3["cr"] / 100.0
    rows = []
    for name, share, weeks in (("co-packers", G.COPACK_SHARE, PROD_LEAD_WEEKS),
                               ("materials", 1 - G.COPACK_SHARE, INHOUSE_LEAD_WEEKS)):
        for w in weeks:
            rows.append(dict(supplier=name, weeks=w, gross=share * w * 7 / 365.0,
                             net=share * max(0.0, w * 7 - cover) / 365.0))
    return dict(hold=h, cover=cover, budget=budget, rows=rows,
                fits=all(r["net"] <= budget for r in rows))


def hold_edge():
    """y2's worst days past terms under the three AP timings, run before / nearest / after the 32nd day."""
    return [daily_chain(_daily(timing=k))[1]["past"] for k in ("before", "nearest", "after")]


# --------------------------------------------------------------------- the report
def _pct(x):
    return "%.0f%%" % (x * 100)


# ---------------------------------------------------------------- A10.16's catalogue multiplier, derived
# Owner, 2026-09-22: sigma derives from A7.03's EXACT y3 velocity, never the printed one. The retired 0.953 was solved
# from a rounded 2.94 on a denominator that counted every door in A7.26's grid; measured over measured the mean is
# scan_identity()'s y3, and sigma follows it through the same top-quintile solve. Everything that reads the
# multiplier or the account target reads these three at call time, so they are assigned before main() and nowhere else.
A703_MEAN_Y3 = scan_identity()[2]["upw"]
# A10.19's date (owner, 2026-10-22, DECISIONS#u16-daily-ledger): the first day of the month after the daily ledger's
# first hold notice, derived and never typed. Assigned here, after group 9 can load the floors it reads, and nowhere
# else; group 10's readers take it at call time.
CALL_DATE = call_date()
SIGMA_VELOCITY = sigma_from_a703()
SIGMA_ACCOUNT = account_target()


# ------------------------------------------------------------ U21, the entry function
# outputs(acct) is what the gate checks and the platform's seeders import, one object (regen plan U21). Each
# _printed_* function carries the values one gate function's entries read, (anchor, label, value), the label the
# entry's own; _values(acct) is the shared work they read, once a factor. The gate reads none of this module's
# internals.
_MEMO = {}


def _values(acct):
    """This generator's share of the work the printed entries read (the gate's _group11_compute until U21), by the
    names the entries use, on the solved account factor `acct`."""
    if acct in _MEMO:
        return _MEMO[acct]
    free = launch_free_sigma()
    A = authorization_draw()
    WO = write_off()
    BS = bucket_split()
    WB = within_bucket_mix()
    A606_ORDER = ("short_ship", "late_otif", "damaged_unsaleables", "spoilage_shortdated",
                  "receiving_miscount", "label_pallet_asn", "pricing_error", "post_audit",
                  "overage", "other")
    chain, _ = supplier_chain()
    def mape_at(sg, n=4000):
        return sum(abs(math.exp(sg * NORM.inv_cdf(k / float(n))) - 1.0) for k in range(1, n)) / (n - 1)
    _MEMO[acct] = dict(
        acct=acct,
        launch_free=free,
        active_skus=ACTIVE_SKUS,
        ceiling2=dict(zip(("sigma", "spread", "cull"),
                     single_multiplier_ceiling(grid=(2.0,))[0])),
        delists=[A["Kroger"]["exits"], A["Walmart"]["exits"], A["total_exits"]],
        pre_delists=[A["Kroger"]["pre_exits"], A["Walmart"]["pre_exits"], A["total_pre_exits"]],
        carried_strikes=[A["Kroger"]["carried"], A["Walmart"]["carried"], A["total_carried"]],
        below=[A["Kroger"]["below"], A["Walmart"]["below"]],
        mape=[mape_at(s) for s in (0.60, 0.50, 0.70)],
        past_y1=chain[0]["past"],
        dpo_y1=chain[0]["dpo"],
        bucket_op=BS["operational"],
        bucket_pool=BS["bucket"],
        invalid_of_operational=[BS["invalid_pct_of_operational"]],
        a606_b2=[WB["published"]["b2"][k] for k in A606_ORDER],
        a606_b1=[WB["published"]["b1"][k] for k in A606_ORDER],
        write_off=[x * 100 for x in WO["current"]],
        write_off_ach=[WO["achievable"]["controls"] * 100, WO["achievable"]["full"] * 100],
        write_off_b1=WO["recovered_b1"],
        a6=dict(coverage=coverage(), sop=sop_lever(), well_run=well_run_pool(), recovery=recovery(),
                 mix=WB["published"], op=WB["pool_share"], a626_map=A626_MAP, a613=A613_RATE),
    )
    return _MEMO[acct]


def _printed_a6_chain(V):
    """The values the gate's _a6_chain_figures reads, keyed (anchor, label) as its entries name them."""
    A606_DOC_ORDER = {"b2": ("short_ship", "label_pallet_asn", "pricing_error", "damaged_unsaleables", "spoilage_shortdated",
                         "late_otif", "receiving_miscount", "post_audit", "other", "overage"),
                  "b1": ("pricing_error", "receiving_miscount", "post_audit", "short_ship", "damaged_unsaleables", "other",
                         "spoilage_shortdated", "label_pallet_asn", "overage", "late_otif")}
    A626_DOC_ORDER = ("po_acknowledgment", "edi_reconciliation", "price_book_governance", "receiving_audit",
                  "item_setup_preflight", "three_way_match", "none")
    A626_ROW_ORDER = ("po_acknowledgment", "edi_reconciliation", "receiving_audit", "item_setup_preflight",
                  "price_book_governance", "three_way_match", "none")
    a6 = V['a6']
    C, S, W, R = a6["coverage"], a6["sop"], a6["well_run"], a6["recovery"]
    cov, nb, rm, rate = C["share"], C["none_by"], S["removal"], a6["a613"]
    ss, late, dmg, spoil, oth = (nb[k] for k in ("short_ship", "late_otif", "damaged_unsaleables",
                                                 "spoilage_shortdated", "other"))
    reach, struct = C["reachable"], C["structural"]
    ctl, full = W["prevention"]["controls"], W["prevention"]["full"]
    cur, pool = W["current"], W["pool"]
    b2c, b2f, totc, totf = W["b2"]["controls"], W["b2"]["full"], W["total"]["controls"], W["total"]["full"]
    shc, shf = W["b2_share"]["controls"], W["b2_share"]["full"]
    ach, dlt, usd, pct = R["achievable"], R["delta"], R["delta_usd"], R["delta_pct"]
    lever = [rm["short_ship"], rm["late_otif"], rm["spoilage_shortdated"]]
    table, table_p = [], []
    for c in A626_DOC_ORDER:
        table += [cov[c], rate[c], cov[c] * rate[c]]
        table_p += [1, 2, 0 if c == "none" else 2]
    return [
        ('A6.26', "A6.26's coverage vector, row",
         [cov[c] for c in A626_ROW_ORDER]),
        ('A6.26', "A6.26's `none` by type, then reachable and structural, row",
         [ss, late, dmg, spoil, oth, reach, struct]),
        ('A6.26', "A6.26's coverage vector, group 6's doc",
         [cov[c] for c in A626_DOC_ORDER]),
        ('A6.26', "A6.26's `none` by type, group 6's doc",
         [ss, late, spoil, reach, dmg, oth]),
        ('A6.26', "A6.26's `none` share, group 6's doc",
         [cov["none"]]),
        ('A6.26', "A6.26's `none` share, the decision",
         [cov["none"]]),
        ('A6.26', 'the block: A6.26 x A6.13 by control, then controls-only prevention',
         table + [ctl * 100]),
        ('A6.26', 'the block: `none` by type, reachable and unreachable',
         [ss, late, spoil, reach, dmg, oth, struct]),
        ('A6.31', "A6.31's reachable base, the `none` share and the structural types, row",
         [ss, late, spoil, reach, cov["none"], dmg, oth]),
        ('A6.31', "A6.31's removal by type, weighted, in points, and the full sum, row",
         lever + [S["weighted"], S["points"], ctl, S["points"] / 100, full]),
        ('A6.31', "A6.31's `none` by type, group 6's doc",
         [ss, late, spoil, dmg, oth]),
        ('A6.31', "A6.31's removal by type, weighted, in points, and the full sum, group 6's doc",
         lever + [S["weighted"] * 100, S["points"], ctl, S["points"] / 100, full]),
        ('A6.31', "the block: A6.31's weighted removal, its points, and full prevention",
         [S["weighted"] * 100, S["points"], full * 100]),
        ('A6.15', "A6.15's pool and its buckets, row",
         [pool] + cur),
        ('A6.15', "A6.15's bucket-1 residual, row",
         [cur[0], F_ACHIEVABLE, R1_ACHIEVABLE, W["b1"]]),
        ('A6.15', "A6.15's two tiers: prevention and bucket-2 residual, row",
         [ctl, b2c, full, b2f]),
        ('A6.15', "A6.15's bucket 3, row",
         [cur[2]]),
        ('A6.15', "A6.15's well-run pools, row",
         [totc, totf]),
        ('A6.15', "A6.15's bucket-2 share of the well-run pool, row",
         [shc, shf]),
        ('A6.15', 'the block: bucket-1 residual',
         [cur[0], F_ACHIEVABLE, R1_ACHIEVABLE, W["b1"]]),
        ('A6.15', 'the block: bucket-2 residual by tier',
         [cur[1], ctl, full, b2c, b2f]),
        ('A6.15', 'the block: bucket 3',
         [cur[2] / pool, pool, cur[2]]),
        ('A4.08', "the block: well-run pools and bucket 2's share of them",
         [totc, totf, shc, shf]),
        ('A6.15', "A6.15's bucket-2 residuals and the pool, group 6's doc",
         [b2c, b2f, pool]),
        ('A6.15', "A6.15's bucket 3, group 6's doc",
         [cur[2]]),
        ('A4.02', "A4.02's bucket 2 in gross, group 6's doc",
         [cur[1]]),
        ('A6.11', "A6.15's controls-only pool in A6.11, row",
         [totc]),
        ('A6.11', "A6.15's full pool in A6.11, row",
         [totf]),
        ('A6.15', "A6.15's controls-only pool in A6.11, group 6's doc",
         [totc]),
        ('A6.15', "A6.15's full pool in A6.11, group 6's doc",
         [totf]),
        ('A4.08', "A4.08's achievable pair at each tier's prevention, row",
         [ctl, ach["controls"], full, ach["full"]]),
        ('A4.08', "A4.08's current, row",
         R["current"]),
        ('A4.08', "A4.08's y3 deltas, per dollar and in $K, row",
         [dlt["controls"], dlt["full"], usd["controls"] * 1000, usd["full"] * 1000]),
        ('A4.08', "A4.08's achievable pair, group 6's doc",
         [ach["controls"], ach["full"]]),
        ('A4.08', "A4.08's y3 deltas, group 6's doc",
         [dlt["controls"], dlt["full"], pct["controls"], pct["full"], usd["controls"] * 1000, usd["full"] * 1000]),
        ('A4.08', "A4.08's y3 deltas, group 6's list of what it resolves",
         [dlt["controls"], dlt["full"], usd["controls"] * 1000, usd["full"] * 1000, pct["controls"], pct["full"]]),
        ('A9.06', "A4.08's achievable pair, the pool and the y3 deltas, A9.06",
         [ach["controls"], ach["full"], R["pool_usd"], usd["controls"], usd["full"]]),
        ('A9.06', "A4.08's current, A9.06",
         R["current"]),
        ('A9.06', "A4.08's current, group 9's doc, the flag and the closing list",
         R["current"]),
        ('A4.08', "A4.08's y3 deltas and the pool, group 9's doc",
         [usd["controls"], usd["full"], R["pool_usd"]]),
        ('A4.08', "A4.08's y3 deltas, group 9's list of what it closes",
         [usd["controls"], usd["full"]]),
        ('A4.08', "A4.08's y3 deltas, group 10's doc",
         [usd["controls"], usd["full"]]),
        ('A4.08', "A4.08's y3 deltas, the A10.17-bands decision",
         [usd["controls"], usd["full"]]),
        ('A6.06', 'A6.06 bucket 2 in the group-6 doc',
         [a6["op"][1]] + [a6["mix"]["b2"][k] for k in A606_DOC_ORDER["b2"]]),
        ('A6.06', 'A6.06 bucket 1 in the group-6 doc',
         [a6["op"][0]] + [a6["mix"]["b1"][k] for k in A606_DOC_ORDER["b1"]]),
        ('A6.26', "A6.26's `none`, the chain decision",
         [cov["none"]]),
        ('A6.15', 'controls-only prevention, the chain decision',
         [ctl]),
        ('A6.15', 'full prevention, the chain decision',
         [full]),
        ('A6.15', "A6.15's well-run pools, the chain decision",
         [totc, totf]),
        ('A4.09', "A4.09's achievable pair, the chain decision",
         [x * 100 for x in (write_off()["achievable"]["controls"],
                            write_off()["achievable"]["full"])]),
        ('A4.08', "A4.08's controls-only endpoint, the chain decision",
         [ach["controls"]]),
        ('A4.08', "A4.08's y3 deltas in $K, the chain decision",
         [usd["controls"] * 1000, usd["full"] * 1000]),
    ]


def _printed_restated_21(V):
    """The values the gate's _restated_21_figures reads, keyed (anchor, label) as its entries name them."""
    P = G.pnl()
    wc = G.working_capital(P["cogs"])
    bb = G.borrowing_base(wc)
    Lg = G.ledger(P["ebitda"], wc, bb)
    ebp, eb3 = V["ebitda_pct"], V["ebitda"][2]
    Af, Ac = G.achievable("full"), G.achievable("controls")
    pf, pc = dict(Af["terms_pct"]), dict(Ac["terms_pct"])
    tf, tc = dict(Af["terms"]), dict(Ac["terms"])
    Wp = well_run_pool()["total"]
    res, line = Af["a431_residual"], G.OPDED[2] * 100
    own = G.own_site_dollars(2) / 1e6
    _contribution = G.dtc_contribution()
    dtc = [_contribution["current"][2] * 100, _contribution["achievable"] * 100]
    FC = filing_cascade()
    cnt, dol = [q * 100 for q in FC["by_count"]], [q * 100 for q in FC["by_dollar"]]
    fte = A906_DISPUTE_FTE
    need = fte_for_count_rate(0.25)
    cf507 = cancel_floor()
    EC = equity_call()
    CFD = counterfactual_date()
    ECQ = equity_call(when=CFD)
    ECB = equity_call_band()
    EDD = call_date(timing="before")
    ECE = note(call_size(EDD, timing="before"))
    EDGE = hold_edge()
    DL = _daily()
    DEV = G.daily_events(DL)
    DCH = daily_chain()
    HCF = hold_cut_fit()
    HOLD = hold_day()
    k31 = [max(k for k, d in enumerate(DL["day"]) if d.year == 2023 + t) for t in range(3)]
    if len(set((e["trough_run"].month, e["trough_run"].day) for e in DEV)) != 1:
        raise AssertionError("the daily ledger's trough day differs by year; A9.12 prints one")
    cuts = dict(((r["supplier"], r["weeks"]), r) for r in HCF["rows"])
    worst507 = max(v["miss"][t] for v in cf507.values() for t in range(3) if v["per_year"][t])
    wm = shelf_series()["Walmart"]
    wm_c, wm_s = wm["cost"][1], wm["shelf"][1]
    at600 = [DISPUTE_CAPACITY[t] / (pool(t) * 1e6 / A919_MEAN) * 100 for t in range(3)]
    ab = a1017_absolute_bands()
    R, W = V["a6"]["recovery"], V["a6"]["well_run"]
    ctl, full = W["prevention"]["controls"], W["prevention"]["full"]
    T = test_a_rate()
    n_sets, spans = float(T["sets"]), float(T["spans"])
    rate = [T["pass_pct"], T["fail_pct"]]
    two = float(sum(1 for _, k, _ in RECIPES if k == 2))
    one = float(sum(1 for _, k, _ in RECIPES if k == 1))
    falls = [-100 * x for t in (1, 2) for k in SHARE if SHARE[k][t - 1] and SHARE[k][t]
             for x in [SHARE[k][t] * GROSS[t] / (SHARE[k][t - 1] * GROSS[t - 1]) - 1] if x < 0]
    A = assortment_ratio()
    Wf = wf_fill_risk()
    z, sv = NORM.inv_cdf(0.9), SIGMA_VELOCITY
    M = deduction_mixture()
    H = hire_return()
    rost = [roster(t) for t in range(3)]
    ret, dis, par = ([r[k] for r in rost] for k in ("retailers", "distributors", "partners"))
    lc = [late_cancels(t) for t in range(3)]
    fin = fines(2)
    qsd = SD_INFULL / math.sqrt(3.0)
    return [
        ('A4.31', "A4.31's derived share of billback+MCB dollars, then of gross",
         [INVALID_SHARE * 100, INVALID_TRADE * 100]),
        ('A4.31', "A4.31's event terms: phantom, then double-funded, at A4.18's midpoints",
         [sum(A418_PHANTOM) * 50, sum(A418_DOUBLE) * 50]),
        ('A4.31', "A4.31's and A4.33's wrong-rate term, % of billback+MCB dollars",
         [WRONG_RATE * (sum(A413_BILLBACK) - sum(A413_MCB)) / sum(A413_MCB) * 100]),
        ('A4.31', "A4.31's dollars by window year",
         [INVALID_TRADE * g for g in G.GROSS]),
        ('A10.14', "A10.14's deduction floor: the bucket pool, A4.01's y3 line, A4.31's invalid share, the row and group 10's doc",
         [(OPDED[2] + INVALID_TRADE) * 100, OPDED[2] * 100, INVALID_TRADE * 100]),
        ('A6.04', "A6.04's invalid MCB claim rate, A4.31's share, the row and group 6's doc",
         [INVALID_SHARE * 100]),
        ('A4.33', "A4.33's overbill: the spread in points, then its share of the authorized claim",
         [(sum(A413_BILLBACK) - sum(A413_MCB)) * 50, (sum(A413_BILLBACK) - sum(A413_MCB))
          / sum(A413_MCB) * 100]),
        ('A4.17', "A4.17's free-fill doors at the distributor-served independents, then A7.04's doors",
         [AUTH_ALL["independents"][t] * A704_DOORS["independents"][t] / float(SKUS) for t in range(3)]
         + [float(d) for d in A704_DOORS["independents"]]),
        ('A9.02', "A9.02's achievable, the deduction term: A4.01's line, the bucket pool, A4.31's residual, then each tier's pool less it, the line, the points and $M",
         [line, (G.OPDED[2] + INVALID_TRADE) * 100, res, Wp["full"], res, Af["pool"], line, pf["deductions"],
          tf["deductions"], Wp["controls"], res, Ac["pool"], pc["deductions"], tc["deductions"]]),
        ('A9.02', "A9.02's achievable, group 9's doc: the residual, the pool, the line, the three terms, then both tiers against y3 EBITDA",
         [res, Wp["full"], Af["pool"], line, pf["deductions"], pf["settlement"], dtc[1], dtc[0],
          own / G.GROSS[2] * 100, pf["dtc"], Af["pct"], Af["ebitda"], abs(eb3), Ac["pct"], Ac["ebitda"]]),
        ('A9.13', "the y1 stub, dated on the daily ledger, $K, A9.13 and group 9's doc",
         [DL["stub"] * 1000]),
        ('A9.13', "y1's DPO and its days past the co-packers' net 30, A9.13 and group 9's doc",
         [V["dpo_y1"], V["past_y1"]]),
        ('A4.06', "A4.06's count rate at 25%: the FTE of filing it needs, then the FTE registered, A4.06 and group 4's doc",
         need + [fte[0], fte[2]]),
        ('A9.06', "A4.06's count rate at 25%: the FTE of filing it needs, A9.06 and group 9's doc",
         need),
        ('A9.06', "A9.06's dispute FTE where group 4 cites it",
         [fte[0], fte[2]]),
        ('A4.06', "A4.06's filing rate by count",
         cnt),
        ('A4.06', "A4.06's filing rate by dollar",
         dol),
        ('A9.08', "A9.08's mean deduction, A10.17's derived mean",
         [deduction_mixture()["mean"]]),
        ('A5.02', "A5.02's y3 PO value, Walmart: share, POs, $K a PO, pallets",
         [G.SHARE["Walmart"][2], POS["Walmart"][2], po_value("Walmart", 2)[0] / 1e3, po_value("Walmart", 2)[1]]),
        ('A5.02', "A5.02's y3 PO value, Costco: share, POs, $K a PO, pallets",
         [G.SHARE["Costco"][2], POS["Costco"][2], po_value("Costco", 2)[0] / 1e3, po_value("Costco", 2)[1]]),
        ('A4.06', "A4.06's filing rate by count, then by dollar, group 4's doc",
         cnt + dol),
        ('A9.06', "A9.06's dollar rate, the same capacity filing by size, A9.06 and group 9's doc",
         dol),
        ('A9.06', "A9.06's dollar rate in group 9's closing list",
         dol),
        ('A10.17', "A10.17's by-count filing rate at A9.19's first-registered $600, then at the derived mean, group 10's doc",
         at600 + cnt),
        ('A10.17', "A10.17's by-count filing rate at A9.19's first-registered $600, in its history",
         at600),
        ('A10.17', "A10.17's by-count filing rate at the derived mean",
         cnt),
        ('A10.17', "A10.17's three moved means, late/OTIF, pricing_error and overage, each its band's log-normal mean",
         [A1017_MEAN[k] for k in ("late_otif", "pricing_error", "overage")]),
        ('A10.17', "A10.17's bands read as absolute: the mean, then sigma read as width and read as absolute",
         [ab["mean"], deduction_mixture()["sigma"], ab["sigma"]]),
        ('A4.08', "A4.08's current per bucket-pool dollar, with its formula's inputs, group 4's doc",
         [B1_SHARE, R1_CURRENT, B2_SHARE, B2_SETTLE] + R["current"]),
        ('A4.08', "A4.08's achievable pair at each tier's prevention, with its formula's inputs, group 4's doc",
         [B1_SHARE, F_ACHIEVABLE, R1_ACHIEVABLE, B2_SHARE, ctl, R["achievable"]["controls"], full,
          R["achievable"]["full"]]),
        ('A4.09', "A4.09's current write-off, group 4's doc",
         V["write_off"]),
        ('A4.09', "A4.09's recovered bucket-1 share, then A4.07's rate it reads, group 4's doc",
         V["write_off_b1"] + [R1_CURRENT]),
        ('A4.32', "A4.32 over the operational pool, then the bucket pool, group 4's doc",
         V["bucket_op"] + V["bucket_pool"]),
        ('A2.01', "A2.01's Test A pass rate, then the share that fails, the row and group 2's doc",
         rate),
        ('A2.01', "A2.01's Test A: the sets of club designs Costco can accept, then those spanning two lines",
         [n_sets, spans]),
        ('A2.01', "A2.01's Test A pass rate where group 10 lists it open",
         [rate[0]]),
        ('A2.01', "A2.01's Test A pass rate and its sets, the Costco-assortment marker",
         [rate[0], spans, n_sets]),
        ('A2.01', "A2.01's window-start catalogue: recipes, those at two sizes, the spice at one, then the SKUs",
         [float(len(RECIPES)), two, 2.0, one, 1.0, float(len(SIZE_SLOTS))]),
        ('A2.02', "A2.02's population: designs, then the sellable SKUs at window start, the row and the worklist",
         [float(len(SIZE_SLOTS) + len(CLUB_RECIPE)), float(len(SIZE_SLOTS))]),
        ('A5.38', "A5.38's surviving accounts that decline: small accounts in y2, then Whole Foods direct in y3",
         falls),
        ('A7.28', "A7.28's assortment readings above the signed band's 0.7 top",
         [x for x in A["door_weighted"] + A["unweighted"] if x > 0.7]),
        ('A10.02', "A10.02's live lines in y3: Whole Foods' 90 line's distance and adjacent-pair risk, then the on-time line's",
         [Wf["years"][2]["sd_above"], Wf["years"][2]["any_pair"] * 100,
          quarter_risk(ONTIME[2], SD_ONTIME, 80.0)[2] * 100]),
        ('A10.05', "A10.05's dollars a club-week, then the clubs they are spread over",
         [club_week_dollars(), float(CLUBS)]),
        ('A10.16', "A10.16's plausibility at the registered sigma: p90 over p10, then the top decile's mean over the bottom's",
         [math.exp(2 * z * sv), NORM.cdf(sv - z) / NORM.cdf(-z - sv)]),
        ('A5.07', "A5.07's worst in-year miss under a per-year floor",
         [worst507 * 100]),
        ('A3.14', "A3.14's Walmart 2024 cost a unit, then its case cost",
         [wm_c, wm_c * 12]),
        ('A3.14', "A3.14's erroneous cost per each, the 2024 markup, the erroneous price",
         [wm_c * 12 / 144, wm_s / wm_c, wm_s / 12]),
        ('A3.15', "A3.15's pricing_error deduction a unit at Walmart's 2024 cost",
         [wm_c - wm_c * 12 / 144]),
        ('A3.14', "A3.14's 2024 case cost, group 3's doc",
         [wm_c * 12]),
        ('A3.14', "A3.14's erroneous cost per each, group 3's doc",
         [wm_c * 12 / 144]),
        ('A3.14', "A3.14's 2024 markup, group 3's doc",
         [wm_s / wm_c]),
        ('A3.15', "A3.15's deduction a unit, group 3's doc",
         [wm_c - wm_c * 12 / 144]),
        ('A4.05', "A10.11's y3 fines where A4.05 and group 4 read them: the total, its share of the pool, the ratio",
         [sum(fin.values()), sum(fin.values()) / op_pool(2) * 100, A405_OTIF_SHARE * op_pool(2) / sum(fin.values())]),
        ('A5.07', "A5.07's late cancels: POs a year, then their share of POs, A5.07, A5.10 and group 5's doc",
         [x["total"] for x in lc] + [x["share"] * 100 for x in lc]),
        ('A5.11', "A5.11's internal fill, exact",
         A511_INTERNAL),
        ('A5.11', "A5.11's retailer-scored in-full, exact",
         INFULL),
        ('A5.12', "A5.12's retailer_increase and its band",
         [float(A512_Y1["ri"]), float(A512_Y3["ri"])]
         + [float(A512_Y1["ri"]) * lo_hi * 2 / sum(A504_INCREASE) for lo_hi in A504_INCREASE]
         + [float(A512_Y3["ri"]) * lo_hi * 2 / sum(A504_INCREASE) for lo_hi in A504_INCREASE]),
        ('A5.12', "A5.12's aggregate short-ship",
         [float(c["rr"] + c["cr"] + c["ff"] - c["os"] - c["ri"]) for c in (dict(A512_Y1, os=0.3), dict(A512_Y3, os=0.5))]),
        ('A5.12', "A5.12's internal fill",
         [A511_INTERNAL[0], A511_INTERNAL[2]]),
        ('A5.12', "A5.12's retailer-scored in-full",
         [INFULL[0], INFULL[2]]),
        ('A10.19', "A10.19's size at the signed D0, then its band over D0, and the day each band end dates the note",
         [EC["size"], ECB[0][1], ECB[1][1], D0_BAND[0], float(ECB[0][0].day), float(ECB[1][0].day)]),
        ('A10.19', "A10.19's size and band, group 10's doc",
         [EC["size"], ECB[0][1], ECB[1][1]]),
        ('A10.19', "A10.19's cushion, A9.14's y3 trigger",
         [EC["trigger"]]),
        ('A10.19', "A10.19's hold day",
         [float(HOLD.day)]),
        ('A10.19', "A10.19's cost-index term, $M for CALL_COST_POINTS of A9.16's 2023 cost level",
         [call_cost_sensitivity()]),
        ('A10.19', "A10.19's edge: y2's worst at the run before, the date and size it gives, then the run after",
         [float(EDGE[0]), float(EDD.day), ECE, float(EDGE[2])]),
        ('A10.19', "A10.19's release: the held invoices it pays, then the cash-in-advance orders",
         [EC["held"], EC["cia"]]),
        ('A10.19', "A10.19's Dec 31 draw in y2 and y3 with the note, its line interest and fees, then the annual ledger's",
         [EC["after"]["ends"][1], EC["after"]["ends"][2], EC["after"]["interest"][1], EC["after"]["interest"][2],
          Lg["interest"][1], Lg["interest"][2]]),
        ('A10.19', "A10.19's coupon in y2 and y3, compounding, in $K",
         [EC["coupon"][1] * 1000, EC["coupon"][2] * 1000]),
        ('A10.19', "A10.19's y3 fixed-charge ratio with the note",
         [EC["fccr"][2]]),
        ('A10.19', "A10.19's counterfactual: availability after it, y3 interest and fees, its coupon in y2 and y3",
         [ECQ["tightest"], ECQ["after"]["interest"][2], ECQ["coupon"][1] * 1000, ECQ["coupon"][2] * 1000]),
        ('A10.19', "A10.19's counterfactual date, the row and A10.07",
         [float(CFD.day)]),
        ('A9.02', "A9.02's below-EBITDA coupon in y2 and y3, then the counterfactual's, in $K",
         [EC["coupon"][1] * 1000, EC["coupon"][2] * 1000, ECQ["coupon"][1] * 1000, ECQ["coupon"][2] * 1000]),
        ('A10.07', "A10.07's oldest unpaid invoice at worst, y1 / y2 / y3, the line's own cash",
         [float(c["past"]) for c in DCH]),
        ('A10.07', "A10.07's y1 priority-loss day",
         [float(DCH[0]["first"]["priority"].day)]),
        ('A10.07', "A10.07's y2 days: priority loss, the late fee, the hold",
         [float(DCH[1]["first"][k].day) for k in ("priority", "fee", "hold")]),
        ('A10.07', "A10.07's y2 edge: the run before, then the run after",
         [float(EDGE[0]), float(EDGE[2])]),
        ('A10.07', "A10.07's release: the held invoices the note pays, then the cash-in-advance orders",
         [EC["held"], EC["cia"]]),
        ('A10.07', "A10.07's hold-cut fit: the co-pack lead it slips by",
         [tuple(float(w) for w in PROD_LEAD_WEEKS)]),
        ('A10.07', "A10.07's hold-cut fit: the cover in days, then the net cut's ends",
         [HCF["cover"], cuts[("co-packers", PROD_LEAD_WEEKS[0])]["net"] * 100,
          cuts[("co-packers", PROD_LEAD_WEEKS[1])]["net"] * 100]),
        ('A10.07', "A10.07's hold-cut fit: y3's allocation_shortage budget, then A5.10's share and A5.12's rate",
         [HCF["budget"] * 100, ALLOCATION_SHARE * 100, A512_Y3["cr"]]),
        ('A10.07', "A10.07's hold-cut fit: the gross co-pack slip the cover absorbed",
         [cuts[("co-packers", w)]["gross"] * 100 for w in PROD_LEAD_WEEKS]),
        ('A10.07', "A10.07's hold-cut fit: the in-house lead the materials slip by",
         [tuple(float(w) for w in INHOUSE_LEAD_WEEKS)]),
        ('A10.07', "A10.07's hold-cut fit: the materials' gross slip",
         [cuts[("materials", w)]["gross"] * 100
          for w in INHOUSE_LEAD_WEEKS]),
        ('A9.13', "A9.13's Dec 31 positions: the draw on the line, the stretch behind it, the need",
         [DL["draw"][k] for k in k31] + [DL["late"][k] for k in k31] + [DL["draw"][k] + DL["late"][k] for k in k31]),
        ('A9.13', "A9.13's Dec 31 AR, then AP",
         [x["ar"] for x in DL["dec31"]] + [x["ap"] for x in DL["dec31"]]),
        ('A9.13', "A9.13's daily need at its peak run",
         [e["peak"] for e in DEV]),
        ('A9.13', "A9.13's daily line interest and fees",
         DL["interest"]),
        ('A9.13', "A9.13's fixed-charge ratio on the daily interest",
         [(G.pnl()["ebitda"][t] - G.CAPEX) / DL["interest"][t] for t in range(3)]),
        ('A9.13', "A9.13's late-fee reading",
         DL["late_fee"]),
        ('A9.13', "A9.13's spring days",
         [float(d.day) for d in DL["springs"]]),
        ('A9.13', "A9.13's part-held runs, then the first one's day",
         [float(len(DL["held"])), float(DL["held"][0][0].day)]),
        ('A9.12', "A9.12's trough day, every window year, A9.12 and A9.13",
         [float(DEV[0]["trough_run"].day)]),
        ('A5.02', "A5.02's POs a year, group 5's doc",
         [float(sum(n[t] for n in POS.values())) for t in range(3)]),
        ('A5.02', "A5.02's order lines a year at A5.37's means, group 5's doc",
         [float(po_lines(t)) for t in range(3)]),
        ('A5.02', "A5.02's Walmart POs, group 5's doc",
         [float(x) for x in POS["Walmart"]]),
        ('A5.02', "A5.02's KeHE POs, group 5's doc",
         [float(x) for x in POS["KeHE"]]),
        ('A5.02', "A5.02's small-account orders, group 5's doc",
         [float(x) for x in POS["small"]]),
        ('A5.32', "A5.32's Walmart DCs, group 5's doc",
         [float(x) for x in WM_DCS]),
        ('A5.32', "A5.32's KeHE DCs, group 5's doc",
         [float(dcs("KeHE", t)) for t in range(3)]),
        ('A5.32', "A5.32's DPI DCs, group 5's doc",
         [float(dcs("DPI", t)) for t in range(3)]),
        ('A5.20', "A1.10's roster: retailers then distributors, A5.20",
         ret + dis),
        ('A5.20', "A1.10's roster: EDI partners, A5.20",
         par),
        ('A4.27', "A1.10's roster: retailers, A4.27",
         ret),
        ('A4.27', "A1.10's roster: distributors, A4.27",
         dis),
        ('A1.10', "A1.10's roster: retailers then distributors, group 4's doc",
         ret + dis),
        ('A1.10', "A1.10's roster: retailers, distributors, then partners, group 5's doc",
         ret + dis + par),
        ('A10.02', "A10.02's dead in-full drop line: y3's distance in quarterly sd, that sd, then y2's and y1's",
         [(INFULL[2] - 85.0) / qsd, qsd, (INFULL[1] - 85.0) / qsd, (INFULL[0] - 85.0) / qsd]),
        ('A9.06', "A9.06's deduction counts",
         filing_cascade()["count"]),
        ('A9.08', "A9.08's loaded analyst: the wage share, then the loaded cost",
         [G.WAGE_SHARE, H["loaded"]]),
        ('A9.08', "A9.08's recovery per dispute-hour, bucket-1 then achievable, each beside the rate it reads, the row",
         [R1_CURRENT, H["rate"]["bucket1"], R1_ACHIEVABLE, H["rate"]["achievable"]]),
        ('A9.08', "A9.08's recovery per dispute-hour, bucket-1 then achievable, each beside the rate it reads, group 9's doc",
         [H["rate"]["bucket1"], R1_CURRENT, H["rate"]["achievable"], R1_ACHIEVABLE]),
        ('A9.08', "A9.08's hire-me return: the analyst's hourly cost, the bucket-1 recovery, the multiple",
         [H["hourly"], H["rate"]["bucket1"], H["multiple"]]),
        ('A9.15', "A9.15's deductions per invoice, y1 -> y3",
         [deductions_per_invoice(0), deductions_per_invoice(2)]),
        ('A9.19', "A9.19's mean, median and sigma, group 9's doc",
         [M["mean"], M["median"], M["sigma"]]),
        ('A9.19', "A9.19's dollar shares of the largest half and the largest tenth, group 9's doc",
         [top_dollar_share(0.5, M) * 100, top_dollar_share(0.1, M) * 100]),
        ('A5.07', "A5.07's window miss odds, retailer order cancels",
         [cf507[(a, "order_retailer")]["window_miss"] * 100 for a in ("Kroger", "Regional", "WF", "Sprouts", "Costco", "DPI")]),
        ('A5.07', "A5.07's window miss odds, Cinderhaven order cancels",
         [cf507[(a, "order_cinderhaven")]["window_miss"] * 100
          for a in ("UNFI", "KeHE", "Kroger", "Regional", "WF", "Sprouts", "Costco", "DPI")]),
        ('A5.07', "A5.07's line-level rates by account, retailer then Cinderhaven",
         [a507_line_rate(a, k) * 100 for a in ("Walmart", "Kroger", "WF", "Sprouts", "Regional", "Costco", "UNFI",
                                                 "KeHE", "DPI", "small") for k in ("line_retailer", "line_cinderhaven")]),
        ('A5.07', "A5.07's window miss odds, line-level: retailer then Cinderhaven, then Regional's Cinderhaven",
         [cf507[(a, k)]["window_miss"] * 100 for a in ("WF", "Sprouts", "Costco", "DPI")
          for k in ("line_retailer", "line_cinderhaven")] + [cf507[("Regional", "line_cinderhaven")]["window_miss"] * 100]),
    ]


def _printed_group11(V):
    """The values the gate's group11_figures reads, keyed (anchor, label) as its entries name them."""
    return [
        ('A4.32', 'A4.32 over the operational pool, then the bucket pool',
         V["bucket_op"] + V["invalid_of_operational"] + V["bucket_pool"]),
        ('A6.06', 'A6.06 bucket 2, the within-bucket mix',
         V["a606_b2"]),
        ('A6.06', 'A6.06 bucket 1, the within-bucket mix',
         V["a606_b1"]),
        ('A4.09', "A4.09's current write-off, and its achievable pair",
         V["write_off"] + V["write_off_ach"]),
        ('A4.09', "A4.09's recovered bucket-1 share, the input that went stale",
         V["write_off_b1"]),
        ('A11.21', 'the factor and the launch-free solve, the slice-1 decision',
         [V["acct"], V["launch_free"]]),
        ('A10.16', "A10.16's floor delists, the slice-1 decision",
         [V["delists"][2]]),
        ('A11.21', "the factor solved on the window, then the launch-free solve, the doc's summary",
         [V["acct"], V["launch_free"]]),
        ('A11.21', "the factor and the launch-free solve, group 10's doc",
         [V["acct"], V["launch_free"]]),
        ('A11.23', 'MAPE at 0.60',
         [V["mape"][0] * 100]),
        ('A11.23', "MAPE at the band's ends",
         [(V["mape"][1] * 100, V["mape"][2] * 100)]),
        ('A7.09', "A10.16's pre-period delists where A7.09 names them",
         [V["pre_delists"][2]]),
        ('A10.16', 'A10.16 floor delists: Kroger, Walmart, total',
         V["delists"]),
        ('A10.16', "A10.16's pre-period exits and the strikes it carries into y1: Kroger, Walmart, total",
         V["pre_delists"] + V["carried_strikes"]),
        ('A10.16', "A10.16 Kroger's floor delists, row",
         [V["delists"][0]]),
        ('A10.16', "A10.16 Walmart's floor delists, then the total, row",
         V["delists"][1:]),
        ('A10.16', 'A10.16 authorized below the floor per review: Kroger, Walmart',
         V["below"][0] + V["below"][1]),
        ('A10.04', 'A10.04 Kroger below the floor per review, then its delists',
         V["below"][0] + [V["delists"][0]]),
        ('A10.09', "A10.16's floor delists, cited in A10.09 and A10.18",
         [V["delists"][2]]),
        ('A10.16', "A10.16's floor delists, group 10's summary table",
         [V["delists"][2]]),
        ('A10.16', "A10.16's floor delists, the decisions",
         [V["delists"][2]]),
        ('A10.16', "A10.16's floor delists, group 11's findings",
         [V["delists"][2]]),
        ('A10.16', "A10.16's pre-period delists and the strikes carried into y1, group 11's finding 1",
         [V["pre_delists"][2], V["carried_strikes"][2]]),
        ('A10.16', "A10.16's pre-period delists and the strikes carried into y1, group 11's owner list",
         [V["pre_delists"][2], V["carried_strikes"][2]]),
        ('A10.16', "A10.16's floor delists by banner, Kroger then Walmart, group 11's finding 1",
         V["delists"][:2]),
        ('A10.16', "A10.16's Kroger floor delists, group 11's owner list",
         [V["delists"][0]]),
        ('A10.16', "A10.16's floor delists, group 11's owner list",
         [V["delists"][2]]),
        ('A9.13', 'the y1 exceedance: $K, days, share of a run, the run, days of invoicing, DPO, days past terms',
         [V["short"][0] * 1000, V["dpo_days"][0], V["run_share"], V["ap_run"] * 1000, V["invoice_days"], V["dpo_y1"],
          V["past_y1"]]),
        ('A11.05', "A11.05's KeHE DCs, the row and group 11's doc",
         [float(dcs("KeHE", t)) for t in range(3)]),
        ('A10.16', "A10.16's tail-band check: the bottom quintile at the catalogue multiplier",
         [A703_MEAN_Y3 * NORM.cdf(NORM.inv_cdf(0.2) - SIGMA_VELOCITY) / 0.2]),
        ('A11.28', "A11.28's variance shares: the week term, then the door term, of A7.03's variance",
         [SIGMA_WEEK ** 2 / SIGMA_VELOCITY ** 2 * 100, SIGMA_DOOR ** 2 / SIGMA_VELOCITY ** 2 * 100]),
        ('A11.27', "A11.27's band-end solves: the account target at the door band's ends",
         [account_target(SIGMA_DOOR_BAND[0]), account_target(SIGMA_DOOR_BAND[1])]),
        ('A7.03', "A7.03's y3 mean where group 11 reads it, and the quintiles at both sigmas",
         [A703_MEAN_Y3,
          A703_MEAN_Y3 * NORM.cdf(SIGMA_VELOCITY - NORM.inv_cdf(0.8)) / 0.2,
          A703_MEAN_Y3 * NORM.cdf(NORM.inv_cdf(0.2) - SIGMA_VELOCITY) / 0.2,
          A703_MEAN_Y3 * NORM.cdf(SIGMA_ACCOUNT - NORM.inv_cdf(0.8)) / 0.2,
          A703_MEAN_Y3 * NORM.cdf(NORM.inv_cdf(0.2) - SIGMA_ACCOUNT) / 0.2]),
        ('A10.16', "A10.16's Walmart cut: the modular's bottom quintile as an index",
         [math.exp(math.log(100.0) - SIGMA_VELOCITY ** 2 / 2
                   + SIGMA_VELOCITY * NORM.inv_cdf(WAL_MODULAR_QUINTILE))]),
        ('A11.21', 'the factor on the window differs from the launch-free solve',
         abs(V["acct"] - V["launch_free"]) > 0.05),
    ]


def _printed_group10(V):
    """The values the gate's check_group10_figures reads, keyed (anchor, label) as its entries name them."""
    fin = fines(2)
    total = sum(fin.values())
    C = coherence_tolerances()
    inflight = A421_UNITEMIZED * A1013_TRAILING_DAYS / 365.0
    lead, cyc = A506_LEAD_MAX, A502_CYCLE_DAYS
    W = wf_fill_risk()
    B = breadth_concurrency()
    S, RC = syndicated_coverage(), rationalization_cuts()
    A = assortment_ratio()
    Sh, Mk, Sc = shelf_series(), markup_series(), scan_identity()
    Ch = channel_velocity()
    ba = Mk["by_account"]
    kro, wal, reg = late_days("Kroger"), late_days("Walmart"), late_days("Regional")
    acv, pen = acv_share(), penetration()
    return [
        ('A10.03', 'A10.03 quarter risk, on-time vs 80',
         [quarter_risk(ONTIME[t], SD_ONTIME, 80.0)[0] * 100 for t in range(3)]),
        ('A10.03', 'A10.03 pair risk in a year',
         [quarter_risk(ONTIME[t], SD_ONTIME, 80.0)[2] * 100 for t in range(3)]),
        ('A10.08', 'A10.08 breadth, SKUs per month',
         [STOCKOUT[t] * ACTIVE_SKUS[t] for t in range(3)]),
        ('A10.13', 'A10.13 tie-out tolerance',
         [C["tie_out"] * 100]),
        ('A10.13', 'A10.13 the in-flight term inside it',
         [inflight * 100]),
        ('A10.13', 'A10.13 delist-to-last-PO lag, the four accounts',
         [C["lag"][k] for k in ("Walmart", "Kroger", "UNFI", "Costco")]),
        ('A10.13', "A10.13 the lag's parts, lead time plus one cycle",
         [lead["Walmart"], cyc["Walmart"], lead["Kroger"], cyc["Kroger"],
          lead["UNFI"], cyc["UNFI"], lead["Costco"], cyc["Costco"]]),
        ('A10.13', 'A10.13 the OTIF-to-fill gap by year',
         C["gap"]),
        ('A10.13', 'A10.13 the band that derivation gives',
         list(C["band"])),
        ('A10.04', "A10.04 the 90 line's distance in quarterly sd",
         [y["sd_above"] for y in W["years"]]),
        ('A10.04', 'A10.04 a stated y1 pair, as one in N',
         [W["years"][0]["one_in_named"]]),
        ('A10.04', 'A10.04 the y3 risks, a stated pair then any adjacent pair',
         [W["years"][2]["named_pair"] * 100, W["years"][2]["any_pair"] * 100]),
        ('A10.08', 'A10.08 the breadth mode by year',
         [b["mode"] for b in B]),
        ('A10.08', 'A10.08 a three-SKU month, exactly',
         [b["p_story"] * 100 for b in B]),
        ('A10.08', "A10.08 the y3 mode's own probability",
         [B[2]["p_mode"] * 100]),
        ('A10.08', 'A10.08 at least three out',
         [b["p_at_least"] * 100 for b in B]),
        ('A7.28', 'A7.28 the coverage parts, then the coverage',
         [s["direct"] for s in S] + [s["distributor"] for s in S] + [s["reported"] for s in S]
         + [s["coverage"] for s in S]),
        ('A10.18', 'A10.18 cuts by account, then the authorizations',
         [a["cuts"] for a in RC["accounts"]] + [RC["authorizations"]]),
        ('A10.13', "A10.13 the gap's window mean",
         [C["gap_mean"]]),
        ('A7.28', 'A7.28 the assortment ratio, door-weighted then unweighted',
         A["door_weighted"] + A["unweighted"]),
        ('A3.08', "A3.08 Kroger's stepped shelf",
         Sh["Kroger"]["shelf"]),
        ('A3.08', 'A3.08 realized margins by banner and year',
         sum((Sh[b]["margin"] for b in ("WF", "Sprouts", "Kroger", "Regional", "Walmart", "Costco")), [])),
        ('A3.28', 'A3.28 the tolerance window its step pattern holds over',
         list(tolerance_window())),
        ('A7.29', 'A7.29 the y3 markup by account',
         [ba[k][2] for k in ("Walmart", "Kroger", "Regional", "Sprouts", "WF", "UNFI", "KeHE", "DPI")]),
        ('A7.29', "A7.29 Walmart's markup by year",
         ba["Walmart"]),
        ('A7.29', "A7.29 Whole Foods' markup by year",
         ba["WF"]),
        ('A7.29', "A7.29 Kroger's markup by year",
         ba["Kroger"]),
        ('A7.29', 'A7.29 the weighted markup',
         Mk["weighted"]),
        ('A7.03', 'A7.03 the markup it reads',
         Mk["weighted"]),
        ('A7.03', 'A7.03 measured retail $M',
         [x["retail"] for x in Sc]),
        ('A7.03', 'A7.03 measured units, millions',
         [x["units"] for x in Sc]),
        ('A7.26', 'A7.26 every live door-SKU-week in the grid',
         [x["live_all"] for x in Sc]),
        ('A7.04', 'A7.04 the grown door plan by banner',
         sum(([float(d) for d in A704_DOORS[b]] for b in ("Walmart", "Kroger", "WF", "Regional", "independents",
                                                            "Sprouts", "Costco")), [])),
        ('A7.04', 'A7.04 the 2026-09-05 plan it was grown from',
         sum(([float(d) for d in A704_BASE[b]] for b in ("Walmart", "Kroger", "WF", "Regional", "independents",
                                                           "Sprouts")), [])),
        ('A7.04', 'A7.04 the door totals',
         [float(sum(A704_DOORS[b][t] for b in A704_DOORS)) for t in range(3)]),
        ('A7.04', 'A7.04 Supercenters per Walmart DC on the grown plan',
         [A704_DOORS["Walmart"][t] / float(k) for t, k in enumerate(WM_DCS)]),
        ('A7.04', "A7.04 the door totals, the doc's ladder table",
         [float(sum(A704_DOORS[b][t] for b in A704_DOORS)) for t in range(3)]),
        ('A7.26', "A7.26 door-SKUs, the doc's ladder table",
         [float(sum(A704_DOORS[b][t] * AUTH_ALL[b][t] for b in A704_DOORS)) for t in range(3)]),
        ('A7.26', "A7.26 scan rows a year and the window, the doc's ladder table",
         [float(sum(A704_DOORS[b][t] * AUTH_ALL[b][t] for b in A704_DOORS) * 52) for t in range(3)]
         + [sum(sum(A704_DOORS[b][t] * AUTH_ALL[b][t] for b in A704_DOORS) for t in range(3)) * 52 / 1e6]),
        ('A7.14', "A7.14 supplier-caused share of the not-on-shelf weeks by year, %",
         [supplier_share(t) * 100 for t in range(3)]),
        ('A7.15', "A7.14's supplier-caused share as A7.15 plants it, %",
         [supplier_share(t) * 100 for t in range(3)]),
        ('A7.15', 'A7.15 gap-weeks and episodes a year (thousands), and episodes per door-SKU',
         [x["gap_weeks"] / 1e3 for x in void_episodes()] + [x["episodes"] / 1e3 for x in void_episodes()]
         + [x["per_door_sku"] for x in void_episodes()]),
        ('A7.28', "A7.28 coverage at the reporting band's ends, 50% then 70%",
         coverage_sensitivity()[0] + [70.0] + coverage_sensitivity()[1]),
        ('A7.05', 'A7.05 format mix at y3 by authorized doors, shares',
         [x * 100.0 / sum(A704_DOORS[b][2] for b in A704_DOORS) for x in (
             A704_DOORS["Kroger"][2] + A704_DOORS["Regional"][2], A704_DOORS["Walmart"][2],
             A704_DOORS["WF"][2] + A704_DOORS["Sprouts"][2] + A704_DOORS["independents"][2],
             A704_DOORS["Costco"][2])]),
        ('A7.05', 'A7.05 format mix at y3 by authorized doors, counts',
         [float(x) for x in (A704_DOORS["Kroger"][2] + A704_DOORS["Regional"][2], A704_DOORS["Walmart"][2],
             A704_DOORS["WF"][2] + A704_DOORS["Sprouts"][2] + A704_DOORS["independents"][2],
             A704_DOORS["Costco"][2], sum(A704_DOORS[b][2] for b in A704_DOORS))]),
        ('A3.16', "A3.16 the 60 drained stores as a share of one Walmart DC's stores, y2",
         [60 * 100.0 / (A704_DOORS["Walmart"][1] / float(WM_DCS[1]))]),
        ('A7.26', 'A7.26 door-SKUs on the grown plan',
         [float(sum(A704_DOORS[b][t] * AUTH_ALL[b][t] for b in A704_DOORS)) for t in range(3)]),
        ('A7.26', 'A7.26 scan rows a year, and the window',
         [float(sum(A704_DOORS[b][t] * AUTH_ALL[b][t] for b in A704_DOORS) * 52) for t in range(3)]
         + [sum(sum(A704_DOORS[b][t] * AUTH_ALL[b][t] for b in A704_DOORS) for t in range(3)) * 52 / 1e6]),
        ('A7.03', "A7.03 mass velocity and its derived bands, each year's own",
         Ch["mass"]["velocity"] + sum((list(b) for b in Ch["mass"]["bands"]), [])),
        ('A7.03', "A7.03 grocery velocity and its derived bands, each year's own",
         Ch["grocery"]["velocity"] + sum((list(b) for b in Ch["grocery"]["bands"]), [])),
        ('A7.03', 'A7.03 natural velocity, against the registered band',
         Ch["natural"]["velocity"]),
        ('A7.03', 'A7.03 the three channel breaches',
         [Ch["mass"]["velocity"][0], Ch["mass"]["bands"][0][1], Ch["natural"]["velocity"][0], Ch["natural"]["bands"][0][1],
          Ch["natural"]["velocity"][1], Ch["natural"]["bands"][1][1]]),
        ('A3.08', "A3.08 margin above A3.06's ceiling, y1 and y2",
         sum(([Sh[b]["above_ceiling"][0], Sh[b]["above_ceiling"][1]] for b in ("Regional", "Costco", "WF")), [])),
        ('A7.03', 'A7.03 measured live door-SKU-weeks',
         [x["live_meas"] for x in Sc]),
        ('A7.03', 'A7.03 velocity, units per SKU per store per week',
         [x["upw"] for x in Sc]),
        ('A7.03', 'A7.03 dollars per measured door-SKU-week',
         [x["dpw"] for x in Sc]),
        ('A7.03', 'A7.03 implied reporting door-SKUs at the band midpoint',
         [x["implied"] for x in Sc]),
        ('A7.03', "A7.03 its measured live door-SKUs on A7.26's grid beside them",
         [x["grid_meas"] for x in Sc]),
        ('A7.03', 'A7.03 the implied-to-registered ratio',
         [x["implied_ratio"] for x in Sc]),
        ('A7.07', 'A7.07 measured door-SKU-weeks and units, growth y1 to y3',
         [Sc[2]["live_meas_vs_y1"], Sc[2]["units_vs_y1"]]),
        ('A7.07', 'A7.07 velocity by year',
         [x["upw"] for x in Sc]),
        ('A7.07', 'A7.07 the headline, units, then y2',
         [Sc[2]["upw_vs_y1"], Sc[1]["upw_vs_y1"]]),
        ('A10.03', "A10.03 A5.17's below-target shares, in-full then on-time",
         [a * 100 for a, _ in reproduce_a517()] + [b * 100 for _, b in reproduce_a517()]),
        ('A10.03', "A10.03 the quarter mean's sd",
         [SD_ONTIME / math.sqrt(3.0)]),
        ('A10.03', 'A10.03 two consecutive quarters below the line',
         [quarter_risk(ONTIME[t], SD_ONTIME, 80.0)[1] * 100 for t in range(3)]),
        ('A7.07', 'A7.07 dollars beside it',
         [Sc[0]["dpw"], Sc[2]["dpw"], Sc[2]["dpw_vs_y1"], Sc[1]["dpw_vs_y1"]]),
        ('A10.11', 'A10.11 y3 fines: the total, then by account',
         [total] + [fin[k] for k in ("Walmart", "Kroger", "UNFI", "KeHE", "Costco", "Regional")]),
        ('A10.11', "A10.11 y3 fines by account, then the total, group 10's table",
         [fin[k] for k in ("Walmart", "Kroger", "UNFI", "KeHE", "Costco", "Regional")] + [total]),
        ('A10.11', 'A10.11 y3 fines as a share of the pool',
         [total / op_pool(2) * 100]),
        ('A10.11', "A10.11 the ratio of A4.05's late/OTIF share to the fines",
         [A405_OTIF_SHARE * op_pool(2) / total]),
        ('A10.11', "A10.11 Walmart's fine, then the correlated and exclusive totals",
         [fin["Walmart"], sum(fines(2, "correlated").values()), sum(fines(2, "exclusive").values())]),
        ('A10.11', "A10.11 Walmart's non-compliant case share",
         [noncompliant_share(2, "independent") * 100]),
        ('A10.11', "A10.11 Kroger's E[days | fined], then the late-cancel shares at Kroger, Walmart and Regional",
         [kro[0], (1 - kro[1]) * 100, (1 - wal[1]) * 100, (1 - reg[1]) * 100]),
        ('A10.11', 'A10.11 late cancels a year',
         [late_cancels(t)["total"] for t in range(3)]),
        ('A10.11', 'A10.11 the lateness means: Walmart, Kroger, Regional',
         [LATE_MEAN["Walmart"], LATE_MEAN["Kroger"], LATE_MEAN["Regional"]]),
        ('A10.08', 'A10.08 Walmart in-full below its tolerance line, share of months',
         [phi((90.0 - INFULL[t]) / SD_INFULL) * 100 for t in range(3)]),
        ('A10.08', 'A10.08 Walmart on-time below its tolerance line, share of months',
         [phi((85.0 - ONTIME[t]) / SD_ONTIME) * 100 for t in range(3)]),
        ('A10.13', 'A10.13 the raw band, before the zero clip',
         list(C["raw_band"])),
        ('A6.02', "A6.02 manual line error at the character, across the reading band, %",
         [manual_line("character", True), manual_line("character")]),
        ('A6.02', "A6.02 manual line error disciplined, across the reading band, %",
         [manual_line("disciplined", True), manual_line("disciplined")]),
        ('A6.02', "A6.02 manual-to-EDI ratio at the character, across both bands",
         edi_ratio()["character_band"]),
        ('A6.02', "A6.02 manual-to-EDI ratio disciplined, across both bands",
         edi_ratio()["disciplined_band"]),
        ('A6.16', "A6.16 manual-vs-EDI spread floor, derived",
         [spread_floor_edi()]),
        ('A6.02', "A6.02 manual-to-EDI ratio at A6.32's point, character then disciplined",
         [edi_ratio()["character"][1], edi_ratio()["disciplined"][1]]),
        ('A9.16', "A9.16 COGS inflation by year, contract-weighted, %",
         [g * 100 for g in G.COGS_INDEX_YOY]),
        ('A9.16', "A9.16 cost level in 2023 and 2024, 2025 = 1",
         G._cost_index()[:2]),
        ('A3.01', "A9.16 cost level relative to 2025, as A3.01 prints it",
         G._cost_index()),
        ('A9.02', "A9.16 cost level relative to 2025, as A9.02 prints it",
         G._cost_index()),
        ('A1.01', "A1.01 the second endpoint's band top, sustained y1 growth, $M",
         [G.GROSS_PRE * (GROSS[0] / G.GROSS_PRE) ** 3]),
        ('A7.04', 'A7.04 %ACV at y3, Walmart',
         [acv["Walmart"]]),
        ('A7.04', "A7.04 %ACV at y3, Walmart's band top",
         [acv["Walmart_top"]]),
        ('A7.01', 'A7.01 Supercenter grocery ACV, $M',
         [supercenter_acv()]),
        ('A7.01', 'A7.01 a Supercenter against a Sprouts box',
         [supercenter_acv() / A701_WALMART["sprouts"]]),
        ('A7.01', "A7.01 Walmart U.S. grocery, % of net sales",
         [A701_WALMART["grocery"] * 100.0 / A701_WALMART["sales"]]),
        ('A7.01', "A7.01 Costco U.S. revenue a warehouse, $M",
         [A701_COSTCO_US * 1e3 / A704_UNIVERSE["Costco"]]),
        ('A7.04', "A7.04 %ACV at y3, Whole Foods at the band's low",
         [acv["WF_low"]]),
        ('A7.04', 'A7.04 %ACV at y3, Kroger',
         [acv["Kroger"]]),
        ('A7.04', 'A7.04 %ACV at y3, Whole Foods',
         [acv["WF"]]),
        ('A7.04', 'A7.04 %ACV at y3, Sprouts',
         [acv["Sprouts"]]),
        ('A7.04', 'A7.04 %ACV at y3, Costco',
         [acv["Costco"]]),
        ('A7.20', 'A7.20 household penetration in units',
         pen),
    ]


def _printed_by_key():
    """The entries the gate builds in a loop, one a key, as one value each: A10.03's quarter table by year, A4.05's
    type mix and A5.38's account table in their docs, 05:154's revision-presence groups, and A7.04's Sprouts doors
    against the universe its cap reads."""
    groups = []
    R = revision_presence()
    for leg, name in (("increase", "increase"), ("cinderhaven", "Cinderhaven-initiated"),
                      ("retailer_reduction", "retailer cut")):
        for per_year, basis in ((False, "over the window"), (True, "per window year")):
            grp = sorted([(a, v) for (a, l), v in R.items() if l == leg and v["per_year"] == per_year
                          and v["fail"] >= 0.01], key=lambda x: -x[1]["fail"])
            if grp:
                groups.append((name, basis, [(a, 1 / v["fail"]) for a, v in grp]))
    table = {}
    for key in SHARE:
        table[key] = [SHARE[key][t] * 100 for t in range(3)] + [SHARE[key][t] * GROSS[t] / GROSS[0] * 100
                                                               for t in range(3)]
    return [('A10.03', "A10.03 the quarter table, by year: one quarter, two consecutive, a pair in the year",
             [[x * 100 for x in quarter_risk(ONTIME[t], SD_ONTIME, 80.0)] for t in range(3)]),
            ('A4.05', "A4.05's type mix in group 4's doc, by type", dict((k, float(v)) for k, v in A405_SHARE.items())),
            ('A5.38', "A5.38's account table in group 5's doc: shares, then dollars on A1.01's index, by account",
             table),
            ('A5.07', "05:154's revision-presence groups: (leg, basis, [(account, one in N)]), by falling odds",
             groups),
            ('A7.04', "A7.04's Sprouts doors in y3, then the universe its cap reads",
             [A704_DOORS["Sprouts"][2], A704_UNIVERSE["Sprouts"]])]


def _derived_dates():
    """The dates U16's daily ledger derives, as the rows print them (owner, 2026-10-22): A10.19's date, the first hold,
    the counterfactual, the band's two dates and the AP-timing edge's; the springs and first part-held run on the
    line's own cash; each year's peak day and trough run; A10.07's first consequences by year (the line's own for y1
    and y2, the note's for y3); y2's worst days past terms at the three AP timings, and the hold line they meet."""
    L = _daily()
    ch = daily_chain()
    ev = G.daily_events(L)
    return dict(call=CALL_DATE, hold=hold_day(), counterfactual=counterfactual_date(),
                band=[d for d, _ in equity_call_band()], edge=call_date(timing="before"),
                springs=L["springs"], first_held=L["held"][0][0],
                peak_days=[e["peak_day"] for e in ev], trough_runs=[e["trough_run"] for e in ev],
                chain_first=[ch[0]["first"], ch[1]["first"], daily_chain(equity_call()["after"])[2]["first"]],
                hold_edge=hold_edge(), hold_line=SUPPLIER_DAYS[2])


def outputs(acct=None):
    """U21's entry function: what the gate checks and the seeders read, one object (regen plan U21).

    `printed` holds every value the registry prints from this generator, keyed by the anchor id that prints it and
    then by the gate entry that reads it, at full precision; beside the entries, the solved account factor and the
    dates U16's daily ledger derives. Given `acct`, the solved factor, account_sigma() returns it and group 11's
    solve_account_factor() is never called; omitted, the factor is solved as it is today."""
    if acct is not None:
        _SOLVED["acct"] = acct
    acct = account_sigma()
    V = dict(G._values())
    V.update(_values(acct))
    printed = {}
    for fn in (_printed_a6_chain, _printed_restated_21, _printed_group11, _printed_group10):
        for anchor, label, value in fn(V):
            printed.setdefault(anchor, {})[label] = value
    for anchor, label, value in _printed_by_key():
        printed.setdefault(anchor, {})[label] = value
    printed.setdefault("A11.27", {})["the SKU x account factor's log-sd, solved on the window's own carried sets"] = acct
    printed.setdefault("A10.19", {})["the dates U16's daily ledger derives"] = _derived_dates()
    return dict(printed=printed)


def main():
    print("GROUP 10 FLOORS -- every count derived from a registered row")
    print("")
    print("FREE INPUTS (everything else is computed)")
    for name, val, status in INPUTS:
        print("   %-40s %-46s %s" % (name, val, status))

    print("")
    print("CHECK 0  the model reproduces A5.17 before it is extended")
    published = [(0.93, 1.00), (0.87, 0.93), (0.96, 0.98)]
    ok = True
    for year, ((i_calc, o_calc), (i_pub, o_pub)) in enumerate(zip(reproduce_a517(), published)):
        hit = abs(round(i_calc, 2) - i_pub) < 0.005 and abs(round(o_calc, 2) - o_pub) < 0.005
        ok = ok and hit
        print("   y%d  in-full below target %s vs A5.17's %s | on-time %s vs %s   %s"
              % (year + 1, _pct(i_calc), _pct(i_pub), _pct(o_calc), _pct(o_pub),
                 "reproduces" if hit else "*** DOES NOT REPRODUCE ***"))
    print("   %s" % ("all six reproduce -- A10.03 and A10.08 extend this model, they do not "
                     "replace it" if ok else "*** the model disagrees with A5.17 ***"))

    print("")
    print("A10.03  the Walmart consequence chain -- is the drop line a live draw?")
    for year in range(3):
        p, pair, yr = quarter_risk(ONTIME[year], SD_ONTIME, 80.0)
        print("   y%d on-time mean %.1f  P(quarter < 80) %5.1f%% | two consecutive %4.1f%% | "
              "at least one pair in the year %4.1f%%"
              % (year + 1, ONTIME[year], p * 100, pair * 100, yr * 100))
    for year in range(3):
        p, pair, yr = quarter_risk(INFULL[year], SD_INFULL, 85.0)
        print("   y%d in-full mean %.1f  P(quarter < 85) %5.1f%% | two consecutive %4.1f%% | "
              "year %4.1f%%" % (year + 1, INFULL[year], p * 100, pair * 100, yr * 100))
    print("   -> the drop line is a DRAW, not a scheduled event. Order reduction depth is")
    print("      A5.04's %d%% median (band %d-%d%%) on the affected SKUs for one quarter."
          % (CUT_DEPTH[1] * 100, CUT_DEPTH[0] * 100, CUT_DEPTH[2] * 100))

    print("")
    print("A10.08  breach frequency of the TOLERANCE line, by account and year")
    print("   Walmart in-full vs 90   %s" %
          " / ".join(_pct(phi((90.0 - INFULL[t]) / SD_INFULL)) for t in range(3)))
    print("   Walmart on-time vs 85   %s   <- on-time LIVES below tolerance" %
          " / ".join(_pct(phi((85.0 - ONTIME[t]) / SD_ONTIME)) for t in range(3)))
    print("   breadth, A5.21 stockout x the live catalogue (%s SKUs)   %s SKUs in any month"
          % (" / ".join(str(n) for n in ACTIVE_SKUS),
             " / ".join("%.1f" % (STOCKOUT[t] * ACTIVE_SKUS[t]) for t in range(3))))
    print("   reaction windows (A5.36 cadence x the consecutive-period rule):")
    print("      Walmart 2 quarters | Kroger 2 quarters then the annual review | WF 2 quarters")
    print("      UNFI and KeHE 2 weeks -> CAP | Costco per rotation | suppliers 45 days")

    print("")
    print("A10.11  late/OTIF fine dollars, and the A4.05 cross-check")
    for year in (2,):
        f = fines(year)
        for k in sorted(f, key=lambda x: -f[x]):
            if f[k]:
                print("      %-10s $%.4fM" % (k, f[k]))
        tot = sum(f.values())
        print("      %-10s $%.4fM" % ("TOTAL", tot))
        print("   A4.05 at %d%% of the $%.2fM y3 pool = $%.3fM  ->  %.2fx the mechanisms"
              % (A405_OTIF_SHARE * 100, op_pool(year), A405_OTIF_SHARE * op_pool(year),
                 A405_OTIF_SHARE * op_pool(year) / tot))
        print("   share of the pool the mechanisms imply: %.1f%%, not %d%%"
              % (tot / op_pool(year) * 100, A405_OTIF_SHARE * 100))
        for a in ("Walmart", "Kroger", "Regional"):
            d, mass = late_days(a)
            print("   %s lateness: geometric mean %.1f d, capped at A5.07's %d -> E[days | fined] "
                  "%.4f, %.2f%% of late POs become cancels" % (a, LATE_MEAN[a], LATE_CANCEL_DAYS, d, (1 - mass) * 100))
        print("   every other account at Kroger's %.1f d until a window is registered" % LATE_MEAN["Kroger"])
        print("   late cancels, every account: %s POs = %s%% of POs by year, inside A5.07's 1.0%%"
              % (" / ".join("%.1f" % late_cancels(t)["total"] for t in range(3)),
                 " / ".join("%.3f" % (late_cancels(t)["share"] * 100) for t in range(3))))
        print("   Walmart overlap: INDEPENDENT (owner-signed). The band the other readings give:")
        for reading in ("correlated", "independent", "exclusive"):
            t = sum(fines(year, reading).values())
            print("      %-11s  non-compliant %4.1f%%  total $%.4fM  ratio %.2fx"
                  % (reading, noncompliant_share(year, reading) * 100, t,
                     A405_OTIF_SHARE * op_pool(year) / t))

    print("")
    print("A10.07  the supplier chain on U16's daily ledger, the line's own cash")
    for year, c in enumerate(daily_chain()):
        print("   y%d  oldest invoice at worst %d d past terms | priority %s, fee %s, hold %s | held: %s"
              % (year + 1, c["past"], c["first"]["priority"], c["first"]["fee"], c["first"]["hold"],
                 ", ".join(c["held"]) or "none"))
    print("   y2's worst days past terms, AP at the run before / nearest / after the 32nd day: %s  (the hold at 45)"
          % " / ".join(str(x) for x in hold_edge()))
    print("   A9.13's annual ladder beside it (the annual-mean reading):")
    for year, c in enumerate(supplier_chain()[0]):
        print("      y%d  DPO stretch %5.2f d -> DPO %5.1f, %5.1f d past co-packer net 30"
              % (year + 1, c["stretch"], c["dpo"], c["past"]))
    print("   the larger co-packer runs %d%% of co-packed volume (A5.30); a hold stops its"
          % (COPACK_LARGER * 100))
    print("   lines for the %d-%d week co-pack production lead time (A5.29)."
          % PROD_LEAD_WEEKS)
    E = equity_call()
    print("")
    print("A10.19  the equity call on the daily ledger: %s, $%.4fM; pays off %.4f held, CIA %.4f; tightest after it %.4f"
          % (E["date"], E["size"], E["held"], E["cia"], E["tightest"]))
    print("   band over D0: %s; the AP edge (run before): %s, $%.4fM; counterfactual %s"
          % ("; ".join("%s $%.4fM" % b for b in equity_call_band()), call_date(timing="before"),
             call_size(call_date(timing="before"), timing="before"), counterfactual_date()))
    print("   PIK by year %s | interest+fees with the note %s | FCCR %s"
          % (" / ".join("%.4f" % x for x in E["coupon"]), " / ".join("%.4f" % x for x in E["after"]["interest"]),
             " / ".join("%.2f" % x for x in E["fccr"])))

    print("")
    print("05:154  revision presence: the chance a correct run fails a leg's test (A5.07's rule), 1% and above")
    names = {"increase": "increase", "cinderhaven": "Cinderhaven-initiated", "retailer_reduction": "retailer cut"}
    for (acct, leg), v in sorted(revision_presence().items(), key=lambda kv: -kv[1]["fail"]):
        if v["fail"] >= 0.01:
            print("   %-22s %-8s %-8s expected rows a year %s -> 1 in %.1f"
                  % (names[leg], acct, "per year" if v["per_year"] else "window",
                     " / ".join("%.1f" % e for e in v["expected"]), 1 / v["fail"]))

    print("")
    print("A10.16  velocity dispersion, and whether the SKU exits fall out")
    print("   sigma from A5.28's cadence (A %.0f runs/yr : C %.1f = %.2f:1, read as terciles) = %.4f"
          % (RUNS_A, RUNS_C, RUNS_A / RUNS_C, velocity_sigma()))
    print("   RETIRED: cadence is censored by the run floor. sigma %.3f is read from A7.03 as the spread within a"
          " carried set (ruled 2026-09-14)." % SIGMA_VELOCITY)
    print("   STEP ONE, the run floor on the recipe: widening the catalogue multiplier alone spreads the carried sets")
    for sg, spread, cull in single_multiplier_ceiling():
        print("      catalogue sigma %.3f -> %s" % (sg, "the window never clears" if spread is None else
                                                   "within-set %.3f, first-draw cull %.1f sizes" % (spread, cull)))
    print("   STEP TWO, the SKU x account factor, with the catalogue multiplier at %.3f and the target at %.3f - A7.03's"
          " spread less door %.2f and week %.2f (ruled 2026-09-15): on the window-start catalogue alone its log-sd"
          % (SIGMA_VELOCITY, SIGMA_ACCOUNT, SIGMA_DOOR, SIGMA_WEEK))
    # #drawn-precision: a solved log-sd prints the two decimals disjoint seeds hold, not three
    print("   solves to %.2f; on the window's own y3 carried sets, launches, cuts and decline included, it solves to"
          " %.2f, and group 11's draw reads that one" % (launch_free_sigma(), account_sigma()))
    print("   Kroger, floor 60% of category average (A7.12), two readings of one missing rule:")
    for year in range(3):
        c = floor_crossings(year)
        print("      y%d index %4.1f | WHOLE CATALOGUE %4.1f%% = %4.1f of %d SKUs | AUTHORIZED top %d: "
              "cut at index %5.1f -> %.2f SKUs"
              % (year + 1, VELOCITY_INDEX[year], c["share_all"] * 100, c["count_all"], SKUS,
                 c["authorized"], c["cut_index"], c["count_auth"]))
    print("   UNFI / KeHE, floor %.0f case per DC per week (A10.06):" % VIABILITY_CASES)
    for year in range(3):
        v = viability_crossings(year)
        print("      y%d  UNFI %.2f cases/SKU/DC/wk, floor is %.3fx the average SKU -> %.2f pairs"
              "   |  KeHE %.2f, %.3fx -> %.2f pairs"
              % (year + 1, v["UNFI"]["per_sku"], v["UNFI"]["ratio"], v["UNFI"]["pairs"],
                 v["KeHE"]["per_sku"], v["KeHE"]["ratio"], v["KeHE"]["pairs"]))
    tot_exits = sum(floor_crossings(y)["count_auth"] for y in range(3))
    tot_pairs = sum(viability_crossings(y)[k]["pairs"] for y in range(3) for k in ("UNFI", "KeHE"))
    print("   WINDOW TOTAL, authorized reading: %.2f Kroger SKU exits + %.2f SKU-DC pairs = %.2f"
          % (tot_exits, tot_pairs, tot_exits + tot_pairs))
    print("   STATIC top-k reading, superseded by the A10.16b draw below: it gives the authorized")
    print("   set no forecast noise, so it cannot place a slow SKU on the shelf. Account-level")
    print("   either way -- the product-level gate is derived in A10.09 and A11.21.")

    print("")
    print("A10.16b  the authorization draw -- authorize on forecast, measure on actual")
    D = authorization_draw()
    print("   A5.25 MAPE %s -> forecast-noise sigma %s"
          % (" / ".join("%.0f%%" % (m * 100) for m in MAPE),
             " / ".join("%.4f" % x for x in D["sf"])))
    for name in ("Kroger", "Walmart"):
        print("   %-8s floor index %5.1f, removed at %d consecutive review(s) per A7.12 | authorized below it per review"
              " %s | EXITS over the window %.3f | the pre-period's own %.2f, outside the window, with %.2f strikes"
              " carried into y1"
              % (name, D[name]["floor"], 2 if name == "Kroger" else 1,
                 " / ".join("%.2f" % x for x in D[name]["below"]), D[name]["exits"],
                 D[name]["pre_exits"], D[name]["carried"]))
    print("   TOTAL SKU EXITS FROM BOTH FLOORS: %.3f over three years; the pre-period adds %.2f of its own, which are"
          " NOT window exits and do not reach R4 (owner, 2026-09-15, items 2 and 4)"
          % (D["total_exits"], D["total_pre_exits"]))
    print("   THE PRE-PERIOD'S REVIEW IS SIMULATED (item 4): the window used to open with every strike count at zero, so"
          " nothing could leave before the second in-window review and every 1 January was a first review - the start-up"
          " artifact the owner had already retired for A10.09 and A10.06. %.2f strikes now carry in." % D["total_carried"])
    print("   These are ACCOUNT-level delists -- a SKU leaving one shelf. They are not the")
    print("   R4 exit gate, which counts SKUs leaving the catalogue and is derived in A10.09 and A11.21.")

    print("")
    print("A10.17  per-type deduction amounts, and the mean that derives from them")
    A = deduction_amounts()
    print("   %-22s %6s %8s %13s %8s" % ("type", "share", "mean $", "count/$pool", "of count"))
    for k in A["order"]:
        print("   %-22s %5d%% %8.1f %13.2e %7.1f%%"
              % (k, A405_SHARE[k], A1017_MEAN[k], A["count"][k], A["count"][k] / A["total"] * 100))
    print("   DERIVED mean $%.1f | median $%.0f | sigma %.4f" % (A["mean"], A["median"], A["sigma"]))
    print("   A9.19 REGISTERS mean $%.0f, median $%.0f, sigma %.4f -- the mean is %.0f%% LOWER"
          % (A919_MEAN, A919_MEDIAN, math.sqrt(2 * math.log(A919_MEAN / A919_MEDIAN)),
             (1 - A["mean"] / A919_MEAN) * 100))
    print("   THE MEAN PROPAGATES, SIGMA DOES NOT. count = pool / mean:")
    for mean, lab in ((A919_MEAN, "at $600"), (A["mean"], "at the derived mean")):
        cnt = [pool(t) * 1e6 / mean for t in range(3)]
        print("      %-20s count %s | filed by count %s"
              % (lab, " / ".join("%.0f" % c for c in cnt),
                 " / ".join("%.1f%%" % (DISPUTE_CAPACITY[t] / cnt[t] * 100) for t in range(3))))
    print("   sigma is a BETWEEN-TYPE FLOOR: point masses per type carry no within-type")
    print("   variance, so %.4f understates it and the dollar-weighted rates that hang off" % A["sigma"])
    print("   A9.19's curve are HELD at the registered sigma until the bands are registered.")

    print("")
    print("A10.17b  within-type bands, and sigma unheld")
    M = deduction_mixture()
    print("   %-22s %-13s %7s %9s  %s" % ("type", "p10-p90", "sigma", "signed $", "signed mean vs band"))
    for k, w, mu, sg, lo, hi in M["parts"]:
        m = A1017_MEAN[k]
        where = "above p90" if m > hi else "below p10" if m < lo else "inside"
        print("   %-22s %5d-%-7d %7.3f %9.1f  %s" % (k, lo, hi, sg, m, where))
    print("   MIXTURE mean $%.1f (unchanged) | median $%.1f | sigma %.4f"
          % (M["mean"], M["median"], M["sigma"]))
    print("   was: held %.4f, between-type floor %.4f"
          % (A919_SIGMA_HELD, deduction_amounts()["sigma"]))
    for lab, c in (("at the held sigma", filing_cascade(A919_SIGMA_HELD)),
                   ("at the derived sigma", filing_cascade(M["sigma"])),
                   ("ON THE MIXTURE (registered)", filing_cascade())):
        print("      %-22s by count %s | by dollar %s | A4.08 current %s"
              % (lab, " / ".join("%.1f%%" % (x * 100) for x in c["by_count"]),
                 " / ".join("%.1f%%" % (x * 100) for x in c["by_dollar"]),
                 " / ".join("%.3f" % x for x in c["current"])))

    print("")
    print("A4.09  write-off -- unrecovered bucket 1 + all of bucket 2, derived (registered 2026-09-17)")
    W = write_off()
    print("   bucket pool, share of gross (A4.01 + A4.31): %s"
          % " / ".join("%.2f%%" % (x * 100) for x in W["pool_share"]))
    print("   bucket-1 dollars recovered, from A4.06's dollar filing on A4.07's %.4f: %s"
          % (R1_CURRENT, " / ".join("%.4f" % x for x in W["recovered_b1"])))
    print("   CURRENT write-off %s of gross"
          % " / ".join("%.2f%%" % (x * 100) for x in W["current"]))
    print("   ACHIEVABLE at y3: controls-only %.2f%% | full %.2f%% -- bucket 1 at A4.06's %.0f%% filing"
          " on A4.07's %.3f, bucket 2 reduced by A6.15 prevention rather than recovered"
          % (W["achievable"]["controls"] * 100, W["achievable"]["full"] * 100,
             F_ACHIEVABLE * 100, R1_ACHIEVABLE))
    print("   RETIRED: a recovered bucket-1 share of %.2f, which implies a %.1f%% dollar filing rate --"
          " the first-draft figure that never followed A4.08's restatement of 2026-09-12"
          % (W["retired_recovered_b1"], W["retired_recovered_b1"] / R1_CURRENT * 100))

    print("")
    print("A6.26 / A6.31 / A6.15  prevention, derived from A6.06's mix (registered 2026-09-18)")
    C, S, WR = coverage(), sop_lever(), well_run_pool()
    print("   A6.26 share of bucket-2 dollars: %s"
          % ", ".join("%s %.1f" % (c, v) for c, v in sorted(C["share"].items(), key=lambda kv: -kv[1])))
    print("   `none` by type: %s | reachable %.1f, structural %.1f"
          % (", ".join("%s %.1f" % (t, v) for t, v in C["none_by"].items()), C["reachable"], C["structural"]))
    print("   A6.31 removal: %s | weighted %.3f of the reachable base = %.1f points"
          % (", ".join("%s %.3f" % (t, S["removal"][t]) for t in SOP_REACHABLE), S["weighted"], S["points"]))
    print("   A6.15 prevention: controls-only %.3f | full %.3f" % (WR["prevention"]["controls"], WR["prevention"]["full"]))
    print("   A6.15 on the y3 bucket pool %.2f%% (b1 %.3f / b2 %.3f / b3 %.3f): bucket-1 residual %.3f;"
          " bucket-2 residual %.2f / %.2f; well-run pool %.2f / %.2f%% of gross; bucket 2's share %.0f%% / %.0f%%"
          % (WR["pool"], WR["current"][0], WR["current"][1], WR["current"][2], WR["b1"], WR["b2"]["controls"],
             WR["b2"]["full"], WR["total"]["controls"], WR["total"]["full"], WR["b2_share"]["controls"],
             WR["b2_share"]["full"]))
    Rc = recovery()
    print("   A4.08 achievable $%.3f / $%.3f per bucket-pool dollar against y3 current $%.3f: y3 deltas $%.3f / $%.3f"
          " = $%.0fK / $%.0fK a year on the $%.2fM y3 bucket pool"
          % (Rc["achievable"]["controls"], Rc["achievable"]["full"], Rc["current"][2], Rc["delta"]["controls"],
             Rc["delta"]["full"], Rc["delta_usd"]["controls"] * 1000, Rc["delta_usd"]["full"] * 1000, Rc["pool_usd"]))

    print("")
    print("A10.18  rationalization -- one-in-one-out at the FORMAL-REVIEW accounts")
    R = rationalization_by_account()
    formal_net = sum(sum(R[a]["net"]) for a in FORMAL_REVIEW)
    cuts = sum(r["total"] for r in R.values())
    print("   %d launches after y1 x %d formal-review accounts = %d authorizations; their A7.26 net"
          % (LAUNCHES_AFTER_Y1, LAUNCH_K, LAUNCHES_AFTER_Y1 * LAUNCH_K))
    print("   growth %+d -> %d cuts. Regional and independents' growth is range extension and is"
          % (formal_net, cuts))
    print("   excluded: an aggregate over all accounts (+7) gave 11 by netting growth that frees no slot.")
    D = authorization_draw()
    print("   ACCOUNT-LEVEL exits over the window: %.2f floor delists + %d rationalization = %.2f"
          % (D["total_exits"], cuts, D["total_exits"] + cuts))
    print("   by account, launches to the top-%d FORMAL-REVIEW accounts by revenue:" % LAUNCH_K)
    for a, r in rationalization_by_account().items():
        print("      %-13s adds %s  net %s  cuts %s = %d"
              % (a, r["adds"], r["net"], r["cuts"], r["total"]))
    print("   Regional and independents grow by RANGE EXTENSION: no slot freed, no cut.")

    print("")
    print("A10.09  the catalogue on A5.38's units, restated 2026-09-14")
    units_3q, units_yr = costco_annual_units()
    print("   Costco (A10.05): %s units over 3 quarters, %s annualized across %d accepted packs"
          % (format(round(units_3q), ","), format(round(units_yr), ","), CLUB_ACCEPTED))
    X = catalogue_exits()
    print("   START-UP ARTIFACT, on each window start's first draw: %.3f sizes and %.2f SKU-DC pairs at the"
          % (X["startup_cull"], X["startup_pairs"]))
    print("   first cycle. The brand culled those SKUs and the distributors discontinued those pairs before the window;")
    print("   the culled recipes were %.2f a catalogue; each culled size is redrawn in its slot, %.2f redraws a catalogue,"
          % (X["startup_recipes"], X["redraws"]))
    print("   and the window opens on the result (mean multiplier %.3f; catalogue sigma %.3f, account factor %.3f)."
          % (X["mean_m"], X["sigma"], X["acct"]))
    print("   With no lifecycle, the window then carries exits %s, pairs %s and club exits %.3f."
          % (" / ".join("%.2f" % v for v in X["exits"]), " / ".join("%.2f" % v for v in X["pairs"]), X["club"]))
    print("   In-window catalogue exits are launch exits and A2.09's decliners crossing the run floor: group 11 (A11.21)")
    print("   derives them on this catalogue, and R4's gate reads them per seed.")

    print("")
    print("A10.09  consequence events in the window")
    print("   Kroger and Walmart floor delists   A10.16's draw above")
    print("   UNFI/KeHE SKU-DC discontinuations  the catalogue above, with group 11's launches and decliners (A11.21)")
    print("   Walmart delists           0 scheduled; the drop line is the draw printed above")
    print("   supplier credit holds     %s on the daily ledger, every supplier the same day (A10.07); A10.19's note"
          " releases it the next day" % (hold_day() or "none"))
    print("   account terminations      0 -- no retailer is lost. A5.38 does carry ONE account exit from 2026-09-15:\n                             DPI ends 2023-12-31 on KeHE's acquisition, which is a consolidation, not a termination")

    print("")
    print("A3.08 / A7.29 / A7.03 / A7.07  the scan identity, on the shelf ruling of 2026-09-22")
    Sh = shelf_series()
    lo, hi = tolerance_window()
    for b, s in Sh.items():
        print("   %-9s cost %s  shelf %s  margin %s%s" % (
            b, " / ".join("%.3f" % c for c in s["cost"]), " / ".join("%.2f" % x for x in s["shelf"]),
            " / ".join("%.1f" % m for m in s["margin"]), "   STEPS" if s["steps"] else ""))
    print("   at A3.28's %.1f point(s) the pattern holds for any tolerance from %.2f to %.2f"
          % (A328_TOLERANCE, lo, hi))
    Mk = markup_series()
    print("   A7.29 markup %s" % " / ".join("%.3f" % m for m in Mk["weighted"]))
    Sc = scan_identity()
    for key, lab, fmt in (("retail", "measured retail $M", "%.1f"), ("units", "measured units M", "%.2f"),
                          ("live_meas", "measured live door-SKU-weeks", "{:,.0f}"),
                          ("upw", "units / measured door-SKU-week", "%.2f"),
                          ("dpw", "$ / measured door-SKU-week", "%.2f")):
        vals = [(fmt.format(r[key]) if fmt.startswith("{") else fmt % r[key]) for r in Sc]
        print("   %-32s %s" % (lab, " / ".join(vals)))
    print("   A7.07 units %+.1f%% y1 -> y3 (y2 %+.1f%%); dollars %+.1f%% (y2 %+.1f%%)"
          % (Sc[2]["upw_vs_y1"], Sc[1]["upw_vs_y1"], Sc[2]["dpw_vs_y1"], Sc[1]["dpw_vs_y1"]))
    print("   implied reporting door-SKUs at %.1f u/s/w: %s against A7.26's %s measured"
          % (sum(A703_BAND) / 2, " / ".join("{:,.0f}".format(r["implied"]) for r in Sc),
             " / ".join("{:,.0f}".format(r["grid_meas"]) for r in Sc)))
    for ch, c in channel_velocity().items():
        print("   %-8s %s u/s/w, bands %s%s" % (ch, " / ".join("%.2f" % v for v in c["velocity"]),
                                                 " / ".join("%.2f-%.2f" % b for b in c["bands"]), "  BREACH y%s" % ",".join(str(t + 1) for t, _ in
                                                                                        c["breach"]) if c["breach"] else ""))
    print("   margin above A3.06's ceiling, y1 / y2: %s" % "; ".join(
        "%s %.1f / %.1f" % (b, s["above_ceiling"][0], s["above_ceiling"][1]) for b, s in Sh.items()
        if any(s["above_ceiling"][:2])))
    print("   A7.04 doors (A704_BASE at the minimum whole-door step, exact ceil, Sprouts capped): totals %s"
          % " / ".join("{:,}".format(sum(v[t] for v in A704_DOORS.values())) for t in range(3)))

    if "--checks" in sys.argv:
        print("")
        print("CROSS-CHECKS INTO OTHER GROUPS (report, do not fix here)")
        print("   A4.05 late/OTIF share   %.0f%% registered vs %.1f%% derived -- group 4's row"
              % (A405_OTIF_SHARE * 100, sum(fines(2).values()) / op_pool(2) * 100))
        print("   A7.12 velocity floors   Kroger 60% of CATEGORY average, Walmart bottom")
        print("                           QUINTILE of the modular. A10.04/A10.12 as specced")
        print("                           use bottom 15% of the BRAND's SKUs -- a different")
        print("                           denominator for the same quantity.")
        print("   A7.12 index vs floor    grocery index %s vs Kroger's floor %.0f -- the brand"
              % (" / ".join("%.0f" % v for v in VELOCITY_INDEX), VELOCITY_FLOOR["Kroger"]))
        print("                           MEAN clears the floor in every year; whether any SKU")
        print("                           crosses it is the dispersion nobody has registered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
