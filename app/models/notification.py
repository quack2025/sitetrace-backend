from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class InAppNotificationResponse(BaseModel):
    id: UUID
    type: str
    title: str
    body: str | None = None
    entity_type: str | None = None
    entity_id: UUID | None = None
    read_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class UnreadCountResponse(BaseModel):
    count: int
