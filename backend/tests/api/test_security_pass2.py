"""Security audit pass 2: regressions for the bypasses that were found."""
from sqlalchemy import select

from app.models import AdminUser, User
from app.models.enums import AdminRole
from tests.api.test_bookings_api import customer_with_points
from tests.api.test_retailer_api import create_shop
from tests.api.test_reviews import bought, rate, shop
from tests.api.test_subscription_api import make_admin_token
from tests.conftest import auth
from tests.factories import product_data


def test_manual_reference_variants_are_the_same_payment(client, login, db):
    _, s = create_shop(client, login, db=db, plan=None)
    support = make_admin_token(db, login, "9000000001", "SUPPORT")
    url = f"/api/v1/admin/retailers/{s['id']}/payments"
    body = {"plan_code": "BASIC", "billing_cycle": "MONTHLY"}
    assert client.post(url, json={**body, "reference": "UTR123456"}, headers=auth(support)).status_code == 201
    for variant in ("utr123456", "UTR 123456", "UTR123456​", "ＵＴＲ123456"):
        r = client.post(url, json={**body, "reference": variant}, headers=auth(support))
        assert r.status_code == 409, variant


def test_admin_cannot_act_on_own_shop(client, login, db, frozen):
    shop_t, s = create_shop(client, login, db=db)  # the shop owner ...
    owner = db.scalar(select(User).where(User.phone == "+919876543210"))
    db.add(AdminUser(user_id=owner.id, role=AdminRole.SUPER_ADMIN))  # ... is also an admin
    db.flush()
    t = login("9876543210")["access_token"]
    rid = s["id"]
    for url, body in [(f"/api/v1/admin/retailers/{rid}/payments", {"plan_code": "PREMIUM", "billing_cycle": "YEARLY",
                                                                    "reference": "SELF1"}),
                      (f"/api/v1/admin/retailers/{rid}/grace", {"extra_days": 30}),
                      (f"/api/v1/admin/retailers/{rid}/plan", {"plan_code": "PREMIUM"})]:
        r = client.post(url, json=body, headers=auth(t))
        assert r.status_code == 403 and r.json()["error"] == "own_shop", url


def test_kept_review_rewritten_can_be_reported_again(client, login, db, frozen):
    shop_t, _ = shop(client, login, db)
    t, b = bought(client, login, db, "9123456780", "Ravi")
    r = rate(client, t, b, 4, "ok shop").json()
    client.post(f"/api/v1/retailers/me/reviews/{r['id']}/flag", json={"reason": "check"}, headers=auth(shop_t))
    support = make_admin_token(db, login, "9000000001", "SUPPORT")
    client.post(f"/api/v1/admin/reviews/{r['id']}/resolve", json={"action": "KEEP"}, headers=auth(support))
    rate(client, t, b, 1, "now abusive text")
    r2 = client.post(f"/api/v1/retailers/me/reviews/{r['id']}/flag", json={"reason": "abusive now"}, headers=auth(shop_t))
    assert r2.status_code == 200 and r2.json()["is_flagged"] is True


def test_anon_id_cannot_impersonate_a_customer(client, login, db, frozen):
    shop_t, s = create_shop(client, login, db=db)
    cust_t = customer_with_points(client, login, db, "9123456780", 0)
    from app.models import Customer
    cid = str(db.scalar(select(Customer.id).join(User).where(User.phone == "+919123456780")))
    ev = {"slug": "sharma-electronics", "event_type": "shop_view"}
    client.post("/api/v1/events", json={**ev, "anon_id": cid})            # fake: anon id = the customer's id
    r = client.post("/api/v1/events", json=ev, headers=auth(cust_t))      # the real customer
    assert r.json()["counted"] is True  # not de-duplicated against (or limited by) the fake one


def test_bad_inputs_are_422_not_500(client, login, db):
    token, _ = create_shop(client, login, db=db)
    r = client.post("/api/v1/retailers/me/products", json=product_data(1, price_paise=10**19), headers=auth(token))
    assert r.status_code == 422
    r = client.post("/api/v1/retailers/me/products", json=product_data(1, stock_qty=3_000_000_000), headers=auth(token))
    assert r.status_code == 422
    sa = make_admin_token(db, login, "9000000002", "SUPER_ADMIN")
    r = client.post("/api/v1/admin/reward-offers", json={"name": "Naive", "starts_at": "2026-11-01T00:00:00",
                                                          "ends_at": "2026-11-08T00:00:00", "threshold_paise": 100,
                                                          "percent_bp": 1000}, headers=auth(sa))
    assert r.status_code == 422

