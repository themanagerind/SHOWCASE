"""Tables for later steps (orders/courier, reviews, analytics, leads, notifications). Logic not built yet."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Model
from app.models.enums import (
    LeadStatus,
    NotificationChannel,
    NotificationStatus,
    OrderStatus,
    ReviewSource,
    ShipmentStatus,
    ShopEventType,
)
from app.models.types import pg_enum


class Order(Model):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_retailer_id_status", "retailer_id", "status"),)

    order_no: Mapped[str] = mapped_column(String(20), unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    item_total_paise: Mapped[int] = mapped_column(BigInteger)
    shipping_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    shipping_markup_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    total_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[OrderStatus] = mapped_column(pg_enum(OrderStatus, "order_status"))
    delivery_address: Mapped[dict] = mapped_column(JSONB)
    payment_reference: Mapped[str | None] = mapped_column(String(100))


class Shipment(Model):
    __tablename__ = "shipments"

    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), unique=True)
    provider: Mapped[str] = mapped_column(String(30))
    awb: Mapped[str | None] = mapped_column(String(60), index=True)
    label_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ShipmentStatus] = mapped_column(pg_enum(ShipmentStatus, "shipment_status"))
    rate_paise: Mapped[int | None] = mapped_column(BigInteger)
    tracking_events: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")


class Review(Model):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("source_type", "source_id"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"), index=True)
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[ReviewSource] = mapped_column(pg_enum(ReviewSource, "review_source"))
    source_id: Mapped[uuid.UUID] = mapped_column()
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    flag_reason: Mapped[str | None] = mapped_column(Text)
    # Moderation (SPEC 4.7): retailer flags -> admin hides (out of page and average) or keeps.
    flagged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # starts the 30-day edit window


class ShopEvent(Model):
    __tablename__ = "shop_events"
    __table_args__ = (
        Index("ix_shop_events_retailer_id_created_at", "retailer_id", "created_at"),
        Index("ix_shop_events_retailer_id_event_type_created_at", "retailer_id", "event_type", "created_at"),
    )

    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customers.id"))
    anon_id: Mapped[str | None] = mapped_column(String(64))
    event_type: Mapped[ShopEventType] = mapped_column(pg_enum(ShopEventType, "shop_event_type"))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)


class Lead(Model):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("retailer_id", "customer_id"),)

    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    score: Mapped[Decimal] = mapped_column(Numeric(8, 3))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[LeadStatus] = mapped_column(pg_enum(LeadStatus, "lead_status"), default=LeadStatus.NEW)
    model_version: Mapped[str] = mapped_column(String(30), default="rules-v1")


class Notification(Model):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    channel: Mapped[NotificationChannel] = mapped_column(pg_enum(NotificationChannel, "notification_channel"))
    template: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    dedupe_key: Mapped[str] = mapped_column(String(120), unique=True)
    status: Mapped[NotificationStatus] = mapped_column(
        pg_enum(NotificationStatus, "notification_status"), default=NotificationStatus.PENDING
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
