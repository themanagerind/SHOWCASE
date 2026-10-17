import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Model
from app.models.enums import BookingStatus, CreditStatus, LedgerEntryType, PaymentMethod
from app.models.types import pg_enum


class Booking(Model):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_bookings_retailer_id_status", "retailer_id", "status"),
        Index("ix_bookings_customer_id_status", "customer_id", "status"),
        Index("ix_bookings_status_cancel_deadline", "status", "cancel_deadline"),
        CheckConstraint("advance_paise >= 0 AND advance_paise <= total_paise", name="advance_within_total"),
    )

    booking_no: Mapped[str] = mapped_column(String(20), unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price_paise: Mapped[int] = mapped_column(BigInteger)
    total_paise: Mapped[int] = mapped_column(BigInteger)
    advance_paise: Mapped[int] = mapped_column(BigInteger)
    balance_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[BookingStatus] = mapped_column(
        pg_enum(BookingStatus, "booking_status"), default=BookingStatus.PENDING_PAYMENT
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    credit_issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}


class PaymentConfirmation(Model):
    __tablename__ = "payment_confirmations"
    __table_args__ = (UniqueConstraint("booking_id", "method", "reference"),)

    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id"), index=True)
    method: Mapped[PaymentMethod] = mapped_column(pg_enum(PaymentMethod, "payment_method"))
    reference: Mapped[str] = mapped_column(String(100), default="")
    proof_media_key: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict | None] = mapped_column(JSONB)
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class CustomerCredit(Model):
    __tablename__ = "customer_credits"
    __table_args__ = (
        Index("ix_customer_credits_customer_retailer_status", "customer_id", "retailer_id", "status"),
        CheckConstraint("used_amount_paise >= 0 AND used_amount_paise <= amount_paise", name="used_within_amount"),
        CheckConstraint("amount_paise > 0", name="amount_positive"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"), index=True)
    booking_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bookings.id"), unique=True)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    used_amount_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    status: Mapped[CreditStatus] = mapped_column(pg_enum(CreditStatus, "credit_status"), default=CreditStatus.ACTIVE)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    settled_note: Mapped[str | None] = mapped_column(Text)


class CreditLedger(Model):
    """Append-only (DB trigger blocks UPDATE/DELETE)."""

    __tablename__ = "credit_ledger"

    credit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customer_credits.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"))
    entry_type: Mapped[LedgerEntryType] = mapped_column(pg_enum(LedgerEntryType, "ledger_entry_type"))
    amount_paise: Mapped[int] = mapped_column(BigInteger)  # +issue, -use, -settle
    balance_after_paise: Mapped[int] = mapped_column(BigInteger)
    reference_type: Mapped[str | None] = mapped_column(String(30))
    reference_id: Mapped[uuid.UUID | None] = mapped_column()
    performed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(Text)
