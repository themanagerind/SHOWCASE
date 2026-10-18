import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.errors import NotFound, Unauthorized
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


def _issue(db: Session, user: User, family_id: uuid.UUID, started_at: datetime, user_agent: str | None) -> TokenPair:
    jti = secrets.token_hex(16)
    refresh, expires_at = create_refresh_token(user.id, jti, family_id)
    db.add(RefreshToken(user_id=user.id, jti=jti, family_id=family_id, expires_at=expires_at,
                        user_agent=(user_agent or "")[:255] or None, session_started_at=started_at))
    access = create_access_token(user.id, user.roles, family_id)
    return TokenPair(access, refresh, user)


def login(db: Session, phone: str, user_agent: str | None = None) -> TokenPair:
    """Call only after the OTP has been verified. Starts a new session (one per device/browser)."""
    user = get_or_create_user(db, phone)
    user.last_login_at = clock.now()
    pair = _issue(db, user, uuid.uuid4(), clock.now(), user_agent)
    db.commit()
    return pair


def _revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=clock.now())
    )


def _admin_session_over(user: User, started_at: datetime, now: datetime) -> bool:
    return "admin" in user.roles and now >= started_at + timedelta(hours=get_settings().admin_session_hours)


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
    now = clock.now()
    if _admin_session_over(user, row.session_started_at, now):
        _revoke_family(db, row.family_id)
        db.commit()
        raise Unauthorized("Session expired, please log in again", code="session_expired")
    row.revoked_at = now
    pair = _issue(db, user, row.family_id, row.session_started_at, user_agent)
    db.commit()
    return pair


def check_session(db: Session, user: User, session_id: uuid.UUID) -> None:
    """Every authenticated request: the login session must still be alive (so logout takes effect at once)."""
    now = clock.now()
    started = db.scalar(
        select(RefreshToken.session_started_at).where(
            RefreshToken.family_id == session_id, RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > now,
        ).limit(1)
    )
    if started is None:
        raise Unauthorized("You have been logged out", code="session_ended")
    if _admin_session_over(user, started, now):
        raise Unauthorized("Session expired, please log in again", code="session_expired")


def logout(db: Session, refresh_token: str) -> None:
    payload = decode_token(refresh_token, "refresh")
    _revoke_family(db, uuid.UUID(payload["fam"]))
    db.commit()


# ---- devices / sessions -------------------------------------------------------------------------

@dataclass
class SessionInfo:
    id: uuid.UUID
    device: str
    started_at: datetime
    last_active_at: datetime
    current: bool


def describe_device(user_agent: str | None) -> str:
    ua = user_agent or ""
    os_ = next((name for pat, name in [
        (r"Android", "Android"), (r"iPhone|iPad|iOS", "iPhone/iPad"), (r"Windows", "Windows"),
        (r"Mac OS X|Macintosh", "Mac"), (r"Linux", "Linux"),
    ] if re.search(pat, ua)), "Unknown device")
    browser = next((name for pat, name in [
        (r"SamsungBrowser", "Samsung Internet"), (r"Edg/", "Edge"), (r"OPR/|Opera", "Opera"),
        (r"Firefox/", "Firefox"), (r"Chrome/", "Chrome"), (r"Safari/", "Safari"),
    ] if re.search(pat, ua)), None)
    return f"{browser} · {os_}" if browser else os_


def list_sessions(db: Session, user: User, current_session_id: uuid.UUID | None) -> list[SessionInfo]:
    now = clock.now()
    rows = db.execute(
        select(RefreshToken.family_id, func.min(RefreshToken.session_started_at), func.max(RefreshToken.created_at))
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > now)
        .group_by(RefreshToken.family_id)
    ).all()
    out = []
    for family_id, started, last in rows:
        ua = db.scalar(select(RefreshToken.user_agent).where(RefreshToken.family_id == family_id)
                       .order_by(RefreshToken.created_at.desc()).limit(1))
        out.append(SessionInfo(family_id, describe_device(ua), started, last, family_id == current_session_id))
    return sorted(out, key=lambda s: (not s.current, -s.last_active_at.timestamp()))


def logout_session(db: Session, user: User, session_id: uuid.UUID) -> None:
    owned = db.scalar(select(RefreshToken.id).where(RefreshToken.family_id == session_id, RefreshToken.user_id == user.id).limit(1))
    if owned is None:
        raise NotFound("Session not found")
    _revoke_family(db, session_id)
    db.commit()


def logout_everywhere(db: Session, user: User, keep_session_id: uuid.UUID | None = None) -> int:
    q = update(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
    if keep_session_id is not None:
        q = q.where(RefreshToken.family_id != keep_session_id)
    n = db.execute(q.values(revoked_at=clock.now())).rowcount
    db.commit()
    return n
