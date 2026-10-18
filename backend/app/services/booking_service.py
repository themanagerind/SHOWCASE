"""Bookings with wallet points (SPEC 4.4) and retailer discounts on unlisted items (SPEC 4.4a).

Money rules (all through wallet_service.post, so balances never go negative and every move is in the ledger):
  reserve            customer  -discount   (BOOKING_HOLD)        + 1 unit of stock held
  customer "bought"  retailer  +discount   (BOOKING_PURCHASED)   stock stays consumed
  24h passed         customer   0          (BOOKING_FORFEITED)   points vanish, stock released
  retailer cancels   customer  +discount   (BOOKING_CANCEL_REFUND) stock released
  unlisted item      customer  -amount / retailer +amount (SHOP_DISCOUNT / SHOP_DISCOUNT_RECEIVED), customer confirms
"""
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import DomainError, Forbidden, NotFound
from app.core.phone import normalize_indian_mobile
from app.models import Booking, Customer, Notification, Product, Retailer, ShopDiscountRequest, User
from app.models.enums import (
    BookingStatus,
    DiscountRequestStatus,
    NotificationChannel,
    ShopEventType,
    WalletEntryType,
    WalletOwnerType,
)
from app.services import analytics_service, plan_service, wallet_service

BOOKING_VALIDITY = timedelta(hours=24)
DISCOUNT_REQUEST_VALIDITY = timedelta(minutes=30)
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I confusion when read aloud at the counter


def _notify(db: Session, user_id, template: str, payload: dict, dedupe_key: str) -> None:
    db.execute(insert(Notification).values(user_id=user_id, channel=NotificationChannel.IN_APP, template=template,
                                           payload=payload, dedupe_key=dedupe_key)
               .on_conflict_do_nothing(index_elements=["dedupe_key"]))


def _booking_no() -> str:
    return "B" + "".join(secrets.choice(_ALPHABET) for _ in range(7))


def _customer_wallet(db: Session, customer_id):
    return wallet_service.get_wallet(db, WalletOwnerType.CUSTOMER, customer_id, lock=True)


def _retailer_wallet(db: Session, retailer_id):
    return wallet_service.get_wallet(db, WalletOwnerType.RETAILER, retailer_id, lock=True)


# ---- bookings -----------------------------------------------------------------------------------

def reserve(db: Session, customer: Customer, product_id: uuid.UUID) -> Booking:
    now = clock.now()
    product = db.scalar(select(Product).where(Product.id == product_id).with_for_update())
    if product is None or not product.is_active or product.deleted_at is not None:
        raise NotFound("Product not found")
    retailer = db.get(Retailer, product.retailer_id)
    if plan_service.get_live_subscription(db, retailer.id) is None:
        raise Forbidden("This shop is not taking bookings right now", code="shop_not_live")
    if retailer.user_id == customer.user_id:
        raise DomainError("You cannot book from your own shop", code="own_shop")
    if product.stock_qty < 1:
        raise DomainError("This product is out of stock", code="out_of_stock")
    discount = product.wallet_discount_paise
    wallet = _customer_wallet(db, customer.id)
    if wallet.balance_paise < discount:
        raise DomainError("Not enough points in your wallet", code="insufficient_points")
    booking = Booking(
        booking_no=_booking_no(), customer_id=customer.id, retailer_id=retailer.id, product_id=product.id,
        product_name=product.name, price_paise=product.price_paise, discount_paise=discount,
        status=BookingStatus.RESERVED, expires_at=now + BOOKING_VALIDITY,
    )
    db.add(booking)
    db.flush()
    wallet_service.post(db, wallet, WalletEntryType.BOOKING_HOLD, -discount, reference_type="booking",
                        reference_id=booking.id, note=f"{booking.booking_no} · {product.name}", user_id=customer.user_id)
    product.stock_qty -= 1
    analytics_service.record(db, retailer.id, ShopEventType.BOOKING_START, customer_id=customer.id,
                             meta={"product_id": str(product.id)})
    _notify(db, retailer.user_id, "booking_reserved", {"booking_no": booking.booking_no, "product": product.name},
            f"booking:{booking.id}:reserved")
    db.commit()
    return booking


def _lock_booking(db: Session, booking_id: uuid.UUID) -> Booking | None:
    return db.scalar(select(Booking).where(Booking.id == booking_id).with_for_update()
                     .execution_options(populate_existing=True))


def _release_stock(db: Session, booking: Booking) -> None:
    product = db.scalar(select(Product).where(Product.id == booking.product_id).with_for_update())
    if product is not None:
        product.stock_qty += 1


def _forfeit(db: Session, booking: Booking, now: datetime) -> None:
    booking.status, booking.forfeited_at = BookingStatus.FORFEITED, now
    _release_stock(db, booking)
    wallet_service.post(db, _customer_wallet(db, booking.customer_id), WalletEntryType.BOOKING_FORFEITED, 0,
                        reference_type="booking", reference_id=booking.id,
                        note=f"{booking.booking_no} · {booking.product_name}")
    _notify(db, db.get(Customer, booking.customer_id).user_id, "booking_forfeited",
            {"booking_no": booking.booking_no}, f"booking:{booking.id}:forfeited")


