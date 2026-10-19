import re
import uuid
from datetime import datetime

from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, HttpUrl, model_validator


PHONE = r"^\+?[0-9]{10,13}$"
PINCODE = r"^[1-9][0-9]{5}$"
MAX_PAISE = 10**10  # ₹10 crore — larger numbers are a 422, not a database overflow (500)
MAX_STOCK = 1_000_000
UPI = r"^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$"
TIME = r"^([01]\d|2[0-3]):[0-5]\d$"
DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def _check_photo(url: str) -> str:
    """Photos are shown to every visitor: https only, no huge strings / data: or javascript: URLs."""
    if len(url) > 500 or not url.startswith("https://") or any(c in url for c in ' "\'<>\n\r\t'):
        raise ValueError("Photo must be an https:// link of at most 500 characters")
    return url


PhotoUrl = Annotated[str, AfterValidator(_check_photo)]


def no_nulls(model: BaseModel, fields: tuple[str, ...]) -> None:
    """PATCH bodies: leaving a field out is fine, sending null for a required column is a 422 (not a 500)."""
    bad = [f for f in fields if f in model.model_fields_set and getattr(model, f) is None]
    if bad:
        raise ValueError(f"These fields cannot be empty: {', '.join(bad)}")


def _check_timings(timings: dict | None) -> None:
    if timings is None:
        return
    for day, ranges in timings.items():
        if day not in DAYS:
            raise ValueError(f"Unknown day '{day}' in timings")
        if len(ranges) > 4:
            raise ValueError(f"At most 4 time ranges per day ({day})")
        for r in ranges:
            if len(r) != 2 or not all(re.match(TIME, t) for t in r) or r[0] >= r[1]:
                raise ValueError(f"Invalid time range {r} for {day}")


class RetailerBase(BaseModel):
    shop_name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=2000)
    photos: list[PhotoUrl] = Field(default_factory=list, max_length=10)
    address_line: str = Field(min_length=3, max_length=255)
    city: str = Field(min_length=2, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    pincode: str = Field(pattern=PINCODE)
    lat: float = Field(ge=6.0, le=37.5)  # India bounding box
    lng: float = Field(ge=68.0, le=97.5)
    timings: dict[str, list[list[str]]] = Field(default_factory=dict)
    phone: str | None = Field(default=None, pattern=PHONE)
    whatsapp_number: str | None = Field(default=None, pattern=PHONE)
    payment_link: HttpUrl | None = None
    upi_id: str | None = Field(default=None, pattern=UPI)


class RetailerCreate(RetailerBase):
    slug: str = Field(min_length=3, max_length=60)

    @model_validator(mode="after")
    def _validate(self):
        _check_timings(self.timings)
        return self


class RetailerUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=3, max_length=60)
    shop_name: str | None = Field(default=None, min_length=2, max_length=120)
    category: str | None = Field(default=None, min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=2000)
    photos: list[PhotoUrl] | None = Field(default=None, max_length=10)
    address_line: str | None = Field(default=None, min_length=3, max_length=255)
    city: str | None = Field(default=None, min_length=2, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    pincode: str | None = Field(default=None, pattern=PINCODE)
    lat: float | None = Field(default=None, ge=6.0, le=37.5)
    lng: float | None = Field(default=None, ge=68.0, le=97.5)
    timings: dict[str, list[list[str]]] | None = None
    phone: str | None = Field(default=None, pattern=PHONE)
    whatsapp_number: str | None = Field(default=None, pattern=PHONE)
    payment_link: HttpUrl | None = None
    upi_id: str | None = Field(default=None, pattern=UPI)

    @model_validator(mode="after")
    def _validate(self):
        no_nulls(self, ("slug", "shop_name", "category", "photos", "address_line", "city", "pincode", "lat", "lng",
                        "timings"))
        _check_timings(self.timings)
        return self


class RetailerPublicOut(BaseModel):
    slug: str
    shop_name: str
    category: str
    description: str | None
    photos: list[str]
    address_line: str
    city: str
    state: str | None
    pincode: str
    lat: float
    lng: float
    timings: dict
    phone: str | None
    whatsapp_number: str | None
    whatsapp_url: str | None
    payment_link: str | None
    upi_id: str | None
    rating_avg: float
    rating_count: int


class RetailerOwnerOut(RetailerPublicOut):
    id: uuid.UUID
    plan_code: str | None
    subscription_status: str | None
    plan_expired: bool = False  # had a plan that is no longer live (SPEC 5 limited access)
    products_locked_until: datetime | None
    can_change_products_now: bool
    swap_locks: bool  # false for plans without the weekly lock (PREMIUM)
    first_listing_free: bool  # true until the first swap: filling empty slots does not lock (SPEC 4.3)
    active_products: int
    max_products: int | None  # None = unlimited (PREMIUM) or no live plan
    customers_count: int
    share_link: str


class ShareOut(BaseModel):
    link: str
    qr_link: str
    whatsapp_share_url: str
    qr_png_url: str


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=60)
    price_paise: int = Field(gt=0, le=MAX_PAISE)
    mrp_paise: int | None = Field(default=None, ge=0, le=MAX_PAISE)
    wallet_discount_paise: int = Field(gt=0, le=MAX_PAISE, description="Mandatory wallet-points discount; also points needed to reserve")
    stock_qty: int = Field(default=0, ge=0, le=MAX_STOCK)
    photos: list[PhotoUrl] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def _discount_within_price(self):
        if self.wallet_discount_paise > self.price_paise:
            raise ValueError("Wallet discount cannot be more than the price")
        return self


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=60)
    price_paise: int | None = Field(default=None, gt=0, le=MAX_PAISE)
    mrp_paise: int | None = Field(default=None, ge=0, le=MAX_PAISE)
    wallet_discount_paise: int | None = Field(default=None, gt=0, le=MAX_PAISE)
    stock_qty: int | None = Field(default=None, ge=0, le=MAX_STOCK)
    photos: list[PhotoUrl] | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def _required_not_null(self):
        no_nulls(self, ("name", "price_paise", "wallet_discount_paise", "stock_qty", "photos"))
        return self


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    category: str | None
    price_paise: int
    mrp_paise: int | None
    wallet_discount_paise: int
    stock_qty: int
    photos: list[str]
    is_active: bool
    activated_at: datetime | None


class SwapIn(BaseModel):
    remove: list[uuid.UUID] = Field(default_factory=list, max_length=200)
    add: list[ProductCreate] = Field(default_factory=list, max_length=200)


class SwapOut(BaseModel):
    added_product_ids: list[uuid.UUID]
    removed_product_ids: list[uuid.UUID]
    locked_until: datetime | None


class KeepIn(BaseModel):
    keep: list[uuid.UUID] = Field(min_length=1)


class StorefrontOut(BaseModel):
    shop: RetailerPublicOut
    products: list[ProductOut]
