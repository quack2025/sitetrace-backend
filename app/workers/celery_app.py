from celery import Celery
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "sitetrace",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Beat schedule for periodic tasks
    beat_schedule={
        "poll-email-inboxes": {
            "task": "app.workers.email_poller.poll_all_inboxes",
            "schedule": settings.poll_interval_seconds,
        },
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["app.workers"])
