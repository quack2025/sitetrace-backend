from fastapi import APIRouter, Request, HTTPException
from datetime import datetime, timezone
from loguru import logger
from app.config import get_settings
from app.database import get_supabase

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events for billing.

    Processes:
    - customer.subscription.created → activate subscription
    - customer.subscription.updated → update plan/status
    - customer.subscription.deleted → deactivate subscription
    - invoice.payment_failed → mark as past_due
    """
    settings = get_settings()
    body = await request.json()
    event_type = body.get("type", "unknown")
    data = body.get("data", {}).get("object", {})

    logger.info(f"Stripe webhook received: {event_type}")

    db = get_supabase()

    if event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
    ):
        stripe_customer_id = data.get("customer")
        stripe_subscription_id = data.get("id")
        status = data.get("status", "active")  # active, past_due, canceled, etc.

        # Map Stripe status to our status
        status_map = {
            "active": "active",
            "past_due": "past_due",
            "canceled": "canceled",
            "incomplete": "pending",
            "incomplete_expired": "canceled",
            "trialing": "active",
            "unpaid": "past_due",
        }
        mapped_status = status_map.get(status, status)

        # Extract plan from metadata or price
        plan = data.get("metadata", {}).get("plan", "starter")

        # Extract period end
        current_period_end = None
        if data.get("current_period_end"):
            current_period_end = datetime.fromtimestamp(
                data["current_period_end"], tz=timezone.utc
            ).isoformat()

        # Upsert subscription record
        db.table("contractor_subscriptions").update(
            {
                "stripe_subscription_id": stripe_subscription_id,
                "plan": plan,
                "status": mapped_status,
                "current_period_end": current_period_end,
            }
        ).eq("stripe_customer_id", stripe_customer_id).execute()

        logger.info(
            f"Subscription updated: customer={stripe_customer_id}, "
            f"plan={plan}, status={mapped_status}"
        )

    elif event_type == "customer.subscription.deleted":
        stripe_customer_id = data.get("customer")

        db.table("contractor_subscriptions").update(
            {"status": "canceled", "stripe_subscription_id": None}
        ).eq("stripe_customer_id", stripe_customer_id).execute()

        logger.info(f"Subscription canceled for customer {stripe_customer_id}")

    elif event_type == "invoice.payment_failed":
        stripe_customer_id = data.get("customer")

        db.table("contractor_subscriptions").update(
            {"status": "past_due"}
        ).eq("stripe_customer_id", stripe_customer_id).execute()

        logger.warning(f"Payment failed for customer {stripe_customer_id}")

    return {"received": True}
