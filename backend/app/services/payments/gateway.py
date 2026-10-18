"""Payment gateway for retailer plan billing (SPEC 5). Razorpay Orders + Checkout today; the interface allows
UPI autopay or another provider later. When keys are not configured, online payment is simply unavailable and
admins record payments manually."""
import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import get_settings


@dataclass
class GatewayOrder:
    order_id: str
    amount_paise: int
    currency: str = "INR"


class PaymentGateway(Protocol):
    name: str
    public_key: str

    def create_order(self, amount_paise: int, receipt: str, notes: dict) -> GatewayOrder: ...

    def verify_payment(self, order_id: str, payment_id: str, signature: str) -> bool: ...

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool: ...


def _hmac_ok(secret: str, message: bytes, signature: str) -> bool:
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


class RazorpayGateway:
    name = "razorpay"
    API = "https://api.razorpay.com/v1"

    def __init__(self, key_id: str, key_secret: str, webhook_secret: str):
        self.public_key = key_id
        self._secret = key_secret
        self._webhook_secret = webhook_secret

    def create_order(self, amount_paise: int, receipt: str, notes: dict) -> GatewayOrder:
        r = httpx.post(
            f"{self.API}/orders",
            auth=(self.public_key, self._secret),
            json={"amount": amount_paise, "currency": "INR", "receipt": receipt[:40], "notes": notes},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        return GatewayOrder(order_id=data["id"], amount_paise=data["amount"])

    def verify_payment(self, order_id: str, payment_id: str, signature: str) -> bool:
        return _hmac_ok(self._secret, f"{order_id}|{payment_id}".encode(), signature)

    def verify_webhook(self, raw_body: bytes, signature: str) -> bool:
        return bool(self._webhook_secret) and _hmac_ok(self._webhook_secret, raw_body, signature)


def get_gateway() -> PaymentGateway | None:
    s = get_settings()
    if not (s.razorpay_key_id and s.razorpay_key_secret):
        return None
    return RazorpayGateway(s.razorpay_key_id, s.razorpay_key_secret, s.razorpay_webhook_secret)
