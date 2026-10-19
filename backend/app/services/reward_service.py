"""Retailer reward offers (SPEC 4.5).

  collected        = points the retailer RECEIVED in [starts_at, ends_at): BOOKING_PURCHASED + SHOP_DISCOUNT_RECEIVED
  qualifies        = opted in AND collected >= threshold
  balance_at_end   = wallet balance at ends_at (ledger up to the end, minus earlier offers' resets recorded later)
  payout           = floor(balance_at_end * percent_bp / 10000), paid in cash outside the app
  on recording     = exactly balance_at_end points leave the wallet (REWARD_RESET); later points stay
"""
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import Conflict, DomainError, Forbidden, NotFound
from app.models import Notification, Retailer, RewardOffer, RewardParticipant, RewardPayout, User, Wallet, WalletLedger
from app.models.enums import NotificationChannel, WalletEntryType, WalletOwnerType
from app.services import plan_service, wallet_service

COLLECTED_TYPES = (WalletEntryType.BOOKING_PURCHASED, WalletEntryType.SHOP_DISCOUNT_RECEIVED)


@dataclass
class Standing:
    retailer_id: uuid.UUID
    shop_name: str
    phone: str | None
    joined_at: datetime
    collected_paise: int
    qualifies: bool
    balance_at_end_paise: int | None  # None until the offer has ended
    payout_paise: int | None
    payout: RewardPayout | None


# ---- admin ----------------------------------------------------------------------------------------

def create_offer(db: Session, user: User, name: str, starts_at: datetime, ends_at: datetime, threshold_paise: int,
                 percent_bp: int) -> RewardOffer:
    if ends_at <= starts_at:
        raise DomainError("End must be after start", code="invalid_period")
    if ends_at <= clock.now():
        raise DomainError("The offer must end in the future", code="invalid_period")
    if threshold_paise <= 0 or not 0 < percent_bp <= 10000:
        raise DomainError("Threshold must be > 0 and percent between 0 and 100", code="invalid_offer")
    if db.scalar(select(RewardOffer.id).where(RewardOffer.cancelled_at.is_(None), RewardOffer.starts_at < ends_at,
                                              RewardOffer.ends_at > starts_at)):
        raise Conflict("Another offer already covers part of this period", code="offer_overlap")
    offer = RewardOffer(name=name.strip(), starts_at=starts_at, ends_at=ends_at, threshold_paise=threshold_paise,
                        percent_bp=percent_bp, created_by_user_id=user.id)
    db.add(offer)
    try:
        db.commit()
    except IntegrityError as e:  # a parallel create won the race; the DB exclusion constraint caught it
        db.rollback()
        raise Conflict("Another offer already covers part of this period", code="offer_overlap") from e
    return offer


def cancel_offer(db: Session, user: User, offer_id: uuid.UUID) -> RewardOffer:
    offer = db.scalar(select(RewardOffer).where(RewardOffer.id == offer_id).with_for_update())
    if offer is None:
        raise NotFound("Offer not found")
    if offer.cancelled_at is not None:
        return offer
    if db.scalar(select(RewardPayout.id).where(RewardPayout.offer_id == offer.id).limit(1)):
        raise Conflict("Payouts are already recorded for this offer", code="offer_has_payouts")
    offer.cancelled_at, offer.cancelled_by_user_id = clock.now(), user.id
    db.commit()
    return offer


def list_offers(db: Session) -> list[RewardOffer]:
    return list(db.scalars(select(RewardOffer).order_by(RewardOffer.starts_at.desc()).limit(100)))


def get_offer(db: Session, offer_id: uuid.UUID) -> RewardOffer:
    offer = db.get(RewardOffer, offer_id)
    if offer is None:
        raise NotFound("Offer not found")
    return offer


# ---- maths ----------------------------------------------------------------------------------------

def _wallet_id(db: Session, retailer_id: uuid.UUID) -> uuid.UUID | None:
    return db.scalar(select(Wallet.id).where(Wallet.owner_type == WalletOwnerType.RETAILER, Wallet.owner_id == retailer_id))


