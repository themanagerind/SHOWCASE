"""SPEC 4.3 + section 11 'Plan limits and weekly swap'."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.errors import DomainError, Forbidden
from app.models import ProductSwap, User
from app.services import product_service as ps
from tests.factories import make_shop, product_data


def owner(db, retailer):
    return db.get(User, retailer.user_id)


def fill(db, retailer, n):
    return [ps.add_product(db, retailer, owner(db, retailer), product_data(i)) for i in range(1, n + 1)]


# ---- plan limits -------------------------------------------------------------------------------

def test_basic_sixth_active_product_rejected(db, frozen):
    shop = make_shop(db, "BASIC")
    fill(db, shop, 5)
    with pytest.raises(Forbidden) as e:
        ps.add_product(db, shop, owner(db, shop), product_data(6))
    assert e.value.code == "product_limit"
    assert ps.active_count(db, shop.id) == 5


def test_pro_twenty_first_active_product_rejected(db, frozen):
    shop = make_shop(db, "PRO")
    fill(db, shop, 20)
    with pytest.raises(Forbidden) as e:
        ps.add_product(db, shop, owner(db, shop), product_data(21))
    assert e.value.code == "product_limit"


def test_premium_is_unlimited(db, frozen):
    shop = make_shop(db, "PREMIUM")
    fill(db, shop, 60)
    assert ps.active_count(db, shop.id) == 60


def test_no_subscription_cannot_add_products(db, frozen):
    shop = make_shop(db, plan_code=None)
    with pytest.raises(Forbidden) as e:
        ps.add_product(db, shop, owner(db, shop), product_data())
    assert e.value.code == "subscription_required"


@pytest.mark.parametrize("status", ["EXPIRED", "CANCELLED"])
def test_expired_or_cancelled_cannot_add_or_swap(db, frozen, status):
    shop = make_shop(db, "BASIC", status=status)
    with pytest.raises(Forbidden):
        ps.add_product(db, shop, owner(db, shop), product_data())
    with pytest.raises(Forbidden):
        ps.swap(db, shop, owner(db, shop), [], [product_data()])


@pytest.mark.parametrize("status", ["TRIAL", "ACTIVE", "GRACE"])
def test_live_statuses_can_add(db, frozen, status):
    shop = make_shop(db, "BASIC", status=status)
    ps.add_product(db, shop, owner(db, shop), product_data())


def test_swap_cannot_exceed_limit(db, frozen):
    shop = make_shop(db, "BASIC")
    products = fill(db, shop, 5)
    with pytest.raises(Forbidden) as e:
        ps.swap(db, shop, owner(db, shop), [products[0].id], [product_data(7), product_data(8)])
    assert e.value.code == "product_limit"
    assert ps.active_count(db, shop.id) == 5
    assert products[0].is_active  # nothing applied


# ---- first-time listing is free ----------------------------------------------------------------

def test_first_time_listing_does_not_lock(db, frozen):
    shop = make_shop(db, "BASIC")
    fill(db, shop, 3)
    frozen.tick(timedelta(days=1))
    fill(db, shop, 2)  # still filling empty slots: no lock, no swap record
    assert shop.products_locked_until is None
    assert not shop.first_swap_done
    assert db.scalars(select(ProductSwap).where(ProductSwap.retailer_id == shop.id)).all() == []


# ---- weekly lock -------------------------------------------------------------------------------

def test_swap_replaces_many_slots_in_one_go_and_locks_7_days(db, frozen):
    shop = make_shop(db, "BASIC")
    products = fill(db, shop, 5)
    record = ps.swap(db, shop, owner(db, shop), [p.id for p in products[:3]], [product_data(i) for i in (6, 7, 8)])
    assert len(record.added_product_ids) == 3 and len(record.removed_product_ids) == 3
    assert shop.products_locked_until == record.locked_until
    assert record.locked_until - frozen.time_to_freeze.replace(tzinfo=record.locked_until.tzinfo) == timedelta(days=7)
    assert ps.active_count(db, shop.id) == 5


def test_add_remove_replace_rejected_during_lock(db, frozen):
    shop = make_shop(db, "BASIC")
    products = fill(db, shop, 4)
    ps.swap(db, shop, owner(db, shop), [products[0].id], [product_data(9)])
    frozen.tick(timedelta(days=6, hours=23, minutes=59, seconds=59))
    u = owner(db, shop)
    for action in (
        lambda: ps.add_product(db, shop, u, product_data(10)),  # empty slot exists, still locked
        lambda: ps.remove_product(db, shop, u, products[1].id),
        lambda: ps.swap(db, shop, u, [products[1].id], [product_data(11)]),
    ):
        with pytest.raises(Forbidden) as e:
            action()
        assert e.value.code == "weekly_lock"


def test_price_stock_photo_description_editable_during_lock(db, frozen):
    shop = make_shop(db, "BASIC")
    products = fill(db, shop, 2)
    ps.swap(db, shop, owner(db, shop), [products[0].id], [product_data(3)])
    p = ps.edit_product(
        db, shop, products[1].id,
        {"price_paise": 12345, "mrp_paise": 20000, "stock_qty": 0, "photos": ["a.jpg"], "description": "new"},
    )
    assert (p.price_paise, p.stock_qty, p.photos, p.description) == (12345, 0, ["a.jpg"], "new")


def test_name_and_category_locked_during_lock_but_free_otherwise(db, frozen):
    shop = make_shop(db, "BASIC")
    products = fill(db, shop, 2)
    ps.edit_product(db, shop, products[1].id, {"name": "Renamed before lock"})
    ps.swap(db, shop, owner(db, shop), [products[0].id], [product_data(3)])
    with pytest.raises(Forbidden):
        ps.edit_product(db, shop, products[1].id, {"name": "Fridge"})
    with pytest.raises(Forbidden):
        ps.edit_product(db, shop, products[1].id, {"category": "appliances"})


def test_swap_allowed_again_exactly_when_lock_ends(db, frozen):
    shop = make_shop(db, "BASIC")
    products = fill(db, shop, 3)
    ps.swap(db, shop, owner(db, shop), [products[0].id], [product_data(4)])
    frozen.tick(timedelta(days=7) - timedelta(microseconds=1))
    with pytest.raises(Forbidden):
        ps.swap(db, shop, owner(db, shop), [products[1].id], [product_data(5)])
    frozen.tick(timedelta(microseconds=1))  # exactly products_locked_until
    ps.swap(db, shop, owner(db, shop), [products[1].id], [product_data(5)])


def test_hiding_a_product_counts_as_swap_and_locks(db, frozen):
    shop = make_shop(db, "BASIC")
    products = fill(db, shop, 3)
    ps.remove_product(db, shop, owner(db, shop), products[0].id)
    assert shop.first_swap_done and shop.products_locked_until is not None
    with pytest.raises(Forbidden):
        ps.add_product(db, shop, owner(db, shop), product_data(9))


def test_single_add_after_first_swap_is_itself_a_swap(db, frozen):
    shop = make_shop(db, "BASIC")
    products = fill(db, shop, 3)
    ps.swap(db, shop, owner(db, shop), [products[0].id], [])
    frozen.tick(timedelta(days=7))
    ps.add_product(db, shop, owner(db, shop), product_data(9))
    assert shop.products_locked_until is not None
    with pytest.raises(Forbidden):
        ps.add_product(db, shop, owner(db, shop), product_data(10))


def test_premium_has_no_lock(db, frozen):
    shop = make_shop(db, "PREMIUM")
    products = fill(db, shop, 3)
    ps.swap(db, shop, owner(db, shop), [products[0].id], [product_data(4)])
    ps.swap(db, shop, owner(db, shop), [products[1].id], [product_data(5)])
    ps.remove_product(db, shop, owner(db, shop), products[2].id)
    ps.add_product(db, shop, owner(db, shop), product_data(6))
    ps.edit_product(db, shop, products[0].id, {"name": "Any time"})
    swaps = db.scalars(select(ProductSwap).where(ProductSwap.retailer_id == shop.id)).all()
    assert len(swaps) == 4 and all(s.locked_until is None for s in swaps)


def test_swap_history_is_recorded(db, frozen):
    shop = make_shop(db, "BASIC")
    products = fill(db, shop, 2)
    ps.swap(db, shop, owner(db, shop), [products[0].id], [product_data(3)])
    swap = db.scalars(select(ProductSwap).where(ProductSwap.retailer_id == shop.id)).one()
    assert swap.removed_product_ids == [products[0].id]
    assert swap.plan_code == "BASIC"
    assert swap.performed_by_user_id == shop.user_id


def test_empty_swap_and_foreign_products_rejected(db, frozen):
    shop = make_shop(db, "BASIC")
    other = make_shop(db, "BASIC")
    theirs = fill(db, other, 1)[0]
    with pytest.raises(DomainError):
        ps.swap(db, shop, owner(db, shop), [], [])
    with pytest.raises(DomainError) as e:
        ps.swap(db, shop, owner(db, shop), [theirs.id], [])
    assert e.value.code == "not_found"
    assert theirs.is_active


# ---- downgrade ---------------------------------------------------------------------------------

def _downgrade(db, shop, to_code):
    from app.models import Plan, Subscription

    sub = db.scalar(select(Subscription).where(Subscription.retailer_id == shop.id))
    sub.plan_id = db.scalar(select(Plan.id).where(Plan.code == to_code))
    db.flush()
    db.expire(sub, ["plan"])


def test_after_downgrade_public_shows_most_recent_n_until_retailer_chooses(db, frozen):
    shop = make_shop(db, "PRO")
    products = []
    for i in range(1, 9):
        products.append(ps.add_product(db, shop, owner(db, shop), product_data(i)))
        frozen.tick(timedelta(minutes=1))
    _downgrade(db, shop, "BASIC")

    public = ps.list_public(db, shop)
    assert [p.id for p in public] == [p.id for p in reversed(products[-5:])]

    keep = [products[0].id, products[1].id, products[2].id]
    ps.keep_products(db, shop, keep)
    assert {p.id for p in ps.list_public(db, shop)} == set(keep)
    assert not shop.first_swap_done and shop.products_locked_until is None  # not a swap


def test_keep_rejects_more_than_limit_or_when_not_over(db, frozen):
    shop = make_shop(db, "PRO")
    products = fill(db, shop, 7)
    with pytest.raises(DomainError):
        ps.keep_products(db, shop, [products[0].id])  # PRO limit not exceeded
    _downgrade(db, shop, "BASIC")
    with pytest.raises(Forbidden):
        ps.keep_products(db, shop, [p.id for p in products[:6]])
