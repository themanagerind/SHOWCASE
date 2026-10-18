from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("showcase", broker=settings.redis_url, backend=settings.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(timezone="UTC", enable_utc=True, task_acks_late=True)
celery_app.conf.beat_schedule = {
    # SPEC 5: TRIAL/ACTIVE -> GRACE -> EXPIRED transitions and 3-day reminders (idempotent).
    "subscription-lifecycle-hourly": {"task": "subscriptions.run_lifecycle", "schedule": crontab(minute=5)},
    # SPEC 4.11: settle THE-MANAGER redemptions whose response was lost (same request_id).
    "wallet-redemption-retry": {"task": "wallet.retry_pending_redemptions", "schedule": crontab(minute="*/5")},
    # SPEC 4.4: 24h-old RESERVED bookings are forfeited; unanswered discount requests expire.
    "bookings-expire": {"task": "bookings.expire", "schedule": crontab(minute="*/5")},
}
