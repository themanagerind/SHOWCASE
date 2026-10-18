"""THE-MANAGER resident signup prefill (SPEC 4.12, docs/integrations/the-manager-prefill.md).

start(token)  -> redeem once server-to-server, keep the data in Redis 15 min under a random prefill_id,
                 give the browser ONLY the mobile number.
claim(id)     -> after OTP login: the rest (name, society address, flat) only if the verified phone is the
                 prefill mobile; the Redis entry is deleted on the first claim either way. Email is never kept.
"""
import json
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError, Forbidden, NotFound
from app.core.phone import normalize_indian_mobile
from app.models import User
from app.models.enums import SignupSource
from app.services import customer_service
from app.services.the_manager import TheManagerClient, TransientError

log = logging.getLogger(__name__)
TTL = timedelta(minutes=15)
TRIES = 3
_TOKEN = re.compile(r"^[A-Za-z0-9_\-]{16,256}$")
FIELDS = ("name", "society_name", "address_line", "city", "state", "pincode", "flat_number", "floor")


@dataclass(frozen=True)
class StartResult:
    status: str  # ok | invalid | expired | unavailable
    prefill_id: str | None = None
    mobile: str | None = None


def _key(prefill_id: str) -> str:
    return f"prefill:{prefill_id}"


def _clean(raw: dict) -> dict:
    """Keep only what the profile form uses, as short trimmed strings. Email is dropped here (never stored)."""
    addr = raw.get("address") if isinstance(raw.get("address"), dict) else {}
    flat = raw.get("flat") if isinstance(raw.get("flat"), dict) else {}

    def s(v, n):
        return v.strip()[:n] if isinstance(v, str) and v.strip() else None

    pin = s(addr.get("pincode"), 6)
    return {
        "name": s(raw.get("name"), 120), "society_name": s(addr.get("society_name"), 120),
        "address_line": s(addr.get("line"), 200), "city": s(addr.get("city"), 80), "state": s(addr.get("state"), 60),
        "pincode": pin if pin and re.fullmatch(r"[1-9]\d{5}", pin) else None,
        "flat_number": s(flat.get("number"), 20), "floor": s(flat.get("floor"), 10),
    }


def start(db: Session, redis: Redis, client: TheManagerClient | None, token: str) -> StartResult:
    if client is None:
        return StartResult("unavailable")
    if not _TOKEN.match(token or ""):
        return StartResult("invalid")
    request_id = f"showcase-prefill-{uuid.uuid4()}"
    result = None
    for _ in range(TRIES):  # same request_id on every retry: THE-MANAGER replays the original 200
        try:
            result = client.redeem_prefill(token, request_id)
            break
        except TransientError as exc:
            log.warning("prefill redeem failed (%s), retrying with %s", exc, request_id)
    if result is None:
        return StartResult("unavailable")
    if result.outcome != "ok":
        if result.outcome == "unauthorized":
            log.error("THE-MANAGER rejected the shared key on prefill redeem")
        return StartResult({"not_found": "invalid", "expired": "expired"}.get(result.outcome, "unavailable"))
    try:
        mobile = normalize_indian_mobile(result.data["mobile"])
    except DomainError:
        return StartResult("invalid")
    prefill_id = secrets.token_urlsafe(24)
    # Decided now, not at claim time: was there already a Showcase account for this mobile? (signup_source)
    existed = db.scalar(select(User.id).where(User.phone == mobile)) is not None
    entry = {"mobile": mobile, "existing_account": existed, **_clean(result.data)}
    redis.set(_key(prefill_id), json.dumps(entry), ex=int(TTL.total_seconds()))
    return StartResult("ok", prefill_id, mobile)


def claim(db: Session, redis: Redis, user: User, prefill_id: str) -> dict:
    raw = redis.getdel(_key(prefill_id)) if len(prefill_id) <= 64 else None
    if raw is None:
        raise NotFound("This link has expired. Please fill in your details.", code="prefill_expired")
    entry = json.loads(raw)
    if entry["mobile"] != user.phone:
        # Someone else verified with a different number: the resident's details are thrown away unseen.
        raise Forbidden("This prefill belongs to another mobile number", code="prefill_phone_mismatch")
    customer = customer_service.get_customer(db, user)
    if not entry["existing_account"]:  # account created through this prefill flow
        customer.signup_source = SignupSource.THE_MANAGER
        db.commit()
    return {k: entry.get(k) for k in FIELDS}
