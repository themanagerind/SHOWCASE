import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_retailer, get_current_user
from app.db.session import get_db
from app.models import Booking, Customer, Retailer, ShopDiscountRequest, User
from app.models.enums import BookingStatus
from app.services import booking_service, customer_service

router = APIRouter(tags=["bookings"])


class BookingIn(BaseModel):
    product_id: uuid.UUID


class BookingOut(BaseModel):
    id: str
    booking_no: str
    product_id: str
    product_name: str
    price_paise: int
    discount_paise: int
    status: str
    created_at: datetime
    expires_at: datetime
    purchased_at: datetime | None
    forfeited_at: datetime | None
    cancelled_at: datetime | None
    cancel_reason: str | None
    shop_name: str | None = None
    shop_slug: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None


class CancelIn(BaseModel):
    reason: str = Field(min_length=2, max_length=200)


class DiscountIn(BaseModel):
    phone: str = Field(min_length=10, max_length=16)
    amount_paise: int = Field(gt=0, le=10_000_000)
    note: str = Field(min_length=2, max_length=120)


class DiscountOut(BaseModel):
    id: str
    amount_paise: int
    note: str
    status: str
    created_at: datetime
    expires_at: datetime
    responded_at: datetime | None
    shop_name: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None


def _booking_out(db: Session, b: Booking, for_retailer: bool) -> BookingOut:
    out = BookingOut(id=str(b.id), booking_no=b.booking_no, product_id=str(b.product_id), product_name=b.product_name,
                     price_paise=b.price_paise, discount_paise=b.discount_paise, status=b.status.value,
                     created_at=b.created_at, expires_at=b.expires_at, purchased_at=b.purchased_at,
                     forfeited_at=b.forfeited_at, cancelled_at=b.cancelled_at, cancel_reason=b.cancel_reason)
    if for_retailer:
        cu = db.get(User, db.get(Customer, b.customer_id).user_id)
        out.customer_name, out.customer_phone = cu.name, cu.phone
    else:
        r = db.get(Retailer, b.retailer_id)
        out.shop_name, out.shop_slug = r.shop_name, r.slug
    return out


def _discount_out(db: Session, r: ShopDiscountRequest, for_retailer: bool) -> DiscountOut:
    out = DiscountOut(id=str(r.id), amount_paise=r.amount_paise, note=r.note, status=r.status.value,
                      created_at=r.created_at, expires_at=r.expires_at, responded_at=r.responded_at)
    if for_retailer:
        # Only who and how much — never the customer's wallet balance (SPEC 4.4a).
        cu = db.get(User, db.get(Customer, r.customer_id).user_id)
        out.customer_name, out.customer_phone = cu.name, cu.phone
    else:
        out.shop_name = db.get(Retailer, r.retailer_id).shop_name
    return out


# ---- customer -------------------------------------------------------------------------------------

@router.post("/bookings", response_model=BookingOut, status_code=201)
def reserve(body: BookingIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = customer_service.get_customer(db, user)
    return _booking_out(db, booking_service.reserve(db, customer, body.product_id), False)


@router.get("/bookings/me", response_model=list[BookingOut])
def my_bookings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = customer_service.get_customer(db, user)
    return [_booking_out(db, b, False) for b in booking_service.list_for_customer(db, customer)]


@router.post("/bookings/{booking_id}/purchased", response_model=BookingOut)
def purchased(booking_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = customer_service.get_customer(db, user)
    return _booking_out(db, booking_service.confirm_purchase(db, customer, booking_id), False)


@router.get("/shop-discounts/me", response_model=list[DiscountOut])
def my_discount_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = customer_service.get_customer(db, user)
    return [_discount_out(db, r, False) for r in booking_service.pending_discounts_for_customer(db, customer)]


@router.post("/shop-discounts/{request_id}/accept", response_model=DiscountOut)
def accept_discount(request_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = customer_service.get_customer(db, user)
    return _discount_out(db, booking_service.respond_to_discount(db, customer, request_id, True), False)


@router.post("/shop-discounts/{request_id}/decline", response_model=DiscountOut)
def decline_discount(request_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = customer_service.get_customer(db, user)
    return _discount_out(db, booking_service.respond_to_discount(db, customer, request_id, False), False)


# ---- retailer -------------------------------------------------------------------------------------

@router.get("/retailers/me/bookings", response_model=list[BookingOut])
def retailer_bookings(status: BookingStatus | None = None, retailer: Retailer = Depends(get_current_retailer),
                      db: Session = Depends(get_db)):
    return [_booking_out(db, b, True) for b in booking_service.list_for_retailer(db, retailer, status)]


@router.post("/retailers/me/bookings/{booking_id}/cancel", response_model=BookingOut)
def retailer_cancel(booking_id: uuid.UUID, body: CancelIn, retailer: Retailer = Depends(get_current_retailer),
                    db: Session = Depends(get_db)):
    return _booking_out(db, booking_service.cancel_by_retailer(db, retailer, booking_id, body.reason.strip()), True)


@router.post("/retailers/me/shop-discounts", response_model=DiscountOut, status_code=201)
def retailer_create_discount(body: DiscountIn, user: User = Depends(get_current_user),
                             retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    req = booking_service.create_discount_request(db, retailer, user, body.phone, body.amount_paise, body.note)
    return _discount_out(db, req, True)


@router.get("/retailers/me/shop-discounts", response_model=list[DiscountOut])
def retailer_discounts(retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    return [_discount_out(db, r, True) for r in booking_service.discounts_for_retailer(db, retailer)]
