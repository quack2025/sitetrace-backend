from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from app.auth import get_current_contractor
from app.database import get_supabase
from app.models.project import ProjectCreate, ProjectUpdate, ProjectResponse

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


def _verify_project_ownership(project_id: UUID, contractor_id: str) -> dict:
    """Fetch project and verify it belongs to the contractor."""
    db = get_supabase()
    result = (
        db.table("projects")
        .select("*")
        .eq("id", str(project_id))
        .eq("contractor_id", contractor_id)
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")
    return result.data


@router.get("", response_model=list[ProjectResponse])
async def list_projects(contractor: dict = Depends(get_current_contractor)):
    db = get_supabase()
    result = (
        db.table("projects")
        .select("*")
        .eq("contractor_id", contractor["id"])
        .order("created_at", desc=True)
        .execute()
    )
    return result.data


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    contractor: dict = Depends(get_current_contractor),
):
    db = get_supabase()
    data = body.model_dump(exclude_none=True)
    data["contractor_id"] = contractor["id"]

    # Convert key_materials to JSON-safe format
    if "key_materials" in data and data["key_materials"] is not None:
        data["key_materials"] = [dict(m) for m in data["key_materials"]]

    # Convert Decimal to float for JSON
    if "original_budget" in data and data["original_budget"] is not None:
        data["original_budget"] = float(data["original_budget"])

    result = db.table("projects").insert(data).execute()
    return result.data[0]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    return _verify_project_ownership(project_id, contractor["id"])


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    contractor: dict = Depends(get_current_contractor),
):
    _verify_project_ownership(project_id, contractor["id"])

    db = get_supabase()
    data = body.model_dump(exclude_none=True)

    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Convert key_materials to JSON-safe format
    if "key_materials" in data and data["key_materials"] is not None:
        data["key_materials"] = [dict(m) for m in data["key_materials"]]

    # Convert Decimal to float for JSON
    if "original_budget" in data and data["original_budget"] is not None:
        data["original_budget"] = float(data["original_budget"])

    result = (
        db.table("projects")
        .update(data)
        .eq("id", str(project_id))
        .eq("contractor_id", contractor["id"])
        .execute()
    )
    return result.data[0]
