from uuid import UUID
from datetime import datetime, timezone
from loguru import logger
from app.database import get_supabase
from app.config import get_settings
from app.notifications.token_service import generate_action_token
from app.notifications.email_sender import send_email
from app.notifications.email_templates import (
    render_change_proposed,
    render_change_confirmed,
    render_client_sign_request,
    render_change_closed,
)
from app.events.publisher import publish_event


async def send_change_proposed(change_event_id: UUID):
    """Notification 1: Alert contractor that a change was detected.

    - Generates confirm/reject action tokens
    - Sends email via Resend with action buttons
    - Creates in-app notification
    - Emits SSE event
    """
    db = get_supabase()
    settings = get_settings()

    # Fetch change event with project + contractor info
    ce = (
        db.table("change_events")
        .select("*, projects!inner(id, name, contractor_id, client_name, "
                "contractors!inner(id, user_id, email, name))")
        .eq("id", str(change_event_id))
        .single()
        .execute()
    ).data

    contractor = ce["projects"]["contractors"]
    contractor_email = contractor["email"]
    contractor_name = contractor["name"]
    contractor_id = ce["projects"]["contractor_id"]
    project_name = ce["projects"]["name"]
    project_id = ce["projects"]["id"]

    # Generate action tokens
    confirm_token = generate_action_token(
        change_event_id=change_event_id, action="confirm"
    )
    reject_token = generate_action_token(
        change_event_id=change_event_id, action="reject"
    )

    # Build action URLs
    confirm_url = (
        f"{settings.backend_url}/api/v1/change-events/{change_event_id}/confirm"
        f"?token={confirm_token}"
    )
    reject_url = (
        f"{settings.backend_url}/api/v1/change-events/{change_event_id}/reject"
        f"?token={reject_token}"
    )
    edit_url = f"{settings.app_base_url}/change-events/{change_event_id}/edit"

    # Store notification records
    now = datetime.now(timezone.utc).isoformat()
    token_expires = generate_action_token.__wrapped__ if hasattr(generate_action_token, '__wrapped__') else None

    for action_token, notif_type in [
        (confirm_token, "change_proposed"),
        (reject_token, "change_proposed"),
    ]:
        db.table("notifications").insert(
            {
                "project_id": project_id,
                "change_event_id": str(change_event_id),
                "type": notif_type,
                "recipient_email": contractor_email,
                "recipient_role": "contractor",
                "action_token": action_token,
                "sent_at": now,
            }
        ).execute()

    # Create in-app notification
    db.table("in_app_notifications").insert(
        {
            "contractor_id": contractor_id,
            "type": "change_proposed",
            "title": f"New change detected in {project_name}",
            "body": ce["description"][:200],
            "entity_type": "change_event",
            "entity_id": str(change_event_id),
        }
    ).execute()

    # Send email via Resend
    evidence_html = ""
    if ce.get("evidence_urls"):
        evidence_html = '<div class="evidence"><p><strong>Evidence attached</strong></p></div>'

    html = render_change_proposed(
        contractor_name=contractor_name,
        project_name=project_name,
        description=ce["description"],
        area=ce.get("area"),
        confidence=ce.get("confidence_score", 0.0),
        confirm_url=confirm_url,
        reject_url=reject_url,
        edit_url=edit_url,
        evidence_html=evidence_html,
    )

    await send_email(
        to=contractor_email,
        subject=f"[SiteTrace] Change detected in {project_name}",
        html=html,
    )

    # Emit SSE event
    await publish_event(
        contractor_id=contractor_id,
        event_type="change_event.created",
        data={
            "change_event_id": str(change_event_id),
            "project_id": project_id,
            "description": ce["description"][:100],
            "status": ce["status"],
            "confidence": ce.get("confidence_score"),
        },
    )

    logger.info(
        f"Change proposed notification sent to {contractor_email} "
        f"(CE: {change_event_id}, Project: {project_name})"
    )


