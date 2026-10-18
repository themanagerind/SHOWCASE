from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.dependencies import get_current_retailer, get_current_user
from app.core.redis import get_redis
from app.db.session import get_db
from app.models import Retailer, User
from app.models.enums import WalletOwnerType
from app.services import customer_service, wallet_service
from app.services.the_manager import TheManagerClient, get_the_manager_client

router = APIRouter(tags=["wallet"])


def the_manager_dep() -> TheManagerClient | None:
    return get_the_manager_client()


class LedgerEntryOut(BaseModel):
    id: str
    created_at: datetime
    entry_type: str
    amount_paise: int
    balance_after_paise: int
    note: str | None


class WalletOut(BaseModel):
    balance_paise: int
    entries: list[LedgerEntryOut]


class RedeemIn(BaseModel):
    code: str = Field(min_length=4, max_length=32)


class RedeemOut(BaseModel):
    status: str  # CREDITED | PENDING | REJECTED | ERROR
    amount_paise: int | None
    balance_paise: int
    error_code: str | None


def _wallet_out(db: Session, owner_type: WalletOwnerType, owner_id) -> WalletOut:
    w = wallet_service.get_wallet(db, owner_type, owner_id)
    db.commit()
    return WalletOut(balance_paise=w.balance_paise, entries=[
        LedgerEntryOut(id=str(e.id), created_at=e.created_at, entry_type=e.entry_type.value, amount_paise=e.amount_paise,
                       balance_after_paise=e.balance_after_paise, note=e.note)
        for e in wallet_service.ledger(db, w)])


@router.get("/wallet/me", response_model=WalletOut)
def my_wallet(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _wallet_out(db, WalletOwnerType.CUSTOMER, customer_service.get_customer(db, user).id)


@router.post("/wallet/me/redeem", response_model=RedeemOut)
def redeem(body: RedeemIn, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db),
           redis: Redis = Depends(get_redis), client: TheManagerClient | None = Depends(the_manager_dep)):
    customer = customer_service.get_customer(db, user)
    rate_limit.hit(redis, "wallet_redeem", str(customer.id), 10, 3600)  # guessing protection
    out = wallet_service.redeem_code(db, customer, body.code, client)
    return RedeemOut(status=out.status.value, amount_paise=out.amount_paise, balance_paise=out.balance_paise,
                     error_code=out.error_code)


@router.get("/retailers/me/wallet", response_model=WalletOut)
def retailer_wallet(retailer: Retailer = Depends(get_current_retailer), db: Session = Depends(get_db)):
    return _wallet_out(db, WalletOwnerType.RETAILER, retailer.id)
