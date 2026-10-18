"""Logout / device sessions: logout is immediate, per device, 'everywhere'; admin sessions end after 12h."""
import uuid
from datetime import timedelta

import jwt

from app.core.config import get_settings
from app.models import AdminUser
from app.models.enums import AdminRole
from tests.conftest import auth

ANDROID = "Mozilla/5.0 (Linux; Android 14; SM-A145F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"


def device_login(client, sms, ua, phone="9876543210"):
    r = client.post("/api/v1/auth/otp/request", json={"phone": phone}, headers={"user-agent": ua})
    code = sms.last_code(r.json()["phone"])
    return client.post("/api/v1/auth/otp/verify", json={"phone": phone, "code": code}, headers={"user-agent": ua}).json()


def me(client, token):
    return client.get("/api/v1/auth/me", headers=auth(token))


def test_logout_takes_effect_immediately(client, sms):
    a = device_login(client, sms, ANDROID)
    assert me(client, a["access_token"]).status_code == 200
    assert client.post("/api/v1/auth/logout", json={"refresh_token": a["refresh_token"]}).status_code == 204
    r = me(client, a["access_token"])  # access token not yet expired, but the session is gone
    assert r.status_code == 401 and r.json()["error"] == "session_ended"
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": a["refresh_token"]}).status_code == 401


def test_logout_on_one_device_keeps_the_other(client, sms):
    a = device_login(client, sms, ANDROID)
    b = device_login(client, sms, IPHONE)
    client.post("/api/v1/auth/logout", json={"refresh_token": a["refresh_token"]})
    assert me(client, a["access_token"]).status_code == 401
    assert me(client, b["access_token"]).status_code == 200


def test_device_list_and_remote_logout(client, sms):
    a = device_login(client, sms, ANDROID)
    b = device_login(client, sms, IPHONE)
    sessions = client.get("/api/v1/auth/sessions", headers=auth(a["access_token"])).json()
    assert len(sessions) == 2
    assert sessions[0]["current"] is True and sessions[0]["device"] == "Chrome · Android"
    other = sessions[1]
    assert other["device"] == "Safari · iPhone/iPad" and other["current"] is False
    assert client.post(f"/api/v1/auth/sessions/{other['id']}/logout", headers=auth(a["access_token"])).status_code == 204
    assert me(client, b["access_token"]).status_code == 401
    assert me(client, a["access_token"]).status_code == 200
    assert len(client.get("/api/v1/auth/sessions", headers=auth(a["access_token"])).json()) == 1


def test_cannot_log_out_someone_elses_session(client, sms):
    a = device_login(client, sms, ANDROID, "9876543210")
    b = device_login(client, sms, IPHONE, "9123456789")
    b_sid = client.get("/api/v1/auth/sessions", headers=auth(b["access_token"])).json()[0]["id"]
    assert client.post(f"/api/v1/auth/sessions/{b_sid}/logout", headers=auth(a["access_token"])).status_code == 404
    assert me(client, b["access_token"]).status_code == 200


def test_logout_everywhere(client, sms):
    a = device_login(client, sms, ANDROID)
    b = device_login(client, sms, IPHONE)
    c = device_login(client, sms, "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/131.0")
    client.post("/api/v1/auth/logout-all", json={"keep_current": True}, headers=auth(a["access_token"]))
    assert [me(client, t["access_token"]).status_code for t in (a, b, c)] == [200, 401, 401]
    client.post("/api/v1/auth/logout-all", json={"keep_current": False}, headers=auth(a["access_token"]))
    assert me(client, a["access_token"]).status_code == 401


def test_refresh_keeps_the_same_session(client, sms):
    a = device_login(client, sms, ANDROID)
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": a["refresh_token"]}).json()
    sessions = client.get("/api/v1/auth/sessions", headers=auth(r["access_token"])).json()
    assert len(sessions) == 1 and sessions[0]["current"] is True


def test_customer_stays_logged_in_while_active_and_is_logged_out_after_30_idle_days(client, sms, frozen):
    t = device_login(client, sms, ANDROID)
    for _ in range(3):  # uses the app every 29 days: never logged out (sliding window)
        frozen.tick(timedelta(days=29))
        t = client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).json()
        assert "access_token" in t
    frozen.tick(timedelta(days=30))
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_admin_session_ends_after_12_hours_even_if_active(client, sms, db, frozen):
    t = device_login(client, sms, ANDROID)
    db.add(AdminUser(user_id=uuid.UUID(t["user"]["id"]), role=AdminRole.SUPER_ADMIN))
    db.flush()
    for _ in range(23):  # refreshes every 30 minutes for 11.5 hours
        frozen.tick(timedelta(minutes=30))
        t = client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).json()
    frozen.tick(timedelta(minutes=15))  # 11h45: still allowed to refresh
    t = client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).json()
    assert me(client, t["access_token"]).status_code == 200
    frozen.tick(timedelta(minutes=15))  # exactly 12h after login; this access token itself is still valid
    r = me(client, t["access_token"])
    assert r.status_code == 401 and r.json()["error"] == "session_expired"
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r.status_code == 401 and r.json()["error"] == "session_expired"


def test_customer_is_not_limited_to_12_hours(client, sms, frozen):
    t = device_login(client, sms, ANDROID)
    frozen.tick(timedelta(hours=13))
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 200


def test_token_without_session_id_is_rejected(client, sms):
    a = device_login(client, sms, ANDROID)
    payload = jwt.decode(a["access_token"], options={"verify_signature": False})
    payload.pop("sid")
    s = get_settings()
    forged_old_style = jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)
    assert me(client, forged_old_style).status_code == 401
