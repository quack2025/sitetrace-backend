from fastapi import APIRouter, Depends, HTTPException, Request
from uuid import UUID
from datetime import datetime, timezone
from decimal import Decimal
from loguru import logger
from app.auth import get_current_contractor
from app.database import get_supabase
from app.models.change_order import (
    ChangeOrderItemCreate,
    ChangeOrderItemUpdate,
    ChangeOrderItemResponse,
    ChangeOrderResponse,
)
from app.notifications.token_service import verify_action_token

router = APIRouter(prefix="/api/v1/change-orders", tags=["change-orders"])


def _verify_co_access(change_order_id: UUID, contractor_id: str) -> dict:
    """Fetch change order and verify ownership."""
    db = get_supabase()
    result = (
        db.table("change_orders")
        .select("*, projects!inner(contractor_id)")
        .eq("id", str(change_order_id))
        .maybe_single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Change order not found")
    if result.data["projects"]["contractor_id"] != contractor_id:
        raise HTTPException(status_code=404, detail="Change order not found")
    return result.data


def _recalculate_totals(change_order_id: UUID):
    """Recalculate subtotal, markup, tax, and total for a change order."""
    db = get_supabase()

    # Get all items
    items = (
        db.table("change_order_items")
        .select("total_cost")
        .eq("change_order_id", str(change_order_id))
        .execute()
    )
    subtotal = sum(Decimal(str(item["total_cost"])) for item in items.data)

    # Get current CO for markup/tax percentages
    co = (
        db.table("change_orders")
        .select("markup_percent, tax_percent")
        .eq("id", str(change_order_id))
        .single()
        .execute()
    )

    markup_percent = Decimal(str(co.data["markup_percent"]))
    tax_percent = Decimal(str(co.data["tax_percent"]))

    markup_amount = subtotal * markup_percent / 100
    tax_amount = (subtotal + markup_amount) * tax_percent / 100
    total = subtotal + markup_amount + tax_amount

    db.table("change_orders").update(
        {
            "subtotal": float(subtotal),
            "markup_amount": float(markup_amount),
            "tax_amount": float(tax_amount),
            "total": float(total),
        }
    ).eq("id", str(change_order_id)).execute()


@router.get("/{change_order_id}", response_model=ChangeOrderResponse)
async def get_change_order(
    change_order_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    co = _verify_co_access(change_order_id, contractor["id"])
    co.pop("projects", None)

    # Fetch items
    db = get_supabase()
    items = (
        db.table("change_order_items")
        .select("*")
        .eq("change_order_id", str(change_order_id))
        .order("sort_order")
        .execute()
    )
    co["items"] = items.data
    return co


@router.post(
    "/{change_order_id}/items",
    response_model=ChangeOrderItemResponse,
    status_code=201,
)
async def add_item(
    change_order_id: UUID,
    body: ChangeOrderItemCreate,
    contractor: dict = Depends(get_current_contractor),
):
    co = _verify_co_access(change_order_id, contractor["id"])
    if co["status"] == "signed":
        raise HTTPException(status_code=409, detail="Cannot modify a signed change order")

    db = get_supabase()
    total_cost = float(body.quantity * body.unit_cost)

    data = body.model_dump(exclude_none=True)
    data["change_order_id"] = str(change_order_id)
    data["total_cost"] = total_cost
    # Convert Decimals to float for JSON
    for key in ("quantity", "unit_cost"):
        if key in data:
            data[key] = float(data[key])
    if "change_event_id" in data and data["change_event_id"]:
        data["change_event_id"] = str(data["change_event_id"])

    result = db.table("change_order_items").insert(data).execute()
    _recalculate_totals(change_order_id)
    return result.data[0]


@router.put(
    "/{change_order_id}/items/{item_id}",
    response_model=ChangeOrderItemResponse,
)
async def update_item(
    change_order_id: UUID,
    item_id: UUID,
    body: ChangeOrderItemUpdate,
    contractor: dict = Depends(get_current_contractor),
):
    co = _verify_co_access(change_order_id, contractor["id"])
    if co["status"] == "signed":
        raise HTTPException(status_code=409, detail="Cannot modify a signed change order")

    db = get_supabase()
    data = body.model_dump(exclude_none=True)

    # Fetch current item to recalculate total_cost
    current = (
        db.table("change_order_items")
        .select("*")
        .eq("id", str(item_id))
        .eq("change_order_id", str(change_order_id))
        .maybe_single()
        .execute()
    )
    if not current.data:
        raise HTTPException(status_code=404, detail="Item not found")

    quantity = data.get("quantity", current.data["quantity"])
    unit_cost = data.get("unit_cost", current.data["unit_cost"])
    data["total_cost"] = float(Decimal(str(quantity)) * Decimal(str(unit_cost)))

    # Convert Decimals to float
    for key in ("quantity", "unit_cost"):
        if key in data:
            data[key] = float(data[key])

    result = (
        db.table("change_order_items")
        .update(data)
        .eq("id", str(item_id))
        .eq("change_order_id", str(change_order_id))
        .execute()
    )
    _recalculate_totals(change_order_id)
    return result.data[0]


@router.delete("/{change_order_id}/items/{item_id}", status_code=204)
async def delete_item(
    change_order_id: UUID,
    item_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    co = _verify_co_access(change_order_id, contractor["id"])
    if co["status"] == "signed":
        raise HTTPException(status_code=409, detail="Cannot modify a signed change order")

    db = get_supabase()
    db.table("change_order_items").delete().eq("id", str(item_id)).eq(
        "change_order_id", str(change_order_id)
    ).execute()
    _recalculate_totals(change_order_id)


@router.post("/{change_order_id}/generate-pdf")
async def generate_pdf(
    change_order_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    """Generate or regenerate the Change Order PDF."""
    co = _verify_co_access(change_order_id, contractor["id"])

    from app.pdf.change_order_generator import generate_change_order_pdf
    try:
        pdf_url = await generate_change_order_pdf(change_order_id)
        return {"pdf_url": pdf_url, "order_number": co["order_number"]}
    except Exception as e:
        logger.error(f"PDF generation failed for {change_order_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate PDF")


@router.post("/{change_order_id}/send", response_model=ChangeOrderResponse)
async def send_to_client(
    change_order_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    """Generate PDF and send Change Order to client for signature."""
    co = _verify_co_access(change_order_id, contractor["id"])

    if co["status"] != "draft":
        raise HTTPException(
            status_code=409,
            detail=f"Can only send draft change orders, current status: {co['status']}",
        )

    # Verify CO has at least one item with cost
    db = get_supabase()
    items = (
        db.table("change_order_items")
        .select("id")
        .eq("change_order_id", str(change_order_id))
        .execute()
    )
    if not items.data:
        raise HTTPException(
            status_code=400,
            detail="Add at least one cost line item before sending to client",
        )

    # Generate PDF before sending
    from app.pdf.change_order_generator import generate_change_order_pdf
    try:
        await generate_change_order_pdf(change_order_id)
    except Exception as e:
        logger.warning(f"PDF generation failed, sending without PDF: {e}")

    # Send notification to client
    from app.notifications.service import send_client_sign_request
    await send_client_sign_request(change_order_id)

    # Refresh and return
    result = (
        db.table("change_orders")
        .select("*")
        .eq("id", str(change_order_id))
        .single()
        .execute()
    )
    co_data = result.data
    co_items = (
        db.table("change_order_items")
        .select("*")
        .eq("change_order_id", str(change_order_id))
        .order("sort_order")
        .execute()
    )
    co_data["items"] = co_items.data
    return co_data


@router.post("/{change_order_id}/sign", response_model=ChangeOrderResponse)
async def sign_change_order(
    change_order_id: UUID,
    token: str,
    request: Request,
):
    """Client signs a Change Order via click-to-sign token."""
    payload = verify_action_token(token)
    if payload.get("change_order_id") != str(change_order_id):
        raise HTTPException(status_code=403, detail="Token does not match this change order")
    if payload.get("action") != "sign":
        raise HTTPException(status_code=403, detail="Invalid action for this token")

    db = get_supabase()

    co = (
        db.table("change_orders")
        .select("*, projects!inner(client_email)")
        .eq("id", str(change_order_id))
        .maybe_single()
        .execute()
    )
    if not co.data:
        raise HTTPException(status_code=404, detail="Change order not found")

    if co.data["status"] == "signed":
        raise HTTPException(status_code=410, detail="Change order already signed")

    # Verify client email matches token
    if payload.get("client_email") != co.data["projects"]["client_email"]:
        raise HTTPException(status_code=403, detail="Email mismatch")

    now = datetime.now(timezone.utc).isoformat()

    # Mark token as used
    db.table("notifications").update(
        {"action_token_used_at": now}
    ).eq("action_token", token).execute()

    # Sign the change order
    client_ip = request.client.host if request.client else None
    client_ua = request.headers.get("user-agent", "")

    result = (
        db.table("change_orders")
        .update(
            {
                "status": "signed",
                "signed_at": now,
                "client_ip": client_ip,
                "client_user_agent": client_ua,
            }
        )
        .eq("id", str(change_order_id))
        .execute()
    )

    # Record state transition
    db.table("state_transitions").insert(
        {
            "entity_type": "change_order",
            "entity_id": str(change_order_id),
            "from_status": co.data["status"],
            "to_status": "signed",
            "actor_type": "client",
            "metadata": {"client_ip": client_ip, "user_agent": client_ua},
            "ip_address": client_ip,
        }
    ).execute()

    # Update linked change events to 'signed' status
    linked_ces = (
        db.table("change_events")
        .select("id, status")
        .eq("project_id", co.data.get("project_id"))
        .in_("status", ["proposed", "confirmed"])
        .execute()
    )
    for ce in linked_ces.data:
        db.table("change_events").update(
            {"status": "signed"}
        ).eq("id", ce["id"]).execute()
        db.table("state_transitions").insert(
            {
                "entity_type": "change_event",
                "entity_id": ce["id"],
                "from_status": ce["status"],
                "to_status": "signed",
                "actor_type": "client",
                "metadata": {"change_order_id": str(change_order_id)},
            }
        ).execute()

    # Regenerate PDF with digital signature metadata
    try:
        from app.pdf.change_order_generator import generate_change_order_pdf
        await generate_change_order_pdf(change_order_id)
    except Exception as e:
        logger.warning(f"Post-sign PDF regeneration failed: {e}")

    # Send close notification to contractor
    try:
        from app.notifications.service import send_change_closed
        await send_change_closed(change_order_id)
    except Exception as e:
        logger.error(f"Failed to send close notification: {e}")

    signed = result.data[0]
    signed.pop("projects", None)
    signed["items"] = []
    return signed
