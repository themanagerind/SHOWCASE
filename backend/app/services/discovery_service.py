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
from sqlalchemy import Float, and_, cast, false, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.models import Plan, Retailer, Subscription
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
        here = cast(func.ST_SetSRID(func.ST_MakePoint(q.lng, q.lat), 4326), Geography)
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
