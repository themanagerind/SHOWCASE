"""Admin controls (SPEC 5). SUPPORT: view, extend grace, record payments. SUPER_ADMIN: everything."""
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.v1.subscriptions import gateway_dep, subscription_out
from app.core.dependencies import require_admin
from app.core.errors import NotFound
from app.db.session import get_db
from app.models import AdminUser, Plan, Retailer, RetailerOffer, Subscription, SubscriptionAuditLog, User
from app.models.enums import LIVE_SUBSCRIPTION_STATUSES, SubscriptionStatus
from app.schemas.subscription import (
    AdminPlanOut,
    AdminRetailerDetail,
    AdminRetailerPage,
    AdminRetailerRow,
    AuditOut,
    GraceIn,
    ManualPaymentIn,
    OfferIn,
    OfferOut,
    PaymentOut,
    PlanChangeIn,
    PlanPriceIn,
    PriceOverrideIn,
)
from app.services import settings_service
from app.services import subscription_service as subs
from app.services.payments.gateway import PaymentGateway

router = APIRouter(prefix="/admin", tags=["admin"])
any_admin = require_admin()
super_admin = require_admin(super_admin=True)


def _retailer(db: Session, retailer_id: uuid.UUID) -> Retailer:
    r = db.get(Retailer, retailer_id)
    if r is None or r.deleted_at is not None:
        raise NotFound("Retailer not found")
    return r


def _row(db: Session, r: Retailer, sub: Subscription | None) -> AdminRetailerRow:
    return AdminRetailerRow(
        id=r.id, slug=r.slug, shop_name=r.shop_name, city=r.city, phone=db.get(User, r.user_id).phone,
        status=sub.status.value if sub else None, plan_code=db.get(Plan, sub.plan_id).code if sub else None,
        billing_cycle=sub.billing_cycle if sub else None, current_period_end=sub.current_period_end if sub else None,
        grace_ends_at=sub.grace_ends_at if sub else None,
    )


def _audit_out(db: Session, a: SubscriptionAuditLog) -> AuditOut:
    admin = db.get(AdminUser, a.admin_user_id)
    return AuditOut(id=a.id, created_at=a.created_at, admin_phone=db.get(User, admin.user_id).phone,
                    retailer_id=a.retailer_id, action=a.action, old_value=a.old_value, new_value=a.new_value)


def _offer_out(db: Session, o: RetailerOffer) -> OfferOut:
    return OfferOut(id=o.id, offer_type=o.offer_type, value=o.value, plan_code=db.get(Plan, o.plan_id).code if o.plan_id else None,
                    billing_cycle=o.billing_cycle, valid_from=o.valid_from, valid_until=o.valid_until, reason=o.reason,
                    revoked_at=o.revoked_at)


@router.get("/retailers", response_model=AdminRetailerPage)
def list_retailers(
    q: str | None = Query(None, max_length=60),
    status: SubscriptionStatus | None = None,
    no_plan: bool = False,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: AdminUser = Depends(any_admin),
    db: Session = Depends(get_db),
):
    base = (
        select(Retailer, Subscription)
        .join(User, User.id == Retailer.user_id)
        .outerjoin(Subscription, Subscription.retailer_id == Retailer.id)
        .where(Retailer.deleted_at.is_(None))
    )
    if q:
        like = f"%{q.strip().lower()}%"
        base = base.where(or_(func.lower(Retailer.shop_name).like(like), Retailer.slug.like(like),
                              User.phone.like(f"%{q.strip()}%"), Retailer.city.like(like)))
    if status is not None:
        base = base.where(Subscription.status == status)
    if no_plan:
        base = base.where(Subscription.id.is_(None))
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(base.order_by(Retailer.created_at.desc()).limit(limit).offset(offset)).all()
    return AdminRetailerPage(total=total, items=[_row(db, r, s) for r, s in rows])


@router.get("/retailers/{retailer_id}", response_model=AdminRetailerDetail)
def retailer_detail(retailer_id: uuid.UUID, _: AdminUser = Depends(any_admin), db: Session = Depends(get_db),
                    gateway: PaymentGateway | None = Depends(gateway_dep)):
    r = _retailer(db, retailer_id)
    sub = subs.get_subscription(db, r.id)
    offers = db.scalars(select(RetailerOffer).where(RetailerOffer.retailer_id == r.id).order_by(RetailerOffer.created_at.desc()))
    audit = db.scalars(select(SubscriptionAuditLog).where(SubscriptionAuditLog.retailer_id == r.id)
                       .order_by(SubscriptionAuditLog.created_at.desc()).limit(100))
    return AdminRetailerDetail(
        retailer=_row(db, r, sub), subscription=subscription_out(db, sub, gateway),
        price_override_paise=sub.price_override_paise if sub else None,
        price_override_reason=sub.price_override_reason if sub else None,
        grace_days=subs.grace_days(db, sub) if sub else settings_service.get(db, "grace_days_default")["days"],
        offers=[_offer_out(db, o) for o in offers], audit=[_audit_out(db, a) for a in audit],
    )


