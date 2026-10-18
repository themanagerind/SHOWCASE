"""SPEC 4.4 / 4.4a over HTTP: who may call what."""
from sqlalchemy import select

from app.models import Customer, User
from app.models.enums import WalletEntryType, WalletOwnerType
from app.services import wallet_service as ws
from tests.api.test_retailer_api import create_shop
from tests.conftest import auth
from tests.factories import product_data


def customer_with_points(client, login, db, phone, paise):
    t = login(phone)["access_token"]
    c = db.scalar(select(Customer).join(User).where(User.phone == "+91" + phone))
    w = ws.get_wallet(db, WalletOwnerType.CUSTOMER, c.id, lock=True)
    ws.post(db, w, WalletEntryType.CODE_REDEEMED, paise, reference_type="test", reference_id=None, note="t", user_id=None)
    db.commit()
    return t


def test_booking_flow_and_rbac(client, login, db, frozen):
    shop_t, _ = create_shop(client, login, db=db)
    pid = client.post("/api/v1/retailers/me/products", json=product_data(2), headers=auth(shop_t)).json()["id"]
    cust_t = customer_with_points(client, login, db, "9123456780", 5000)

    b = client.post("/api/v1/bookings", json={"product_id": pid}, headers=auth(cust_t))
    assert b.status_code == 201, b.text
    b = b.json()
    assert (b["status"], b["discount_paise"], b["shop_name"]) == ("RESERVED", 2000, "Sharma Electronics")

    # retailer sees it with the customer's contact, but cannot mark it purchased
    rb = client.get("/api/v1/retailers/me/bookings?status=RESERVED", headers=auth(shop_t)).json()
    assert [x["booking_no"] for x in rb] == [b["booking_no"]] and rb[0]["customer_phone"] == "+919123456780"
    assert client.post(f"/api/v1/bookings/{b['id']}/purchased", headers=auth(shop_t)).status_code in (403, 404)

    r = client.post(f"/api/v1/bookings/{b['id']}/purchased", headers=auth(cust_t))
    assert r.status_code == 200 and r.json()["status"] == "PURCHASED"
    assert client.get("/api/v1/retailers/me/wallet", headers=auth(shop_t)).json()["balance_paise"] == 2000
    assert client.get("/api/v1/wallet/me", headers=auth(cust_t)).json()["balance_paise"] == 3000

    # a plain customer has no retailer endpoints
    assert client.get("/api/v1/retailers/me/bookings", headers=auth(cust_t)).status_code in (403, 404)
    assert client.post("/api/v1/bookings", json={"product_id": pid}).status_code == 401


def test_retailer_cancel_and_insufficient_points(client, login, db, frozen):
    shop_t, _ = create_shop(client, login, db=db)
    pid = client.post("/api/v1/retailers/me/products", json=product_data(2), headers=auth(shop_t)).json()["id"]
    cust_t = customer_with_points(client, login, db, "9123456780", 3000)
    b = client.post("/api/v1/bookings", json={"product_id": pid}, headers=auth(cust_t)).json()
    r = client.post("/api/v1/bookings", json={"product_id": pid}, headers=auth(cust_t))
    assert r.status_code == 400 and r.json()["error"] == "insufficient_points"
    r = client.post(f"/api/v1/retailers/me/bookings/{b['id']}/cancel", json={"reason": "out of stock"}, headers=auth(shop_t))
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED_BY_RETAILER"
    assert client.get("/api/v1/wallet/me", headers=auth(cust_t)).json()["balance_paise"] == 3000
    mine = client.get("/api/v1/bookings/me", headers=auth(cust_t)).json()
    assert mine[0]["cancel_reason"] == "out of stock"


def test_unlisted_item_discount_over_http(client, login, db, frozen):
    shop_t, _ = create_shop(client, login, db=db)
    cust_t = customer_with_points(client, login, db, "9123456780", 3000)
    r = client.post("/api/v1/retailers/me/shop-discounts", json={"phone": "9123456780", "amount_paise": 1000,
                                                                  "note": "Ceiling fan"}, headers=auth(shop_t))
    assert r.status_code == 201, r.text
    assert "balance_paise" not in r.json()  # retailer never learns the customer's balance
    pending = client.get("/api/v1/shop-discounts/me", headers=auth(cust_t)).json()
    assert [(p["shop_name"], p["amount_paise"]) for p in pending] == [("Sharma Electronics", 1000)]
    # the retailer cannot accept on the customer's behalf
    assert client.post(f"/api/v1/shop-discounts/{pending[0]['id']}/accept", headers=auth(shop_t)).status_code == 404
    r = client.post(f"/api/v1/shop-discounts/{pending[0]['id']}/accept", headers=auth(cust_t))
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED"
    assert client.get("/api/v1/wallet/me", headers=auth(cust_t)).json()["balance_paise"] == 2000
    hist = client.get("/api/v1/retailers/me/shop-discounts", headers=auth(shop_t)).json()
    assert hist[0]["status"] == "CONFIRMED" and hist[0]["customer_phone"] == "+919123456780"
    r = client.post("/api/v1/retailers/me/shop-discounts", json={"phone": "9000011111", "amount_paise": 1000,
                                                                  "note": "x item"}, headers=auth(shop_t))
    assert r.status_code == 404 and r.json()["error"] == "customer_not_found"
