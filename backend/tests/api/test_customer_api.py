"""SPEC 4.2: customer joins via retailer link/QR, favourites, retailer's customer list, consent."""
from datetime import timedelta

from sqlalchemy import select

from app.models import Retailer
from tests.api.test_retailer_api import create_shop
from tests.conftest import auth

SHOP_PHONE, CUST_PHONE, CUST2_PHONE = "9876543210", "9123456789", "9988776655"


def setup_shop(client, login, db, plan="BASIC", **kw):
    token, _ = create_shop(client, login, SHOP_PHONE, plan=plan, db=db, **kw)
    return token


def join(client, token, slug="sharma-electronics", source="LINK"):
    return client.post(f"/api/v1/retailers/{slug}/join", json={"source": source}, headers=auth(token))


def test_join_via_link_adds_favourite_with_source(client, login, db):
    shop_token = setup_shop(client, login, db)
    cust = login(CUST_PHONE)["access_token"]
    r = join(client, cust, source="LINK")
    assert r.status_code == 200 and r.json()["source"] == "LINK"
    favs = client.get("/api/v1/customers/me/favourites", headers=auth(cust)).json()
    assert [f["slug"] for f in favs] == ["sharma-electronics"]
    assert favs[0]["whatsapp_url"] == "https://wa.me/919876543210"
    customers = client.get("/api/v1/retailers/me/customers", headers=auth(shop_token)).json()
    assert customers["total"] == 1 and customers["items"][0]["source"] == "LINK"


def test_join_via_qr_records_qr(client, login, db):
    setup_shop(client, login, db)
    cust = login(CUST_PHONE)["access_token"]
    assert join(client, cust, source="QR").json()["source"] == "QR"


def test_rejoin_is_idempotent_and_keeps_first_source(client, login, db):
    shop_token = setup_shop(client, login, db)
    cust = login(CUST_PHONE)["access_token"]
    join(client, cust, source="QR")
    assert join(client, cust, source="LINK").json()["source"] == "QR"
    assert client.get("/api/v1/retailers/me/customers", headers=auth(shop_token)).json()["total"] == 1


def test_unfavourite_keeps_customer_in_retailer_list(client, login, db):
    shop_token = setup_shop(client, login, db)
    cust = login(CUST_PHONE)["access_token"]
    join(client, cust)
    assert client.delete("/api/v1/customers/me/favourites/sharma-electronics", headers=auth(cust)).status_code == 204
    assert client.get("/api/v1/customers/me/favourites", headers=auth(cust)).json() == []
    items = client.get("/api/v1/retailers/me/customers", headers=auth(shop_token)).json()["items"]
    assert len(items) == 1 and items[0]["is_favourite"] is False
    # Joining again restores the favourite, original source kept
    assert join(client, cust, source="QR").json()["source"] == "LINK"
    assert len(client.get("/api/v1/customers/me/favourites", headers=auth(cust)).json()) == 1


def test_add_favourite_from_app_uses_discovery_source(client, login, db):
    setup_shop(client, login, db)
    cust = login(CUST_PHONE)["access_token"]
    r = client.post("/api/v1/customers/me/favourites/sharma-electronics", headers=auth(cust))
    assert r.status_code == 201 and r.json()["source"] == "DISCOVERY"


def test_cannot_join_shop_without_live_subscription(client, login, db):
    setup_shop(client, login, db, plan=None)
    cust = login(CUST_PHONE)["access_token"]
    assert join(client, cust).status_code == 404
    assert join(client, cust, slug="no-such-shop").status_code == 404


def test_expired_shop_disappears_from_favourites(client, login, db):
    setup_shop(client, login, db)
    cust = login(CUST_PHONE)["access_token"]
    join(client, cust)
    shop = db.scalar(select(Retailer).where(Retailer.slug == "sharma-electronics"))
    from app.models import Subscription
    from app.models.enums import SubscriptionStatus

    db.scalar(select(Subscription).where(Subscription.retailer_id == shop.id)).status = SubscriptionStatus.EXPIRED
    db.flush()
    assert client.get("/api/v1/customers/me/favourites", headers=auth(cust)).json() == []


def test_retailer_cannot_join_own_shop(client, login, db):
    shop_token = setup_shop(client, login, db)
    r = join(client, shop_token)
    assert r.status_code == 400 and r.json()["error"] == "own_shop"