def collected(db: Session, offer: RewardOffer, retailer_id: uuid.UUID) -> int:
    wid = _wallet_id(db, retailer_id)
    if wid is None:
        return 0
    return int(db.scalar(select(func.coalesce(func.sum(WalletLedger.amount_paise), 0)).where(
        WalletLedger.wallet_id == wid, WalletLedger.entry_type.in_(COLLECTED_TYPES),
        WalletLedger.created_at >= offer.starts_at, WalletLedger.created_at < offer.ends_at)))


def balance_at_end(db: Session, offer: RewardOffer, retailer_id: uuid.UUID) -> int:
    """Balance at ends_at. A reset for an EARLIER offer that was recorded after this end still removed points
    that existed at this end, so it is subtracted too (no double cash on the same points)."""
    wid = _wallet_id(db, retailer_id)
    if wid is None:
        return 0
    return max(0, int(db.scalar(select(func.coalesce(func.sum(WalletLedger.amount_paise), 0)).where(
        WalletLedger.wallet_id == wid,
        or_(WalletLedger.created_at < offer.ends_at,
            and_(WalletLedger.entry_type == WalletEntryType.REWARD_RESET, WalletLedger.reference_id != offer.id))))))


def payout_for(offer: RewardOffer, balance: int) -> int:
    return balance * offer.percent_bp // 10000  # floor to the paisa


def standings(db: Session, offer: RewardOffer) -> list[Standing]:
    ended = clock.now() >= offer.ends_at
    rows = db.execute(select(RewardParticipant, Retailer.shop_name, Retailer.phone)
                      .join(Retailer, Retailer.id == RewardParticipant.retailer_id)
                      .where(RewardParticipant.offer_id == offer.id).order_by(RewardParticipant.joined_at)).all()
    payouts = {p.retailer_id: p for p in db.scalars(select(RewardPayout).where(RewardPayout.offer_id == offer.id))}
    out = []
    for part, shop_name, phone in rows:
        paid = payouts.get(part.retailer_id)
        got = paid.points_collected_paise if paid else collected(db, offer, part.retailer_id)
        qualifies = got >= offer.threshold_paise
        bal = pay = None
        if paid:
            bal, pay = paid.balance_at_end_paise, paid.payout_paise
        elif ended and qualifies and offer.cancelled_at is None:
            bal = balance_at_end(db, offer, part.retailer_id)
            pay = payout_for(offer, bal)
        out.append(Standing(part.retailer_id, shop_name, phone, part.joined_at, got, qualifies, bal, pay, paid))
    return out


# ---- payouts --------------------------------------------------------------------------------------

def record_payout(db: Session, user: User, offer_id: uuid.UUID, retailer_id: uuid.UUID, paid_on: date,
                  reference: str) -> RewardPayout:
    # Lock the offer: a parallel cancel_offer must either see this payout or block it (never both happen).
    offer = db.scalar(select(RewardOffer).where(RewardOffer.id == offer_id).with_for_update())
    if offer is None:
        raise NotFound("Offer not found")
    if offer.cancelled_at is not None:
        raise DomainError("This offer was cancelled", code="offer_cancelled")
    if clock.now() < offer.ends_at:
        raise DomainError("The offer has not ended yet", code="offer_not_ended")
    if db.get(Retailer, retailer_id).user_id == user.id:
        raise Forbidden("Admins cannot record a payout to their own shop", code="own_shop")
    if db.scalar(select(RewardParticipant.id).where(RewardParticipant.offer_id == offer.id,
                                                    RewardParticipant.retailer_id == retailer_id)) is None:
        raise DomainError("This retailer did not join the offer", code="not_participant")
    # Lock the wallet first: serialises payouts for this retailer, so the duplicate check below is reliable.
    wallet = wallet_service.get_wallet(db, WalletOwnerType.RETAILER, retailer_id, lock=True)
    if db.scalar(select(RewardPayout.id).where(RewardPayout.offer_id == offer.id, RewardPayout.retailer_id == retailer_id)):
        raise Conflict("Payout already recorded", code="payout_exists")
    got = collected(db, offer, retailer_id)
    if got < offer.threshold_paise:
        raise DomainError("This retailer did not reach the threshold", code="not_qualified")
    _require_earlier_offers_paid(db, offer, retailer_id)
    bal = balance_at_end(db, offer, retailer_id)
    payout = RewardPayout(offer_id=offer.id, retailer_id=retailer_id, points_collected_paise=got,
                          balance_at_end_paise=bal, payout_paise=payout_for(offer, bal), paid_on=paid_on,
                          reference=reference.strip()[:120], recorded_by_user_id=user.id)
    db.add(payout)
    db.flush()
    if bal > 0:
        wallet_service.post(db, wallet, WalletEntryType.REWARD_RESET, -bal, reference_type="reward_offer",
                            reference_id=offer.id, note=offer.name, user_id=user.id)
    retailer = db.get(Retailer, retailer_id)
    db.execute(insert(Notification).values(
        user_id=retailer.user_id, channel=NotificationChannel.IN_APP, template="reward_paid",
        payload={"offer": offer.name, "payout_paise": payout.payout_paise}, dedupe_key=f"reward:{payout.id}")
        .on_conflict_do_nothing(index_elements=["dedupe_key"]))
    db.commit()
    return payout


