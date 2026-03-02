from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from loguru import logger
from app.auth import get_current_contractor
from app.database import get_supabase
from app.models.bulletin import BulletinResponse
from app.routers.projects import _verify_project_ownership

router = APIRouter(prefix="/api/v1", tags=["bulletins"])


@router.get(
    "/projects/{project_id}/bulletins",
    response_model=list[BulletinResponse],
)
async def list_bulletins(
    project_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    _verify_project_ownership(project_id, contractor["id"])
    db = get_supabase()

    result = (
        db.table("document_bulletins")
        .select("*")
        .eq("project_id", str(project_id))
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.get("/bulletins/{bulletin_id}", response_model=BulletinResponse)
async def get_bulletin(
    bulletin_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    db = get_supabase()
    bulletin = (
        db.table("document_bulletins")
        .select("*, projects!inner(contractor_id)")
        .eq("id", str(bulletin_id))
        .maybe_single()
        .execute()
    ).data

    if not bulletin or bulletin["projects"]["contractor_id"] != contractor["id"]:
        raise HTTPException(status_code=404, detail="Bulletin not found")

    bulletin.pop("projects", None)
    return bulletin


@router.post(
    "/change-orders/{co_id}/generate-bulletin",
    response_model=dict,
    status_code=202,
)
async def trigger_bulletin_generation(
    co_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    """Manually trigger bulletin generation for a change order."""
    db = get_supabase()

    co = (
        db.table("change_orders")
        .select("*, projects!inner(contractor_id)")
        .eq("id", str(co_id))
        .maybe_single()
        .execute()
    ).data
    if not co or co["projects"]["contractor_id"] != contractor["id"]:
        raise HTTPException(status_code=404, detail="Change order not found")

    from app.workers.bulletin_processor import generate_and_distribute_bulletin
    generate_and_distribute_bulletin.delay(str(co_id))

    logger.info(f"Bulletin generation triggered for CO {co_id}")
    return {"status": "queued", "change_order_id": str(co_id)}


@router.get("/bulletins/{bulletin_id}/tracking", response_model=list[dict])
async def get_bulletin_tracking(
    bulletin_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    """Get distribution tracking for a bulletin."""
    db = get_supabase()

    bulletin = (
        db.table("document_bulletins")
        .select("distribution_list, projects!inner(contractor_id)")
        .eq("id", str(bulletin_id))
        .maybe_single()
        .execute()
    ).data
    if not bulletin or bulletin["projects"]["contractor_id"] != contractor["id"]:
        raise HTTPException(status_code=404, detail="Bulletin not found")

    return bulletin.get("distribution_list", [])
