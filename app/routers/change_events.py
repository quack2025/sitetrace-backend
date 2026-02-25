from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from uuid import UUID
from datetime import datetime
from typing import Optional
from app.auth import get_current_contractor
from app.database import get_supabase
from app.models.change_event import (
    ChangeEventCreate,
    ChangeEventUpdate,
    ChangeEventResponse,
    RejectRequest,
)
from app.notifications.token_service import verify_action_token

router = APIRouter(tags=["change-events"])


def _verify_change_event_access(change_event_id: UUID, contractor_id: str) -> dict:
    """Fetch change event and verify it belongs to a project owned by the contractor."""
    db = get_supabase()
    result = (
        db.table("change_events")
        .select("*, projects!inner(contractor_id)")
        .eq("id", str(change_event_id))
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Change event not found")
    if result.data["projects"]["contractor_id"] != contractor_id:
        raise HTTPException(status_code=404, detail="Change event not found")
    return result.data


def _record_transition(
    entity_id: UUID,
    from_status: str | None,
    to_status: str,
    actor_type: str,
    actor_id: str | None = None,
    reason: str | None = None,
    metadata: dict | None = None,
    ip_address: str | None = None,
):
    """Record a state transition."""
    db = get_supabase()
    db.table("state_transitions").insert(
        {
            "entity_type": "change_event",
            "entity_id": str(entity_id),
            "from_status": from_status,
            "to_status": to_status,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "reason": reason,
            "metadata": metadata or {},
            "ip_address": ip_address,
        }
    ).execute()


@router.get(
    "/api/v1/projects/{project_id}/change-events",
    response_model=list[ChangeEventResponse],
)
async def list_change_events(
    project_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    # Verify project ownership
    db = get_supabase()
    project = (
        db.table("projects")
        .select("id")
        .eq("id", str(project_id))
        .eq("contractor_id", contractor["id"])
        .maybe_single()
        .execute()
    )
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")

    result = (
        db.table("change_events")
        .select("*")
        .eq("project_id", str(project_id))
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.post(
    "/api/v1/projects/{project_id}/change-events/manual",
    response_model=ChangeEventResponse,
    status_code=201,
)
async def create_manual_change_event(
    project_id: UUID,
    body: ChangeEventCreate,
    contractor: dict = Depends(get_current_contractor),
):
    db = get_supabase()

    # Verify project ownership
    project = (
        db.table("projects")
        .select("id")
        .eq("id", str(project_id))
        .eq("contractor_id", contractor["id"])
        .maybe_single()
        .execute()
    )
    if not project.data:
        raise HTTPException(status_code=404, detail="Project not found")

    # Create ingest event for manual entry
    ingest_result = (
        db.table("ingest_events")
        .insert(
            {
                "project_id": str(project_id),
                "channel": "manual",
                "raw_payload": {"description": body.description, "notes": body.notes},
                "sender_name": contractor.get("name"),
                "sender_email": contractor.get("email"),
                "processing_status": "completed",
                "processed_at": datetime.utcnow().isoformat(),
            }
        )
        .execute()
    )
    ingest_event = ingest_result.data[0]

    # Create change event
    ce_result = (
        db.table("change_events")
        .insert(
            {
                "project_id": str(project_id),
                "status": "proposed",
                "description": body.description,
                "area": body.area,
                "material_from": body.material_from,
                "material_to": body.material_to,
                "confidence_score": 1.0,
                "raw_text": body.notes,
            }
        )
        .execute()
    )
    change_event = ce_result.data[0]

    # Link source
    db.table("change_event_sources").insert(
        {
            "change_event_id": change_event["id"],
            "ingest_event_id": ingest_event["id"],
            "relevance_score": 1.0,
        }
    ).execute()

    # Record state transition
    _record_transition(
        entity_id=change_event["id"],
        from_status=None,
        to_status="proposed",
        actor_type="contractor",
        actor_id=contractor.get("user_id"),
    )

    return change_event


@router.get(
    "/api/v1/change-events/{change_event_id}",
    response_model=ChangeEventResponse,
)
async def get_change_event(
    change_event_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    ce = _verify_change_event_access(change_event_id, contractor["id"])
    # Remove nested projects data from response
    ce.pop("projects", None)
    return ce


@router.put(
    "/api/v1/change-events/{change_event_id}",
    response_model=ChangeEventResponse,
)
async def update_change_event(
    change_event_id: UUID,
    body: ChangeEventUpdate,
    contractor: dict = Depends(get_current_contractor),
):
    ce = _verify_change_event_access(change_event_id, contractor["id"])

    if ce["status"] not in ("proposed", "manual_review"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot edit change event in status '{ce['status']}'. "
            "Only 'proposed' and 'manual_review' events can be edited.",
        )

    db = get_supabase()
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = (
        db.table("change_events")
        .update(data)
        .eq("id", str(change_event_id))
        .execute()
    )

    _record_transition(
        entity_id=change_event_id,
        from_status=ce["status"],
        to_status=ce["status"],  # Status doesn't change on edit
        actor_type="contractor",
        actor_id=contractor.get("user_id"),
        metadata={"edited_fields": list(data.keys())},
    )

    return result.data[0]


@router.post(
    "/api/v1/change-events/{change_event_id}/confirm",
    response_model=ChangeEventResponse,
)
async def confirm_change_event(
    change_event_id: UUID,
    token: str,
    request: Request,
):
    # Verify token
    payload = verify_action_token(token)
    if payload.get("change_event_id") != str(change_event_id):
        raise HTTPException(status_code=403, detail="Token does not match this change event")
    if payload.get("action") != "confirm":
        raise HTTPException(status_code=403, detail="Invalid action for this token")

    db = get_supabase()

    # Check current status
    ce = (
        db.table("change_events")
        .select("*")
        .eq("id", str(change_event_id))
        .maybe_single()
        .execute()
    )
    if not ce.data:
        raise HTTPException(status_code=404, detail="Change event not found")

    if ce.data["status"] not in ("proposed", "manual_review"):
        raise HTTPException(
            status_code=409,
            detail=f"Change event already in status '{ce.data['status']}'",
        )

    # Mark token as used
    db.table("notifications").update(
        {"action_token_used_at": datetime.utcnow().isoformat()}
    ).eq("action_token", token).execute()

    # Update status
    result = (
        db.table("change_events")
        .update(
            {
                "status": "confirmed",
                "confirmed_at": datetime.utcnow().isoformat(),
            }
        )
        .eq("id", str(change_event_id))
        .execute()
    )

    _record_transition(
        entity_id=change_event_id,
        from_status=ce.data["status"],
        to_status="confirmed",
        actor_type="contractor",
        ip_address=request.client.host if request.client else None,
    )

    # Auto-create Change Order for this confirmed event
    confirmed = result.data[0]
    _auto_create_change_order(confirmed)

    return confirmed


def _auto_create_change_order(change_event: dict):
    """Automatically create a draft Change Order when a change event is confirmed."""
    db = get_supabase()
    project_id = change_event["project_id"]

    # Generate order number: CO-YYYY-NNN
    year = datetime.utcnow().year
    count_result = (
        db.table("change_orders")
        .select("id", count="exact")
        .eq("project_id", project_id)
        .execute()
    )
    next_num = (count_result.count or 0) + 1
    order_number = f"CO-{year}-{next_num:03d}"

    co_result = (
        db.table("change_orders")
        .insert(
            {
                "project_id": project_id,
                "order_number": order_number,
                "description": change_event["description"],
                "status": "draft",
            }
        )
        .execute()
    )
    co = co_result.data[0]

    # Create an initial line item from the change event
    db.table("change_order_items").insert(
        {
            "change_order_id": co["id"],
            "change_event_id": change_event["id"],
            "description": change_event["description"],
            "category": "other",
            "quantity": 1,
            "unit": "unit",
            "unit_cost": 0,
            "total_cost": 0,
            "sort_order": 0,
        }
    ).execute()

    # State transition for the CO
    db.table("state_transitions").insert(
        {
            "entity_type": "change_order",
            "entity_id": co["id"],
            "from_status": None,
            "to_status": "draft",
            "actor_type": "system",
            "metadata": {"change_event_id": change_event["id"], "auto_created": True},
        }
    ).execute()


@router.post(
    "/api/v1/change-events/{change_event_id}/reject",
    response_model=ChangeEventResponse,
)
async def reject_change_event(
    change_event_id: UUID,
    token: str,
    body: RejectRequest | None = None,
    request: Request = None,
):
    # Verify token
    payload = verify_action_token(token)
    if payload.get("change_event_id") != str(change_event_id):
        raise HTTPException(status_code=403, detail="Token does not match this change event")
    if payload.get("action") != "reject":
        raise HTTPException(status_code=403, detail="Invalid action for this token")

    db = get_supabase()

    # Check current status
    ce = (
        db.table("change_events")
        .select("*")
        .eq("id", str(change_event_id))
        .maybe_single()
        .execute()
    )
    if not ce.data:
        raise HTTPException(status_code=404, detail="Change event not found")

    if ce.data["status"] not in ("proposed", "manual_review"):
        raise HTTPException(
            status_code=409,
            detail=f"Change event already in status '{ce.data['status']}'",
        )

    # Mark token as used
    db.table("notifications").update(
        {"action_token_used_at": datetime.utcnow().isoformat()}
    ).eq("action_token", token).execute()

    # Update status
    rejection_reason = body.reason if body else None
    result = (
        db.table("change_events")
        .update(
            {
                "status": "rejected",
                "rejected_at": datetime.utcnow().isoformat(),
                "rejection_reason": rejection_reason,
            }
        )
        .eq("id", str(change_event_id))
        .execute()
    )

    _record_transition(
        entity_id=change_event_id,
        from_status=ce.data["status"],
        to_status="rejected",
        actor_type="contractor",
        reason=rejection_reason,
        ip_address=request.client.host if request and request.client else None,
    )

    return result.data[0]