def _require_earlier_offers_paid(db: Session, offer: RewardOffer, retailer_id: uuid.UUID) -> None:
    """Payouts go in order, so 'balance at end' of a later offer never counts points an earlier offer will pay."""
    earlier = db.scalars(select(RewardOffer).join(RewardParticipant, and_(
        RewardParticipant.offer_id == RewardOffer.id, RewardParticipant.retailer_id == retailer_id)).where(
        RewardOffer.cancelled_at.is_(None), RewardOffer.ends_at <= offer.starts_at)).all()
    for e in earlier:
        unpaid = db.scalar(select(RewardPayout.id).where(RewardPayout.offer_id == e.id,
                                                         RewardPayout.retailer_id == retailer_id)) is None
        if unpaid and collected(db, e, retailer_id) >= e.threshold_paise:
            raise Conflict(f"Record the payout for the earlier offer '{e.name}' first", code="earlier_offer_unpaid")


# ---- retailer -------------------------------------------------------------------------------------

def current_offer(db: Session) -> RewardOffer | None:
    """The next offer that has not ended (running now, or upcoming)."""
    return db.scalar(select(RewardOffer).where(RewardOffer.cancelled_at.is_(None), RewardOffer.ends_at > clock.now())
                     .order_by(RewardOffer.starts_at).limit(1))


def is_participant(db: Session, offer: RewardOffer, retailer: Retailer) -> bool:
    return db.scalar(select(RewardParticipant.id).where(RewardParticipant.offer_id == offer.id,
                                                        RewardParticipant.retailer_id == retailer.id)) is not None


def join(db: Session, retailer: Retailer, offer_id: uuid.UUID) -> None:
    offer = get_offer(db, offer_id)
    if offer.cancelled_at is not None or clock.now() >= offer.ends_at:
        raise DomainError("This offer is closed", code="offer_closed")
    if plan_service.get_live_subscription(db, retailer.id) is None:
        raise Forbidden("An active plan is needed for this", code="subscription_required")
    db.execute(insert(RewardParticipant).values(offer_id=offer.id, retailer_id=retailer.id, joined_at=clock.now())
               .on_conflict_do_nothing(index_elements=["offer_id", "retailer_id"]))
    db.commit()


def leave(db: Session, retailer: Retailer, offer_id: uuid.UUID) -> None:
    offer = get_offer(db, offer_id)
    if clock.now() >= offer.ends_at:
        raise DomainError("This offer has ended", code="offer_closed")
    part = db.scalar(select(RewardParticipant).where(RewardParticipant.offer_id == offer.id,
                                                     RewardParticipant.retailer_id == retailer.id))
    if part is not None:
        db.delete(part)
    db.commit()


def payouts_for_retailer(db: Session, retailer: Retailer) -> list[tuple[RewardPayout, str]]:
    return list(db.execute(select(RewardPayout, RewardOffer.name).join(RewardOffer, RewardOffer.id == RewardPayout.offer_id)
                           .where(RewardPayout.retailer_id == retailer.id).order_by(RewardPayout.created_at.desc())).all())
