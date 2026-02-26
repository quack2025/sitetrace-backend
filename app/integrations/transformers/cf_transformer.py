"""Transform SiteTrace change order data to Contractor Foreman API format."""


def transform_to_cf_format(
    change_order: dict,
    items: list[dict] | None = None,
    cf_project_id: str | None = None,
) -> dict:
    """Transform a SiteTrace change order into the Contractor Foreman API payload.

    Args:
        change_order: Change order dict with nested `projects` (with `contractors`).
        items: Line items list. If None, reads from change_order['change_order_items'].
        cf_project_id: CF-side project ID for linking.

    Returns:
        Dict formatted for CF API POST /change-orders.
    """
    project = change_order.get("projects", {})
    if items is None:
        items = change_order.get("change_order_items", [])

    cf_items = []
    for item in items:
        cf_items.append({
            "description": item["description"],
            "category": _map_category(item.get("category", "other")),
            "quantity": float(item.get("quantity", 1)),
            "unit": item.get("unit", "unit"),
            "unit_price": float(item.get("unit_cost", 0)),
            "total": float(item.get("total_cost", 0)),
            "notes": item.get("notes", ""),
        })

    payload = {
        "project_name": project.get("name", ""),
        "order_number": change_order.get("order_number", ""),
        "description": change_order.get("description", ""),
        "status": _map_status(change_order.get("status", "draft")),
        "items": cf_items,
        "subtotal": float(change_order.get("subtotal", 0)),
        "markup_percent": float(change_order.get("markup_percent", 0)),
        "markup_amount": float(change_order.get("markup_amount", 0)),
        "tax_percent": float(change_order.get("tax_percent", 0)),
        "tax_amount": float(change_order.get("tax_amount", 0)),
        "total": float(change_order.get("total", 0)),
        "currency": change_order.get("currency", "USD"),
        "client_name": project.get("client_name", ""),
        "contractor_name": project.get("contractors", {}).get("name", ""),
        "source": "sitetrace",
        "external_id": str(change_order.get("id", "")),
    }
    if cf_project_id:
        payload["project_id"] = cf_project_id
    return payload


def _map_category(st_category: str) -> str:
    """Map SiteTrace category to CF category."""
    mapping = {
        "labor": "LABOR",
        "material": "MATERIAL",
        "equipment": "EQUIPMENT",
        "subcontract": "SUBCONTRACT",
        "other": "OTHER",
    }
    return mapping.get(st_category, "OTHER")


def _map_status(st_status: str) -> str:
    """Map SiteTrace status to CF status."""
    mapping = {
        "draft": "PENDING",
        "sent_to_client": "SUBMITTED",
        "signed": "APPROVED",
    }
    return mapping.get(st_status, "PENDING")
