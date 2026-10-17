"""DB-level guarantees from the initial migration."""
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import (
    Booking, CreditLedger, CustomerCredit, Plan, Product, ProductSwap, SubscriptionAuditLog,
)
from app.models.enums import LedgerEntryType
from tests.factories import make_admin, make_customer, make_retailer


def test_seeded_plans_match_spec(db):
    plans = {p.code: p for p in db.scalars(select(Plan))}
    assert set(plans) == {"BASIC", "PRO", "PREMIUM"}  # no free plan
    assert all(p.base_price_paise > 0 for p in plans.values())
    assert (plans["BASIC"].features["max_products"], plans["BASIC"].features["visibility_scope"]) == (5, "PINCODE")
    assert (plans["PRO"].features["max_products"], plans["PRO"].features["visibility_scope"]) == (20, "CITY")
    assert (plans["PREMIUM"].features["max_products"], plans["PREMIUM"].features["visibility_scope"]) == (None, "INDIA")
    assert plans["PREMIUM"].features["weekly_swap"] is False
    assert [plans[c].base_price_paise for c in ("BASIC", "PRO", "PREMIUM")] == [19900, 39900, 99900]


def _assert_append_only(db, table: str) -> None:
    for stmt in (f"UPDATE {table} SET created_at = now()", f"DELETE FROM {table}"):
        with pytest.raises(DBAPIError, match="append-only"):
            with db.begin_nested():
                db.execute(text(stmt))


def test_audit_log_is_append_only(db):
    admin = make_admin(db)
    db.add(SubscriptionAuditLog(admin_user_id=admin.id, action="price_change", old_value={"a": 1}, new_value={"a": 2}))
    db.flush()
    _assert_append_only(db, "subscription_audit_log")


def test_product_swaps_is_append_only(db):
    retailer = make_retailer(db)
    db.add(ProductSwap(retailer_id=retailer.id, performed_by_user_id=retailer.user_id, plan_code="BASIC"))
    db.flush()
    _assert_append_only(db, "product_swaps")


def test_credit_ledger_is_append_only(db):
    customer = make_customer(db)
    retailer = make_retailer(db)
    product = Product(retailer_id=retailer.id, name="TV", price_paise=1000000)
    db.add(product)
    db.flush()
    booking = Booking(
        booking_no="B1", customer_id=customer.id, retailer_id=retailer.id, product_id=product.id,
        unit_price_paise=1000000, total_paise=1000000, advance_paise=50000, balance_paise=950000,
    )
    db.add(booking)
    db.flush()
    credit = CustomerCredit(customer_id=customer.id, retailer_id=retailer.id, booking_id=booking.id, amount_paise=50000)
    db.add(credit)
    db.flush()
    db.add(CreditLedger(
        credit_id=credit.id, customer_id=customer.id, retailer_id=retailer.id,
        entry_type=LedgerEntryType.ISSUE, amount_paise=50000, balance_after_paise=50000,
    ))
    db.flush()
    _assert_append_only(db, "credit_ledger")


def test_postgis_location_index_exists(db):
    method = db.execute(
        text(
            "SELECT am.amname FROM pg_class c JOIN pg_am am ON am.oid = c.relam "
            "WHERE c.relname = 'ix_retailers_location_gist'"
        )
    ).scalar_one()
    assert method == "gist"
