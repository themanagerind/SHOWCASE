"""Plan product limits and the weekly slot-swap rule (SPEC 4.3).

- Before the retailer's first swap, empty slots can be filled freely (no lock).
- After that, any add / remove / replace is a swap: allowed only when not locked, and it locks the
  product set for 7 days (plans with weekly_swap=false, i.e. PREMIUM, never lock).
- During the lock, price / MRP / wallet discount / stock / photos / description can still be edited.
- Hiding a product counts as a remove. Plan-downgrade clean-up ("keep") is not a swap.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import DomainError, Forbidden, NotFound
from app.models import Product, ProductSwap, Retailer, User
from app.services import plan_service
from app.services.plan_service import PlanFeatures

SWAP_LOCK = timedelta(days=7)
# Editable at any time, including during the weekly lock.
ALWAYS_EDITABLE = {"price_paise", "mrp_paise", "wallet_discount_paise", "stock_qty", "photos", "description"}
# Changing these would effectively replace the product, so they follow the lock.
LOCKED_FIELDS = {"name", "category"}


def _lock_retailer(db: Session, retailer_id: uuid.UUID) -> Retailer:
    # Row lock serialises concurrent adds/swaps for one shop, so two requests cannot both take the last slot.
    return db.scalar(select(Retailer).where(Retailer.id == retailer_id).with_for_update().execution_options(
        populate_existing=True
    ))


def active_count(db: Session, retailer_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(Product).where(
            Product.retailer_id == retailer_id, Product.is_active.is_(True), Product.deleted_at.is_(None)
        )
    )


def is_locked(retailer: Retailer, features: PlanFeatures | None, now: datetime) -> bool:
    if features is not None and not features.weekly_swap:
        return False
    return retailer.products_locked_until is not None and now < retailer.products_locked_until


def check_weekly_lock(retailer: Retailer, features: PlanFeatures, now: datetime) -> None:
    if is_locked(retailer, features, now):
        raise Forbidden(
            f"Products are locked until {retailer.products_locked_until.isoformat()}; "
            "you can still edit price, stock, photos and description",
            code="weekly_lock",
        )


def check_product_limit(features: PlanFeatures, resulting_active: int) -> None:
    if features.max_products is not None and resulting_active > features.max_products:
        raise Forbidden(
            f"Your {features.code} plan allows {features.max_products} active products", code="product_limit"
        )


def _record_swap(
    db: Session, retailer: Retailer, user: User, features: PlanFeatures, added: list, removed: list, now: datetime
) -> ProductSwap:
    locked_until = now + SWAP_LOCK if features.weekly_swap else None
    retailer.products_locked_until = locked_until
    retailer.first_swap_done = True
    swap = ProductSwap(
        retailer_id=retailer.id,
        performed_by_user_id=user.id,
        added_product_ids=added,
        removed_product_ids=removed,
        plan_code=features.code,
        locked_until=locked_until,
    )
    db.add(swap)
    return swap


def _new_product(retailer: Retailer, data: dict, now: datetime) -> Product:
    return Product(retailer_id=retailer.id, is_active=True, activated_at=now, **data)


def _get_own(db: Session, retailer: Retailer, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None or product.retailer_id != retailer.id or product.deleted_at is not None:
        raise NotFound("Product not found")
    return product


def add_product(db: Session, retailer: Retailer, user: User, data: dict) -> Product:
    now = clock.now()
    features = plan_service.require_live_features(db, retailer.id)
    retailer = _lock_retailer(db, retailer.id)
    if retailer.first_swap_done:
        check_weekly_lock(retailer, features, now)
    check_product_limit(features, active_count(db, retailer.id) + 1)
    product = _new_product(retailer, data, now)
    db.add(product)
    db.flush()
    if retailer.first_swap_done:
        _record_swap(db, retailer, user, features, [product.id], [], now)
    db.commit()
    return product


def remove_product(db: Session, retailer: Retailer, user: User, product_id: uuid.UUID) -> None:
    """Hide a product from the shop (soft: is_active=false). Counts as a swap."""
    now = clock.now()
    features = plan_service.require_live_features(db, retailer.id)
    retailer = _lock_retailer(db, retailer.id)
    check_weekly_lock(retailer, features, now)
    product = _get_own(db, retailer, product_id)
    if not product.is_active:
        raise DomainError("Product is already hidden", code="already_hidden")
    product.is_active = False
    product.deactivated_at = now
    _record_swap(db, retailer, user, features, [], [product.id], now)
    db.commit()


def swap(db: Session, retailer: Retailer, user: User, remove_ids: list[uuid.UUID], add: list[dict]) -> ProductSwap:
    """Replace any number of slots in one go; locks the set for 7 days afterwards."""
    if not remove_ids and not add:
        raise DomainError("Nothing to swap", code="empty_swap")
    if len(set(remove_ids)) != len(remove_ids):
        raise DomainError("Duplicate product in remove list", code="invalid_swap")
    now = clock.now()
    features = plan_service.require_live_features(db, retailer.id)
    retailer = _lock_retailer(db, retailer.id)
    check_weekly_lock(retailer, features, now)

    to_remove = [_get_own(db, retailer, pid) for pid in remove_ids]
    if any(not p.is_active for p in to_remove):
        raise DomainError("Only active products can be swapped out", code="invalid_swap")
    check_product_limit(features, active_count(db, retailer.id) - len(to_remove) + len(add))

    for p in to_remove:
        p.is_active = False
        p.deactivated_at = now
    new_products = [_new_product(retailer, data, now) for data in add]
    db.add_all(new_products)
    db.flush()
    record = _record_swap(db, retailer, user, features, [p.id for p in new_products], remove_ids, now)
    db.commit()
    return record


def edit_product(db: Session, retailer: Retailer, product_id: uuid.UUID, data: dict) -> Product:
    now = clock.now()
    product = _get_own(db, retailer, product_id)
    if LOCKED_FIELDS & data.keys():
        features = plan_service.get_live_features(db, retailer.id)
        if is_locked(retailer, features, now):
            raise Forbidden("Name and category cannot be changed while products are locked", code="weekly_lock")
    unknown = data.keys() - ALWAYS_EDITABLE - LOCKED_FIELDS
    if unknown:
        raise DomainError(f"Cannot edit fields: {', '.join(sorted(unknown))}", code="invalid_fields")
    price = data.get("price_paise", product.price_paise)
    discount = data.get("wallet_discount_paise", product.wallet_discount_paise)
    if not 0 < discount <= price:
        raise DomainError("Wallet discount must be more than 0 and not more than the price", code="invalid_discount")
    for key, value in data.items():
        setattr(product, key, value)
    db.commit()
    return product


def keep_products(db: Session, retailer: Retailer, keep_ids: list[uuid.UUID]) -> None:
    """After a plan downgrade: retailer picks which products stay active. Not a swap, no lock."""
    features = plan_service.require_live_features(db, retailer.id)
    retailer = _lock_retailer(db, retailer.id)
    active = list(db.scalars(select(Product).where(
        Product.retailer_id == retailer.id, Product.is_active.is_(True), Product.deleted_at.is_(None)
    )))
    if features.max_products is None or len(active) <= features.max_products:
        raise DomainError("You are within your plan limit; use swap instead", code="not_over_limit")
    active_ids = {p.id for p in active}
    keep = set(keep_ids)
    if not keep <= active_ids or len(keep) != len(keep_ids):
        raise DomainError("Keep list must contain distinct active products", code="invalid_keep")
    if len(keep) > features.max_products:
        raise Forbidden(
            f"Your {features.code} plan allows {features.max_products} active products", code="product_limit"
        )
    now = clock.now()
    for p in active:
        if p.id not in keep:
            p.is_active = False
            p.deactivated_at = now
    db.commit()


def list_own(db: Session, retailer: Retailer) -> list[Product]:
    return list(db.scalars(
        select(Product)
        .where(Product.retailer_id == retailer.id, Product.deleted_at.is_(None))
        .order_by(Product.is_active.desc(), Product.activated_at.desc())
    ))


def list_public(db: Session, retailer: Retailer) -> list[Product]:
    """Active products; if over the plan limit (after a downgrade) only the most recently activated N."""
    features = plan_service.get_live_features(db, retailer.id)
    if features is None:
        return []
    q = (
        select(Product)
        .where(Product.retailer_id == retailer.id, Product.is_active.is_(True), Product.deleted_at.is_(None))
        .order_by(Product.activated_at.desc(), Product.id)
    )
    if features.max_products is not None:
        q = q.limit(features.max_products)
    return list(db.scalars(q))
