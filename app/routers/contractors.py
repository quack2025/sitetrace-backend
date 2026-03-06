from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from loguru import logger
from app.auth import get_current_user, get_current_contractor
from app.database import get_supabase

router = APIRouter(prefix="/api/v1", tags=["contractors"])


class ContractorCreate(BaseModel):
    name: str
    company: str | None = None
    phone: str | None = None


class ContractorUpdate(BaseModel):
    name: str | None = None
    company: str | None = None
    phone: str | None = None


@router.get("/contractors/me")
async def get_my_profile(user: dict = Depends(get_current_user)):
    """Get the current user's contractor profile. Returns 404 if not onboarded."""
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


@router.post("/contractors", status_code=201)
async def create_contractor(body: ContractorCreate, user: dict = Depends(get_current_user)):
    """Create a contractor profile for the authenticated user (onboarding)."""
    db = get_supabase()

    # Check if already exists
    existing = (
        db.table("contractors")
        .select("id")
        .eq("user_id", user["user_id"])
        .maybe_single()
        .execute()
    )

    if existing.data:
        raise HTTPException(
            status_code=409,
            detail="Contractor profile already exists.",
        )

    data = {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": body.name,
        "company": body.company,
        "phone": body.phone,
    }

    result = db.table("contractors").insert(data).execute()

    logger.info(f"Contractor created: {result.data[0]['id']} for user {user['user_id']}")
    return result.data[0]


@router.put("/contractors/me")
async def update_my_profile(body: ContractorUpdate, contractor: dict = Depends(get_current_contractor)):
    """Update the current contractor's profile."""
    db = get_supabase()

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")

    result = (
        db.table("contractors")
        .update(updates)
        .eq("id", contractor["id"])
        .execute()
    )

    return result.data[0]
