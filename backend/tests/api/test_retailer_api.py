import uuid

from fastapi import Depends
from sqlalchemy import select

from app.core.dependencies import require_plan
from app.main import app
from app.models import Retailer
from tests.conftest import auth
from tests.factories import make_subscription, product_data

SHOP = {
    "slug": "sharma-electronics",
    "shop_name": "Sharma Electronics",
    "category": "electronics",
    "address_line": "12 MG Road",
    "city": "  Indore ",
    "pincode": "452001",
    "lat": 22.7196,
    "lng": 75.8577,
    "whatsapp_number": "9876543210",
    "payment_link": "https://rzp.io/l/sharma",
    "upi_id": "sharma@okicici",
    "timings": {"mon": [["10:00", "20:00"]]},
}


def create_shop(client, login, phone="9876543210", plan="BASIC", db=None, **overrides):
    token = login(phone)["access_token"]
    r = client.post("/api/v1/retailers", json={**SHOP, **overrides}, headers=auth(token))
    assert r.status_code == 201, r.text
    if plan and db is not None:
        make_subscription(db, db.get(Retailer, uuid.UUID(r.json()["id"])), plan)
    return token, r.json()


def test_create_shop_adds_retailer_role_and_normalises_city(client, login, db):
    token, shop = create_shop(client, login, db=db)
    assert shop["city"] == "indore"
    assert shop["whatsapp_url"] == "https://wa.me/919876543210"
    assert shop["share_link"].endswith("/sharma-electronics?src=link")
    assert shop["subscription_status"] is None  # no free plan: nothing until a subscription exists
    me = client.get("/api/v1/retailers/me", headers=auth(token)).json()
    assert me["subscription_status"] == "ACTIVE" and me["plan_code"] == "BASIC"
    assert "retailer" in client.get("/api/v1/auth/me", headers=auth(token)).json()["roles"]


def test_one_shop_per_phone(client, login, db):
    token, _ = create_shop(client, login, db=db)
    r = client.post("/api/v1/retailers", json={**SHOP, "slug": "second-shop"}, headers=auth(token))
    assert r.status_code == 409 and r.json()["error"] == "shop_exists"


def test_slug_taken_and_reserved(client, login, db):
    create_shop(client, login, db=db)
    other = login("9123456789")["access_token"]
    assert client.post("/api/v1/retailers", json=SHOP, headers=auth(other)).json()["error"] == "slug_taken"
    r = client.post("/api/v1/retailers", json={**SHOP, "slug": "admin"}, headers=auth(other))
    assert r.json()["error"] == "slug_reserved"


def test_invalid_input_rejected(client, login):
    token = login()["access_token"]
    for bad in ({"pincode": "45200"}, {"lat": 51.5}, {"upi_id": "not-a-upi"}, {"timings": {"mon": [["20:00", "10:00"]]}},
                {"advance_type": "PERCENT", "advance_value": 150}):
        assert client.post("/api/v1/retailers", json={**SHOP, **bad}, headers=auth(token)).status_code == 422


def test_public_storefront_needs_live_subscription(client, login, db):
    create_shop(client, login, plan=None, db=db)
    assert client.get("/api/v1/retailers/sharma-electronics").status_code == 404
    shop = db.scalar(select(Retailer).where(Retailer.slug == "sharma-electronics"))
    make_subscription(db, shop, "BASIC")
    r = client.get("/api/v1/retailers/Sharma-Electronics")
    assert r.status_code == 200
    assert r.json()["shop"]["shop_name"] == "Sharma Electronics"


def test_expired_shop_not_public_and_cannot_add_products(client, login, db):
    token, _ = create_shop(client, login, plan=None, db=db)
    make_subscription(db, db.scalar(select(Retailer)), "BASIC", status="EXPIRED")
    assert client.get("/api/v1/retailers/sharma-electronics").status_code == 404
    r = client.post("/api/v1/retailers/me/products", json=product_data(), headers=auth(token))
    assert r.status_code == 403 and r.json()["error"] == "subscription_required"


