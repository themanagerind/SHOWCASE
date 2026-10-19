"""Shop analytics (SPEC 4.9).

Events: favourite_add, booking_start and booking_confirmed are recorded here by the backend (they cannot be
faked from a browser); shop_view, product_view, whatsapp_click and call_click come from the browser via
track(). A visitor is the logged-in customer, else a random per-browser anon_id. No location is stored.
"""
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from redis import Redis
from sqlalchemy import String, and_, cast, delete, func, select
from sqlalchemy.orm import Session

from app.core import clock, rate_limit
from app.core.dates import add_months
from app.core.errors import DomainError
from app.models import Customer, Product, Retailer, ShopEvent, User
from app.models.enums import ShopEventType
from app.services import plan_service

IST = ZoneInfo("Asia/Kolkata")
BROWSER_EVENTS = {ShopEventType.SHOP_VIEW, ShopEventType.PRODUCT_VIEW, ShopEventType.WHATSAPP_CLICK,
                  ShopEventType.CALL_CLICK}
DEDUPE = timedelta(minutes=30)  # same visitor, same shop/event (or product) -> counted once per 30 minutes
RETENTION_MONTHS = 13
_ANON = re.compile(r"^[A-Za-z0-9\-]{8,64}$")


def record(db: Session, retailer_id: uuid.UUID, event_type: ShopEventType, *, customer_id: uuid.UUID | None = None,
           anon_id: str | None = None, meta: dict | None = None) -> None:
    """Adds the event to the caller's transaction (the caller commits)."""
    db.add(ShopEvent(retailer_id=retailer_id, event_type=event_type, customer_id=customer_id, anon_id=anon_id,
                     meta=meta or {}, created_at=clock.now()))


def track(db: Session, redis: Redis, retailer: Retailer, event_type: ShopEventType, user: User | None,
          anon_id: str | None, product_id: uuid.UUID | None, ip: str = "unknown") -> bool:
    """Browser event. Returns False when it was not counted (own shop, duplicate)."""
    if event_type not in BROWSER_EVENTS:
        raise DomainError("This event cannot be sent from the browser", code="invalid_event")
    if anon_id is not None and not _ANON.match(anon_id):
        raise DomainError("Bad visitor id", code="invalid_event")
    if user is not None and user.id == retailer.user_id:
        return False  # the retailer's own visits don't count
    customer_id = db.scalar(select(Customer.id).where(Customer.user_id == user.id)) if user else None
    # Separate namespaces: an anon_id set to someone's customer id must not count (or rate-limit) as them.
    visitor = f"c:{customer_id}" if customer_id else (f"a:{anon_id}" if anon_id else None)
    if visitor is None:
        raise DomainError("Visitor id required", code="invalid_event")
    rate_limit.hit(redis, "events", visitor, 300, 3600)
    rate_limit.hit(redis, "events_ip", ip, 600, 3600)  # a fresh anon_id per request must not bypass the cap
    meta = {}
    if event_type == ShopEventType.PRODUCT_VIEW:
        if product_id is None or db.scalar(select(Product.id).where(
                Product.id == product_id, Product.retailer_id == retailer.id)) is None:
            raise DomainError("Unknown product", code="invalid_event")
        meta = {"product_id": str(product_id)}
    # Every browser event: same visitor, same shop (and product) -> counted once per 30 minutes.
    who = ShopEvent.customer_id == customer_id if customer_id else ShopEvent.anon_id == anon_id
    recent = select(ShopEvent.id).where(
        ShopEvent.retailer_id == retailer.id, ShopEvent.event_type == event_type, who,
        ShopEvent.created_at > clock.now() - DEDUPE)
    if meta:
        recent = recent.where(ShopEvent.meta["product_id"].astext == meta["product_id"])
    if db.scalar(recent.limit(1)) is not None:
        return False
    record(db, retailer.id, event_type, customer_id=customer_id, anon_id=None if customer_id else anon_id, meta=meta)
    db.commit()
    return True


def purge_old(db: Session, now: datetime | None = None) -> int:
    """Job: raw events older than 13 months are deleted (SPEC 4.9)."""
    now = now or clock.now()
    cutoff = add_months(now, -RETENTION_MONTHS)  # exact calendar months (31 Oct -> 30 Sep a year before)
    n = db.execute(delete(ShopEvent).where(ShopEvent.created_at < cutoff)).rowcount
    db.commit()
    return n


# ---- dashboard ------------------------------------------------------------------------------------

