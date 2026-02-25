from fastapi import APIRouter, Depends
from uuid import UUID
from datetime import datetime
from app.auth import get_current_contractor
from app.database import get_supabase
from app.models.notification import InAppNotificationResponse, UnreadCountResponse

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("/in-app", response_model=list[InAppNotificationResponse])
async def list_in_app_notifications(
    contractor: dict = Depends(get_current_contractor),
    limit: int = 50,
    offset: int = 0,
):
    db = get_supabase()
    result = (
        db.table("in_app_notifications")
        .select("*")
        .eq("contractor_id", contractor["id"])
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return result.data


@router.get("/in-app/unread-count", response_model=UnreadCountResponse)
async def get_unread_count(contractor: dict = Depends(get_current_contractor)):
    db = get_supabase()
    result = (
        db.table("in_app_notifications")
        .select("id", count="exact")
        .eq("contractor_id", contractor["id"])
        .is_("read_at", "null")
        .execute()
    )
    return {"count": result.count or 0}


@router.post("/in-app/{notification_id}/read", status_code=204)
async def mark_as_read(
    notification_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    db = get_supabase()
    db.table("in_app_notifications").update(
        {"read_at": datetime.utcnow().isoformat()}
    ).eq("id", str(notification_id)).eq("contractor_id", contractor["id"]).execute()
