import asyncio
from loguru import logger
from app.workers.celery_app import celery_app
from app.database import get_supabase
from app.ingestors.gmail import GmailIngestor
from app.agents.project_router import route_email_to_project


def _run_async(coro):
    """Run async code from sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.workers.email_poller.poll_all_inboxes")
def poll_all_inboxes():
    """Celery Beat task: poll all active email integrations."""
    db = get_supabase()

    integrations = (
        db.table("integrations")
        .select("*, contractors!inner(id, name, email)")
        .eq("is_active", True)
        .in_("type", ["gmail", "outlook"])
        .execute()
    ).data

    logger.info(f"Polling {len(integrations)} active email integrations")

    for integration in integrations:
        try:
            _poll_single_integration(integration)
        except Exception as e:
            logger.error(
                f"Failed to poll integration {integration['id']} "
                f"(contractor: {integration['contractor_id']}): {e}"
            )

    logger.info("Email polling cycle complete")


def _poll_single_integration(integration: dict):
    """Poll a single integration and enqueue new messages."""
    db = get_supabase()
    contractor_id = integration["contractor_id"]

    # Select ingestor
    if integration["type"] == "gmail":
        ingestor = GmailIngestor()
    else:
        # TODO: Sprint 5 — Outlook ingestor
        logger.warning(f"Outlook ingestor not yet implemented, skipping {integration['id']}")
        return

    # Fetch new messages
    events = _run_async(ingestor.fetch_new_messages(integration))

    for event in events:
        # Route to project
        project_id = _run_async(
            route_email_to_project(
                sender_email=event.sender_email or "",
                sender_name=event.sender_name or "",
                subject=event.subject or "",
                body_preview=(event.raw_payload.get("body", ""))[:500],
                contractor_id=contractor_id,
            )
        )
        event.project_id = project_id

        # Insert ingest event
        data = event.model_dump(exclude_none=True)
        # Convert datetime to isoformat string
        if "received_at" in data and data["received_at"]:
            data["received_at"] = data["received_at"].isoformat()

        result = db.table("ingest_events").insert(data).execute()
        ingest_event = result.data[0]

        # Enqueue for processing
        from app.workers.content_processor import process_content

        process_content.delay(ingest_event["id"])

    # Update last_polled_at
    from datetime import datetime, timezone

    db.table("integrations").update(
        {"last_polled_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", integration["id"]).execute()

    logger.info(
        f"Integration {integration['id']}: {len(events)} new messages enqueued"
    )
