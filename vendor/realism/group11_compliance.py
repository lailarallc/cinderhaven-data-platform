#!/usr/bin/env python3
"""The generator for group 11 - compliance, portals, remaining entities - and its one
critical-path calculation: the launch lifecycle on the registered floors (A11.21).

WHAT IT DOES, ON THE RULINGS OF 2026-09-14
------------------------------------------
A launch leaves the catalogue only through registered floors: A7.13's 90-day bars, A7.12's floors,
A10.18's one-in-one-out cuts, A10.06's DC floor after the guaranteed sale, A5.29's run floor on the
recipe, and A11.24's rule that a launch no national account carries is discontinued at the next
planning cycle. NOTHING IS SOLVED AGAINST A TARGET. The owner signed the two free inputs: no launch
decay (A11.21, lambda 0 - the floors, cuts and selection noise already remove the published share, and
decay on top would count the same failure twice) and the forecast error retailers select a launch on
(A11.23, sigma_pred 0.60). The share of launches gone by 24 months DERIVES and is printed against
Salnikova, Baglione & Stanton's 29% (A11.20) and the category band; A7.13's shares derive with it.

Units follow A5.38's dollars over A3.04's prices account by account. A SKU's velocity at an account is
its catalogue multiplier - A10.16's sigma, derived from A7.03's exact y3 velocity (2026-09-22) - times
an account factor retailers cannot forecast. The factor's log-sd is solved here, on the window's own y3
carried sets - launches, cuts and decline included - so that those sets spread the ACCOUNT target, and
group10_floors reads the solved value. A7.03's spread is NOT that target: it is measured over door-SKU-weeks,
and the owner ruled on 2026-09-15 that the door (A11.27) and week (A11.28) components come out of it before
the factor closes the gap, leaving F.SIGMA_ACCOUNT at the account. In-window catalogue exits are launch exits -
2022's cohort included - A2.09's at-risk and fading SKUs declining at their signed rates, and other mature
sizes culled with their recipe, all DRAWN per seed for R4.

    python scripts/group11_compliance.py            # the report, about fifteen minutes: the factor's solve dominates
"""
import math
import os
import sys
from statistics import NormalDist

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import group10_floors as F  # noqa: E402
import group9_ledger as G  # noqa: E402

NORM = NormalDist()

# ------------------------------------------------------------ A11.20, the published survival and its plausibility
# Salnikova, Baglione & Stanton, J. Int'l Food & Agribusiness Marketing 33(3) 2021: 2,810 products, 17 categories,
# launched 2010-12; success = still available two years after introduction; BRANDED 71%. Ruled the target
# for the catalogue definition (2026-09-14); since the second ruling it is what the derived share is
# printed against. Category range 58-88% (Salnikova, Baglione & Stanton 2019).
TARGET = dict(survival=0.71, months=24, band=(0.58, 0.88))   # A11.20: branded 71% at 24 months; category 58-88%
# Stanton, Food Processing 2014-03-27: 66% still listed when checked at least 18 months after launch -
# plausibility since 2026-09-14.
STANTON = dict(survival=0.66, months=18)   # A11.20: plausibility, 66% still listed 18 months after launch
# IRI via FoodNavigator-USA 2014-07-31: 44% of 258 New Product Pacesetters "from 2002 to 2011" existed
# in January 2013 - mature-set plausibility.
PACESETTER_SURVIVED, PACESETTER_YEARS, PACESETTER_MEASURED = 0.44, (2002, 2011), 2013.0

# ------------------------------------------------------------ registered rows read
SIGMA = F.SIGMA_VELOCITY                      # A10.16's catalogue multiplier, derived; A7.03's within-set spread too
LAMBDA = 0.0                                  # A11.21: no launch decay, owner-signed 2026-09-14
SIGMA_PRED = 0.60                             # A11.23: the launch forecast error, owner-signed 2026-09-14
SIGMA_PRED_SENSITIVITY = (0.50, 0.70)         # A11.23: printed beside the signed value; not a band
IN_HOUSE_SHARE = sum(1 for m in F.NONCLUB_MODE if m == "in") / float(len(F.NONCLUB_MODE))   # group 2
PRE_QUARTERS, WINDOW_QUARTERS = 4, 12         # 2022 is the pre-period, registered catalogue history (A7.09)
SLOTS = range(-PRE_QUARTERS, WINDOW_QUARTERS)
LAUNCHES_A_YEAR = 3                           # A7.09: 9 launches over the window, 3 a year; 2022 at the same rate
LAUNCH_P = LAUNCHES_A_YEAR / 4.0              # expected launches a quarter, for the expected environment
LAUNCH_ACCOUNTS = F.LAUNCH_ACCOUNTS           # A10.18: the top-3 formal-review accounts, k = 3
A713_BAR = dict((k, F.A713_BARS[k]) for k in ("Walmart", "Kroger", "WF"))   # A7.13 90-day bar, via group 10
A713_SHARES = (0.25, 0.40)                    # A7.13's practitioner shares: plausibility since 2026-09-14
A710_ACCEPTANCE = 0.40                        # A7.10: 40% of submissions accepted
REVIEW_MONTHS = 6                             # A7.10: Walmart resets twice a year; Kroger annual + mid-year
NATURAL_INDEX = [105.0, 100.0, 95.0]          # A7.12 natural channel, y2 the midpoint
GUARANTEED_SALE_MONTHS = 6                    # A10.06: UNFI supplier terms s6a, per DC
WALMART_FLOOR = math.exp(math.log(100.0) - SIGMA ** 2 / 2
                         + SIGMA * NORM.inv_cdf(F.WAL_MODULAR_QUINTILE))   # A10.16's bottom quintile of the modular, at SIGMA
KROGER_FLOOR = F.VELOCITY_FLOOR["Kroger"]     # A7.12: 60, two consecutive reviews
WF_FLOOR = F.VELOCITY_FLOOR["WF"]             # A7.12: 50, at the 90-day check
A209 = dict(star=15, gem=8, moderate=40, question=12, at_risk=10, fading=8, wide_dead=7)   # A2.09, % of SKUs
DECLINE = {"at_risk": 0.20, "fading": 0.35}   # A2.09: velocity lost a year, owner-signed 2026-09-14, no stop
A528_RUNS = {"A": (8, 12), "C": (3, 4)}       # A5.28: in-house campaigns a year, A and C items
# A11.26, the brand's own rationalization at the annual planning cycle (owner, 2026-09-14, third rulings 4):
# discontinue a SKU below 25% of median velocity for two consecutive quarters with no national authorization.
# The threshold is signed LOW because a poorly managed brand keeps zombies; the count derives and is printed.
PRUNE_SHARE = 0.25            # A11.26, owner-signed: share of the catalogue's median velocity
PRUNE_QUARTERS = 2            # A11.26: consecutive quarters below it
PRUNE_FROM_YEAR = 1           # y2's cycle, the first with two in-window quarters behind it (ruled 2026-09-14)
                              # mirror-exempt: an index into the window's years, y2 = 1, not a figure
TRIALS = 6000                               # mirror-exempt: the catalogue draw's sample size, not a figure; seeded
                                            # per trial, so it reproduces
SOLVE_TRIALS = TRIALS                         # the account factor's solve runs on the published seeds, so it closes exactly
CADENCE_TRIALS = TRIALS                       # window starts behind the generated-volume cadence; at 1,000 its solved
                                              # sigmas moved in the second decimal between disjoint seeds (audit 2026-09-14)


largest_remainder = F.largest_remainder   # A2.09's integer rule, ONE exact definition, in group 10


DECLINER_COUNT = dict((k, v) for k, v in largest_remainder(A209, F.SKUS).items() if k in DECLINE)
DECLINERS = sum(DECLINER_COUNT.values())

# ------------------------------------------------------------ free inputs and readings, counted
INPUTS = [
    ("launch decay", "none: lambda 0", "owner-signed 2026-09-14 (A11.21)"),
    ("launch forecast error", "sigma_pred 0.60, a MAPE of 54% on group 10's conversion", "owner-signed 2026-09-14 (A11.23)"),
    ("A2.09 decline", "at-risk -20% velocity a year, fading -35%, from window start, no stop", "owner-signed 2026-09-14"),
    ("SKU x account factor", "velocity at an account = catalogue multiplier x a factor retailers cannot forecast",
     "structure, owner-signed 2026-09-14; its log-sd derives"),
    ("the factor's population", "solved on the window's own y3 carried sets, launches, cuts and decline included",
     "READING: the ruling's 'about 0.79' was measured on a catalogue with none of them"),
    ("the factor's target", "A7.03's spread less the door and week components, F.SIGMA_ACCOUNT at the account",
     "ruled 2026-09-15: A7.03's spread is door-SKU-week, an account review is not"),
    ("door dispersion", "log-sd 0.55 across an account's doors within a week, band 0.50-0.60",
     "owner-signed 2026-09-15 (A11.27); band midpoint is a READING"),
    ("week dispersion", "log-sd 0.30 across weeks within a door-SKU", "owner-signed 2026-09-15 (A11.28)"),
    ("catalogue sigma", "A10.16's, derived from A7.03's exact y3 velocity", "ruled 2026-09-14; 2026-09-22"),
    ("run floor", "two minimum economic runs a year on the recipe's live sizes", "ruled 2026-09-14 (A5.28, A5.29)"),
    ("units", "every A5.38 line's dollars over A3.04's realized price", "ruled 2026-09-14"),
    ("cadence rule", "runs a year scale with the square root of volume (economic lot sizing), on the multiplier as ruled"
     " and on generated in-house recipe volume", "READING behind A5.28's bound"),
    ("catalogue check", "quarterly from month 6", "DRAFT: no row registers the cycle"),
    ("launch schedule", "3 of each year's 4 quarters, 2022 included, chosen at random", "READING of A7.09's 3 a year"),
    ("launch doors", "all authorized doors at the three accounts from launch", "DRAFT: A7.09 says 2-4 accounts, then spread"),
    ("launch slot", "a launch takes an open slot - A7.26's growth or a vacancy a delist left - else the account cuts its"
     " lowest item at the account; a cut launch is no longer carried there", "A10.18, A11.24"),
    ("launch recipes", "a window launch is its own recipe; 2022's survivors take a size slot of their mode in group 2's map",
     "READING"),
    ("review timing", "month 3, then month 9 and every 6 months after, counted from launch", "READING: A7.10 sets spring and fall"),
    ("launch review rules", "Kroger two strikes at 60; Walmart one strike at reset; WF at the 90-day check only",
     "READING of A7.12"),
    ("mature account floors", "not applied to mature SKUs inside the catalogue draw", "READING: group 10 never coupled them"),
    ("guaranteed sale", "UNFI's six months, applied to KeHE too", "DRAFT"),
    ("window start", "39 sizes whose recipes clear the run floor at the first cycle; culled sizes redrawn in their slots",
     "READING of ruling 4"),
    ("decliners", "A2.09's at-risk and fading on 39 by its integer rule, at random among mature sizes", "READING"),
    ("exit sources", "by the SKU that leaves: a size culled with its recipe is counted as itself, not as a recipe-mate's"
     " decline", "READING"),
    ("A7.13's population", "2022's launches, their 2022 quarters on the expected environment and their window quarters"
     " on the draw, pooled with the window's", "READING"),
    ("2022 environment", "y1's doors, velocities and volumes; no cuts in 2022", "READING: no row registers 2022's"),
    ("R4's exit criterion", "every modelled exit had a production run and a submission", "READING: A7.24 writes the installed base"),
    ("A11.26's velocity", "the SKU's catalogue multiplier with its A2.09 decline, not its units at any account",
     "ruled 2026-09-14, reading confirmed 2026-09-15"),
    ("A11.26's median", "over the live non-club sizes; the club designs are Costco's rotation, not catalogue slots",
     "ruled 2026-09-14, reading confirmed 2026-09-15"),
    ("A11.26's authorization", "'national' is A11.24's three launch accounts - Walmart, Kroger, the Whole Foods leg",
     "ruled 2026-09-14, reading confirmed 2026-09-15"),
    ("A11.26's first cycle", "y2's, the first planning cycle with two in-window quarters behind it",
     "ruled 2026-09-14, reading confirmed 2026-09-15"),
    ("A11.26's two quarters", "the two quarters the cycle has behind it, t-1 and t-2, measured before that year's fill"
     " and launch", "READING: the ruling gives the cycle and the count, not which two"),
    ("Amazon's place and share", "inside A8.01's 10%, 30% of it in y1 rising to 40% in y3, y2 the midpoint",
     "owner-signed 2026-09-15 (A11.01, item 12); y2's midpoint is a READING"),
    ("Amazon's price", "A3.18's $8.99 everyday, no welcome code", "READING: the ladder is untouched and A8.16 is own-site"),
    ("Amazon's referral rate", "blended 13.6% over A11.03's pack mix", "owner-signed 2026-09-18 (A11.03); the 8% floor is the retired reading"),
    ("Amazon's DTC cost share", "A8.11's per-year share applied to the whole 10%, marketplace included",
     "READING: no row splits COGS between own site and Amazon"),
    ("the small-account order", "the tier's dollars over a Faire-typical order of about $450",
     "owner-signed 2026-09-15 (A5.02, item 7), retiring the asserted 120"),
    ("the Faire split", "40% marketplace, 10% Faire Direct, 50% direct; Faire Direct pays processing and no commission",
     "owner-signed 2026-09-15 (A11.04, item 7)"),
    ("DPI's ship-to point", "absorbed into KeHE's from y2, so A5.32's count is conserved",
     "READING of 'A5.32 follows' (item 5); the alternative concentrates the volume"),
    ("the direct tier's terms", "A9.11's 60 days applied to the whole tier, struck from Faire's payout alone",
     "OWED: half the tier is now off Faire and no row registers its terms"),
]


