from functools import lru_cache

from pydantic import Field
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

    public_base_url: str = "http://localhost:3000"
    cors_origins: list[str] = ["http://localhost:3000"]

    # Razorpay (retailer plan billing). Empty = online payment off; admins record payments manually.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    # THE-MANAGER wallet integration (SPEC 4.11) — flow not built yet
    the_manager_base_url: str = "http://localhost:8000"
    the_manager_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
