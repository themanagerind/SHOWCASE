import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy import select

from app.api.v1.subscriptions import gateway_dep
from app.main import app
from app.models import AdminUser, User
from app.models.enums import AdminRole
from app.services.payments.gateway import GatewayOrder, RazorpayGateway
from tests.api.test_retailer_api import create_shop
from tests.conftest import auth, set_setting

SECRET, WEBHOOK_SECRET = "rzp_test_secret", "whsec_test"


class FakeRazorpay(RazorpayGateway):
    """Real signature checks; only the network call to create an order is faked."""

    def __init__(self):
        super().__init__("rzp_test_key", SECRET, WEBHOOK_SECRET)
        self.n = 0

    def create_order(self, amount_paise, receipt, notes):
        self.n += 1
        return GatewayOrder(order_id=f"order_{self.n}_{uuid.uuid4().hex[:6]}", amount_paise=amount_paise)


def sign(msg: str, secret: str) -> str:
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


@pytest.fixture
def gateway():
    g = FakeRazorpay()
    app.dependency_overrides[gateway_dep] = lambda: g
    yield g
    app.dependency_overrides.pop(gateway_dep, None)


def make_admin_token(db, login, phone, role):
    data = login(phone)
    db.add(AdminUser(user_id=uuid.UUID(data["user"]["id"]), role=AdminRole(role)))
    db.flush()
    return data["access_token"]


# ---- retailer side ----------------------------------------------------------------------------

def test_new_shop_gets_trial_automatically(client, login, db):
    set_setting(db, "trial", {"enabled": True, "duration_value": 30, "duration_unit": "days", "plan_code": "PRO"})
    token, shop = create_shop(client, login, db=db, plan=None)
    me = client.get("/api/v1/subscriptions/me", headers=auth(token)).json()
    assert (me["status"], me["plan_code"]) == ("TRIAL", "PRO")
    assert client.get("/api/v1/retailers/sharma-electronics").status_code == 200  # live during trial


def test_plan_options_show_my_prices(client, login, db):
    token, _ = create_shop(client, login, db=db, plan=None)
    plans = {p["code"]: p for p in client.get("/api/v1/subscriptions/plans", headers=auth(token)).json()}
    assert plans["BASIC"]["monthly"]["amount_paise"] == 19900 and plans["BASIC"]["yearly"]["amount_paise"] == 159900
    assert plans["PREMIUM"]["yearly"]["gst_paise"] > 0


def test_checkout_without_gateway_returns_clear_error(client, login, db):
    token, _ = create_shop(client, login, db=db, plan=None)
    app.dependency_overrides[gateway_dep] = lambda: None
    try:
        r = client.post("/api/v1/subscriptions/me/checkout", json={"plan_code": "PRO", "billing_cycle": "MONTHLY"},
                        headers=auth(token))
        assert r.status_code == 400 and r.json()["error"] == "gateway_not_configured"
        assert client.get("/api/v1/subscriptions/me", headers=auth(token)).json()["online_payment_available"] is False
    finally:
        app.dependency_overrides.pop(gateway_dep, None)


def test_checkout_confirm_with_valid_signature_activates(client, login, db, gateway):
    token, _ = create_shop(client, login, db=db, plan=None)
    co = client.post("/api/v1/subscriptions/me/checkout", json={"plan_code": "PRO", "billing_cycle": "YEARLY"},
                     headers=auth(token)).json()
    assert co["amount_paise"] == 319900 and co["key_id"] == "rzp_test_key"
    bad = client.post(f"/api/v1/subscriptions/me/checkout/{co['payment_id']}/confirm",
                      json={"razorpay_payment_id": "pay_1", "razorpay_signature": "forged"}, headers=auth(token))
    assert bad.status_code == 400 and bad.json()["error"] == "bad_signature"
    ok = client.post(f"/api/v1/subscriptions/me/checkout/{co['payment_id']}/confirm",
                     json={"razorpay_payment_id": "pay_1", "razorpay_signature": sign(f"{co['order_id']}|pay_1", SECRET)},
                     headers=auth(token)).json()
    assert (ok["status"], ok["plan_code"], ok["billing_cycle"]) == ("ACTIVE", "PRO", "YEARLY")


def test_webhook_marks_paid_once_and_rejects_bad_signature(client, login, db, gateway):
    token, _ = create_shop(client, login, db=db, plan=None)
    co = client.post("/api/v1/subscriptions/me/checkout", json={"plan_code": "BASIC", "billing_cycle": "MONTHLY"},
                     headers=auth(token)).json()
    event = {"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_9", "order_id": co["order_id"], "amount": co["amount_paise"]}}}}
    raw = json.dumps(event)
    assert client.post("/api/v1/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": "nope"}).status_code == 401
    for _ in range(2):  # duplicate delivery is harmless
        r = client.post("/api/v1/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sign(raw, WEBHOOK_SECRET)})
        assert r.status_code == 200
    me = client.get("/api/v1/subscriptions/me", headers=auth(token)).json()
    assert me["status"] == "ACTIVE" and len(me["payments"]) == 1


def test_webhook_amount_mismatch_rejected(client, login, db, gateway):
    token, _ = create_shop(client, login, db=db, plan=None)
    co = client.post("/api/v1/subscriptions/me/checkout", json={"plan_code": "BASIC", "billing_cycle": "MONTHLY"},
                     headers=auth(token)).json()
    raw = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {
        "id": "pay_x", "order_id": co["order_id"], "amount": 100}}}})
    r = client.post("/api/v1/webhooks/razorpay", content=raw, headers={"X-Razorpay-Signature": sign(raw, WEBHOOK_SECRET)})
    assert r.status_code == 400 and r.json()["error"] == "amount_mismatch"