async def send_change_confirmed(change_event_id: UUID):
    """Notification 2: Confirm to contractor that the change was accepted
    and a Change Order has been created."""
    db = get_supabase()
    settings = get_settings()

    ce = (
        db.table("change_events")
        .select("*, projects!inner(id, name, contractor_id, "
                "contractors!inner(id, email, name))")
        .eq("id", str(change_event_id))
        .single()
        .execute()
    ).data

    contractor = ce["projects"]["contractors"]
    contractor_email = contractor["email"]
    contractor_name = contractor["name"]
    contractor_id = ce["projects"]["contractor_id"]
    project_name = ce["projects"]["name"]
    project_id = ce["projects"]["id"]

    # Find associated change order
    co = (
        db.table("change_orders")
        .select("id, order_number")
        .eq("project_id", project_id)
        .order("created_at", desc=True)
        .limit(1)
        .maybe_single()
        .execute()
    ).data

    order_number = co["order_number"] if co else "Pending"
    co_url = f"{settings.app_base_url}/change-orders/{co['id']}" if co else ""

    # Send email
    html = render_change_confirmed(
        contractor_name=contractor_name,
        project_name=project_name,
        description=ce["description"],
        order_number=order_number,
        co_url=co_url,
    )

    await send_email(
        to=contractor_email,
        subject=f"[SiteTrace] Change Order {order_number} created — {project_name}",
        html=html,
    )

    # Store notification
    db.table("notifications").insert(
        {
            "project_id": project_id,
            "change_event_id": str(change_event_id),
            "type": "change_confirmed",
            "recipient_email": contractor_email,
            "recipient_role": "contractor",
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()

    # In-app notification
    db.table("in_app_notifications").insert(
        {
            "contractor_id": contractor_id,
            "type": "change_confirmed",
            "title": f"Change Order {order_number} created",
            "body": f"Your confirmed change in {project_name} is now a Change Order.",
            "entity_type": "change_order",
            "entity_id": co["id"] if co else str(change_event_id),
        }
    ).execute()

    # SSE event
    await publish_event(
        contractor_id=contractor_id,
        event_type="change_event.confirmed",
        data={
            "change_event_id": str(change_event_id),
            "project_id": project_id,
            "order_number": order_number,
        },
    )

    logger.info(
        f"Change confirmed notification sent to {contractor_email} "
        f"(CE: {change_event_id}, CO: {order_number})"
    )


async def send_client_sign_request(change_order_id: UUID):
    """Notification 3: Send Change Order to client for digital signature."""
    db = get_supabase()
    settings = get_settings()

    co = (
        db.table("change_orders")
        .select("*, projects!inner(id, name, client_name, client_email, contractor_id, "
                "contractors!inner(id, email, name))")
        .eq("id", str(change_order_id))
        .single()
        .execute()
    ).data

    client_email = co["projects"]["client_email"]
    client_name = co["projects"]["client_name"]
    contractor_name = co["projects"]["contractors"]["name"]
    contractor_id = co["projects"]["contractor_id"]
    project_name = co["projects"]["name"]
    project_id = co["projects"]["id"]

    # Generate sign token
    sign_token = generate_action_token(
        change_order_id=change_order_id,
        action="sign",
        client_email=client_email,
    )

    sign_url = (
        f"{settings.backend_url}/api/v1/change-orders/{change_order_id}/sign"
        f"?token={sign_token}"
    )
    pdf_url = co.get("pdf_url", "")

    # Send email to CLIENT
    html = render_client_sign_request(
        client_name=client_name,
        contractor_name=contractor_name,
        project_name=project_name,
        order_number=co["order_number"],
        description=co["description"],
        total=str(co.get("total", "0.00")),
        currency=co.get("currency", "USD"),
        sign_url=sign_url,
        pdf_url=pdf_url,
    )

    await send_email(
        to=client_email,
        subject=f"[SiteTrace] Change Order {co['order_number']} — Signature Required",
        html=html,
    )

    # Store notification
    db.table("notifications").insert(
        {
            "project_id": project_id,
            "change_event_id": None,
            "type": "client_sign_request",
            "recipient_email": client_email,
            "recipient_role": "client",
            "action_token": sign_token,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()

    # Update CO status
    db.table("change_orders").update(
        {
            "status": "sent_to_client",
            "sent_to_client_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", str(change_order_id)).execute()

    # State transition
    db.table("state_transitions").insert(
        {
            "entity_type": "change_order",
            "entity_id": str(change_order_id),
            "from_status": "draft",
            "to_status": "sent_to_client",
            "actor_type": "contractor",
            "metadata": {"client_email": client_email},
        }
    ).execute()

    # SSE event
    await publish_event(
        contractor_id=contractor_id,
        event_type="change_order.sent",
        data={
            "change_order_id": str(change_order_id),
            "project_id": project_id,
            "order_number": co["order_number"],
            "client_email": client_email,
        },
    )

    logger.info(
        f"Client sign request sent to {client_email} "
        f"(CO: {co['order_number']}, Project: {project_name})"
    )


async def send_change_closed(change_order_id: UUID):
    """Notification 4: Notify contractor that client signed the CO."""
    db = get_supabase()
    settings = get_settings()

    co = (
        db.table("change_orders")
        .select("*, projects!inner(id, name, client_name, client_email, contractor_id, "
                "contractors!inner(id, email, name))")
        .eq("id", str(change_order_id))
        .single()
        .execute()
    ).data

    contractor = co["projects"]["contractors"]
    contractor_email = contractor["email"]
    contractor_name = contractor["name"]
    contractor_id = co["projects"]["contractor_id"]
    project_name = co["projects"]["name"]
    project_id = co["projects"]["id"]
    client_name = co["projects"]["client_name"]

    html = render_change_closed(
        contractor_name=contractor_name,
        project_name=project_name,
        order_number=co["order_number"],
        client_name=client_name,
        signed_at=co.get("signed_at", ""),
        total=str(co.get("total", "0.00")),
        currency=co.get("currency", "USD"),
        co_url=f"{settings.app_base_url}/change-orders/{co['id']}",
    )

    await send_email(
        to=contractor_email,
        subject=f"[SiteTrace] Change Order {co['order_number']} signed — {project_name}",
        html=html,
    )

    # Store notification
    db.table("notifications").insert(
        {
            "project_id": project_id,
            "type": "change_closed",
            "recipient_email": contractor_email,
            "recipient_role": "contractor",
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()

    # In-app notification
    db.table("in_app_notifications").insert(
        {
            "contractor_id": contractor_id,
            "type": "change_closed",
            "title": f"CO {co['order_number']} signed by {client_name}",
            "body": f"Change Order in {project_name} has been approved and signed.",
            "entity_type": "change_order",
            "entity_id": str(change_order_id),
        }
    ).execute()

    # SSE event
    await publish_event(
        contractor_id=contractor_id,
        event_type="change_order.signed",
        data={
            "change_order_id": str(change_order_id),
            "project_id": project_id,
            "order_number": co["order_number"],
            "signed_at": co.get("signed_at"),
        },
    )

    logger.info(
        f"Change closed notification sent to {contractor_email} "
        f"(CO: {co['order_number']}, signed by {client_name})"
    )