def confirm_purchase(db: Session, customer: Customer, booking_id: uuid.UUID) -> Booking:
    """Only the CUSTOMER can confirm ("I bought it"), so a retailer cannot claim points for a sale that
    did not happen (SPEC 4.4). Works even if the shop's plan has since expired (SPEC 5 matrix)."""
    now = clock.now()
    booking = _lock_booking(db, booking_id)
    if booking is None or booking.customer_id != customer.id:
        raise NotFound("Booking not found")
    if booking.status == BookingStatus.PURCHASED:
        return booking  # double tap is harmless
    if booking.status != BookingStatus.RESERVED:
        raise DomainError("This booking can no longer be completed", code="booking_closed")
    if now >= booking.expires_at:
        _forfeit(db, booking, now)
        db.commit()
        raise DomainError("This booking has expired", code="booking_expired")
    booking.status, booking.purchased_at = BookingStatus.PURCHASED, now
    analytics_service.record(db, booking.retailer_id, ShopEventType.BOOKING_CONFIRMED, customer_id=customer.id,
                             meta={"product_id": str(booking.product_id)})
    wallet_service.post(db, _retailer_wallet(db, booking.retailer_id), WalletEntryType.BOOKING_PURCHASED,
                        booking.discount_paise, reference_type="booking", reference_id=booking.id,
                        note=f"{booking.booking_no} · {booking.product_name}", user_id=customer.user_id)
    _notify(db, db.get(Retailer, booking.retailer_id).user_id, "booking_purchased",
            {"booking_no": booking.booking_no, "points": booking.discount_paise}, f"booking:{booking.id}:purchased")
    db.commit()
    return booking


def cancel_by_retailer(db: Session, retailer: Retailer, booking_id: uuid.UUID, reason: str) -> Booking:
    """e.g. out of stock: the customer did nothing wrong, so the points come back (SPEC 4.4)."""
    now = clock.now()
    booking = _lock_booking(db, booking_id)
    if booking is None or booking.retailer_id != retailer.id:
        raise NotFound("Booking not found")
    if booking.status != BookingStatus.RESERVED:
        raise DomainError("Only open bookings can be cancelled", code="booking_closed")
    if now >= booking.expires_at:
        _forfeit(db, booking, now)
        db.commit()
        raise DomainError("This booking has already expired", code="booking_expired")
    booking.status, booking.cancelled_at, booking.cancel_reason = BookingStatus.CANCELLED_BY_RETAILER, now, reason
    _release_stock(db, booking)
    wallet_service.post(db, _customer_wallet(db, booking.customer_id), WalletEntryType.BOOKING_CANCEL_REFUND,
                        booking.discount_paise, reference_type="booking", reference_id=booking.id,
                        note=f"{booking.booking_no} · {reason}", user_id=retailer.user_id)
    _notify(db, db.get(Customer, booking.customer_id).user_id, "booking_cancelled",
            {"booking_no": booking.booking_no, "reason": reason}, f"booking:{booking.id}:cancelled")
    db.commit()
    return booking


def forfeit_expired(db: Session, now: datetime | None = None) -> int:
    """Job (every 5 minutes): RESERVED bookings past 24h are forfeited. Idempotent."""
    now = now or clock.now()
    ids = db.scalars(select(Booking.id).where(Booking.status == BookingStatus.RESERVED, Booking.expires_at <= now)).all()
    done = 0
    for bid in ids:
        booking = _lock_booking(db, bid)
        if booking.status == BookingStatus.RESERVED and booking.expires_at <= now:
            _forfeit(db, booking, now)
            done += 1
        db.commit()
    return done


def has_open_booking(db: Session, customer_id: uuid.UUID, retailer_id: uuid.UUID) -> bool:
    """RESERVED and still inside its 24h (the forfeit job may run a few minutes late)."""
    return db.scalar(select(Booking.id).where(
        Booking.customer_id == customer_id, Booking.retailer_id == retailer_id,
        Booking.status == BookingStatus.RESERVED, Booking.expires_at > clock.now()).limit(1)) is not None


def limited_view(db: Session, customer: Customer, slug: str) -> tuple[Retailer, list[Booking]]:
    """SPEC 5: a shop's contact details + the customer's open bookings, even if the shop's plan expired —
    but only while the customer has an open booking there."""
    retailer = db.scalar(select(Retailer).where(Retailer.slug == slug, Retailer.deleted_at.is_(None)))
    if retailer is None or not has_open_booking(db, customer.id, retailer.id):
        raise NotFound("Shop not found")
    open_ = [b for b in list_for_customer(db, customer, BookingStatus.RESERVED)
             if b.retailer_id == retailer.id and b.expires_at > clock.now()]
    return retailer, open_


