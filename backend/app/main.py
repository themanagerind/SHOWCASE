from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import DomainError

_s = get_settings()
_dev_docs = _s.env != "prod"  # no public API explorer in production
app = FastAPI(title="Showcase API", version="0.1.0", docs_url="/docs" if _dev_docs else None,
              redoc_url="/redoc" if _dev_docs else None, openapi_url="/openapi.json" if _dev_docs else None)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",  # API answers carry tokens and personal data
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


@app.middleware("http")
async def limits_and_headers(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > _s.max_body_bytes:
        return JSONResponse(status_code=413, content={"error": "too_large", "message": "Request is too large"})
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        if k == "Cache-Control" and k.lower() in response.headers:
            continue  # keep an explicit cache policy (e.g. the QR image)
        response.headers.setdefault(k, v)
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=_s.cors_origins,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(DomainError)
def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message})


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


app.include_router(api_router)
