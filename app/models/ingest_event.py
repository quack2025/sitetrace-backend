from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class IngestEventCreate(BaseModel):
    project_id: UUID | None = None
    channel: str  # gmail, outlook, whatsapp, manual, api
    raw_payload: dict
    attachments: list[dict] = []
    sender_email: str | None = None
    sender_name: str | None = None
    subject: str | None = None
    received_at: datetime | None = None
    external_message_id: str | None = None


class IngestEventResponse(BaseModel):
    id: UUID
    project_id: UUID | None = None
    channel: str
    sender_email: str | None = None
    sender_name: str | None = None
    subject: str | None = None
    received_at: datetime | None = None
    processing_status: str
    error_message: str | None = None
    processed_at: datetime | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
