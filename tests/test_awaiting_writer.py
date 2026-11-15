"""seed_all.AWAITING_WRITER is an exceptions list, and it only shrinks (owner, 2026-11-15).

It lets a write target that plan U8 gave schema stay empty after a full run
until the unit named beside it writes it. Two tests hold it:
- fast tier: it never gains a table and never changes a table's writer; the
  ceiling below is the list as U8 merged it;
- database tier: once the vendored regen plan marks a listed table's writer
  DONE, that table may not still be empty. The writer takes its tables off the
  list in the change that fills them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "generation"))
import seed_all  # noqa: E402

#: The list as U8 merged it (platform main, 2026-11-15). Only ever remove a line.
CEILING = {
    "raw.shopify_subscriptions": "U10",
    "raw.shopify_subscription_cancellations": "U11",
    "raw.marketplace_accounts": "U13",
    "raw.amazon_orders": "U13",
    "raw.amazon_order_lines": "U13",
    "raw.amazon_fees": "U13",
    "raw.amazon_buy_box": "U11",
    "raw.amazon_3p_listings": "U11",
    "raw.marketplace_events": "U11",
    "raw.map_policy": "U11",
    "raw.map_price_monitor": "U11",
    "raw.map_violations": "U11",
    "raw.small_accounts": "U13",
    "raw.small_account_orders": "U13",
    "raw.small_account_order_lines": "U13",
    "raw.small_account_shipments": "U13",
    "raw.small_account_shipment_lines": "U13",
    "raw.small_account_receipt_lines": "U13",
    "raw.small_account_remittances": "U13",
    "raw.invoices": "U11",
    "raw.store_week_oos": "U11",
}
UNIT_STATUS = json.loads((ROOT / "vendor" / "realism" / "unit_status.json").read_text(encoding="utf-8"))


def test_the_list_never_gains_a_table_or_changes_a_writer():
    added = {t: u for t, u in seed_all.AWAITING_WRITER.items() if t not in CEILING}
    changed = {t: (CEILING[t], u) for t, u in seed_all.AWAITING_WRITER.items() if t in CEILING and CEILING[t] != u}
    assert added == {} and changed == {}, f"AWAITING_WRITER only shrinks: added {added}, writer changed {changed}"


def test_every_writer_is_a_unit_in_the_vendored_plan():
    assert sorted({u for u in seed_all.AWAITING_WRITER.values() if u not in UNIT_STATUS}) == []


@pytest.mark.db
def test_no_listed_table_is_still_empty_once_its_writer_is_done(db):
    still_empty = []
    with db.cursor() as cur:
        for table, unit in sorted(seed_all.AWAITING_WRITER.items()):
            if not UNIT_STATUS[unit]["done"]:
                continue
            schema, name = table.split(".")
            cur.execute(f'SELECT EXISTS (SELECT 1 FROM "{schema}"."{name}")')
            if not cur.fetchone()[0]:
                still_empty.append(f"{table} ({unit} is DONE)")
    db.rollback()
    assert still_empty == [], f"a DONE writer left its table empty: {still_empty}"
