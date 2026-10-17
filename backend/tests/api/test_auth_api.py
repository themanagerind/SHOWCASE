from datetime import timedelta

from app.core.config import get_settings
from tests.conftest import auth


def test_first_login_creates_user_with_customer_role(client, login):
    data = login("9876543210")
    assert data["user"]["phone"] == "+919876543210"
    assert data["user"]["roles"] == ["customer"]
    me = client.get("/api/v1/auth/me", headers=auth(data["access_token"]))
    assert me.status_code == 200
    assert me.json()["id"] == data["user"]["id"]


def test_second_login_returns_same_user(login):
    assert login("9876543210")["user"]["id"] == login("+91 98765 43210")["user"]["id"]


def test_me_requires_token(client):
    r = client.get("/api/v1/auth/me")
    assert r.status_code == 401


def test_refresh_token_cannot_be_used_as_access_token(client, login):
    data = login()
    assert client.get("/api/v1/auth/me", headers=auth(data["refresh_token"])).status_code == 401


def test_access_token_expires(client, login, frozen):
    data = login()
    frozen.tick(timedelta(minutes=get_settings().access_token_minutes))
    r = client.get("/api/v1/auth/me", headers=auth(data["access_token"]))
    assert r.status_code == 401
    assert r.json()["error"] == "token_expired"


def test_refresh_rotates_and_old_token_reuse_kills_family(client, login, frozen):
    data = login()
    r1 = client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert r1.status_code == 200
    new_refresh = r1.json()["refresh_token"]
    assert new_refresh != data["refresh_token"]

    # Re-using the old (rotated) token is treated as theft ...
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert reuse.status_code == 401
    assert reuse.json()["error"] == "token_reused"
    # ... and the newer token of the same family stops working too.
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401


def test_logout_revokes_refresh_token(client, login):
    data = login()
    assert client.post("/api/v1/auth/logout", json={"refresh_token": data["refresh_token"]}).status_code == 204
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]}).status_code == 401


def test_invalid_phone_returns_400(client):
    r = client.post("/api/v1/auth/otp/request", json={"phone": "1234567890"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_phone"


def test_otp_request_rate_limited_returns_429(client, frozen):
    for _ in range(get_settings().otp_send_limit_per_phone_10min):
        assert client.post("/api/v1/auth/otp/request", json={"phone": "9876543210"}).status_code == 200
    assert client.post("/api/v1/auth/otp/request", json={"phone": "9876543210"}).status_code == 429


def test_disabled_user_cannot_use_access_token(client, login, db):
    from app.models import User

    data = login()
    user = db.get(User, __import__("uuid").UUID(data["user"]["id"]))
    user.is_active = False
    db.flush()
    assert client.get("/api/v1/auth/me", headers=auth(data["access_token"])).status_code == 401
