"""Retailer reward offers (SPEC 4.5). Admin: create/cancel (SUPER_ADMIN), record payouts (any admin). Retailer: join/leave."""
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.orm import Session

from app.core import clock
from app.core.dependencies import get_current_retailer, require_admin
from app.db.session import get_db
from app.models import AdminUser, Retailer, RewardOffer, RewardPayout, User
from app.services import reward_service

router = APIRouter(tags=["rewards"])
any_admin = require_admin()
super_admin = require_admin(super_admin=True)


class OfferIn(BaseModel):
    name: str = Field(min_length=3, max_length=120)
    starts_at: AwareDatetime  # a time without a zone is refused (422) instead of crashing
    ends_at: AwareDatetime
    threshold_paise: int = Field(gt=0, le=10**12)
    percent_bp: int = Field(gt=0, le=10000)


class OfferOut(BaseModel):
    id: str
    name: str
    starts_at: datetime
    ends_at: datetime
    threshold_paise: int
    percent_bp: int
    status: str  # UPCOMING | RUNNING | ENDED | CANCELLED
    created_at: datetime


class PayoutOut(BaseModel):
    offer_id: str
    offer_name: str | None = None
    retailer_id: str
    points_collected_paise: int
    balance_at_end_paise: int
    payout_paise: int
    paid_on: date
    reference: str
    created_at: datetime


class StandingOut(BaseModel):
    retailer_id: str
    shop_name: str
    phone: str | None
    joined_at: datetime
    collected_paise: int
    qualifies: bool
    balance_at_end_paise: int | None
    payout_paise: int | None
    payout: PayoutOut | None


class OfferDetail(BaseModel):
    offer: OfferOut
    standings: list[StandingOut]


class PayoutIn(BaseModel):
    retailer_id: uuid.UUID
    paid_on: date
    reference: str = Field(min_length=2, max_length=120)


class MyOfferOut(BaseModel):
    offer: OfferOut | None
    joined: bool
    collected_paise: int
    payouts: list[PayoutOut]


def offer_out(o: RewardOffer) -> OfferOut:
    now = clock.now()
    status = ("CANCELLED" if o.cancelled_at else "ENDED" if now >= o.ends_at else
              "RUNNING" if now >= o.starts_at else "UPCOMING")
    return OfferOut(id=str(o.id), name=o.name, starts_at=o.starts_at, ends_at=o.ends_at,
                    threshold_paise=o.threshold_paise, percent_bp=o.percent_bp, status=status, created_at=o.created_at)


def payout_out(p: RewardPayout, name: str | None = None) -> PayoutOut:
    return PayoutOut(offer_id=str(p.offer_id), offer_name=name, retailer_id=str(p.retailer_id),
                     points_collected_paise=p.points_collected_paise, balance_at_end_paise=p.balance_at_end_paise,
                     payout_paise=p.payout_paise, paid_on=p.paid_on, reference=p.reference, created_at=p.created_at)


def _detail(db: Session, offer: RewardOffer) -> OfferDetail:
    return OfferDetail(offer=offer_out(offer), standings=[
        StandingOut(retailer_id=str(s.retailer_id), shop_name=s.shop_name, phone=s.phone, joined_at=s.joined_at,
                    collected_paise=s.collected_paise, qualifies=s.qualifies, balance_at_end_paise=s.balance_at_end_paise,
                    payout_paise=s.payout_paise, payout=payout_out(s.payout) if s.payout else None)
        for s in reward_service.standings(db, offer)])


# ---- admin ----------------------------------------------------------------------------------------

@router.get("/admin/reward-offers", response_model=list[OfferOut])
def list_offers(_: AdminUser = Depends(any_admin), db: Session = Depends(get_db)):
    return [offer_out(o) for o in reward_service.list_offers(db)]


@router.post("/admin/reward-offers", response_model=OfferOut, status_code=201)
def create_offer(body: OfferIn, admin: AdminUser = Depends(super_admin), db: Session = Depends(get_db)):
    o = reward_service.create_offer(db, db.get(User, admin.user_id), body.name, body.starts_at, body.ends_at,
                                    body.threshold_paise, body.percent_bp)
    return offer_out(o)


@router.get("/admin/reward-offers/{offer_id}", response_model=OfferDetail)
def offer_detail(offer_id: uuid.UUID, _: AdminUser = Depends(any_admin), db: Session = Depends(get_db)):
    return _detail(db, reward_service.get_offer(db, offer_id))


@router.post("/admin/reward-offers/{offer_id}/cancel", response_model=OfferOut)
def cancel_offer(offer_id: uuid.UUID, admin: AdminUser = Depends(super_admin), db: Session = Depends(get_db)):
    return offer_out(reward_service.cancel_offer(db, db.get(User, admin.user_id), offer_id))


@router.post("/admin/reward-offers/{offer_id}/payouts", response_model=OfferDetail, status_code=201)
def record_payout(offer_id: uuid.UUID, body: PayoutIn, admin: AdminUser = Depends(any_admin),
                  db: Session = Depends(get_db)):
    reward_service.record_payout(db, db.get(User, admin.user_id), offer_id, body.retailer_id, body.paid_on, body.reference)
    return _detail(db, reward_service.get_offer(db, offer_id))


# ---- retailer -------------------------------------------------------------------------------------

@router.get("/retailers/me/reward-offer", response_model=MyOfferOut)
def my_offer(retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    o = reward_service.current_offer(db)
    payouts = [payout_out(p, name) for p, name in reward_service.payouts_for_retailer(db, retailer)]
    if o is None:
        return MyOfferOut(offer=None, joined=False, collected_paise=0, payouts=payouts)
    return MyOfferOut(offer=offer_out(o), joined=reward_service.is_participant(db, o, retailer),
                      collected_paise=reward_service.collected(db, o, retailer.id), payouts=payouts)


@router.post("/retailers/me/reward-offers/{offer_id}/join", response_model=MyOfferOut)
def join(offer_id: uuid.UUID, retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    reward_service.join(db, retailer, offer_id)
    return my_offer(retailer, db)


@router.post("/retailers/me/reward-offers/{offer_id}/leave", response_model=MyOfferOut)
def leave(offer_id: uuid.UUID, retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    reward_service.leave(db, retailer, offer_id)
    return my_offer(retailer, db)
