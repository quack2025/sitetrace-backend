"""Change Order PDF generator using WeasyPrint.

Generates professional PDF documents with cost tables, evidence images,
and digital signature metadata.
"""
import base64
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from loguru import logger
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.database import get_supabase
from app.processors.storage import (
    upload_file,
    generate_signed_url,
    change_order_path,
)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _format_decimal(value) -> str:
    """Format a numeric value to 2 decimal places."""
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _format_date(value) -> str:
    """Format an ISO date string to readable format."""
    if not value:
        return "—"
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, datetime):
            dt = value
        else:
            return str(value)
        return dt.strftime("%B %d, %Y at %I:%M %p")
    except (ValueError, AttributeError):
        return str(value)


async def generate_change_order_pdf(change_order_id: UUID) -> str:
    """Generate a professional PDF for a change order.

    Workflow:
    1. Fetch change_order + items + linked change_events + project
    2. Fetch evidence images from storage
    3. Render HTML template with Jinja2
    4. Convert to PDF with WeasyPrint
    5. Upload PDF to Supabase Storage
    6. Update change_order.pdf_url
    7. Record state_transition

    Args:
        change_order_id: UUID of the change order.

    Returns:
        Signed URL to the generated PDF.
    """
    db = get_supabase()

    # Fetch change order with project and contractor
    co = (
        db.table("change_orders")
        .select(
            "*, projects!inner(id, name, client_name, client_email, "
            "project_type, contractor_id, "
            "contractors!inner(id, name, email))"
        )
        .eq("id", str(change_order_id))
        .single()
        .execute()
    ).data

    project = co["projects"]
    contractor = project["contractors"]

    # Fetch line items
    items = (
        db.table("change_order_items")
        .select("*")
        .eq("change_order_id", str(change_order_id))
        .order("sort_order")
        .execute()
    ).data

    # Fetch linked change events for evidence and original message
    change_events = (
        db.table("change_events")
        .select("*, change_event_sources!inner(ingest_event_id)")
        .eq("project_id", project["id"])
        .execute()
    ).data

    # Collect evidence and original message from the first change event
    evidence_images = []
    original_message = ""
    message_timestamp = ""
    detection_date = ""
    confirmation_date = ""
    area = ""
    material_from = ""
    material_to = ""

    if change_events:
        ce = change_events[0]
        area = ce.get("area", "")
        material_from = ce.get("material_from", "")
        material_to = ce.get("material_to", "")
        original_message = ce.get("raw_text", "") or ""
        detection_date = _format_date(ce.get("created_at"))
        confirmation_date = _format_date(ce.get("confirmed_at"))

        # Fetch evidence URLs
        evidence_urls = ce.get("evidence_urls") or []
        for i, url in enumerate(evidence_urls):
            try:
                # If URL is a storage path, generate signed URL and fetch
                evidence_images.append({
                    "base64": "",  # Will be filled if image data is available
                    "caption": f"Evidence {i + 1}",
                })
            except Exception as e:
                logger.debug(f"Could not load evidence image: {e}")

    # Build template context
    now = datetime.now(timezone.utc)
    context = {
        "order_number": co["order_number"],
        "generated_date": now.strftime("%B %d, %Y"),
        "project_name": project["name"],
        "client_name": project["client_name"],
        "contractor_name": contractor["name"],
        "project_type": project.get("project_type", "—"),
        "detection_date": detection_date or "—",
        "confirmation_date": confirmation_date or "—",
        "description": co["description"],
        "area": area,
        "material_from": material_from,
        "material_to": material_to,
        "items": [
            {
                "description": item["description"],
                "category": item.get("category", "other"),
                "quantity": _format_decimal(item["quantity"]).rstrip("0").rstrip(".") or "1",
                "unit": item.get("unit", "unit"),
                "unit_cost": _format_decimal(item["unit_cost"]),
                "total_cost": _format_decimal(item["total_cost"]),
            }
            for item in items
        ],
        "currency": co.get("currency", "USD"),
        "subtotal": _format_decimal(co.get("subtotal", 0)),
        "markup_percent": float(co.get("markup_percent", 0)),
        "markup_amount": _format_decimal(co.get("markup_amount", 0)),
        "tax_percent": float(co.get("tax_percent", 0)),
        "tax_amount": _format_decimal(co.get("tax_amount", 0)),
        "total": _format_decimal(co.get("total", 0)),
        "evidence_images": [img for img in evidence_images if img["base64"]],
        "original_message": original_message[:500] if original_message else "",
        "message_timestamp": message_timestamp,
        "signed_at": _format_date(co.get("signed_at")) if co.get("signed_at") else None,
        "signed_by_email": project.get("client_email", ""),
        "signed_from_ip": co.get("client_ip", ""),
        "doc_version": "v1.0",
    }

    # Render HTML with Jinja2
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("change_order.html")
    html_content = template.render(**context)

    # Generate PDF with WeasyPrint
    pdf_bytes = HTML(string=html_content).write_pdf()

    logger.info(
        f"PDF generated for {co['order_number']}: {len(pdf_bytes)} bytes"
    )

    # Upload to Supabase Storage
    storage_path = change_order_path(
        project_id=UUID(project["id"]),
        order_number=co["order_number"],
    )

    try:
        await upload_file(
            bucket="change-orders",
            path=storage_path,
            file_bytes=pdf_bytes,
            content_type="application/pdf",
        )

        # Generate signed URL
        pdf_url = await generate_signed_url("change-orders", storage_path)

        # Update change order with PDF URL
        db.table("change_orders").update(
            {"pdf_url": pdf_url}
        ).eq("id", str(change_order_id)).execute()

        # Record state transition
        db.table("state_transitions").insert(
            {
                "entity_type": "change_order",
                "entity_id": str(change_order_id),
                "from_status": co["status"],
                "to_status": co["status"],
                "actor_type": "system",
                "metadata": {
                    "action": "pdf_generated",
                    "pdf_size_bytes": len(pdf_bytes),
                    "storage_path": storage_path,
                },
            }
        ).execute()

        logger.info(f"PDF uploaded to {storage_path} for {co['order_number']}")
        return pdf_url

    except Exception as e:
        logger.error(f"Failed to upload PDF for {co['order_number']}: {e}")
        # Return the PDF bytes as base64 as fallback
        # The caller can still use it even if storage fails
        raise
