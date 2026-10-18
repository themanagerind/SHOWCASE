"""Shop analytics (SPEC 4.9): browser events in, retailer dashboard out."""
import uuid
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_retailer, get_optional_user
from app.core.redis import get_redis
from app.db.session import get_db
from app.models import Retailer, User
from app.models.enums import ShopEventType
from app.services import analytics_service, retailer_service

router = APIRouter(tags=["analytics"])


class EventIn(BaseModel):
    slug: str = Field(min_length=1, max_length=60)
    event_type: Literal["shop_view", "product_view", "whatsapp_click", "call_click"]
    anon_id: str | None = Field(default=None, max_length=64)
    product_id: uuid.UUID | None = None


class EventOut(BaseModel):
    counted: bool


class DashboardOut(BaseModel):
    full: bool
    days: int
    views_7d: int
    daily: list[dict]
    visitors: int
    new_visitors: int
    returning_visitors: int
    shop_views: int
    whatsapp_clicks: int
    call_clicks: int
    favourites: int
    bookings_started: int
    bookings_confirmed: int
    top_products: list[dict]


@router.post("/events", response_model=EventOut)
def track(body: EventIn, request: Request, user: User | None = Depends(get_optional_user),
          db: Session = Depends(get_db), redis: Redis = Depends(get_redis)):
    retailer = retailer_service.get_public(db, body.slug)  # only live shops are tracked
    return EventOut(counted=analytics_service.track(db, redis, retailer, ShopEventType(body.event_type), user,
                                                    body.anon_id, body.product_id,
                                                    request.client.host if request.client else "unknown"))


@router.get("/retailers/me/analytics", response_model=DashboardOut)
def my_analytics(days: int = Query(30), retailer: Retailer = Depends(get_current_retailer),
                 db: Session = Depends(get_db)):
    return DashboardOut(**asdict(analytics_service.dashboard(db, retailer, days)))
