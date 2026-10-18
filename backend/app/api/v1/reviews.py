"""Ratings and reviews (SPEC 4.7)."""
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_retailer, get_current_user, require_admin
from app.db.session import get_db
from app.models import AdminUser, Customer, Retailer, Review, User
from app.models.enums import ReviewSource
from app.services import customer_service, retailer_service, review_service

router = APIRouter(tags=["reviews"])
any_admin = require_admin()


class ReviewIn(BaseModel):
    source_type: Literal["BOOKING", "SHOP_DISCOUNT"]
    source_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)


class ReviewOut(BaseModel):
    id: str
    rating: int
    comment: str | None
    author: str  # "Ravi V."
    created_at: datetime
    updated_at: datetime


class OwnReviewOut(ReviewOut):
    is_flagged: bool
    flag_reason: str | None
    is_hidden: bool
    resolved: bool


class RateableOut(BaseModel):
    source_type: str
    source_id: str
    shop_name: str
    label: str
    purchased_at: datetime
    rating: int | None
    comment: str | None


class ShopReviewsOut(BaseModel):
    rating_avg: float
    rating_count: int
    reviews: list[ReviewOut]


class FlagIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ResolveIn(BaseModel):
    action: Literal["HIDE", "KEEP"]


class FlaggedOut(OwnReviewOut):
    shop_name: str


def _out(r: Review, author: str) -> ReviewOut:
    return ReviewOut(id=str(r.id), rating=r.rating, comment=r.comment, author=author, created_at=r.created_at,
                     updated_at=r.updated_at)


def _author(db: Session, r: Review) -> str:
    return review_service.public_name(db.get(User, db.get(Customer, r.customer_id).user_id).name)


def _own(r: Review, author: str) -> dict:
    return {**_out(r, author).model_dump(), "is_flagged": r.is_flagged, "flag_reason": r.flag_reason,
            "is_hidden": r.is_hidden, "resolved": r.resolved_at is not None}


# ---- customer -------------------------------------------------------------------------------------

@router.get("/reviews/me/rateable", response_model=list[RateableOut])
def rateable(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = review_service.rateable(db, customer_service.get_customer(db, user))
    names = {r.id: r.shop_name for r in db.query(Retailer).filter(Retailer.id.in_({i.retailer_id for i in items}))} if items else {}
    return [RateableOut(source_type=i.source_type.value, source_id=str(i.source_id), shop_name=names[i.retailer_id],
                        label=i.label, purchased_at=i.purchased_at, rating=i.review.rating if i.review else None,
                        comment=i.review.comment if i.review else None) for i in items]


@router.post("/reviews", response_model=ReviewOut)
def submit(body: ReviewIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    r = review_service.submit(db, customer_service.get_customer(db, user), ReviewSource(body.source_type),
                              body.source_id, body.rating, body.comment)
    return _out(r, review_service.public_name(user.name))


# ---- retailer -------------------------------------------------------------------------------------

@router.get("/retailers/me/reviews", response_model=list[OwnReviewOut])
def my_reviews(retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    return [OwnReviewOut(**_own(r, a)) for r, a in review_service.list_for_retailer(db, retailer)]


@router.post("/retailers/me/reviews/{review_id}/flag", response_model=OwnReviewOut)
def flag(review_id: uuid.UUID, body: FlagIn, retailer: Retailer = Depends(get_current_retailer),
         db: Session = Depends(get_db)):
    r = review_service.flag(db, retailer, review_id, body.reason)
    return OwnReviewOut(**_own(r, _author(db, r)))


# ---- admin ----------------------------------------------------------------------------------------

@router.get("/admin/reviews/flagged", response_model=list[FlaggedOut])
def flagged(_: AdminUser = Depends(any_admin), db: Session = Depends(get_db)):
    return [FlaggedOut(**_own(r, a), shop_name=shop) for r, a, shop in review_service.flagged_queue(db)]


@router.post("/admin/reviews/{review_id}/resolve", response_model=OwnReviewOut)
def resolve(review_id: uuid.UUID, body: ResolveIn, admin: AdminUser = Depends(any_admin), db: Session = Depends(get_db)):
    r = review_service.resolve(db, db.get(User, admin.user_id), review_id, body.action == "HIDE")
    return OwnReviewOut(**_own(r, _author(db, r)))


# Public route last: "/retailers/me/reviews" above must not be read as slug "me".
@router.get("/retailers/{slug}/reviews", response_model=ShopReviewsOut)
def shop_reviews(slug: str, db: Session = Depends(get_db)):
    retailer = retailer_service.get_public(db, slug)
    return ShopReviewsOut(rating_avg=float(retailer.rating_avg), rating_count=retailer.rating_count,
                          reviews=[_out(r, a) for r, a in review_service.list_public(db, retailer)])
