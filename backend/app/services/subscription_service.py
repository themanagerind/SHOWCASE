"""Subscriptions, pricing, payments and lifecycle (SPEC 5).

State model: a subscription's status is DERIVED from its PAID periods (subscription_payments) and its trial:
  - a PAID period covers now          -> ACTIVE (plan/cycle of that period)
  - else the trial has not ended       -> TRIAL
  - else within grace after last end   -> GRACE (features continue)
  - else                               -> EXPIRED
`recompute()` applies this; the hourly lifecycle job and every payment/admin action call it.
"""
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.dates import add_months
from app.core.errors import Conflict, DomainError, Forbidden, NotFound
from app.models import (
    AdminUser,
    Notification,
    Plan,
    Retailer,
    RetailerOffer,
    Subscription,
    SubscriptionAuditLog,
    SubscriptionPayment,
)
from app.models.enums import (
    LIVE_SUBSCRIPTION_STATUSES,
    AdminRole,
    BillingPeriod,
    NotificationChannel,
    OfferType,
    SubscriptionPaymentStatus,
    SubscriptionStatus,
)
from app.services import settings_service
from app.services.payments.gateway import PaymentGateway

CYCLE_MONTHS = {BillingPeriod.MONTHLY: 1, BillingPeriod.YEARLY: 12}
REMINDER_BEFORE = timedelta(days=3)


# ---- helpers ------------------------------------------------------------------------------------

def get_plan(db: Session, code: str) -> Plan:
    plan = db.scalar(select(Plan).where(Plan.code == code, Plan.is_active.is_(True)))
    if plan is None:
        raise NotFound(f"Unknown plan '{code}'", code="unknown_plan")
    return plan


def get_subscription(db: Session, retailer_id: uuid.UUID, lock: bool = False) -> Subscription | None:
    q = select(Subscription).where(Subscription.retailer_id == retailer_id)
    if lock:
        q = q.with_for_update()
    return db.scalar(q)


def audit(db: Session, admin: AdminUser, action: str, *, retailer_id=None, subscription_id=None, old=None, new=None):
    db.add(SubscriptionAuditLog(
        admin_user_id=admin.id, retailer_id=retailer_id, subscription_id=subscription_id,
        action=action, old_value=old, new_value=new,
    ))


def _round_div(numerator: int, denominator: int) -> int:
    """Integer division rounding half up (money stays in integer paise)."""
    return (2 * numerator + denominator) // (2 * denominator)


# ---- pricing ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Quote:
    plan_code: str
    billing_cycle: BillingPeriod
    base_paise: int
    amount_paise: int  # GST-inclusive
    gst_paise: int
    source: str  # OVERRIDE | OFFER | BASE
    offer_id: uuid.UUID | None = None


def base_price(plan: Plan, cycle: BillingPeriod) -> int:
    return plan.yearly_price_paise if cycle == BillingPeriod.YEARLY else plan.base_price_paise


def gst_part(db: Session, amount_paise: int) -> int:
    gst = settings_service.get(db, "gst")
    rate = gst["rate_bps"]
    if gst["inclusive"]:
        return amount_paise - _round_div(amount_paise * 10000, 10000 + rate)
    return _round_div(amount_paise * rate, 10000)


def active_offer(db: Session, retailer_id, plan: Plan, cycle: BillingPeriod, now: datetime) -> RetailerOffer | None:
    return db.scalar(
        select(RetailerOffer)
        .where(
            RetailerOffer.retailer_id == retailer_id,
            RetailerOffer.revoked_at.is_(None),
            RetailerOffer.valid_from <= now,
            RetailerOffer.valid_until > now,
            (RetailerOffer.plan_id.is_(None)) | (RetailerOffer.plan_id == plan.id),
            (RetailerOffer.billing_cycle.is_(None)) | (RetailerOffer.billing_cycle == cycle),
        )
        .order_by(RetailerOffer.created_at.desc(), RetailerOffer.id.desc())
        .limit(1)
    )


