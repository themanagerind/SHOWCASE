from fastapi import APIRouter

from app.api.v1 import admin, auth, bookings, customers, discovery, prefill, retailers, reviews, rewards, subscriptions, wallet

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(customers.router)
api_router.include_router(wallet.router)
api_router.include_router(bookings.router)
api_router.include_router(rewards.router)
api_router.include_router(prefill.router)
api_router.include_router(reviews.router)
api_router.include_router(discovery.router)
api_router.include_router(retailers.router)
api_router.include_router(subscriptions.router)
api_router.include_router(admin.router)
