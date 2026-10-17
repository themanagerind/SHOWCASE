"""SPEC 4.8a product search: PREMIUM all India, PRO city + radius, BASIC never."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.errors import DomainError
from app.models import Plan, Product, Subscription
from app.models.enums import SubscriptionStatus
from app.services.discovery_service import ProductSearchQuery, search_products
from tests.factories import make_shop, point_from

LAT, LNG = 22.7196, 75.8577  # Indore


def shop(db, plan, meters=500, city="indore", bearing=0.0, rating=0, **kw):
    return make_shop(db, plan, location=point_from(db, LAT, LNG, meters, bearing), city=city, rating_avg=rating, **kw)


def product(db, retailer, name, **kw):
    p = Product(retailer_id=retailer.id, name=name, price_paise=kw.pop("price", 10000),
                wallet_discount_paise=kw.pop("discount", 500), stock_qty=kw.pop("stock", 3), **kw)
    db.add(p)
    db.flush()
    return p


def q(term, **kw):
    base = dict(q=term, lat=LAT, lng=LNG, radius_km=5, city="indore")
    base.update(kw)
    return ProductSearchQuery(**base)


def names(db, query):
    return [f.product.name for f in search_products(db, query)]


def test_premium_found_all_india_beyond_radius(db):
    far = shop(db, "PREMIUM", meters=800_000, city="delhi")  # ~800 km away, other city
    product(db, far, "Bajaj Mixer Grinder")
    assert names(db, q("mixer")) == ["Bajaj Mixer Grinder"]
    assert names(db, q("mixer", lat=None, lng=None, city=None)) == ["Bajaj Mixer Grinder"]


def test_pro_only_same_city_and_within_radius(db):
    near = shop(db, "PRO", meters=1000)
    product(db, near, "Philips LED Bulb")
    far_same_city = shop(db, "PRO", meters=8000, bearing=90)
    product(db, far_same_city, "Wipro LED Bulb")
    other_city = shop(db, "PRO", meters=1000, city="dewas", bearing=180)
    product(db, other_city, "Syska LED Bulb")
    assert names(db, q("led bulb")) == ["Philips LED Bulb"]
    assert set(names(db, q("led bulb", radius_km=10))) == {"Philips LED Bulb", "Wipro LED Bulb"}
    # without GPS: city only, no radius
    assert set(names(db, q("led bulb", lat=None, lng=None))) == {"Philips LED Bulb", "Wipro LED Bulb"}


def test_basic_never_in_product_search(db):
    basic = shop(db, "BASIC", meters=10, pincode="452001")
    product(db, basic, "Havells Ceiling Fan")
    assert names(db, q("fan")) == []


@pytest.mark.parametrize("status", ["EXPIRED", "CANCELLED"])
def test_non_live_subscription_hidden(db, status):
    s = shop(db, "PREMIUM")
    product(db, s, "Samsung Smart TV")
    db.scalar(select(Subscription).where(Subscription.retailer_id == s.id)).status = SubscriptionStatus(status)
    db.flush()
    assert names(db, q("tv")) == []


def test_hidden_and_deleted_products_absent(db):
    from app.core import clock

    s = shop(db, "PREMIUM")
    product(db, s, "Hidden Cooler", is_active=False)
    product(db, s, "Deleted Cooler", deleted_at=clock.now())
    product(db, s, "Symphony Cooler")
    assert names(db, q("cooler")) == ["Symphony Cooler"]


def test_downgrade_limit_respected(db, frozen):
    from app.core import clock

    s = shop(db, "PRO")
    for i in range(7):
        product(db, s, f"Kurta {i}", activated_at=clock.now() + timedelta(minutes=i))
    sub = db.scalar(select(Subscription).where(Subscription.retailer_id == s.id))
    sub.plan_id = db.scalar(select(Plan.id).where(Plan.code == "BASIC"))
    db.flush()
    assert names(db, q("kurta")) == []  # BASIC now: not in product search at all
    sub.plan_id = db.scalar(select(Plan.id).where(Plan.code == "PRO"))
    plan = db.scalar(select(Plan).where(Plan.code == "PRO"))
    plan.features = {**plan.features, "max_products": 3}
    db.flush()
    assert sorted(names(db, q("kurta"))) == ["Kurta 4", "Kurta 5", "Kurta 6"]


@pytest.mark.parametrize("typed", ["mixar", "MIXER", "grindr", "मिक्सर"])
def test_spelling_tolerant_and_hindi(db, typed):
    s = shop(db, "PREMIUM")
    product(db, s, "Bajaj Mixer Grinder")
    product(db, s, "मिक्सर ग्राइंडर 750W")
    assert names(db, q(typed)), typed


def test_unrelated_query_finds_nothing(db):
    s = shop(db, "PREMIUM")
    product(db, s, "Bajaj Mixer Grinder")
    assert names(db, q("saree")) == []


def test_like_wildcards_are_literal(db):
    s = shop(db, "PREMIUM")
    product(db, s, "Bajaj Mixer Grinder")
    assert names(db, q("%%")) == []


def test_ranking_text_match_then_ring_then_rating_then_plan(db):
    near_low = shop(db, "PREMIUM", meters=100, rating=3.0)
    near_high = shop(db, "PREMIUM", meters=600, rating=4.9, bearing=90)
    mid_pro = shop(db, "PRO", meters=1200, rating=4.0, bearing=180)
    mid_premium = shop(db, "PREMIUM", meters=1300, rating=4.0, bearing=270)
    far_india = shop(db, "PREMIUM", meters=700_000, city="mumbai", rating=5.0)
    product(db, near_low, "Fan Regulator")              # word-prefix, ring 0, rating 3.0
    product(db, near_high, "Usha Fan")                   # word-prefix, ring 0, rating 4.9
    product(db, mid_pro, "Crompton Fan")                 # word-prefix, ring 1, PRO
    product(db, mid_premium, "Orient Fan")               # word-prefix, ring 1, PREMIUM -> before PRO
    product(db, far_india, "Bajaj Fan")                  # word-prefix, far beyond radius -> after nearer ones
    product(db, near_high, "Infant Toy")                 # contains "fan" mid-word -> after all word-prefix hits
    assert names(db, q("fan")) == [
        "Usha Fan", "Fan Regulator", "Orient Fan", "Crompton Fan", "Bajaj Fan", "Infant Toy",
    ]


def test_without_gps_own_city_first(db):
    other = shop(db, "PREMIUM", city="bhopal", rating=5.0)
    mine = shop(db, "PREMIUM", city="indore", rating=1.0, bearing=90)
    product(db, other, "Usha Fan")
    product(db, mine, "Bajaj Fan")
    assert names(db, q("fan", lat=None, lng=None)) == ["Bajaj Fan", "Usha Fan"]


def test_distance_returned_and_stock_flag(db):
    s = shop(db, "PREMIUM", meters=1500)
    product(db, s, "Out Of Stock Fan", stock=0)
    (found,) = search_products(db, q("fan"))
    assert found.distance_m == pytest.approx(1500, abs=1)


def test_query_validation(db):
    with pytest.raises(DomainError):
        search_products(db, q(" a "))
    with pytest.raises(DomainError):
        search_products(db, q("fan", radius_km=3))
