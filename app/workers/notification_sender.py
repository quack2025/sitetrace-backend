from loguru import logger
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.notification_sender.send_email_notification")
def send_email_notification(notification_id: str):
    """Send an email notification via Resend."""
    # TODO: Sprint 2 — Full implementation with Resend API
    logger.info(f"Email notification task for: {notification_id}")
