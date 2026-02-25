from pydantic import BaseModel, EmailStr
from datetime import datetime
from uuid import UUID
from decimal import Decimal


class ProjectCreate(BaseModel):
    name: str
    address: str | None = None
    client_name: str
    client_email: str
    project_type: str | None = None  # residential, commercial, remodel, new_build
    scope_summary: str | None = None
    key_materials: list[dict] | None = None
    original_budget: Decimal | None = None
    currency: str = "USD"
    gmail_label: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    client_name: str | None = None
    client_email: str | None = None
    status: str | None = None  # active, completed, archived
    project_type: str | None = None
    scope_summary: str | None = None
    key_materials: list[dict] | None = None
    original_budget: Decimal | None = None
    currency: str | None = None
    gmail_label: str | None = None


class ProjectResponse(BaseModel):
    id: UUID
    contractor_id: UUID
    name: str
    address: str | None = None
    client_name: str
    client_email: str
    status: str
    project_type: str | None = None
    scope_summary: str | None = None
    key_materials: list[dict] | None = None
    original_budget: Decimal | None = None
    currency: str
    gmail_label: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
