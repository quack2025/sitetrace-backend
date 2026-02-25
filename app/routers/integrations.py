from fastapi import APIRouter, Depends
from app.auth import get_current_contractor
from app.database import get_supabase

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


@router.get("/status")
async def get_integration_status(contractor: dict = Depends(get_current_contractor)):
    """Get the status of all integrations for the current contractor."""
    db = get_supabase()
    result = (
        db.table("integrations")
        .select("id, type, is_active, last_polled_at, created_at")
        .eq("contractor_id", contractor["id"])
        .execute()
    )
    return {
        "integrations": result.data,
        "available": ["gmail", "outlook", "contractor_foreman"],
    }
