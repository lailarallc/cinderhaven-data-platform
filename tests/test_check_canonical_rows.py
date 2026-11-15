"""Plan U19: check_canonical.py requires every row it parses; a reworded row fails before any connection.

Fast tier: runs parse_canonical() and run_checks() against copies of CINDERHAVEN_CANONICAL.md with one row
reworded. No database: run_checks() returns before it connects.
"""
from __future__ import annotations

import re

import pytest

import check_canonical as cc

TEXT = cc.CANONICAL_PATH.read_text(encoding="utf-8")

#: (a row label as the parser's regex reads it, the key that row yields)
ROWS = [
    (r"\| Chargebacks\s*\|", "chargeback_count_total"),
    (r"\| Scan revenue \(trailing-52w\)", "trailing_52w_revenue"),
    (r"\| All-in trade cost \(annualized\)", "all_in_annual"),
    (r"\| All-in trade rate", "trade_rate"),
    (r"\| Structural trade \(annual\)", "structural_annual"),
    (r"\| Structural trade rate", "structural_rate"),
    (r"\| Operational waste rate", "op_waste_rate"),
    (r"\| OTIF — total annual exposure", "otif_exposure_total"),
    (r"\| OTIF — annual fines \(measured\)", "otif_fines_annual"),
    (r"\| OTIF — annual velocity damage \(modeled\)", "otif_velocity_annual"),
    (r"\| Short-ship — total cost \(3yr\)", "shortship_total_3yr"),
    (r"\| Short-ship — total cost \(annual\)", "shortship_annual"),
    (r"\| Short-ship — compliance fines \(3yr\)", "shortship_dims_sum"),
]


def test_today_every_required_row_parses():
    assert set(cc.REQUIRED) <= set(cc.parse_canonical())


def test_every_parsed_key_is_required():
    assert set(cc.parse_canonical()) == set(cc.REQUIRED)


@pytest.mark.parametrize("label,key", ROWS)
def test_a_reworded_row_fails_before_connecting(tmp_path, monkeypatch, capsys, label, key):
    assert re.search(label, TEXT), label  # three rate rows also appear in the doc's audit table; all are reworded
    p = tmp_path / "CINDERHAVEN_CANONICAL.md"
    p.write_text(re.sub(label, "| Reworded row |", TEXT), encoding="utf-8")
    monkeypatch.setattr(cc, "CANONICAL_PATH", p)
    monkeypatch.setattr(cc, "get_connection", lambda: pytest.fail("connected despite a missing row"))
    assert key not in cc.parse_canonical()
    assert cc.run_checks() == 1
    assert key in capsys.readouterr().out
