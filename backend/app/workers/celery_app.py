from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("showcase", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(timezone="UTC", enable_utc=True, task_acks_late=True)
# Tasks (booking expiry, reminders, subscription lifecycle) are added in steps 5 and 6.
