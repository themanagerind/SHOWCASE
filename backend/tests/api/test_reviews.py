"""SPEC 4.7 / section 11 'Ratings'."""
from datetime import timedelta

from app.models import Retailer
from tests.api.test_bookings_api import customer_with_points
from tests.api.test_retailer_api import create_shop
from tests.api.test_subscription_api import make_admin_token
from tests.conftest import auth
from tests.factories import product_data


def bought(client, login, db, phone="9123456780", name=None):
    """A customer with one purchased booking at sharma-electronics. Returns (cust_token, booking_id)."""
    t = customer_with_points(client, login, db, phone, 10000)
    if name:
        client.patch("/api/v1/customers/me", json={"name": name}, headers=auth(t))
    pid = client.get("/api/v1/retailers/sharma-electronics").json()["products"][0]["id"]
    b = client.post("/api/v1/bookings", json={"product_id": pid}, headers=auth(t)).json()
    assert client.post(f"/api/v1/bookings/{b['id']}/purchased", headers=auth(t)).status_code == 200
    return t, b["id"]


def shop(client, login, db):
    t, s = create_shop(client, login, db=db)
    client.post("/api/v1/retailers/me/products", json=product_data(1), headers=auth(t))
    return t, s


def rate(client, t, sid, rating, comment=None, source="BOOKING"):
    return client.post("/api/v1/reviews", json={"source_type": source, "source_id": sid, "rating": rating,
                                                "comment": comment}, headers=auth(t))


def test_rate_after_purchase_updates_average_and_public_name(client, login, db, frozen):
    shop_t, s = shop(client, login, db)
    t1, b1 = bought(client, login, db, "9123456780", "Ravi Kumar Verma")
    t2, b2 = bought(client, login, db, "9123456781", "Sita")
    assert rate(client, t1, b1, 5, "Great service").status_code == 200
    assert rate(client, t2, b2, 4).status_code == 200
    pub = client.get("/api/v1/retailers/sharma-electronics/reviews").json()
    assert (pub["rating_avg"], pub["rating_count"]) == (4.5, 2)
    assert {r["author"] for r in pub["reviews"]} == {"Ravi V.", "Sita"}
    assert "9123456780" not in str(pub)
    # rateable list shows the existing rating, and editing within 30 days changes the average
    items = client.get("/api/v1/reviews/me/rateable", headers=auth(t1)).json()
    assert (items[0]["rating"], items[0]["shop_name"]) == (5, "Sharma Electronics")
    rate(client, t1, b1, 2, "Changed my mind")
    pub = client.get("/api/v1/retailers/sharma-electronics/reviews").json()
    assert (pub["rating_avg"], pub["rating_count"]) == (3.0, 2)  # still one review per purchase
    assert client.get("/api/v1/retailers/sharma-electronics").json()["shop"]["rating_count"] == 2


def test_only_own_completed_purchases_within_30_days(client, login, db, frozen):
    shop(client, login, db)
    t, b = bought(client, login, db)
    other = login("9123456789")["access_token"]
    assert rate(client, other, b, 5).json()["error"] == "purchase_not_found"
    # reserved but not bought -> cannot rate
    pid = client.get("/api/v1/retailers/sharma-electronics").json()["products"][0]["id"]
    open_b = client.post("/api/v1/bookings", json={"product_id": pid}, headers=auth(t)).json()
    assert rate(client, t, open_b["id"], 5).json()["error"] == "purchase_not_found"
    assert rate(client, t, b, 6).status_code == 422
    frozen.tick(timedelta(days=30))
    t = login("9123456780")["access_token"]
    assert rate(client, t, b, 5).json()["error"] == "review_window_closed"
    assert client.get("/api/v1/reviews/me/rateable", headers=auth(t)).json() == []


def test_unlisted_item_discount_can_be_rated(client, login, db, frozen):
    shop_t, _ = shop(client, login, db)
    t = customer_with_points(client, login, db, "9123456780", 5000)
    req = client.post("/api/v1/retailers/me/shop-discounts", json={"phone": "9123456780", "amount_paise": 1000,
                                                                     "note": "Table fan"}, headers=auth(shop_t)).json()
    assert rate(client, t, req["id"], 4, source="SHOP_DISCOUNT").json()["error"] == "purchase_not_found"  # not confirmed
    client.post(f"/api/v1/shop-discounts/{req['id']}/accept", headers=auth(t))
    assert rate(client, t, req["id"], 4, source="SHOP_DISCOUNT").status_code == 200
    assert client.get("/api/v1/reviews/me/rateable", headers=auth(t)).json()[0]["label"] == "Table fan"


def test_flag_and_admin_hide_or_keep(client, login, db, frozen):
    shop_t, s = shop(client, login, db)
    t1, b1 = bought(client, login, db, "9123456780", "Ravi")
    t2, b2 = bought(client, login, db, "9123456781", "Amit")
    r1 = rate(client, t1, b1, 1, "abusive words").json()
    r2 = rate(client, t2, b2, 5, "nice").json()
    other_shop_t, _ = create_shop(client, login, phone="9000000777", db=db, slug="other-shop")
    assert client.post(f"/api/v1/retailers/me/reviews/{r1['id']}/flag", json={"reason": "abuse"},
                       headers=auth(other_shop_t)).status_code == 404  # not their review
    for rid in (r1["id"], r2["id"]):
        assert client.post(f"/api/v1/retailers/me/reviews/{rid}/flag", json={"reason": "abusive language"},
                           headers=auth(shop_t)).json()["is_flagged"] is True
    support = make_admin_token(db, login, "9000000001", "SUPPORT")  # any admin role may moderate
    q = client.get("/api/v1/admin/reviews/flagged", headers=auth(support)).json()
    assert {x["id"] for x in q} == {r1["id"], r2["id"]} and q[0]["shop_name"] == "Sharma Electronics"
    assert client.get("/api/v1/admin/reviews/flagged", headers=auth(shop_t)).status_code == 403
    client.post(f"/api/v1/admin/reviews/{r1['id']}/resolve", json={"action": "HIDE"}, headers=auth(support))
    client.post(f"/api/v1/admin/reviews/{r2['id']}/resolve", json={"action": "KEEP"}, headers=auth(support))
    pub = client.get("/api/v1/retailers/sharma-electronics/reviews").json()
    assert (pub["rating_avg"], pub["rating_count"], [r["id"] for r in pub["reviews"]]) == (5.0, 1, [r2["id"]])
    assert db.get(Retailer, __import__("uuid").UUID(s["id"])).rating_count == 1
    assert client.get("/api/v1/admin/reviews/flagged", headers=auth(support)).json() == []
    # resolved: cannot be flagged again; the retailer still sees the hidden one, marked hidden
    assert client.post(f"/api/v1/retailers/me/reviews/{r2['id']}/flag", json={"reason": "again"},
                       headers=auth(shop_t)).json()["error"] == "review_resolved"
    own = {r["id"]: r for r in client.get("/api/v1/retailers/me/reviews", headers=auth(shop_t)).json()}
    assert own[r1["id"]]["is_hidden"] is True and own[r2["id"]]["is_hidden"] is False
    # editing a hidden review keeps it hidden and out of the average
    rate(client, t1, b1, 5, "edited")
    assert client.get("/api/v1/retailers/sharma-electronics/reviews").json()["rating_count"] == 1
