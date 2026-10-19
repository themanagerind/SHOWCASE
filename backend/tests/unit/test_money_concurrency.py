"""Security audit: races on money paths, run with real parallel DB sessions (not the savepoint fixture)."""
import threading
import time
from datetime import date, timedelta
from unittest import mock

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core import clock
from app.models import Plan, Retailer, RewardOffer, RewardParticipant, RewardPayout, Subscription, SubscriptionPayment, User
from app.models.enums import BillingPeriod, SubscriptionPaymentStatus, WalletEntryType, WalletOwnerType
from app.services import reward_service as rs
from app.services import subscription_service as subs
from app.services import wallet_service as ws
from tests.factories import make_shop, make_super_admin


def test_two_payments_settling_at_once_get_consecutive_periods(engine):
    with Session(engine) as s:
        shop = make_shop(s, "BASIC")
        sub = s.scalar(select(Subscription).where(Subscription.retailer_id == shop.id))
        plan = s.scalar(select(Plan).where(Plan.code == "BASIC"))
        orders = []
        for i in range(2):
            p = SubscriptionPayment(subscription_id=sub.id, plan_id=plan.id, billing_cycle=BillingPeriod.MONTHLY,
                                    amount_paise=19900, gst_paise=0, price_source="BASE", gateway="razorpay",
                                    status=SubscriptionPaymentStatus.CREATED, gateway_order_id=f"order_race_{shop.id}_{i}")
            s.add(p)
            orders.append(p.gateway_order_id)
        s.commit()
        sub_id, shop_id, user_id = sub.id, shop.id, shop.user_id

    barrier = threading.Barrier(2)

    def worker(order_id):
        with Session(engine) as s:
            barrier.wait()
            subs.handle_gateway_event(s, {"event": "payment.captured", "payload": {"payment": {"entity": {
                "order_id": order_id, "id": "pay_" + order_id[-12:], "amount": 19900}}}})

    real = subs.add_months

    def slow(*a, **k):  # widen the window between reading the latest period end and committing
        time.sleep(0.5)
        return real(*a, **k)

    try:
        with mock.patch.object(subs, "add_months", slow):
            ts = [threading.Thread(target=worker, args=(o,)) for o in orders]
            [t.start() for t in ts]
            [t.join() for t in ts]
        with Session(engine) as s:
            periods = sorted(s.execute(select(SubscriptionPayment.period_start, SubscriptionPayment.period_end)
                                       .where(SubscriptionPayment.subscription_id == sub_id)).all())
        assert len(periods) == 2 and periods[1][0] == periods[0][1]  # second starts where the first ends
    finally:  # committed rows would disturb other tests' counts
        with Session(engine) as s:
            s.execute(delete(SubscriptionPayment).where(SubscriptionPayment.subscription_id == sub_id))
            s.execute(delete(Subscription).where(Subscription.id == sub_id))
            s.execute(delete(Retailer).where(Retailer.id == shop_id))
            s.execute(delete(User).where(User.id == user_id))
            s.commit()


def test_cancel_and_payout_at_the_same_time_cannot_both_happen(engine):
    now = clock.now()
    with Session(engine) as s:
        admin = make_super_admin(s)
        user = s.get(User, admin.user_id)
        shop = make_shop(s, "BASIC")
        # Far in the past so it never overlaps offers made by other tests.
        offer = RewardOffer(name="race", starts_at=now - timedelta(days=400), ends_at=now - timedelta(days=390),
                            threshold_paise=1, percent_bp=1000, created_by_user_id=user.id)
        s.add(offer)
        s.flush()
        s.add(RewardParticipant(offer_id=offer.id, retailer_id=shop.id, joined_at=now - timedelta(days=399)))
        w = ws.get_wallet(s, WalletOwnerType.RETAILER, shop.id, lock=True)
        with mock.patch.object(clock, "now", return_value=now - timedelta(days=395)):
            ws.post(s, w, WalletEntryType.BOOKING_PURCHASED, 5000)
        s.commit()
        offer_id, shop_id, user_id = offer.id, shop.id, user.id

    # Tx1 = cancel_offer, paused right after its "no payouts yet" check, holding the offer lock.
    s1 = Session(engine)
    o1 = s1.scalar(select(RewardOffer).where(RewardOffer.id == offer_id).with_for_update())
    assert s1.scalar(select(RewardPayout.id).where(RewardPayout.offer_id == offer_id)) is None
    out = []

    def payer():
        with Session(engine) as s2:
            try:
                rs.record_payout(s2, s2.get(User, user_id), offer_id, shop_id, date.today(), "UTR-race")
                out.append("paid")
            except Exception as e:  # noqa: BLE001 - recorded for the assertion below
                out.append(getattr(e, "code", repr(e)))

    t = threading.Thread(target=payer)
    t.start()
    time.sleep(0.8)
    o1.cancelled_at, o1.cancelled_by_user_id = clock.now(), user_id
    s1.commit()
    s1.close()
    t.join(10)
    with Session(engine) as s:
        paid = s.scalar(select(RewardPayout.id).where(RewardPayout.offer_id == offer_id))
        cancelled = s.get(RewardOffer, offer_id).cancelled_at is not None
    assert cancelled and paid is None and out == ["offer_cancelled"]


def test_cleanup_leaves_no_live_test_offers(engine):
    with Session(engine) as s:
        s.execute(text("UPDATE retailer_reward_offers SET cancelled_at = now() WHERE name = 'race' AND cancelled_at IS NULL"))
        s.commit()


def test_lifecycle_job_does_not_overwrite_a_payment_settling_at_the_same_time(engine):
    from app.models.enums import SubscriptionStatus
    with Session(engine) as s:
        shop = make_shop(s, "BASIC", status="GRACE")
        sub = s.scalar(select(Subscription).where(Subscription.retailer_id == shop.id))
        sub.grace_ends_at = clock.now() - timedelta(hours=1)  # grace is over: the job would expire it
        s.commit()
        shop_id, sub_id, user_id, plan_id = shop.id, sub.id, shop.user_id, sub.plan_id

    payer = Session(engine)  # a payment is settling and holds the subscription lock
    psub = payer.scalar(select(Subscription).where(Subscription.id == sub_id).with_for_update())
    t = threading.Thread(target=lambda: subs.run_lifecycle(Session(engine)))
    t.start()
    t.join(10)  # the job must skip the locked row instead of waiting or writing a stale status
    pay = SubscriptionPayment(subscription_id=sub_id, plan_id=plan_id, billing_cycle=BillingPeriod.MONTHLY,
                              amount_paise=19900, gst_paise=0, price_source="BASE", gateway="manual",
                              reference="UTR-LIFECYCLE", status=SubscriptionPaymentStatus.CREATED)
    payer.add(pay)
    payer.flush()
    subs._activate(payer, psub, pay, clock.now())
    payer.commit()
    payer.close()
    try:
        with Session(engine) as s:
            assert s.get(Subscription, sub_id).status == SubscriptionStatus.ACTIVE  # not EXPIRED by the job
    finally:
        with Session(engine) as s:
            s.execute(text("DELETE FROM notifications WHERE user_id = :u"), {"u": user_id})
            s.execute(delete(SubscriptionPayment).where(SubscriptionPayment.subscription_id == sub_id))
            s.execute(delete(Subscription).where(Subscription.id == sub_id))
            s.execute(delete(Retailer).where(Retailer.id == shop_id))
            s.execute(delete(User).where(User.id == user_id))
            s.commit()