def list_for_customer(db: Session, customer: Customer, status: BookingStatus | None = None) -> list[Booking]:
    q = select(Booking).where(Booking.customer_id == customer.id)
    if status:
        q = q.where(Booking.status == status)
    return list(db.scalars(q.order_by(Booking.created_at.desc()).limit(100)))


def list_for_retailer(db: Session, retailer: Retailer, status: BookingStatus | None = None) -> list[Booking]:
    q = select(Booking).where(Booking.retailer_id == retailer.id)
    if status:
        q = q.where(Booking.status == status)
    return list(db.scalars(q.order_by(Booking.created_at.desc()).limit(200)))


# ---- discounts on unlisted items (SPEC 4.4a) ----------------------------------------------------

def create_discount_request(db: Session, retailer: Retailer, user: User, phone: str, amount_paise: int,
                            note: str) -> ShopDiscountRequest:
    if plan_service.get_live_subscription(db, retailer.id) is None:
        raise Forbidden("An active plan is needed for this", code="subscription_required")
    if amount_paise <= 0:
        raise DomainError("Amount must be more than 0", code="invalid_amount")
    customer = db.scalar(select(Customer).join(User, User.id == Customer.user_id).where(
        User.phone == normalize_indian_mobile(phone), Customer.deleted_at.is_(None)))
    if customer is None:
        raise NotFound("No Showcase customer with this number", code="customer_not_found")
    if customer.user_id == retailer.user_id:
        raise DomainError("You cannot give a discount to yourself", code="own_shop")
    req = ShopDiscountRequest(retailer_id=retailer.id, customer_id=customer.id, amount_paise=amount_paise,
                              note=note.strip()[:120], status=DiscountRequestStatus.PENDING,
                              expires_at=clock.now() + DISCOUNT_REQUEST_VALIDITY, created_by_user_id=user.id)
    db.add(req)
    db.flush()
    _notify(db, customer.user_id, "shop_discount_request",
            {"shop": retailer.shop_name, "amount_paise": amount_paise, "note": req.note}, f"discount:{req.id}:new")
    db.commit()
    return req


def respond_to_discount(db: Session, customer: Customer, request_id: uuid.UUID, accept: bool) -> ShopDiscountRequest:
    now = clock.now()
    req = db.scalar(select(ShopDiscountRequest).where(ShopDiscountRequest.id == request_id).with_for_update()
                    .execution_options(populate_existing=True))
    if req is None or req.customer_id != customer.id:
        raise NotFound("Request not found")
    if req.status != DiscountRequestStatus.PENDING:
        raise DomainError("This request is already closed", code="request_closed")
    if now >= req.expires_at:
        req.status = DiscountRequestStatus.EXPIRED
        db.commit()
        raise DomainError("This request has expired", code="request_expired")
    if not accept:
        req.status, req.responded_at = DiscountRequestStatus.DECLINED, now
        db.commit()
        return req
    retailer = db.get(Retailer, req.retailer_id)
    # Lock in a fixed order (customer, then retailer) — same as bookings — to avoid deadlocks.
    cw = _customer_wallet(db, customer.id)
    if cw.balance_paise < req.amount_paise:
        raise DomainError("Not enough points in your wallet", code="insufficient_points")
    wallet_service.post(db, cw, WalletEntryType.SHOP_DISCOUNT, -req.amount_paise, reference_type="shop_discount",
                        reference_id=req.id, note=f"{retailer.shop_name} · {req.note}", user_id=customer.user_id)
    wallet_service.post(db, _retailer_wallet(db, retailer.id), WalletEntryType.SHOP_DISCOUNT_RECEIVED, req.amount_paise,
                        reference_type="shop_discount", reference_id=req.id, note=req.note, user_id=customer.user_id)
    req.status, req.responded_at = DiscountRequestStatus.CONFIRMED, now
    db.commit()
    return req


def pending_discounts_for_customer(db: Session, customer: Customer) -> list[ShopDiscountRequest]:
    return list(db.scalars(select(ShopDiscountRequest).where(
        ShopDiscountRequest.customer_id == customer.id, ShopDiscountRequest.status == DiscountRequestStatus.PENDING,
        ShopDiscountRequest.expires_at > clock.now()).order_by(ShopDiscountRequest.created_at.desc())))


def discounts_for_retailer(db: Session, retailer: Retailer) -> list[ShopDiscountRequest]:
    return list(db.scalars(select(ShopDiscountRequest).where(ShopDiscountRequest.retailer_id == retailer.id)
                           .order_by(ShopDiscountRequest.created_at.desc()).limit(50)))


def expire_discount_requests(db: Session, now: datetime | None = None) -> int:
    now = now or clock.now()
    reqs = db.scalars(select(ShopDiscountRequest).where(
        ShopDiscountRequest.status == DiscountRequestStatus.PENDING, ShopDiscountRequest.expires_at <= now)).all()
    for r in reqs:
        r.status = DiscountRequestStatus.EXPIRED
    db.commit()
    return len(reqs)
