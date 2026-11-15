"""Plan U8's test scenarios: the origin-R7 write targets exist and hold their cascade rows (database tier).

Every table the two scripted disasters write (spec 07) must take the row its
cascade names, or it is a stub. Each test plants rows inside a transaction as
the harness administrator and rolls back. Needs a rebuilt world at run seed 0
(python tests/harness.py rebuild): the staging views and the dims are dbt's.
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg2
import pytest

pytestmark = pytest.mark.db

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "generation"))

U8_TABLES = (
    "marketplace_accounts", "amazon_orders", "amazon_order_lines", "amazon_fees", "amazon_buy_box",
    "amazon_3p_listings", "marketplace_events", "map_policy", "map_price_monitor", "map_violations",
    "small_accounts", "small_account_orders", "small_account_order_lines", "small_account_shipments",
    "small_account_shipment_lines", "small_account_receipt_lines", "small_account_remittances",
    "shopify_subscriptions", "shopify_subscription_cancellations", "invoices", "store_week_oos",
)
PER_ORDER_FEES = ("referral", "fba_fulfillment", "returnless_refund")
MONTHLY_FEES = ("storage", "inbound_placement", "advertising", "selling_plan")
RETAILER_BANNERS = {"national retailer", "regional retailer", "club retailer", "natural retailer"}
# The owner's domain (spec DECISIONS 2026-09-02, platform DECISIONS 2026-11-15).
BANNER_DOMAIN = RETAILER_BANNERS | {"distributor", "marketplace", "independent"}
# Year 3 of the window, where A3.12's MAP binds; year 1 for the pre-policy monitor.
Y1, Y3 = "2023-03-06", "2025-01-06"


@pytest.fixture
def cur(db):
    c = db.cursor()
    yield c
    db.rollback()
    c.close()


def _one(cur, q, args=()):
    cur.execute(q, args)
    return cur.fetchone()[0]


def _rejects(cur, q, args=()):
    """True when the statement is refused by a constraint; the transaction is restored either way."""
    cur.execute("SAVEPOINT s")
    try:
        cur.execute(q, args)
    except (psycopg2.IntegrityError, psycopg2.DataError):
        cur.execute("ROLLBACK TO SAVEPOINT s")
        return True
    cur.execute("RELEASE SAVEPOINT s")
    return False


def _plant(cur):
    """The cascade rows spec 07 names for the six groups, keyed to the rebuilt world. Returns the keys."""
    sku = _one(cur, "SELECT min(sku) FROM raw.product_master")
    store = _one(cur, "SELECT min(store_id) FROM raw.stores")
    dtc_order = _one(cur, "SELECT min(order_id) FROM raw.shopify_orders")
    email = _one(cur, "SELECT email FROM raw.shopify_orders WHERE order_id = %s", (dtc_order,))
    ret_ship = _one(cur, "SELECT min(shipment_id) FROM raw.retailer_shipments")
    q = cur.execute
    q("INSERT INTO raw.marketplace_accounts VALUES ('MKT-AMAZON', 'amazon', 'Amazon Seller Central', 'marketplace'),"
      " ('MKT-FAIRE', 'faire', 'Faire', 'marketplace')")
    q("INSERT INTO raw.amazon_orders VALUES ('AMZ-1', 'MKT-AMAZON', %s, 2, 17.98)", (Y3,))
    q("INSERT INTO raw.amazon_order_lines VALUES ('AMZ-1', %s, 2, 8.99, 17.98)", (sku,))
    for i, t in enumerate(PER_ORDER_FEES):
        q("INSERT INTO raw.amazon_fees VALUES (%s, 'MKT-AMAZON', 'AMZ-1', %s, %s, 1.00)", (f"FEE-O{i}", t, Y3))
    for i, t in enumerate(MONTHLY_FEES):
        q("INSERT INTO raw.amazon_fees VALUES (%s, 'MKT-AMAZON', NULL, %s, '2025-01-31', 10.00)", (f"FEE-M{i}", t))
    q("INSERT INTO raw.amazon_buy_box VALUES (%s, %s, 0)", (sku, Y3))
    q("INSERT INTO raw.amazon_3p_listings VALUES ('LST-1', %s, 'a reseller', %s, NULL, 5.49, 400)", (sku, Y3))
    q("INSERT INTO raw.small_accounts VALUES ('SA-VT', 'a gift shop', 'gift', 'converted_from_dtc', %s, 'inside rep',"
      " 'tier_3', 1, 'parcel billed', 30, %s, %s, 'independent')", (email, Y3, Y3))
    q("INSERT INTO raw.marketplace_events VALUES ('EV-1', 'MKT-FAIRE', %s, 'channel_conflict_complaint', %s,"
      " 'SA-VT', NULL, 'declined', NULL)", (Y3, sku))
    q("INSERT INTO raw.small_account_orders VALUES ('SAO-1', 'SA-VT', 'direct', %s, NULL, 12, 72.00, 18.00, 6.00,"
      " 'shipped', NULL, NULL)", (Y3,))
    q("INSERT INTO raw.small_account_order_lines VALUES ('SAO-1', %s, 12, 12, NULL, 0, FALSE, 6.00, 72.00)", (sku,))
    q("INSERT INTO raw.small_account_shipments VALUES ('SAS-1', 'SAO-1', %s, NULL, 'parcel', 12)", (Y3,))
    q("INSERT INTO raw.small_account_shipment_lines VALUES ('SAS-1', %s, 12, 12, NULL)", (sku,))
    q("INSERT INTO raw.small_account_receipt_lines VALUES ('SAS-1', %s, 12, NULL)", (sku,))
    q("INSERT INTO raw.small_account_remittances VALUES ('SAR-1', 'SA-VT', 'direct', '2025-02-05', 96.00, 0, 96.00)")
    q("INSERT INTO raw.map_policy VALUES (%s, '2025-01-01', 7.99)", (sku,))
    q("INSERT INTO raw.map_price_monitor VALUES ('MON-Y1', %s, %s, '3p_vs_dtc', 5.49, 8.99, 'LST-1', NULL, TRUE)",
      (sku, Y1))
    q("INSERT INTO raw.map_price_monitor VALUES ('MON-Y3', %s, %s, 'dtc_vs_map', 6.29, 7.99, NULL, '2025-01-01', TRUE)",
      (sku, Y3))
    q("INSERT INTO raw.map_violations VALUES ('VIO-1', 'MON-Y3', %s, %s, %s, 6.29, '2025-01-01')", (dtc_order, sku, Y3))
    q("INSERT INTO raw.shopify_subscriptions VALUES ('SUB-1', %s, %s, 30, '2024-01-01', 'cancelled')", (email, sku))
    q("INSERT INTO raw.shopify_subscription_cancellations VALUES ('CAN-1', 'SUB-1', '2024-03-04',"
      " 'found it cheaper')")
    q("UPDATE raw.shopify_orders SET subscription_id = 'SUB-1' WHERE order_id = %s", (dtc_order,))
    q("INSERT INTO raw.invoices VALUES ('INV-R', %s, NULL, NULL, %s, 'net 30', '2025-02-05', 100.00),"
      " ('INV-S', NULL, NULL, 'SAS-1', %s, 'net 30', '2025-02-05', 96.00)", (ret_ship, Y3, Y3))
    q("INSERT INTO raw.store_week_oos VALUES (%s, %s, %s, TRUE)", (sku, store, Y3))
    return {"sku": sku, "dtc_order": dtc_order}


# -- happy path ----------------------------------------------------------------

def test_every_write_target_holds_its_cascade_row(cur):
    _plant(cur)
    counts = {t: _one(cur, f"SELECT count(*) FROM raw.{t}") for t in U8_TABLES}
    assert {t: n for t, n in counts.items() if n == 0} == {}
    assert _one(cur, "SELECT count(DISTINCT fee_type) FROM raw.amazon_fees") == 7
    assert _one(cur, "SELECT count(*) FROM raw.shopify_orders WHERE subscription_id IS NOT NULL") == 1


def test_a_per_order_fee_needs_its_order_and_a_monthly_fee_has_none(cur):
    _plant(cur)
    assert _rejects(cur, "INSERT INTO raw.amazon_fees VALUES ('X1', 'MKT-AMAZON', NULL, 'referral', %s, 1)", (Y3,))
    assert _rejects(cur, "INSERT INTO raw.amazon_fees VALUES ('X2', 'MKT-AMAZON', 'AMZ-1', 'storage', %s, 1)", (Y3,))


def test_a_converted_account_carries_its_dtc_customer_and_rep(cur):
    _plant(cur)
    assert _rejects(cur, "INSERT INTO raw.small_accounts (small_account_id, name, account_type, origin, price_tier,"
                         " banner_type) VALUES ('X', 'x', 'gift', 'converted_from_dtc', 'tier_3', 'independent')")
    assert _rejects(cur, "INSERT INTO raw.small_accounts (small_account_id, name, account_type, origin, dtc_customer_id,"
                         " price_tier, banner_type) VALUES ('X', 'x', 'gift', 'inbound', 'c', 'tier_3', 'independent')")


def test_an_invoice_keys_exactly_one_channels_shipment(cur):
    _plant(cur)
    ret_ship = _one(cur, "SELECT min(shipment_id) FROM raw.retailer_shipments")
    assert _rejects(cur, "INSERT INTO raw.invoices VALUES ('X', %s, NULL, 'SAS-1', %s, 'net 30', %s, 1)",
                    (ret_ship, Y3, Y3))
    assert _rejects(cur, "INSERT INTO raw.invoices VALUES ('X', NULL, NULL, NULL, %s, 'net 30', %s, 1)", (Y3, Y3))


# -- N35: no violation before the policy; the monitor from year 1 ----------------

def test_a_map_violation_before_the_policy_is_rejected(cur):
    keys = _plant(cur)
    args = (keys["dtc_order"], keys["sku"])
    # dated before its MAP's effective date
    assert _rejects(cur, "INSERT INTO raw.map_violations VALUES ('X1', 'MON-Y3', %s, %s, '2024-06-03', 6.29,"
                         " '2025-01-01')", args)
    # against a MAP that does not exist (year 2: no policy)
    assert _rejects(cur, "INSERT INTO raw.map_violations VALUES ('X2', 'MON-Y3', %s, %s, '2024-06-03', 6.29,"
                         " '2024-01-01')", args)


def test_the_monitor_reads_from_year_one_and_checks_map_only_under_a_policy(cur):
    keys = _plant(cur)
    assert _one(cur, "SELECT count(*) FROM raw.map_price_monitor WHERE reading_date < '2024-01-01'") == 1
    assert _rejects(cur, "INSERT INTO raw.map_price_monitor VALUES ('X', %s, '2024-06-03', 'dtc_vs_map', 6.29, 7.99,"
                         " NULL, NULL, TRUE)", (keys["sku"],))
    assert _rejects(cur, "INSERT INTO raw.map_price_monitor VALUES ('X', %s, '2024-06-03', 'dtc_vs_map', 6.29, 7.99,"
                         " NULL, '2025-01-01', TRUE)", (keys["sku"],))


# -- N22: a 3P brand has no vendor chargebacks and no shortage claims -----------

def test_no_amazon_table_holds_a_vendor_chargeback_or_a_shortage_claim(cur):
    cur.execute("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'raw' AND c.relkind = 'r' AND c.relname ~ '(amazon|marketplace)'")
    tables = [r[0] for r in cur.fetchall()]
    assert tables and not [t for t in tables if "chargeback" in t or "shortage" in t], tables
    cur.execute("SELECT count(*) FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'raw' AND c.relname = ANY(%s) "
                "AND a.attnum > 0 AND (a.attname ~ 'chargeback|shortage')", (tables,))
    assert cur.fetchone()[0] == 0
    _plant(cur)
    for t in ("chargeback", "shortage_claim", "vendor_chargeback"):
        assert _rejects(cur, "INSERT INTO raw.amazon_fees VALUES ('X', 'MKT-AMAZON', NULL, %s, %s, 1)", (t, Y3))
        assert _rejects(cur, "INSERT INTO raw.marketplace_events VALUES ('X', 'MKT-AMAZON', %s, %s, NULL, NULL,"
                             " NULL, NULL, NULL)", (Y3, t))


def test_amazon_fees_reach_staging_and_every_per_order_fee_joins_an_order(cur):
    _plant(cur)
    assert _one(cur, "SELECT count(*) FROM public_staging.stg_amazon_fees") == 7
    assert _one(cur, "SELECT count(*) FROM public_staging.stg_amazon_fees f WHERE f.order_id IS NOT NULL "
                     "AND NOT EXISTS (SELECT 1 FROM public_staging.stg_amazon_orders o "
                     "WHERE o.order_id = f.order_id)") == 0
    assert _one(cur, "SELECT count(*) FROM public_staging.stg_amazon_fees WHERE order_id IS NOT NULL") == 3
    assert _one(cur, "SELECT count(*) FROM public_staging.stg_amazon_orders") == 1


# -- N37: a channel, not a retailer ---------------------------------------------

def test_the_small_account_tier_has_no_retailer_row(cur):
    from seed_config import RETAILERS
    assert _one(cur, "SELECT count(*) FROM raw.retailers") == len(RETAILERS)
    assert {r["banner_type"] for r in RETAILERS} <= RETAILER_BANNERS
    assert _rejects(cur, "INSERT INTO raw.retailers (retailer_id, name, banner_type) "
                         "VALUES ('RET-SMALL', 'small', 'independent')")


def test_n37_order_to_cash_rows_key_to_an_n37_account(cur):
    _plant(cur)
    for t in ("small_account_orders", "small_account_remittances"):
        assert _one(cur, f"SELECT count(*) FROM raw.{t} WHERE small_account_id = 'SA-VT'") == 1, t
    assert _rejects(cur, "INSERT INTO raw.small_account_orders VALUES ('X', 'RET-WALMART', 'direct', %s, NULL, 1, 1,"
                         " 0, 0, 'open', NULL, NULL)", (Y3,))
    assert _one(cur, "SELECT count(*) FROM public_staging.stg_small_account_orders WHERE small_account_id = 'SA-VT' "
                     "AND ordering_channel = 'direct'") == 1


# -- banner_type on every account ----------------------------------------------

def test_banner_type_covers_every_account_and_takes_only_the_ruled_domain(cur):
    _plant(cur)
    for table in ("retailers", "distributors", "marketplace_accounts", "small_accounts"):
        assert _one(cur, f"SELECT count(*) FROM raw.{table} WHERE banner_type IS NULL") == 0, table
        cur.execute(f"SELECT DISTINCT banner_type FROM raw.{table}")
        assert {r[0] for r in cur.fetchall()} <= BANNER_DOMAIN, table
    assert _rejects(cur, "UPDATE raw.retailers SET banner_type = 'grocer'")
    assert _rejects(cur, "UPDATE raw.distributors SET banner_type = 'national retailer'")
    assert _rejects(cur, "UPDATE raw.small_accounts SET banner_type = 'marketplace'")


def test_banner_type_reaches_the_dims_and_the_models_consumers_render_from(cur):
    for rel in ("public_marts.dim_retailers", "public_marts.dim_distributors",
                "public_intermediate.int_all_partners", "public_marts.fct_chargebacks"):
        assert _one(cur, f"SELECT count(*) FROM {rel}") > 0, rel
        assert _one(cur, f"SELECT count(*) FROM {rel} WHERE banner_type IS NULL") == 0, rel
    cur.execute("SELECT DISTINCT banner_type FROM public_marts.dim_retailers")
    assert {r[0] for r in cur.fetchall()} == {"national retailer", "regional retailer", "club retailer",
                                              "natural retailer"}


# -- N8 ------------------------------------------------------------------------

def test_chargebacks_carry_nullable_order_and_shipment_keys_into_staging(cur):
    for side in ("retailer", "distributor"):
        assert _one(cur, f"SELECT count(*) FROM raw.{side}_chargebacks") > 0
        assert _one(cur, f"SELECT count(*) FROM raw.{side}_chargebacks "
                         "WHERE order_id IS NOT NULL OR shipment_id IS NOT NULL") == 0
        assert _one(cur, f"SELECT count(*) FROM public_staging.stg_{side}_chargebacks "
                         "WHERE order_id IS NULL AND shipment_id IS NULL") > 0
    assert _rejects(cur, "UPDATE raw.retailer_chargebacks SET order_id = 'NO-SUCH-ORDER' "
                         "WHERE chargeback_id = (SELECT min(chargeback_id) FROM raw.retailer_chargebacks)")


# -- empty at this stage -------------------------------------------------------

def test_the_write_targets_exist_and_are_empty_until_their_writers_run(cur):
    assert {t: _one(cur, f"SELECT count(*) FROM raw.{t}") for t in U8_TABLES} == {t: 0 for t in U8_TABLES}
    assert _one(cur, "SELECT count(*) FROM raw.shopify_orders WHERE subscription_id IS NOT NULL") == 0
