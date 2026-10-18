"""DEV ONLY: a stand-in for THE-MANAGER's wallet-redemption verify API, following the agreed contract.

Run:  MOCK_TM_KEY=dev-shared-key .venv/bin/uvicorn scripts.mock_the_manager:app --port 8000
Then set THE_MANAGER_BASE_URL=http://localhost:8000 and THE_MANAGER_API_KEY=dev-shared-key for Showcase.
Demo codes: DEMO1500 (₹1,500), DEMO0500 (₹500), SHOP2500 (₹2,500), TINY0100 (₹100).

Resident prefill (SPEC 4.12): open http://localhost:8000/dev/shop-now (optionally ?mobile=9123456789) to act
as the "Shop Now" button — it mints a 5-minute single-use token and redirects to Showcase /welcome?prefill=.
"""
import os
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

app = FastAPI(title="Mock THE-MANAGER")
KEY = os.environ.get("MOCK_TM_KEY", "dev-shared-key")
CODES = {"DEMO1500": 150000, "DEMO0500": 50000, "SHOP2500": 250000, "TINY0100": 10000}
USED: dict[str, tuple[str | None, dict]] = {}  # code -> (request_id, original 200 body)


class VerifyIn(BaseModel):
    code: str
    request_id: str | None = None


@app.post("/api/v1/wallet-redemptions/verify")
def verify(body: VerifyIn, x_store_api_key: str = Header(default="")):
    if x_store_api_key != KEY:
        return JSONResponse({"detail": "bad key"}, status_code=401)
    code = "".join(body.code.split()).upper()
    if code not in CODES:
        return JSONResponse({"detail": "not found"}, status_code=404)
    if code in USED:
        rid, original = USED[code]
        if body.request_id and rid == body.request_id:
            return original  # safe retry: replay the original success
        return JSONResponse({"detail": "already used"}, status_code=409)
    original = {"amount_paise": CODES[code], "used_at": datetime.now(UTC).isoformat()}
    USED[code] = (body.request_id, original)
    return original


# ---- resident prefill -----------------------------------------------------------------------------
SHOWCASE_URL = os.environ.get("MOCK_SHOWCASE_URL", "http://localhost:3000")
TOKENS: dict[str, dict] = {}  # token -> {resident, expires, request_id, body}


class RedeemIn(BaseModel):
    token: str
    request_id: str


@app.get("/dev/shop-now")
def shop_now(mobile: str = "9123456789", name: str = "Ravi Verma"):
    token = secrets.token_urlsafe(24)  # opaque: no data in the URL
    TOKENS[token] = {"expires": datetime.now(UTC) + timedelta(minutes=5), "request_id": None, "resident": {
        "name": name, "mobile": "+91" + mobile[-10:], "email": "ravi@example.com",
        "address": {"society_name": "Green Park Residency", "line": "AB Road, Vijay Nagar", "city": "Indore",
                    "state": "Madhya Pradesh", "pincode": "452010"},
        "flat": {"number": "B-402", "floor": "4"},
    }}
    return RedirectResponse(f"{SHOWCASE_URL}/welcome?prefill={token}")


@app.post("/api/v1/showcase-prefill/redeem")
def redeem(body: RedeemIn, x_store_api_key: str = Header(default="")):
    if x_store_api_key != KEY:
        return JSONResponse({"detail": "bad key"}, status_code=401)
    t = TOKENS.get(body.token)
    if t is None:
        return JSONResponse({"detail": "not found"}, status_code=404)
    if t["request_id"] is not None:
        if t["request_id"] == body.request_id:
            return t["resident"]  # safe retry
        return JSONResponse({"detail": "used"}, status_code=410)
    if datetime.now(UTC) >= t["expires"]:
        return JSONResponse({"detail": "expired"}, status_code=410)
    t["request_id"] = body.request_id
    return t["resident"]
