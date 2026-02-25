from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class TimestampMixin(BaseModel):
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PaginationParams(BaseModel):
    offset: int = 0
    limit: int = 50


class PaginatedResponse(BaseModel):
    data: list
    total: int
    offset: int
    limit: int


class StateTransitionCreate(BaseModel):
    entity_type: str  # 'change_event' | 'change_order' | 'project' | 'integration'
    entity_id: UUID
    from_status: str | None = None
    to_status: str
    actor_id: UUID | None = None
    actor_type: str  # 'system' | 'contractor' | 'client' | 'ai'
    reason: str | None = None
    metadata: dict = {}
    ip_address: str | None = None
