"""Wallet points (SPEC 4.5, 4.11). 1 point = 1 paisa. Balances are cached on the wallet row and always equal
the sum of its append-only ledger entries; they can never go negative."""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Model
from app.models.enums import RedemptionStatus, WalletEntryType, WalletOwnerType
from app.models.types import pg_enum


class Wallet(Model):
    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("owner_type", "owner_id"),
        CheckConstraint("balance_paise >= 0", name="balance_non_negative"),
    )

    owner_type: Mapped[WalletOwnerType] = mapped_column(pg_enum(WalletOwnerType, "wallet_owner_type"))
    owner_id: Mapped[uuid.UUID] = mapped_column()  # customers.id or retailers.id
    balance_paise: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class WalletLedger(Model):
    """Append-only (DB trigger blocks UPDATE/DELETE)."""

    __tablename__ = "wallet_ledger"
    __table_args__ = (Index("ix_wallet_ledger_wallet_id_created_at", "wallet_id", "created_at"),)

    wallet_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("wallets.id"))
    entry_type: Mapped[WalletEntryType] = mapped_column(pg_enum(WalletEntryType, "wallet_entry_type"))
    amount_paise: Mapped[int] = mapped_column(BigInteger)  # signed
    balance_after_paise: Mapped[int] = mapped_column(BigInteger)
    reference_type: Mapped[str | None] = mapped_column(String(30))
    reference_id: Mapped[uuid.UUID | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class WalletRedemption(Model):
    """One attempt to turn a THE-MANAGER code into points. Saved BEFORE the remote call so a lost response
    can be retried with the same request_id (THE-MANAGER replays the original 200)."""

    __tablename__ = "wallet_redemptions"
    __table_args__ = (
        # A code can be credited at most once in Showcase, whatever THE-MANAGER says.
        Index("uq_wallet_redemptions_code_hash_credited", "code_hash", unique=True,
              postgresql_where=text("status = 'CREDITED'")),
        Index("ix_wallet_redemptions_status_created_at", "status", "created_at"),
    )

    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))  # HMAC of the normalised code; the code itself is not stored
    code_hint: Mapped[str] = mapped_column(String(8))  # e.g. "••••EFGH" for the customer's history
    code_sent: Mapped[str] = mapped_column(String(32))  # exactly as typed, needed to retry; cleared once final
    request_id: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[RedemptionStatus] = mapped_column(pg_enum(RedemptionStatus, "redemption_status"))
    amount_paise: Mapped[int | None] = mapped_column(BigInteger)
    remote_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
