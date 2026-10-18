import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import BillingPeriod, OfferType


class PriceOut(BaseModel):
    base_paise: int
    amount_paise: int
    gst_paise: int
    source: str


class PlanOptionOut(BaseModel):
    code: str
    name: str
    features: dict
    monthly: PriceOut
    yearly: PriceOut


class PaymentOut(BaseModel):
    id: uuid.UUID
    plan_code: str
    billing_cycle: BillingPeriod
    amount_paise: int
    gst_paise: int
    status: str
    gateway: str
    reference: str | None
    period_start: datetime | None
    period_end: datetime | None
    paid_at: datetime | None


class SubscriptionOut(BaseModel):
    status: str | None
    plan_code: str | None
    billing_cycle: BillingPeriod | None
    trial_ends_at: datetime | None
    current_period_end: datetime | None
    grace_ends_at: datetime | None
    next_period: PaymentOut | None  # a paid period that starts later (renewal / plan change)
    online_payment_available: bool
    payments: list[PaymentOut]


class CheckoutIn(BaseModel):
    plan_code: str
    billing_cycle: BillingPeriod


class CheckoutOut(BaseModel):
    payment_id: uuid.UUID
    gateway: str
    key_id: str
    order_id: str
    amount_paise: int
    currency: str = "INR"


class CheckoutConfirmIn(BaseModel):
    razorpay_payment_id: str = Field(max_length=64)
    razorpay_signature: str = Field(max_length=128)


# ---- admin ----

class AdminRetailerRow(BaseModel):
    id: uuid.UUID
    slug: str
    shop_name: str
    city: str
    phone: str
    status: str | None
    plan_code: str | None
    billing_cycle: BillingPeriod | None
    current_period_end: datetime | None
    grace_ends_at: datetime | None


class AdminRetailerPage(BaseModel):
    total: int
    items: list[AdminRetailerRow]


class OfferIn(BaseModel):
    offer_type: OfferType
    value: int = Field(ge=0)
    valid_from: datetime
    valid_until: datetime
    reason: str = Field(min_length=3, max_length=500)
    plan_code: str | None = None
    billing_cycle: BillingPeriod | None = None


class OfferOut(BaseModel):
    id: uuid.UUID
    offer_type: OfferType
    value: int
    plan_code: str | None
    billing_cycle: BillingPeriod | None
    valid_from: datetime
    valid_until: datetime
    reason: str
    revoked_at: datetime | None


class AuditOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    admin_phone: str
    retailer_id: uuid.UUID | None
    action: str
    old_value: dict | None
    new_value: dict | None


class AdminRetailerDetail(BaseModel):
    retailer: AdminRetailerRow
    subscription: SubscriptionOut
    price_override_paise: int | None
    price_override_reason: str | None
    grace_days: int
    offers: list[OfferOut]
    audit: list[AuditOut]


class ManualPaymentIn(BaseModel):
    plan_code: str
    billing_cycle: BillingPeriod
    reference: str = Field(min_length=2, max_length=120)
    amount_paise: int | None = Field(default=None, ge=0)


class GraceIn(BaseModel):
    extra_days: int = Field(ge=1, le=90)


class PriceOverrideIn(BaseModel):
    amount_paise: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=3, max_length=500)


class PlanChangeIn(BaseModel):
    plan_code: str


class PlanPriceIn(BaseModel):
    monthly_paise: int | None = Field(default=None, gt=0)
    yearly_paise: int | None = Field(default=None, gt=0)
    apply_to: str = Field(pattern="^(ALL|NEW_ONLY)$")


class AdminPlanOut(BaseModel):
    code: str
    name: str
    monthly_paise: int
    yearly_paise: int
    features: dict
    subscribers: int