def test_phone_hidden_without_consent_and_shown_with_consent(client, login, db):
    shop_token = setup_shop(client, login, db)
    cust = login(CUST_PHONE)["access_token"]
    join(client, cust)
    item = client.get("/api/v1/retailers/me/customers", headers=auth(shop_token)).json()["items"][0]
    assert item["phone"] == "91XXXXXX89" and item["contact_consent"] is False

    client.patch("/api/v1/customers/me", json={"contact_consent": True}, headers=auth(cust))
    item = client.get("/api/v1/retailers/me/customers", headers=auth(shop_token)).json()["items"][0]
    assert item["phone"] == "+919123456789"

    client.patch("/api/v1/customers/me", json={"contact_consent": False}, headers=auth(cust))
    item = client.get("/api/v1/retailers/me/customers", headers=auth(shop_token)).json()["items"][0]
    assert item["phone"] == "91XXXXXX89"


def test_consent_is_off_by_default_and_timestamped(client, login, frozen):
    cust = login(CUST_PHONE)["access_token"]
    me = client.get("/api/v1/customers/me", headers=auth(cust)).json()
    assert me["contact_consent"] is False and me["consent_at"] is None and me["profile_complete"] is False

    me = client.patch("/api/v1/customers/me", json={
        "name": "Ravi", "pincode": "452001", "city": " Indore ", "preferred_language": "hi", "contact_consent": True,
    }, headers=auth(cust)).json()
    assert me["consent_at"].startswith("2026-10-17T10:00:00")
    assert (me["city"], me["preferred_language"], me["profile_complete"]) == ("indore", "hi", True)

    frozen.tick(timedelta(minutes=10))
    me = client.patch("/api/v1/customers/me", json={"contact_consent": True}, headers=auth(cust)).json()
    assert me["consent_at"].startswith("2026-10-17T10:00:00")  # unchanged when consent was already given
    me = client.patch("/api/v1/customers/me", json={"contact_consent": False}, headers=auth(cust)).json()
    assert me["contact_consent"] is False and me["consent_at"] is None


def test_invalid_profile_rejected(client, login):
    cust = login(CUST_PHONE)["access_token"]
    for bad in ({"pincode": "012345"}, {"preferred_language": "fr"}, {"name": "A"}):
        assert client.patch("/api/v1/customers/me", json=bad, headers=auth(cust)).status_code == 422


def test_customers_and_retailers_only_see_their_own_data(client, login, db):
    shop_a = setup_shop(client, login, db)
    shop_b, _ = create_shop(client, login, "9000000001", plan="BASIC", db=db, slug="verma-store")
    c1 = login(CUST_PHONE)["access_token"]
    c2 = login(CUST2_PHONE)["access_token"]
    join(client, c1)
    join(client, c2, slug="verma-store")

    assert [f["slug"] for f in client.get("/api/v1/customers/me/favourites", headers=auth(c1)).json()] == [
        "sharma-electronics"
    ]
    assert [f["slug"] for f in client.get("/api/v1/customers/me/favourites", headers=auth(c2)).json()] == [
        "verma-store"
    ]
    a_list = client.get("/api/v1/retailers/me/customers", headers=auth(shop_a)).json()
    b_list = client.get("/api/v1/retailers/me/customers", headers=auth(shop_b)).json()
    assert a_list["total"] == 1 and b_list["total"] == 1
    assert a_list["items"][0]["customer_id"] != b_list["items"][0]["customer_id"]
    # c2 cannot remove a favourite it never had
    assert client.delete("/api/v1/customers/me/favourites/sharma-electronics", headers=auth(c2)).status_code == 404
    # a plain customer has no retailer customer list
    assert client.get("/api/v1/retailers/me/customers", headers=auth(c1)).status_code == 404


def test_join_requires_login(client, login, db):
    setup_shop(client, login, db)
    assert client.post("/api/v1/retailers/sharma-electronics/join", json={"source": "LINK"}).status_code == 401


def test_retailer_customer_list_paginates(client, login, db):
    shop_token = setup_shop(client, login, db)
    for i in range(3):
        join(client, login(f"90000000{10 + i}")["access_token"])
    page = client.get("/api/v1/retailers/me/customers?limit=2&offset=0", headers=auth(shop_token)).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    page2 = client.get("/api/v1/retailers/me/customers?limit=2&offset=2", headers=auth(shop_token)).json()
    assert len(page2["items"]) == 1
