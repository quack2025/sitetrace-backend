from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class TeamMemberCreate(BaseModel):
    name: str
    email: str
    role: str | None = None
    receives_bulletins: bool = True
    phone: str | None = None


class TeamMemberUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    role: str | None = None
    receives_bulletins: bool | None = None
    phone: str | None = None


class TeamMemberResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    email: str
    role: str | None = None
    receives_bulletins: bool
    phone: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
