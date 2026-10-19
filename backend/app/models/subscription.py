import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Model
from app.models.enums import BillingPeriod, OfferType, SubscriptionPaymentStatus, SubscriptionStatus
from app.models.types import pg_enum


class Plan(Model):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(60))
    base_price_paise: Mapped[int] = mapped_column(BigInteger)  # monthly, GST-inclusive
    yearly_price_paise: Mapped[int] = mapped_column(BigInteger)  # GST-inclusive
    features: Mapped[dict] = mapped_column(JSONB, default=dict)
    priority: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class PlatformSetting(Model):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(60), unique=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_users.id"))


class Subscription(Model):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_subscriptions_status_current_period_end", "status", "current_period_end"),)

    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"), unique=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    billing_cycle: Mapped[BillingPeriod] = mapped_column(
        pg_enum(BillingPeriod, "billing_period"), default=BillingPeriod.MONTHLY, server_default="MONTHLY"
    )
    status: Mapped[SubscriptionStatus] = mapped_column(pg_enum(SubscriptionStatus, "subscription_status"))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grace_days_override: Mapped[int | None] = mapped_column(Integer)
    grace_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    price_override_paise: Mapped[int | None] = mapped_column(BigInteger)
    price_override_reason: Mapped[str | None] = mapped_column(Text)
    # The override is for ONE plan + cycle (deep audit): switching plan/cycle must not carry the old price along.
    price_override_plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id"))
    price_override_cycle: Mapped[BillingPeriod | None] = mapped_column(pg_enum(BillingPeriod, "billing_period"))
    # True = kept old price after a NEW_ONLY price change (an "ALL" change ends it); False = set by an admin.
    price_override_grandfathered: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped["Plan"] = relationship(foreign_keys=[plan_id])


class RetailerOffer(Model):
    __tablename__ = "retailer_offers"

    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"), index=True)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id"))  # None = any plan
    billing_cycle: Mapped[BillingPeriod | None] = mapped_column(pg_enum(BillingPeriod, "billing_period"))  # None = any
    offer_type: Mapped[OfferType] = mapped_column(pg_enum(OfferType, "offer_type"))
    value: Mapped[int] = mapped_column(BigInteger)  # percent for PERCENT, paise otherwise
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    created_by_admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("admin_users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SubscriptionPayment(Model):
    """One paid (or pending) billing period. The subscription's state is derived from PAID periods."""

    __tablename__ = "subscription_payments"
    __table_args__ = (
        Index("ix_subscription_payments_subscription_id_status", "subscription_id", "status"),
        # A bank/UPI reference can be recorded once (references are normalised before saving).
        Index("uq_subscription_payments_manual_reference", "reference", unique=True,
              postgresql_where=text("gateway = 'manual'")),
    )

    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    billing_cycle: Mapped[BillingPeriod] = mapped_column(pg_enum(BillingPeriod, "billing_period"))
    amount_paise: Mapped[int] = mapped_column(BigInteger)  # GST-inclusive
    gst_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    price_source: Mapped[str] = mapped_column(String(20))  # OVERRIDE | OFFER | BASE | ADMIN
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # set when PAID
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[SubscriptionPaymentStatus] = mapped_column(
        pg_enum(SubscriptionPaymentStatus, "subscription_payment_status")
    )
    gateway: Mapped[str] = mapped_column(String(30), default="razorpay")  # razorpay | manual
    gateway_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    gateway_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    reference: Mapped[str | None] = mapped_column(String(120))  # UTR / receipt no. for manual payments
    recorded_by_admin_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("admin_users.id"))
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped["Plan"] = relationship()


class SubscriptionAuditLog(Model):
    """Append-only (DB trigger blocks UPDATE/DELETE)."""

    __tablename__ = "subscription_audit_log"

    admin_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("admin_users.id"))
    retailer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("retailers.id"), index=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subscriptions.id"))
    action: Mapped[str] = mapped_column(String(60))
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
