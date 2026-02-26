"""Outlook OAuth2 connection flow.

Handles Microsoft OAuth authorization code flow for connecting
a contractor's Outlook account for email monitoring.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from datetime import datetime, timedelta, timezone
import httpx
from app.auth import get_current_contractor
from app.config import get_settings
from app.database import get_supabase

router = APIRouter(prefix="/api/v1/integrations/outlook", tags=["integrations"])

MS_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
SCOPES = "https://graph.microsoft.com/Mail.Read offline_access"


@router.post("/connect")
async def start_outlook_connection(
    contractor: dict = Depends(get_current_contractor),
):
    """Generate Microsoft OAuth URL for the contractor to authorize."""
    settings = get_settings()

    if not settings.outlook_client_id:
        raise HTTPException(status_code=501, detail="Outlook integration not configured")

    # Build OAuth URL
    params = {
        "client_id": settings.outlook_client_id,
        "response_type": "code",
        "redirect_uri": settings.outlook_redirect_uri,
        "scope": SCOPES,
        "response_mode": "query",
        "state": contractor["id"],
    }

    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    auth_url = f"{MS_AUTH_URL}?{query_string}"

    return {"auth_url": auth_url}


@router.get("/callback")
async def outlook_callback(code: str, state: str, request: Request):
    """Handle Microsoft OAuth callback — exchange code for tokens."""
    settings = get_settings()
    contractor_id = state

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            MS_TOKEN_URL,
            data={
                "client_id": settings.outlook_client_id,
                "client_secret": settings.outlook_client_secret,
                "code": code,
                "redirect_uri": settings.outlook_redirect_uri,
                "grant_type": "authorization_code",
                "scope": SCOPES,
            },
        )

        if resp.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Microsoft token exchange failed: {resp.text[:200]}",
            )

        tokens = resp.json()

    access_token = tokens["access_token"]
    refresh_token = tokens.get("refresh_token", "")
    expires_in = tokens.get("expires_in", 3600)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    # Fetch user email from Graph API
    async with httpx.AsyncClient() as client:
        me_resp = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if me_resp.status_code == 200:
            user_data = me_resp.json()
            connected_email = user_data.get("mail") or user_data.get("userPrincipalName", "")
        else:
            connected_email = ""

    # Upsert integration record
    db = get_supabase()

    existing = (
        db.table("integrations")
        .select("id")
        .eq("contractor_id", contractor_id)
        .eq("channel", "outlook")
        .maybe_single()
        .execute()
    )

    integration_data = {
        "contractor_id": contractor_id,
        "channel": "outlook",
        "provider": "microsoft_graph",
        "is_active": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expires_at": expires_at.isoformat(),
        "connected_email": connected_email,
    }

    if existing.data:
        db.table("integrations").update(integration_data).eq(
            "id", existing.data["id"]
        ).execute()
    else:
        db.table("integrations").insert(integration_data).execute()

    return {
        "status": "connected",
        "email": connected_email,
        "channel": "outlook",
    }