@dataclass
class Dashboard:
    full: bool  # False: plan without analytics -> teaser only
    days: int
    views_7d: int
    daily: list[dict] = field(default_factory=list)  # [{date, visitors, views}]
    visitors: int = 0
    new_visitors: int = 0
    returning_visitors: int = 0
    shop_views: int = 0
    whatsapp_clicks: int = 0
    call_clicks: int = 0
    favourites: int = 0
    bookings_started: int = 0
    bookings_confirmed: int = 0
    top_products: list[dict] = field(default_factory=list)  # [{product_id, name, views}]


_VISITOR = func.coalesce("c:" + cast(ShopEvent.customer_id, String), "a:" + ShopEvent.anon_id)
_IST_DAY = func.date(func.timezone("Asia/Kolkata", ShopEvent.created_at))


def _count(db: Session, retailer_id, event_type: ShopEventType, since: datetime) -> int:
    return db.scalar(select(func.count()).where(ShopEvent.retailer_id == retailer_id,
                                                ShopEvent.event_type == event_type, ShopEvent.created_at >= since))


def dashboard(db: Session, retailer: Retailer, days: int) -> Dashboard:
    if days not in (7, 30, 90):
        raise DomainError("days must be 7, 30 or 90", code="invalid_period")
    features = plan_service.require_live_features(db, retailer.id)  # expired: closed like the other plan screens
    now = clock.now()
    # "X people viewed your shop": distinct visitors, not view events (deep audit).
    views_7d = db.scalar(select(func.count(func.distinct(_VISITOR))).where(
        ShopEvent.retailer_id == retailer.id, ShopEvent.event_type == ShopEventType.SHOP_VIEW,
        ShopEvent.created_at >= now - timedelta(days=7)))
    if not features.has("analytics"):
        return Dashboard(full=False, days=7, views_7d=views_7d)

    # Whole IST days: today plus the previous days-1 days.
    today = now.astimezone(IST).date()
    first = today - timedelta(days=days - 1)
    since = datetime.combine(first, datetime.min.time(), IST)
    views = and_(ShopEvent.retailer_id == retailer.id, ShopEvent.event_type == ShopEventType.SHOP_VIEW)

    per_day = {d: (v, n) for d, v, n in db.execute(
        select(_IST_DAY, func.count(func.distinct(_VISITOR)), func.count())
        .where(views, ShopEvent.created_at >= since).group_by(_IST_DAY))}
    daily = [{"date": (first + timedelta(days=i)).isoformat(),
              "visitors": per_day.get(first + timedelta(days=i), (0, 0))[0],
              "views": per_day.get(first + timedelta(days=i), (0, 0))[1]} for i in range(days)]

    # A visitor of this period is "returning" if they visited the shop on 2+ different days (any time so far).
    in_period = select(_VISITOR.label("v")).where(views, ShopEvent.created_at >= since).distinct().subquery()
    day_counts = (select(_VISITOR.label("v"), func.count(func.distinct(_IST_DAY)).label("d"))
                  .where(views, _VISITOR.in_(select(in_period.c.v))).group_by(_VISITOR).subquery())
    visitors, returning = db.execute(select(func.count(), func.count().filter(day_counts.c.d >= 2))
                                     .select_from(day_counts)).one()

    top = db.execute(
        select(ShopEvent.meta["product_id"].astext.label("pid"), func.count().label("n"))
        .where(ShopEvent.retailer_id == retailer.id, ShopEvent.event_type == ShopEventType.PRODUCT_VIEW,
               ShopEvent.created_at >= since)
        .group_by("pid").order_by(func.count().desc()).limit(5)).all()
    names = {str(p.id): p.name for p in db.scalars(select(Product).where(
        Product.id.in_([uuid.UUID(t.pid) for t in top])))} if top else {}

    def c(t: ShopEventType) -> int:
        return _count(db, retailer.id, t, since)

    return Dashboard(
        full=True, days=days, views_7d=views_7d, daily=daily, visitors=visitors, returning_visitors=returning,
        new_visitors=visitors - returning, shop_views=c(ShopEventType.SHOP_VIEW),
        whatsapp_clicks=c(ShopEventType.WHATSAPP_CLICK), call_clicks=c(ShopEventType.CALL_CLICK),
        favourites=c(ShopEventType.FAVOURITE_ADD), bookings_started=c(ShopEventType.BOOKING_START),
        bookings_confirmed=c(ShopEventType.BOOKING_CONFIRMED),
        top_products=[{"product_id": t.pid, "name": names.get(t.pid, "—"), "views": t.n} for t in top],
    )

