from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class DocumentCreate(BaseModel):
    category: str
    name: str
    external_url: str | None = None
    mime_type: str | None = None
    notes: str | None = None


class DocumentUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    external_url: str | None = None
    notes: str | None = None


class DocumentVersionCreate(BaseModel):
    """Create a new version of an existing document (supersedes the previous)."""
    external_url: str | None = None
    mime_type: str | None = None
    notes: str | None = None


class DocumentResponse(BaseModel):
    id: UUID
    project_id: UUID
    category: str
    name: str
    version: int
    status: str
    storage_path: str | None = None
    external_url: str | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None
    superseded_by: UUID | None = None
    superseded_at: datetime | None = None
    notes: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class DocumentHealthResponse(BaseModel):
    total: int
    current: int
    superseded: int
    draft: int
    categories: dict[str, int]  # category -> count of current docs


class AffectedDocumentCreate(BaseModel):
    document_id: UUID
    impact_type: str = "supersedes"
    notes: str | None = None


class AffectedDocumentResponse(BaseModel):
    id: UUID
    change_order_id: UUID
    document_id: UUID
    impact_type: str
    notes: str | None = None
    created_at: datetime | None = None
    document: DocumentResponse | None = None

    model_config = {"from_attributes": True}
