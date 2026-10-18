"""DEV ONLY: a stand-in for THE-MANAGER's wallet-redemption verify API, following the agreed contract.

Run:  MOCK_TM_KEY=dev-shared-key .venv/bin/uvicorn scripts.mock_the_manager:app --port 8000
Then set THE_MANAGER_BASE_URL=http://localhost:8000 and THE_MANAGER_API_KEY=dev-shared-key for Showcase.
Demo codes: DEMO1500 (₹1,500), DEMO0500 (₹500), SHOP2500 (₹2,500), TINY0100 (₹100).
"""
import os
from datetime import UTC, datetime

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
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
