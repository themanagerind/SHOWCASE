"""THE-MANAGER resident signup prefill (SPEC 4.12)."""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy.orm import Session

from app.api.v1.wallet import the_manager_dep
from app.core import rate_limit
from app.core.dependencies import get_current_user
from app.core.redis import get_redis
from app.db.session import get_db
from app.models import User
from app.services import prefill_service
from app.services.the_manager import TheManagerClient

router = APIRouter(prefix="/prefill", tags=["prefill"])


class StartIn(BaseModel):
    token: str = Field(min_length=1, max_length=300)


class StartOut(BaseModel):
    status: str  # ok | invalid | expired | unavailable — anything but ok means: normal signup
    prefill_id: str | None
    mobile: str | None  # the only personal data sent before OTP


class PrefillOut(BaseModel):
    name: str | None
    society_name: str | None
    address_line: str | None
    city: str | None
    state: str | None
    pincode: str | None
    flat_number: str | None
    floor: str | None


@router.post("/start", response_model=StartOut)
def start(body: StartIn, request: Request, db: Session = Depends(get_db), redis: Redis = Depends(get_redis),
          client: TheManagerClient | None = Depends(the_manager_dep)):
    rate_limit.hit(redis, "prefill_start", request.client.host if request.client else "unknown", 20, 3600)
    r = prefill_service.start(db, redis, client, body.token)
    return StartOut(status=r.status, prefill_id=r.prefill_id, mobile=r.mobile)


@router.get("/{prefill_id}", response_model=PrefillOut)
def claim(prefill_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db),
          redis: Redis = Depends(get_redis)):
    return PrefillOut(**prefill_service.claim(db, redis, user, prefill_id))
