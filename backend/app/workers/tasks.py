from app.db.session import SessionLocal
from app.services import booking_service, subscription_service, wallet_service
from app.services.the_manager import get_the_manager_client
from app.workers.celery_app import celery_app


@celery_app.task(name="subscriptions.run_lifecycle")
def run_subscription_lifecycle() -> dict:
    with SessionLocal() as db:
        return subscription_service.run_lifecycle(db)


@celery_app.task(name="wallet.retry_pending_redemptions")
def retry_pending_redemptions() -> dict:
    with SessionLocal() as db:
        return wallet_service.retry_pending(db, get_the_manager_client())


@celery_app.task(name="bookings.expire")
def expire_bookings() -> dict:
    with SessionLocal() as db:
        return {"forfeited": booking_service.forfeit_expired(db),
                "discount_requests_expired": booking_service.expire_discount_requests(db)}
