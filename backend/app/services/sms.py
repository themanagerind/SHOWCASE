import logging
from typing import Protocol

log = logging.getLogger(__name__)


class SmsSender(Protocol):
    def send_otp(self, phone: str, code: str) -> None: ...


class ConsoleSmsSender:
    """Dev-only sender. A real provider (MSG91, Twilio, ...) implements the same protocol."""

    def send_otp(self, phone: str, code: str) -> None:
        log.warning("DEV OTP for %s: %s", phone, code)


def get_sms_sender() -> SmsSender:
    from app.core.config import get_settings

    s = get_settings()
    if s.sms_provider == "console" and s.env in ("dev", "test"):
        return ConsoleSmsSender()
    # Settings already refuse "console" in prod; no real provider is wired yet (needed before launch).
    raise RuntimeError(f"SMS provider {s.sms_provider!r} is not available")
