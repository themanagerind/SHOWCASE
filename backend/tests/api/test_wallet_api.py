from app.api.v1.wallet import the_manager_dep
from app.main import app
from tests.api.test_retailer_api import create_shop
from tests.conftest import auth
from tests.unit.test_wallet import FakeTheManager


def with_tm(tm):
    app.dependency_overrides[the_manager_dep] = lambda: tm


def test_redeem_and_view_wallet(client, login):
    with_tm(FakeTheManager())
    try:
        t = login()["access_token"]
        r = client.post("/api/v1/wallet/me/redeem", json={"code": "AB3DEFGH"}, headers=auth(t)).json()
        assert (r["status"], r["amount_paise"], r["balance_paise"]) == ("CREDITED", 150000, 150000)
        w = client.get("/api/v1/wallet/me", headers=auth(t)).json()
        assert w["balance_paise"] == 150000 and w["entries"][0]["entry_type"] == "CODE_REDEEMED"
        bad = client.post("/api/v1/wallet/me/redeem", json={"code": "AB3DEFGH"}, headers=auth(t))
        assert bad.status_code == 409 and bad.json()["error"] == "code_already_used"
    finally:
        app.dependency_overrides.pop(the_manager_dep, None)


def test_redeem_rate_limited(client, login):
    with_tm(FakeTheManager())
    try:
        t = login()["access_token"]
        codes = [f"WRONG{i:03d}" for i in range(11)]
        statuses = [client.post("/api/v1/wallet/me/redeem", json={"code": c}, headers=auth(t)).status_code for c in codes]
        assert statuses[:10] == [200] * 10 and statuses[10] == 429
    finally:
        app.dependency_overrides.pop(the_manager_dep, None)


def test_wallet_requires_login_and_retailer_wallet_starts_empty(client, login, db):
    assert client.get("/api/v1/wallet/me").status_code == 401
    token, _ = create_shop(client, login, db=db)
    w = client.get("/api/v1/retailers/me/wallet", headers=auth(token)).json()
    assert w == {"balance_paise": 0, "entries": []}
