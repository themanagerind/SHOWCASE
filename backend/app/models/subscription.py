import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Model
from app.models.enums import BillingPeriod, OfferType, SubscriptionPaymentStatus, SubscriptionStatus
from app.models.types import pg_enum


class Plan(Model):
    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(20), unique=True)
    name: Mapped[str] = mapped_column(String(60))
    base_price_paise: Mapped[int] = mapped_column(BigInteger)
    billing_period: Mapped[BillingPeriod] = mapped_column(
        pg_enum(BillingPeriod, "billing_period"), default=BillingPeriod.MONTHLY
    )
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
    status: Mapped[SubscriptionStatus] = mapped_column(pg_enum(SubscriptionStatus, "subscription_status"))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grace_days_override: Mapped[int | None] = mapped_column(Integer)
    grace_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    price_override_paise: Mapped[int | None] = mapped_column(BigInteger)
    price_override_reason: Mapped[str | None] = mapped_column(Text)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    plan: Mapped["Plan"] = relationship()


class RetailerOffer(Model):
    __tablename__ = "retailer_offers"

    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"), index=True)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plans.id"))
    offer_type: Mapped[OfferType] = mapped_column(pg_enum(OfferType, "offer_type"))
    value: Mapped[int] = mapped_column(BigInteger)  # percent for PERCENT, paise otherwise
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(Text)
    created_by_admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("admin_users.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SubscriptionPayment(Model):
    __tablename__ = "subscription_payments"

    subscription_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[SubscriptionPaymentStatus] = mapped_column(
        pg_enum(SubscriptionPaymentStatus, "subscription_payment_status")
    )
    gateway: Mapped[str] = mapped_column(String(30), default="razorpay")
    gateway_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SubscriptionAuditLog(Model):
    """Append-only (DB trigger blocks UPDATE/DELETE)."""

    __tablename__ = "subscription_audit_log"

    admin_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("admin_users.id"))
    retailer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("retailers.id"), index=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("subscriptions.id"))
    action: Mapped[str] = mapped_column(String(60))
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
