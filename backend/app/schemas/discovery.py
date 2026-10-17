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
