"""SPEC 4.5 reward offers over HTTP: who may do what."""
from datetime import timedelta

from app.core import clock
from app.models.enums import WalletEntryType
from tests.api.test_retailer_api import create_shop
from tests.api.test_subscription_api import make_admin_token
from tests.conftest import auth
from tests.unit.test_rewards import earn


def body(start, days=1, threshold=1000):
    return {"name": "Week offer", "starts_at": start.isoformat(), "ends_at": (start + timedelta(days=days)).isoformat(),
            "threshold_paise": threshold, "percent_bp": 2000}


def test_reward_offer_flow_and_rbac(client, login, db, frozen):
    shop_t, shop = create_shop(client, login, db=db)
    support = make_admin_token(db, login, "9000000001", "SUPPORT")
    sa = make_admin_token(db, login, "9000000002", "SUPER_ADMIN")
    start = clock.now() - timedelta(hours=1)

    r = client.post("/api/v1/admin/reward-offers", json=body(start), headers=auth(support))
    assert r.status_code == 403 and r.json()["error"] == "super_admin_only"
    assert client.post("/api/v1/admin/reward-offers", json=body(start), headers=auth(shop_t)).status_code == 403
    o = client.post("/api/v1/admin/reward-offers", json=body(start), headers=auth(sa))
    assert o.status_code == 201 and o.json()["status"] == "RUNNING"
    oid = o.json()["id"]
    r = client.post("/api/v1/admin/reward-offers", json=body(start + timedelta(hours=2)), headers=auth(sa))
    assert r.status_code == 409 and r.json()["error"] == "offer_overlap"

    mine = client.get("/api/v1/retailers/me/reward-offer", headers=auth(shop_t)).json()
    assert mine["offer"]["id"] == oid and mine["joined"] is False
    mine = client.post(f"/api/v1/retailers/me/reward-offers/{oid}/join", headers=auth(shop_t)).json()
    assert mine["joined"] is True

    from app.models import Retailer
    import uuid
    retailer = db.get(Retailer, uuid.UUID(shop["id"]))
    earn(db, retailer, 1500)
    earn(db, retailer, 500, WalletEntryType.SHOP_DISCOUNT_RECEIVED)
    assert client.get("/api/v1/retailers/me/reward-offer", headers=auth(shop_t)).json()["collected_paise"] == 2000

    frozen.tick(timedelta(days=1))
    support, sa, shop_t = (login(p)["access_token"] for p in ("9000000001", "9000000002", "9876543210"))  # tokens expired
    d = client.get(f"/api/v1/admin/reward-offers/{oid}", headers=auth(support)).json()
    assert d["offer"]["status"] == "ENDED"
    row = d["standings"][0]
    assert (row["qualifies"], row["balance_at_end_paise"], row["payout_paise"]) == (True, 2000, 400)
    pay = {"retailer_id": shop["id"], "paid_on": "2026-10-19", "reference": "UPI 98765"}
    assert client.post(f"/api/v1/admin/reward-offers/{oid}/payouts", json=pay, headers=auth(shop_t)).status_code == 403
    r = client.post(f"/api/v1/admin/reward-offers/{oid}/payouts", json=pay, headers=auth(support))  # SUPPORT may record
    assert r.status_code == 201 and r.json()["standings"][0]["payout"]["reference"] == "UPI 98765"
    r = client.post(f"/api/v1/admin/reward-offers/{oid}/payouts", json=pay, headers=auth(support))
    assert r.status_code == 409 and r.json()["error"] == "payout_exists"
    assert client.get("/api/v1/retailers/me/wallet", headers=auth(shop_t)).json()["balance_paise"] == 0
    mine = client.get("/api/v1/retailers/me/reward-offer", headers=auth(shop_t)).json()
    assert mine["offer"] is None and mine["payouts"][0]["payout_paise"] == 400
    assert client.post(f"/api/v1/admin/reward-offers/{oid}/cancel", headers=auth(sa)).status_code == 409
