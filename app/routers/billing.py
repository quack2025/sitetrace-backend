"""Stripe billing endpoints — subscription management.

Plans:
- Starter: $200/month, 3 active projects
- Pro: $300/month, unlimited projects
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
import httpx
from app.auth import get_current_contractor
from app.config import get_settings
from app.database import get_supabase

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])

PLANS = {
    "starter": {
        "name": "Starter",
        "price_monthly": 200,
        "max_active_projects": 3,
    },
    "pro": {
        "name": "Pro",
        "price_monthly": 300,
        "max_active_projects": None,  # unlimited
    },
}


@router.get("/plans")
async def list_plans():
    """List available subscription plans."""
    return {"plans": PLANS}


@router.get("/subscription")
async def get_subscription(
    contractor: dict = Depends(get_current_contractor),
):
    """Get the current contractor's subscription status."""
    db = get_supabase()
    sub = (
        db.table("contractor_subscriptions")
        .select("*")
        .eq("contractor_id", contractor["id"])
        .maybe_single()
        .execute()
    ).data

    if not sub:
        return {
            "plan": None,
            "status": "inactive",
            "message": "No active subscription",
        }

    return {
        "plan": sub["plan"],
        "status": sub["status"],
        "current_period_end": sub.get("current_period_end"),
        "stripe_customer_id": sub.get("stripe_customer_id"),
    }


@router.post("/subscribe")
async def create_checkout_session(
    plan: str,
    contractor: dict = Depends(get_current_contractor),
):
    """Create a Stripe Checkout session for subscribing to a plan."""
    settings = get_settings()

    if not settings.stripe_secret_key:
        raise HTTPException(status_code=501, detail="Stripe not configured")

    if plan not in PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {plan}")

    # Get or create Stripe customer
    db = get_supabase()
    existing_sub = (
        db.table("contractor_subscriptions")
        .select("stripe_customer_id")
        .eq("contractor_id", contractor["id"])
        .maybe_single()
        .execute()
    ).data

    stripe_customer_id = existing_sub.get("stripe_customer_id") if existing_sub else None

    async with httpx.AsyncClient() as client:
        # Create customer if needed
        if not stripe_customer_id:
            resp = await client.post(
                "https://api.stripe.com/v1/customers",
                headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
                data={
                    "email": contractor["email"],
                    "name": contractor["name"],
                    "metadata[contractor_id]": contractor["id"],
                },
            )
            resp.raise_for_status()
            stripe_customer_id = resp.json()["id"]

            # Store customer ID
            db.table("contractor_subscriptions").upsert(
                {
                    "contractor_id": contractor["id"],
                    "stripe_customer_id": stripe_customer_id,
                    "plan": plan,
                    "status": "pending",
                }
            ).execute()

        # Create Checkout session
        price_id = settings.stripe_prices.get(plan, "")
        if not price_id:
            raise HTTPException(
                status_code=501,
                detail=f"Stripe price not configured for plan: {plan}",
            )

        resp = await client.post(
            "https://api.stripe.com/v1/checkout/sessions",
            headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
            data={
                "customer": stripe_customer_id,
                "mode": "subscription",
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": 1,
                "success_url": f"{settings.app_base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
                "cancel_url": f"{settings.app_base_url}/billing/cancel",
                "metadata[contractor_id]": contractor["id"],
                "metadata[plan]": plan,
            },
        )
        resp.raise_for_status()
        session = resp.json()

    return {"checkout_url": session["url"], "session_id": session["id"]}


@router.post("/portal")
async def create_portal_session(
    contractor: dict = Depends(get_current_contractor),
):
    """Create a Stripe Customer Portal session for managing subscription."""
    settings = get_settings()

    if not settings.stripe_secret_key:
        raise HTTPException(status_code=501, detail="Stripe not configured")

    db = get_supabase()
    sub = (
        db.table("contractor_subscriptions")
        .select("stripe_customer_id")
        .eq("contractor_id", contractor["id"])
        .maybe_single()
        .execute()
    ).data

    if not sub or not sub.get("stripe_customer_id"):
        raise HTTPException(status_code=404, detail="No Stripe customer found")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.stripe.com/v1/billing_portal/sessions",
            headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
            data={
                "customer": sub["stripe_customer_id"],
                "return_url": f"{settings.app_base_url}/billing",
            },
        )
        resp.raise_for_status()
        session = resp.json()

    return {"portal_url": session["url"]}