def apply_offer(base: int, offer: RetailerOffer) -> int:
    if offer.offer_type == OfferType.PERCENT:
        return base - _round_div(base * offer.value, 100)
    if offer.offer_type == OfferType.FIXED_DISCOUNT:
        return max(base - offer.value, 0)
    return offer.value  # CUSTOM_PRICE


def quote(db: Session, retailer: Retailer, plan: Plan, cycle: BillingPeriod, now: datetime | None = None) -> Quote:
    """SPEC 5 price order: subscription price_override -> active retailer offer -> plan base price."""
    now = now or clock.now()
    base = base_price(plan, cycle)
    sub = get_subscription(db, retailer.id)
    if (sub and sub.price_override_paise is not None and sub.price_override_plan_id == plan.id
            and sub.price_override_cycle == cycle):
        amount, source, offer_id = sub.price_override_paise, "OVERRIDE", None
    elif (offer := active_offer(db, retailer.id, plan, cycle, now)) is not None:
        amount, source, offer_id = apply_offer(base, offer), "OFFER", offer.id
    else:
        amount, source, offer_id = base, "BASE", None
    return Quote(plan.code, cycle, base, amount, gst_part(db, amount), source, offer_id)


# ---- lifecycle ----------------------------------------------------------------------------------

def grace_days(db: Session, sub: Subscription) -> int:
    if sub.grace_days_override is not None:
        return sub.grace_days_override
    return settings_service.get(db, "grace_days_default")["days"]


def _paid_periods(db: Session, sub: Subscription) -> list[SubscriptionPayment]:
    return list(db.scalars(
        select(SubscriptionPayment)
        .where(SubscriptionPayment.subscription_id == sub.id, SubscriptionPayment.status == SubscriptionPaymentStatus.PAID)
        .order_by(SubscriptionPayment.period_start)
    ))


def recompute(db: Session, sub: Subscription, now: datetime | None = None) -> SubscriptionStatus:
    now = now or clock.now()
    if sub.status == SubscriptionStatus.CANCELLED:
        return sub.status
    periods = _paid_periods(db, sub)
    covering = next((p for p in reversed(periods) if p.period_start <= now < p.period_end), None)
    if covering:
        sub.status = SubscriptionStatus.ACTIVE
        sub.plan_id, sub.billing_cycle = covering.plan_id, covering.billing_cycle
        sub.current_period_start, sub.current_period_end = covering.period_start, covering.period_end
        sub.grace_ends_at = None
    elif sub.trial_ends_at is not None and now < sub.trial_ends_at:
        sub.status = SubscriptionStatus.TRIAL
        sub.current_period_end = sub.trial_ends_at
    else:
        ended = [p.period_end for p in periods if p.period_end <= now]
        if sub.trial_ends_at is not None and sub.trial_ends_at <= now:
            ended.append(sub.trial_ends_at)
        if not ended:
            sub.status = SubscriptionStatus.EXPIRED  # never paid, no trial
            sub.grace_ends_at = None
        else:
            last_end = max(ended)
            sub.current_period_end = last_end
            sub.grace_ends_at = last_end + timedelta(days=grace_days(db, sub))
            sub.status = SubscriptionStatus.GRACE if now < sub.grace_ends_at else SubscriptionStatus.EXPIRED
    db.expire(sub, ["plan"])
    return sub.status


def next_paid_period(db: Session, sub: Subscription, now: datetime) -> SubscriptionPayment | None:
    return db.scalar(
        select(SubscriptionPayment)
        .where(
            SubscriptionPayment.subscription_id == sub.id,
            SubscriptionPayment.status == SubscriptionPaymentStatus.PAID,
            SubscriptionPayment.period_start > now,
        )
        .order_by(SubscriptionPayment.period_start)
        .limit(1)
    )


