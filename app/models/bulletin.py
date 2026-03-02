from pydantic import BaseModel
from datetime import datetime
from uuid import UUID


class BulletinResponse(BaseModel):
    id: UUID
    project_id: UUID
    change_order_id: UUID | None = None
    bulletin_number: str
    title: str
    summary_text: str
    affected_areas: list[dict] = []
    distribution_list: list[dict] = []
    pdf_url: str | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
