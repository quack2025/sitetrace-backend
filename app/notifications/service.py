from uuid import UUID
from loguru import logger
from app.database import get_supabase
from app.notifications.token_service import generate_action_token


async def send_change_proposed(change_event_id: UUID):
    """Notification 1: Alert contractor that a change was detected."""
    db = get_supabase()

    # Fetch change event with project info
    ce = (
        db.table("change_events")
        .select("*, projects!inner(name, contractor_id, contractors!inner(email, name))")
        .eq("id", str(change_event_id))
        .single()
        .execute()
    ).data

    contractor_email = ce["projects"]["contractors"]["email"]
    contractor_name = ce["projects"]["contractors"]["name"]
    project_name = ce["projects"]["name"]

    # Generate action tokens
    confirm_token = generate_action_token(
        change_event_id=change_event_id, action="confirm"
    )
    reject_token = generate_action_token(
        change_event_id=change_event_id, action="reject"
    )

    # Store notification
    db.table("notifications").insert(
        {
            "project_id": ce["project_id"],
            "change_event_id": str(change_event_id),
            "type": "change_proposed",
            "recipient_email": contractor_email,
            "recipient_role": "contractor",
            "action_token": confirm_token,
        }
    ).execute()

    # Also store reject token notification
    db.table("notifications").insert(
        {
            "project_id": ce["project_id"],
            "change_event_id": str(change_event_id),
            "type": "change_proposed",
            "recipient_email": contractor_email,
            "recipient_role": "contractor",
            "action_token": reject_token,
        }
    ).execute()

    # Create in-app notification
    contractor_id = ce["projects"]["contractor_id"]
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

    # TODO: Send actual email via Resend (Sprint 2)
    logger.info(
        f"Change proposed notification queued for {contractor_email} "
        f"(CE: {change_event_id}, Project: {project_name})"
    )


async def send_change_confirmed(change_event_id: UUID):
    """Notification 2: Confirm to contractor that change order was created."""
    # TODO: Sprint 2 — Full implementation
    logger.info(f"Change confirmed notification for CE: {change_event_id}")


async def send_client_sign_request(change_order_id: UUID):
    """Notification 3: Send change order to client for signature."""
    # TODO: Sprint 4 — Full implementation with PDF attachment
    logger.info(f"Client sign request for CO: {change_order_id}")


async def send_change_closed(change_order_id: UUID):
    """Notification 4: Notify contractor that client signed."""
    # TODO: Sprint 4 — Full implementation
    logger.info(f"Change closed notification for CO: {change_order_id}")