def _notify(db: Session, user_id, template: str, payload: dict, dedupe_key: str) -> None:
    db.execute(
        insert(Notification)
        .values(user_id=user_id, channel=NotificationChannel.IN_APP, template=template, payload=payload,
                dedupe_key=dedupe_key)
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )


def run_lifecycle(db: Session, now: datetime | None = None) -> dict:
    """Hourly job: recompute every subscription and queue reminders. Safe to run any number of times."""
    now = now or clock.now()
    changed = reminders = 0
    rows = db.execute(
        select(Subscription, Retailer.user_id)
        .join(Retailer, Retailer.id == Subscription.retailer_id)
        .where(Subscription.status != SubscriptionStatus.CANCELLED)
    ).all()
    for sub, user_id in rows:
        before = sub.status
        after = recompute(db, sub, now)
        if after != before:
            changed += 1
            _notify(db, user_id, f"subscription_{after.value.lower()}",
                    {"status": after.value, "grace_ends_at": sub.grace_ends_at.isoformat() if sub.grace_ends_at else None},
                    f"sub:{sub.id}:{after.value}:{(sub.current_period_end or now).isoformat()}")
        ends = sub.current_period_end
        if (after in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL) and ends and now < ends <= now + REMINDER_BEFORE
                and next_paid_period(db, sub, now) is None):
            reminders += 1
            _notify(db, user_id, "subscription_expiring", {"ends_at": ends.isoformat(), "status": after.value},
                    f"sub-expiring:{sub.id}:{ends.isoformat()}")
    db.commit()
    return {"checked": len(rows), "changed": changed, "reminders": reminders}


# ---- trial --------------------------------------------------------------------------------------

def start_trial_if_enabled(db: Session, retailer: Retailer, now: datetime | None = None) -> Subscription | None:
    """Called when a shop is created. One trial per retailer, ever."""
    now = now or clock.now()
    trial = settings_service.get(db, "trial")
    if not trial["enabled"] or get_subscription(db, retailer.id) is not None:
        return None
    if trial["duration_unit"] == "months":
        ends = add_months(now, trial["duration_value"])
    else:
        ends = now + timedelta(days=trial["duration_value"])
    sub = Subscription(
        retailer_id=retailer.id, plan_id=get_plan(db, trial["plan_code"]).id, billing_cycle=BillingPeriod.MONTHLY,
        status=SubscriptionStatus.TRIAL, trial_ends_at=ends, current_period_start=now, current_period_end=ends,
    )
    db.add(sub)
    db.flush()
    return sub


# ---- payments -----------------------------------------------------------------------------------

def _ensure_subscription(db: Session, retailer: Retailer, plan: Plan, cycle: BillingPeriod) -> Subscription:
    sub = get_subscription(db, retailer.id, lock=True)
    if sub is None:
        sub = Subscription(retailer_id=retailer.id, plan_id=plan.id, billing_cycle=cycle, status=SubscriptionStatus.EXPIRED)
        db.add(sub)
        db.flush()
    return sub


def _activate(db: Session, sub: Subscription, payment: SubscriptionPayment, now: datetime) -> None:
    """Mark a payment PAID and place its period. Paying early queues the period after the current one, so the
    retailer loses no days and a plan change takes effect from the next renewal (SPEC 5)."""
    if payment.status == SubscriptionPaymentStatus.PAID:
        return  # idempotent: webhook + client confirmation may both arrive
    latest_end = db.scalar(
        select(func.max(SubscriptionPayment.period_end)).where(
            SubscriptionPayment.subscription_id == sub.id, SubscriptionPayment.status == SubscriptionPaymentStatus.PAID
        )
    )
    start = now
    if latest_end and latest_end > start:
        start = latest_end
    if sub.status == SubscriptionStatus.TRIAL and sub.trial_ends_at and sub.trial_ends_at > start:
        start = sub.trial_ends_at
    payment.period_start = start
    payment.period_end = add_months(start, CYCLE_MONTHS[payment.billing_cycle])
    payment.status = SubscriptionPaymentStatus.PAID
    payment.paid_at = now
    db.flush()
    recompute(db, sub, now)


