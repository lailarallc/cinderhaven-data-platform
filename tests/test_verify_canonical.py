"""Plan U19: verify_canonical.py fails on every way of not measuring, and compares at the yml's precision.

Fast tier: fixture yml and gather text in tmp_path; no database. The artifact emit is stubbed so no test writes
reference/.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

import verify_canonical as vc

YML = """meta:
  verified_against_production: '2026-07-29'
universe:
  skus_total:
    all_time: 50
trade:
  all_in_rate_pct:
    trailing_52w: 11.00
revenue:
  retail_scan:
    cy2025: 32323139.62
supersedes:
  - {token: 'a retired fixture token', reason: x}
"""
GATHER = """--- DATA WINDOWS ---
universe.skus_total.all_time|50
trade.all_in_rate_pct.trailing_52w|11.003291549683935
revenue.retail_scan.cy2025|32323139.62
window.scan_data|2023-01-07..2025-12-27
"""


def _run(tmp_path, monkeypatch, gather: str | None = GATHER, yml: str = YML, db_url: str | None = None,
         fleet=None) -> int:
    y = tmp_path / "canonical_values.yml"
    y.write_text(yml, encoding="utf-8")
    monkeypatch.setattr(vc, "CANONICAL_YAML", y)
    monkeypatch.setattr(vc, "emit_artifacts", lambda: None)
    if db_url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", db_url)
    g = None
    if gather is not None:
        g = tmp_path / "gather.txt"
        g.write_text(gather, encoding="utf-8")
    return vc.run(g, fleet)


#: A figure only a consumer's export produces, and a calculator's fixed-input case.
YML_PRODUCED = YML.replace("supersedes:", """shortship:
  cost_3yr:
    trailing_36m: 888062.40
calculator:
  net_case:
    fixed: -36320
producers:
  shortship.cost_3yr.trailing_36m: {kind: export, repo: short-ship-cost, file: web/public/data/summary.json, json: totals.3.cost}
  calculator.net_case.fixed: {kind: fixed_input, repo: cost-of-saying-yes, file: model/defaults.py, regex: 'NET = (-?[0-9_,]+)', why: fixed deal inputs}
