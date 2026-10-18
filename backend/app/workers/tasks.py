from app.db.session import SessionLocal
from app.services import subscription_service
from app.workers.celery_app import celery_app


@celery_app.task(name="subscriptions.run_lifecycle")
def run_subscription_lifecycle() -> dict:
    with SessionLocal() as db:
        return subscription_service.run_lifecycle(db)
