import jwt
from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import HTTPException
from app.config import get_settings


def generate_action_token(
    change_event_id: UUID | None = None,
    change_order_id: UUID | None = None,
    action: str = "confirm",
    client_email: str | None = None,
    expires_hours: int | None = None,
) -> str:
    """Generate a JWT action token for email-based actions."""
    settings = get_settings()
    if expires_hours is None:
        expires_hours = settings.action_token_expire_hours

    payload = {
        "action": action,
        "exp": datetime.now(timezone.utc) + timedelta(hours=expires_hours),
        "iat": datetime.now(timezone.utc),
    }

    if change_event_id:
        payload["change_event_id"] = str(change_event_id)
    if change_order_id:
        payload["change_order_id"] = str(change_order_id)
    if client_email:
        payload["client_email"] = client_email

    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_action_token(token: str) -> dict:
    """Verify and decode a JWT action token. Raises HTTPException on failure."""
    settings = get_settings()

    # Check if token was already used
    from app.database import get_supabase

    db = get_supabase()
    existing = (
        db.table("notifications")
        .select("action_token_used_at")
        .eq("action_token", token)
        .maybe_single()
        .execute()
    )
    if existing.data and existing.data.get("action_token_used_at"):
        raise HTTPException(status_code=410, detail="Token already used")

    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
