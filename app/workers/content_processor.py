import asyncio
from datetime import datetime, timezone
from loguru import logger
from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.agents.orchestrator import process_ingest_event
from app.notifications.service import send_change_proposed


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="app.workers.content_processor.process_content",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=1800,  # max 30 min between retries
)
def process_content(self, ingest_event_id: str):
    """Process a single ingest event through the AI pipeline."""
    db = get_supabase()

    try:
        # Mark as processing
        db.table("ingest_events").update(
            {"processing_status": "processing"}
        ).eq("id", ingest_event_id).execute()

        logger.info(f"Processing ingest event {ingest_event_id}")

        # Run the orchestrator
        created_events = _run_async(process_ingest_event(ingest_event_id))

        # Mark as completed
        db.table("ingest_events").update(
            {
                "processing_status": "completed",
                "processed_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", ingest_event_id).execute()

        # Send notifications for each created change event
        for ce in created_events:
            if ce.get("status") == "proposed":
                try:
                    _run_async(send_change_proposed(ce["id"]))
                except Exception as e:
                    logger.error(
                        f"Failed to send notification for CE {ce['id']}: {e}"
                    )

        logger.info(
            f"Ingest event {ingest_event_id} processed: "
            f"{len(created_events)} change events created"
        )

    except Exception as e:
        logger.error(
            f"Failed to process ingest event {ingest_event_id} "
            f"(attempt {self.request.retries + 1}/4): {e}"
        )

        # If max retries exhausted, mark as failed and create manual_review CE
        if self.request.retries >= self.max_retries:
            db.table("ingest_events").update(
                {
                    "processing_status": "failed",
                    "error_message": str(e)[:500],
                }
            ).eq("id", ingest_event_id).execute()

            # Create a manual_review change event so nothing is lost
            ie = (
                db.table("ingest_events")
                .select("project_id, subject, raw_payload")
                .eq("id", ingest_event_id)
                .single()
                .execute()
            ).data

            if ie.get("project_id"):
                db.table("change_events").insert(
                    {
                        "project_id": ie["project_id"],
                        "status": "manual_review",
                        "description": f"[Auto] Processing failed for: {ie.get('subject', 'No subject')}",
                        "raw_text": str(ie.get("raw_payload", {}))[:2000],
                        "confidence_score": 0.0,
                    }
                ).execute()

            logger.error(
                f"Ingest event {ingest_event_id} failed permanently after "
                f"{self.max_retries + 1} attempts. Created manual_review event."
            )
        else:
            raise  # Let Celery retry
