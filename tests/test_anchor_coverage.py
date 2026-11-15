"""The coverage gate (plan U5): each arm broken one way on an in-memory copy, and the finding names that row or
constant and never a neighbour's (DECISIONS#self-test-attribution). A check never shown to fail is not known to work."""
from __future__ import annotations

import copy
import json
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "generation"))
import check_anchor_coverage as cov  # noqa: E402

VENDOR = ROOT / "vendor" / "realism"


@pytest.fixture(scope="module")
def base():
    manifest = json.loads((VENDOR / "MANIFEST.json").read_text("utf-8"))
    rows = yaml.safe_load((VENDOR / "anchors.yml").read_text("utf-8"))
    sources = {p.stem: p.read_text("utf-8") for p in sorted((ROOT / "generation").glob("seed_*.py"))}
    ca = cov.load_spec_gate(VENDOR)
    return {"manifest": manifest, "rows": rows, "sources": sources, "ca": ca,
            "index": {r["anchor_id"]: r for r in rows}}


def _all(report):
    return [f for fs in report.blocking.values() for f in fs]


def _keys_and_consts(base, sources=None):
    sources = sources or base["sources"]
    return cov.read_keys(sources["seed_config"]), cov.seeder_constants(sources, base["ca"])


def test_the_committed_bundle_and_seeders_pass(base):
    report = cov.check()
    assert _all(report) == [], report.blocking
    assert set(report.blocking) == {"bundle", "seeder keys", "seeder prints", "first-order", "effective dating"}


# ── bundle ──────────────────────────────────────────────────────────

def test_a_file_whose_hash_differs_from_the_manifest_fails_naming_the_file(base):
    m = copy.deepcopy(base["manifest"])
    m["files"]["anchors.yml"] = "0" * 64
    report = cov.Report()
    assert not cov.arm_bundle(VENDOR, m, report)
    assert report.blocking["bundle"] == [f"anchors.yml: SHA-256 {cov.hashlib.sha256((VENDOR / 'anchors.yml').read_bytes()).hexdigest()} where the MANIFEST records {'0' * 64}"]


def test_a_manifest_recording_a_spec_gate_that_was_not_clean_fails(base):
    m = copy.deepcopy(base["manifest"])
    m["spec_gate"]["clean"], m["spec_gate"]["blocking_findings"] = False, 3
    report = cov.Report()
    assert not cov.arm_bundle(VENDOR, m, report)
    assert len(report.blocking["bundle"]) == 1 and "was not CLEAN (3 blocking findings)" in report.blocking["bundle"][0]


def test_an_unverified_bundle_stops_every_other_arm(base):
    m = copy.deepcopy(base["manifest"])
    m["files"]["check_anchors.py"] = "f" * 64
    report = cov.check(manifest=m)
    assert list(report.blocking) == ["bundle"]


# ── seeder keys ─────────────────────────────────────────────────────

def test_an_unlisted_numeric_constant_fails_naming_it(base):
    sources = dict(base["sources"], seed_retailer=base["sources"]["seed_retailer"] + "\nNEW_RATE = 0.5\n")
    keys, consts = _keys_and_consts(base, sources)
    report = cov.Report()
    cov.arm_keys(consts, keys, base["index"], report)
    assert report.blocking["seeder keys"] == ["seed_retailer.NEW_RATE: a numeric constant neither keyed, exempt nor owed"]


def test_a_key_naming_an_absent_row_fails_naming_the_constant(base):
    cfg = base["sources"]["seed_config"].replace('{"key": "A4.07"}', '{"key": "A99.99"}')
    keys, consts = _keys_and_consts(base, dict(base["sources"], seed_config=cfg))
    report = cov.Report()
    cov.arm_keys(consts, keys, base["index"], report)
    assert report.blocking["seeder keys"] == [
        "seed_config.EVIDENCE_OUTCOME_WEIGHTS: names A99.99, which is not in the vendored registry"]


def test_an_entry_for_a_constant_that_no_longer_exists_fails_naming_it(base):
    src = base["sources"]["seed_void_patterns"]
    line = next(l for l in src.splitlines() if l.startswith("ADDRESS_SEED"))
    keys, consts = _keys_and_consts(base, dict(base["sources"], seed_void_patterns=src.replace(line, "")))
    report = cov.Report()
    cov.arm_keys(consts, keys, base["index"], report)
    assert report.blocking["seeder keys"] == [
        "seed_void_patterns.ADDRESS_SEED: a key-table entry for a constant that no longer exists"]


