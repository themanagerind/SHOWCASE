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

    prod = Settings(env="prod", jwt_secret=STRONG, database_url="postgresql+psycopg://a:b@db/x", sms_provider="msg91",
                    cors_origins=["https://showcase.in"])
    monkeypatch.setattr(config, "get_settings", lambda: prod)
    with pytest.raises(RuntimeError):
        sms.get_sms_sender()


def test_security_headers_and_body_limit(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    big = client.post("/api/v1/auth/otp/request", content=b"x" * 1_000_001, headers={"Content-Type": "application/json"})
    assert big.status_code == 413


def test_chunked_body_over_limit_is_rejected_without_buffering(client):
    """Security audit pass 2: no Content-Length (chunked) must not bypass the body limit."""
    def chunks():
        for _ in range(20):
            yield b"x" * 100_000  # 2 MB in total, sent without Content-Length

    r = client.post("/api/v1/auth/otp/request", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_env_must_be_exact():
    for bad in ("Prod", "production", " prod"):
        with pytest.raises(ValidationError):
            Settings(env=bad, jwt_secret=STRONG)


def test_every_frontend_route_is_a_reserved_slug():
    """A shop slug equal to a frontend page would make its share link open that page."""
    import pathlib

    from app.services.retailer_service import RESERVED_SLUGS

    app_dir = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "app"
    routes = {p.name for p in app_dir.iterdir() if p.is_dir() and not p.name.startswith(("[", "("))}
    public = {p.stem for p in (app_dir.parent / "public").iterdir()}
    assert routes and routes <= RESERVED_SLUGS, routes - RESERVED_SLUGS
    assert public <= RESERVED_SLUGS | {f for f in public if f.startswith("icon")}, public - RESERVED_SLUGS


def test_non_ascii_digits_are_not_a_phone_number():
    from app.core.errors import DomainError
    from app.core.phone import normalize_indian_mobile

    for raw in ("9८७६५४३२१०", "9８７６５４３２１０", "9٨٧٦٥٤٣٢١٠"):
        with pytest.raises(DomainError):
            normalize_indian_mobile(raw)
    assert normalize_indian_mobile("9876543210") == "+919876543210"
