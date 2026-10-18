"""Ratings and reviews (SPEC 4.7).

A customer may rate a shop once per completed purchase — a booking they marked "I bought it" or a confirmed
discount on an unlisted item — within 30 days, and may change it within the same 30 days. Retailers flag
abusive reviews; an admin hides (out of the page and the average) or keeps them.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import DomainError, NotFound
from app.models import Booking, Customer, Retailer, Review, ShopDiscountRequest, User
from app.models.enums import BookingStatus, DiscountRequestStatus, ReviewSource

WINDOW = timedelta(days=30)


@dataclass
class Purchase:
    source_type: ReviewSource
    source_id: uuid.UUID
    retailer_id: uuid.UUID
    label: str  # product name / item note
    purchased_at: datetime
    review: Review | None


def _purchase(db: Session, customer: Customer, source_type: ReviewSource, source_id: uuid.UUID) -> Purchase:
    if source_type == ReviewSource.BOOKING:
        b = db.get(Booking, source_id)
        if b is None or b.customer_id != customer.id or b.status != BookingStatus.PURCHASED:
            raise NotFound("Purchase not found", code="purchase_not_found")
        return Purchase(source_type, b.id, b.retailer_id, b.product_name, b.purchased_at, None)
    if source_type == ReviewSource.SHOP_DISCOUNT:
        r = db.get(ShopDiscountRequest, source_id)
        if r is None or r.customer_id != customer.id or r.status != DiscountRequestStatus.CONFIRMED:
            raise NotFound("Purchase not found", code="purchase_not_found")
        return Purchase(source_type, r.id, r.retailer_id, r.note, r.responded_at, None)
    raise DomainError("This purchase type cannot be rated", code="purchase_not_found")


def rateable(db: Session, customer: Customer) -> list[Purchase]:
    """Purchases of the last 30 days, with the existing review if any (for 'Rate your purchase')."""
    since = clock.now() - WINDOW
    items = [Purchase(ReviewSource.BOOKING, b.id, b.retailer_id, b.product_name, b.purchased_at, None)
             for b in db.scalars(select(Booking).where(Booking.customer_id == customer.id,
                                                       Booking.status == BookingStatus.PURCHASED,
                                                       Booking.purchased_at > since))]
    items += [Purchase(ReviewSource.SHOP_DISCOUNT, r.id, r.retailer_id, r.note, r.responded_at, None)
              for r in db.scalars(select(ShopDiscountRequest).where(
                  ShopDiscountRequest.customer_id == customer.id,
                  ShopDiscountRequest.status == DiscountRequestStatus.CONFIRMED,
                  ShopDiscountRequest.responded_at > since))]
    reviews = {(r.source_type, r.source_id): r for r in db.scalars(select(Review).where(
        Review.customer_id == customer.id, Review.source_id.in_([i.source_id for i in items])))} if items else {}
    for i in items:
        i.review = reviews.get((i.source_type, i.source_id))
    return sorted(items, key=lambda i: i.purchased_at, reverse=True)


def submit(db: Session, customer: Customer, source_type: ReviewSource, source_id: uuid.UUID, rating: int,
           comment: str | None) -> Review:
    if not 1 <= rating <= 5:
        raise DomainError("Rating must be 1 to 5", code="invalid_rating")
    p = _purchase(db, customer, source_type, source_id)
    if clock.now() >= p.purchased_at + WINDOW:
        raise DomainError("Purchases can be rated within 30 days", code="review_window_closed")
    retailer = db.get(Retailer, p.retailer_id)
    if retailer.user_id == customer.user_id:
        raise DomainError("You cannot rate your own shop", code="own_shop")
    comment = (comment or "").strip()[:1000] or None
    review = db.scalar(select(Review).where(Review.source_type == source_type, Review.source_id == source_id)
                       .with_for_update())
    if review is None:
        review = Review(customer_id=customer.id, retailer_id=p.retailer_id, source_type=source_type,
                        source_id=source_id, purchased_at=p.purchased_at, rating=rating, comment=comment)
        db.add(review)
    else:  # edit within the window; a hidden review stays hidden
        review.rating, review.comment = rating, comment
    db.flush()
    recompute(db, p.retailer_id)
    db.commit()
    return review


def recompute(db: Session, retailer_id: uuid.UUID) -> None:
    count, avg = db.execute(select(func.count(), func.avg(Review.rating)).where(
        Review.retailer_id == retailer_id, Review.is_hidden.is_(False))).one()
    retailer = db.get(Retailer, retailer_id)
    retailer.rating_count = count
    retailer.rating_avg = Decimal(avg or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def public_name(name: str | None) -> str:
    """'Ravi Kumar Verma' -> 'Ravi V.'; no name -> 'Customer'. The phone number is never shown."""
    parts = (name or "").split()
    if not parts:
        return "Customer"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0].upper()}."


def list_public(db: Session, retailer: Retailer, limit: int = 20) -> list[tuple[Review, str]]:
    rows = db.execute(select(Review, User.name).join(Customer, Customer.id == Review.customer_id)
                      .join(User, User.id == Customer.user_id)
                      .where(Review.retailer_id == retailer.id, Review.is_hidden.is_(False))
                      .order_by(Review.created_at.desc()).limit(limit)).all()
    return [(r, public_name(n)) for r, n in rows]


def list_for_retailer(db: Session, retailer: Retailer) -> list[tuple[Review, str]]:
    rows = db.execute(select(Review, User.name).join(Customer, Customer.id == Review.customer_id)
                      .join(User, User.id == Customer.user_id)
                      .where(Review.retailer_id == retailer.id).order_by(Review.created_at.desc()).limit(200)).all()
    return [(r, public_name(n)) for r, n in rows]


def flag(db: Session, retailer: Retailer, review_id: uuid.UUID, reason: str) -> Review:
    review = db.get(Review, review_id)
    if review is None or review.retailer_id != retailer.id:
        raise NotFound("Review not found")
    if review.resolved_at is not None:
        raise DomainError("An admin has already checked this review", code="review_resolved")
    review.is_flagged, review.flag_reason, review.flagged_at = True, reason.strip()[:500], clock.now()
    db.commit()
    return review


def flagged_queue(db: Session) -> list[tuple[Review, str, str]]:
    rows = db.execute(select(Review, User.name, Retailer.shop_name).join(Customer, Customer.id == Review.customer_id)
                      .join(User, User.id == Customer.user_id).join(Retailer, Retailer.id == Review.retailer_id)
                      .where(Review.is_flagged.is_(True), Review.resolved_at.is_(None))
                      .order_by(Review.flagged_at)).all()
    return [(r, public_name(n), shop) for r, n, shop in rows]


def resolve(db: Session, user: User, review_id: uuid.UUID, hide: bool) -> Review:
    review = db.scalar(select(Review).where(Review.id == review_id).with_for_update())
    if review is None or not review.is_flagged:
        raise NotFound("Flagged review not found")
    if review.resolved_at is not None:
        raise DomainError("Already resolved", code="review_resolved")
    review.is_hidden, review.resolved_at, review.resolved_by_user_id = hide, clock.now(), user.id
    db.flush()
    recompute(db, review.retailer_id)
    db.commit()
    return review
