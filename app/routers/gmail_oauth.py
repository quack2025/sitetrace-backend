"""Gmail OAuth2 endpoints for connecting Gmail to SiteTrace.

Flow:
1. POST /integrations/gmail/connect → returns Google OAuth URL
2. User authorizes in browser
3. GET /integrations/gmail/callback → exchanges code for tokens, stores in DB
"""
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
import httpx

from app.auth import get_current_contractor
from app.config import get_settings
from app.database import get_supabase

router = APIRouter(prefix="/api/v1/integrations/gmail", tags=["integrations"])

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
]


@router.post("/connect")
async def gmail_connect(contractor: dict = Depends(get_current_contractor)):
    """Start Gmail OAuth flow. Returns the Google authorization URL."""
    settings = get_settings()

    if not settings.gmail_client_id or not settings.gmail_redirect_uri:
        raise HTTPException(
            status_code=503,
            detail="Gmail integration not configured. Set GMAIL_CLIENT_ID and GMAIL_REDIRECT_URI.",
        )

    params = {
        "client_id": settings.gmail_client_id,
        "redirect_uri": settings.gmail_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": contractor["id"],  # Pass contractor_id as state for callback
    }

    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    logger.info(f"Gmail OAuth initiated for contractor {contractor['id']}")

    return {"auth_url": auth_url}


@router.get("/callback")
async def gmail_callback(code: str, state: str, request: Request):
    """Handle Google OAuth callback. Exchanges code for tokens."""
    settings = get_settings()
    contractor_id = state  # state contains the contractor_id

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    # Exchange code for tokens
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.gmail_client_id,
                "client_secret": settings.gmail_client_secret,
                "redirect_uri": settings.gmail_redirect_uri,
                "grant_type": "authorization_code",
            },
        )

        if resp.status_code != 200:
            logger.error(f"Gmail token exchange failed: {resp.text[:300]}")
            raise HTTPException(
                status_code=502,
                detail="Failed to exchange authorization code with Google",
            )

        tokens = resp.json()

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in", 3600)
    token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    if not refresh_token:
        raise HTTPException(
            status_code=400,
            detail="No refresh token received. Please revoke access at "
            "https://myaccount.google.com/permissions and try again.",
        )

    db = get_supabase()

    # Upsert: update existing Gmail integration or create new one
    existing = (
        db.table("integrations")
        .select("id")
        .eq("contractor_id", contractor_id)
        .eq("type", "gmail")
        .maybe_single()
        .execute()
    )

    integration_data = {
        "contractor_id": contractor_id,
        "type": "gmail",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expires_at": token_expires_at.isoformat(),
        "is_active": True,
    }

    if existing.data:
        db.table("integrations").update(integration_data).eq(
            "id", existing.data["id"]
        ).execute()
        logger.info(f"Gmail integration updated for contractor {contractor_id}")
    else:
        db.table("integrations").insert(integration_data).execute()
        logger.info(f"Gmail integration created for contractor {contractor_id}")

    # Record state transition
    db.table("state_transitions").insert(
        {
            "entity_type": "integration",
            "entity_id": existing.data["id"] if existing.data else contractor_id,
            "from_status": None,
            "to_status": "connected",
            "actor_type": "contractor",
            "metadata": {"type": "gmail"},
        }
    ).execute()

    # Redirect to frontend success page
    return {
        "status": "connected",
        "message": "Gmail connected successfully. Email polling will start within 5 minutes.",
    }
