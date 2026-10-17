import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import Unauthorized
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.models import Customer, RefreshToken, User


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    user: User


def get_or_create_user(db: Session, phone: str) -> User:
    user = db.scalar(select(User).where(User.phone == phone))
    if user is None:
        user = User(phone=phone)
        db.add(user)
        db.flush()
        # Every user can browse and join shops, so a customer profile is created on first login.
        db.add(Customer(user_id=user.id))
        db.flush()
        db.refresh(user)
    if not user.is_active or user.deleted_at is not None:
        raise Unauthorized("Account disabled", code="account_disabled")
    return user


def _issue(db: Session, user: User, family_id: uuid.UUID, user_agent: str | None) -> TokenPair:
    jti = secrets.token_hex(16)
    refresh, expires_at = create_refresh_token(user.id, jti, family_id)
    db.add(RefreshToken(user_id=user.id, jti=jti, family_id=family_id, expires_at=expires_at, user_agent=user_agent))
    access = create_access_token(user.id, user.roles)
    return TokenPair(access, refresh, user)


def login(db: Session, phone: str, user_agent: str | None = None) -> TokenPair:
    """Call only after the OTP has been verified."""
    user = get_or_create_user(db, phone)
    user.last_login_at = clock.now()
    pair = _issue(db, user, uuid.uuid4(), user_agent)
    db.commit()
    return pair


def _revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=clock.now())
    )


def refresh(db: Session, refresh_token: str, user_agent: str | None = None) -> TokenPair:
    payload = decode_token(refresh_token, "refresh")
    row = db.scalar(select(RefreshToken).where(RefreshToken.jti == payload["jti"]).with_for_update())
    if row is None:
        raise Unauthorized("Unknown refresh token")
    if row.revoked_at is not None:
        # A rotated token was used again: treat as theft and kill the whole session family.
        _revoke_family(db, row.family_id)
        db.commit()
        raise Unauthorized("Refresh token reuse detected", code="token_reused")
    user = db.get(User, row.user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise Unauthorized("Account disabled", code="account_disabled")
    row.revoked_at = clock.now()
    pair = _issue(db, user, row.family_id, user_agent)
    db.commit()
    return pair


def logout(db: Session, refresh_token: str) -> None:
    payload = decode_token(refresh_token, "refresh")
    _revoke_family(db, uuid.UUID(payload["fam"]))
    db.commit()
