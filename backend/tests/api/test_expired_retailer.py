"""SPEC 5 status matrix / section 11: expired-retailer limited access (step 7)."""
import uuid
from datetime import timedelta

from sqlalchemy import update

from app.models import Subscription
from app.models.enums import SubscriptionStatus
from tests.api.test_bookings_api import customer_with_points
from tests.api.test_retailer_api import create_shop
from tests.conftest import auth
from tests.factories import product_data


def expire(db, shop_id):
    db.execute(update(Subscription).where(Subscription.retailer_id == uuid.UUID(shop_id))
               .values(status=SubscriptionStatus.EXPIRED))
    db.flush()


def setup(client, login, db):
    shop_t, shop = create_shop(client, login, db=db)
    pid = client.post("/api/v1/retailers/me/products", json=product_data(1), headers=auth(shop_t)).json()["id"]
    cust_t = customer_with_points(client, login, db, "9123456780", 5000)
    client.post("/api/v1/retailers/sharma-electronics/join", json={"source": "LINK"}, headers=auth(cust_t))
    b = client.post("/api/v1/bookings", json={"product_id": pid}, headers=auth(cust_t)).json()
    other_t = login("9123456781")["access_token"]
    return shop_t, shop, cust_t, other_t, pid, b


def test_customer_with_open_booking_gets_limited_view_only(client, login, db, frozen):
    shop_t, shop, cust_t, other_t, pid, b = setup(client, login, db)
    expire(db, shop["id"])

    assert client.get("/api/v1/retailers/sharma-electronics").status_code == 404  # public page hidden
    lv = client.get("/api/v1/bookings/shops/sharma-electronics", headers=auth(cust_t))
    assert lv.status_code == 200
    lv = lv.json()
    assert lv["live"] is False and lv["whatsapp_url"] and lv["address_line"] and "products" not in lv
    assert [x["booking_no"] for x in lv["bookings"]] == [b["booking_no"]]
    assert client.get("/api/v1/bookings/shops/sharma-electronics", headers=auth(other_t)).status_code == 404
    favs = client.get("/api/v1/customers/me/favourites", headers=auth(cust_t)).json()
    assert (favs[0]["available"], favs[0]["limited_view"]) == (False, True) and favs[0]["whatsapp_url"]

    # no new bookings, but the open one can still be completed
    r = client.post("/api/v1/bookings", json={"product_id": pid}, headers=auth(cust_t))
    assert r.status_code == 403 and r.json()["error"] == "shop_not_live"
    assert client.post(f"/api/v1/bookings/{b['id']}/purchased", headers=auth(cust_t)).json()["status"] == "PURCHASED"

    # booking closed -> limited view gone, favourite greyed without details
    assert client.get("/api/v1/bookings/shops/sharma-electronics", headers=auth(cust_t)).status_code == 404
    favs = client.get("/api/v1/customers/me/favourites", headers=auth(cust_t)).json()
    assert (favs[0]["available"], favs[0]["limited_view"], favs[0]["whatsapp_url"]) == (False, False, None)


def test_limited_view_ends_when_the_24h_pass(client, login, db, frozen):
    shop_t, shop, cust_t, other_t, pid, b = setup(client, login, db)
    expire(db, shop["id"])
    frozen.tick(timedelta(hours=24))
    cust_t = login("9123456780")["access_token"]
    assert client.get("/api/v1/bookings/shops/sharma-electronics", headers=auth(cust_t)).status_code == 404


def test_expired_retailer_keeps_bookings_loses_products_share_customers(client, login, db, frozen):
    shop_t, shop, cust_t, other_t, pid, b = setup(client, login, db)
    expire(db, shop["id"])
    for url in ("/api/v1/retailers/me/products", "/api/v1/retailers/me/share", "/api/v1/retailers/me/qr",
                "/api/v1/retailers/me/customers"):
        r = client.get(url, headers=auth(shop_t))
        assert r.status_code == 403 and r.json()["error"] == "subscription_required", url
    assert client.post("/api/v1/retailers/me/products", json=product_data(2), headers=auth(shop_t)).status_code == 403
    me = client.get("/api/v1/retailers/me", headers=auth(shop_t)).json()  # dashboard still opens
    assert (me["plan_code"], me["plan_expired"]) == (None, True)
    assert client.get("/api/v1/retailers/me/wallet", headers=auth(shop_t)).status_code == 200
    rb = client.get("/api/v1/retailers/me/bookings", headers=auth(shop_t)).json()
    assert [x["booking_no"] for x in rb] == [b["booking_no"]]
    r = client.post(f"/api/v1/retailers/me/bookings/{b['id']}/cancel", json={"reason": "closing"}, headers=auth(shop_t))
    assert r.status_code == 200 and client.get("/api/v1/wallet/me", headers=auth(cust_t)).json()["balance_paise"] == 5000

    # renewing restores everything; nothing was deleted
    db.execute(update(Subscription).where(Subscription.retailer_id == uuid.UUID(shop["id"]))
               .values(status=SubscriptionStatus.ACTIVE))
    db.flush()
    assert len(client.get("/api/v1/retailers/me/products", headers=auth(shop_t)).json()) == 1
    assert client.get("/api/v1/retailers/me/customers", headers=auth(shop_t)).json()["total"] == 1
    assert client.get("/api/v1/retailers/sharma-electronics").status_code == 200
    favs = client.get("/api/v1/customers/me/favourites", headers=auth(cust_t)).json()
    assert favs[0]["available"] is True
