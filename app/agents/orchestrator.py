from uuid import UUID
from loguru import logger
from app.database import get_supabase
from app.agents.text_detector import detect_changes_in_text
from app.models.change_event import ChangeEventProposal
from app.config import get_settings


async def process_ingest_event(ingest_event_id: UUID) -> list[dict]:
    """Process an ingest event through the AI pipeline.

    Returns list of created change_event records.
    """
    settings = get_settings()
    db = get_supabase()

    # Fetch ingest event
    ie = (
        db.table("ingest_events")
        .select("*")
        .eq("id", str(ingest_event_id))
        .single()
        .execute()
    ).data

    # Fetch project context (if project assigned)
    project = None
    if ie.get("project_id"):
        project = (
            db.table("projects")
            .select("*")
            .eq("id", ie["project_id"])
            .single()
            .execute()
        ).data

    # Extract text content
    raw = ie.get("raw_payload", {})
    text = raw.get("body", "")
    subject = raw.get("subject", "") or ie.get("subject", "")

    created_events = []

    # --- Phase 1: Text analysis ---
    if text.strip():
        proposals, metadata = await detect_changes_in_text(
            text=text,
            subject=subject,
            project_name=project["name"] if project else "",
            project_type=project.get("project_type", "") if project else "",
            scope_summary=project.get("scope_summary", "") if project else "",
            key_materials=str(project.get("key_materials", "")) if project else "",
        )

        for proposal in proposals:
            status = (
                "proposed"
                if proposal.confidence >= settings.confidence_threshold
                else "manual_review"
            )

            ce_result = (
                db.table("change_events")
                .insert(
                    {
                        "project_id": ie.get("project_id"),
                        "status": status,
                        "description": proposal.description,
                        "area": proposal.area,
                        "material_from": proposal.material_from,
                        "material_to": proposal.material_to,
                        "confidence_score": proposal.confidence,
                        "raw_text": text[:2000],
                        "prompt_version": metadata.get("prompt_version"),
                        "model_used": metadata.get("model_used"),
                        "tokens_used": metadata.get("tokens_used"),
                        "processing_time_ms": metadata.get("processing_time_ms"),
                    }
                )
                .execute()
            )
            ce = ce_result.data[0]

            # Link source
            db.table("change_event_sources").insert(
                {
                    "change_event_id": ce["id"],
                    "ingest_event_id": str(ingest_event_id),
                    "relevance_score": proposal.confidence,
                }
            ).execute()

            # Record state transition
            db.table("state_transitions").insert(
                {
                    "entity_type": "change_event",
                    "entity_id": ce["id"],
                    "from_status": None,
                    "to_status": status,
                    "actor_type": "ai",
                    "metadata": {
                        "confidence": proposal.confidence,
                        "prompt_version": metadata.get("prompt_version"),
                        "channel": ie["channel"],
                    },
                }
            ).execute()

            created_events.append(ce)
            logger.info(
                f"Created change_event {ce['id']} (status={status}, "
                f"confidence={proposal.confidence:.2f})"
            )

    # --- Phase 2: Image analysis (Sprint 3) ---
    # TODO: Process image attachments with image_classifier + visual_change

    # --- Phase 3: Document analysis (Sprint 3) ---
    # TODO: Process document attachments with doc_parser + text_detector

    return created_events
