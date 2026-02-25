from fastapi import APIRouter, Request, HTTPException
from loguru import logger

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events for billing."""
    # TODO: Sprint 6 — Stripe billing integration
    body = await request.json()
    event_type = body.get("type", "unknown")
    logger.info(f"Stripe webhook received: {event_type}")
    return {"received": True}
