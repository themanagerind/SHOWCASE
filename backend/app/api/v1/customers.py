from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.retailers import wa_url
from app.core.dependencies import get_current_retailer, get_current_user
from app.db.session import get_db
from app.models import Retailer, RetailerCustomer, User
from app.models.enums import JoinSource
from app.schemas.customer import (
    CustomerProfileOut,
    CustomerProfileUpdate,
    FavouriteOut,
    JoinIn,
    RetailerCustomerOut,
    RetailerCustomerPage,
)
from app.services import customer_service

router = APIRouter(tags=["customers"])


def _profile_out(user: User, db: Session) -> CustomerProfileOut:
    c = customer_service.get_customer(db, user)
    return CustomerProfileOut(
        id=c.id, phone=user.phone, name=user.name, preferred_language=user.preferred_language, pincode=c.pincode,
        city=c.city, contact_consent=c.contact_consent, consent_at=c.consent_at, search_radius_km=c.search_radius_km,
        profile_complete=customer_service.is_profile_complete(user, c),
    )


def _favourite_out(retailer: Retailer, link: RetailerCustomer) -> FavouriteOut:
    return FavouriteOut(
        slug=retailer.slug, shop_name=retailer.shop_name, category=retailer.category, city=retailer.city,
        photo=retailer.photos[0] if retailer.photos else None, whatsapp_url=wa_url(retailer.whatsapp_number),
        source=link.source, joined_at=link.created_at,
    )


@router.get("/customers/me", response_model=CustomerProfileOut)
def my_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _profile_out(user, db)


@router.patch("/customers/me", response_model=CustomerProfileOut)
def update_profile(body: CustomerProfileUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer_service.update_profile(db, user, customer_service.get_customer(db, user), body.model_dump(exclude_unset=True))
    return _profile_out(user, db)


@router.get("/customers/me/favourites", response_model=list[FavouriteOut])
def my_favourites(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_favourite_out(r, rc) for r, rc in customer_service.list_favourites(db, user)]


@router.post("/customers/me/favourites/{slug}", response_model=FavouriteOut, status_code=201)
def add_favourite(slug: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    link = customer_service.join(db, user, slug, JoinSource.DISCOVERY)
    return _favourite_out(db.get(Retailer, link.retailer_id), link)


@router.delete("/customers/me/favourites/{slug}", status_code=204)
def remove_favourite(slug: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer_service.remove_favourite(db, user, slug)


@router.post("/retailers/{slug}/join", response_model=FavouriteOut)
def join_shop(slug: str, body: JoinIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    link = customer_service.join(db, user, slug, body.source)
    return _favourite_out(db.get(Retailer, link.retailer_id), link)


@router.get("/retailers/me/customers", response_model=RetailerCustomerPage)
def my_customers(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    retailer: Retailer = Depends(get_current_retailer),
    db: Session = Depends(get_db),
):
    total, rows = customer_service.list_retailer_customers(db, retailer, limit, offset)
    return RetailerCustomerPage(
        total=total,
        items=[
            RetailerCustomerOut(
                customer_id=r.customer.id, name=r.user.name, phone=r.visible_phone,
                contact_consent=r.customer.contact_consent, source=r.link.source, is_favourite=r.link.is_favourite,
                joined_at=r.link.created_at,
            )
            for r in rows
        ],
    )