# ------------------------------------------------------------ selection on forecast
def cut_log(sigma_pred, accept=A710_ACCEPTANCE):
    """The log-forecast a submission must beat to be among the accepted share."""
    return -SIGMA ** 2 / 2 + math.sqrt(SIGMA ** 2 + sigma_pred ** 2) * NORM.inv_cdf(1 - accept)


def accept_weight(m, sigma_pred, accept=A710_ACCEPTANCE):
    """P(a submission of multiplier m is accepted) when the retailer takes the top `accept` share on a
    forecast carrying sigma_pred's error."""
    return 1 - NORM.cdf((cut_log(sigma_pred, accept) - math.log(m)) / sigma_pred)


def _simpson(f, lo, hi, n=1200):
    h = (hi - lo) / n
    return h / 3 * sum((1 if k in (0, n) else (4 if k % 2 else 2)) * f(lo + k * h) for k in range(n + 1))


_MEAN = {}


def mean_accepted(sigma_pred):
    """E[multiplier | accepted] at sigma_pred."""
    if sigma_pred not in _MEAN:
        num = _simpson(lambda z: NORM.pdf(z) * math.exp(-SIGMA ** 2 / 2 + SIGMA * z)
                       * accept_weight(math.exp(-SIGMA ** 2 / 2 + SIGMA * z), sigma_pred), -9.0, 9.0)
        _MEAN[sigma_pred] = num / A710_ACCEPTANCE
    return _MEAN[sigma_pred]


def draw_accepted(rng, sigma_pred):
    """One accepted launch: submissions from the catalogue's log-normal until the retailer's forecast - the
    multiplier with sigma_pred's error - clears A7.10's acceptance cut."""
    cut = cut_log(sigma_pred)
    while True:
        m = rng.lognormvariate(-SIGMA ** 2 / 2, SIGMA)
        if math.log(m) + rng.gauss(0, sigma_pred) > cut:
            return m


# ------------------------------------------------------------ A5.28 as a bound on the catalogue sigma
def tercile_ratio(sigma):
    """Top-tercile over bottom-tercile mean of a log-normal with this sigma."""
    z1, z2 = NORM.inv_cdf(1 / 3.0), NORM.inv_cdf(2 / 3.0)
    return (1 - NORM.cdf(z2 - sigma)) / NORM.cdf(z1 - sigma)


def cadence_bound(sigma=SIGMA):
    """A5.28 read as a bound, as the owner computed it (2026-09-14): runs a year scale with the square root of volume,
    and the A:C cadence is the square root of the top-tercile over bottom-tercile mean of the catalogue MULTIPLIER.
    Returns that ratio at `sigma` and C items' runs a year with A items at A5.28's midpoint; the same at a catalogue
    sigma of 2.0; and the sigmas at A5.28's midpoint ratio and at its widest, A 12 : C 3. cadence_on_volume() reads the
    same rule on the volumes the catalogue generates."""
    a_mid = sum(A528_RUNS["A"]) / 2.0
    c_mid = sum(A528_RUNS["C"]) / 2.0

    def sigma_at(ratio):
        lo, hi = 0.01, 5.0
        for _ in range(60):
            mid = (lo + hi) / 2
            if math.sqrt(tercile_ratio(mid)) < ratio:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    r, r2 = math.sqrt(tercile_ratio(sigma)), math.sqrt(tercile_ratio(2.0))
    return dict(ratio=r, c_runs=a_mid / r, ratio_at_2=r2, c_runs_at_2=a_mid / r2, a_mid=a_mid,
                sigma_at_mid=sigma_at(a_mid / c_mid), sigma_at_widest=sigma_at(A528_RUNS["A"][1] / float(A528_RUNS["C"][0])))