def create_checkout(db: Session, retailer: Retailer, plan_code: str, cycle: BillingPeriod, gateway: PaymentGateway | None):
    if gateway is None:
        raise DomainError("Online payment is not available yet", code="gateway_not_configured")
    now = clock.now()
    plan = get_plan(db, plan_code)
    q = quote(db, retailer, plan, cycle, now)
    if q.amount_paise <= 0:
        raise DomainError("Nothing to pay for this plan", code="zero_amount")
    sub = _ensure_subscription(db, retailer, plan, cycle)
    payment = SubscriptionPayment(
        subscription_id=sub.id, plan_id=plan.id, billing_cycle=cycle, amount_paise=q.amount_paise,
        gst_paise=q.gst_paise, price_source=q.source, status=SubscriptionPaymentStatus.CREATED, gateway=gateway.name,
    )
    db.add(payment)
    db.flush()
    order = gateway.create_order(q.amount_paise, receipt=str(payment.id),
                                 notes={"retailer_id": str(retailer.id), "plan": plan.code, "cycle": cycle.value})
    payment.gateway_order_id = order.order_id
    db.commit()
    return payment, q


def _lock_payment(db: Session, where) -> SubscriptionPayment | None:
    return db.scalar(select(SubscriptionPayment).where(where).with_for_update().execution_options(populate_existing=True))


def confirm_checkout(db: Session, retailer: Retailer, payment_id: uuid.UUID, gateway_payment_id: str,
                     signature: str, gateway: PaymentGateway | None) -> SubscriptionPayment:
    if gateway is None:
        raise DomainError("Online payment is not available yet", code="gateway_not_configured")
    # Lock order everywhere: subscription, then payment. Two payments settling at once must not both read
    # the same "latest period end" and get overlapping periods.
    sub = get_subscription(db, retailer.id, lock=True)
    payment = _lock_payment(db, SubscriptionPayment.id == payment_id)
    if payment is None or sub is None or payment.subscription_id != sub.id:
        raise NotFound("Payment not found")
    if not gateway.verify_payment(payment.gateway_order_id or "", gateway_payment_id, signature):
        raise DomainError("Payment could not be verified", code="bad_signature")
    if payment.status != SubscriptionPaymentStatus.PAID:
        payment.gateway_payment_id = gateway_payment_id
        _activate(db, sub, payment, clock.now())
    db.commit()
    return payment


def handle_gateway_event(db: Session, event: dict) -> bool:
    """Razorpay webhook (signature already verified). Returns True if a payment was marked paid."""
    if event.get("event") not in ("payment.captured", "order.paid"):
        return False
    entity = event.get("payload", {}).get("payment", {}).get("entity", {})
    order_id, gateway_payment_id = entity.get("order_id"), entity.get("id")
    found = db.scalar(select(SubscriptionPayment).where(SubscriptionPayment.gateway_order_id == order_id)) if order_id else None
    if found is None:
        return False
    db.scalar(select(Subscription).where(Subscription.id == found.subscription_id).with_for_update())  # same lock order
    payment = _lock_payment(db, SubscriptionPayment.id == found.id)
    if entity.get("amount") is not None and int(entity["amount"]) != payment.amount_paise:
        raise DomainError("Paid amount does not match the order", code="amount_mismatch")
    if payment.status != SubscriptionPaymentStatus.PAID:
        payment.gateway_payment_id = gateway_payment_id
        payment.raw_payload = event
        _activate(db, db.get(Subscription, payment.subscription_id), payment, clock.now())
    db.commit()
    return True


# ---- admin actions (every one is audited) -------------------------------------------------------

