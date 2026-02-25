from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class ChangeEventProposal(BaseModel):
    """Output from AI agents — a proposed change event."""
    is_change_event: bool
    confidence: float
    description: str = ""
    area: str | None = None
    material_from: str | None = None
    material_to: str | None = None
    requester_name: str | None = None
    urgency: str = "normal"


class ChangeEventCreate(BaseModel):
    """Manual creation of a change event."""
    description: str
    area: str | None = None
    material_from: str | None = None
    material_to: str | None = None
    notes: str | None = None


class ChangeEventUpdate(BaseModel):
    """Editable fields before confirmation."""
    description: str | None = None
    area: str | None = None
    material_from: str | None = None
    material_to: str | None = None


class ChangeEventResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    description: str
    area: str | None = None
    material_from: str | None = None
    material_to: str | None = None
    confidence_score: float | None = None
    raw_text: str | None = None
    evidence_urls: list[str] = []
    prompt_version: str | None = None
    model_used: str | None = None
    tokens_used: int | None = None
    processing_time_ms: int | None = None
    proposed_at: datetime | None = None
    confirmed_at: datetime | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class RejectRequest(BaseModel):
    reason: str | None = None
