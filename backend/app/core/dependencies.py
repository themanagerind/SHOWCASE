import uuid
from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.db.session import get_db
from app.models import Retailer, User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User:
    if creds is None:
        raise Unauthorized("Not authenticated")
    payload = decode_token(creds.credentials, "access")
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise Unauthorized("Account disabled", code="account_disabled")
    return user


def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)
) -> User | None:
    """For public endpoints that personalise when a valid token is present. A bad token is still a 401."""
    return get_current_user(creds, db) if creds is not None else None


def require_role(*roles: str) -> Callable[..., User]:
    """Roles are re-read from the database, so a revoked role takes effect before the token expires."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if not set(roles) & set(user.roles):
            raise Forbidden("You do not have access to this resource")
        return user

    return checker


def get_current_retailer(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Retailer:
    from app.services import retailer_service

    return retailer_service.get_by_user(db, user)


def require_plan(feature: str | None = None) -> Callable[..., Retailer]:
    """403 unless the retailer has a TRIAL/ACTIVE/GRACE subscription whose plan includes `feature`."""
    from app.services import plan_service

    def checker(retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)) -> Retailer:
        plan_service.require_live_features(db, retailer.id, feature)
        return retailer

    return checker


def require_admin(super_admin: bool = False) -> Callable[..., object]:
    """SUPPORT can view, extend grace and record payments; prices/offers/plans/settings need SUPER_ADMIN."""
    from app.models import AdminUser
    from app.models.enums import AdminRole

    def checker(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> AdminUser:
        from sqlalchemy import select

        admin = db.scalar(select(AdminUser).where(AdminUser.user_id == user.id, AdminUser.is_active.is_(True)))
        if admin is None:
            raise Forbidden("Admin access only")
        if super_admin and admin.role != AdminRole.SUPER_ADMIN:
            raise Forbidden("Only a super admin can do this", code="super_admin_only")
        return admin

    return checker
