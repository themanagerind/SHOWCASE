"""SPEC 4.4 / 4.4a / section 11 'Booking': points-only bookings and discounts on unlisted items."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core import clock
from app.core.errors import DomainError, Forbidden, NotFound
from app.models import Booking, Notification, Product, User
from app.models.enums import BookingStatus, DiscountRequestStatus, WalletEntryType, WalletOwnerType
from app.services import booking_service as bs
from app.services import wallet_service as ws
from tests.factories import make_customer, make_shop


def fund(db, customer, paise):
    w = ws.get_wallet(db, WalletOwnerType.CUSTOMER, customer.id, lock=True)
    ws.post(db, w, WalletEntryType.CODE_REDEEMED, paise, reference_type="test", reference_id=None, note="test",
            user_id=None)
    db.commit()


def bal(db, owner_type, owner_id):
    w = ws.get_wallet(db, owner_type, owner_id)
    db.refresh(w)
    assert ws.ledger_sum(db, w) == w.balance_paise  # ledger always explains the balance
    return w.balance_paise


def cbal(db, c):
    return bal(db, WalletOwnerType.CUSTOMER, c.id)


def rbal(db, r):
    return bal(db, WalletOwnerType.RETAILER, r.id)


def make_product(db, shop, discount=5000, stock=2, price=100000):
    p = Product(retailer_id=shop.id, name="TV", price_paise=price, wallet_discount_paise=discount, stock_qty=stock)
    db.add(p)
    db.flush()
    return p


@pytest.fixture
def setup(db, frozen):
    shop, c = make_shop(db), make_customer(db)
    p = make_product(db, shop)
    fund(db, c, 10000)
    return shop, c, p


def test_reserve_holds_points_and_one_unit_of_stock(db, setup):
    shop, c, p = setup
    b = bs.reserve(db, c, p.id)
    assert b.status == BookingStatus.RESERVED and b.discount_paise == 5000
    assert b.expires_at == clock.now() + timedelta(hours=24)
    assert cbal(db, c) == 5000 and db.get(Product, p.id).stock_qty == 1
    assert rbal(db, shop) == 0  # retailer gets nothing until the customer confirms
    assert db.scalar(select(Notification).where(Notification.template == "booking_reserved")) is not None


def test_exact_points_allowed_one_paisa_short_rejected(db, frozen):
    shop, c1, c2 = make_shop(db), make_customer(db), make_customer(db)
    p = make_product(db, shop, discount=5000)
    fund(db, c1, 5000)
    fund(db, c2, 4999)
    bs.reserve(db, c1, p.id)
    assert cbal(db, c1) == 0
    with pytest.raises(DomainError) as e:
        bs.reserve(db, c2, p.id)
    assert e.value.code == "insufficient_points"
    assert cbal(db, c2) == 4999 and db.get(Product, p.id).stock_qty == 1


def test_no_stock_rejected(db, setup):
    shop, c, p = setup
    p.stock_qty = 0
    db.flush()
    with pytest.raises(DomainError) as e:
        bs.reserve(db, c, p.id)
    assert e.value.code == "out_of_stock" and cbal(db, c) == 10000


def test_multiple_bookings_of_same_product_allowed(db, setup):
    shop, c, p = setup
    bs.reserve(db, c, p.id)
    bs.reserve(db, c, p.id)
    assert cbal(db, c) == 0 and db.get(Product, p.id).stock_qty == 0
    with pytest.raises(DomainError):  # stock now gone
        bs.reserve(db, c, p.id)


def test_shop_without_live_plan_or_inactive_product_cannot_be_booked(db, frozen):
    c = make_customer(db)
    fund(db, c, 10000)
    dead = make_shop(db, plan_code=None)
    with pytest.raises(Forbidden):
        bs.reserve(db, c, make_product(db, dead).id)
    live = make_shop(db)
    p = make_product(db, live)
    p.is_active = False
    db.flush()
    with pytest.raises(NotFound):
        bs.reserve(db, c, p.id)


def test_cannot_book_own_shop(db, frozen):
    shop = make_shop(db)
    from app.models import Customer
    me = Customer(user_id=shop.user_id)
    db.add(me)
    db.flush()
    fund(db, me, 10000)
    with pytest.raises(DomainError) as e:
        bs.reserve(db, me, make_product(db, shop).id)
    assert e.value.code == "own_shop"


def test_purchase_credits_retailer_once_and_never_deducts_again(db, setup):
    shop, c, p = setup
    b = bs.reserve(db, c, p.id)
    bs.confirm_purchase(db, c, b.id)
    bs.confirm_purchase(db, c, b.id)  # double tap
    assert cbal(db, c) == 5000 and rbal(db, shop) == 5000
    assert db.get(Product, p.id).stock_qty == 1  # sold unit stays out of stock
    assert db.get(Booking, b.id).status == BookingStatus.PURCHASED


def test_only_the_booking_customer_can_confirm(db, setup):
    shop, c, p = setup
    b = bs.reserve(db, c, p.id)
    other = make_customer(db)
    with pytest.raises(NotFound):
        bs.confirm_purchase(db, other, b.id)
    assert rbal(db, shop) == 0


def test_confirm_allowed_just_before_24h_and_forfeits_at_exactly_24h(db, setup, frozen):
    shop, c, p = setup
    b1 = bs.reserve(db, c, p.id)
    b2 = bs.reserve(db, c, p.id)
    frozen.tick(timedelta(hours=24) - timedelta(seconds=1))
    bs.confirm_purchase(db, c, b1.id)
    frozen.tick(timedelta(seconds=1))  # exactly 24h
    with pytest.raises(DomainError) as e:
        bs.confirm_purchase(db, c, b2.id)
    assert e.value.code == "booking_expired"
    b2 = db.get(Booking, b2.id)
    assert b2.status == BookingStatus.FORFEITED
    assert cbal(db, c) == 0 and rbal(db, shop) == 5000  # forfeited points vanish, go to nobody
    assert db.get(Product, p.id).stock_qty == 1  # forfeited unit released


def test_purchase_allowed_after_shop_plan_expired(db, setup):
    shop, c, p = setup
    b = bs.reserve(db, c, p.id)
    from app.models import Subscription
    from app.models.enums import SubscriptionStatus
    for s in db.scalars(select(Subscription).where(Subscription.retailer_id == shop.id)):
        s.status = SubscriptionStatus.EXPIRED
    db.flush()
    bs.confirm_purchase(db, c, b.id)
    assert rbal(db, shop) == 5000


def test_forfeit_job_is_idempotent_and_releases_stock(db, setup, frozen):
    shop, c, p = setup
    b = bs.reserve(db, c, p.id)
    frozen.tick(timedelta(hours=23, minutes=59))
    assert bs.forfeit_expired(db) == 0
    frozen.tick(timedelta(minutes=1))
    assert bs.forfeit_expired(db) == 1
    assert bs.forfeit_expired(db) == 0
    assert db.get(Booking, b.id).status == BookingStatus.FORFEITED
    assert db.get(Product, p.id).stock_qty == 2 and cbal(db, c) == 5000
    entries = [e.entry_type for e in ws.ledger(db, ws.get_wallet(db, WalletOwnerType.CUSTOMER, c.id))]
    assert entries.count(WalletEntryType.BOOKING_FORFEITED) == 1
    with pytest.raises(DomainError):
        bs.confirm_purchase(db, c, b.id)


def test_retailer_cancel_refunds_once_and_releases_stock(db, setup):
    shop, c, p = setup
    b = bs.reserve(db, c, p.id)
    bs.cancel_by_retailer(db, shop, b.id, "out of stock")
    with pytest.raises(DomainError):
        bs.cancel_by_retailer(db, shop, b.id, "again")
    assert cbal(db, c) == 10000 and db.get(Product, p.id).stock_qty == 2
    with pytest.raises(DomainError):  # cancelled booking cannot be "bought" afterwards
        bs.confirm_purchase(db, c, b.id)
    assert rbal(db, shop) == 0


def test_other_retailer_cannot_cancel(db, setup):
    shop, c, p = setup
    b = bs.reserve(db, c, p.id)
    with pytest.raises(NotFound):
        bs.cancel_by_retailer(db, make_shop(db), b.id, "nope")


def test_cannot_cancel_purchased_booking(db, setup):
    shop, c, p = setup
    b = bs.reserve(db, c, p.id)
    bs.confirm_purchase(db, c, b.id)
    with pytest.raises(DomainError):
        bs.cancel_by_retailer(db, shop, b.id, "changed mind")
    assert cbal(db, c) == 5000 and rbal(db, shop) == 5000


# ---- discounts on unlisted items ------------------------------------------------------------------

def phone_of(db, customer):
    return db.get(User, customer.user_id).phone


def owner(db, shop):
    return db.get(User, shop.user_id)


def test_discount_request_needs_customer_confirmation(db, setup):
    shop, c, _ = setup
    req = bs.create_discount_request(db, shop, owner(db, shop), phone_of(db, c), 3000, "Fan purchase")
    assert req.status == DiscountRequestStatus.PENDING and cbal(db, c) == 10000  # nothing moves yet
    assert [r.id for r in bs.pending_discounts_for_customer(db, c)] == [req.id]
    bs.respond_to_discount(db, c, req.id, True)
    assert cbal(db, c) == 7000 and rbal(db, shop) == 3000
    with pytest.raises(DomainError):  # cannot be accepted twice
        bs.respond_to_discount(db, c, req.id, True)
    assert cbal(db, c) == 7000


def test_discount_decline_moves_nothing(db, setup):
    shop, c, _ = setup
    req = bs.create_discount_request(db, shop, owner(db, shop), phone_of(db, c), 3000, "Fan")
    bs.respond_to_discount(db, c, req.id, False)
    assert db.get(type(req), req.id).status == DiscountRequestStatus.DECLINED
    assert cbal(db, c) == 10000 and rbal(db, shop) == 0


def test_discount_insufficient_points_keeps_request_pending(db, setup):
    shop, c, _ = setup
    req = bs.create_discount_request(db, shop, owner(db, shop), phone_of(db, c), 10001, "Big item")
    with pytest.raises(DomainError) as e:
        bs.respond_to_discount(db, c, req.id, True)
    assert e.value.code == "insufficient_points"
    assert db.get(type(req), req.id).status == DiscountRequestStatus.PENDING and cbal(db, c) == 10000


def test_discount_request_expires_after_30_minutes(db, setup, frozen):
    shop, c, _ = setup
    req = bs.create_discount_request(db, shop, owner(db, shop), phone_of(db, c), 3000, "Fan")
    frozen.tick(timedelta(minutes=30))
    with pytest.raises(DomainError) as e:
        bs.respond_to_discount(db, c, req.id, True)
    assert e.value.code == "request_expired" and cbal(db, c) == 10000
    req2 = bs.create_discount_request(db, shop, owner(db, shop), phone_of(db, c), 1000, "Bulb")
    frozen.tick(timedelta(minutes=30))
    assert bs.pending_discounts_for_customer(db, c) == []
    assert bs.expire_discount_requests(db) == 1
    assert db.get(type(req2), req2.id).status == DiscountRequestStatus.EXPIRED


def test_discount_request_rules(db, setup):
    shop, c, _ = setup
    u = owner(db, shop)
    with pytest.raises(NotFound):
        bs.create_discount_request(db, shop, u, "9123456789", 1000, "x item")
    with pytest.raises(DomainError):
        bs.create_discount_request(db, shop, u, phone_of(db, c), 0, "x item")
    req = bs.create_discount_request(db, shop, u, phone_of(db, c), 1000, "x item")
    with pytest.raises(NotFound):  # another customer cannot accept it
        bs.respond_to_discount(db, make_customer(db), req.id, True)
    dead = make_shop(db, plan_code=None)
    with pytest.raises(Forbidden):
        bs.create_discount_request(db, dead, owner(db, dead), phone_of(db, c), 1000, "x item")
