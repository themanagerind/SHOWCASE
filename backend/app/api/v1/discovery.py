from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.retailers import wa_url
from app.core.dependencies import get_optional_user
from app.db.session import get_db
from app.models import Customer, RetailerCustomer, User
from app.schemas.discovery import DiscoveredShopOut, DiscoveryOut, FoundProductOut, ProductSearchOut
from app.services import discovery_service
from app.services.retailer_service import normalize_city

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.get("/shops", response_model=DiscoveryOut)
def discover(
    lat: float | None = Query(None, ge=6.0, le=37.5),
    lng: float | None = Query(None, ge=68.0, le=97.5),
    radius_km: int | None = Query(None),
    pincode: str | None = Query(None, pattern=r"^[1-9][0-9]{5}$"),
    city: str | None = Query(None, min_length=2, max_length=80),
    category: str | None = Query(None, max_length=60),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0, le=10_000),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    customer = (
        db.scalar(select(Customer).where(Customer.user_id == user.id, Customer.deleted_at.is_(None))) if user else None
    )
    if customer is not None:
        # Logged-in customers: pincode/city/radius always come from their own profile (SPEC 4.8).
        pincode, city = customer.pincode, customer.city
        radius_km = radius_km or customer.search_radius_km
    q = discovery_service.DiscoveryQuery(
        lat=lat if lng is not None else None,
        lng=lng if lat is not None else None,
        radius_km=radius_km or 5,
        pincode=pincode,
        city=normalize_city(city) if city else None,
        category=category,
        limit=limit,
        offset=offset,
    )
    shops = discovery_service.find_shops(db, q)
    favourite_ids: set = set()
    if customer is not None and shops:
        favourite_ids = set(db.scalars(select(RetailerCustomer.retailer_id).where(
            RetailerCustomer.customer_id == customer.id,
            RetailerCustomer.is_favourite.is_(True),
            RetailerCustomer.retailer_id.in_([s.retailer.id for s in shops]),
        )))
    return DiscoveryOut(
        radius_km=q.radius_km,
        used_location=q.has_location,
        items=[
            DiscoveredShopOut(
                slug=s.retailer.slug, shop_name=s.retailer.shop_name, category=s.retailer.category,
                city=s.retailer.city, photo=s.retailer.photos[0] if s.retailer.photos else None,
                rating_avg=float(s.retailer.rating_avg), rating_count=s.retailer.rating_count,
                distance_m=round(s.distance_m) if s.distance_m is not None else None,
                whatsapp_url=wa_url(s.retailer.whatsapp_number), is_favourite=s.retailer.id in favourite_ids,
            )
            for s in shops
        ],
    )


@router.get("/products", response_model=ProductSearchOut)
def search_products(
    q: str = Query(..., min_length=2, max_length=60),
    lat: float | None = Query(None, ge=6.0, le=37.5),
    lng: float | None = Query(None, ge=68.0, le=97.5),
    radius_km: int | None = Query(None),
    city: str | None = Query(None, min_length=2, max_length=80),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0, le=10_000),
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    customer = (
        db.scalar(select(Customer).where(Customer.user_id == user.id, Customer.deleted_at.is_(None))) if user else None
    )
    if customer is not None:
        city = customer.city
        radius_km = radius_km or customer.search_radius_km
    query = discovery_service.ProductSearchQuery(
        q=q,
        lat=lat if lng is not None else None,
        lng=lng if lat is not None else None,
        radius_km=radius_km or 5,
        city=normalize_city(city) if city else None,
        limit=limit,
        offset=offset,
    )
    found = discovery_service.search_products(db, query)
    return ProductSearchOut(
        radius_km=query.radius_km,
        used_location=query.has_location,
        items=[
            FoundProductOut(
                id=str(f.product.id), name=f.product.name, photo=f.product.photos[0] if f.product.photos else None,
                price_paise=f.product.price_paise, mrp_paise=f.product.mrp_paise,
                wallet_discount_paise=f.product.wallet_discount_paise, in_stock=f.product.stock_qty > 0,
                shop_slug=f.retailer.slug, shop_name=f.retailer.shop_name, shop_city=f.retailer.city,
                distance_m=round(f.distance_m) if f.distance_m is not None else None,
            )
            for f in found
        ],
    )
