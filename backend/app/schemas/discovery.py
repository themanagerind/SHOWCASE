from pydantic import BaseModel


class DiscoveredShopOut(BaseModel):
    slug: str
    shop_name: str
    category: str
    city: str
    photo: str | None
    rating_avg: float
    rating_count: int
    distance_m: float | None
    whatsapp_url: str | None
    is_favourite: bool


class DiscoveryOut(BaseModel):
    radius_km: int
    used_location: bool
    items: list[DiscoveredShopOut]


class FoundProductOut(BaseModel):
    id: str
    name: str
    photo: str | None
    price_paise: int
    mrp_paise: int | None
    wallet_discount_paise: int
    in_stock: bool
    shop_slug: str
    shop_name: str
    shop_city: str
    distance_m: float | None


class ProductSearchOut(BaseModel):
    radius_km: int
    used_location: bool
    items: list[FoundProductOut]
