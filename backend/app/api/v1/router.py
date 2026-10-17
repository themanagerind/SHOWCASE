from fastapi import APIRouter

from app.api.v1 import auth, customers, discovery, retailers

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(customers.router)
api_router.include_router(discovery.router)
api_router.include_router(retailers.router)
