import json
import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.dependencies import get_current_retailer
from app.core.errors import DomainError, Unauthorized
from app.db.session import get_db
from app.models import Plan, Retailer, Subscription, SubscriptionPayment
from app.models.enums import BillingPeriod, SubscriptionPaymentStatus
from app.schemas.subscription import (
    CheckoutConfirmIn,
    CheckoutIn,
    CheckoutOut,
    PaymentOut,
    PlanOptionOut,
    PriceOut,
    SubscriptionOut,
)
from app.services import subscription_service as subs
from app.services.payments.gateway import PaymentGateway, get_gateway

router = APIRouter(tags=["subscriptions"])


def gateway_dep() -> PaymentGateway | None:
    return get_gateway()


def payment_out(db: Session, p: SubscriptionPayment) -> PaymentOut:
    return PaymentOut(
        id=p.id, plan_code=db.get(Plan, p.plan_id).code, billing_cycle=p.billing_cycle, amount_paise=p.amount_paise,
        gst_paise=p.gst_paise, status=p.status.value, gateway=p.gateway, reference=p.reference,
        period_start=p.period_start, period_end=p.period_end, paid_at=p.paid_at,
    )


def subscription_out(db: Session, sub: Subscription | None, gateway: PaymentGateway | None) -> SubscriptionOut:
    if sub is None:
        return SubscriptionOut(status=None, plan_code=None, billing_cycle=None, trial_ends_at=None, current_period_end=None,
                               grace_ends_at=None, next_period=None, online_payment_available=gateway is not None, payments=[])
    payments = db.scalars(
        select(SubscriptionPayment)
        .where(SubscriptionPayment.subscription_id == sub.id, SubscriptionPayment.status == SubscriptionPaymentStatus.PAID)
        .order_by(SubscriptionPayment.paid_at.desc())
    ).all()
    nxt = subs.next_paid_period(db, sub, clock.now())
    return SubscriptionOut(
        status=sub.status.value, plan_code=db.get(Plan, sub.plan_id).code, billing_cycle=sub.billing_cycle,
        trial_ends_at=sub.trial_ends_at, current_period_end=sub.current_period_end, grace_ends_at=sub.grace_ends_at,
        next_period=payment_out(db, nxt) if nxt else None, online_payment_available=gateway is not None,
        payments=[payment_out(db, p) for p in payments],
    )


@router.get("/subscriptions/plans", response_model=list[PlanOptionOut])
def plan_options(retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    """Plans with this retailer's actual prices (override / offer applied), GST-inclusive."""
    out = []
    for plan in db.scalars(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.priority)):
        m = subs.quote(db, retailer, plan, BillingPeriod.MONTHLY)
        y = subs.quote(db, retailer, plan, BillingPeriod.YEARLY)
        out.append(PlanOptionOut(
            code=plan.code, name=plan.name, features=plan.features,
            monthly=PriceOut(base_paise=m.base_paise, amount_paise=m.amount_paise, gst_paise=m.gst_paise, source=m.source),
            yearly=PriceOut(base_paise=y.base_paise, amount_paise=y.amount_paise, gst_paise=y.gst_paise, source=y.source),
        ))
    return out


@router.get("/subscriptions/me", response_model=SubscriptionOut)
def my_subscription(retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db),
                    gateway: PaymentGateway | None = Depends(gateway_dep)):
    return subscription_out(db, subs.get_subscription(db, retailer.id), gateway)


@router.post("/subscriptions/me/checkout", response_model=CheckoutOut)
def checkout(body: CheckoutIn, retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db),
             gateway: PaymentGateway | None = Depends(gateway_dep)):
    payment, q = subs.create_checkout(db, retailer, body.plan_code, body.billing_cycle, gateway)
    return CheckoutOut(payment_id=payment.id, gateway=gateway.name, key_id=gateway.public_key,
                       order_id=payment.gateway_order_id, amount_paise=q.amount_paise)


@router.post("/subscriptions/me/checkout/{payment_id}/confirm", response_model=SubscriptionOut)
def confirm(payment_id: uuid.UUID, body: CheckoutConfirmIn, retailer: Retailer = Depends(get_current_retailer),
            db: Session = Depends(get_db), gateway: PaymentGateway | None = Depends(gateway_dep)):
    subs.confirm_checkout(db, retailer, payment_id, body.razorpay_payment_id, body.razorpay_signature, gateway)
    return subscription_out(db, subs.get_subscription(db, retailer.id), gateway)


@router.post("/webhooks/razorpay", include_in_schema=False)
async def razorpay_webhook(request: Request, db: Session = Depends(get_db),
                           gateway: PaymentGateway | None = Depends(gateway_dep),
                           x_razorpay_signature: str = Header(default="")):
    raw = await request.body()
    if gateway is None:
        raise DomainError("Online payment is not configured", code="gateway_not_configured")
    if not gateway.verify_webhook(raw, x_razorpay_signature):
        raise Unauthorized("Bad webhook signature", code="bad_signature")
    try:
        event = json.loads(raw)
    except ValueError as exc:
        raise DomainError("Invalid JSON", code="bad_payload") from exc
    return {"processed": subs.handle_gateway_event(db, event)}
