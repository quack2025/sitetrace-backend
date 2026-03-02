from fastapi import APIRouter, Depends, HTTPException
from uuid import UUID
from app.auth import get_current_contractor
from app.database import get_supabase
from app.models.team_member import TeamMemberCreate, TeamMemberUpdate, TeamMemberResponse
from app.routers.projects import _verify_project_ownership

router = APIRouter(prefix="/api/v1", tags=["team-members"])


@router.post(
    "/projects/{project_id}/team-members",
    response_model=TeamMemberResponse,
    status_code=201,
)
async def add_team_member(
    project_id: UUID,
    body: TeamMemberCreate,
    contractor: dict = Depends(get_current_contractor),
):
    _verify_project_ownership(project_id, contractor["id"])
    db = get_supabase()

    data = body.model_dump(exclude_none=True)
    data["project_id"] = str(project_id)

    result = db.table("project_team_members").insert(data).execute()
    return result.data[0]


@router.get(
    "/projects/{project_id}/team-members",
    response_model=list[TeamMemberResponse],
)
async def list_team_members(
    project_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    _verify_project_ownership(project_id, contractor["id"])
    db = get_supabase()

    result = (
        db.table("project_team_members")
        .select("*")
        .eq("project_id", str(project_id))
        .order("created_at")
        .execute()
    )
    return result.data


@router.put("/team-members/{member_id}", response_model=TeamMemberResponse)
async def update_team_member(
    member_id: UUID,
    body: TeamMemberUpdate,
    contractor: dict = Depends(get_current_contractor),
):
    db = get_supabase()

    # Verify ownership through project
    member = (
        db.table("project_team_members")
        .select("*, projects!inner(contractor_id)")
        .eq("id", str(member_id))
        .maybe_single()
        .execute()
    ).data
    if not member or member["projects"]["contractor_id"] != contractor["id"]:
        raise HTTPException(status_code=404, detail="Team member not found")

    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = (
        db.table("project_team_members")
        .update(data)
        .eq("id", str(member_id))
        .execute()
    )
    return result.data[0]


@router.delete("/team-members/{member_id}", status_code=204)
async def delete_team_member(
    member_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    db = get_supabase()

    member = (
        db.table("project_team_members")
        .select("*, projects!inner(contractor_id)")
        .eq("id", str(member_id))
        .maybe_single()
        .execute()
    ).data
    if not member or member["projects"]["contractor_id"] != contractor["id"]:
        raise HTTPException(status_code=404, detail="Team member not found")

    db.table("project_team_members").delete().eq("id", str(member_id)).execute()
