"""Generator parity (plan U15): the generated world reproduces the spec generators' printed outputs.

Every key every entry function returns has a route in parity_routes.json, and
a key with none fails (the coverage test). A route is one of:
- `arm`: an exact or draw arm in this file, named by its test;
- `owed`: an arm pre-registered here, its class, assertion and writer unit
  fixed before generation; the writer writes it as SQL when it gives the table
  the shape the assertion reads. While the vendored plan marks the writer
  not DONE the row is red by design; once DONE, an owed route fails here;
- `suite`: checked by another named suite and assertion (the landings table's
  Suite column), its writer named;
- `unread`: read by no seeder, with why.
Each key is classed as exact or a draw by the generator's own form, never by
what generation produces. The keys that land in truth stay with the R7 ledger
suite, so this file never reads truth.

Perturbation: every bundle output a seeder reads, moved one unit in a patched
bundle, must change that seeder's planned rows (the probe method).
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "generation"))
import realism_bundle  # noqa: E402

HERE = Path(__file__).resolve().parent
ROUTES = json.loads((HERE / "parity_routes.json").read_text(encoding="utf-8"))
UNITS = json.loads((ROOT / "vendor" / "realism" / "unit_status.json").read_text(encoding="utf-8"))
AP = realism_bundle.AP_SCHEDULE
#: red by design: committed before U15's step 5 gives seed_costing plan(bundle) and its paid-date rule
RED_UNTIL_STEP_5 = pytest.mark.xfail(strict=True, reason="committed red before U15 step 5's seed_costing edit")


@pytest.fixture(scope="module")
def bundle():
    return realism_bundle.load()


# ---------------------------------------------------------------- coverage
def keys(outputs) -> set[str]:
    """Every key the entry functions return: each printed entry, each series, the pinned trial."""
    out = set()
    for gen, o in outputs["generators"].items():
        for anchor, labels in o["printed"].items():
            out |= {"|".join((gen, "printed", anchor, label)) for label in labels}
        out |= {f"{gen}|series|{name}" for name in o.get("series", {})}
        if "trial" in o:
            out.add(f"{gen}|trial")
    return out


def route_problems(keyset, routes, units, module) -> list[str]:
    bad = [f"no route: {k}" for k in sorted(keyset - set(routes))]
    bad += [f"route for a key no entry function returns: {k}" for k in sorted(set(routes) - keyset)]
    for k, r in sorted(routes.items()):
        kind = r.get("route")
        if kind == "arm" and not callable(getattr(module, r.get("test", ""), None)):
            bad.append(f"{k}: its arm {r.get('test')} is not in this file")
        elif kind in ("owed", "suite") and not (r.get("writer") in units and r.get("assertion")):
            bad.append(f"{k}: a {kind} route names no window unit and assertion")
        elif kind == "owed" and r.get("class") not in ("exact", "draw", "tolerance"):
            bad.append(f"{k}: an owed arm is classed exact, draw or tolerance")
        elif kind == "unread" and not r.get("why"):
            bad.append(f"{k}: an unread key says why")
        elif kind not in ("arm", "owed", "suite", "unread"):
            bad.append(f"{k}: no such route {kind!r}")
    return bad


def test_every_key_every_entry_function_returns_has_a_route(bundle):
    assert route_problems(keys(bundle.outputs), ROUTES, UNITS, sys.modules[__name__]) == []


def test_a_key_added_to_an_entry_function_with_no_route_fails_the_coverage_test(bundle):
    added = keys(bundle.outputs) | {"group9_ledger|printed|A9.11|a new entry"}
    assert route_problems(added, ROUTES, UNITS, sys.modules[__name__]) == [
        "no route: group9_ledger|printed|A9.11|a new entry"]


def test_a_writer_that_has_landed_leaves_no_owed_arm():
    landed = sorted({r["writer"] for r in ROUTES.values() if r["route"] == "owed" and UNITS[r["writer"]]["done"]})
    assert landed == [], f"{landed} are DONE in the vendored plan; write their owed arms as tests here"


# ---------------------------------------------------------------- perturbation
def _invoices():
    """A fixed invoice set across the window, mixed sizes, so a moved run or share moves whole invoices."""
    rows, d, n = [], date(2022, 12, 20), 0
    while d < date(2026, 1, 1):
        n += 1
        rows.append((f"SINV-{n:06d}", "SUP-COPACK-01", f"RUN-{n:05d}", d, None, None, "copack",
                     1000.0 + 37.0 * (n % 23), 0.0, 0.0, 0.0))
        d += timedelta(days=3)
    return rows


def _moved(b):
    """Each output seed_costing reads through the bundle, moved one unit (a day; a day of DPO or terms; one AP-run
    day of the month; one $M of a run's held share)."""
    sched = b.ap_schedule()
    return {
        "the AP-run schedule's days": b.patched(("printed",) + AP, [dict(r, day=r["day"] + timedelta(1))
                                                                    for r in sched]),
        "the AP-run schedule's held": b.patched(("printed",) + AP, [dict(r, held=min(r["due"], r["held"] + 1.0))
                                                                    for r in sched]),
        "A9.11's DPO": b.patched(("constant", "group9_ledger", "DPO"), b.constant("group9_ledger", "DPO") + 1),
        "A9.11's AP-run days": b.patched(("constant", "group9_ledger", "AP_RUN_DAYS"), (2, 17)),
        "A9.11's co-packer terms": b.patched(("constant", "group10_floors", "SUPPLIER_TERMS"),
                                             dict(b.constant("group10_floors", "SUPPLIER_TERMS"), **{
                                                 "co-packers": b.supplier_terms("co-packers") + 1})),
    }


@RED_UNTIL_STEP_5
@pytest.mark.parametrize("output", ["the AP-run schedule's days", "the AP-run schedule's held", "A9.11's DPO",
                                    "A9.11's AP-run days", "A9.11's co-packer terms"])
def test_each_output_seed_costing_reads_moves_its_planned_rows(bundle, output):
    import seed_costing
    if "AP-run days" in output:      # a moved run day must still find a run in the ledger's schedule
        sched = [dict(r, day=r["day"] + timedelta(1)) for r in bundle.ap_schedule()]
        base = bundle.patched(("printed",) + AP, sched)
        moved = base.patched(("constant", "group9_ledger", "AP_RUN_DAYS"), (2, 17))
        assert seed_costing.plan(moved, _invoices()) != seed_costing.plan(base, _invoices())
        return
    assert seed_costing.plan(_moved(bundle)[output], _invoices()) != seed_costing.plan(bundle, _invoices())


@RED_UNTIL_STEP_5
def test_the_packaging_suppliers_terms_move_its_row(bundle):
    import seed_costing
    p = bundle.patched(("constant", "group10_floors", "SUPPLIER_TERMS"),
                       dict(bundle.constant("group10_floors", "SUPPLIER_TERMS"), glass=46))
    products = {"S1": {"product_line": "Sauces"}}
    assert seed_costing.build_suppliers(products, p) != seed_costing.build_suppliers(products, bundle)


# ---------------------------------------------------------------- U15's exact arm: paid dates
def paid_date_problems(bundle, rows) -> list[str]:
    """rows: (invoice_id, invoice_date, due_date, paid_date, goods, surcharge, moq, credit) as written.

    Exact: each paid date equals the one the daily ledger's schedule and U18's oldest-first rule give. Then, read
    from the rows alone, each is a run day of the schedule (or the invoice's own run past the window), never before
    the invoice's run, and at every run the invoices paid are older than every invoice left waiting."""
    import seed_costing
    bad = []
    given = [(i, None, None, d, None, None, "copack", g, s, m, c) for i, d, _, _, g, s, m, c in rows]
    want = {r[0]: (r[4], r[5]) for r in seed_costing.plan(bundle, given)}
    days = [r["day"] for r in bundle.ap_schedule()]
    last = days[-1]
    for i, d, due, paid, *_ in rows:
        if (due, paid) != want[i]:
            bad.append(f"{i}: due {due}, paid {paid}; the ledger gives due {want[i][0]}, paid {want[i][1]}")
        run = bundle.ap_run(d)
        if paid < run:
            bad.append(f"{i}: paid {paid}, before its AP run {run}")
        if paid not in days and not (run > last and paid == run):
            bad.append(f"{i}: paid {paid}, not an AP run of the ledger's schedule")
    order = {i: (d, i) for i, d, *_ in rows}
    run_of = {i: bundle.ap_run(d) for i, d, *_ in rows}
    paid_of = {r[0]: r[3] for r in rows}
    for day in days:
        due_by = [i for i in paid_of if run_of[i] <= day and paid_of[i] >= day]
        paid_now = [order[i] for i in due_by if paid_of[i] == day]
        waiting = [order[i] for i in due_by if paid_of[i] > day]
        if paid_now and waiting and max(paid_now) > min(waiting):
            bad.append(f"{day}: paid {max(paid_now)[1]} while the older {min(waiting)[1]} waits")
    return bad


def _written(db):
    with db.cursor() as cur:
        cur.execute("SELECT invoice_id, invoice_date, due_date, paid_date, goods_amount, freight_surcharge, moq_fee, "
                    "short_ship_credit FROM costing.fct_supplier_invoices WHERE invoice_type = 'copack' "
                    "ORDER BY invoice_id")
        return cur.fetchall()


@pytest.mark.db
@RED_UNTIL_STEP_5
def test_every_copack_invoice_is_paid_on_the_daily_ledgers_schedule(db, bundle):
    rows = _written(db)
    assert rows, "costing.fct_supplier_invoices holds no copack invoice"
    assert paid_date_problems(bundle, rows) == []


@RED_UNTIL_STEP_5
def test_one_invoice_paid_a_day_off_the_ledger_fails_the_arm(bundle):
    import seed_costing
    given = _invoices()[:200]
    planned = seed_costing.plan(bundle, given)
    rows = [(r[0], r[3], r[4], r[5], r[7], r[8], r[9], r[10]) for r in planned]
    assert paid_date_problems(bundle, rows) == []
    i, d, due, paid, *rest = rows[57]
    rows[57] = (i, d, due, paid + timedelta(1), *rest)
    assert any(p.startswith(f"{i}:") for p in paid_date_problems(bundle, rows))
