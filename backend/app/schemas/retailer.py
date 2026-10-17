import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from app.models.enums import AdvanceType

PHONE = r"^\+?[0-9]{10,13}$"
PINCODE = r"^[1-9][0-9]{5}$"
UPI = r"^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$"
TIME = r"^([01]\d|2[0-3]):[0-5]\d$"
DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}


def _check_timings(timings: dict | None) -> None:
    if timings is None:
        return
    for day, ranges in timings.items():
        if day not in DAYS:
            raise ValueError(f"Unknown day '{day}' in timings")
        for r in ranges:
            if len(r) != 2 or not all(re.match(TIME, t) for t in r) or r[0] >= r[1]:
                raise ValueError(f"Invalid time range {r} for {day}")


def _check_advance(advance_type: AdvanceType | None, advance_value: int | None) -> None:
    if advance_type is None or advance_value is None:
        return
    if advance_type == AdvanceType.PERCENT and not 1 <= advance_value <= 100:
        raise ValueError("Advance percent must be 1-100")
    if advance_type == AdvanceType.FIXED and advance_value < 100:
        raise ValueError("Fixed advance must be at least ₹1 (100 paise)")


class RetailerBase(BaseModel):
    shop_name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=2000)
    photos: list[str] = Field(default_factory=list, max_length=10)
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
    advance_type: AdvanceType = AdvanceType.PERCENT
    advance_value: int = 20


class RetailerCreate(RetailerBase):
    slug: str = Field(min_length=3, max_length=60)

    @model_validator(mode="after")
    def _validate(self):
        _check_timings(self.timings)
        _check_advance(self.advance_type, self.advance_value)
        return self


class RetailerUpdate(BaseModel):
    slug: str | None = Field(default=None, min_length=3, max_length=60)
    shop_name: str | None = Field(default=None, min_length=2, max_length=120)
    category: str | None = Field(default=None, min_length=2, max_length=60)
    description: str | None = Field(default=None, max_length=2000)
    photos: list[str] | None = Field(default=None, max_length=10)
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
    advance_type: AdvanceType | None = None
    advance_value: int | None = None

    @model_validator(mode="after")
    def _validate(self):
        _check_timings(self.timings)
        if (self.advance_type is None) != (self.advance_value is None):
            raise ValueError("advance_type and advance_value must be updated together")
        _check_advance(self.advance_type, self.advance_value)
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
    advance_type: AdvanceType
    advance_value: int
    plan_code: str | None
    subscription_status: str | None
    products_locked_until: datetime | None
    can_change_products_now: bool
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
    price_paise: int = Field(ge=0)
    mrp_paise: int | None = Field(default=None, ge=0)
    stock_qty: int = Field(default=0, ge=0)
    photos: list[str] = Field(default_factory=list, max_length=8)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    category: str | None = Field(default=None, max_length=60)
    price_paise: int | None = Field(default=None, ge=0)
    mrp_paise: int | None = Field(default=None, ge=0)
    stock_qty: int | None = Field(default=None, ge=0)
    photos: list[str] | None = Field(default=None, max_length=8)


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    category: str | None
    price_paise: int
    mrp_paise: int | None
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
