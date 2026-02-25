from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from app.config import get_settings, Settings
from app.database import get_supabase

security = HTTPBearer()


def _decode_supabase_token(token: str, settings: Settings) -> dict:
    """Decode and validate a Supabase JWT token."""
    try:
        payload = jwt.decode(
            token,
            settings.supabase_anon_key,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Extract and validate the current user from the Bearer token."""
    settings = get_settings()
    payload = _decode_supabase_token(credentials.credentials, settings)

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token: no user ID")

    return {"user_id": user_id, "email": payload.get("email", "")}


async def get_current_contractor(user: dict = Depends(get_current_user)) -> dict:
    """Fetch the contractor record for the authenticated user."""
    db = get_supabase()
    result = (
        db.table("contractors")
        .select("*")
        .eq("user_id", user["user_id"])
        .maybe_single()
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=404,
            detail="Contractor profile not found. Please complete onboarding.",
        )

    return result.data
