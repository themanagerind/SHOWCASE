"""SPEC 4.9 / section 11: analytics events and the retailer dashboard."""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from app.models import ShopEvent, Subscription
from app.services import analytics_service
from tests.api.test_bookings_api import customer_with_points
from tests.api.test_retailer_api import create_shop
from tests.conftest import auth
from tests.factories import product_data


def ev(client, event_type, anon="browser-aaaa1111", token=None, **kw):
    return client.post("/api/v1/events", json={"slug": "sharma-electronics", "event_type": event_type, "anon_id": anon, **kw},
                       headers=auth(token) if token else {})


def setup(client, login, db, plan="PRO"):
    t, s = create_shop(client, login, db=db, plan=plan)
    pid = client.post("/api/v1/retailers/me/products", json=product_data(1), headers=auth(t)).json()["id"]
    return t, s, pid


def test_views_deduped_own_visits_ignored_server_events_recorded(client, login, db, frozen):
    shop_t, s, pid = setup(client, login, db)
    assert ev(client, "shop_view").json()["counted"] is True
    assert ev(client, "shop_view").json()["counted"] is False  # same browser within 30 min
    frozen.tick(timedelta(minutes=30))
    assert ev(client, "shop_view").json()["counted"] is True
    assert ev(client, "shop_view", anon="browser-bbbb2222").json()["counted"] is True
    shop_t = login("9876543210")["access_token"]  # token expired with the clock tick
    assert ev(client, "shop_view", token=shop_t).json()["counted"] is False  # retailer's own visit
    assert ev(client, "whatsapp_click").json()["counted"] is True
    assert ev(client, "whatsapp_click").json()["counted"] is False  # clicks too: once per 30 min per visitor
    assert ev(client, "product_view", product_id=pid).json()["counted"] is True
    assert ev(client, "product_view", product_id=str(uuid.uuid4())).status_code == 400
    assert ev(client, "booking_confirmed").status_code == 422  # server-only events can't be sent
    assert ev(client, "shop_view", anon="bad id!").status_code == 400

    # favourite / booking events come from the backend itself
    cust = customer_with_points(client, login, db, "9123456780", 5000)
    client.post("/api/v1/retailers/sharma-electronics/join", json={"source": "QR"}, headers=auth(cust))
    client.post("/api/v1/retailers/sharma-electronics/join", json={"source": "QR"}, headers=auth(cust))  # not twice
    b = client.post("/api/v1/bookings", json={"product_id": pid}, headers=auth(cust)).json()
    client.post(f"/api/v1/bookings/{b['id']}/purchased", headers=auth(cust))
    types = dict(db.execute(select(ShopEvent.event_type, func.count()).group_by(ShopEvent.event_type)).all())
    assert {k.value: v for k, v in types.items()} == {
        "shop_view": 3, "whatsapp_click": 1, "product_view": 1, "favourite_add": 1, "booking_start": 1,
        "booking_confirmed": 1}
    assert db.scalar(select(func.count()).where(ShopEvent.lat.is_not(None))) == 0  # no location stored


def test_dashboard_numbers(client, login, db, frozen):
    shop_t, s, pid = setup(client, login, db)
    ev(client, "shop_view", anon="visitor-one-111")          # day 1: A
    ev(client, "product_view", anon="visitor-one-111", product_id=pid)
    frozen.tick(timedelta(days=1))
    ev(client, "shop_view", anon="visitor-one-111")          # day 2: A again -> returning
    ev(client, "shop_view", anon="visitor-two-222")          # day 2: B new
    ev(client, "call_click", anon="visitor-two-222")
    shop_t = login("9876543210")["access_token"]
    d = client.get("/api/v1/retailers/me/analytics?days=7", headers=auth(shop_t)).json()
    assert d["full"] is True and len(d["daily"]) == 7
    assert (d["visitors"], d["new_visitors"], d["returning_visitors"], d["shop_views"]) == (2, 1, 1, 3)
    assert [x["visitors"] for x in d["daily"][-2:]] == [1, 2]
    assert d["call_clicks"] == 1 and d["top_products"] == [{"product_id": pid, "name": "Product 1", "views": 1}]
    assert client.get("/api/v1/retailers/me/analytics?days=12", headers=auth(shop_t)).status_code == 400


def test_basic_plan_gets_teaser_and_expired_is_closed(client, login, db, frozen):
    shop_t, s, pid = setup(client, login, db, plan="BASIC")
    ev(client, "shop_view")
    ev(client, "shop_view", anon="browser-cccc3333")
    d = client.get("/api/v1/retailers/me/analytics?days=30", headers=auth(shop_t)).json()
    assert (d["full"], d["views_7d"], d["daily"], d["visitors"]) == (False, 2, [], 0)
    db.execute(update(Subscription).where(Subscription.retailer_id == uuid.UUID(s["id"])).values(status="EXPIRED"))
    db.flush()
    assert client.get("/api/v1/retailers/me/analytics", headers=auth(shop_t)).json()["error"] == "subscription_required"
    assert ev(client, "shop_view", anon="browser-dddd4444").status_code == 404  # hidden shop is not tracked


def test_purge_keeps_13_months(db, frozen):
    from tests.factories import make_shop
    shop = make_shop(db)
    now = datetime.fromisoformat("2026-10-17T10:00:00+00:00")
    for days in (30, 380, 400):
        db.add(ShopEvent(retailer_id=shop.id, event_type="shop_view", anon_id="x" * 10, meta={},
                         created_at=now - timedelta(days=days)))
    db.flush()
    assert analytics_service.purge_old(db, now) == 1  # only the 400-day-old one (> 13 months)
    assert db.scalar(select(func.count()).select_from(ShopEvent)) == 2



def test_fresh_anon_ids_cannot_flood_events_from_one_ip(client, login, db, frozen):
    """Security audit: rotating anon_id per request is capped per IP."""
    setup(client, login, db)
    codes = [ev(client, "whatsapp_click", anon=f"flood-{i:06d}").status_code for i in range(601)]
    assert codes[:600] == [200] * 600 and codes[600] == 429
