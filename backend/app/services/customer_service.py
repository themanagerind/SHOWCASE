"""Customer profile, joining a shop via link/QR, favourites and the retailer's customer list (SPEC 4.2)."""
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import DomainError, NotFound
from app.models import Customer, Retailer, RetailerCustomer, User
from app.models.enums import LIVE_SUBSCRIPTION_STATUSES, JoinSource
from app.models.subscription import Subscription
from app.services import retailer_service


def get_customer(db: Session, user: User) -> Customer:
    customer = db.scalar(select(Customer).where(Customer.user_id == user.id, Customer.deleted_at.is_(None)))
    if customer is None:
        raise NotFound("Customer profile not found")
    return customer


def is_profile_complete(user: User, customer: Customer) -> bool:
    return bool(user.name and customer.pincode and customer.city)


def update_profile(db: Session, user: User, customer: Customer, data: dict) -> None:
    if "name" in data:
        user.name = data.pop("name").strip()
    if "preferred_language" in data:
        user.preferred_language = data.pop("preferred_language")
    if "city" in data:
        customer.city = retailer_service.normalize_city(data.pop("city"))
    if "pincode" in data:
        customer.pincode = data.pop("pincode")
    if "search_radius_km" in data:
        customer.search_radius_km = data.pop("search_radius_km")
    if "contact_consent" in data:
        consent = data.pop("contact_consent")
        if consent != customer.contact_consent:
            customer.contact_consent = consent
            # consent_at records when consent was last GIVEN; withdrawal clears it (DPDP).
            customer.consent_at = clock.now() if consent else None
    db.commit()


def join(db: Session, user: User, slug: str, source: JoinSource) -> RetailerCustomer:
    """Idempotent: re-joining marks the shop favourite again but keeps the original source."""
    retailer = retailer_service.get_public(db, slug)  # 404 unless the shop has a live subscription
    if retailer.user_id == user.id:
        raise DomainError("You cannot join your own shop", code="own_shop")
    customer = get_customer(db, user)
    db.execute(
        insert(RetailerCustomer)
        .values(retailer_id=retailer.id, customer_id=customer.id, source=source, is_favourite=True)
        .on_conflict_do_update(
            index_elements=["retailer_id", "customer_id"], set_={"is_favourite": True, "updated_at": func.now()}
        )
    )
    db.commit()
    return db.scalar(
        select(RetailerCustomer)
        .where(RetailerCustomer.retailer_id == retailer.id, RetailerCustomer.customer_id == customer.id)
        .execution_options(populate_existing=True)
    )


def remove_favourite(db: Session, user: User, slug: str) -> None:
    """The customer stays in the retailer's customer list, only marked as not favourite."""
    customer = get_customer(db, user)
    link = db.scalar(
        select(RetailerCustomer)
        .join(Retailer, Retailer.id == RetailerCustomer.retailer_id)
        .where(Retailer.slug == slug.lower(), RetailerCustomer.customer_id == customer.id)
    )
    if link is None:
        raise NotFound("Shop is not in your favourites")
    link.is_favourite = False
    db.commit()


def list_favourites(db: Session, user: User) -> list[tuple[Retailer, RetailerCustomer]]:
    """Favourite shops that are publicly live. Expired shops come back in step 7 (limited view)."""
    customer = get_customer(db, user)
    rows = db.execute(
        select(Retailer, RetailerCustomer)
        .join(RetailerCustomer, RetailerCustomer.retailer_id == Retailer.id)
        .join(Subscription, Subscription.retailer_id == Retailer.id)
        .where(
            RetailerCustomer.customer_id == customer.id,
            RetailerCustomer.is_favourite.is_(True),
            Retailer.deleted_at.is_(None),
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
        )
        .order_by(RetailerCustomer.created_at.desc())
    ).all()
    return [(r, rc) for r, rc in rows]


def mask_phone(phone: str) -> str:
    digits = phone.removeprefix("+91")
    return f"{digits[:2]}{'X' * (len(digits) - 4)}{digits[-2:]}"


@dataclass
class CustomerRow:
    customer: Customer
    user: User
    link: RetailerCustomer

    @property
    def visible_phone(self) -> str:
        return self.user.phone if self.customer.contact_consent else mask_phone(self.user.phone)


def list_retailer_customers(db: Session, retailer: Retailer, limit: int, offset: int) -> tuple[int, list[CustomerRow]]:
    base = (
        select(RetailerCustomer, Customer, User)
        .join(Customer, Customer.id == RetailerCustomer.customer_id)
        .join(User, User.id == Customer.user_id)
        .where(RetailerCustomer.retailer_id == retailer.id, Customer.deleted_at.is_(None), User.deleted_at.is_(None))
    )
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(base.order_by(RetailerCustomer.created_at.desc()).limit(limit).offset(offset)).all()
    return total, [CustomerRow(customer=c, user=u, link=rc) for rc, c, u in rows]