@router.post("/retailers/{retailer_id}/payments", response_model=PaymentOut, status_code=201)
def record_payment(retailer_id: uuid.UUID, body: ManualPaymentIn, admin: AdminUser = Depends(any_admin),
                   db: Session = Depends(get_db)):
    from app.api.v1.subscriptions import payment_out

    p = subs.record_manual_payment(db, admin, _retailer(db, retailer_id), body.plan_code, body.billing_cycle,
                                   body.reference, body.amount_paise)
    return payment_out(db, p)


@router.post("/retailers/{retailer_id}/grace")
def extend_grace(retailer_id: uuid.UUID, body: GraceIn, admin: AdminUser = Depends(any_admin), db: Session = Depends(get_db)):
    sub = subs.extend_grace(db, admin, _retailer(db, retailer_id), body.extra_days)
    return {"status": sub.status.value, "grace_days": sub.grace_days_override, "grace_ends_at": sub.grace_ends_at}


@router.put("/retailers/{retailer_id}/price-override")
def price_override(retailer_id: uuid.UUID, body: PriceOverrideIn, admin: AdminUser = Depends(super_admin),
                   db: Session = Depends(get_db)):
    sub = subs.set_price_override(db, admin, _retailer(db, retailer_id), body.amount_paise, body.reason)
    return {"price_override_paise": sub.price_override_paise, "reason": sub.price_override_reason}


@router.post("/retailers/{retailer_id}/offers", response_model=OfferOut, status_code=201)
def create_offer(retailer_id: uuid.UUID, body: OfferIn, admin: AdminUser = Depends(super_admin),
                 db: Session = Depends(get_db)):
    o = subs.create_offer(db, admin, _retailer(db, retailer_id), **body.model_dump())
    return _offer_out(db, o)


@router.delete("/retailers/{retailer_id}/offers/{offer_id}", status_code=204)
def revoke_offer(retailer_id: uuid.UUID, offer_id: uuid.UUID, admin: AdminUser = Depends(super_admin),
                 db: Session = Depends(get_db)):
    subs.revoke_offer(db, admin, _retailer(db, retailer_id), offer_id)


@router.post("/retailers/{retailer_id}/plan")
def change_plan(retailer_id: uuid.UUID, body: PlanChangeIn, admin: AdminUser = Depends(super_admin),
                db: Session = Depends(get_db)):
    sub = subs.change_plan_now(db, admin, _retailer(db, retailer_id), body.plan_code)
    return {"plan_code": body.plan_code, "status": sub.status.value}


@router.get("/plans", response_model=list[AdminPlanOut])
def plans(_: AdminUser = Depends(any_admin), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Subscription.plan_id, func.count()).where(
        Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES)).group_by(Subscription.plan_id)).all())
    return [AdminPlanOut(code=p.code, name=p.name, monthly_paise=p.base_price_paise, yearly_paise=p.yearly_price_paise,
                         features=p.features, subscribers=counts.get(p.id, 0))
            for p in db.scalars(select(Plan).order_by(Plan.priority))]


@router.put("/plans/{code}/prices")
def plan_prices(code: str, body: PlanPriceIn, admin: AdminUser = Depends(super_admin), db: Session = Depends(get_db)):
    return subs.update_plan_prices(db, admin, code, monthly_paise=body.monthly_paise, yearly_paise=body.yearly_paise,
                                   apply_to=body.apply_to)


@router.patch("/plans/{code}/features")
def plan_features(code: str, body: dict, admin: AdminUser = Depends(super_admin), db: Session = Depends(get_db)):
    return subs.update_plan_features(db, admin, code, body)


@router.get("/settings")
def get_settings_(_: AdminUser = Depends(any_admin), db: Session = Depends(get_db)):
    return {k: settings_service.get(db, k) for k in settings_service.DEFAULTS}


@router.put("/settings/{key}")
def put_setting(key: str, body: dict, admin: AdminUser = Depends(super_admin), db: Session = Depends(get_db)):
    return subs.update_setting(db, admin, key, body)


@router.get("/audit", response_model=list[AuditOut])
def audit_log(retailer_id: uuid.UUID | None = None, limit: int = Query(100, ge=1, le=500),
              _: AdminUser = Depends(any_admin), db: Session = Depends(get_db)):
    q = select(SubscriptionAuditLog).order_by(SubscriptionAuditLog.created_at.desc()).limit(limit)
    if retailer_id:
        q = q.where(SubscriptionAuditLog.retailer_id == retailer_id)
    return [_audit_out(db, a) for a in db.scalars(q)]


@router.post("/jobs/lifecycle")
def run_lifecycle_now(_: AdminUser = Depends(super_admin), db: Session = Depends(get_db)):
    """Run the hourly subscription job immediately (normally Celery beat does this)."""
    return subs.run_lifecycle(db)
