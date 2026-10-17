import hashlib
import hmac
import uuid
from datetime import datetime, timedelta

import jwt

from app.core import clock
from app.core.config import get_settings
from app.core.errors import Unauthorized


def hash_otp(phone: str, code: str) -> str:
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def create_access_token(user_id: uuid.UUID, roles: list[str]) -> str:
    s = get_settings()
    now = clock.now()
    payload = {
        "sub": str(user_id),
        "roles": roles,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=s.access_token_minutes),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def create_refresh_token(user_id: uuid.UUID, jti: str, family_id: uuid.UUID) -> tuple[str, datetime]:
    s = get_settings()
    now = clock.now()
    expires_at = now + timedelta(days=s.refresh_token_days)
    payload = {"sub": str(user_id), "jti": jti, "fam": str(family_id), "type": "refresh", "iat": now, "exp": expires_at}
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), expires_at


def decode_token(token: str, expected_type: str) -> dict:
    s = get_settings()
    try:
        payload = jwt.decode(
            token, s.jwt_secret, algorithms=[s.jwt_algorithm], options={"verify_exp": False, "require": ["exp", "sub"]}
        )
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid token") from exc
    # Expiry checked against the injectable clock so tests can control time.
    if payload["exp"] <= clock.now().timestamp():
        raise Unauthorized("Token expired", code="token_expired")
    if payload.get("type") != expected_type:
        raise Unauthorized("Wrong token type")
    return payload
