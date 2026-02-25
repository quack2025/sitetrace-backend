from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from decimal import Decimal


class ChangeOrderItemCreate(BaseModel):
    change_event_id: UUID | None = None
    description: str
    category: str = "other"  # labor, material, equipment, subcontract, other
    quantity: Decimal = Decimal("1")
    unit: str = "unit"
    unit_cost: Decimal = Decimal("0")
    notes: str | None = None
    sort_order: int = 0


class ChangeOrderItemUpdate(BaseModel):
    description: str | None = None
    category: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_cost: Decimal | None = None
    notes: str | None = None
    sort_order: int | None = None


class ChangeOrderItemResponse(BaseModel):
    id: UUID
    change_order_id: UUID
    change_event_id: UUID | None = None
    description: str
    category: str | None = None
    quantity: Decimal
    unit: str
    unit_cost: Decimal
    total_cost: Decimal
    notes: str | None = None
    sort_order: int
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class ChangeOrderResponse(BaseModel):
    id: UUID
    project_id: UUID
    order_number: str
    description: str
    status: str
    subtotal: Decimal
    markup_percent: Decimal
    markup_amount: Decimal
    tax_percent: Decimal
    tax_amount: Decimal
    total: Decimal
    currency: str
    pdf_url: str | None = None
    cf_change_order_id: str | None = None
    items: list[ChangeOrderItemResponse] = []
    sent_to_client_at: datetime | None = None
    signed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
