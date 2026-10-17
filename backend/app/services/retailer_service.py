import re

from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import Conflict, DomainError, NotFound
from app.models import Retailer, User
from app.services import plan_service

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,58})[a-z0-9]$")
RESERVED_SLUGS = {
    "me", "api", "admin", "app", "login", "logout", "signup", "auth", "settings", "shops", "shop", "retailers",
    "discover", "search", "credits", "bookings", "orders", "help", "about", "terms", "privacy", "static", "_next",
}


def normalize_city(city: str) -> str:
    return " ".join(city.strip().lower().split())


def validate_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not SLUG_RE.match(slug) or "--" in slug:
        raise DomainError("Slug must be 3-60 chars: a-z, 0-9 and single hyphens", code="invalid_slug")
    if slug in RESERVED_SLUGS:
        raise DomainError("This shop link is reserved", code="slug_reserved")
    return slug


def to_point(lat: float, lng: float) -> WKTElement:
    return WKTElement(f"POINT({lng} {lat})", srid=4326)


def lat_lng(retailer: Retailer) -> tuple[float, float]:
    p = to_shape(retailer.location)
    return p.y, p.x


def get_by_user(db: Session, user: User) -> Retailer:
    retailer = db.scalar(select(Retailer).where(Retailer.user_id == user.id, Retailer.deleted_at.is_(None)))
    if retailer is None:
        raise NotFound("You do not have a shop yet", code="no_shop")
    return retailer


def _slug_taken(db: Session, slug: str) -> bool:
    return db.scalar(select(Retailer.id).where(Retailer.slug == slug)) is not None


def create(db: Session, user: User, data: dict) -> Retailer:
    # SPEC: one phone number = one shop.
    if db.scalar(select(Retailer.id).where(Retailer.user_id == user.id)) is not None:
        raise Conflict("This phone number already has a shop", code="shop_exists")
    slug = validate_slug(data.pop("slug"))
    if _slug_taken(db, slug):
        raise Conflict("This shop link is already taken", code="slug_taken")
    lat, lng = data.pop("lat"), data.pop("lng")
    data["city"] = normalize_city(data["city"])
    retailer = Retailer(user_id=user.id, slug=slug, location=to_point(lat, lng), **data)
    db.add(retailer)
    db.commit()
    db.refresh(user)
    return retailer


def update(db: Session, retailer: Retailer, data: dict) -> Retailer:
    if "slug" in data:
        slug = validate_slug(data.pop("slug"))
        if slug != retailer.slug:
            if _slug_taken(db, slug):
                raise Conflict("This shop link is already taken", code="slug_taken")
            retailer.slug = slug
    lat, lng = data.pop("lat", None), data.pop("lng", None)
    if (lat is None) != (lng is None):
        raise DomainError("lat and lng must be updated together", code="invalid_location")
    if lat is not None:
        retailer.location = to_point(lat, lng)
    if "city" in data:
        data["city"] = normalize_city(data["city"])
    for key, value in data.items():
        setattr(retailer, key, value)
    db.commit()
    return retailer


def get_public(db: Session, slug: str) -> Retailer:
    """Public storefront: only shops with a TRIAL/ACTIVE/GRACE subscription are visible (no free plan)."""
    retailer = db.scalar(select(Retailer).where(Retailer.slug == slug.lower(), Retailer.deleted_at.is_(None)))
    if retailer is None or plan_service.get_live_subscription(db, retailer.id) is None:
        raise NotFound("Shop not found")
    return retailer