def test_an_owed_entry_without_its_reason_fails(base):
    cfg = base["sources"]["seed_config"].replace(
        '"seed_dtc.STATE_WEIGHTS": {"owed": "U10", "why": "own-site customers by state"}',
        '"seed_dtc.STATE_WEIGHTS": {"owed": "U10", "why": ""}')
    keys, consts = _keys_and_consts(base, dict(base["sources"], seed_config=cfg))
    report = cov.Report()
    cov.arm_keys(consts, keys, base["index"], report)
    assert report.blocking["seeder keys"] == ["seed_dtc.STATE_WEIGHTS: an owed entry names its unit and why"]


def test_exempt_and_owed_entries_print_every_run_with_reasons_and_units(base):
    keys, consts = _keys_and_consts(base)
    report = cov.Report()
    cov.arm_keys(consts, keys, base["index"], report)
    shown = report.printed["seeder keys"]
    assert "exempt seed_retailer.COPY_CHUNK_SIZE: a COPY chunk size" in shown
    assert any(l.startswith("owed to U10 (") and "seed_dtc.STATE_WEIGHTS (own-site customers by state)" in l
               for l in shown)


# ── seeder prints ───────────────────────────────────────────────────

def test_a_keyed_value_its_row_does_not_print_fails_naming_the_constant(base):
    cfg = base["sources"]["seed_config"].replace('"strong":   {"won": 0.45,', '"strong":   {"won": 0.46,')
    assert cfg != base["sources"]["seed_config"]
    keys, consts = _keys_and_consts(base, dict(base["sources"], seed_config=cfg))
    report = cov.Report()
    cov.arm_prints(consts, keys, base["index"], base["ca"], report)
    found = report.blocking["seeder prints"]
    assert found and all(f.startswith("seed_config.EVIDENCE_OUTCOME_WEIGHTS: keyed to A4.07") for f in found)


def test_an_owed_entry_whose_row_now_prints_the_value_fails_until_removed(base):
    cfg = base["sources"]["seed_config"].replace(
        '"seed_config.EVIDENCE_OUTCOME_WEIGHTS": {"key": "A4.07"}',
        '"seed_config.EVIDENCE_OUTCOME_WEIGHTS": {"owed": "U13", "row": "A4.07", "why": "x"}')
    keys, consts = _keys_and_consts(base, dict(base["sources"], seed_config=cfg))
    report = cov.Report()
    cov.arm_prints(consts, keys, base["index"], base["ca"], report)
    assert report.blocking["seeder prints"] == [
        "seed_config.EVIDENCE_OUTCOME_WEIGHTS: owed to U13, but A4.07 now prints every value: paid, remove the note"]


def test_an_owed_entry_whose_row_does_not_print_the_value_passes(base):
    keys, consts = _keys_and_consts(base)
    assert keys["seed_config.SEASONALITY"]["row"] == "A7.19"
    report = cov.Report()
    cov.arm_prints(consts, keys, base["index"], base["ca"], report)
    assert report.blocking.get("seeder prints", []) == []


# ── first-order (restated 2026-11-12) ───────────────────────────────

def _first_order(base, index, level="BLOCK"):
    m = copy.deepcopy(base["manifest"])
    for c in m["spec_gate"]["checks"]:
        if c["name"] == base["ca"].FIRST_ORDER_SIGNED_CHECK:
            c["level"] = level
    report = cov.Report()
    cov.arm_first_order(m, index, base["ca"], report)
    return report


def test_the_seventeen_signed_rows_pass(base):
    report = _first_order(base, base["index"])
    assert report.blocking.get("first-order") == []
    assert "17 first-order rows" in report.printed["first-order"]


@pytest.mark.parametrize("break_, expect", [
    (lambda r: r.pop("owner_signed"), "A1.01: first-order and not owner-signed"),
    (lambda r: r.update(signed_figures="9:000000000000"), "A1.01: signed at 9:000000000000, the row is now "),
    (lambda r: r.update(verified_by="someone"), "A1.01: first-order and carries verified_by 'someone'"),
])
def test_a_first_order_row_unsigned_stale_or_externally_verified_blocks_naming_it(base, break_, expect):
    index = copy.deepcopy(base["index"])
    break_(index["A1.01"])
    found = _first_order(base, index).blocking["first-order"]
    assert len(found) == 1 and found[0].startswith(expect)


