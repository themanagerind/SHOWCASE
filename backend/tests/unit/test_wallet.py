"""SPEC 4.5 / 4.11 / section 11 'Wallet': code redemption and the points ledger."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import Conflict, DomainError
from app.models import WalletLedger, WalletRedemption
from app.models.enums import RedemptionStatus, WalletEntryType, WalletOwnerType
from app.services import wallet_service as ws
from app.services.the_manager import HttpTheManagerClient, TransientError, VerifyResult
from tests.factories import make_customer


class FakeTheManager:
    """Behaves like the agreed contract; can lose responses or fail N times."""

    def __init__(self, codes=None):
        self.codes = codes or {"AB3DEFGH": 150000, "SMALL100": 10000}
        self.used: dict[str, str] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_next = 0          # raise TransientError before doing anything
        self.lose_response_next = 0  # consume the code, then raise (response lost on the way back)
        self.outcome_override = None

    def verify(self, code, request_id):
        self.calls.append((code, request_id))
        if self.fail_next:
            self.fail_next -= 1
            raise TransientError("network down")
        if self.outcome_override:
            return VerifyResult(self.outcome_override)
        c = ws.normalise_code(code)
        if c not in self.codes:
            return VerifyResult("not_found")
        if c in self.used and self.used[c] != request_id:
            return VerifyResult("used")
        self.used[c] = request_id
        if self.lose_response_next:
            self.lose_response_next -= 1
            raise TransientError("timeout after commit")
        return VerifyResult("ok", self.codes[c])


def balance(db, customer):
    return ws.get_wallet(db, WalletOwnerType.CUSTOMER, customer.id).balance_paise


def test_valid_code_credits_full_amount_once(db):
    c, tm = make_customer(db), FakeTheManager()
    out = ws.redeem_code(db, c, "ab3d efgh", tm)  # case/space-insensitive
    assert (out.status, out.amount_paise, out.balance_paise) == (RedemptionStatus.CREDITED, 150000, 150000)
    w = ws.get_wallet(db, WalletOwnerType.CUSTOMER, c.id)
    assert ws.ledger_sum(db, w) == w.balance_paise == 150000
    entry = ws.ledger(db, w)[0]
    assert entry.entry_type == WalletEntryType.CODE_REDEEMED and entry.note.endswith("••••EFGH")


def test_raw_code_not_kept_after_settlement(db):
    c = make_customer(db)
    ws.redeem_code(db, c, "AB3DEFGH", FakeTheManager())
    r = db.scalar(select(WalletRedemption))
    assert r.code_sent == "" and "AB3DEFGH" not in r.code_hash and r.code_hint == "••••EFGH"


def test_unknown_code_rejected_nothing_credited(db):
    c = make_customer(db)
    out = ws.redeem_code(db, c, "ZZZZ9999", FakeTheManager())
    assert (out.status, out.error_code, out.balance_paise) == (RedemptionStatus.REJECTED, "invalid_code", 0)


def test_code_used_elsewhere_rejected(db):
    tm = FakeTheManager()
    tm.used["AB3DEFGH"] = "someone-elses-request"
    out = ws.redeem_code(db, make_customer(db), "AB3DEFGH", tm)
    assert (out.status, out.error_code) == (RedemptionStatus.REJECTED, "code_already_used")


def test_lost_response_is_retried_with_same_request_id_and_credited_once(db):
    c, tm = make_customer(db), FakeTheManager()
    tm.lose_response_next = 1
    out = ws.redeem_code(db, c, "AB3DEFGH", tm)
    assert out.status == RedemptionStatus.CREDITED and out.balance_paise == 150000
    assert len(tm.calls) == 2 and tm.calls[0][1] == tm.calls[1][1]  # same request_id both times
    assert tm.calls[0][1].startswith("showcase-redeem-")


def test_still_down_stays_pending_then_job_settles_it(db):
    c, tm = make_customer(db), FakeTheManager()
    tm.fail_next = ws.TRIES_PER_REQUEST
    out = ws.redeem_code(db, c, "AB3DEFGH", tm)
    assert (out.status, out.balance_paise) == (RedemptionStatus.PENDING, 0)
    first_request_id = tm.calls[0][1]
    res = ws.retry_pending(db, tm, older_than=timedelta(seconds=-1))
    assert res == {"retried": 1, "settled": 1, "failed": 0}
    assert balance(db, c) == 150000 and tm.calls[-1][1] == first_request_id


def test_customer_resubmitting_a_pending_code_reuses_the_attempt(db):
    c, tm = make_customer(db), FakeTheManager()
    tm.fail_next = ws.TRIES_PER_REQUEST
    ws.redeem_code(db, c, "AB3DEFGH", tm)
    ws.redeem_code(db, c, "AB3DEFGH", tm)
    assert len({rid for _, rid in tm.calls}) == 1
    assert db.query(WalletRedemption).count() == 1 and balance(db, c) == 150000


def test_code_already_credited_in_showcase_never_credited_twice(db):
    tm = FakeTheManager()
    ws.redeem_code(db, make_customer(db), "AB3DEFGH", tm)
    with pytest.raises(Conflict):
        ws.redeem_code(db, make_customer(db), "AB3DEFGH", tm)
    assert len(tm.calls) == 1  # THE-MANAGER not even asked


@pytest.mark.parametrize("outcome,code", [("unauthorized", "the_manager_unauthorized"), ("unavailable", "the_manager_unavailable")])
def test_integration_problems_are_errors_not_rejections(db, outcome, code):
    tm = FakeTheManager()
    tm.outcome_override = outcome
    out = ws.redeem_code(db, make_customer(db), "AB3DEFGH", tm)
    assert (out.status, out.error_code, out.balance_paise) == (RedemptionStatus.ERROR, code, 0)


def test_not_configured_and_bad_format(db):
    with pytest.raises(DomainError) as e:
        ws.redeem_code(db, make_customer(db), "AB3DEFGH", None)
    assert e.value.code == "wallet_unavailable"
    with pytest.raises(DomainError) as e:
        ws.redeem_code(db, make_customer(db), "ab!", FakeTheManager())
    assert e.value.code == "invalid_code_format"


def test_wallet_never_goes_negative_and_ledger_is_append_only(db):
    c = make_customer(db)
    ws.redeem_code(db, c, "SMALL100", FakeTheManager())
    w = ws.get_wallet(db, WalletOwnerType.CUSTOMER, c.id, lock=True)
    with pytest.raises(DomainError) as e:
        ws.post(db, w, WalletEntryType.BOOKING_HOLD, -10001)
    assert e.value.code == "insufficient_points" and w.balance_paise == 10000
    ws.post(db, w, WalletEntryType.BOOKING_HOLD, -10000)  # exactly the balance is fine
    assert ws.ledger_sum(db, w) == w.balance_paise == 0
    for stmt in ("UPDATE wallet_ledger SET amount_paise = 1", "DELETE FROM wallet_ledger"):
        with pytest.raises(DBAPIError, match="append-only"):
            with db.begin_nested():
                db.execute(text(stmt))
    with pytest.raises(DBAPIError):  # DB constraint backs up the service check
        with db.begin_nested():
            db.execute(text("UPDATE wallets SET balance_paise = -1 WHERE id = :i"), {"i": w.id})


# ---- the real HTTP client against the mock THE-MANAGER ------------------------------------------

def _wire(monkeypatch, app):
    tc = TestClient(app)
    monkeypatch.setattr("app.services.the_manager.httpx.post",
                        lambda url, json, headers, timeout: tc.post("/api/v1/wallet-redemptions/verify", json=json, headers=headers))


def test_http_client_follows_the_contract(monkeypatch):
    from scripts import mock_the_manager as mock

    mock.USED.clear()
    _wire(monkeypatch, mock.app)
    client = HttpTheManagerClient("http://tm", mock.KEY)
    ok = client.verify("demo1500", "rid-1")
    assert (ok.outcome, ok.amount_paise) == ("ok", 150000) and ok.used_at is not None
    assert client.verify("DEMO1500", "rid-1").outcome == "ok"      # same request_id: replay
    assert client.verify("DEMO1500", "rid-2").outcome == "used"    # different: 409
    assert client.verify("NOPE0000", "rid-3").outcome == "not_found"
    assert HttpTheManagerClient("http://tm", "wrong").verify("DEMO0500", "x").outcome == "unauthorized"


def test_http_client_rejects_float_amounts(monkeypatch):
    from fastapi import FastAPI

    bad = FastAPI()
    bad.post("/api/v1/wallet-redemptions/verify")(lambda: {"amount": 150.0, "amount_paise": 150.0, "used_at": None})
    _wire(monkeypatch, bad)
    with pytest.raises(TransientError):
        HttpTheManagerClient("http://tm", "k").verify("X", "r")


def test_lost_response_then_outage_keeps_redemption_pending_until_credited(db):
    """Security audit: timeout (code consumed remotely) followed by 503 must not end as ERROR (money lost)."""
    c = make_customer(db)
    tm = FakeTheManager()
    tm.lose_response_next = 1  # attempt 1: THE-MANAGER uses the code, response is lost

    real_verify = tm.verify

    def flaky(code, request_id):
        if len(tm.calls) == 1:  # attempt 2 of the same request: integration outage
            tm.calls.append((code, request_id))
            return VerifyResult("unavailable")
        return real_verify(code, request_id)

    tm.verify = flaky
    out = ws.redeem_code(db, c, "AB3DEFGH", tm)
    assert out.status == RedemptionStatus.PENDING and balance(db, c) == 0
    tm.verify = real_verify  # outage over: the job retries with the same request_id and THE-MANAGER replays 200
    ws.retry_pending(db, tm, older_than=timedelta(0))
    assert balance(db, c) == 150000
    assert len({rid for _, rid in tm.calls}) == 1


def test_odd_reply_never_blocks_the_retry_job(db):
    """Deep audit: one malformed THE-MANAGER answer must not crash the job for everyone after it."""
    c1, c2 = make_customer(db), make_customer(db)
    tm = FakeTheManager()
    tm.fail_next = 3
    ws.redeem_code(db, c1, "AB3DEFGH", tm)   # both stay PENDING (network down)
    tm.fail_next = 3
    ws.redeem_code(db, c2, "SMALL100", tm)
    calls = {"n": 0}
    real = tm.verify

    def broken_then_ok(code, rid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("garbage reply")  # an unexpected error, not a TransientError
        return real(code, rid)

    tm.verify = broken_then_ok
    res = ws.retry_pending(db, tm, older_than=timedelta(0))
    assert res["failed"] == 1 and res["settled"] == 1   # the second customer still got their points


def test_reply_with_odd_date_still_credits():
    import httpx

    def handler(request):
        return httpx.Response(200, json={"amount_paise": 5000, "used_at": "17/10/2026 16:43"})

    client = HttpTheManagerClient("http://tm", "k")
    from unittest import mock

    with mock.patch("httpx.post", lambda *a, **k: handler(None)):
        assert client.verify("DEMO0500", "r").outcome == "ok"
