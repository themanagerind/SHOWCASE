"""SPEC 4.5 / section 11 'Reward offer'."""
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core import clock
from app.core.errors import Conflict, DomainError, Forbidden
from app.models import RewardPayout, User
from app.models.enums import WalletEntryType, WalletOwnerType
from app.services import reward_service as rs
from app.services import wallet_service as ws
from tests.factories import make_shop, make_user

H = timedelta(hours=1)
D = timedelta(days=1)


def earn(db, shop, paise, kind=WalletEntryType.BOOKING_PURCHASED):
    w = ws.get_wallet(db, WalletOwnerType.RETAILER, shop.id, lock=True)
    ws.post(db, w, kind, paise, reference_type="test", reference_id=None, note="t", user_id=None)
    db.commit()


def balance(db, shop):
    w = ws.get_wallet(db, WalletOwnerType.RETAILER, shop.id)
    db.refresh(w)
    assert ws.ledger_sum(db, w) == w.balance_paise
    return w.balance_paise


@pytest.fixture
def admin(db):
    return make_user(db)


def offer(db, admin, start_in=H, days=7, threshold=20000, bp=2000, name="Diwali offer"):
    s = clock.now() + start_in
    return rs.create_offer(db, admin, name, s, s + days * D, threshold, bp)


def test_qualifiers_payout_and_reset(db, frozen, admin):
    o = offer(db, admin)
    exact, short, outsider = make_shop(db), make_shop(db), make_shop(db)
    for s in (exact, short):
        rs.join(db, s, o.id)
    earn(db, exact, 5000)  # before the start: counts for the balance, not for "collected"
    frozen.tick(2 * H)
    earn(db, exact, 15000)
    earn(db, exact, 5000, WalletEntryType.SHOP_DISCOUNT_RECEIVED)  # 20000 collected = exact threshold
    earn(db, short, 19999)
    earn(db, outsider, 50000)  # never joined
    frozen.tick(7 * D)
    rows = {r.retailer_id: r for r in rs.standings(db, o)}
    assert rows[exact.id].qualifies and rows[exact.id].collected_paise == 20000
    assert rows[exact.id].balance_at_end_paise == 25000 and rows[exact.id].payout_paise == 5000  # 20% of 25000
    assert not rows[short.id].qualifies and rows[short.id].payout_paise is None
    assert outsider.id not in rows
    with pytest.raises(DomainError) as e:
        rs.record_payout(db, admin, o.id, short.id, date(2026, 10, 25), "UPI 1")
    assert e.value.code == "not_qualified"
    with pytest.raises(DomainError) as e:
        rs.record_payout(db, admin, o.id, outsider.id, date(2026, 10, 25), "UPI 1")
    assert e.value.code == "not_participant"
    p = rs.record_payout(db, admin, o.id, exact.id, date(2026, 10, 25), "UPI 123")
    assert (p.payout_paise, p.balance_at_end_paise) == (5000, 25000)
    assert balance(db, exact) == 0
    assert balance(db, short) == 19999 and balance(db, outsider) == 50000  # everyone else keeps theirs
    with pytest.raises(Conflict):
        rs.record_payout(db, admin, o.id, exact.id, date(2026, 10, 25), "again")
    assert balance(db, exact) == 0


def test_points_after_the_end_are_kept(db, frozen, admin):
    o = offer(db, admin, start_in=-H, days=1, threshold=1000, bp=1000)
    s = make_shop(db)
    rs.join(db, s, o.id)
    earn(db, s, 3000)
    frozen.tick(D)  # offer ends now
    earn(db, s, 700)  # earned while the admin hasn't paid yet
    assert rs.collected(db, o, s.id) == 3000
    p = rs.record_payout(db, admin, o.id, s.id, date(2026, 10, 20), "cash")
    assert (p.balance_at_end_paise, p.payout_paise) == (3000, 300)
    assert balance(db, s) == 700


def test_payout_rounds_down_to_the_paisa(db, frozen, admin):
    o = offer(db, admin, start_in=-H, days=1, threshold=1, bp=3333)  # 33.33%
    s = make_shop(db)
    rs.join(db, s, o.id)
    earn(db, s, 1001)
    frozen.tick(D)
    assert rs.record_payout(db, admin, o.id, s.id, date(2026, 10, 20), "x").payout_paise == 333  # 333.63 -> 333


def test_no_payout_before_end_or_for_cancelled_offer(db, frozen, admin):
    o = offer(db, admin, start_in=-H, days=1, threshold=100)
    s = make_shop(db)
    rs.join(db, s, o.id)
    earn(db, s, 500)
    with pytest.raises(DomainError) as e:
        rs.record_payout(db, admin, o.id, s.id, date(2026, 10, 17), "x")
    assert e.value.code == "offer_not_ended"
    rs.cancel_offer(db, admin, o.id)
    frozen.tick(D)
    with pytest.raises(DomainError) as e:
        rs.record_payout(db, admin, o.id, s.id, date(2026, 10, 19), "x")
    assert e.value.code == "offer_cancelled" and balance(db, s) == 500