def normalise_reference(raw: str) -> str:
    """'utr 123456', 'UTR123456\u200b' and fullwidth 'ＵＴＲ123456' are the same bank reference."""
    s = unicodedata.normalize("NFKC", raw)
    return "".join(ch for ch in s if not ch.isspace() and unicodedata.category(ch) != "Cf").upper()


def record_manual_payment(db: Session, admin: AdminUser, retailer: Retailer, plan_code: str, cycle: BillingPeriod,
                          reference: str, amount_paise: int | None = None) -> SubscriptionPayment:
    now = clock.now()
    plan = get_plan(db, plan_code)
    q = quote(db, retailer, plan, cycle, now)
    amount = q.amount_paise if amount_paise is None else amount_paise
    if amount < 0:
        raise DomainError("Amount cannot be negative", code="invalid_amount")
    if amount != q.amount_paise and admin.role != AdminRole.SUPER_ADMIN:
        # A different amount is effectively a price change, which is SUPER_ADMIN-only (SPEC 5).
        raise Forbidden("Only a super admin can record a different amount", code="super_admin_only")
    reference = normalise_reference(reference)
    sub = _ensure_subscription(db, retailer, plan, cycle)  # locks the subscription: serialises payments
    if db.scalar(select(SubscriptionPayment.id).where(SubscriptionPayment.gateway == "manual",
                                                      SubscriptionPayment.reference == reference)):
        raise Conflict("A payment with this reference is already recorded", code="duplicate_reference")
    payment = SubscriptionPayment(
        subscription_id=sub.id, plan_id=plan.id, billing_cycle=cycle, amount_paise=amount,
        gst_paise=gst_part(db, amount), price_source=q.source if amount_paise is None else "ADMIN",
        status=SubscriptionPaymentStatus.CREATED, gateway="manual", reference=reference, recorded_by_admin_id=admin.id,
    )
    db.add(payment)
    db.flush()
    _activate(db, sub, payment, now)
    audit(db, admin, "payment_recorded", retailer_id=retailer.id, subscription_id=sub.id, new={
        "plan": plan.code, "cycle": cycle.value, "amount_paise": amount, "reference": reference,
        "period_start": payment.period_start.isoformat(), "period_end": payment.period_end.isoformat(),
    })
    db.commit()
    return payment


def _live_or_any_subscription(db: Session, retailer: Retailer) -> Subscription:
    sub = get_subscription(db, retailer.id, lock=True)
    if sub is None:
        raise NotFound("This retailer has no subscription yet", code="no_subscription")
    return sub


def extend_grace(db: Session, admin: AdminUser, retailer: Retailer, extra_days: int) -> Subscription:
    if not 1 <= extra_days <= 90:
        raise DomainError("Extra days must be 1-90", code="invalid_days")
    sub = _live_or_any_subscription(db, retailer)
    old = {"grace_days": grace_days(db, sub), "grace_ends_at": sub.grace_ends_at.isoformat() if sub.grace_ends_at else None,
           "status": sub.status.value}
    sub.grace_days_override = grace_days(db, sub) + extra_days
    recompute(db, sub)
    audit(db, admin, "grace_extended", retailer_id=retailer.id, subscription_id=sub.id, old=old, new={
        "grace_days": sub.grace_days_override, "grace_ends_at": sub.grace_ends_at.isoformat() if sub.grace_ends_at else None,
        "status": sub.status.value,
    })
    db.commit()
    return sub