supersedes:""")


def _fleet(tmp_path, cost="888062.4", net="-36_320"):
    root = tmp_path / "fleet"
    ss = root / "published" / "short-ship-cost"
    (ss / ".git").mkdir(parents=True)
    (ss / "web/public/data").mkdir(parents=True)
    (ss / "web/public/data/summary.json").write_text(
        '{"totals": [{}, {}, {}, {"cost": %s}]}' % cost, encoding="utf-8")
    cy = root / "published" / "cost-of-saying-yes"
    (cy / ".git").mkdir(parents=True)
    (cy / "model").mkdir()
    (cy / "model/defaults.py").write_text(f"NET = {net}\n", encoding="utf-8")
    return root


def test_producer_keys_are_named_not_compared_without_exports(tmp_path, monkeypatch, capsys):
    assert _run(tmp_path, monkeypatch, yml=YML_PRODUCED) == 0
    out = capsys.readouterr().out
    assert "by a named consumer producer: 2; failures: 0" in out
    assert "not compared in this run (pass --exports): calculator.net_case.fixed, shortship.cost_3yr.trailing_36m" in out


def test_producer_keys_pass_against_the_working_copies(tmp_path, monkeypatch, capsys):
    assert _run(tmp_path, monkeypatch, yml=YML_PRODUCED, fleet=_fleet(tmp_path)) == 0


@pytest.mark.parametrize("kw,expect", [
    ({"cost": "888062.41"}, "shortship.cost_3yr.trailing_36m: documented 888062.40, short-ship-cost gives 888062.41"),
    ({"net": "-36_321"}, "calculator.net_case.fixed: documented -36320, cost-of-saying-yes gives -36321"),
    ({"net": "x"}, "regex 'NET = (-?[0-9_,]+)' matches nothing"),
])
def test_a_producer_that_disagrees_fails(tmp_path, monkeypatch, capsys, kw, expect):
    assert _run(tmp_path, monkeypatch, yml=YML_PRODUCED, fleet=_fleet(tmp_path, **kw)) == 1
    assert expect in capsys.readouterr().out


def test_a_missing_working_copy_fails(tmp_path, monkeypatch, capsys):
    assert _run(tmp_path, monkeypatch, yml=YML_PRODUCED, fleet=tmp_path / "empty") == 1
    assert "no working copy of cost-of-saying-yes" in capsys.readouterr().out


@pytest.mark.parametrize("entry,expect", [
    ("{kind: export, repo: r, file: f}", "needs exactly one of json or regex"),
    ("{kind: guess, repo: r, file: f, json: a}", "needs kind"),
    ("{kind: fixed_input, repo: r, file: f, json: a}", "says why its value holds"),
])
def test_a_malformed_producer_fails(tmp_path, monkeypatch, capsys, entry, expect):
    yml = YML_PRODUCED.replace("{kind: export, repo: short-ship-cost, file: web/public/data/summary.json, json: totals.3.cost}",
                               entry)
    assert _run(tmp_path, monkeypatch, yml=yml) == 1
    assert expect in capsys.readouterr().out


def test_a_key_with_two_producers_fails(tmp_path, monkeypatch, capsys):
    gather = GATHER + "shortship.cost_3yr.trailing_36m|888062.40\n"
    assert _run(tmp_path, monkeypatch, gather=gather, yml=YML_PRODUCED) == 1
    assert "named in producers; one producer only" in capsys.readouterr().out


def test_a_producer_for_no_figure_fails(tmp_path, monkeypatch, capsys):
    yml = YML_PRODUCED.replace("producers:\n", "producers:\n  nothing.here.x: {kind: export, repo: r, file: f, json: a}\n")
    assert _run(tmp_path, monkeypatch, yml=yml) == 1
    assert "nothing.here.x: in producers but not a documented figure" in capsys.readouterr().out


def test_the_yml_keeps_its_literal_precision():
    docs = vc.documented(YML)
    assert docs == {"universe.skus_total.all_time": Decimal(50), "trade.all_in_rate_pct.trailing_52w": Decimal("11.00"),
                    "revenue.retail_scan.cy2025": Decimal("32323139.62")}
    assert docs["trade.all_in_rate_pct.trailing_52w"].as_tuple().exponent == -2


def test_a_matching_gather_passes(tmp_path, monkeypatch, capsys):
    assert _run(tmp_path, monkeypatch) == 0
    assert "documented figures: 3; produced by the gather: 3; by a named consumer producer: 0; failures: 0" in \
        capsys.readouterr().out


@pytest.mark.parametrize("gather,expect", [
    (GATHER.replace("|50\n", "|51\n"), "universe.skus_total.all_time: documented 50, live 51"),
    (GATHER.replace("11.003291549683935", "11.005"), "11.01 at the yml's precision"),
    (GATHER.replace("32323139.62", "32323139.63"), "revenue.retail_scan.cy2025: documented 32323139.62"),
    (GATHER.replace("revenue.retail_scan.cy2025|32323139.62\n", ""),
     "revenue.retail_scan.cy2025: documented 32323139.62, no producer"),
    (GATHER + "revenue.dtc_gross.cy2025|ERR: ProgrammingError\n", "not key|number"),
    (GATHER + "this is not a gather line\n", "not key|number"),
])
def test_each_failure_fails(tmp_path, monkeypatch, capsys, gather, expect):
    assert _run(tmp_path, monkeypatch, gather) == 1
    assert expect in capsys.readouterr().out


def test_no_gather_source_fails(tmp_path, monkeypatch, capsys):
    assert _run(tmp_path, monkeypatch, gather=None) == 1
    assert "no gather source" in capsys.readouterr().out


def test_a_connection_prod_guard_refuses_fails(tmp_path, monkeypatch, capsys):
    assert _run(tmp_path, monkeypatch, gather=None, db_url="host=cinderhaven-db.flycast port=5432 dbname=cinderhaven") == 1
    assert "ProdDatabaseError" in capsys.readouterr().out


def test_a_figure_added_to_the_yml_without_a_producer_fails(tmp_path, monkeypatch, capsys):
    yml = YML.replace("revenue:\n", "fulfillment:\n  otif_walmart_pct:\n    cy2025: 84.12\nrevenue:\n")
    assert _run(tmp_path, monkeypatch, yml=yml) == 1
    assert "fulfillment.otif_walmart_pct.cy2025: documented 84.12, no producer" in capsys.readouterr().out


def test_half_up_at_the_yml_precision():
    assert vc.at_precision(Decimal("11.005"), Decimal("11.00")) == Decimal("11.01")
    assert vc.at_precision(Decimal("379558.775"), Decimal("379558.78")) == Decimal("379558.78")
    assert vc.at_precision(Decimal("49.4999"), Decimal(50)) == Decimal(49)


def test_a_window_line_yields_its_row_count():
    live = vc.parse_gather(["window.retailer_deductions|2023-01-23|2026-01-02|14947", "window.tail_orders|2026-01-02||"])
    assert live == {"rows.retailer_deductions.all_time": Decimal(14947)}


def test_extra_gather_keys_are_listed_not_failed(tmp_path, monkeypatch, capsys):
    assert _run(tmp_path, monkeypatch, GATHER + "volume.units_scan.cy2025|1000\n") == 0
    assert "gathered, not documented (not a failure): volume.units_scan.cy2025" in capsys.readouterr().out


@pytest.mark.db
def test_the_gather_produces_every_documented_figure(db):
    import harness

    lines = vc.gather_from_db(harness.dsn(harness.harness_values()))
    live = vc.parse_gather(lines)
    docs = vc.documented(vc.CANONICAL_YAML.read_text(encoding="utf-8"))
    assert set(docs) - set(live) == set()


def test_the_history_block_is_not_a_figure():
    yml = YML.replace("supersedes:", "history:\n  - {figure: universe.skus_total.all_time, was: 49, now: 50}\nsupersedes:")
    assert set(vc.documented(yml)) == set(vc.documented(YML))


def test_the_gather_sql_splits_into_statements():
    stmts = vc.gather_statements("\\pset footer off\n-- a; comment\nSELECT 1;\nSELECT 'a|1'\n;\n")
    assert [s.strip() for s in stmts] == ["SELECT 1", "SELECT 'a|1'"]
