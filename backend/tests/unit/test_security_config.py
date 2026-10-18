"""Security audit: unsafe settings are refused; API sends security headers and caps body size."""
import pytest
from pydantic import ValidationError

from app.core.config import Settings

STRONG = "a" * 64


def test_placeholder_jwt_secret_is_refused():
    with pytest.raises(ValidationError, match="placeholder"):
        Settings(jwt_secret="CHANGE_ME_TO_A_LONG_RANDOM_STRING", env="dev")


def test_production_refuses_dev_settings():
    with pytest.raises(ValidationError) as e:
        Settings(env="prod", jwt_secret="b" * 40)
    msg = str(e.value)
    for part in ("at least 64", "DATABASE_URL", "SMS_PROVIDER=console", "localhost"):
        assert part in msg


def test_production_with_real_settings_starts():
    s = Settings(env="prod", jwt_secret=STRONG, database_url="postgresql+psycopg://app:s3cret@db/showcase",
                 sms_provider="msg91", cors_origins=["https://showcase.in"])
    assert s.env == "prod"


def test_console_sms_never_used_outside_dev(monkeypatch):
    from app.core import config
    from app.services import sms

    monkeypatch.setattr(config, "get_settings", lambda: Settings(env="staging", jwt_secret=STRONG))
    with pytest.raises(RuntimeError):
        sms.get_sms_sender()


def test_security_headers_and_body_limit(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    big = client.post("/api/v1/auth/otp/request", content=b"x" * 1_000_001, headers={"Content-Type": "application/json"})
    assert big.status_code == 413
