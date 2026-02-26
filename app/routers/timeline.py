"""Project timeline endpoint — unified history view.

Returns a chronologically ordered array of all project events:
ingest_events, change_events, change_orders, state_transitions,
and notifications.
"""
from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from pydantic import BaseModel
from datetime import datetime
from app.auth import get_current_contractor
from app.database import get_supabase

router = APIRouter(prefix="/api/v1/projects", tags=["timeline"])


class TimelineItem(BaseModel):
    timestamp: datetime
    type: str  # ingest_event | change_event | change_order | transition | notification
    entity_id: str
    title: str
    description: str = ""
    metadata: dict = {}


class TimelineResponse(BaseModel):
    project_id: str
    project_name: str
    items: list[TimelineItem]
    total_count: int


def _verify_project_ownership(project_id: UUID, contractor_id: str) -> dict:
    """Fetch project and verify the contractor owns it."""
    db = get_supabase()
    result = (
        db.table("projects")
        .select("*")
        .eq("id", str(project_id))
        .eq("contractor_id", contractor_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")
    return result.data


@router.get("/{project_id}/timeline", response_model=TimelineResponse)
async def get_project_timeline(
    project_id: UUID,
    limit: int = 100,
    offset: int = 0,
    contractor: dict = Depends(get_current_contractor),
):
    """Get the full timeline of a project — all events in chronological order."""
    project = _verify_project_ownership(project_id, contractor["id"])
    db = get_supabase()
    items: list[TimelineItem] = []

    # 1. Ingest events
    ie_result = (
        db.table("ingest_events")
        .select("id, channel, sender_email, subject, processing_status, received_at, created_at")
        .eq("project_id", str(project_id))
        .execute()
    )
    for ie in ie_result.data:
        ts = ie.get("received_at") or ie.get("created_at")
        if not ts:
            continue
        items.append(TimelineItem(
            timestamp=ts,
            type="ingest_event",
            entity_id=ie["id"],
            title=f"Email received: {ie.get('subject', 'No subject')[:60]}",
            description=f"From {ie.get('sender_email', 'unknown')} via {ie['channel']}",
            metadata={
                "channel": ie["channel"],
                "processing_status": ie["processing_status"],
            },
        ))

    # 2. Change events
    ce_result = (
        db.table("change_events")
        .select("id, description, status, area, confidence_score, created_at, confirmed_at, rejected_at")
        .eq("project_id", str(project_id))
        .execute()
    )
    for ce in ce_result.data:
        # Creation event
        items.append(TimelineItem(
            timestamp=ce["created_at"],
            type="change_event",
            entity_id=ce["id"],
            title=f"Change detected: {ce['description'][:60]}",
            description=f"Area: {ce.get('area', 'N/A')} | Confidence: {ce.get('confidence_score', 0):.0%}",
            metadata={
                "status": ce["status"],
                "confidence": ce.get("confidence_score"),
                "area": ce.get("area"),
            },
        ))
        # Confirmation event
        if ce.get("confirmed_at"):
            items.append(TimelineItem(
                timestamp=ce["confirmed_at"],
                type="change_event",
                entity_id=ce["id"],
                title=f"Change confirmed: {ce['description'][:60]}",
                description="Contractor confirmed this change event",
                metadata={"status": "confirmed"},
            ))
        # Rejection event
        if ce.get("rejected_at"):
            items.append(TimelineItem(
                timestamp=ce["rejected_at"],
                type="change_event",
                entity_id=ce["id"],
                title=f"Change rejected: {ce['description'][:60]}",
                description="Contractor rejected this change event",
                metadata={"status": "rejected"},
            ))

    # 3. Change orders
    co_result = (
        db.table("change_orders")
        .select("id, order_number, description, status, total, currency, created_at, sent_to_client_at, signed_at")
        .eq("project_id", str(project_id))
        .execute()
    )
    for co in co_result.data:
        items.append(TimelineItem(
            timestamp=co["created_at"],
            type="change_order",
            entity_id=co["id"],
            title=f"CO {co['order_number']} created",
            description=co["description"][:100],
            metadata={
                "status": co["status"],
                "total": str(co.get("total", 0)),
                "currency": co.get("currency", "USD"),
            },
        ))
        if co.get("sent_to_client_at"):
            items.append(TimelineItem(
                timestamp=co["sent_to_client_at"],
                type="change_order",
                entity_id=co["id"],
                title=f"CO {co['order_number']} sent to client",
                metadata={"status": "sent_to_client"},
            ))
        if co.get("signed_at"):
            items.append(TimelineItem(
                timestamp=co["signed_at"],
                type="change_order",
                entity_id=co["id"],
                title=f"CO {co['order_number']} signed",
                metadata={"status": "signed"},
            ))

    # 4. Key state transitions
    st_result = (
        db.table("state_transitions")
        .select("id, entity_type, entity_id, from_status, to_status, actor_type, metadata, created_at")
        .in_("entity_id", [
            *[ie["id"] for ie in ie_result.data],
            *[ce["id"] for ce in ce_result.data],
            *[co["id"] for co in co_result.data],
        ])
        .execute()
    )
    for st in st_result.data:
        st_meta = st.get("metadata", {}) or {}
        action = st_meta.get("action", "")
        if action in ("pdf_generated", "cf_export"):
            items.append(TimelineItem(
                timestamp=st["created_at"],
                type="transition",
                entity_id=st["entity_id"],
                title=f"{action.replace('_', ' ').title()} — {st['entity_type']}",
                description=f"By {st['actor_type']}",
                metadata=st_meta,
            ))

    # 5. Notifications sent
    notif_result = (
        db.table("notifications")
        .select("id, type, recipient_email, recipient_role, sent_at")
        .eq("project_id", str(project_id))
        .execute()
    )
    for n in notif_result.data:
        if not n.get("sent_at"):
            continue
        items.append(TimelineItem(
            timestamp=n["sent_at"],
            type="notification",
            entity_id=n["id"],
            title=f"Notification: {n['type'].replace('_', ' ').title()}",
            description=f"Sent to {n.get('recipient_email', 'unknown')} ({n.get('recipient_role', '')})",
            metadata={"notification_type": n["type"]},
        ))

    # Sort by timestamp descending (most recent first)
    items.sort(key=lambda x: x.timestamp, reverse=True)
    total_count = len(items)

    # Apply pagination
    items = items[offset : offset + limit]

    return TimelineResponse(
        project_id=str(project_id),
        project_name=project["name"],
        items=items,
        total_count=total_count,
    )
