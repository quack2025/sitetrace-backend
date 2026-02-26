"""Contractor Foreman API integration.

Exports SiteTrace change orders to Contractor Foreman project management.
Handles rate limiting, retries, and graceful failure.
"""
import httpx
import time
from uuid import UUID
from loguru import logger
from app.config import get_settings
from app.database import get_supabase
from app.integrations.transformers.cf_transformer import transform_to_cf_format

CF_API_BASE = "https://api.contractorforeman.com/v1"
MAX_RETRIES = 3
RETRY_DELAYS = [2, 5, 15]  # seconds


async def export_change_order_to_cf(change_order_id: UUID) -> str | None:
    """Export a change order to Contractor Foreman.

    Args:
        change_order_id: UUID of the change order to export.

    Returns:
        CF change order ID if successful, None if failed.
    """
    db = get_supabase()

    # Fetch change order with items and project
    co = (
        db.table("change_orders")
        .select(
            "*, projects!inner(id, name, client_name, cf_project_id, "
            "contractor_id, contractors!inner(id, name))"
        )
        .eq("id", str(change_order_id))
        .single()
        .execute()
    ).data

    # Fetch line items
    items = (
        db.table("change_order_items")
        .select("*")
        .eq("change_order_id", str(change_order_id))
        .order("sort_order")
        .execute()
    ).data

    # Get CF integration credentials
    integration = (
        db.table("integrations")
        .select("*")
        .eq("contractor_id", co["projects"]["contractor_id"])
        .eq("provider", "contractor_foreman")
        .eq("is_active", True)
        .maybe_single()
        .execute()
    ).data

    if not integration:
        logger.info(
            f"No active CF integration for contractor "
            f"{co['projects']['contractor_id']}, skipping export"
        )
        return None

    cf_project_id = co["projects"].get("cf_project_id")
    if not cf_project_id:
        logger.warning(
            f"Project {co['projects']['id']} has no cf_project_id, skipping CF export"
        )
        return None

    # Transform to CF format
    cf_payload = transform_to_cf_format(co, items, cf_project_id)

    # Send to CF API with retry logic
    api_key = integration.get("access_token") or integration.get("api_key")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    cf_co_id = None
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{CF_API_BASE}/change-orders",
                    headers=headers,
                    json=cf_payload,
                )

                if resp.status_code == 429:
                    # Rate limited — wait and retry
                    retry_after = int(resp.headers.get("Retry-After", RETRY_DELAYS[attempt]))
                    logger.warning(
                        f"CF API rate limited, retrying in {retry_after}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()
                cf_data = resp.json()
                cf_co_id = cf_data.get("id") or cf_data.get("change_order_id")
                break

        except httpx.HTTPStatusError as e:
            logger.error(
                f"CF API error (attempt {attempt + 1}/{MAX_RETRIES}): "
                f"{e.response.status_code} {e.response.text[:200]}"
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])
        except Exception as e:
            logger.error(
                f"CF API request failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}"
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAYS[attempt])

    if cf_co_id:
        # Store CF reference in our database
        db.table("change_orders").update(
            {"cf_change_order_id": str(cf_co_id)}
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
                    "action": "cf_export",
                    "cf_change_order_id": str(cf_co_id),
                    "cf_project_id": cf_project_id,
                },
            }
        ).execute()

        logger.info(
            f"Exported CO {co['order_number']} to CF: {cf_co_id}"
        )
    else:
        logger.error(
            f"Failed to export CO {co['order_number']} to CF after {MAX_RETRIES} attempts"
        )

    return cf_co_id
