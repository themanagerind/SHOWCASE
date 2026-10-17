from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.errors import DomainError

app = FastAPI(title="Showcase API", version="0.1.0")


@app.exception_handler(DomainError)
def domain_error_handler(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message})


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


app.include_router(api_router)