def set_price_override(db: Session, admin: AdminUser, retailer: Retailer, amount_paise: int | None, reason: str) -> Subscription:
    if amount_paise is not None and amount_paise < 0:
        raise DomainError("Price cannot be negative", code="invalid_amount")
    sub = _live_or_any_subscription(db, retailer)
    old = {"price_override_paise": sub.price_override_paise, "reason": sub.price_override_reason}
    sub.price_override_paise, sub.price_override_reason = amount_paise, reason if amount_paise is not None else None
    # Bound to the plan + cycle the retailer is on now; it does not follow them to another plan or cycle.
    sub.price_override_plan_id = sub.plan_id if amount_paise is not None else None
    sub.price_override_cycle = sub.billing_cycle if amount_paise is not None else None
    sub.price_override_grandfathered = False
    audit(db, admin, "price_override_set", retailer_id=retailer.id, subscription_id=sub.id, old=old,
          new={"price_override_paise": amount_paise, "reason": reason})
    db.commit()
    return sub


def create_offer(db: Session, admin: AdminUser, retailer: Retailer, *, offer_type: OfferType, value: int,
                 valid_from: datetime, valid_until: datetime, reason: str, plan_code: str | None = None,
                 billing_cycle: BillingPeriod | None = None) -> RetailerOffer:
    if valid_until <= valid_from:
        raise DomainError("valid_until must be after valid_from", code="invalid_dates")
    if offer_type == OfferType.PERCENT and not 1 <= value <= 100:
        raise DomainError("Percent must be 1-100", code="invalid_offer")
    if offer_type != OfferType.PERCENT and value < 0:
        raise DomainError("Amount cannot be negative", code="invalid_offer")
    offer = RetailerOffer(
        retailer_id=retailer.id, plan_id=get_plan(db, plan_code).id if plan_code else None, billing_cycle=billing_cycle,
        offer_type=offer_type, value=value, valid_from=valid_from, valid_until=valid_until, reason=reason,
        created_by_admin_id=admin.id,
    )
    db.add(offer)
    db.flush()
    audit(db, admin, "offer_created", retailer_id=retailer.id, new={
        "offer_id": str(offer.id), "type": offer_type.value, "value": value, "plan": plan_code,
        "cycle": billing_cycle.value if billing_cycle else None, "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(), "reason": reason,
    })
    db.commit()
    return offer


def revoke_offer(db: Session, admin: AdminUser, retailer: Retailer, offer_id: uuid.UUID) -> None:
    offer = db.get(RetailerOffer, offer_id)
    if offer is None or offer.retailer_id != retailer.id:
        raise NotFound("Offer not found")
    if offer.revoked_at is None:
        offer.revoked_at = clock.now()
        audit(db, admin, "offer_revoked", retailer_id=retailer.id, old={"offer_id": str(offer.id)})
    db.commit()


def change_plan_now(db: Session, admin: AdminUser, retailer: Retailer, plan_code: str) -> Subscription:
    """Admin-only immediate plan change (retailer changes apply from the next renewal)."""
    now = clock.now()
    plan = get_plan(db, plan_code)
    sub = _live_or_any_subscription(db, retailer)
    old_plan = db.get(Plan, sub.plan_id).code
    covering = db.scalar(select(SubscriptionPayment).where(
        SubscriptionPayment.subscription_id == sub.id, SubscriptionPayment.status == SubscriptionPaymentStatus.PAID,
        SubscriptionPayment.period_start <= now, SubscriptionPayment.period_end > now,
    ))
    if covering is not None:
        covering.plan_id = plan.id
    sub.plan_id = plan.id
    recompute(db, sub, now)
    audit(db, admin, "plan_changed_now", retailer_id=retailer.id, subscription_id=sub.id,
          old={"plan": old_plan}, new={"plan": plan.code})
    db.commit()
    return sub


