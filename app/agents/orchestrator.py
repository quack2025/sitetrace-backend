import asyncio
import time
from uuid import UUID
from loguru import logger
from app.database import get_supabase
from app.agents.text_detector import detect_changes_in_text
from app.agents.image_classifier import classify_image
from app.agents.visual_change import extract_changes_from_image
from app.processors.image_processor import normalize_image
from app.processors.pdf_extractor import extract_from_pdf
from app.processors.doc_parser import parse_docx, parse_xlsx
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
        """Phase 2: Image analysis via classify → extract pipeline."""
        if not image_attachments:
            return []

        results = []
        for att in image_attachments:
            try:
                file_bytes = att.get("data")
                if not file_bytes:
                    logger.warning(f"No image data for attachment: {att.get('filename')}")
                    continue

                # If data came as base64 string (from ingestor), decode it
                if isinstance(file_bytes, str):
                    import base64
                    file_bytes = base64.b64decode(file_bytes)

                filename = att.get("filename", "image.jpg")

                # Step 1: Normalize image
                processed = await normalize_image(file_bytes, filename)

                # Step 2: Classify
                classification, cls_meta = await classify_image(
                    image_base64=processed.base64_data,
                    media_type="image/jpeg",
                )

                # Step 3: Extract changes (skips "other" and "document" types)
                proposals, vis_meta = await extract_changes_from_image(
                    image_base64=processed.base64_data,
                    image_type=classification.image_type,
                    media_type="image/jpeg",
                    project_name=project["name"] if project else "",
                    project_type=project.get("project_type", "") if project else "",
                    scope_summary=project.get("scope_summary", "") if project else "",
                    key_materials=str(project.get("key_materials", "")) if project else "",
                )

                # Merge metadata from both stages
                merged_meta = {
                    **vis_meta,
                    "image_classification": classification.image_type,
                    "image_classification_confidence": classification.confidence,
                    "classification_tokens": cls_meta.get("tokens_used", 0),
                    "total_tokens": cls_meta.get("tokens_used", 0) + vis_meta.get("tokens_used", 0),
                    "source_filename": filename,
                }

                results.extend([(p, merged_meta) for p in proposals])

            except Exception as e:
                logger.error(f"Image analysis failed for {att.get('filename')}: {e}")
                continue

        logger.info(f"Image pipeline: {len(results)} proposals from {len(image_attachments)} images")
        return results

    async def analyze_documents():
        """Phase 3: Document analysis — extract text and run through detector."""
        if not doc_attachments:
            return []

        results = []
        for att in doc_attachments:
            try:
                file_bytes = att.get("data")
                if not file_bytes:
                    logger.warning(f"No data for document: {att.get('filename')}")
                    continue

                # If data came as base64 string, decode it
                if isinstance(file_bytes, str):
                    import base64
                    file_bytes = base64.b64decode(file_bytes)

                filename = att.get("filename", "document")
                mime = att.get("mime_type", "")

                # Step 1: Parse document based on type
                doc_text = ""
                pdf_images = []

                if mime == "application/pdf":
                    pdf_content = await extract_from_pdf(file_bytes)
                    doc_text = pdf_content.total_text
                    # Collect images from PDF pages for the image pipeline
                    for page in pdf_content.pages:
                        for img_b64 in page.images_base64:
                            pdf_images.append(img_b64)

                elif mime in (
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/msword",
                ):
                    doc_text = await parse_docx(file_bytes)

                elif mime in (
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/vnd.ms-excel",
                ):
                    doc_text = await parse_xlsx(file_bytes)

                else:
                    logger.warning(f"Unsupported document type: {mime}")
                    continue

                # Step 2: Run extracted text through text detector
                if doc_text.strip():
                    proposals, meta = await detect_changes_in_text(
                        text=doc_text,
                        subject=f"Document: {filename}",
                        project_name=project["name"] if project else "",
                        project_type=project.get("project_type", "") if project else "",
                        scope_summary=project.get("scope_summary", "") if project else "",
                        key_materials=str(project.get("key_materials", "")) if project else "",
                    )
                    meta["source_filename"] = filename
                    meta["source_type"] = "document"
                    results.extend([(p, meta) for p in proposals])

                # Step 3: If PDF had embedded images, run them through image pipeline
                for img_b64 in pdf_images:
                    try:
                        classification, cls_meta = await classify_image(
                            image_base64=img_b64,
                            media_type="image/jpeg",
                        )
                        img_proposals, vis_meta = await extract_changes_from_image(
                            image_base64=img_b64,
                            image_type=classification.image_type,
                            media_type="image/jpeg",
                            project_name=project["name"] if project else "",
                            project_type=project.get("project_type", "") if project else "",
                            scope_summary=project.get("scope_summary", "") if project else "",
                            key_materials=str(project.get("key_materials", "")) if project else "",
                        )
                        vis_meta["source_filename"] = filename
                        vis_meta["source_type"] = "pdf_embedded_image"
                        results.extend([(p, vis_meta) for p in img_proposals])
                    except Exception as e:
                        logger.error(f"PDF image analysis failed for {filename}: {e}")

            except Exception as e:
                logger.error(f"Document analysis failed for {att.get('filename')}: {e}")
                continue

        logger.info(f"Document pipeline: {len(results)} proposals from {len(doc_attachments)} documents")
        return results

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
