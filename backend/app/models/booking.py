"""Bookings with wallet points (SPEC 4.4) and retailer discounts on unlisted items (SPEC 4.4a)."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Model
from app.models.enums import BookingStatus, DiscountRequestStatus
from app.models.types import pg_enum


class Booking(Model):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_bookings_retailer_id_status", "retailer_id", "status"),
        Index("ix_bookings_customer_id_status", "customer_id", "status"),
        Index("ix_bookings_status_expires_at", "status", "expires_at"),
        CheckConstraint("discount_paise > 0", name="discount_positive"),
    )

    booking_no: Mapped[str] = mapped_column(String(16), unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    product_name: Mapped[str] = mapped_column(String(160))  # snapshot at booking time
    price_paise: Mapped[int] = mapped_column(BigInteger)  # snapshot
    discount_paise: Mapped[int] = mapped_column(BigInteger)  # points held = discount at purchase
    status: Mapped[BookingStatus] = mapped_column(pg_enum(BookingStatus, "booking_status"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    purchased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    forfeited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)


class ShopDiscountRequest(Model):
    __tablename__ = "shop_discount_requests"
    __table_args__ = (
        Index("ix_shop_discount_requests_customer_id_status", "customer_id", "status"),
        Index("ix_shop_discount_requests_retailer_id_created_at", "retailer_id", "created_at"),
        CheckConstraint("amount_paise > 0", name="amount_positive"),
    )

    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    note: Mapped[str] = mapped_column(String(120))
    status: Mapped[DiscountRequestStatus] = mapped_column(pg_enum(DiscountRequestStatus, "discount_request_status"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