def cadence_on_volume(sigma=SIGMA, acct=None, trials=CADENCE_TRIALS):
    """The same rule on generated volume (2026-09-14 audit): in-house recipes are A5.28's campaigns, so rank each window
    start's in-house recipes by their units, take the top third's mean over the bottom third's, and the A:C cadence is
    its square root. Returns the median over window starts and C items' runs a year with A at A5.28's midpoint."""
    acct = F.account_sigma() if acct is None else acct
    per = []
    for trial in range(trials):
        state, _ = F.window_start(trial, sigma, acct=acct)
        vol = F.units(state, 0, dict(state["m"]))
        by = {}
        for i in state["live"]:
            if state["mode"][i] == "in":
                by[state["recipe"][i]] = by.get(state["recipe"][i], 0.0) + vol[i]
        v = sorted(by.values())
        k = len(v) // 3
        per.append(math.sqrt((sum(v[-k:]) / k) / (sum(v[:k]) / k)))
    per.sort()
    ratio = per[len(per) // 2]
    return dict(ratio=ratio, c_runs=sum(A528_RUNS["A"]) / 2.0 / ratio)


def sigma_for_volume_cadence(ratio, acct=None, trials=CADENCE_TRIALS):
    """The catalogue sigma at which generated in-house recipe volume gives this A:C cadence, the factor held."""
    lo, hi = 0.05, SIGMA
    if cadence_on_volume(hi, acct, trials)["ratio"] <= ratio:
        return hi
    for _ in range(12):
        mid = (lo + hi) / 2
        if cadence_on_volume(mid, acct, trials)["ratio"] < ratio:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ------------------------------------------------------------ the environment a launch meets
_CACHE = {}
_CONF = dict(acct=None, base_trials=TRIALS)   # the factor and base the environment is built on; keyed into _CACHE


def base():
    """Group 10's catalogue at window start, at the configured factor: expected carried-set sums at the account."""
    key = ("base", _CONF["acct"], _CONF["base_trials"])
    if key not in _CACHE:
        _CACHE[key] = F.catalogue_exits(trials=_CONF["base_trials"], acct=_CONF["acct"])
    return _CACHE[key]


def base_at(acct, trials=TRIALS):
    """The base at a given factor, for the report; it sets the environment's configuration too."""
    _CONF.update(acct=acct, base_trials=trials)
    return base()


def year_of(quarter):
    """Window year for a quarter index: 2022's quarters meet y1's environment, quarters past the window y3's."""
    return min(max(quarter // 4, 0), 2)


def decay(months):
    """A11.21's launch decay: lambda is 0, owner-signed, so velocity holds."""
    return math.exp(-LAMBDA * months)


def expected_env(t, sigma_pred=SIGMA_PRED):
    """What a launch meets in quarter t on expectation: each account's incumbents at the account (the carried set less
    the item a launch displaces), the catalogue mass, the accounts' units and A8.02's jars. From the window's first
    quarter the mass counts the window's launches only: 2022's survivors are inside the 39."""
    key = ("env", t, sigma_pred, _CONF["acct"], _CONF["base_trials"])
    if key not in _CACHE:
        y = year_of(t)
        B = base()
        mass = F.SKUS * B["mean_m"] + sum(LAUNCH_P * mean_accepted(sigma_pred) for s in SLOTS
                                          if (s >= 0 or t < 0) and s <= min(t, WINDOW_QUARTERS - 1))
        _CACHE[key] = dict(y=y, mass=mass, units=F.ACCOUNT_UNITS[y], jars=G.dtc_jars(y),
                           incumbents=dict((a, (B["sets"][a]["minus_min"][y], F.AUTH_ALL[a][y])) for a in LAUNCH_ACCOUNTS))
    return _CACHE[key]


def launch_rules(L, t, e, env, accounts_only=False):
    """One quarter of a launch, on the registered floors. `env` gives, per account the launch is carried at, the
    incumbents' velocity sum at the account and the carried count including the launch, the accounts' units and the
    catalogue mass; the same function serves the expected environment (2022's cohort) and the realized one (the draw).
    The launch's velocity at an account is e times its account factor.

    At month 3, A7.13's 90-day bars at all three accounts - the launch's units at the account over its doors and 52
    weeks - and Whole Foods' floor of 50. From month 9 every six months, Kroger's floor of 60 on two consecutive
    reviews and Walmart's bottom quintile at reset. From month 6, A10.06's DC floor and the catalogue check: A5.29's run
    floor on the launch's own recipe, or no national account."""
    y = env["y"]
    U = env["units"]
    months = 3 * (t - L["q0"] + 1)
    share = {}
    for a in LAUNCH_ACCOUNTS:
        if not L["accounts"][a]:
            continue
        inc, n = env["incumbents"][a]
        ea = e * L["eps"][a]
        share[a] = ea / (inc + ea)
        index = (F.VELOCITY_INDEX[y] if a != "WF" else NATURAL_INDEX[y]) * ea / ((inc + ea) / n)
        if months == 3:
            usw = U[a] * share[a] / (F.RETAIL_DOORS[a][y] * 52.0)
            if usw < A713_BAR[a] or (a == "WF" and index < WF_FLOOR):
                L["accounts"][a] = False
                L["delist"][a] = t
        elif months >= 9 and (months - 3) % REVIEW_MONTHS == 0:
            if a == "Kroger":
                L["strikes"][a] = L["strikes"][a] + 1 if index < KROGER_FLOOR else 0
                if L["strikes"][a] >= 2:
                    L["accounts"][a] = False
                    L["delist"][a] = t
            elif a == "Walmart" and index < WALMART_FLOOR:
                L["accounts"][a] = False
                L["delist"][a] = t
    if accounts_only or months < GUARANTEED_SALE_MONTHS:
        return None
    for d in F.DISTRIBUTORS:
        if L["dcs"][d] and U[d] / F.dcs(d, y) * e / env["mass"] / 52.0 / F.CASE_UNITS < F.VIABILITY_CASES:
            L["dcs"][d] = False
            if L["dc_loss"] is None:
                L["dc_loss"] = t
    if not any(L["accounts"].values()):
        return "no account"
    retail = sum(U[a] * share[a] for a in LAUNCH_ACCOUNTS if L["accounts"][a])
    rest = env["jars"] + sum(U[k] for k in F.SHARE_ACCOUNTS) + sum(U[d] for d in F.DISTRIBUTORS if L["dcs"][d])
    if retail + rest * e / env["mass"] < F.RUN_FLOOR[L["mode"]]:
        return "run floor"
    return None


def chain_odds():
    """A10.03: the Walmart breach chain's odds a window year - any adjacent pair of quarters below a drop line, on-time's
    80 or in-full's 85 (A10.02's consecutive-period rule), the two lines taken as independent."""
    out = []
    for y in range(3):
        on = F.quarter_risk(F.ONTIME[y], F.SD_ONTIME, 80.0)[2]
        inf = F.quarter_risk(F.INFULL[y], F.SD_INFULL, 85.0)[2]
        out.append(1 - (1 - on) * (1 - inf))
    return out


def chain_schedule(rng):
    """A10.03's chain as a registered floor (owner, 2026-10-14, DECISIONS#u18-rulings Q4). Per window year a breach at
    chain_odds(); the pair completes in one of the year's last three quarters; stage 3 at the next line review, 0-6
    months on; stage 4, one quarter of reduced orders; stage 5, the delist at the next modular reset, 0-6 months on, so
    breach to delist is 9-18 months as A10.03 states. Returns {delist quarter: breach year} for the delists that land
    inside the window; a later one leaves the account in the consequence state (A10.12)."""
    odds = chain_odds()
    out = {}
    for y in range(3):
        if rng.random() < odds[y]:
            done = 4 * y + rng.randrange(1, 4)
            q = done + int(math.ceil((rng.uniform(0, 6) + 3 + rng.uniform(0, 6)) / 3.0))
            if q < WINDOW_QUARTERS:
                out[q] = y
    return out


def new_launch(m, mode, q0, eps):
    return dict(m=m, mode=mode, q0=q0, eps=eps, accounts=dict((a, True) for a in LAUNCH_ACCOUNTS),
                strikes=dict((a, 0) for a in LAUNCH_ACCOUNTS), dcs=dict((d, True) for d in F.DISTRIBUTORS),
                delist={}, cut={}, dc_loss=None, exit=None, why=None)


def launch_life(m, mode, q0, sigma_pred, quarters, eps):
    """A launch's quarters on the expected environment: account delists, first DC loss, catalogue exit."""
    L = new_launch(m, mode, q0, eps)
    for t in range(q0, q0 + quarters):
        why = launch_rules(L, t, m * decay(3 * (t - q0 + 1)), expected_env(t, sigma_pred))
        if why:
            L["exit"], L["why"] = t, why
            break
    return L


def _within(state, e, y, acc):
    """Door-weighted sums of log velocity at the account over its carried set's mean, A7.03's measure, into acc."""
    for a in F.RETAIL_ACCOUNTS:
        doors = F.RETAIL_DOORS[a][y]
        carried = [e[i] * state["eps"][i][a] for i in state["auth"][a] if i in state["live"]]
        if not doors or not carried:
            continue
        mean = sum(carried) / len(carried)
        for v in carried:
            x = math.log(v / mean)
            acc[0] += doors
            acc[1] += doors * x
            acc[2] += doors * x * x


# ------------------------------------------------------------ the catalogue, drawn per seed
def _median(values):
    """The median of a sample, the two middle values averaged when the count is even."""
    s = sorted(values)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _catalogue(state):
    """A trial's catalogue as the platform seeds it: the live SKUs, each with its recipe and mode, and the set each
    account carries."""
    live = sorted(state["live"])
    return dict(skus=[[i, state["recipe"][i], state["mode"][i]] for i in live],
                carried=dict((a, sorted(i for i in state["auth"][a] if i in state["live"])) for a in F.SET_ACCOUNTS))


def catalogue_draws(sigma_pred=SIGMA_PRED, trials=TRIALS, launches=True, decline=True, acct=None, base_trials=TRIALS,
                    prune=True, replay=None):
    """In-window catalogue exits drawn per seed: group 10's catalogue with 2022's surviving launches in its 39, A2.09's
    at-risk and fading SKUs declining at their signed rates, and the window's launches taking slots at Walmart, Kroger
    and Whole Foods (A10.18) - every SKU on A5.38's units, its account factors, the recipe run floor and the planning
    cycle. A11.26's brand-side rationalization runs at y2's and y3's cycles. With launches, decline and pruning off
    it IS group10_floors.catalogue_exits(), draw for draw (CHECK 0), and every quarter of every trial is checked
    against seven invariants (CHECK 1). `replay`, a trial index, records that trial's lifecycle - its window-start
    and window-end catalogues, its decliners, launches and exits - as R["replay"] (U21's `trial` part)."""
    acct = F.account_sigma() if acct is None else acct
    replayed = None
    _CONF.update(acct=acct, base_trials=base_trials)
    src = ("2022 cohort", "window launches", "A2.09 at-risk", "A2.09 fading", "other mature", "A11.26 pruning",
           "club packs")
    by_year = dict((k, [0.0] * 3) for k in src)
    totals, pairs = [], [0.0] * 3
    pre_exits = cuts = launch_cuts = launched = redraws = mass = tail = tail_carried = tail_with_decliner = 0.0
    pairs_exiting = 0.0
    why = {"no account": 0.0, "run floor": 0.0, "pruned": 0.0}
    mature_start, mature_exits = [0.0] * 3, [0.0] * 3
    live_start, live_end = [0.0] * 3, 0.0     # the catalogue actually live, against F.ACTIVE_SKUS
    horizon = dict((c, [0.0, 0.0]) for c in ("2022", "window"))                  # [gone by 24 months, observed]
    first = dict((a, [0.0, 0.0]) for a in LAUNCH_ACCOUNTS)                     # [delisted at the 90-day check, listings]
    first_by = dict((c, [0.0, 0.0]) for c in ("2022", "window"))
    two = dict((c, [0.0, 0.0]) for c in ("2022", "window"))                    # [ended within two years, observed]
    within = [0.0, 0.0, 0.0]
    prune_by_year = [0.0] * 3
    prune_kind = dict(mature=0.0, at_risk=0.0, fading=0.0, launch=0.0)
    prune_carried = 0.0                      # pruned SKUs a distributor or a non-launch account still carried
    violations = dict(flag=0, gone=0, set=0, units=0, exited=0, monotone=0, prune=0)
    checks = 0
    chain_delists, chain_trials = [0.0] * 3, set()      # A10.03's floor: Walmart delists by year, the trials with any
    for trial in range(trials):
        rl = F.trial_rng(trial, "launch")
        rd = F.trial_rng(trial, "decline")
        ra = F.trial_rng(trial, "launch-account")
        chain_at = chain_schedule(F.trial_rng(trial, "chain"))    # A10.03's floor, on a stream of its own (U18 Q4)
        cohort, pre, schedule = {}, [], set()
        if launches:
            for year in range(-1, 3):
                schedule |= set(rl.sample(range(4 * year, 4 * year + 4), LAUNCHES_A_YEAR))
            for q0 in sorted(q for q in schedule if q < 0):
                m = draw_accepted(rl, sigma_pred)
                mode = "in" if rl.random() < IN_HOUSE_SHARE else "co"
                noise = [rl.gauss(0, 1) for _ in range(3)]
                eps = F.account_factors(ra, acct)
                L = launch_life(m, mode, q0, sigma_pred, -q0, eps)
                L.update(id=1000 + q0 + PRE_QUARTERS, noise=noise)
                cohort[L["id"]] = L
                if L["exit"] is not None:
                    pre_exits += 1
                    continue
                pre.append(dict(id=L["id"], m=m * decay(3 * -q0), mode=mode, noise=noise, eps=eps,
                                carried=[a for a in LAUNCH_ACCOUNTS if L["accounts"][a]],
                                gone=[a for a in LAUNCH_ACCOUNTS if not L["accounts"][a]]))
        state, _ = F.window_start(trial, pre=pre, acct=acct)
        redraws += state["redraws"]
        mass += sum(state["m"].values())
        mature = sorted(i for i in state["live"] if i < 1000)
        chosen = rd.sample(mature, DECLINERS) if decline else []
        rate = dict((i, DECLINE["at_risk"] if k < DECLINER_COUNT["at_risk"] else DECLINE["fading"])
                    for k, i in enumerate(chosen))
        rec = None
        if trial == replay:
            rec = replayed = dict(trial=trial, window_start=_catalogue(state), launches=[], exits=[],
                                  decliners=[[i, "at_risk" if k < DECLINER_COUNT["at_risk"] else "fading"]
                                             for k, i in enumerate(chosen)])
        m0 = dict(state["m"])
        for p in pre:
            m0[p["id"]] = cohort[p["id"]]["m"]
        total = 0
        weak = {}                       # A11.26: per quarter, the live sizes below PRUNE_SHARE of median velocity
        pruned_all = set()
        sizes = dict(gone=dict((a, 0) for a in F.SET_ACCOUNTS), dead=0)   # CHECK 1: these only grow
        for t in range(WINDOW_QUARTERS):
            y = t // 4
            if t % 4 == 0:
                mature_start[y] += sum(1 for i in state["live"] if i < 1000)
                live_start[y] += len(state["live"])
            e = {}
            for i in state["live"]:
                if i >= 1000:
                    e[i] = m0[i] * decay(3 * (t - cohort[i]["q0"] + 1))
                elif i in rate:
                    e[i] = m0[i] * (1 - rate[i]) ** ((t + 1) / 4.0)
                else:
                    e[i] = m0[i]
            # A11.26's reading: velocity is the catalogue multiplier with decline, the median over the live non-club
            # sizes, both taken before this year's fill and this quarter's launch
            if prune:
                bar = PRUNE_SHARE * _median(e.values())
                weak[t] = set(i for i in state["live"] if e[i] < bar)
            if t and t % 4 == 0:        # the year's growth is filled BEFORE the quarter's launch exists (audit 2026-09-14)
                F.fill(state, y, e, reserve=1 if launches else 0)
            new = None
            if t in schedule:
                m = draw_accepted(rl, sigma_pred)
                mode = "in" if rl.random() < IN_HOUSE_SHARE else "co"
                new = new_launch(m, mode, t, F.account_factors(ra, acct))
                new.update(id=2000 + t, noise=[rl.gauss(0, 1) for _ in range(3)])
                cohort[new["id"]] = new
                m0[new["id"]] = m
                e[new["id"]] = m * decay(3)
                state["mode"][new["id"]], state["noise"][new["id"]] = mode, new["noise"]
                state["eps"][new["id"]], state["recipe"][new["id"]] = new["eps"], ("launch", new["id"])
                state["live"].add(new["id"])
                state["launches"].add(new["id"])
                launched += 1
                if rec is not None:
                    rec["launches"].append(dict(id=new["id"], quarter=t, mode=mode, velocity=m))
                for a in LAUNCH_ACCOUNTS:
                    carried = [i for i in state["auth"][a] if i in state["live"]]
                    if len(carried) >= F.AUTH_ALL[a][y]:
                        low = min(carried, key=lambda i: (e[i] * state["eps"][i][a], i))
                        state["auth"][a].discard(low)
                        state["gone"][a].add(low)
                        if low in cohort:
                            cohort[low]["accounts"][a] = False     # no longer carried there, which A11.24 reads
                            cohort[low]["cut"][a] = t
                            launch_cuts += 1
                        cuts += 1
                    state["auth"][a].add(new["id"])
            if t in chain_at:           # A10.03's stage 5: Walmart delists the brand's lowest-velocity carried SKU
                carried = [i for i in state["auth"]["Walmart"] if i in state["live"]]
                if carried:
                    low = min(carried, key=lambda i: (e[i] * state["eps"][i]["Walmart"], i))
                    state["auth"]["Walmart"].discard(low)
                    state["gone"]["Walmart"].add(low)
                    if low in cohort:
                        cohort[low]["accounts"]["Walmart"] = False
                        cohort[low]["delist"]["Walmart"] = t
                    chain_delists[y] += 1
                    chain_trials.add(trial)
            if y == 2:
                _within(state, e, y, within)
            exempt = set(i for i in state["live"]
                         if i >= 1000 and 3 * (t - cohort[i]["q0"] + 1) < GUARANTEED_SALE_MONTHS)
            forced_now = []
            pruned_now = []

            def hook(state, t, e):
                forced = []
                # A11.26 at the annual planning cycle, from y2's: a size below the bar in both preceding quarters
                # that no launch account carries is discontinued whatever its distributor and DTC volume
                if prune and t % 4 == 0 and y >= PRUNE_FROM_YEAR:
                    for i in sorted(state["live"]):
                        if i in exempt or any(i in state["auth"][a] for a in LAUNCH_ACCOUNTS):
                            continue
                        if all(i in weak.get(t - k, ()) for k in range(1, PRUNE_QUARTERS + 1)):
                            pruned_now.append(i)
                    forced.extend(pruned_now)
                for i in sorted(j for j in state["live"] if j >= 1000):
                    L = cohort[i]
                    was = dict(L["accounts"])
                    inc = {}
                    for a in LAUNCH_ACCOUNTS:
                        carried = [j for j in state["auth"][a] if j in state["live"]]
                        inc[a] = (sum(e[j] * state["eps"][j][a] for j in carried if j != i), max(len(carried), 1))
                    launch_rules(L, t, e[i], dict(y=t // 4, incumbents=inc, units=F.ACCOUNT_UNITS[t // 4]),
                                 accounts_only=True)
                    for a in LAUNCH_ACCOUNTS:
                        if was[a] and not L["accounts"][a]:
                            state["auth"][a].discard(i)
                            state["gone"][a].add(i)
                    if 3 * (t - L["q0"] + 1) >= GUARANTEED_SALE_MONTHS and not any(L["accounts"].values()):
                        forced.append(i)
                forced_now.extend(forced)
                return forced
            carried_now = set(i for a in F.SET_ACCOUNTS for i in state["auth"][a])
            dead_before = set(state["dead"])
            gone, lost = F.quarter(state, t, e, hook=hook, exempt=exempt, reserve=1 if launches else 0)
            pairs[y] += lost
            gone_set = set(gone)
            pairs_exiting += sum(F.dcs(d, y) for d, i in state["dead"] - dead_before if i in gone_set)
            # CHECK 1, every quarter: the launch flags and the sets agree, nothing gone is carried, no launch sits at a
            # non-launch account, the units allocated are A5.38's less Costco's plus the consumer channel's, no exited SKU is
            # carried anywhere, the gone sets and the dead pairs only grow, and A11.26 took nothing a launch account
            # carried and nothing it had already taken
            checks += 1
            for i in state["live"]:
                if i >= 1000:
                    for a in LAUNCH_ACCOUNTS:
                        violations["flag"] += (i in state["auth"][a]) != cohort[i]["accounts"][a]
            for a in F.SET_ACCOUNTS:
                violations["gone"] += len(state["auth"][a] & state["gone"][a] & state["live"])   # every SKU, not launches only
                violations["exited"] += len(state["auth"][a] - state["live"])
                if a not in LAUNCH_ACCOUNTS:
                    violations["set"] += len(state["auth"][a] & state["launches"])
                violations["monotone"] += len(state["gone"][a]) < sizes["gone"][a]
                sizes["gone"][a] = len(state["gone"][a])
            violations["monotone"] += len(state["dead"]) < sizes["dead"]
            sizes["dead"] = len(state["dead"])
            want = (G.dtc_jars(y) + G.amazon_units(y)
                    + sum(v for k, v in F.ACCOUNT_UNITS[y].items() if k != "Costco"))
            violations["units"] += abs(sum(state["vol"].values()) - want) > 1e-6 * want
            violations["prune"] += sum(1 for i in pruned_now
                                       if i in pruned_all or i in state["live"] or i not in gone_set)
            pruned_all |= set(pruned_now)
            for i in gone:
                if i in pruned_now:
                    key = "A11.26 pruning"
                    prune_by_year[y] += 1
                    prune_kind["launch" if i >= 1000 else
                               ("at_risk" if rate.get(i) == DECLINE["at_risk"] else
                                "fading" if i in rate else "mature")] += 1
                    prune_carried += i in carried_now
                elif i >= 2000:
                    key = "window launches"
                elif i >= 1000:
                    key = "2022 cohort"
                elif i in rate:
                    key = "A2.09 at-risk" if rate[i] == DECLINE["at_risk"] else "A2.09 fading"
                else:
                    key = "other mature"
                    tail += 1
                    tail_carried += i in carried_now
                    tail_with_decliner += any(j in rate for j in gone_set if j != i
                                              and state["recipe"][j] == state["recipe"][i])
                by_year[key][y] += 1
                total += 1
                if rec is not None:
                    rec["exits"].append(dict(id=i, quarter=t, source=key))
                if i < 1000:
                    mature_exits[y] += 1
                else:
                    cohort[i]["exit"] = t
                    why["pruned" if i in pruned_now else
                        "no account" if i in forced_now else "run floor"] += 1
        live_end += len(state["live"])
        c = F.club_exits(state)
        by_year["club packs"][2] += c
        total += c
        if rec is not None:
            rec.update(club_exits_y3=c, window_end=_catalogue(state))
        totals.append(total)
        for L in cohort.values():
            c_ = "2022" if L["q0"] < 0 else "window"
            full = L["q0"] + 7 < WINDOW_QUARTERS          # its 24 months fall inside the draw
            gone24 = L["exit"] is not None and L["exit"] - L["q0"] + 1 <= 8
            if full:
                horizon[c_][1] += 1
                horizon[c_][0] += gone24
            for a in LAUNCH_ACCOUNTS:
                d = L["delist"].get(a)
                first[a][1] += 1
                first[a][0] += d is not None and d == L["q0"]
                first_by[c_][1] += 1
                first_by[c_][0] += d is not None and d == L["q0"]
                if full:
                    ends = [x for x in (d, L["cut"].get(a)) if x is not None]
                    ended = min(ends) if ends else None
                    two[c_][1] += 1
                    two[c_][0] += (ended is not None and ended - L["q0"] + 1 <= 8) or gone24
    n = float(trials)
    ordered = sorted(totals)

    def ratio(pairs_):
        num, den = sum(p[0] for p in pairs_), sum(p[1] for p in pairs_)
        return num / den if den else float("nan")
    return dict(by_year=dict((k, [v / n for v in vals]) for k, vals in by_year.items()),
                chain_delists=[c_ / n for c_ in chain_delists], chain_trials=len(chain_trials) / n,
                total=[sum(by_year[k][y] for k in src) / n for y in range(3)], pairs=[p / n for p in pairs],
                pre_exits=pre_exits / n, cuts=cuts / n, launch_cuts=launch_cuts / n, launched=launched / n,
                redraws=redraws / n, mean_m=mass / n / F.SKUS,
                p10=ordered[int(0.10 * len(ordered))], median=ordered[len(ordered) // 2], mean=sum(totals) / n,
                dist=dict((k, ordered.count(k) / n) for k in sorted(set(ordered))),
                horizon=ratio(horizon.values()), observed=sum(v[1] for v in horizon.values()) / n,
                horizon_by=dict((c_, ratio([v])) for c_, v in horizon.items()),
                a713=(ratio(first.values()), ratio(two.values())),
                a713_first=dict((a, v[0] / v[1]) for a, v in first.items() if v[1]),
                a713_by=dict((c_, (ratio([first_by[c_]]), ratio([two[c_]]))) for c_ in ("2022", "window")),
                hazard=[mature_exits[y] / mature_start[y] if mature_start[y] else 0.0 for y in range(3)],
                tail_carried=tail_carried / tail if tail else 0.0, tail_with_decliner=tail_with_decliner / n,
                launch_exits=dict((k, v / n) for k, v in why.items()), pairs_exiting=pairs_exiting / n,
                prune=[v / n for v in prune_by_year], prune_kind=dict((k, v / n) for k, v in prune_kind.items()),
                prune_carried=prune_carried / sum(prune_by_year) if sum(prune_by_year) else 0.0,
                live_start=[v / n for v in live_start], live_end=live_end / n,
                within=math.sqrt(within[2] / within[0] - (within[1] / within[0]) ** 2) if within[0] else float("nan"),
                violations=violations, checks=checks, acct=acct, replay=replayed)


def solve_account_factor(trials=SOLVE_TRIALS):
    """The SKU x account factor's log-sd (owner, 2026-09-14: signed as structure, its size derived), solved so the
    window's own y3 carried sets - launches, cuts and A2.09's decline included, as generated - spread the ACCOUNT
    target, door-weighted over the four formal-review accounts.

    The target is F.SIGMA_ACCOUNT, not A7.03's whole spread (owner, 2026-09-15, ruling 3): that is measured over
    door-SKU-weeks, and an account review reads account-averaged velocity, where door and week variation average
    out. Solving to the whole spread at the account attributed store and week noise to accounts - that was revision 6's 0.944.
    group10_floors.launch_free_sigma() prints the same solve on the launch-free population. Each step rebuilds
    group 10's base at the step's factor; the seeds are shared, so the solve reproduces.

    The bracket is checked, not assumed: a solve that clamps at an end returns a number no downstream figure
    would flag (2026-09-15). The ends are probed at a fraction of the trials - whether the target lies between
    them is structural, and does not need the published figure's precision."""
    lo, hi = 0.0, 1.5
    probe = max(300, trials // 20)
    f_lo = catalogue_draws(trials=probe, acct=lo, base_trials=probe)["within"]
    f_hi = catalogue_draws(trials=probe, acct=hi, base_trials=probe)["within"]
    if not (f_lo < F.SIGMA_ACCOUNT <= f_hi):
        raise RuntimeError("account factor: target %.4f outside the bracket [%.4f at %.2f, %.4f at %.2f]"
                           % (F.SIGMA_ACCOUNT, f_lo, lo, f_hi, hi))
    for _ in range(12):
        mid = (lo + hi) / 2
        if catalogue_draws(trials=trials, acct=mid, base_trials=trials)["within"] < F.SIGMA_ACCOUNT:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def pacesetter_hazard():
    """The constant annual hazard the IRI figure implies, on two age conventions and two methods.

    Launch at the start of each year gives mean age 6.5; mid-year gives 6.0. The shortcut divides
    by the mean age; the exact reading averages survival over launch years, and because exp is
    convex the shortcut understates. All four assume launches evenly spread, which no source states."""
    out = {}
    for label, offset in (("start", 0.0), ("mid", 0.5)):
        ages = [PACESETTER_MEASURED - (yr + offset) for yr in range(PACESETTER_YEARS[0], PACESETTER_YEARS[1] + 1)]
        mean_age = sum(ages) / len(ages)
        lo, hi = 0.0, 2.0
        for _ in range(100):
            mid = (lo + hi) / 2
            if sum(math.exp(-mid * a) for a in ages) / len(ages) > PACESETTER_SURVIVED:
                lo = mid
            else:
                hi = mid
        out[label] = dict(mean_age=mean_age, shortcut=1 - math.exp(math.log(PACESETTER_SURVIVED) / mean_age),
                          exact=1 - math.exp(-(lo + hi) / 2))
    return out


# ------------------------------------------------------------ the rest of group 11: what derives
REPAIR_MINUTES = {            # A11.15: PDHA R/02_build_frames.R fix_minutes_est, owner-signed starting values
    "GTIN check digit invalid": 10, "UPC check digit invalid": 10, "case weight or dims missing": 30,
    "brand owner missing": 10, "country of origin missing": 30, "weight implausible": 15}
LOADED_HOURLY = 42.14         # A9.05: N23, the clerk's loaded cost over A9.06's productive hours
SWELL = (0.015, 0.020)        # A4.30: swell allowance, share of distributor purchases, UNFI/KeHE
DISPOSITION = {"donate": 0.40, "liquidate": 0.30, "destroy": 0.30}   # A11.12, owner-ruled
COMPLAINTS_PER_UNIT = 1.0 / 10000    # A11.08, owner-signed
LOT_UNITS_IN_HOUSE = F.RUN_FLOOR["in"] / 2   # A5.29: two minimum runs of 2,000, one kettle batch each
WORKING_DAYS = 250                   # A11.08: working days a year, the divisor of complaints a working day
BAD_DEBT = 0.002                     # A9.01: G&A bad debt, 0.2% of gross


def kroger_deduction_rate():
    """A11.14 as ruled: late/OTIF by A5.15's per-day mechanism, every other A4.05 type at Kroger's
    share of wholesale dollars. The pool is A4.05's denominator, A4.01 plus A4.31."""
    out = []
    for y in range(3):
        w = F.wholesale(y)
        kro = w * F.SHARE["Kroger"][y]          # group10_floors.SHARE holds fractions
        pool = F.pool(y)
        fines_k = F.fines(y)["Kroger"]
        others = sum(pool * s / 100.0 for t, s in F.A405_SHARE.items() if t != "late_otif") * F.SHARE["Kroger"][y]
        late_by_volume = pool * F.A405_SHARE["late_otif"] / 100.0 * F.SHARE["Kroger"][y]
        out.append(dict(kroger_wholesale=kro, fines=fines_k, late_by_volume=late_by_volume, others=others,
                        rate=(fines_k + others) / kro, brand=pool / w))
    return out


def repair_dollars():
    """A11.15: each defect type's minutes at A9.05's loaded hour."""
    return dict((k, v / 60.0 * LOADED_HOURLY) for k, v in REPAIR_MINUTES.items())


def swell_containment():
    """A11.13: swell at UNFI and KeHE against A4.05's damaged/unsaleables type, two ways.

    Brand-wide, the type contains swell. At the distributors' own share of wholesale - the
    allocation A11.14 uses - it does not, and the brand-wide fit requires retailers' damaged
    rate per dollar to run at a stated fraction of the distributors'."""
    out = []
    for y in range(3):
        w = F.wholesale(y)
        dshare = F.SHARE["UNFI"][y] + F.SHARE["KeHE"][y]
        purchases = w * dshare
        damaged = F.pool(y) * F.A405_SHARE["damaged_unsaleables"] / 100.0
        swell = [s * purchases for s in SWELL]
        at_share = damaged * dshare
        # EXACT (owner, 2026-09-23): y1's lower bound is 55/2 on the registered decimals, an exact half that the
        # float put below 27.5 and printed as 27. Every input is a registered literal, read through F._q.
        q = F._q
        wq = q(F.GROSS[y]) * (1 - q(F.S_DTC))
        dq = (q(G.SHARE["UNFI"][y]) + q(G.SHARE["KeHE"][y])) / 100
        damq = (q(F.OPDED[y]) + q(F.INVALID_TRADE)) * q(F.GROSS[y]) * F.A405_SHARE["damaged_unsaleables"] / 100
        ratio = [float((damq - q(s) * wq * dq) / (wq * (1 - dq)) / q(s)) for s in SWELL]
        out.append(dict(purchases=purchases, swell=swell, damaged=damaged, share=[sw / damaged for sw in swell],
                        at_share=at_share, multiple=[sw / at_share for sw in swell], retailer_ratio=ratio))
    return out


def write_offs():
    """A11.12: A5.21's rate on A9.12's inventory at COGS, the line A9.02 reads, split by the ruled disposition."""
    P = G.pnl()
    wc = G.working_capital(P["cogs"])
    return [dict(inventory=wc["inv"][y], rate=G.WRITE_OFF[y], dollars=P["group11"][y]["write_off"],
                 split=dict((k, v * P["group11"][y]["write_off"]) for k, v in DISPOSITION.items()))
            for y in range(3)]


def units():
    """Units shipped by year: A5.38's wholesale dollars at A3.04's realized prices (group 9's), Costco's twins
    at two jars each, A8.02's own-site jars and Amazon's units.

    The consumer channel is TWO lines since item 12 split A8.01's 10% (ruled 2026-09-15). A11.08's complaints run
    per unit sold, so a marketplace unit counts exactly as an own-site one does - leaving Amazon out would have
    dropped the complaint base by the share the split moved."""
    out = []
    for y in range(3):
        u = G.units_by_account(y)
        club = u.pop("Costco")
        whole = sum(u.values())
        dtc, amazon = G.dtc_jars(y), G.amazon_units(y)
        out.append(dict(wholesale=whole, club=club, dtc=dtc, amazon=amazon,
                        total=whole + club + dtc + amazon))
    return out


CLUB_IN_HOUSE_SHARE = sum(1 for m in F.CLUB_DESIGN_MODE if m == "in") / float(len(F.CLUB_DESIGN_MODE))   # group 2


def complaints_and_lots():
    """A11.08: complaints at the signed rate; in-house kettle lots on the in-house share of SKUs, and of
    the club designs for Costco's jars (count proxies - volume by line is not registered)."""
    return [dict(complaints=u["total"] * COMPLAINTS_PER_UNIT, per_day=u["total"] * COMPLAINTS_PER_UNIT / WORKING_DAYS,
                 lots=((u["wholesale"] + u["dtc"]) * IN_HOUSE_SHARE + u["club"] * CLUB_IN_HOUSE_SHARE) / LOT_UNITS_IN_HOUSE)
            for u in units()]


def small_accounts():
    """A11.04 against A5.38's dollars, A5.02's restated order count and A9.01's bad debt; Faire's fees as A9.02 reads
    them, on the split the owner signed 2026-09-15.

    A5.02's 120 orders a year is retired (item 7): the count is the tier's dollars over a Faire-typical order of about
    $450, so the AOV reproduces $450 by construction and the one-pallet objection goes with it - A5.02's acceptance
    floor of about $5,100 was a pallet, and a $450 drop is not one. The asserted count is printed beside the derived
    one, because the finding it produced is what the restatement retires."""
    out = []
    for y in range(3):
        dollars = F.wholesale(y) * F.SHARE["small"][y] * 1e6
        orders = F.POS["small"][y]
        bad = BAD_DEBT * F.GROSS[y] * 1e6
        out.append(dict(dollars=dollars, orders=orders, aov=dollars / orders, faire=G.faire_fees(y) * 1e6, bad_debt=bad,
                        bad_share=bad / dollars, asserted_orders=G.SMALL_ORDERS_ASSERTED[y],
                        asserted_aov=dollars / G.SMALL_ORDERS_ASSERTED[y],
                        on_faire=dollars * (G.FAIRE_SPLIT["marketplace"] + G.FAIRE_SPLIT["direct_program"])))
    return out


def amazon():
    """A11.01's place, ruled 2026-09-15 (item 12): Amazon inside A8.01's 10%, its share owner-signed at 30% rising to
    40%, group 8's own-site rows on the remainder. A9.01's marketplace line prices the Amazon part: A11.22's referral
    blended over A11.03's owner-signed pack mix and its plan, A11.31's FBA fees and A11.30's advertising. The 8%
    floor and band printed here are the retired reading, the dated record of what the P&L read before 2026-09-18;
    the plan beside them is current."""
    out = []
    for y in range(3):
        f = G.amazon_fees(y)
        out.append(dict(dollars=G.amazon_dollars(y), own_site=G.own_site_dollars(y), units=G.amazon_units(y),
                        jars=G.dtc_jars(y), share=G.AMAZON_SHARE[y], referral=f["referral"], plan=f["plan"],
                        total=f["total"], band=f["band"]))
    return out


def materiality_reach(floor=250.0):
    """A11.11: how much of the deduction stream a $250 floor exempts, on A10.17's mixture."""
    M = F.deduction_mixture()
    lx = math.log(floor)
    count = sum(w * NORM.cdf((lx - mu) / sg) for _, w, mu, sg, _, _ in M["parts"])
    dollars = sum(w * math.exp(mu + sg * sg / 2) * NORM.cdf((lx - mu - sg * sg) / sg)
                  for _, w, mu, sg, _, _ in M["parts"]) / M["mean"]
    return dict(count=count, dollars=dollars, median=M["median"], mean=M["mean"])


BUYER_TURNOVER = 0.30         # A11.19, owner-signed
RESET_QUARTERS = 2                   # A11.19: quarters a buyer reset lasts
# A5.38: the national accounts and the date each goes live -- Sprouts authorized Q1 y2, Costco's rotation from Q2 y3;
# None is live before the window opens. Each year's weight is the share of the calendar year the account is live,
# counted from the date, never typed (owner, 2026-09-25): Costco's 0.75 is April to December.
NATIONAL_LIVE_FROM = {"Walmart": None, "Kroger": None, "WF": None, "Sprouts": "2024-01-01", "Costco": "2025-04-01"}


def _live_share(start, year):
    if start is None or int(start[:4]) < year:
        return 1
    if int(start[:4]) > year:
        return 0
    month = int(start[5:7])
    return 1 if month == 1 else (13 - month) / 12


NATIONAL = [dict((a, _live_share(s, 2023 + y)) for a, s in NATIONAL_LIVE_FROM.items() if _live_share(s, 2023 + y))
            for y in range(3)]   # A5.38, derived from the dates above


def buyer_resets():
    """A11.19: expected resets a year, weighted by the part of the year each account is live, and the
    share of an account's quarters inside a two-quarter reset."""
    return [dict(accounts=sum(N.values()), resets=BUYER_TURNOVER * sum(N.values()),
                 in_reset=BUYER_TURNOVER * RESET_QUARTERS / 4.0) for N in NATIONAL]


RECALL_EVENTS = {2022: 471, 2023: 464, 2024: 456}          # A11.08: openFDA food enforcement, fiscal years
FOOD_ESTABLISHMENTS = {2022: 38817, 2023: 40712, 2024: 42010}   # A11.08: BLS QCEW private NAICS 311


def recall_odds():
    """A11.08: industry recall events per food-manufacturing establishment, as one firm's odds. The
    numerator includes non-manufacturers and the denominator counts establishments, so the direction
    of the bias is not established; fiscal 2022-2024 stands in for calendar 2023-2025."""
    rates = dict((yr, RECALL_EVENTS[yr] / float(FOOD_ESTABLISHMENTS[yr])) for yr in RECALL_EVENTS)
    mean = sum(rates.values()) / len(rates)
    return dict(rates=rates, mean=mean, window=1 - (1 - mean) ** 3)


# ------------------------------------------------------------ U21, the entry function
# outputs(acct, trial) is what the gate checks and the platform's seeders import, one object (regen plan U21). Each
# _printed_* function carries the values one gate function's entries read, (anchor, label, value), the label the
# entry's own; _values(acct) is the shared work they read, once a factor. The gate reads none of this module's
# internals.
_MEMO = {}


def _no_prune():
    """A11.26's counterfactual, which its own row and group 11's doc publish: the same draw with the brand-side
    rationalization off. A causal sentence names the counterfactual that measured it (#causal-claims-probed), so
    the counterfactual is watched like the claim. Moved from the gate on U21."""
    R = catalogue_draws(prune=False)
    return dict(total=R["total"], pairs=R["pairs"], hazard=R["hazard"], live_start=R["live_start"],
                live_end=R["live_end"], other=R["by_year"]["other mature"], at_risk=R["by_year"]["A2.09 at-risk"],
                fading=R["by_year"]["A2.09 fading"], p10=R["p10"], median=R["median"], mean=R["mean"],
                other_decl=R["tail_with_decliner"], pairs_exiting=R["pairs_exiting"], within=R["within"])


def _a713_arms(acct):
    """A7.13's causal block names two counterfactuals -- A7.12's index at the category average of 100 everywhere,
    and no account factor at all -- and a causal sentence names the counterfactual that measured it
    (#causal-claims-probed), so the counterfactual is watched like the claim. Moved from the gate on U21.

    Arm A mutates two module globals. It restores them and clears the draw cache either way: a leaked index would
    silently rescale every draw taken after it, which is a worse failure than the one this closes.
    """
    vi, ni = list(F.VELOCITY_INDEX), list(NATURAL_INDEX)
    try:
        F.VELOCITY_INDEX[:] = [100.0] * 3
        NATURAL_INDEX[:] = [100.0] * 3
        _CACHE.clear()
        index100 = catalogue_draws(acct=acct)["a713"]
    finally:
        F.VELOCITY_INDEX[:] = vi
        NATURAL_INDEX[:] = ni
        _CACHE.clear()
    no_factor = catalogue_draws(acct=0.0)["a713"]
    return dict(index100=dict(first=index100[0], two=index100[1]),
                no_factor=dict(first=no_factor[0], two=no_factor[1]))


def _values(acct):
    """This generator's share of the work the printed entries read (the gate's _group11_compute until U21), by the
    names the entries use, on the solved account factor `acct`."""
    if acct in _MEMO:
        return _MEMO[acct]
    free = F.launch_free_sigma()
    R_free = catalogue_draws(acct=free)
    X = base_at(acct)
    R = catalogue_draws()
    S50, S70 = (catalogue_draws(sp) for sp in SIGMA_PRED_SENSITIVITY)
    by = R["by_year"]
    CB = cadence_bound()
    CV = cadence_on_volume(acct=acct)
    headroom = []
    for trial in range(2000):
        state, _ = F.window_start(trial, acct=acct)
        vol = F.units(state, 0, dict(state["m"]))
        i = sorted(state["live"])[trial % len(state["live"])]
        mates = [j for j in state["live"] if state["recipe"][j] == state["recipe"][i]]
        headroom.append((sum(vol[j] for j in mates if j != i) + vol[i] * (1 - DECLINE["fading"]) ** 3)
                        / F.RUN_FLOOR[state["mode"][i]])
    headroom.sort()
    added = [LAUNCHES_A_YEAR + (F.CLUB_ACCEPTED if y == 2 else 0) for y in range(3)]
    _MEMO[acct] = dict(
        within=R["within"],
        within_free=R_free["within"],
        free=dict(horizon=R_free["horizon"], first=R_free["a713"][0], two=R_free["a713"][1], total=R_free["total"]),
        cadence=dict(CB, volume_ratio=CV["ratio"], volume_c_runs=CV["c_runs"],
                 volume_sigma_widest=sigma_for_volume_cadence(A528_RUNS["A"][1] / float(A528_RUNS["C"][0]), acct),
                 volume_sigma_mid=sigma_for_volume_cadence(CB["a_mid"] / (sum(A528_RUNS["C"]) / 2.0), acct)),
        horizon=R["horizon"],
        observed=R["observed"],
        first=R["a713"][0],
        two=R["a713"][1],
        by_first=R["a713_first"],
        by_cohort=R["a713_by"],
        sens=[dict(horizon=S["horizon"], first=S["a713"][0], two=S["a713"][1], p10=S["p10"])
             for S in (S50, S70)],
        cohort=by["2022 cohort"],
        window=by["window launches"],
        at_risk=by["A2.09 at-risk"],
        fading=by["A2.09 fading"],
        other=by["other mature"],
        club=by["club packs"],
        total=R["total"],
        pairs=R["pairs"],
        pre_exits=R["pre_exits"],
        prune=R["prune"],
        prune_kind=R["prune_kind"],
        prune_carried=R["prune_carried"],
        live_start=R["live_start"],
        live_end=R["live_end"],
        no_prune=_no_prune(),
        a713_arms=_a713_arms(acct),
        p10=R["p10"],
        median=R["median"],
        mean=R["mean"],
        cuts=R["cuts"],
        launch_cuts=R["launch_cuts"],
        tail_carried=R["tail_carried"],
        other_decl=R["tail_with_decliner"],
        launch_exits=R["launch_exits"],
        pairs_exiting=R["pairs_exiting"],
        violations=R["violations"],
        hazard=R["hazard"],
        added=added,
        net=[added[y] - R["total"][y] for y in range(3)],
        decliners=DECLINER_COUNT,
        logsd=dict((a, X["sets"][a]["logsd"][1 if a == "Sprouts" else 0]) for a in F.RETAIL_ACCOUNTS),
        startup_cull=X["startup_cull"],
        startup_recipes=X["startup_recipes"],
        startup_pairs=X["startup_pairs"],
        redraws=X["redraws"],
        headroom=headroom[len(headroom) // 2],
        amazon=amazon(),
        kroger=kroger_deduction_rate(),
        repair=repair_dollars(),
        swell=swell_containment(),
        write_offs=write_offs(),
        reach=materiality_reach(),
        units=units(),
        lots=complaints_and_lots(),
        recall=recall_odds(),
        small=small_accounts(),
        resets=buyer_resets(),
        pacesetter=pacesetter_hazard(),
    )
    return _MEMO[acct]


def _printed_restated_21(V):
    """The values the gate's _restated_21_figures reads, keyed (anchor, label) as its entries name them."""
    rate03, p10_03 = F.test_a_rate()["pass_pct"], V["p10"]
    return [
        ('A11.13', "A11.13's multiples over the window, the envelope its plausibility keeps",
         [(min(s["multiple"][0] for s in V["swell"]), max(s["multiple"][1] for s in V["swell"]))]),
        ('A11.26', "a declining size's recipe over its floor, A11.26 and its decision",
         [V["headroom"]]),
        ('A2.01', "03's gate: Test A's pass rate (A2.01, A11.18)",
         [rate03]),
        ('A11.21', "03's gate: catalogue exits at R4's pass mark, the new-products row",
         [p10_03]),
        ('A11.21', "03's gate: catalogue exits at R4's pass mark, the gates row",
         [p10_03]),
    ]


def _printed_group11(V):
    """The values the gate's group11_figures reads, keyed (anchor, label) as its entries name them."""
    def pct(xs):
        return [x * 100 for x in xs]
    bf, bc = V["by_first"], V["by_cohort"]
    a713 = pct([V["first"], bf["Walmart"], bf["Kroger"], bf["WF"], V["two"]])
    s50, s70 = V["sens"]
    cad = V["cadence"]
    cad_mult = [cad["ratio"], cad["c_runs"], 2.0, cad["ratio_at_2"], cad["c_runs_at_2"], cad["sigma_at_mid"],
                cad["sigma_at_widest"]]
    table = (V["cohort"] + V["window"] + V["at_risk"] + V["fading"] + V["other"] + V["prune"] + V["club"]
             + V["total"])
    NP, PK = V["no_prune"], V["prune_kind"]
    sd = V["logsd"]
    sds = [sd["Walmart"], sd["Kroger"], sd["WF"], sd["Sprouts"]]
    kro, swell, wo, reach = V["kroger"], V["swell"], V["write_offs"], V["reach"]
    units, lots, rec, small, og, ore = V["units"], V["lots"], V["recall"], V["small"], V["organic"], V["oregon"]
    hz, costs = V["pacesetter"], V["costs"]
    rec_series = [r * 100 for _, r in sorted(rec["rates"].items())] + [rec["window"] * 100]
    into, ruled, pack = ore["into"], ore["ruled"], ore["packaging"]
    free = V["free"]
    cost_total = [c["total"] for c in costs]
    viol = V["violations"]
    return [
        ('A7.13', "A7.13's two shares, the slice-1 decision",
         [V["first"] * 100, V["two"] * 100]),
        ('A11.24', 'the 24-month share, the slice-1 decision',
         [V["horizon"] * 100]),
        ('A10.09', 'catalogue exits, the slice-1 decision',
         V["total"]),
        ('A11.21', 'the factor on the window and the spread it leaves, doc',
         [V["acct"], V["within"]]),
        ('A11.21', "the launch-free solve, the window's spread at it, and what the draw gives there, doc",
         [V["launch_free"], V["within_free"], free["horizon"] * 100, free["first"] * 100, free["two"] * 100] + free["total"]),
        ('A11.21', 'the factor on the window and the spread it leaves, row',
         [V["acct"], V["within"]]),
        ('A11.21', "the launch-free solve and the window's spread at it, row",
         [V["launch_free"], V["within_free"]]),
        ('A11.21', "the factor, the launch-free solve and the window's spread at it, the owner's list",
         [V["acct"], V["launch_free"], V["within_free"]]),
        ('A11.21', 'the factor and its spread, the decision',
         [V["acct"], V["within"]]),
        ('A11.21', "the launch-free solve and the window's spread at it, the decision",
         [V["launch_free"], V["within_free"]]),
        ('A10.16', 'the factor, the spread it leaves, window-start spreads and the launch-free solve, A10.16',
         [V["acct"], V["within"]] + sds + [V["launch_free"]]),
        ('A7.03', "window-start spreads by account, group 10's doc",
         sds),
        ('A5.28', 'A5.28 on the multiplier',
         cad_mult),
        ('A5.28', "A5.28 on the multiplier, then on generated volume, the doc's summary",
         [cad["ratio"], cad["volume_ratio"], cad["volume_c_runs"]]),
        ('A5.28', 'A5.28 on generated volume: the ratio, C runs, the sigmas at the widest and the midpoint',
         [cad["volume_ratio"], cad["volume_c_runs"], cad["volume_sigma_widest"], cad["volume_sigma_mid"]]),
        ('A5.28', 'A5.28 on generated volume, row',
         [cad["volume_ratio"], cad["volume_c_runs"], cad["volume_sigma_widest"],
          cad["volume_sigma_mid"]]),
        ('A5.28', 'A5.28 on generated volume, the decision',
         [cad["volume_ratio"], cad["volume_c_runs"], cad["volume_sigma_widest"]]),
        ('A5.28', "A5.28 on both, the owner's list",
         [cad["ratio"], cad["volume_ratio"], cad["volume_c_runs"],
         cad["volume_sigma_widest"]]),
        ('A5.28', "A5.28 on the multiplier then on volume, group 10's doc",
         cad_mult[:4] + [cad["volume_ratio"]]),
        ('A11.24', 'the 24-month share, doc summary',
         [V["horizon"] * 100]),
        ('A11.21', "the 24-month share by sigma_pred, the doc's table",
         [s50["horizon"] * 100, V["horizon"] * 100, s70["horizon"] * 100]),
        ('A7.13', "A7.13 at the 90-day check by sigma_pred, the doc's table",
         [s50["first"] * 100, V["first"] * 100, s70["first"] * 100]),
        ('A7.13', "A7.13 within two years by sigma_pred, the doc's table",
         [s50["two"] * 100, V["two"] * 100, s70["two"] * 100]),
        ('A11.21', "R4's 10th percentile by sigma_pred, the doc's table",
         [s50["p10"], V["p10"], s70["p10"]]),
        ('A11.21', 'the launches observed, and the points above 29%',
         [V["observed"], V["horizon"] * 100 - 29]),
        ('A11.21', 'the 24-month share, the launches observed, then at sigma_pred 0.50 and 0.70, row',
         [V["horizon"] * 100, V["observed"], s50["horizon"] * 100, s70["horizon"] * 100]),
        ('A11.23', 'the 24-month share at sigma_pred 0.50 and 0.70, A11.23',
         [s50["horizon"] * 100, s70["horizon"] * 100]),
        ('A11.21', 'the 24-month share, then at sigma_pred 0.50 and 0.70, the decision',
         [V["horizon"] * 100, s50["horizon"] * 100, s70["horizon"] * 100]),
        ('A11.24', 'the 24-month share, A11.24',
         [V["horizon"] * 100]),
        ('A11.24', "the 24-month share, group 10's owner list",
         [V["horizon"] * 100]),
        ('A7.13', 'A7.13 derived: 90-day share, Walmart, Kroger, Whole Foods, two-year',
         a713),
        ('A7.13', 'A7.13 derived, where A7.13 and group 7 print it',
         a713),
        ('A7.13', "A7.13's two shares, the doc's summary",
         pct([V["first"], V["two"]])),
        ('A7.13', "A7.13's two shares, the owner's list",
         pct([V["first"], V["two"]])),
        ('A7.13', "A7.13 at the 90-day check at sigma_pred 0.50 and 0.70, then at the launch-free factor, the owner's list",
         [s50["first"] * 100, s70["first"] * 100, free["first"] * 100]),
        ('A7.13', "A7.13 by cohort: 2022's two shares, then the window's",
         pct([bc["2022"][0], bc["2022"][1], bc["window"][0], bc["window"][1]])),
        ('A2.09', "A2.09's decliners among 39",
         [V["decliners"]["at_risk"], V["decliners"]["fading"]]),
        ('A2.09', "A2.09's decliners among 39, A2.09 and group 2",
         [V["decliners"]["at_risk"], V["decliners"]["fading"]]),
        ('A2.09', "A2.09's exits over the window, A2.09 and group 2",
         [sum(V["at_risk"]), sum(V["fading"])]),
        ('A2.09', "A2.09's exits over the window, the decision, at-risk",
         [sum(V["at_risk"])]),
        ('A2.09', "A2.09's exits over the window, the decision, fading",
         [sum(V["fading"])]),
        ('A11.26', "the exits table, row by row: 2022, window launches, at-risk, fading, other mature, A11.26's pruning, club packs, total",
         table),
        ('A10.09', "in-window exits and their sum, then each source with the tail's recipe-mates, row",
         V["total"] + [sum(V["total"])] + V["cohort"] + V["window"] + V["at_risk"] + V["fading"] + V["other"]
         + [V["other_decl"]] + V["prune"] + V["club"]),
        ('A10.09', 'in-window exits and their sum, then each source, A10.09',
         V["total"] + [sum(V["total"])] + V["cohort"] + V["window"] + V["at_risk"] + V["fading"] + V["other"]
         + V["prune"] + V["club"]),
        ('A11.26', "A11.26's prunes over the window and by year, then by kind: other mature, at-risk, fading, launches",
         [sum(V["prune"])] + V["prune"] + [PK["mature"], PK["at_risk"], PK["fading"], PK["launch"]]),
        ('A11.26', "A11.26's prunes still carried at an account with a set when they went",
         [V["prune_carried"] * 100]),
        ('A11.26', "the live catalogue at each year's start and at window end, with the rule",
         V["live_start"] + [V["live_end"]]),
        ('A11.26', "the live catalogue without the rule, at each year's start and at window end",
         NP["live_start"] + [NP["live_end"]]),
        ('A11.26', 'the mature hazard with the rule, two decimals',
         pct(V["hazard"])),
        ('A11.26', 'the mature hazard without the rule',
         pct(NP["hazard"])),
        ('A11.26', "the mature hazard without the rule, group 11's owner list",
         pct(NP["hazard"])),
        ('A11.26', "the mature hazard without the rule, group 11's summary",
         pct(NP["hazard"])),
        ('A11.21', "the mature hazard without the rule, group 11's A11.21 section",
         pct(NP["hazard"])),
        ('A11.26', "the mature hazard without the rule, group 11's A11.26 section",
         pct(NP["hazard"])),
        ('A11.26', "the mature hazard, group 11's summary",
         pct(V["hazard"])),
        ('A11.21', "the mature hazard, group 11's A11.21 section",
         pct(V["hazard"])),
        ('A11.26', "exits over the window and by year without the rule, then R4's pass mark and median there",
         [sum(NP["total"])] + NP["total"] + [NP["p10"], NP["median"]]),
        ('A10.09', 'catalogue exits a year, where the summaries print them',
         V["total"]),
        ('A10.09', 'catalogue exits a year and over the window, the second rulings',
         V["total"] + [sum(V["total"])]),
        ('A10.09', "catalogue exits a year and over the window, group 10's summary table",
         V["total"] + [sum(V["total"])]),
        ('A11.24', 'launch exits through A11.24',
         [V["launch_exits"]["no account"]]),
        ('A7.09', "2022's launches that leave before the window",
         [V["pre_exits"]]),
        ('A11.21', 'the other mature sizes beside a declining recipe-mate, then all of them, doc',
         [V["other_decl"], sum(V["other"])]),
        ('A11.21', "the other mature sizes, then those beside a declining recipe-mate, the owner's list",
         [sum(V["other"]), V["other_decl"]]),
        ('A11.21', 'R4: the 10th percentile, median, mean and pass mark',
         [V["p10"], V["median"], V["mean"], V["p10"]]),
        ('A10.09', "R4's pass mark where the gate's readers print it",
         [V["p10"]]),
        ('A1.10', 'A1.10: launches and club packs added, then the net',
         V["added"] + V["net"]),
        ('A1.10', "A1.10's net where it is published",
         V["net"]),
        ('A10.18', "A10.18's cuts in the draw, then those on launches",
         [V["cuts"], V["launch_cuts"]]),
        ('A11.20', 'the mature hazard',
         pct(V["hazard"])),
        ('A11.26', "the mature hazard, the owner's list",
         pct(V["hazard"])),
        ('A11.20', "the mature hazard, group 11's A11.20 section",
         pct(V["hazard"])),
        ('A11.26', "a declining size's recipe over its floor",
         [V["headroom"]]),
        ('A10.09', 'A10.09 the start-up cull: sizes, recipes, redraws',
         [V["startup_cull"], V["startup_recipes"], V["redraws"]]),
        ('A10.09', "A10.09 the start-up cull: sizes, recipes, group 10's doc",
         [V["startup_cull"], V["startup_recipes"]]),
        ('A10.09', "A10.09 the start-up redraws, group 10's doc",
         [V["redraws"]]),
        ('A10.09', "A10.09 the pre-window exits: 2022's lost launches and A10.16's pre-period delists",
         [V["pre_exits"], V["pre_delists"][2]]),
        ('A10.09', 'the start-up cull, the decision',
         [V["startup_cull"], V["startup_recipes"]]),
        ('A10.06', 'A10.06 the start-up SKU-DC pairs',
         [V["startup_pairs"]]),
        ('A10.06', 'A10.06 pairs in the window, their sum, and those on exiting SKUs',
         V["pairs"] + [sum(V["pairs"]), V["pairs_exiting"]]),
        ('A10.09', 'A10.06 pairs in the window, A10.09',
         V["pairs"]),
        ('A10.06', "A10.06 pairs by year and over the window, group 10's summary table",
         V["pairs"] + [sum(V["pairs"])]),
        ('A7.09', "2022's launches that leave before the window, group 11's owner list",
         [V["pre_exits"]]),
        ('A9.02', 'what A9.02 reads from group 11, row by row, then EBITDA',
         [c[k] for k in ("write_off", "faire", "organic", "oregon", "total") for c in costs] + V["ebitda"]),
        ('A9.02', "group 11's costs, row by row, then EBITDA, group 9's P&L block",
         cost_total + [c[k] for k in ("write_off", "faire", "organic", "oregon") for c in costs] + V["ebitda"]),
        ('A9.02', "group 11's costs, A9.02 and group 9's doc",
         cost_total),
        ('A9.02', "group 11's costs, EBITDA and the gap, revision 6 in the decision",
         cost_total + V["ebitda"] + [V["gap"]]),
        ('A11.01', "Amazon's dollars, own-site dollars and units",
         [a["dollars"] / 1e6 for a in V["amazon"]]
         + [a["own_site"] / 1e6 for a in V["amazon"]] + [a["units"] for a in V["amazon"]]),
        ('A11.01', "Amazon's share of A8.01's 10%, and its share of y3 gross",
         [a["share"] * 100 for a in V["amazon"]] + [V["amazon"][2]["dollars"] / V["gross_y3"] / 1e6 * 100]),
        ('A11.25', 'A11.25 units into Oregon: Walmart',
         [into["Walmart"]]),
        ('A11.25', 'A11.25 units into Oregon: own-site DTC jars',
         [into["DTC"]]),
        ('A11.25', 'A11.25 units into Oregon: Amazon',
         [into["Amazon"]]),
        ('A11.25', 'A11.25 units into Oregon: small accounts',
         [into["small"]]),
        ('A11.25', 'A11.25 units into Oregon: UNFI and KeHE',
         [into["distributors"]]),
        ('A11.25', 'A11.25 units into Oregon: DPI',
         [into["DPI"]]),
        ('A11.25', 'A11.25 units into Oregon, in all, doc',
         [ore["units"]]),
        ('A11.25', 'A11.25 units into Oregon, in all, row',
         [ore["units"]]),
        ('A11.25', 'A11.25 units into Oregon, in all, the decision',
         [ore["units"]]),
        ('A11.25', 'A11.25 the ruled weight: lb, tons, without the distributors, the fee',
         [ruled["lb"], ruled["tons"],
         ruled["tons_without_distributors"],
         ruled["fee"] * 1e6]),
        ('A11.25', 'A11.25 packaging alone: lb a unit, tons, without the distributors, the fee',
         [pack["lb"], pack["tons"], pack["tons_without_distributors"], pack["fee"] * 1e6]),
        ('A11.25', "A11.25 the ruled weight's lb, row",
         [ruled["lb"]]),
        ('A11.25', "A11.25 the ruled weight's tons, row",
         [ruled["tons"]]),
        ('A11.25', 'A11.25 packaging alone, then both readings without the distributors, row',
         [pack["lb"], pack["tons"], ruled["tons_without_distributors"], pack["tons_without_distributors"]]),
        ('A11.25', 'A11.25 the fee at both weights, row',
         [ruled["fee"] * 1e6, pack["fee"] * 1e6]),
        ('A11.25', "A11.25 tons at both weights, the doc's summary",
         [ruled["tons"], pack["tons"]]),
        ('A11.25', 'A11.25 tons, the decision: both weights, then both without the distributors',
         [ruled["tons"], pack["tons"], ruled["tons_without_distributors"], pack["tons_without_distributors"]]),
        ('A11.25', 'A11.25 the fee at both weights, the decision',
         [ruled["fee"] * 1e6, pack["fee"] * 1e6]),
        ('A11.25', "A11.25 the units over the ruling's 2,000 jars",
         [ore["units"] / 2000.0]),
        ('A2.08', "A2.08's packaging weight, where it derives",
         [pack["lb"]]),
        ('A2.08', "A2.08's packaging weight, the column it owes",
         [pack["lb"]]),
        ('A11.22', "A2.08's packaging weight, A11.22's copy",
         [pack["lb"]]),
        ('A2.08', "A2.08's two weights, group 11's owner list",
         [ruled["lb"], pack["lb"]]),
        ('A11.20', 'A11.20 Pacesetter hazard',
         [hz["start"]["shortcut"] * 100, hz["start"]["exact"] * 100, hz["mid"]["shortcut"] * 100, hz["mid"]["exact"] * 100]),
        ('A11.14', 'A11.14 Kroger, row order: fines, other types, wholesale, rate, pool',
         [k["fines"] for k in kro] + [k["others"] for k in kro] + [k["kroger_wholesale"] for k in kro]
         + [k["rate"] * 100 for k in kro] + [k["brand"] * 100 for k in kro]),
        ('A11.29', "A11.29's copy of A11.14's Kroger deduction rate",
         [k["rate"] * 100 for k in kro]),
        ('A11.14', 'A11.14 Kroger, table order: wholesale, fines, other types, rate, pool',
         [k["kroger_wholesale"] for k in kro] + [k["fines"] for k in kro] + [k["others"] for k in kro]
         + [k["rate"] * 100 for k in kro] + [k["brand"] * 100 for k in kro]),
        ('A11.15', 'A11.15 repair dollars',
         list(V["repair"].values())),
        ('A11.13', 'A11.13 distributor purchases',
         [s["purchases"] for s in swell]),
        ('A11.13', 'A11.13 the swell base at UNFI and KeHE, y2 and y3, row',
         [s["purchases"] for s in swell[1:]]),
        ('A11.13', 'A11.13 swell, y1',
         [tuple(swell[0]["swell"])]),
        ('A11.13', 'A11.13 swell by year',
         [tuple(s["swell"]) for s in swell]),
        ('A11.13', "A11.13 swell's share of the type brand-wide, y1",
         [(swell[0]["share"][0] * 100, swell[0]["share"][1] * 100)]),
        ('A11.13', "A11.13 the type brand-wide, then at the distributors' share",
         [s["damaged"] for s in swell] + [s["at_share"] for s in swell]),
        ('A11.13', "A11.13 swell against the type at the distributors' share, then retailers' damaged rate needed",
         [tuple(s["multiple"]) for s in swell] + [(s["retailer_ratio"][1] * 100, s["retailer_ratio"][0] * 100) for s in swell]),
        ('A11.12', 'A11.12 inventory at COGS, then write-offs',
         [w["inventory"] for w in wo] + [w["dollars"] for w in wo]),
        ('A11.11', "A11.11 the floor's reach",
         pct([reach["count"], reach["dollars"]])),
        ('A11.11', "A11.11 the mixture's median and mean, then the floor's reach",
         [reach["median"], reach["mean"]] + pct([reach["count"], reach["dollars"]])),
        ('A11.08', 'A11.08 units shipped, millions, row',
         [u["total"] / 1e6 for u in units]),
        ('A11.08', 'A11.08 units shipped, millions, doc',
         [u["total"] / 1e6 for u in units]),
        ('A11.08', 'A11.08 complaints, then a working day, row',
         [c["complaints"] for c in lots] + [c["per_day"] for c in lots]),
        ('A11.08', 'A11.08 complaints, doc',
         [c["complaints"] for c in lots]),
        ('A11.08', 'A11.08 complaints a working day, doc',
         [c["per_day"] for c in lots]),
        ('A11.08', 'A11.08 kettle lots',
         [c["lots"] for c in lots]),
        ('A11.08', 'A11.08 recall rates, then odds over the window',
         rec_series),
        ('A11.04', "A11.04 the tier's dollars, $K",
         [s["dollars"] / 1e3 for s in small]),
        ('A11.04', 'A11.04 dollars an order',
         [s["aov"] for s in small]),
        ('A11.04', 'A11.04 orders a year on the restated count',
         [s["orders"] for s in small]),
        ('A11.04', 'A11.04 the value the asserted 120 orders implied',
         [s["asserted_aov"] for s in small]),
        ('A11.04', "A11.04 Faire's fees as A9.02 reads them, $K",
         [s["faire"] / 1e3 for s in small]),
        ('A11.04', 'A11.04 brand-wide bad debt $K, then against the tier',
         [s["bad_debt"] / 1e3 for s in small] + pct([s["bad_share"] for s in small])),
        ('A11.04', 'A11.04 brand-wide bad debt against the tier',
         pct([s["bad_share"] for s in small])),
        ('A11.09', 'A11.09 organic sales stand-in',
         [o["sales"] for o in og]),
        ('A11.09', 'A11.09 the organic certificate as A9.02 reads it, $',
         [o["net"] * 1e6 for o in og]),
        ('A11.19', 'A11.19 buyer resets, then the share of quarters in a reset',
         [r["resets"] for r in V["resets"]] + [V["resets"][0]["in_reset"] * 100]),
        ('A10.16', "A10.16's cap reading: the A:C cadence on the multiplier, then on generated volume",
         [V["cadence"]["ratio"], V["cadence"]["volume_ratio"]]),
        ('A11.26', "A11.26's spread of the y3 carried sets",
         [V["within"]]),
        ('A2.09', "A2.09's at-risk and fading sizes, as A11.26's rule takes them",
         [PK["at_risk"], PK["fading"]]),
        ('A10.09', "A10.09's launch exits through A11.24, the window total, and A11.26's share of it",
         [V["launch_exits"]["no account"], sum(V["total"]), sum(V["prune"])]),
        ('A7.13', "A7.13's causal arms: the index-100 and no-factor counterfactuals beside the baseline",
         [V["a713_arms"]["index100"]["first"] * 100, V["first"] * 100, V["a713_arms"]["no_factor"]["first"] * 100,
          V["a713_arms"]["index100"]["two"] * 100, V["a713_arms"]["no_factor"]["two"] * 100]),
        ('A7.13', "A7.13's causal arms where group 7 prints the 90-day pair",
         [V["a713_arms"]["index100"]["first"] * 100, V["a713_arms"]["no_factor"]["first"] * 100]),
        ('A10.16', "A10.16's sigma-2.0 alternative: the spread, its first-draw cull, and this reading's",
         [V["ceiling2"]["spread"], V["ceiling2"]["cull"], V["startup_cull"]]),
        ('A7.13', 'A7.13 does not land near its practitioner shares',
         abs(V["first"] - 0.25) > 0.05 or abs(V["two"] - 0.40) > 0.05),
        ('A11.21', 'the 24-month share sits inside the category band',
         0.12 <= V["horizon"] <= 0.42),
        ('A5.28', "the generated-volume cadence falls outside A5.28's 3-4 runs",
         V["cadence"]["volume_c_runs"] < 3),
        ('A11.21', 'the seven invariants hold in every quarter of every trial',
         not any(viol.values())),
        ('A11.26', 'A11.26 prunes more than a rounding',
         sum(V["prune"]) > 0.5),
        ('A11.26', "A11.26 is what brings the drawn catalogue back to A2.01's",
         V["live_end"] < NP["live_end"] - 1),
        ('A11.24', 'every launch exit comes through A11.24',
         V["launch_exits"]["run floor"] == 0),
        ('A11.21', 'no other mature exit was carried by a retailer',
         V["tail_carried"] == 0),
        ('A11.25', 'every Oregon reading passes one metric ton',
         min(ruled["tons"], pack["tons"], ruled["tons_without_distributors"], pack["tons_without_distributors"]) > 1),
    ]


def outputs(acct=None, trial=0):
    """U21's entry function: what the gate checks and the seeders read, one object (regen plan U21).

    `printed` holds every value the registry prints from this generator, keyed by the anchor id that prints it and
    then by the gate entry that reads it, at full precision. `trial` is the replayed trial's catalogue lifecycle on the
    generator's own streams (trial_rng): its window-start and window-end catalogues, decliners, launches and exits,
    trial 0 by the owner's ruling of 2026-10-14 (DECISIONS#u18-rulings). It names which SKUs the world declines, the
    answer a detection tool is scored against, so no row prints it and the gate checks none of it. Given `acct`, the
    solved factor, account_sigma() returns it and solve_account_factor() is never called; omitted, it is solved."""
    if acct is not None:
        F._SOLVED["acct"] = acct
    acct = F.account_sigma()
    V = dict(G._values())
    V.update(F._values(acct))
    V.update(_values(acct))
    printed = {}
    for fn in (_printed_restated_21, _printed_group11):
        for anchor, label, value in fn(V):
            printed.setdefault(anchor, {})[label] = value
    return dict(printed=printed, trial=catalogue_draws(acct=acct, trials=trial + 1, replay=trial)["replay"])


# ------------------------------------------------------------ the report
def _s(v, p=3):
    return " / ".join(("%." + str(p) + "f") % x for x in v)


def main():
    print("GROUP 11 -- the launch lifecycle on the registered floors, and what the rest of the group derives")
    print("")
    print("FREE INPUTS AND READINGS (the rest is read from registered rows)")
    for name, val, status in INPUTS:
        print("   %-26s %-104s %s" % (name, val, status))

    print("")
    print("CHECK 0  the catalogue is group 10's, reproduced before it is extended")
    acct = F.account_sigma()
    B = base_at(acct)
    R0 = catalogue_draws(launches=False, decline=False, prune=False)
    tail0 = R0["by_year"]["other mature"]
    same = (tail0 == B["exits"] and R0["pairs"] == B["pairs"] and R0["by_year"]["club packs"][2] == B["club"]
            and R0["redraws"] == B["redraws"] and R0["mean_m"] == B["mean_m"])
    print("   group10_floors.catalogue_exits(): %.3f redraws a window start, mean multiplier %.4f, in-window exits %s,"
          " pairs %s, club exits %.3f" % (B["redraws"], B["mean_m"], _s(B["exits"]), _s(B["pairs"]), B["club"]))
    print("   catalogue_draws, launches and decline off: %.3f, %.4f, %s, %s, %.3f   %s"
          % (R0["redraws"], R0["mean_m"], _s(tail0), _s(R0["pairs"]), R0["by_year"]["club packs"][2],
             "reproduces" if same else "*** DOES NOT REPRODUCE ***"))
    print("   (without a lifecycle both sides carry no exits, so CHECK 0 holds only the draw's start; CHECK 1 carries the"
          " mechanism. A11.26's pruning is off in this arm for the same reason launches and decline are: group 10 has no"
          " brand-side rule)")

    print("")
    print("A11.21  the launch lifecycle at lambda %.0f and sigma_pred %.2f, both owner-signed: nothing is solved against the"
          " survival target; the one solve is the account factor's, against A7.03's spread less door and week" % (LAMBDA, SIGMA_PRED))
    R = catalogue_draws()
    V_ = R["violations"]
    print("CHECK 1  invariants in every quarter of every trial (%d quarter-trials): a launch's flag and its set disagree %d"
          " times, a SKU is carried and gone %d times, a launch sits at a non-launch account %d times, allocated units"
          " miss A5.38's less Costco's plus A8.02's jars and Amazon's units %d times, an exited SKU is still carried %d"
          " times, a gone set or"
          " the dead pairs shrink %d times, an A11.26 prune does not land %d times   %s"
          % (R["checks"], V_["flag"], V_["gone"], V_["set"], V_["units"], V_["exited"], V_["monotone"], V_["prune"],
             "holds" if not any(V_.values()) else "*** VIOLATED ***"))

    print("")
    print("GROUP 10 ON A5.38'S UNITS (ruled 2026-09-14)")
    print("   the start-up artifact, on each window start's first draw: %.3f sizes in %.3f recipes, %.2f SKU-DC pairs"
          % (B["startup_cull"], B["startup_recipes"], B["startup_pairs"]))
    print("   culled sizes are redrawn in their slots: %.2f redraws a window start, mean multiplier %.3f"
          % (B["redraws"], B["mean_m"]))
    print("   A7.03's %.3f decomposes (ruled 2026-09-15): door %.2f (band %.2f-%.2f) and week %.2f come out of it, so a"
          " carried set spreads %.3f AT THE ACCOUNT, %.3f-%.3f at the band's ends"
          % (SIGMA, F.SIGMA_DOOR, F.SIGMA_DOOR_BAND[0], F.SIGMA_DOOR_BAND[1], F.SIGMA_WEEK, F.SIGMA_ACCOUNT,
             F.account_target(F.SIGMA_DOOR_BAND[1]), F.account_target(F.SIGMA_DOOR_BAND[0])))
    # #drawn-precision: a solved log-sd prints two decimals and a drawn share prints none. Four disjoint seed
    # sets of 6,000 put the factor at 0.5953-0.6004 and A7.13's shares inside a point, so the decimals below
    # were decimals the seeds did not hold. The exact values stay available in the returned dicts.
    print("   the SKU x account factor's log-sd solves to %.2f on the window's own y3 carried sets, which then spread %.2f"
          " against that target; on the window-start catalogue alone it would solve to %.2f"
          % (acct, R["within"], F.launch_free_sigma()))
    print("   carried sets on group 10's catalogue with no launches, at window start (Sprouts at its y2 opening), spread of"
          " log velocity at the account: %s"
          % "; ".join("%s %.3f" % (a, B["sets"][a]["logsd"][0 if a != "Sprouts" else 1]) for a in F.RETAIL_ACCOUNTS))
    CB = cadence_bound()
    CV = cadence_on_volume(acct=acct)
    print("   A5.28 as a bound, ON THE MULTIPLIER as ruled: at catalogue sigma %.3f the A:C cadence is %.2f:1, C items at"
          " %.1f runs a year with A at %.0f; at 2.0 it is %.1f:1 and C runs %.2f; A5.28's midpoint reads as %.3f, its"
          " widest as %.3f" % (SIGMA, CB["ratio"], CB["c_runs"], CB["a_mid"], CB["ratio_at_2"], CB["c_runs_at_2"],
                              CB["sigma_at_mid"], CB["sigma_at_widest"]))
    mid_v = sigma_for_volume_cadence(CB["a_mid"] / (sum(A528_RUNS["C"]) / 2.0), acct)
    wide_v = sigma_for_volume_cadence(A528_RUNS["A"][1] / float(A528_RUNS["C"][0]), acct)
    print("   the same rule ON GENERATED IN-HOUSE RECIPE VOLUME: at %.3f the A:C cadence is %.2f:1 and C recipes run %.1f"
          " times a year; A5.28's widest is met at a catalogue sigma of %.3f and its midpoint at %.3f, the factor held"
          % (SIGMA, CV["ratio"], CV["c_runs"], wide_v, mid_v))
    D10 = F.authorization_draw()
    print("   A10.16's floor delists, with the account factor: Kroger %.3f + Walmart %.3f = %.3f; the pre-period's own"
          " exits %.2f + %.2f = %.2f, outside the window, and %.2f + %.2f = %.2f strikes carried into y1"
          % (D10["Kroger"]["exits"], D10["Walmart"]["exits"], D10["total_exits"],
             D10["Kroger"]["pre_exits"], D10["Walmart"]["pre_exits"], D10["total_pre_exits"],
             D10["Kroger"]["carried"], D10["Walmart"]["carried"], D10["total_carried"]))

    print("")
    print("A11.21  what derives")
    gone = (1 - TARGET["survival"]) * 100
    print("   launches gone from the catalogue by %d months: %.0f%%, over the %.2f launches a seed observed for 24 months;"
          " A11.20's branded %.0f%%, the category %.0f-%.0f%% | 2022's cohort %.0f%%, the window's %.0f%%"
          % (TARGET["months"], R["horizon"] * 100, R["observed"], gone, (1 - TARGET["band"][1]) * 100,
             (1 - TARGET["band"][0]) * 100, R["horizon_by"]["2022"] * 100, R["horizon_by"]["window"] * 100))
    print("   A7.13 DERIVES: %.0f%% of new listings delisted at the 90-day check (Walmart %.0f, Kroger %.0f, Whole Foods %.0f);"
          " %.0f%% delisted or cut within two years | 2022's cohort %.0f%% / %.0f%%, the window's %.0f%% / %.0f%%"
          % (R["a713"][0] * 100, R["a713_first"]["Walmart"] * 100, R["a713_first"]["Kroger"] * 100,
             R["a713_first"]["WF"] * 100, R["a713"][1] * 100, R["a713_by"]["2022"][0] * 100, R["a713_by"]["2022"][1] * 100,
             R["a713_by"]["window"][0] * 100, R["a713_by"]["window"][1] * 100))
    for sp in SIGMA_PRED_SENSITIVITY:
        S = catalogue_draws(sp)
        print("   sensitivity, sigma_pred %.2f, the factor held at the 0.60 solve: gone by 24 months %.0f%% | A7.13 %.0f%% /"
              " %.0f%% | exits %s | R4's 10th percentile %d"
              % (sp, S["horizon"] * 100, S["a713"][0] * 100, S["a713"][1] * 100, _s(S["total"], 2), S["p10"]))

    print("")
    print("THE CATALOGUE, DRAWN PER SEED (%d trials): 2022's cohort and the window's launches, A2.09's %d at-risk and %d fading"
          % (TRIALS, DECLINER_COUNT["at_risk"], DECLINER_COUNT["fading"]))
    for k in ("2022 cohort", "window launches", "A2.09 at-risk", "A2.09 fading", "other mature", "A11.26 pruning",
              "club packs"):
        print("   %-18s %s = %.2f" % (k, _s(R["by_year"][k], 2), sum(R["by_year"][k])))
    print("   IN-WINDOW CATALOGUE EXITS %s = %.2f | SKU-DC pairs %s = %.2f, %.2f of them on SKUs leaving the catalogue that"
          " quarter | 2022's launches gone before the window %.2f"
          % (_s(R["total"], 2), sum(R["total"]), _s(R["pairs"], 2), sum(R["pairs"]), R["pairs_exiting"], R["pre_exits"]))
    print("   launch exits by rule: A11.24's no national account %.2f, the run floor %.2f, A11.26's pruning %.2f"
          % (R["launch_exits"]["no account"], R["launch_exits"]["run floor"], R["launch_exits"]["pruned"]))
    PK = R["prune_kind"]
    print("   A11.26 DERIVES: %.2f sizes discontinued at the planning cycle, %s by year - below %.0f%% of median velocity"
          " in both preceding quarters with no national authorization; by kind, other mature %.2f, A2.09 at-risk %.2f,"
          " fading %.2f, launches %.2f; only %.2f%% carried at an account with a set in the quarter they went"
          % (sum(R["prune"]), _s(R["prune"], 2), PRUNE_SHARE * 100, PK["mature"], PK["at_risk"], PK["fading"],
             PK["launch"], R["prune_carried"] * 100))
    print("   other mature exits %.2f: carried by a retailer in the quarter they left %.1f%%; culled with a declining"
          " recipe-mate %.2f" % (sum(R["by_year"]["other mature"]), R["tail_carried"] * 100, R["tail_with_decliner"]))
    print("   launches %.2f; A10.18 cuts %.2f, %.2f of them on launches" % (R["launched"], R["cuts"], R["launch_cuts"]))
    print("   R4: exits per seed - 10th percentile %d, median %d, mean %.2f; distribution %s"
          % (R["p10"], R["median"], R["mean"], ", ".join("%d: %.1f%%" % (k, v * 100) for k, v in R["dist"].items())))
    added = [LAUNCHES_A_YEAR + (F.CLUB_ACCEPTED if y == 2 else 0) for y in range(3)]
    print("   A1.10 DERIVED: A7.09's launches and Costco's club packs %s less exits %s = net %s SKUs a year"
          % (_s(added, 2), _s(R["total"], 2), _s([added[y] - R["total"][y] for y in range(3)], 2)))
    print("   the non-club catalogue actually live at each year's start %s, and %.2f at window end, against A2.01's"
          " %s read as the catalogue by year" % (_s(R["live_start"], 2), R["live_end"],
                                                 " / ".join("%d" % s for s in F.ACTIVE_SKUS)))

    print("")
    print("THE MATURE SET'S PLAUSIBILITY")
    P = pacesetter_hazard()
    print("   IRI's 44%% as a constant annual hazard: shortcut %.1f%% / exact %.1f%% at start-of-year ages (mean %.1f);"
          " shortcut %.1f%% / exact %.1f%% at mid-year ages (mean %.1f)"
          % (P["start"]["shortcut"] * 100, P["start"]["exact"] * 100, P["start"]["mean_age"],
             P["mid"]["shortcut"] * 100, P["mid"]["exact"] * 100, P["mid"]["mean_age"]))
    print("   the mature catalogue's hazard in the draw, exits over the mature sizes live at each year's start: %s%%"
          % _s([h * 100 for h in R["hazard"]], 1))

    print("")
    print("THE REST OF GROUP 11 -- the figures that derive from registered rows")
    print("   A11.14 Kroger, as ruled ($M; rates on Kroger's own wholesale):")
    for y, k in enumerate(kroger_deduction_rate()):
        print("      y%d Kroger wholesale %.4f | late fines by A5.15's mechanism %.4f vs by volume %.4f | other types %.4f"
              " | Kroger %.2f%% vs brand pool %.2f%%"
              % (y + 1, k["kroger_wholesale"], k["fines"], k["late_by_volume"], k["others"], k["rate"] * 100, k["brand"] * 100))
    print("   A11.15 repair dollars at A9.05's $%.2f loaded hour:" % LOADED_HOURLY)
    for name, d in repair_dollars().items():
        print("      %-28s %2d min  $%.2f" % (name, REPAIR_MINUTES[name], d))
    print("   A11.13 distributor swell against A4.05's damaged/unsaleables type ($M):")
    for y, s in enumerate(swell_containment()):
        print("      y%d purchases %.3f | swell %.4f-%.4f | type brand-wide %.4f (%.0f-%.0f%%) | type at distributor share %.4f"
              " -> swell %.2f-%.2fx it | brand-wide fit needs retailers' damaged rate at %.0f-%.0f%% of distributors'"
              % (y + 1, s["purchases"], s["swell"][0], s["swell"][1], s["damaged"], s["share"][0] * 100, s["share"][1] * 100,
                 s["at_share"], s["multiple"][0], s["multiple"][1], s["retailer_ratio"][1] * 100, s["retailer_ratio"][0] * 100))
    print("   A11.12 write-offs, A5.21's rate on A9.12's inventory ($M), read by A9.02:")
    for y, w_ in enumerate(write_offs()):
        print("      y%d inventory %.3f x %.1f%% = %.4f | donate %.4f liquidate %.4f destroy %.4f"
              % (y + 1, w_["inventory"], w_["rate"] * 100, w_["dollars"], w_["split"]["donate"], w_["split"]["liquidate"],
                 w_["split"]["destroy"]))
    print("   A11.08 units, complaints and lots:")
    for y, (u, c) in enumerate(zip(units(), complaints_and_lots())):
        print("      y%d units %.2fM (wholesale %.2fM, club %.2fM, own-site jars %.2fM, Amazon %.2fM) -> complaints"
              " %.0f, %.1f a working day | in-house kettle lots %.0f"
              % (y + 1, u["total"] / 1e6, u["wholesale"] / 1e6, u["club"] / 1e6, u["dtc"] / 1e6, u["amazon"] / 1e6,
                 c["complaints"], c["per_day"], c["lots"]))
    O = recall_odds()
    print("   A11.08 recall events per food establishment: %s -> %.2f%% a year, %.1f%% over the window; a recall is a draw"
          % (" / ".join("FY%d %.2f%%" % (yr, r * 100) for yr, r in sorted(O["rates"].items())), O["mean"] * 100,
             O["window"] * 100))
    print("   A11.04 small accounts against A5.38, A5.02 as restated and A9.01; Faire on the signed 40 / 10 / 50 split,"
          " read by A9.02:")
    for y, s in enumerate(small_accounts()):
        print("      y%d dollars $%.0fK over A5.02's derived %d orders = $%.0f an order (A5.02's retired 120 gave"
              " $%.0f) | $%.0fK of the tier is on Faire | Faire fees $%.1fK | A9.01's brand-wide bad debt $%.1fK ="
              " %.1f%% of the tier's dollars"
              % (y + 1, s["dollars"] / 1e3, s["orders"], s["aov"], s["asserted_aov"], s["on_faire"] / 1e3,
                 s["faire"] / 1e3, s["bad_debt"] / 1e3, s["bad_share"] * 100))
    print("   A11.01 Amazon inside A8.01's 10%, its share owner-signed (item 12); A11.22's retired 8% floor and band, with the current plan:")
    for y, a in enumerate(amazon()):
        print("      y%d Amazon %.0f%% of the 10%% = $%.3fM at A3.18's $%.2f = %.0f units; own site $%.3fM = %.0f"
              " A8.02 jars | RETIRED reading: referral at the 8%% floor $%.1fK + plan $%.1fK = $%.1fK, the band $%.1f-%.1fK"
              % (y + 1, a["share"] * 100, a["dollars"] / 1e6, G.AMAZON_PRICE, a["units"], a["own_site"] / 1e6,
                 a["jars"], a["referral"] * 1e3, a["plan"] * 1e3, a["total"] * 1e3, a["band"][0] * 1e3,
                 a["band"][1] * 1e3))
    Rm = materiality_reach()
    print("   A11.11 a $250 floor on A10.17's mixture (median $%.1f, mean $%.1f): exempts %.1f%% of deductions by count,"
          " %.1f%% by dollars" % (Rm["median"], Rm["mean"], Rm["count"] * 100, Rm["dollars"] * 100))
    print("   A11.19 buyer resets at %.0f%% a year: %s a year across %s account-years; an account spends %.0f%% of its quarters in a reset"
          % (BUYER_TURNOVER * 100, _s([r["resets"] for r in buyer_resets()], 3),
             " / ".join("%.2f" % r["accounts"] for r in buyer_resets()), buyer_resets()[0]["in_reset"] * 100))
    OG = [G.organic_certificate(y) for y in range(3)]
    print("   A11.09 organic at Tilth's Retail class, A2.18's ~20%% count share standing in for sales ($M %s): fee $%d +"
          " facility $%.0f + inspection $%.0f - OCCSP $%s = $%s, read by A9.02"
          % (_s([o["sales"] for o in OG], 2), OG[0]["fee"], OG[0]["facility"], OG[0]["inspection"],
             " / ".join("%.0f" % o["occsp"] for o in OG),
             " / ".join("%.0f" % (o["net"] * 1e6) for o in OG)))
    E = G.oregon()
    print("   A11.10 Oregon on 2024 supply: Walmart %.0f + own-site DTC %.0f + Amazon %.0f + small accounts %.0f + UNFI"
          " and KeHE %.0f + DPI %.0f = %.0f units; revenue test: 2024 gross $%.3fM, so it fails"
          % (E["into"]["Walmart"], E["into"]["DTC"], E["into"]["Amazon"], E["into"]["small"],
             E["into"]["distributors"], E["into"]["DPI"], E["units"], G.GROSS[1]))
    for label, name in (("ruled", "at the ruled %.2f lb" % G.UNIT_LB), ("packaging", "on packaging, %.2f lb" % (G.UNIT_LB - G.NET_CONTENTS_LB))):
        e_ = E[label]
        print("      %-24s %.1f metric tons (%.1f without UNFI, KeHE and DPI) -> %s; fee at $%.2f/lb $%.0f"
              % (name, e_["tons"], e_["tons_without_distributors"], "OBLIGATED" if e_["obligated"] else "exempt",
                 G.GLASS_RATE, e_["fee"] * 1e6))
    print("      the rate is CAA's 2025 class average for glass and ceramics, $%.2f a pound, Tier B and effective-dated"
          " to 2025; its first DATED schedule, for 2026, prints glass bottles and jars at $%.2f, which A1.07's Do-not"
          " keeps out of the window" % (G.GLASS_RATE, G.GLASS_RATE_2026))
    Pl = G.pnl()
    print("   WHAT A9.02 READS FROM GROUP 11 ($M): write-offs %s + Faire %s + organic %s + Oregon %s = %s"
          " -> EBITDA %s"
          % (_s([r["write_off"] for r in Pl["group11"]], 4), _s([r["faire"] for r in Pl["group11"]], 4),
             _s([r["organic"] for r in Pl["group11"]], 4), _s([r["oregon"] for r in Pl["group11"]], 4),
             _s([r["total"] for r in Pl["group11"]], 4), _s(Pl["ebitda"], 4)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
