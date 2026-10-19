"""SPEC 5 + section 11 'Subscription and plans'."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.dates import add_months
from app.core.errors import DomainError
from app.models import Notification, Plan, Subscription, SubscriptionAuditLog, SubscriptionPayment
from app.models.enums import BillingPeriod, OfferType, SubscriptionStatus
from app.services import subscription_service as subs
from tests.conftest import set_setting
from tests.factories import make_retailer, make_super_admin

M, Y = BillingPeriod.MONTHLY, BillingPeriod.YEARLY
T0 = datetime(2026, 10, 17, 10, 0, tzinfo=UTC)


def plan(db, code):
    return db.scalar(select(Plan).where(Plan.code == code))


def trial_on(db, days=30, code="PRO"):
    set_setting(db, "trial", {"enabled": True, "duration_value": days, "duration_unit": "days", "plan_code": code})


def audits(db, action):
    return db.scalars(select(SubscriptionAuditLog).where(SubscriptionAuditLog.action == action)).all()


# ---- price resolution -------------------------------------------------------------------------

def test_base_prices_monthly_and_yearly(db):
    r = make_retailer(db)
    assert subs.quote(db, r, plan(db, "BASIC"), M).amount_paise == 19900
    assert subs.quote(db, r, plan(db, "BASIC"), Y).amount_paise == 159900
    assert subs.quote(db, r, plan(db, "PREMIUM"), Y).source == "BASE"


def test_gst_is_included_in_price(db):
    q = subs.quote(db, make_retailer(db), plan(db, "BASIC"), M)
    assert q.gst_paise == 19900 - round(19900 / 1.18)  # 3036 of ₹199 is GST
    set_setting(db, "gst", {"rate_bps": 1800, "inclusive": False})
    assert subs.quote(db, make_retailer(db), plan(db, "BASIC"), M).gst_paise == 3582


@pytest.mark.parametrize("otype,value,expected", [
    (OfferType.PERCENT, 25, 29925),       # 39900 - 25% = 299.25
    (OfferType.FIXED_DISCOUNT, 10000, 29900),
    (OfferType.CUSTOM_PRICE, 9900, 9900),
    (OfferType.FIXED_DISCOUNT, 99999, 0),  # never negative
])
def test_offer_types(db, frozen, otype, value, expected):
    admin, r = make_super_admin(db), make_retailer(db)
    subs.create_offer(db, admin, r, offer_type=otype, value=value, valid_from=clock.now() - timedelta(days=1),
                      valid_until=clock.now() + timedelta(days=30), reason="festival")
    q = subs.quote(db, r, plan(db, "PRO"), M)
    assert (q.amount_paise, q.source) == (expected, "OFFER")


def test_price_order_override_then_offer_then_base(db, frozen):
    admin, r = make_super_admin(db), make_retailer(db)
    pro = plan(db, "PRO")
    db.add(Subscription(retailer_id=r.id, plan_id=pro.id, billing_cycle=M, status=SubscriptionStatus.ACTIVE))
    db.flush()
    assert subs.quote(db, r, pro, M).source == "BASE"
    subs.create_offer(db, admin, r, offer_type=OfferType.PERCENT, value=50, valid_from=clock.now(),
                      valid_until=clock.now() + timedelta(days=10), reason="launch")
    assert subs.quote(db, r, pro, M).source == "OFFER"
    subs.set_price_override(db, admin, r, 12300, "special deal")
    q = subs.quote(db, r, pro, M)
    assert (q.amount_paise, q.source) == (12300, "OVERRIDE")
    # override is for the subscription's own plan + cycle only
    assert subs.quote(db, r, pro, Y).source == "OFFER"


def test_offer_validity_window_revoke_and_plan_filter(db, frozen):
    admin, r = make_super_admin(db), make_retailer(db)
    o = subs.create_offer(db, admin, r, offer_type=OfferType.PERCENT, value=10, valid_from=clock.now() + timedelta(days=1),
                          valid_until=clock.now() + timedelta(days=5), reason="later", plan_code="PRO", billing_cycle=Y)
    assert subs.quote(db, r, plan(db, "PRO"), Y).source == "BASE"            # not started
    frozen.tick(timedelta(days=1))
    assert subs.quote(db, r, plan(db, "PRO"), Y).source == "OFFER"           # started (exact boundary)
    assert subs.quote(db, r, plan(db, "PRO"), M).source == "BASE"            # other cycle
    assert subs.quote(db, r, plan(db, "BASIC"), Y).source == "BASE"          # other plan
    frozen.tick(timedelta(days=4))
    assert subs.quote(db, r, plan(db, "PRO"), Y).source == "BASE"            # ended (valid_until exclusive)
    frozen.tick(timedelta(days=-2))
    subs.revoke_offer(db, admin, r, o.id)
    assert subs.quote(db, r, plan(db, "PRO"), Y).source == "BASE"


def test_offer_validation(db, frozen):
    admin, r = make_super_admin(db), make_retailer(db)
    with pytest.raises(DomainError):
        subs.create_offer(db, admin, r, offer_type=OfferType.PERCENT, value=0, valid_from=clock.now(),
                          valid_until=clock.now() + timedelta(days=1), reason="x")
    with pytest.raises(DomainError):
        subs.create_offer(db, admin, r, offer_type=OfferType.PERCENT, value=10, valid_from=clock.now(),
                          valid_until=clock.now(), reason="x")


# ---- trial and lifecycle ---------------------------------------------------------------------

def test_trial_starts_once_with_configured_plan(db, frozen):
    trial_on(db, days=30, code="PRO")
    r = make_retailer(db)
    sub = subs.start_trial_if_enabled(db, r)
    assert (sub.status, db.get(Plan, sub.plan_id).code) == (SubscriptionStatus.TRIAL, "PRO")
    assert sub.trial_ends_at == clock.now() + timedelta(days=30)
    assert subs.start_trial_if_enabled(db, r) is None  # only once


def test_trial_disabled_gives_no_subscription(db):
    assert subs.start_trial_if_enabled(db, make_retailer(db)) is None


def test_trial_in_months(db, frozen):
    set_setting(db, "trial", {"enabled": True, "duration_value": 1, "duration_unit": "months", "plan_code": "BASIC"})
    sub = subs.start_trial_if_enabled(db, make_retailer(db))
    assert sub.trial_ends_at == add_months(clock.now(), 1)


def test_trial_to_grace_to_expired_on_exact_dates(db, frozen):
    trial_on(db, days=30)
    r = make_retailer(db)
    sub = subs.start_trial_if_enabled(db, r)
    end = sub.trial_ends_at
    assert subs.recompute(db, sub, end - timedelta(microseconds=1)) == SubscriptionStatus.TRIAL
    assert subs.recompute(db, sub, end) == SubscriptionStatus.GRACE           # trial without payment -> GRACE
    assert sub.grace_ends_at == end + timedelta(days=7)                        # default grace 7 days
    assert subs.recompute(db, sub, end + timedelta(days=7) - timedelta(microseconds=1)) == SubscriptionStatus.GRACE
    assert subs.recompute(db, sub, end + timedelta(days=7)) == SubscriptionStatus.EXPIRED


def test_admin_extended_grace_is_respected_and_audited(db, frozen):
    trial_on(db, days=10)
    admin, r = make_super_admin(db, "SUPPORT"), make_retailer(db)
    sub = subs.start_trial_if_enabled(db, r)
    frozen.move_to(sub.trial_ends_at + timedelta(days=8))
    assert subs.recompute(db, sub) == SubscriptionStatus.EXPIRED
    subs.extend_grace(db, admin, r, 5)  # 7 + 5 = 12 days of grace
    assert sub.status == SubscriptionStatus.GRACE
    assert sub.grace_ends_at == sub.trial_ends_at + timedelta(days=12)
    assert len(audits(db, "grace_extended")) == 1


def test_default_grace_days_setting(db, frozen):
    trial_on(db, days=10)
    set_setting(db, "grace_days_default", {"days": 3})
    sub = subs.start_trial_if_enabled(db, make_retailer(db))
    subs.recompute(db, sub, sub.trial_ends_at)
    assert sub.grace_ends_at == sub.trial_ends_at + timedelta(days=3)


# ---- payments ---------------------------------------------------------------------------------

def test_manual_payment_activates_now_when_no_trial(db, frozen):
    admin, r = make_super_admin(db, "SUPPORT"), make_retailer(db)
    p = subs.record_manual_payment(db, admin, r, "BASIC", M, "UTR123")
    sub = subs.get_subscription(db, r.id)
    assert sub.status == SubscriptionStatus.ACTIVE and p.amount_paise == 19900 and p.price_source == "BASE"
    assert (p.period_start, p.period_end) == (clock.now(), add_months(clock.now(), 1))
    assert len(audits(db, "payment_recorded")) == 1


def test_paying_during_trial_loses_no_trial_days(db, frozen):
    trial_on(db, days=30, code="PRO")
    admin, r = make_super_admin(db), make_retailer(db)
    sub = subs.start_trial_if_enabled(db, r)
    frozen.tick(timedelta(days=10))
    p = subs.record_manual_payment(db, admin, r, "BASIC", Y, "cash-1")
    assert p.period_start == sub.trial_ends_at and p.period_end == add_months(sub.trial_ends_at, 12)
    assert sub.status == SubscriptionStatus.TRIAL and db.get(Plan, sub.plan_id).code == "PRO"
    assert subs.recompute(db, sub, sub.trial_ends_at) == SubscriptionStatus.ACTIVE
    assert (db.get(Plan, sub.plan_id).code, sub.billing_cycle) == ("BASIC", Y)


def test_early_renewal_stacks_and_avoids_grace(db, frozen):
    admin, r = make_super_admin(db), make_retailer(db)
    first = subs.record_manual_payment(db, admin, r, "BASIC", M, "a")
    second = subs.record_manual_payment(db, admin, r, "BASIC", M, "b")
    assert second.period_start == first.period_end
    sub = subs.get_subscription(db, r.id)
    assert subs.recompute(db, sub, first.period_end) == SubscriptionStatus.ACTIVE
    assert sub.current_period_end == second.period_end


def test_plan_change_by_payment_applies_from_next_renewal(db, frozen):
    admin, r = make_super_admin(db), make_retailer(db)
    basic = subs.record_manual_payment(db, admin, r, "BASIC", M, "a")
    subs.record_manual_payment(db, admin, r, "PRO", M, "b")
    sub = subs.get_subscription(db, r.id)
    assert db.get(Plan, sub.plan_id).code == "BASIC"                       # still BASIC now
    subs.recompute(db, sub, basic.period_end)
    assert db.get(Plan, sub.plan_id).code == "PRO"                         # PRO from renewal


def test_admin_can_change_plan_immediately(db, frozen):
    admin, r = make_super_admin(db), make_retailer(db)
    subs.record_manual_payment(db, admin, r, "BASIC", M, "a")
    sub = subs.change_plan_now(db, admin, r, "PREMIUM")
    assert db.get(Plan, sub.plan_id).code == "PREMIUM"
    subs.recompute(db, sub, clock.now() + timedelta(days=1))
    assert db.get(Plan, sub.plan_id).code == "PREMIUM"                    # survives recompute
    assert len(audits(db, "plan_changed_now")) == 1


def test_payment_after_expiry_starts_now(db, frozen):
    admin, r = make_super_admin(db), make_retailer(db)
    first = subs.record_manual_payment(db, admin, r, "BASIC", M, "a")
    frozen.move_to(first.period_end + timedelta(days=30))
    sub = subs.get_subscription(db, r.id)
    assert subs.recompute(db, sub) == SubscriptionStatus.EXPIRED
    p = subs.record_manual_payment(db, admin, r, "BASIC", M, "b")
    assert p.period_start == clock.now() and sub.status == SubscriptionStatus.ACTIVE


def test_yearly_period_and_month_end_clamp():
    assert add_months(datetime(2026, 1, 31, tzinfo=UTC), 1) == datetime(2026, 2, 28, tzinfo=UTC)
    assert add_months(datetime(2028, 1, 31, tzinfo=UTC), 1) == datetime(2028, 2, 29, tzinfo=UTC)
    assert add_months(datetime(2026, 10, 17, tzinfo=UTC), 12) == datetime(2027, 10, 17, tzinfo=UTC)


# ---- admin price changes ----------------------------------------------------------------------

def test_price_change_new_only_grandfathers_existing_subscribers(db, frozen):
    admin = make_super_admin(db)
    old_r, new_r = make_retailer(db), make_retailer(db)
    subs.record_manual_payment(db, admin, old_r, "PRO", M, "a")
    res = subs.update_plan_prices(db, admin, "PRO", monthly_paise=49900, yearly_paise=None, apply_to="NEW_ONLY")
    assert res["grandfathered"] == 1
    assert subs.quote(db, old_r, plan(db, "PRO"), M).amount_paise == 39900   # keeps old price
    assert subs.quote(db, new_r, plan(db, "PRO"), M).amount_paise == 49900   # new retailers pay new price
    assert len(audits(db, "plan_price_changed")) == 1 and len(audits(db, "price_grandfathered")) == 1


def test_price_change_all_applies_to_everyone(db, frozen):
    admin, r = make_super_admin(db), make_retailer(db)
    subs.record_manual_payment(db, admin, r, "PRO", M, "a")
    subs.update_plan_prices(db, admin, "PRO", monthly_paise=29900, yearly_paise=None, apply_to="ALL")
    assert subs.quote(db, r, plan(db, "PRO"), M).amount_paise == 29900


def test_no_free_plan_price_zero_rejected(db):
    with pytest.raises(DomainError):
        subs.update_plan_prices(db, make_super_admin(db), "BASIC", monthly_paise=0, yearly_paise=None, apply_to="ALL")


def test_settings_change_validated_and_audited(db):
    admin = make_super_admin(db)
    subs.update_setting(db, admin, "trial", {"enabled": False, "duration_value": 14, "duration_unit": "days", "plan_code": "BASIC"})
    assert len(audits(db, "setting_trial_changed")) == 1
    with pytest.raises(DomainError):
        subs.update_setting(db, admin, "trial", {"enabled": True, "duration_value": 0, "duration_unit": "days", "plan_code": "PRO"})
    with pytest.raises(DomainError):
        subs.update_setting(db, admin, "grace_days_default", {"days": -1})


def test_every_admin_action_is_audited(db, frozen):
    admin, r = make_super_admin(db), make_retailer(db)
    subs.record_manual_payment(db, admin, r, "BASIC", M, "a")
    subs.extend_grace(db, admin, r, 2)
    subs.set_price_override(db, admin, r, 15000, "loyal")
    o = subs.create_offer(db, admin, r, offer_type=OfferType.PERCENT, value=5, valid_from=clock.now(),
                          valid_until=clock.now() + timedelta(days=1), reason="x")
    subs.revoke_offer(db, admin, r, o.id)
    subs.change_plan_now(db, admin, r, "PRO")
    actions = {a.action for a in db.scalars(select(SubscriptionAuditLog).where(SubscriptionAuditLog.retailer_id == r.id))}
    assert actions == {"payment_recorded", "grace_extended", "price_override_set", "offer_created", "offer_revoked",
                       "plan_changed_now"}


# ---- lifecycle job ----------------------------------------------------------------------------

def test_lifecycle_job_transitions_and_reminds_once(db, frozen):
    trial_on(db, days=5)
    r = make_retailer(db)
    sub = subs.start_trial_if_enabled(db, r)
    frozen.move_to(sub.trial_ends_at - timedelta(days=2))
    subs.run_lifecycle(db)
    subs.run_lifecycle(db)  # idempotent: reminder only once
    reminders = db.scalars(select(Notification).where(Notification.template == "subscription_expiring")).all()
    assert len(reminders) == 1 and reminders[0].user_id == r.user_id
    frozen.move_to(sub.trial_ends_at)
    res = subs.run_lifecycle(db)
    assert res["changed"] == 1 and sub.status == SubscriptionStatus.GRACE
    subs.run_lifecycle(db)
    assert db.scalar(select(func.count()).select_from(Notification).where(Notification.template == "subscription_grace")) == 1


def test_no_reminder_when_next_period_already_paid(db, frozen):
    admin, r = make_super_admin(db), make_retailer(db)
    first = subs.record_manual_payment(db, admin, r, "BASIC", M, "a")
    subs.record_manual_payment(db, admin, r, "BASIC", M, "b")
    frozen.move_to(first.period_end - timedelta(days=1))
    assert subs.run_lifecycle(db)["reminders"] == 0


def test_expired_retailer_is_not_live(db, frozen):
    from app.services import plan_service

    admin, r = make_super_admin(db), make_retailer(db)
    p = subs.record_manual_payment(db, admin, r, "BASIC", M, "a")
    assert plan_service.get_live_subscription(db, r.id) is not None
    frozen.move_to(p.period_end + timedelta(days=7))
    subs.run_lifecycle(db)
    assert plan_service.get_live_subscription(db, r.id) is None


def test_payments_never_double_count(db, frozen):
    admin, r = make_super_admin(db), make_retailer(db)
    subs.record_manual_payment(db, admin, r, "BASIC", M, "a")
    sub = subs.get_subscription(db, r.id)
    paid = db.scalars(select(SubscriptionPayment).where(SubscriptionPayment.subscription_id == sub.id)).all()
    subs._activate(db, sub, paid[0], clock.now())  # second activation is a no-op
    assert db.scalar(select(func.count()).select_from(SubscriptionPayment)) == 1


# ---- deep audit: a price override belongs to one plan + cycle --------------------------------------

def test_override_does_not_follow_the_retailer_to_another_plan_or_cycle(db, frozen):
    admin, r = make_super_admin(db), make_retailer(db)
    subs.record_manual_payment(db, admin, r, "PRO", M, "a")
    subs.set_price_override(db, admin, r, 29900, "loyal customer")
    assert subs.quote(db, r, plan(db, "PRO"), M).amount_paise == 29900
    assert subs.quote(db, r, plan(db, "PRO"), Y).amount_paise == 319900       # yearly: not the monthly override
    assert subs.quote(db, r, plan(db, "BASIC"), M).amount_paise == 19900      # another plan: its own price
    subs.record_manual_payment(db, admin, r, "PRO", Y, "b")                    # queued yearly period ...
    frozen.tick(timedelta(days=32))
    subs.run_lifecycle(db)                                                     # ... becomes current
    assert subs.quote(db, r, plan(db, "PRO"), Y).amount_paise == 319900       # still the real yearly price
    assert subs.quote(db, r, plan(db, "PRO"), M).amount_paise == 29900        # override kept for PRO monthly


def test_price_change_all_ends_grandfathering_but_keeps_admin_overrides(db, frozen):
    admin = make_super_admin(db)
    kept, custom = make_retailer(db), make_retailer(db)
    subs.record_manual_payment(db, admin, kept, "PRO", M, "a")
    subs.record_manual_payment(db, admin, custom, "PRO", M, "b")
    subs.set_price_override(db, admin, custom, 25000, "special deal")
    subs.update_plan_prices(db, admin, "PRO", monthly_paise=44900, yearly_paise=None, apply_to="NEW_ONLY")
    assert subs.quote(db, kept, plan(db, "PRO"), M).amount_paise == 39900     # grandfathered
    subs.update_plan_prices(db, admin, "PRO", monthly_paise=49900, yearly_paise=None, apply_to="ALL")
    assert subs.quote(db, kept, plan(db, "PRO"), M).amount_paise == 49900     # "all" includes them now
    assert subs.quote(db, custom, plan(db, "PRO"), M).amount_paise == 25000   # admin deal untouched
    assert len(audits(db, "price_grandfathering_ended")) == 1


def test_months_are_counted_in_indian_time():
    from zoneinfo import ZoneInfo
    ist = ZoneInfo("Asia/Kolkata")
    paid = datetime(2026, 5, 1, 1, 0, tzinfo=ist).astimezone(UTC)      # 30 Apr 19:30 UTC
    assert add_months(paid, 1).astimezone(ist) == datetime(2026, 6, 1, 1, 0, tzinfo=ist)


def test_paying_months_ahead_does_not_lose_days_after_february(db):
    from freezegun import freeze_time
    admin, r = make_super_admin(db), make_retailer(db)
    with freeze_time("2027-01-31 06:00:00"):  # 31 Jan, 11:30 IST
        a = subs.record_manual_payment(db, admin, r, "BASIC", M, "a")
        b = subs.record_manual_payment(db, admin, r, "BASIC", M, "b")
    ist = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")
    assert a.period_end.astimezone(ist).date().isoformat() == "2027-02-28"
    assert b.period_end.astimezone(ist).date().isoformat() == "2027-03-31"  # not 28 Mar
