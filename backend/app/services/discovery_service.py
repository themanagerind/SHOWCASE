"""Location-based discovery (SPEC 4.8).

Visibility = live subscription (TRIAL/ACTIVE/GRACE) AND plan scope:
  PINCODE -> shop.pincode == customer pincode
  CITY    -> shop.city    == customer city
  INDIA   -> anywhere
With GPS every shop must also be within the radius; ranking is by ring (radius / 6), then rating,
then plan priority, then exact distance. Without GPS there is no radius: CITY/INDIA shops must be
in the customer's city and the order is rating, then plan priority.
"""
from dataclasses import dataclass

from geoalchemy2 import Geography
from sqlalchemy import Float, and_, case, cast, false, func, literal, or_, select, text, true, tuple_, union
from sqlalchemy.orm import Session, aliased

from app.core.errors import DomainError
from app.models import Plan, Product, Retailer, Subscription
from app.models.enums import LIVE_SUBSCRIPTION_STATUSES

RADIUS_OPTIONS_KM = (2, 5, 10, 25, 50)
RINGS = 6


@dataclass(frozen=True)
class DiscoveryQuery:
    lat: float | None
    lng: float | None
    radius_km: int
    pincode: str | None
    city: str | None
    category: str | None = None
    limit: int = 20
    offset: int = 0

    @property
    def has_location(self) -> bool:
        return self.lat is not None and self.lng is not None


@dataclass
class DiscoveredShop:
    retailer: Retailer
    distance_m: float | None
    plan_code: str


def find_shops(db: Session, q: DiscoveryQuery) -> list[DiscoveredShop]:
    if q.radius_km not in RADIUS_OPTIONS_KM:
        raise DomainError(f"radius_km must be one of {RADIUS_OPTIONS_KM}", code="invalid_radius")
    if not q.has_location and not (q.pincode or q.city):
        raise DomainError("Share your location or add pincode and city in your profile", code="location_required")

    scope = Plan.features["visibility_scope"].astext
    pincode_ok = and_(scope == "PINCODE", Retailer.pincode == q.pincode) if q.pincode else false()
    city_ok = Retailer.city == q.city if q.city else false()
    if q.has_location:
        scope_ok = or_(pincode_ok, and_(scope == "CITY", city_ok), scope == "INDIA")
    else:
        # No GPS → no radius, so INDIA-scope shops are limited to the customer's city.
        scope_ok = or_(pincode_ok, and_(scope.in_(("CITY", "INDIA")), city_ok))

    stmt = (
        select(Retailer, Plan.code)
        .join(Subscription, Subscription.retailer_id == Retailer.id)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(
            Retailer.deleted_at.is_(None),
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            scope_ok,
        )
    )
    if q.category:
        stmt = stmt.where(func.lower(Retailer.category) == q.category.strip().lower())

    if q.has_location:
        radius_m = q.radius_km * 1000
        here = cast(func.ST_SetSRID(func.ST_MakePoint(q.lng, q.lat), 4326), Geography(srid=4326))
        distance = func.ST_Distance(Retailer.location, here)
        ring = func.floor(distance / (radius_m / RINGS))
        stmt = (
            stmt.add_columns(cast(distance, Float).label("distance_m"))
            .where(func.ST_DWithin(Retailer.location, here, radius_m))
            .order_by(ring, Retailer.rating_avg.desc(), Plan.priority.desc(), distance, Retailer.id)
        )
    else:
        stmt = stmt.add_columns(cast(None, Float).label("distance_m")).order_by(
            Retailer.rating_avg.desc(), Plan.priority.desc(), Retailer.shop_name, Retailer.id
        )

    rows = db.execute(stmt.limit(q.limit).offset(q.offset)).all()
    return [DiscoveredShop(retailer=r, plan_code=code, distance_m=d) for r, code, d in rows]


# ---- product search (SPEC 4.8a) -----------------------------------------------------------------

TRGM_THRESHOLD = 0.4  # word_similarity cut-off for spelling-tolerant matches ("mixar" -> "mixer")
MAX_CANDIDATES = 2000  # text matches considered per search; beyond this, move search to a dedicated engine


@dataclass(frozen=True)
class ProductSearchQuery:
    q: str
    lat: float | None
    lng: float | None
    radius_km: int
    city: str | None
    limit: int = 20
    offset: int = 0

    @property
    def has_location(self) -> bool:
        return self.lat is not None and self.lng is not None


