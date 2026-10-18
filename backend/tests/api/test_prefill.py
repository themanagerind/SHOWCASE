"""SPEC 4.12 / docs/integrations/the-manager-prefill.md: resident signup prefill."""
from sqlalchemy import select

from app.api.v1.wallet import the_manager_dep
from app.main import app
from app.models import Customer, User
from app.services.the_manager import PrefillResult, TransientError
from tests.conftest import auth

TOKEN = "tok_" + "a" * 30
RESIDENT = {
    "name": "Ravi Verma", "mobile": "+919123456789", "email": "ravi@example.com",
    "address": {"society_name": "Green Park Residency", "line": "AB Road", "city": "Indore", "state": "Madhya Pradesh",
                "pincode": "452010"},
    "flat": {"number": "B-402", "floor": "4"},
}


class FakeTM:
    def __init__(self, outcome="ok", fail_first=0):
        self.outcome, self.fail_first, self.calls, self.used_by = outcome, fail_first, [], None

    def redeem_prefill(self, token, request_id):
        self.calls.append((token, request_id))
        if self.fail_first:
            self.fail_first -= 1
            raise TransientError("timeout")
        if self.outcome != "ok":
            return PrefillResult(self.outcome)
        if self.used_by not in (None, request_id):
            return PrefillResult("expired")  # single use
        self.used_by = request_id
        return PrefillResult("ok", RESIDENT)


def use(tm):
    app.dependency_overrides[the_manager_dep] = lambda: tm


def start(client, token=TOKEN):
    return client.post("/api/v1/prefill/start", json={"token": token}).json()


def test_full_flow_reveals_only_mobile_before_otp(client, login, db):
    use(FakeTM())
    s = start(client)
    assert s["status"] == "ok" and s["mobile"] == "+919123456789"
    assert set(s) == {"status", "prefill_id", "mobile"}  # no name/address before OTP
    t = login("9123456789")["access_token"]
    d = client.get(f"/api/v1/prefill/{s['prefill_id']}", headers=auth(t))
    assert d.status_code == 200
    d = d.json()
    assert d == {"name": "Ravi Verma", "society_name": "Green Park Residency", "address_line": "AB Road",
                 "city": "Indore", "state": "Madhya Pradesh", "pincode": "452010", "flat_number": "B-402", "floor": "4"}
    assert "email" not in d
    # one read only
    assert client.get(f"/api/v1/prefill/{s['prefill_id']}", headers=auth(t)).json()["error"] == "prefill_expired"
    c = db.scalar(select(Customer).join(User).where(User.phone == "+919123456789"))
    assert c.signup_source.value == "THE_MANAGER"
    assert c.society_name is None  # nothing saved until the resident saves the form
    r = client.patch("/api/v1/customers/me", json={"name": d["name"], "pincode": d["pincode"], "city": d["city"],
                                                     "society_name": d["society_name"], "flat_number": d["flat_number"],
                                                     "floor": d["floor"], "state": d["state"], "address_line": d["address_line"]},
                     headers=auth(t)).json()
    assert (r["society_name"], r["flat_number"], r["profile_complete"], r["contact_consent"]) == (
        "Green Park Residency", "B-402", True, False)


def test_other_mobile_gets_nothing_and_data_is_discarded(client, login):
    use(FakeTM())
    s = start(client)
    other = login("9123456780")["access_token"]
    r = client.get(f"/api/v1/prefill/{s['prefill_id']}", headers=auth(other))
    assert r.status_code == 403 and r.json()["error"] == "prefill_phone_mismatch"
    right = login("9123456789")["access_token"]  # even the right person can't read it any more
    assert client.get(f"/api/v1/prefill/{s['prefill_id']}", headers=auth(right)).status_code == 404


def test_existing_customer_keeps_signup_source(client, login, db):
    use(FakeTM())
    t = login("9123456789")["access_token"]  # signed up directly earlier
    s = start(client)
    t = login("9123456789")["access_token"]
    client.get(f"/api/v1/prefill/{s['prefill_id']}", headers=auth(t))
    c = db.scalar(select(Customer).join(User).where(User.phone == "+919123456789"))
    assert c.signup_source.value == "DIRECT"


def test_token_single_use_and_errors_fall_back(client):
    tm = FakeTM()
    use(tm)
    assert start(client)["status"] == "ok"
    assert start(client)["status"] == "expired"  # 410: used
    for outcome, status in (("not_found", "invalid"), ("expired", "expired"), ("unauthorized", "unavailable"),
                            ("unavailable", "unavailable")):
        use(FakeTM(outcome))
        assert start(client) == {"status": status, "prefill_id": None, "mobile": None}
    use(FakeTM())
    assert start(client, "bad token!")["status"] == "invalid"
    app.dependency_overrides[the_manager_dep] = lambda: None  # integration not configured
    assert start(client)["status"] == "unavailable"


def test_retry_uses_same_request_id(client):
    tm = FakeTM(fail_first=2)
    use(tm)
    assert start(client)["status"] == "ok"
    assert len(tm.calls) == 3 and len({rid for _, rid in tm.calls}) == 1
    tm2 = FakeTM(fail_first=5)
    use(tm2)
    assert start(client)["status"] == "unavailable"


def test_prefill_expires_after_15_minutes(client, login, redis, frozen):
    use(FakeTM())
    s = start(client)
    assert 0 < redis.ttl(f"prefill:{s['prefill_id']}") <= 15 * 60
    raw = redis.get(f"prefill:{s['prefill_id']}")
    assert "ravi@example.com" not in raw  # email never kept, not even in Redis


def test_start_is_rate_limited_per_ip(client):
    use(FakeTM("not_found"))
    codes = [client.post("/api/v1/prefill/start", json={"token": TOKEN}).status_code for _ in range(21)]
    assert codes[:20] == [200] * 20 and codes[20] == 429


def test_claim_needs_login(client):
    assert client.get("/api/v1/prefill/abc").status_code == 401

