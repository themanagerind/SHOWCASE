"""Security audit: input validation (photos, timings, nulls, offsets, expired edits, admin search)."""
import uuid

from sqlalchemy import update

from app.models import Subscription
from tests.api.test_retailer_api import SHOP, create_shop
from tests.api.test_subscription_api import make_admin_token
from tests.conftest import auth
from tests.factories import product_data


def test_photos_must_be_short_https_links(client, login, db):
    t = login()["access_token"]
    for bad in ["javascript:alert(1)", "data:text/html,<script>x</script>", "http://plain.example/a.jpg",
                "https://x.example/" + "a" * 600]:
        r = client.post("/api/v1/retailers", json={**SHOP, "photos": [bad]}, headers=auth(t))
        assert r.status_code == 422, bad
    token, _ = create_shop(client, login, db=db, phone="9876543211", slug="ok-shop", photos=["https://cdn.example/a.jpg"])
    r = client.post("/api/v1/retailers/me/products", json=product_data(1, photos=["javascript:x"]), headers=auth(token))
    assert r.status_code == 422


def test_timings_are_bounded(client, login, db):
    token, _ = create_shop(client, login, db=db)
    r = client.patch("/api/v1/retailers/me", json={"timings": {"mon": [["09:00", "10:00"]] * 5}}, headers=auth(token))
    assert r.status_code == 422


def test_null_for_required_fields_is_422_not_500(client, login, db):
    token, _ = create_shop(client, login, db=db)
    pid = client.post("/api/v1/retailers/me/products", json=product_data(1), headers=auth(token)).json()["id"]
    for url, body in [("/api/v1/retailers/me", {"shop_name": None}), ("/api/v1/retailers/me", {"photos": None}),
                      (f"/api/v1/retailers/me/products/{pid}", {"price_paise": None}),
                      ("/api/v1/customers/me", {"name": None})]:
        assert client.patch(url, json=body, headers=auth(token)).status_code == 422, (url, body)
    # optional fields can still be cleared
    assert client.patch("/api/v1/retailers/me", json={"description": None}, headers=auth(token)).status_code == 200


def test_huge_offset_is_rejected(client):
    r = client.get("/api/v1/discovery/shops", params={"lat": 22.7, "lng": 75.8, "offset": 10**20})
    assert r.status_code == 422


def test_expired_retailer_cannot_edit_products(client, login, db):
    token, shop = create_shop(client, login, db=db)
    pid = client.post("/api/v1/retailers/me/products", json=product_data(1), headers=auth(token)).json()["id"]
    db.execute(update(Subscription).where(Subscription.retailer_id == uuid.UUID(shop["id"])).values(status="EXPIRED"))
    db.flush()
    r = client.patch(f"/api/v1/retailers/me/products/{pid}", json={"price_paise": 5000}, headers=auth(token))
    assert r.status_code == 403 and r.json()["error"] == "subscription_required"


def test_admin_search_treats_percent_literally(client, login, db):
    create_shop(client, login, db=db)
    admin = make_admin_token(db, login, "9000000001", "SUPPORT")
    assert client.get("/api/v1/admin/retailers", params={"q": "%"}, headers=auth(admin)).json()["total"] == 0
    assert client.get("/api/v1/admin/retailers", params={"q": "sharma"}, headers=auth(admin)).json()["total"] == 1
