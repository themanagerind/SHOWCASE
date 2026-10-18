"""Client for THE-MANAGER's wallet-redemption verify API (SPEC 4.11, docs: contract in SPEC).

POST {base}/api/v1/wallet-redemptions/verify  header X-Store-Api-Key  body {code, request_id}
200 {amount_paise, used_at} | 404 unknown code | 409 already used | 401 bad key | 503 not configured there.
Retrying with the SAME request_id after a lost response returns the original 200.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx

from app.core.config import get_settings


class TransientError(Exception):
    """Network problem or unexpected server error: the redemption stays PENDING and is retried later."""


@dataclass(frozen=True)
class VerifyResult:
    outcome: str  # ok | not_found | used | unauthorized | unavailable
    amount_paise: int | None = None
    used_at: datetime | None = None


class TheManagerClient(Protocol):
    def verify(self, code: str, request_id: str) -> VerifyResult: ...


class HttpTheManagerClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0):
        self.url = base_url.rstrip("/") + "/api/v1/wallet-redemptions/verify"
        self.api_key = api_key
        self.timeout = timeout

    def verify(self, code: str, request_id: str) -> VerifyResult:
        try:
            r = httpx.post(self.url, json={"code": code, "request_id": request_id},
                           headers={"X-Store-Api-Key": self.api_key}, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise TransientError(str(exc)) from exc
        if r.status_code == 200:
            data = r.json()
            amount = data.get("amount_paise")
            if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
                raise TransientError(f"unexpected amount_paise: {amount!r}")  # never trust a float/odd value
            used_at = datetime.fromisoformat(data["used_at"]) if data.get("used_at") else None
            return VerifyResult("ok", amount, used_at)
        known = {404: "not_found", 409: "used", 401: "unauthorized", 503: "unavailable"}
        if r.status_code in known:
            return VerifyResult(known[r.status_code])
        raise TransientError(f"HTTP {r.status_code}")


def get_the_manager_client() -> TheManagerClient | None:
    s = get_settings()
    if not (s.the_manager_base_url and s.the_manager_api_key):
        return None
    return HttpTheManagerClient(s.the_manager_base_url, s.the_manager_api_key)
