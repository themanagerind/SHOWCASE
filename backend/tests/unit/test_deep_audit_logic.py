"""Deep audit: logic edge cases (downgrade visibility, analytics teaser, retention)."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app.core import clock
from app.core.errors import NotFound
from app.models import Plan, Product, ShopEvent, Subscription
from app.services import analytics_service as an
from app.services import booking_service as bs
from app.services import discovery_service as ds
from app.services import product_service as ps
from tests.factories import make_customer, make_shop
from tests.unit.test_bookings import fund


def _many_products(db, shop, n, name="Lamp"):
    same_time = clock.now()  # one swap: every product shares activated_at
    for i in range(n):
        db.add(Product(retailer_id=shop.id, name=f"{name} {i:02d}", price_paise=1000, wallet_discount_paise=100,
                       stock_qty=5, activated_at=same_time))
    db.flush()


def _downgrade(db, shop, code):
    plan_id = db.scalar(select(Plan.id).where(Plan.code == code))
    db.execute(update(Subscription).where(Subscription.retailer_id == shop.id).values(plan_id=plan_id))
    db.flush()


def test_page_and_search_show_the_same_products_after_a_downgrade(db, frozen):
    shop = make_shop(db, "PREMIUM", city="indore")
    _many_products(db, shop, 22)
    _downgrade(db, shop, "PRO")  # limit 20
    page = {p.id for p in ps.list_public(db, shop)}
    found = {f.product.id for f in ds.search_products(
        db, ds.ProductSearchQuery(q="lamp", lat=None, lng=None, radius_km=5, city="indore", limit=50))}
    assert len(page) == 20 and page == found


def test_product_hidden_by_downgrade_cannot_be_booked(db, frozen):
    shop, c = make_shop(db, "PRO"), make_customer(db)
    _many_products(db, shop, 7)
    _downgrade(db, shop, "BASIC")  # limit 5
    fund(db, c, 10000)
    visible = {p.id for p in ps.list_public(db, shop)}
    hidden = [p.id for p in db.scalars(select(Product).where(Product.retailer_id == shop.id)) if p.id not in visible]
    assert len(hidden) == 2
    with pytest.raises(NotFound):
        bs.reserve(db, c, hidden[0])
    assert bs.reserve(db, c, next(iter(visible))).status.value == "RESERVED"


def test_basic_teaser_counts_people_not_views(db, frozen):
    shop = make_shop(db, "BASIC")
    for day in range(5):  # one visitor, five days in a row
        db.add(ShopEvent(retailer_id=shop.id, event_type="shop_view", anon_id="visitor-one", meta={},
                         created_at=clock.now() - timedelta(days=day)))
    db.add(ShopEvent(retailer_id=shop.id, event_type="shop_view", anon_id="visitor-two", meta={}, created_at=clock.now()))
    db.flush()
    assert an.dashboard(db, shop, 7).views_7d == 2


def test_purge_cutoff_is_exactly_13_calendar_months(db):
    shop = make_shop(db)
    now = datetime(2026, 10, 31, 12, tzinfo=UTC)
    for created in (datetime(2025, 9, 29, 12, tzinfo=UTC), datetime(2025, 10, 1, 12, tzinfo=UTC)):
        db.add(ShopEvent(retailer_id=shop.id, event_type="shop_view", anon_id="xxxxxxxx", meta={}, created_at=created))
    db.flush()
    assert an.purge_old(db, now) == 1  # 29 Sep 2025 is older than 13 months; 1 Oct 2025 is not
    assert db.scalar(select(func.count()).select_from(ShopEvent).where(ShopEvent.retailer_id == shop.id)) == 1