def test_a_bundle_where_no_row_is_first_order_fails(base):
    index = copy.deepcopy(base["index"])
    for r in index.values():
        r.pop("first_order", None)
    found = _first_order(base, index).blocking["first-order"]
    assert found == ["no row carries first_order: true; a gate keyed to an unset flag passes on nothing"]


def test_below_block_the_arm_prints_and_the_run_proceeds(base):
    index = copy.deepcopy(base["index"])
    index["A1.01"].pop("owner_signed")
    report = _first_order(base, index, level="WARN")
    assert "first-order" not in report.blocking
    assert "A1.01: first-order and not owner-signed" in report.printed["first-order"]


def test_a_tier_a_row_outside_the_set_with_verified_by_null_blocks_nothing(base):
    r = base["index"]["A1.06"]
    assert r["tier"] == "A" and r.get("first_order") is not True and r.get("verified_by") is None
    assert _first_order(base, base["index"]).blocking.get("first-order") == []


# ── effective dating ────────────────────────────────────────────────

def test_a_key_naming_a_row_effective_after_the_span_fails(base):
    index = copy.deepcopy(base["index"])
    index["A4.07"]["effective_from"] = "2027-01-01"
    keys, _ = _keys_and_consts(base)
    report = cov.Report()
    cov.arm_effective(keys, index, date(2026, 1, 2), report)
    assert report.blocking["effective dating"] == [
        "seed_config.EVIDENCE_OUTCOME_WEIGHTS: A4.07's effective_from 2027-01-01 postdates the generated span's "
        "end 2026-01-02"]


def test_a_dated_period_outside_its_rows_span_fails(base):
    keys = {"seed_config.X": {"key": "A4.07", "periods": [("2023-01-01", 1.0), ("2027-06-01", 2.0)]}}
    report = cov.Report()
    cov.arm_effective(keys, base["index"], date(2026, 1, 2), report)
    assert len(report.blocking["effective dating"]) == 1
    assert report.blocking["effective dating"][0].startswith("seed_config.X: period from 2027-06-01")


def test_a_dated_constant_takes_each_periods_value_and_two_periods_differ():
    import seed_config
    periods = [("2023-01-01", 0.10), ("2024-07-01", 0.12)]
    assert seed_config.value_in_effect(periods, date(2023, 3, 1)) == 0.10
    assert seed_config.value_in_effect(periods, date(2025, 3, 1)) == 0.12


def test_a_pre_window_date_is_refused_until_its_owner_ruling():
    import seed_config
    with pytest.raises(NotImplementedError, match="owner ruling"):
        seed_config.value_in_effect([("2023-01-01", 0.10)], date(2022, 12, 1))


# ── the reverse direction ───────────────────────────────────────────

def test_the_reverse_list_prints_and_never_blocks(base):
    keys, _ = _keys_and_consts(base)
    enums = yaml.safe_load((VENDOR / "anchor_enums.yml").read_text("utf-8"))
    report = cov.Report()
    cov.reverse(keys, base["index"], enums, report)
    assert report.blocking == {}
    line = report.printed["reverse"][0]
    assert "numeric rows named by no seeder key" in line and "A4.07" not in line.split(": ", 1)[1].split()


# ── not-for-citation ────────────────────────────────────────────────

def _row(rid, status="pinned", tier="D", cls="owner-judgment", deps=()):
    return {"anchor_id": rid, "status": status, "tier": tier, "evidence_class": cls, "depends_on": list(deps)}


@pytest.mark.parametrize("soft", [_row("S", status="decided", cls="practitioner-estimate"),
                                  _row("S", status="decided", cls="owner-judgment"),
                                  _row("S", status="derived", tier="B", cls="derived-from-adjacent")])
def test_a_figure_deriving_from_an_unpinned_soft_row_is_marked_naming_that_row(soft):
    index = {"F": _row("F", deps=["M"]), "M": _row("M", deps=["S", "N23"]), "S": soft}
    assert cov.not_for_citation(["F"], index) == (True, ["S"])


def test_a_figure_derived_only_from_pinned_rows_is_clear():
    index = {"F": _row("F", deps=["M"]), "M": _row("M", tier="B", cls="practitioner-estimate")}
    assert cov.not_for_citation(["F"], index) == (False, [])
