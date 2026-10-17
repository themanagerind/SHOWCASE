from fastapi import APIRouter, Depends, Request
from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.core.redis import get_redis
from app.db.session import get_db
from app.models import User
from app.schemas.auth import OtpRequestIn, OtpRequestOut, OtpVerifyIn, RefreshIn, TokenOut, UserOut
from app.services import auth_service
from app.services.otp_service import OtpService
from app.services.sms import SmsSender, get_sms_sender

router = APIRouter(prefix="/auth", tags=["auth"])


def get_otp_service(redis: Redis = Depends(get_redis), sms: SmsSender = Depends(get_sms_sender)) -> OtpService:
    return OtpService(redis, sms, get_settings())


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, phone=user.phone, name=user.name, preferred_language=user.preferred_language, roles=user.roles
    )


def _token_out(pair: auth_service.TokenPair) -> TokenOut:
    return TokenOut(access_token=pair.access_token, refresh_token=pair.refresh_token, user=_user_out(pair.user))


@router.post("/otp/request", response_model=OtpRequestOut)
def request_otp(body: OtpRequestIn, request: Request, otp: OtpService = Depends(get_otp_service)):
    ip = request.client.host if request.client else "unknown"
    phone = otp.request(body.phone, ip)
    return OtpRequestOut(phone=phone, expires_in_seconds=get_settings().otp_ttl_seconds)


@router.post("/otp/verify", response_model=TokenOut)
def verify_otp(
    body: OtpVerifyIn, request: Request, otp: OtpService = Depends(get_otp_service), db: Session = Depends(get_db)
):
    phone = otp.verify(body.phone, body.code)
    return _token_out(auth_service.login(db, phone, request.headers.get("user-agent")))


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    return _token_out(auth_service.refresh(db, body.refresh_token, request.headers.get("user-agent")))


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, db: Session = Depends(get_db)):
    auth_service.logout(db, body.refresh_token)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return _user_out(user)
