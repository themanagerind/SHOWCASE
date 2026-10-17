"""SPEC 4.8 + section 11 'Visibility'."""
import pytest
from sqlalchemy import select

from app.core.errors import DomainError
from app.models import Subscription
from app.models.enums import SubscriptionStatus
from app.services.discovery_service import DiscoveryQuery, find_shops
from tests.factories import make_shop, point_from

# Customer standing at Rajwada, Indore
LAT, LNG = 22.7196, 75.8577
HOME_PIN, OTHER_PIN = "452001", "452010"


def shop_at(db, meters, plan="PREMIUM", bearing=0.0, rating=0, **kw):
    kw.setdefault("pincode", HOME_PIN)
    kw.setdefault("city", "indore")
    return make_shop(db, plan, location=point_from(db, LAT, LNG, meters, bearing), rating_avg=rating, **kw)


def q(**kw):
    base = dict(lat=LAT, lng=LNG, radius_km=5, pincode=HOME_PIN, city="indore")
    base.update(kw)
    return DiscoveryQuery(**base)


def slugs(db, query):
    return [s.retailer.slug for s in find_shops(db, query)]


# ---- plan scope -------------------------------------------------------------------------------

def test_pincode_scope_hidden_from_other_pincode(db):
    shop = shop_at(db, 500, plan="BASIC")
    assert shop.slug in slugs(db, q())
    assert shop.slug not in slugs(db, q(pincode=OTHER_PIN))


def test_city_scope_hidden_outside_city(db):
    shop = shop_at(db, 500, plan="PRO", pincode=OTHER_PIN)
    assert shop.slug in slugs(db, q())  # same city, different pincode is fine
    assert shop.slug not in slugs(db, q(city="dewas"))


def test_india_scope_shown_anywhere_within_radius(db):
    shop = shop_at(db, 3000, plan="PREMIUM", city="mhow", pincode="453441")
    assert shop.slug in slugs(db, q(city="dewas", pincode="455001"))
    assert shop.slug in slugs(db, q(city=None, pincode=None))  # anonymous visitor with GPS only


def test_india_scope_not_shown_outside_radius(db):
    shop = shop_at(db, 7000, plan="PREMIUM")
    assert shop.slug not in slugs(db, q(radius_km=5))
    assert shop.slug in slugs(db, q(radius_km=10))


def test_radius_boundary_is_exact(db):
    inside = shop_at(db, 4990)
    outside = shop_at(db, 5010)
    found = slugs(db, q(radius_km=5))
    assert inside.slug in found and outside.slug not in found


@pytest.mark.parametrize("status", ["EXPIRED", "CANCELLED"])
def test_expired_or_cancelled_shop_absent(db, status):
    shop = shop_at(db, 200, plan="PREMIUM")
    db.scalar(select(Subscription).where(Subscription.retailer_id == shop.id)).status = SubscriptionStatus(status)
    db.flush()
    assert shop.slug not in slugs(db, q())


@pytest.mark.parametrize("status", ["TRIAL", "GRACE"])
def test_trial_and_grace_visible(db, status):
    shop = shop_at(db, 200, plan="PREMIUM", status=status)
    assert shop.slug in slugs(db, q())


def test_shop_without_subscription_absent(db):
    shop = shop_at(db, 200, plan=None)
    assert shop.slug not in slugs(db, q())


def test_category_filter_is_case_insensitive(db):
    tv = shop_at(db, 300, category="Electronics")
    shop_at(db, 300, category="Clothing", bearing=90)
    assert slugs(db, q(category="electronics")) == [tv.slug]


# ---- ranking ----------------------------------------------------------------------------------

def test_ranking_ring_then_rating_then_plan_priority(db):
    # radius 5 km -> 6 rings of ~833 m: ring 0 = 0-833 m, ring 1 = 833-1667 m, ...
    near_low = shop_at(db, 100, rating=3.0, bearing=0)
    near_high = shop_at(db, 700, rating=4.8, bearing=90)                       # ring 0: better rating wins
    tie_basic = shop_at(db, 1000, plan="BASIC", rating=4.0, bearing=180)       # ring 1
    tie_premium = shop_at(db, 1500, plan="PREMIUM", rating=4.0, bearing=270)   # ring 1: plan breaks the tie
    far_best = shop_at(db, 2500, rating=5.0, bearing=45)                       # ring 3: never above a closer ring
    order = slugs(db, q(radius_km=5))
    assert order == [near_high.slug, near_low.slug, tie_premium.slug, tie_basic.slug, far_best.slug]


def test_same_ring_same_rating_same_plan_falls_back_to_distance(db):
    a = shop_at(db, 600, rating=4.0, bearing=0)
    b = shop_at(db, 200, rating=4.0, bearing=90)
    assert slugs(db, q()) == [b.slug, a.slug]


def test_distance_is_returned_in_metres(db):
    shop_at(db, 1234)
    (found,) = find_shops(db, q())
    assert found.distance_m == pytest.approx(1234, abs=1)


# ---- no GPS fallback --------------------------------------------------------------------------

def test_without_gps_uses_profile_pincode_and_city_ordered_by_rating(db):
    basic_home = shop_at(db, 100, plan="BASIC", rating=3.5)
    pro_city = shop_at(db, 40_000, plan="PRO", pincode=OTHER_PIN, rating=4.5)
    premium_city = shop_at(db, 60_000, plan="PREMIUM", pincode=OTHER_PIN, rating=4.0)
    shop_at(db, 900, plan="PREMIUM", city="dewas", pincode="455001", rating=5.0)   # other city
    shop_at(db, 100, plan="BASIC", pincode=OTHER_PIN, rating=5.0)                  # other pincode
    found = find_shops(db, q(lat=None, lng=None))
    assert [s.retailer.slug for s in found] == [pro_city.slug, premium_city.slug, basic_home.slug]
    assert all(s.distance_m is None for s in found)


def test_without_gps_and_profile_location_is_required(db):
    with pytest.raises(DomainError) as e:
        find_shops(db, q(lat=None, lng=None, pincode=None, city=None))
    assert e.value.code == "location_required"


def test_radius_must_be_an_allowed_option(db):
    with pytest.raises(DomainError) as e:
        find_shops(db, q(radius_km=7))
    assert e.value.code == "invalid_radius"


def test_pagination(db):
    for i in range(5):
        shop_at(db, 100 * (i + 1), bearing=i * 60)
    first = slugs(db, q(limit=3))
    second = slugs(db, q(limit=3, offset=3))
    assert len(first) == 3 and len(second) == 2 and not set(first) & set(second)