def update_plan_prices(db: Session, admin: AdminUser, plan_code: str, *, monthly_paise: int | None,
                       yearly_paise: int | None, apply_to: str) -> dict:
    """apply_to = ALL (everyone renews at the new price) or NEW_ONLY (existing subscribers keep today's price
    as a recorded price_override for their plan and cycle)."""
    if apply_to not in ("ALL", "NEW_ONLY"):
        raise DomainError("apply_to must be ALL or NEW_ONLY", code="invalid_scope")
    for v in (monthly_paise, yearly_paise):
        if v is not None and v <= 0:
            raise DomainError("Price must be more than 0 (no free plan)", code="invalid_amount")
    plan = get_plan(db, plan_code)
    old = {"monthly_paise": plan.base_price_paise, "yearly_paise": plan.yearly_price_paise}
    grandfathered = 0
    if apply_to == "NEW_ONLY":
        changed_cycles = {
            BillingPeriod.MONTHLY: monthly_paise is not None and monthly_paise != plan.base_price_paise,
            BillingPeriod.YEARLY: yearly_paise is not None and yearly_paise != plan.yearly_price_paise,
        }
        subs = db.scalars(select(Subscription).where(
            Subscription.plan_id == plan.id, Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.price_override_paise.is_(None),
        ))
        for sub in subs:
            if changed_cycles[sub.billing_cycle]:
                sub.price_override_paise = base_price(plan, sub.billing_cycle)
                sub.price_override_reason = f"Grandfathered: {plan.code} price change on {clock.now().date().isoformat()}"
                sub.price_override_plan_id, sub.price_override_cycle = plan.id, sub.billing_cycle
                sub.price_override_grandfathered = True
                grandfathered += 1
                audit(db, admin, "price_grandfathered", retailer_id=sub.retailer_id, subscription_id=sub.id,
                      new={"price_override_paise": sub.price_override_paise})
    else:  # ALL: "apply to all" includes retailers who kept an old price; admin-set custom prices stay
        for sub in db.scalars(select(Subscription).where(Subscription.price_override_grandfathered.is_(True),
                                                         Subscription.price_override_plan_id == plan.id)):
            audit(db, admin, "price_grandfathering_ended", retailer_id=sub.retailer_id, subscription_id=sub.id,
                  old={"price_override_paise": sub.price_override_paise})
            sub.price_override_paise = sub.price_override_reason = None
            sub.price_override_plan_id = sub.price_override_cycle = None
            sub.price_override_grandfathered = False
            grandfathered -= 1
    if monthly_paise is not None:
        plan.base_price_paise = monthly_paise
    if yearly_paise is not None:
        plan.yearly_price_paise = yearly_paise
    new = {"monthly_paise": plan.base_price_paise, "yearly_paise": plan.yearly_price_paise, "apply_to": apply_to,
           "grandfathered": grandfathered}
    audit(db, admin, "plan_price_changed", old={"plan": plan.code, **old}, new={"plan": plan.code, **new})
    db.commit()
    return new


FEATURE_KEYS = {"max_products", "weekly_swap", "visibility_scope", "analytics", "ml_leads", "broadcast", "courier"}


def update_plan_features(db: Session, admin: AdminUser, plan_code: str, features: dict) -> dict:
    unknown = set(features) - FEATURE_KEYS
    if unknown:
        raise DomainError(f"Unknown features: {', '.join(sorted(unknown))}", code="invalid_features")
    if "visibility_scope" in features and features["visibility_scope"] not in ("PINCODE", "CITY", "INDIA"):
        raise DomainError("visibility_scope must be PINCODE, CITY or INDIA", code="invalid_features")
    if "max_products" in features and features["max_products"] is not None and (
        not isinstance(features["max_products"], int) or features["max_products"] < 1
    ):
        raise DomainError("max_products must be a positive number or null (unlimited)", code="invalid_features")
    plan = get_plan(db, plan_code)
    old = dict(plan.features)
    plan.features = {**plan.features, **features}
    audit(db, admin, "plan_features_changed", old={"plan": plan.code, **old}, new={"plan": plan.code, **plan.features})
    db.commit()
    return plan.features


def update_setting(db: Session, admin: AdminUser, key: str, value: dict) -> dict:
    old, new = settings_service.put(db, key, value, admin.id)
    audit(db, admin, f"setting_{key}_changed", old=old, new=new)
    db.commit()
    return new

