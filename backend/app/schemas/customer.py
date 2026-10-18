import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import JoinSource

PINCODE = r"^[1-9][0-9]{5}$"
LANGUAGES = r"^(en|hi|gu|mr|te|bn|kn|or)$"  # SPEC 8: UI languages; extend together with frontend/lib/locales


class CustomerProfileOut(BaseModel):
    id: uuid.UUID
    phone: str
    name: str | None
    preferred_language: str
    pincode: str | None
    city: str | None
    contact_consent: bool
    consent_at: datetime | None
    search_radius_km: int
    profile_complete: bool


class CustomerProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    preferred_language: str | None = Field(default=None, pattern=LANGUAGES)
    pincode: str | None = Field(default=None, pattern=PINCODE)
    city: str | None = Field(default=None, min_length=2, max_length=80)
    contact_consent: bool | None = None
    search_radius_km: Literal[2, 5, 10, 25, 50] | None = None


class JoinIn(BaseModel):
    source: JoinSource = JoinSource.LINK


class FavouriteOut(BaseModel):
    slug: str
    shop_name: str
    category: str
    city: str
    photo: str | None
    whatsapp_url: str | None
    source: JoinSource
    joined_at: datetime
    available: bool = True  # False: plan expired — shown greyed (SPEC 5)
    limited_view: bool = False  # expired, but the customer has an open booking there


class RetailerCustomerOut(BaseModel):
    customer_id: uuid.UUID
    name: str | None
    phone: str  # full only with the customer's contact consent, masked otherwise (SPEC 4.2)
    contact_consent: bool
    source: JoinSource
    is_favourite: bool
    joined_at: datetime


class RetailerCustomerPage(BaseModel):
    total: int
    items: list[RetailerCustomerOut]
