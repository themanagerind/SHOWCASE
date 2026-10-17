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
    return ConsoleSmsSender()
