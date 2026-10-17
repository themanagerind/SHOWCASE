from tests.api.test_customer_api import join, setup_shop
from tests.conftest import auth

URL = "/api/v1/discovery/shops"
GPS = {"lat": 22.7196, "lng": 75.8577}


def test_anonymous_with_gps_sees_only_matching_scopes(client, login, db):
    setup_shop(client, login, db, plan="BASIC")  # sharma-electronics, pincode 452001, at GPS point
    r = client.get(URL, params=GPS)
    assert r.status_code == 200 and r.json()["items"] == []  # BASIC needs a pincode match
    r = client.get(URL, params={**GPS, "pincode": "452001"})
    item = r.json()["items"][0]
    assert item["slug"] == "sharma-electronics" and item["distance_m"] == 0 and item["is_favourite"] is False


def test_logged_in_customer_uses_profile_and_sees_favourite_flag(client, login, db):
    setup_shop(client, login, db, plan="BASIC")
    cust = login("9123456789")["access_token"]
    client.patch("/api/v1/customers/me", json={"pincode": "452001", "city": "Indore", "search_radius_km": 2},
                 headers=auth(cust))
    join(client, cust)
    # Query-string pincode is ignored for logged-in customers: the profile wins.
    r = client.get(URL, params={**GPS, "pincode": "110001"}, headers=auth(cust)).json()
    assert r["radius_km"] == 2 and r["used_location"] is True
    assert r["items"][0]["is_favourite"] is True


def test_without_gps_and_profile_returns_400(client, login):
    cust = login("9123456789")["access_token"]
    r = client.get(URL, headers=auth(cust))
    assert r.status_code == 400 and r.json()["error"] == "location_required"


def test_invalid_radius_rejected(client):
    assert client.get(URL, params={**GPS, "radius_km": 7}).json()["error"] == "invalid_radius"
    r = client.patch("/api/v1/customers/me", json={"search_radius_km": 7})
    assert r.status_code in (401, 422)


def test_radius_saved_in_profile(client, login):
    cust = login("9123456789")["access_token"]
    assert client.get("/api/v1/customers/me", headers=auth(cust)).json()["search_radius_km"] == 5
    r = client.patch("/api/v1/customers/me", json={"search_radius_km": 25}, headers=auth(cust))
    assert r.json()["search_radius_km"] == 25
    assert client.patch("/api/v1/customers/me", json={"search_radius_km": 7}, headers=auth(cust)).status_code == 422


def test_bad_token_is_401_not_anonymous(client):
    assert client.get(URL, params=GPS, headers=auth("garbage")).status_code == 401


def test_product_search_api(client, login, db):
    from sqlalchemy import select

    from app.models import Plan, Retailer, Subscription

    token, _ = __import__("tests.api.test_retailer_api", fromlist=["create_shop"]).create_shop(
        client, login, "9876543210", plan="PREMIUM", db=db
    )
    client.post("/api/v1/retailers/me/products",
                json={"name": "Bajaj Mixer Grinder", "price_paise": 349900, "wallet_discount_paise": 20000, "stock_qty": 0},
                headers=auth(token))
    r = client.get("/api/v1/discovery/products", params={"q": "mixar", **GPS})
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["name"] == "Bajaj Mixer Grinder" and item["shop_slug"] == "sharma-electronics"
    assert item["in_stock"] is False and item["wallet_discount_paise"] == 20000 and item["distance_m"] == 0
    assert client.get("/api/v1/discovery/products", params={"q": "m"}).status_code == 422
    # Downgrade to BASIC: no longer in product search
    shop = db.scalar(select(Retailer).where(Retailer.slug == "sharma-electronics"))
    db.scalar(select(Subscription).where(Subscription.retailer_id == shop.id)).plan_id = db.scalar(
        select(Plan.id).where(Plan.code == "BASIC"))
    db.flush()
    assert client.get("/api/v1/discovery/products", params={"q": "mixer", **GPS}).json()["items"] == []
