import uuid
from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import Forbidden, Unauthorized
from app.core.security import decode_token
from app.db.session import get_db
from app.models import User

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


def require_role(*roles: str) -> Callable[..., User]:
    """Roles are re-read from the database, so a revoked role takes effect before the token expires."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if not set(roles) & set(user.roles):
            raise Forbidden("You do not have access to this resource")
        return user

    return checker
