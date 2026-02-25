import asyncio
import time
from uuid import UUID
from loguru import logger
from app.database import get_supabase
from app.agents.text_detector import detect_changes_in_text
from app.models.change_event import ChangeEventProposal
from app.config import get_settings


async def process_ingest_event(ingest_event_id: UUID) -> list[dict]:
    """Process an ingest event through the full AI pipeline.

    Pipeline:
    1. Extract text → text_detector (returns list of proposals)
    2. Classify images → image_classifier → visual_change (Sprint 3)
    3. Parse documents → doc_parser → text_detector (Sprint 3)
    4. Run text + image analysis in parallel
    5. Deduplicate similar proposals
    6. Persist change_events + link sources + record transitions
    7. Create change_order automatically for confirmed events

    Returns list of created change_event records.
    """
    start_time = time.time()
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

    # Extract content from raw_payload
    raw = ie.get("raw_payload", {})
    text = raw.get("body", "")
    subject = raw.get("subject", "") or ie.get("subject", "")
    attachments = ie.get("attachments", [])

    # Separate attachments by type
    image_attachments = [
        a for a in attachments
        if a.get("mime_type", "").startswith("image/")
    ]
    doc_attachments = [
        a for a in attachments
        if a.get("mime_type", "") in (
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/msword",
            "application/vnd.ms-excel",
        )
    ]

    # --- Run analysis phases in parallel ---
    all_proposals: list[tuple[ChangeEventProposal, dict]] = []

    async def analyze_text():
        """Phase 1: Text analysis."""
        if not text.strip():
            return []
        proposals, metadata = await detect_changes_in_text(
            text=text,
            subject=subject,
            project_name=project["name"] if project else "",
            project_type=project.get("project_type", "") if project else "",
            scope_summary=project.get("scope_summary", "") if project else "",
            key_materials=str(project.get("key_materials", "")) if project else "",
        )
        return [(p, metadata) for p in proposals]

    async def analyze_images():
        """Phase 2: Image analysis (Sprint 3 — placeholder)."""
        if not image_attachments:
            return []
        # TODO: Sprint 3 — For each image:
        # 1. Download via ingestor.download_attachment()
        # 2. Normalize with image_processor
        # 3. Classify with image_classifier
        # 4. Extract changes with visual_change agent
        # 5. Return proposals with metadata
        logger.info(
            f"Skipping {len(image_attachments)} image attachments "
            "(image pipeline not yet implemented)"
        )
        return []

    async def analyze_documents():
        """Phase 3: Document analysis (Sprint 3 — placeholder)."""
        if not doc_attachments:
            return []
        # TODO: Sprint 3 — For each document:
        # 1. Download via ingestor.download_attachment()
        # 2. Parse with pdf_extractor / doc_parser
        # 3. Run extracted text through text_detector
        # 4. If PDF has images, run through image pipeline
        # 5. Return proposals with metadata
        logger.info(
            f"Skipping {len(doc_attachments)} document attachments "
            "(document pipeline not yet implemented)"
        )
        return []

    # Run all phases concurrently
    results = await asyncio.gather(
        analyze_text(),
        analyze_images(),
        analyze_documents(),
        return_exceptions=True,
    )

    for i, result in enumerate(results):
        phase_names = ["text", "images", "documents"]
        if isinstance(result, Exception):
            logger.error(f"Phase {phase_names[i]} failed: {result}")
            continue
        all_proposals.extend(result)

    # --- Deduplicate similar proposals ---
    deduplicated = _deduplicate_proposals(all_proposals)

    # --- Persist change events ---
    created_events = []
    for proposal, metadata in deduplicated:
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
                    "raw_text": text[:2000] if text else None,
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
                    "urgency": proposal.urgency,
                },
            }
        ).execute()

        created_events.append(ce)
        logger.info(
            f"Created change_event {ce['id']} (status={status}, "
            f"confidence={proposal.confidence:.2f}, area={proposal.area})"
        )

    elapsed_ms = int((time.time() - start_time) * 1000)
    logger.info(
        f"Orchestrator complete for ingest_event {ingest_event_id}: "
        f"{len(created_events)} change events in {elapsed_ms}ms "
        f"(text={len(all_proposals)} proposals, "
        f"images={len(image_attachments)} attachments, "
        f"docs={len(doc_attachments)} attachments)"
    )

    return created_events


def _deduplicate_proposals(
    proposals: list[tuple[ChangeEventProposal, dict]],
    similarity_threshold: float = 0.92,
) -> list[tuple[ChangeEventProposal, dict]]:
    """Remove near-duplicate proposals based on text similarity.

    Uses simple token overlap for now. Sprint 5 will add embedding-based
    cosine similarity for production-grade deduplication.
    """
    if len(proposals) <= 1:
        return proposals

    deduplicated = []
    seen_descriptions: list[set[str]] = []

    for proposal, metadata in proposals:
        desc_tokens = set(proposal.description.lower().split())

        is_duplicate = False
        for seen_tokens in seen_descriptions:
            if not desc_tokens or not seen_tokens:
                continue
            overlap = len(desc_tokens & seen_tokens) / max(
                len(desc_tokens | seen_tokens), 1
            )
            if overlap >= similarity_threshold:
                is_duplicate = True
                logger.info(
                    f"Deduplicated proposal: '{proposal.description[:60]}...' "
                    f"(overlap: {overlap:.2f})"
                )
                break

        if not is_duplicate:
            deduplicated.append((proposal, metadata))
            seen_descriptions.append(desc_tokens)

    if len(proposals) != len(deduplicated):
        logger.info(
            f"Deduplication: {len(proposals)} → {len(deduplicated)} proposals"
        )

    return deduplicated
