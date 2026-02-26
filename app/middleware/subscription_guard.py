"""Subscription enforcement — checks project limits before creation.

Middleware-style dependency that verifies the contractor has an active
subscription and hasn't exceeded their project limit.
"""
from fastapi import Depends, HTTPException
from loguru import logger
from app.auth import get_current_contractor
from app.database import get_supabase

PLAN_LIMITS = {
    "starter": 3,
    "pro": None,  # unlimited
}


async def enforce_project_limit(
    contractor: dict = Depends(get_current_contractor),
) -> dict:
    """FastAPI dependency: check if contractor can create more projects.

    Returns the contractor dict if allowed.
    Raises 402 if at project limit.
    Raises 403 if no active subscription.
    """
    db = get_supabase()

    # Fetch subscription
    sub = (
        db.table("contractor_subscriptions")
        .select("plan, status")
        .eq("contractor_id", contractor["id"])
        .maybe_single()
        .execute()
    ).data

    if not sub or sub["status"] not in ("active", "trialing"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "No active subscription",
                "message": "Please subscribe to create projects.",
                "upgrade_url": "/billing/subscribe",
            },
        )

    plan = sub["plan"]
    limit = PLAN_LIMITS.get(plan)

    if limit is None:
        # Unlimited plan
        return contractor

    # Count active projects
    projects = (
        db.table("projects")
        .select("id", count="exact")
        .eq("contractor_id", contractor["id"])
        .eq("is_active", True)
        .execute()
    )
    active_count = projects.count or 0

    if active_count >= limit:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Project limit reached",
                "message": f"Your {plan.title()} plan allows {limit} active projects. "
                           f"Upgrade to Pro for unlimited projects.",
                "current_count": active_count,
                "limit": limit,
                "upgrade_url": "/billing/subscribe?plan=pro",
            },
        )

    return contractor