def test_offer_with_payouts_cannot_be_cancelled(db, frozen, admin):
    o = offer(db, admin, start_in=-H, days=1, threshold=100)
    s = make_shop(db)
    rs.join(db, s, o.id)
    earn(db, s, 500)
    frozen.tick(D)
    rs.record_payout(db, admin, o.id, s.id, date(2026, 10, 19), "x")
    with pytest.raises(Conflict):
        rs.cancel_offer(db, admin, o.id)


def test_overlapping_offers_rejected_adjacent_allowed(db, frozen, admin):
    a = offer(db, admin, start_in=H, days=7)
    with pytest.raises(Conflict):
        rs.create_offer(db, admin, "Overlap", a.ends_at - H, a.ends_at + D, 100, 100)
    b = rs.create_offer(db, admin, "Next week", a.ends_at, a.ends_at + 7 * D, 100, 100)  # starts exactly at a's end
    rs.cancel_offer(db, admin, b.id)
    rs.create_offer(db, admin, "Replaces b", a.ends_at, a.ends_at + D, 100, 100)  # cancelled ones don't block


def test_db_blocks_overlap_even_without_the_service(db, frozen, admin):
    a = offer(db, admin)
    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.execute(text("INSERT INTO retailer_reward_offers (name, starts_at, ends_at, threshold_paise, percent_bp, "
                            "created_by_user_id) VALUES ('x', :s, :e, 1, 1, :u)"),
                       {"s": a.starts_at + H, "e": a.ends_at + H, "u": admin.id})


def test_join_rules(db, frozen, admin):
    o = offer(db, admin, start_in=-H, days=1)
    with pytest.raises(Forbidden):
        rs.join(db, make_shop(db, plan_code=None), o.id)
    s = make_shop(db)
    rs.join(db, s, o.id)
    rs.join(db, s, o.id)  # idempotent
    rs.leave(db, s, o.id)
    assert not rs.is_participant(db, o, s)
    frozen.tick(D)
    with pytest.raises(DomainError):
        rs.join(db, s, o.id)


def test_joining_late_still_counts_the_whole_period(db, frozen, admin):
    o = offer(db, admin, start_in=-H, days=2, threshold=1000)
    s = make_shop(db)
    earn(db, s, 1000)  # before joining, but inside the period
    frozen.tick(D)
    rs.join(db, s, o.id)
    frozen.tick(D)
    assert rs.standings(db, o)[0].qualifies


def test_expired_plan_still_paid(db, frozen, admin):
    o = offer(db, admin, start_in=-H, days=1, threshold=100)
    s = make_shop(db)
    rs.join(db, s, o.id)
    earn(db, s, 500)
    db.execute(text("UPDATE subscriptions SET status = 'EXPIRED' WHERE retailer_id = :r"), {"r": s.id})
    frozen.tick(D)
    assert rs.record_payout(db, admin, o.id, s.id, date(2026, 10, 19), "x").payout_paise == 100


def test_earlier_offer_must_be_paid_first_and_no_double_cash(db, frozen, admin):
    a = offer(db, admin, start_in=-H, days=1, threshold=1000, bp=1000, name="A")
    s = make_shop(db)
    rs.join(db, s, a.id)
    earn(db, s, 4000)
    frozen.tick(D)
    b = rs.create_offer(db, admin, "B", a.ends_at, a.ends_at + D, 1000, 1000)
    rs.join(db, s, b.id)
    earn(db, s, 2000)
    frozen.tick(D)
    with pytest.raises(Conflict) as e:
        rs.record_payout(db, admin, b.id, s.id, date(2026, 10, 20), "b")
    assert e.value.code == "earlier_offer_unpaid"
    assert rs.record_payout(db, admin, a.id, s.id, date(2026, 10, 20), "a").balance_at_end_paise == 4000
    pb = rs.record_payout(db, admin, b.id, s.id, date(2026, 10, 20), "b")
    assert pb.balance_at_end_paise == 2000 and pb.payout_paise == 200  # A's 4000 points are not paid again
    assert balance(db, s) == 0


def test_payout_records_are_append_only(db, frozen, admin):
    o = offer(db, admin, start_in=-H, days=1, threshold=100)
    s = make_shop(db)
    rs.join(db, s, o.id)
    earn(db, s, 500)
    frozen.tick(D)
    p = rs.record_payout(db, admin, o.id, s.id, date(2026, 10, 19), "x")
    with pytest.raises(DBAPIError):
        with db.begin_nested():
            db.execute(text("UPDATE reward_payouts SET payout_paise = 1 WHERE id = :i"), {"i": p.id})
    assert db.get(RewardPayout, p.id).payout_paise == 100
    assert isinstance(db.get(User, admin.id), User)
