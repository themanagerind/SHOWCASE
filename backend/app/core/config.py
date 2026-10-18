from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"  # dev | test | prod
    database_url: str = "postgresql+psycopg://showcase:showcase@localhost:5432/showcase"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 30  # sliding: unused for this long -> logged out
    admin_session_hours: int = 12  # admins are logged out this long after login, even if active

    otp_length: int = 6
    otp_ttl_seconds: int = 300
    otp_max_verify_attempts: int = 5
    otp_send_limit_per_phone_10min: int = 3
    otp_send_limit_per_phone_day: int = 10
    otp_send_limit_per_ip_hour: int = 30
    otp_verify_limit_per_ip_10min: int = 30

    public_base_url: str = "http://localhost:3000"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Razorpay (retailer plan billing). Empty = online payment off; admins record payments manually.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # THE-MANAGER wallet integration (SPEC 4.11) — flow not built yet
    the_manager_base_url: str = "http://localhost:8000"
    the_manager_api_key: str = ""

    # "console" prints OTPs to the log and is allowed only in dev/test. Production needs a real SMS provider.
    sms_provider: str = "console"
    max_body_bytes: int = 1_000_000

    @field_validator("jwt_secret")
    @classmethod
    def _no_placeholder_secret(cls, v: str) -> str:
        if "CHANGE_ME" in v.upper():
            raise ValueError("JWT_SECRET is still the placeholder from .env.example — generate one: openssl rand -hex 32")
        return v

    @model_validator(mode="after")
    def _production_must_not_use_dev_settings(self) -> "Settings":
        if self.env != "prod":
            return self
        problems = []
        if len(self.jwt_secret) < 64:
            problems.append("JWT_SECRET must be at least 64 characters (openssl rand -hex 32)")
        if "showcase:showcase@" in self.database_url or "CHANGE_ME" in self.database_url:
            problems.append("DATABASE_URL uses a default/placeholder password")
        if self.sms_provider == "console":
            problems.append("SMS_PROVIDER=console would write OTP codes to the log")
        if any("localhost" in o for o in self.cors_origins):
            problems.append("CORS_ORIGINS still points at localhost")
        if self.the_manager_api_key in ("dev-shared-key",):
            problems.append("THE_MANAGER_API_KEY is the dev mock key")
        if problems:
            raise ValueError("Unsafe production settings: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
