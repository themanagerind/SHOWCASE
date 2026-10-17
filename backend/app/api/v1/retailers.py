import io
import uuid
from urllib.parse import quote

import qrcode
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.dependencies import get_current_retailer, get_current_user
from app.db.session import get_db
from app.models import Retailer, User
from app.schemas.retailer import (
    KeepIn,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    RetailerCreate,
    RetailerOwnerOut,
    RetailerPublicOut,
    RetailerUpdate,
    ShareOut,
    StorefrontOut,
    SwapIn,
    SwapOut,
)
from app.services import customer_service, plan_service, product_service, retailer_service

router = APIRouter(prefix="/retailers", tags=["retailers"])


def _share_link(retailer: Retailer, source: str) -> str:
    return f"{get_settings().public_base_url}/{retailer.slug}?src={source}"


def wa_url(number: str | None) -> str | None:
    if not number:
        return None
    digits = "".join(ch for ch in number if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return f"https://wa.me/{digits}"


def _public_out(retailer: Retailer) -> RetailerPublicOut:
    lat, lng = retailer_service.lat_lng(retailer)
    return RetailerPublicOut(
        slug=retailer.slug, shop_name=retailer.shop_name, category=retailer.category,
        description=retailer.description, photos=retailer.photos, address_line=retailer.address_line,
        city=retailer.city, state=retailer.state, pincode=retailer.pincode, lat=lat, lng=lng,
        timings=retailer.timings, phone=retailer.phone, whatsapp_number=retailer.whatsapp_number,
        whatsapp_url=wa_url(retailer.whatsapp_number), payment_link=retailer.payment_link, upi_id=retailer.upi_id,
        rating_avg=float(retailer.rating_avg), rating_count=retailer.rating_count,
    )


def _owner_out(db: Session, retailer: Retailer) -> RetailerOwnerOut:
    sub = plan_service.get_live_subscription(db, retailer.id)
    features = plan_service.PlanFeatures.from_plan(sub.plan) if sub else None
    locked = product_service.is_locked(retailer, features, clock.now()) if retailer.first_swap_done else False
    return RetailerOwnerOut(
        **_public_out(retailer).model_dump(),
        id=retailer.id,
        plan_code=features.code if features else None, subscription_status=sub.status.value if sub else None,
        products_locked_until=retailer.products_locked_until if locked else None,
        can_change_products_now=features is not None and not locked,
        swap_locks=features.weekly_swap if features else True,
        first_listing_free=not retailer.first_swap_done,
        active_products=product_service.active_count(db, retailer.id),
        max_products=features.max_products if features else None,
        customers_count=customer_service.count_customers(db, retailer),
        share_link=_share_link(retailer, "link"),
    )


def _dump(model) -> dict:
    data = model.model_dump(exclude_unset=True)
    if data.get("payment_link") is not None:
        data["payment_link"] = str(data["payment_link"])
    return data


@router.post("", response_model=RetailerOwnerOut, status_code=201)
def create_shop(body: RetailerCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = body.model_dump()
    if data.get("payment_link") is not None:
        data["payment_link"] = str(data["payment_link"])
    return _owner_out(db, retailer_service.create(db, user, data))


@router.get("/me", response_model=RetailerOwnerOut)
def my_shop(retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    return _owner_out(db, retailer)


@router.patch("/me", response_model=RetailerOwnerOut)
def update_shop(body: RetailerUpdate, retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    return _owner_out(db, retailer_service.update(db, retailer, _dump(body)))


@router.get("/me/share", response_model=ShareOut)
def share(retailer: Retailer = Depends(get_current_retailer)):
    link = _share_link(retailer, "link")
    text = f"{retailer.shop_name} — ab online! Hamare products dekhiye: {link}"
    return ShareOut(
        link=link, qr_link=_share_link(retailer, "qr"),
        whatsapp_share_url=f"https://wa.me/?text={quote(text)}", qr_png_url="/api/v1/retailers/me/qr",
    )


@router.get("/me/qr", response_class=Response, responses={200: {"content": {"image/png": {}}}})
def qr_png(retailer: Retailer = Depends(get_current_retailer)):
    buf = io.BytesIO()
    qrcode.make(_share_link(retailer, "qr"), box_size=10, border=2).save(buf, format="PNG")
    return Response(
        buf.getvalue(), media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="{retailer.slug}-qr.png"'},
    )


@router.get("/me/products", response_model=list[ProductOut])
def my_products(retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    return product_service.list_own(db, retailer)


@router.post("/me/products", response_model=ProductOut, status_code=201)
def add_product(
    body: ProductCreate,
    retailer: Retailer = Depends(get_current_retailer),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return product_service.add_product(db, retailer, user, body.model_dump())


@router.patch("/me/products/{product_id}", response_model=ProductOut)
def edit_product(
    product_id: uuid.UUID, body: ProductUpdate,
    retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db),
):
    return product_service.edit_product(db, retailer, product_id, body.model_dump(exclude_unset=True))


@router.delete("/me/products/{product_id}", status_code=204)
def remove_product(
    product_id: uuid.UUID,
    retailer: Retailer = Depends(get_current_retailer),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    product_service.remove_product(db, retailer, user, product_id)


@router.post("/me/products/swap", response_model=SwapOut)
def swap_products(
    body: SwapIn,
    retailer: Retailer = Depends(get_current_retailer),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = product_service.swap(db, retailer, user, body.remove, [p.model_dump() for p in body.add])
    return SwapOut(
        added_product_ids=record.added_product_ids, removed_product_ids=record.removed_product_ids,
        locked_until=record.locked_until,
    )


@router.post("/me/products/keep", status_code=204)
def keep_products(body: KeepIn, retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    product_service.keep_products(db, retailer, body.keep)


@router.get("/{slug}", response_model=StorefrontOut)
def storefront(slug: str, db: Session = Depends(get_db)):
    retailer = retailer_service.get_public(db, slug)
    return StorefrontOut(shop=_public_out(retailer), products=product_service.list_public(db, retailer))
