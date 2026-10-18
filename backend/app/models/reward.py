"""Retailer reward offers (SPEC 4.5): admin offers cash for points collected in a period."""
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Model


class RewardOffer(Model):
    __tablename__ = "retailer_reward_offers"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="period_valid"),
        CheckConstraint("threshold_paise > 0", name="threshold_positive"),
        CheckConstraint("percent_bp > 0 AND percent_bp <= 10000", name="percent_range"),
        # One offer at a time: live offer periods may never overlap, so the same points cannot earn cash twice.
        ExcludeConstraint((func.tstzrange(text("starts_at"), text("ends_at")), "&&"), using="gist",
                          where=text("cancelled_at IS NULL"), name="ex_retailer_reward_offers_no_overlap"),
    )

    name: Mapped[str] = mapped_column(String(120))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    threshold_paise: Mapped[int] = mapped_column(BigInteger)  # points to collect in the period
    percent_bp: Mapped[int] = mapped_column(Integer)  # cash = balance at end × percent_bp / 10000
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))


class RewardParticipant(Model):
    """A retailer who opted in. Leaving (before the end) deletes the row — no money is involved."""

    __tablename__ = "reward_participants"
    __table_args__ = (UniqueConstraint("offer_id", "retailer_id"),)

    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailer_reward_offers.id"))
    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RewardPayout(Model):
    """Cash paid outside the app, recorded once per retailer per offer. Append-only (DB trigger)."""

    __tablename__ = "reward_payouts"
    __table_args__ = (
        UniqueConstraint("offer_id", "retailer_id"),
        CheckConstraint("payout_paise >= 0 AND balance_at_end_paise >= 0", name="amounts_non_negative"),
    )

    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailer_reward_offers.id"))
    retailer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("retailers.id"), index=True)
    points_collected_paise: Mapped[int] = mapped_column(BigInteger)
    balance_at_end_paise: Mapped[int] = mapped_column(BigInteger)  # = points deducted (REWARD_RESET)
    payout_paise: Mapped[int] = mapped_column(BigInteger)
    paid_on: Mapped[date] = mapped_column(Date)
    reference: Mapped[str] = mapped_column(String(120))
    recorded_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
