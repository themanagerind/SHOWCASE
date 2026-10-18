"""Wallets and the points ledger (SPEC 4.5) + THE-MANAGER code redemption (SPEC 4.11).

Every balance change goes through `post()`, which locks the wallet row, refuses to go below zero and writes an
append-only ledger entry, so a wallet's balance always equals the sum of its ledger entries.
"""
import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.errors import Conflict, DomainError
from app.models import Customer, Wallet, WalletLedger, WalletRedemption
from app.models.enums import RedemptionStatus, WalletEntryType, WalletOwnerType
from app.services.the_manager import TheManagerClient, TransientError

TRIES_PER_REQUEST = 3  # immediate retries (same request_id) before leaving the redemption PENDING for the job
MAX_JOB_ATTEMPTS = 50


# ---- wallets & ledger ---------------------------------------------------------------------------

def get_wallet(db: Session, owner_type: WalletOwnerType, owner_id: uuid.UUID, lock: bool = False) -> Wallet:
    db.execute(insert(Wallet).values(owner_type=owner_type, owner_id=owner_id).on_conflict_do_nothing(
        index_elements=["owner_type", "owner_id"]))
    q = select(Wallet).where(Wallet.owner_type == owner_type, Wallet.owner_id == owner_id)
    if lock:
        q = q.with_for_update()
    return db.scalar(q.execution_options(populate_existing=True))


def post(db: Session, wallet: Wallet, entry_type: WalletEntryType, amount_paise: int, *, reference_type: str | None = None,
         reference_id: uuid.UUID | None = None, note: str | None = None, user_id: uuid.UUID | None = None) -> WalletLedger:
    """Caller must hold the wallet row lock (get_wallet(..., lock=True))."""
    new_balance = wallet.balance_paise + amount_paise
    if new_balance < 0:
        raise DomainError("Not enough points in the wallet", code="insufficient_points")
    wallet.balance_paise = new_balance
    entry = WalletLedger(wallet_id=wallet.id, entry_type=entry_type, amount_paise=amount_paise,
                         balance_after_paise=new_balance, reference_type=reference_type, reference_id=reference_id,
                         note=note, created_by_user_id=user_id)
    db.add(entry)
    db.flush()
    return entry


def ledger(db: Session, wallet: Wallet, limit: int = 50) -> list[WalletLedger]:
    return list(db.scalars(select(WalletLedger).where(WalletLedger.wallet_id == wallet.id)
                           .order_by(WalletLedger.created_at.desc(), WalletLedger.id.desc()).limit(limit)))


def ledger_sum(db: Session, wallet: Wallet) -> int:
    return db.scalar(select(func.coalesce(func.sum(WalletLedger.amount_paise), 0)).where(WalletLedger.wallet_id == wallet.id))


# ---- THE-MANAGER code redemption ----------------------------------------------------------------

CODE_RE = re.compile(r"^[A-Z0-9]{6,16}$")


def normalise_code(raw: str) -> str:
    return re.sub(r"[\s-]", "", raw or "").upper()


def code_hash(code: str) -> str:
    return hmac.new(get_settings().jwt_secret.encode(), f"tm-code:{code}".encode(), hashlib.sha256).hexdigest()


@dataclass
class RedeemOutcome:
    status: RedemptionStatus
    amount_paise: int | None
    balance_paise: int
    error_code: str | None = None


def _finalise(db: Session, redemption_id: uuid.UUID, client: TheManagerClient, tries: int) -> WalletRedemption:
    """Call THE-MANAGER with the saved request_id and settle the redemption. Safe to repeat."""
    r = db.scalar(select(WalletRedemption).where(WalletRedemption.id == redemption_id))
    if r.status != RedemptionStatus.PENDING:
        return r
    result = None
    for _ in range(tries):
        r.attempts += 1
        try:
            result = client.verify(r.code_sent, r.request_id)
            break
        except TransientError:
            continue
    db.commit()  # keep the attempt count even if we give up for now
    if result is None:
        return r  # still PENDING: the retry job will try again with the same request_id
    r = db.scalar(select(WalletRedemption).where(WalletRedemption.id == redemption_id).with_for_update()
                  .execution_options(populate_existing=True))
    if r.status != RedemptionStatus.PENDING:
        db.commit()
        return r
    if result.outcome == "ok":
        wallet = get_wallet(db, WalletOwnerType.CUSTOMER, r.customer_id, lock=True)
        post(db, wallet, WalletEntryType.CODE_REDEEMED, result.amount_paise, reference_type="redemption",
             reference_id=r.id, note=f"THE-MANAGER code {r.code_hint}")
        r.status, r.amount_paise, r.remote_used_at = RedemptionStatus.CREDITED, result.amount_paise, result.used_at
    elif result.outcome in ("not_found", "used"):
        r.status, r.error_code = RedemptionStatus.REJECTED, {"not_found": "invalid_code", "used": "code_already_used"}[result.outcome]
    else:  # unauthorized / unavailable: our integration problem, the code was not consumed
        r.status, r.error_code = RedemptionStatus.ERROR, f"the_manager_{result.outcome}"
    r.code_sent = ""  # the raw code is not kept once the redemption is final
    db.commit()
    return r


def redeem_code(db: Session, customer: Customer, raw_code: str, client: TheManagerClient | None) -> RedeemOutcome:
    if client is None:
        raise DomainError("Wallet codes cannot be redeemed right now", code="wallet_unavailable")
    code = normalise_code(raw_code)
    if not CODE_RE.match(code):
        raise DomainError("Please check the code", code="invalid_code_format")
    h = code_hash(code)
    if db.scalar(select(WalletRedemption.id).where(WalletRedemption.code_hash == h,
                                                   WalletRedemption.status == RedemptionStatus.CREDITED)):
        raise Conflict("This code has already been used", code="code_already_used")
    pending = db.scalar(select(WalletRedemption).where(
        WalletRedemption.customer_id == customer.id, WalletRedemption.code_hash == h,
        WalletRedemption.status == RedemptionStatus.PENDING))
    if pending is None:  # save first, so a lost response can be retried with the same request_id
        pending = WalletRedemption(customer_id=customer.id, code_hash=h, code_hint=f"••••{code[-4:]}",
                                   code_sent=raw_code.strip()[:32], request_id=f"showcase-redeem-{uuid.uuid4()}",
                                   status=RedemptionStatus.PENDING)
        db.add(pending)
        db.commit()
    r = _finalise(db, pending.id, client, TRIES_PER_REQUEST)
    wallet = get_wallet(db, WalletOwnerType.CUSTOMER, customer.id)
    db.commit()
    return RedeemOutcome(r.status, r.amount_paise, wallet.balance_paise, r.error_code)


def retry_pending(db: Session, client: TheManagerClient | None, older_than: timedelta = timedelta(minutes=1)) -> dict:
    """Background job: settle redemptions whose response was lost. Same request_id → THE-MANAGER replays."""
    if client is None:
        return {"retried": 0}
    ids = db.scalars(select(WalletRedemption.id).where(
        WalletRedemption.status == RedemptionStatus.PENDING, WalletRedemption.attempts < MAX_JOB_ATTEMPTS,
        WalletRedemption.created_at < clock.now() - older_than)).all()
    settled = sum(_finalise(db, rid, client, 1).status != RedemptionStatus.PENDING for rid in ids)
    return {"retried": len(ids), "settled": settled}
