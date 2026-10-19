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
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        if k == "Cache-Control" and k.lower() in response.headers:
            continue  # keep an explicit cache policy (e.g. the QR image)
        response.headers.setdefault(k, v)
    return response


class _TooLarge(Exception):
    pass


class BodyLimitMiddleware:
    """Caps request bodies at max_body_bytes, counting the bytes as they arrive — so a chunked upload without
    Content-Length is stopped too (security audit), not buffered into memory."""

    def __init__(self, app, max_bytes: int):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        length = headers.get(b"content-length", b"")
        if length.isdigit() and int(length) > self.max_bytes:
            return await self._reject(send)
        seen = 0
        started = rejected = False

        async def limited_receive():
            nonlocal seen, started, rejected
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    if not started:  # answer now: the app may turn the exception below into a generic 400
                        started = rejected = True
                        await self._reject(send)
                    raise _TooLarge
            return message

        async def tracking_send(message):
            nonlocal started
            if rejected:
                return  # we already answered 413
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(send)

    @staticmethod
    async def _reject(send):
        body = b'{"error":"too_large","message":"Request is too large"}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


app.add_middleware(
    CORSMiddleware,
    allow_origins=_s.cors_origins,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)


app.add_middleware(BodyLimitMiddleware, max_bytes=_s.max_body_bytes)  # outermost of ours


@app.exception_handler(DomainError)
def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message})


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


app.include_router(api_router)