def test_retailer_cannot_confirm_someone_elses_payment(client, login, db, gateway):
    t1, _ = create_shop(client, login, "9876543210", db=db, plan=None)
    t2, _ = create_shop(client, login, "9123456789", db=db, plan=None, slug="other-shop")
    co = client.post("/api/v1/subscriptions/me/checkout", json={"plan_code": "BASIC", "billing_cycle": "MONTHLY"},
                     headers=auth(t1)).json()
    r = client.post(f"/api/v1/subscriptions/me/checkout/{co['payment_id']}/confirm",
                    json={"razorpay_payment_id": "p", "razorpay_signature": sign(f"{co['order_id']}|p", SECRET)},
                    headers=auth(t2))
    assert r.status_code == 404


# ---- admin side -------------------------------------------------------------------------------

def test_non_admin_gets_403(client, login):
    token = login()["access_token"]
    assert client.get("/api/v1/admin/retailers", headers=auth(token)).status_code == 403


def test_support_can_view_record_payment_and_extend_grace_but_not_change_prices(client, login, db):
    _, shop = create_shop(client, login, db=db, plan=None)
    support = make_admin_token(db, login, "9000000001", "SUPPORT")
    rid = shop["id"]
    lst = client.get("/api/v1/admin/retailers", params={"q": "sharma"}, headers=auth(support)).json()
    assert lst["total"] == 1 and lst["items"][0]["status"] is None
    r = client.post(f"/api/v1/admin/retailers/{rid}/payments",
                    json={"plan_code": "BASIC", "billing_cycle": "MONTHLY", "reference": "UPI-123"}, headers=auth(support))
    assert r.status_code == 201 and r.json()["amount_paise"] == 19900
    assert client.post(f"/api/v1/admin/retailers/{rid}/grace", json={"extra_days": 3}, headers=auth(support)).status_code == 200
    for method, url, body in [
        ("put", f"/api/v1/admin/retailers/{rid}/price-override", {"amount_paise": 100, "reason": "nope"}),
        ("post", f"/api/v1/admin/retailers/{rid}/offers", {"offer_type": "PERCENT", "value": 10, "reason": "nope",
                                                            "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2027-01-01T00:00:00Z"}),
        ("post", f"/api/v1/admin/retailers/{rid}/plan", {"plan_code": "PREMIUM"}),
        ("put", "/api/v1/admin/plans/BASIC/prices", {"monthly_paise": 100, "apply_to": "ALL"}),
        ("put", "/api/v1/admin/settings/trial", {"enabled": False, "duration_value": 1, "duration_unit": "days", "plan_code": "BASIC"}),
    ]:
        resp = getattr(client, method)(url, json=body, headers=auth(support))
        assert resp.status_code == 403 and resp.json()["error"] == "super_admin_only", url


def test_super_admin_full_flow_and_audit(client, login, db):
    token, shop = create_shop(client, login, db=db, plan=None)
    sa = make_admin_token(db, login, "9000000002", "SUPER_ADMIN")
    rid = shop["id"]
    r = client.post(f"/api/v1/admin/retailers/{rid}/offers", json={
        "offer_type": "PERCENT", "value": 50, "reason": "Diwali", "plan_code": "PRO",
        "valid_from": "2026-01-01T00:00:00Z", "valid_until": "2027-01-01T00:00:00Z"}, headers=auth(sa))
    assert r.status_code == 201
    plans = {p["code"]: p for p in client.get("/api/v1/subscriptions/plans", headers=auth(token)).json()}
    assert plans["PRO"]["monthly"]["amount_paise"] == 19950 and plans["PRO"]["monthly"]["source"] == "OFFER"
    client.post(f"/api/v1/admin/retailers/{rid}/payments",
                json={"plan_code": "PRO", "billing_cycle": "MONTHLY", "reference": "cash"}, headers=auth(sa))
    detail = client.get(f"/api/v1/admin/retailers/{rid}", headers=auth(sa)).json()
    assert detail["subscription"]["status"] == "ACTIVE" and detail["subscription"]["payments"][0]["amount_paise"] == 19950
    assert {a["action"] for a in detail["audit"]} == {"offer_created", "payment_recorded"}
    assert all(a["admin_phone"] == "+919000000002" for a in detail["audit"])
    s = client.put("/api/v1/admin/settings/grace_days_default", json={"days": 10}, headers=auth(sa))
    assert s.status_code == 200 and client.get("/api/v1/admin/settings", headers=auth(sa)).json()["grace_days_default"]["days"] == 10
    plans_admin = client.get("/api/v1/admin/plans", headers=auth(sa)).json()
    assert next(p for p in plans_admin if p["code"] == "PRO")["subscribers"] == 1
    assert client.post("/api/v1/admin/jobs/lifecycle", headers=auth(sa)).json()["checked"] >= 1


def test_inactive_admin_is_rejected(client, login, db):
    sa = make_admin_token(db, login, "9000000003", "SUPER_ADMIN")
    admin = db.scalar(select(AdminUser).join(User, User.id == AdminUser.user_id).where(User.phone == "+919000000003"))
    admin.is_active = False
    db.flush()
    assert client.get("/api/v1/admin/retailers", headers=auth(sa)).status_code == 403