def test_product_crud_and_public_listing(client, login, db, frozen):
    token, _ = create_shop(client, login, db=db)
    ids = [client.post("/api/v1/retailers/me/products", json=product_data(i), headers=auth(token)).json()["id"]
           for i in range(1, 6)]
    r = client.post("/api/v1/retailers/me/products", json=product_data(6), headers=auth(token))
    assert r.status_code == 403 and r.json()["error"] == "product_limit"

    r = client.post("/api/v1/retailers/me/products/swap", json={"remove": ids[:2], "add": [product_data(7)]},
                    headers=auth(token))
    assert r.status_code == 200 and r.json()["locked_until"] is not None

    me = client.get("/api/v1/retailers/me", headers=auth(token)).json()
    assert me["can_change_products_now"] is False and me["products_locked_until"] is not None

    assert client.delete(f"/api/v1/retailers/me/products/{ids[2]}", headers=auth(token)).json()["error"] == "weekly_lock"
    r = client.patch(f"/api/v1/retailers/me/products/{ids[2]}", json={"price_paise": 999, "stock_qty": 1},
                     headers=auth(token))
    assert r.status_code == 200 and r.json()["price_paise"] == 999

    public = client.get("/api/v1/retailers/sharma-electronics").json()["products"]
    assert len(public) == 4


def test_unknown_edit_field_rejected(client, login, db):
    token, _ = create_shop(client, login, db=db)
    pid = client.post("/api/v1/retailers/me/products", json=product_data(), headers=auth(token)).json()["id"]
    r = client.patch(f"/api/v1/retailers/me/products/{pid}", json={"is_active": False}, headers=auth(token))
    assert r.status_code == 422


def test_retailer_cannot_touch_another_retailers_products(client, login, db):
    token_a, _ = create_shop(client, login, "9876543210", db=db)
    token_b, _ = create_shop(client, login, "9123456789", db=db, slug="verma-store")
    pid = client.post("/api/v1/retailers/me/products", json=product_data(), headers=auth(token_a)).json()["id"]

    assert client.patch(f"/api/v1/retailers/me/products/{pid}", json={"price_paise": 1},
                        headers=auth(token_b)).status_code == 404
    assert client.delete(f"/api/v1/retailers/me/products/{pid}", headers=auth(token_b)).status_code == 404
    r = client.post("/api/v1/retailers/me/products/swap", json={"remove": [pid]}, headers=auth(token_b))
    assert r.status_code == 404
    assert client.get("/api/v1/retailers/me/products", headers=auth(token_b)).json() == []


def test_customer_without_shop_gets_404_on_retailer_endpoints(client, login):
    token = login()["access_token"]
    r = client.get("/api/v1/retailers/me", headers=auth(token))
    assert r.status_code == 404 and r.json()["error"] == "no_shop"


def test_qr_and_share(client, login, db):
    token, _ = create_shop(client, login, db=db)
    r = client.get("/api/v1/retailers/me/qr", headers=auth(token))
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    share = client.get("/api/v1/retailers/me/share", headers=auth(token)).json()
    assert share["qr_link"].endswith("?src=qr")
    assert share["whatsapp_share_url"].startswith("https://wa.me/?text=")


def test_require_plan_returns_403_for_feature_outside_plan(client, login, db):
    @app.get("/_test/analytics")
    def _probe(_=Depends(require_plan("analytics"))):
        return {"ok": True}

    try:
        token_basic, _ = create_shop(client, login, "9876543210", plan="BASIC", db=db)
        token_pro, _ = create_shop(client, login, "9123456789", plan="PRO", db=db, slug="pro-shop")
        r = client.get("/_test/analytics", headers=auth(token_basic))
        assert r.status_code == 403 and r.json()["error"] == "plan_feature_missing"
        assert client.get("/_test/analytics", headers=auth(token_pro)).status_code == 200
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/_test/analytics"]