@dataclass
class FoundProduct:
    product: Product
    retailer: Retailer
    distance_m: float | None


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_products(db: Session, q: ProductSearchQuery) -> list[FoundProduct]:
    """PREMIUM: all India. PRO: customer's city and within radius. BASIC: never."""
    if q.radius_km not in RADIUS_OPTIONS_KM:
        raise DomainError(f"radius_km must be one of {RADIUS_OPTIONS_KM}", code="invalid_radius")
    term = " ".join(q.q.lower().split())
    if len(term) < 2:
        raise DomainError("Search needs at least 2 characters", code="query_too_short")
    db.execute(text(f"SET LOCAL pg_trgm.word_similarity_threshold = {TRGM_THRESHOLD}"))

    # Plain `is_active` (not `IS TRUE`) so PostgreSQL can use the partial indexes `WHERE is_active AND deleted_at IS NULL`.
    live = and_(Product.is_active, Product.deleted_at.is_(None))
    name = func.lower(Product.name)
    esc = _like_escape(term)
    word_prefix = or_(name.like(f"{esc}%", escape="\\"), name.like(f"% {esc}%", escape="\\"))
    contains = name.like(f"%{esc}%", escape="\\")
    fuzzy = name.op("%>")(term)  # word_similarity(term, name) >= threshold, uses the trigram index
    # UNION of three index-backed lookups: an OR of these makes PostgreSQL scan the whole table.
    # Step 1: index-only lookup of matching product ids (UNION: an OR of these would scan the table).
    candidate_ids = list(db.scalars(
        union(
            select(Product.id).where(live, contains),
            select(Product.id).where(live, fuzzy),
            select(Product.id).where(live, func.lower(Product.category) == term),
        ).limit(MAX_CANDIDATES)
    ))
    if not candidate_ids:
        return []

    # Step 2: visibility, plan limits and ranking on that small, known set only.
    scope = Plan.features["visibility_scope"].astext
    max_products = Plan.features["max_products"].as_integer()
    # After a downgrade the shop page shows only the most recently activated N products; mirror that here.
    # CASE guarantees the count runs only for limited plans (PRO), never for unlimited ones (PREMIUM).
    newer = aliased(Product)
    newer_count = (
        select(func.count())
        .where(
            newer.retailer_id == Product.retailer_id,
            newer.is_active,
            newer.deleted_at.is_(None),
            tuple_(newer.activated_at, newer.id) > tuple_(Product.activated_at, Product.id),
        )
        .scalar_subquery()
    )
    within_plan_limit = case((max_products.is_(None), true()), else_=newer_count < max_products)
    text_rank = case((word_prefix, 0), (contains, 1), else_=2)

    pro_ok = and_(scope == "CITY", Retailer.city == q.city) if q.city else false()
    here = None
    if q.has_location:
        radius_m = q.radius_km * 1000
        here = cast(func.ST_SetSRID(func.ST_MakePoint(q.lng, q.lat), 4326), Geography(srid=4326))
        pro_ok = and_(pro_ok, func.ST_DWithin(Retailer.location, here, radius_m))
    visible = or_(scope == "INDIA", pro_ok)

    stmt = (
        select(Product, Retailer)
        .join(Retailer, Retailer.id == Product.retailer_id)
        .join(Subscription, Subscription.retailer_id == Retailer.id)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(
            Product.id.in_(candidate_ids),
            Retailer.deleted_at.is_(None),
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            within_plan_limit,
            visible,
        )
    )
    if here is not None:
        distance = func.ST_Distance(Retailer.location, here)
        ring = func.floor(distance / (q.radius_km * 1000 / RINGS))  # beyond the radius: higher rings, nearest first
        stmt = stmt.add_columns(cast(distance, Float).label("distance_m")).order_by(
            text_rank, ring, Retailer.rating_avg.desc(), Plan.priority.desc(), distance, Product.id
        )
    else:
        own_city_first = case((Retailer.city == q.city, 0), else_=1) if q.city else literal(0)
        stmt = stmt.add_columns(cast(None, Float).label("distance_m")).order_by(
            text_rank, own_city_first, Retailer.rating_avg.desc(), Plan.priority.desc(), Product.id
        )
    rows = db.execute(stmt.limit(q.limit).offset(q.offset)).all()
    return [FoundProduct(product=p, retailer=r, distance_m=d) for p, r, d in rows]
