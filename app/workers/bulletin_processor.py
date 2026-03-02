"""Celery task for generating and distributing Document Bulletins.

Triggered when a Change Order is signed. Generates an AI-powered bulletin,
creates a PDF, and distributes it to all project team members.
"""
import asyncio
from uuid import UUID
from datetime import datetime, timezone
from loguru import logger
from app.workers.celery_app import celery_app
from app.database import get_supabase


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="app.workers.bulletin_processor.generate_and_distribute_bulletin",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def generate_and_distribute_bulletin(self, change_order_id: str):
    """Generate a document bulletin for a signed change order.

    Steps:
    1. Fetch CO + linked change events + project + team members
    2. Generate bulletin content via Claude AI
    3. Generate PDF
    4. Store bulletin record
    5. Distribute via email to all team members
    """
    try:
        _run_async(_process_bulletin(change_order_id))
    except Exception as exc:
        logger.error(f"Bulletin generation failed for CO {change_order_id}: {exc}")
        raise self.retry(exc=exc)


async def _process_bulletin(change_order_id: str):
    from app.agents.bulletin_generator import generate_bulletin_content
    from app.pdf.bulletin_pdf_generator import generate_bulletin_pdf
    from app.notifications.email_sender import send_email
    from app.notifications.email_templates import render_document_bulletin

    db = get_supabase()

    # Fetch change order with project + contractor
    co = (
        db.table("change_orders")
        .select(
            "*, projects!inner(id, name, client_name, client_email, "
            "project_type, contractor_id, "
            "contractors!inner(id, name, email))"
        )
        .eq("id", change_order_id)
        .single()
        .execute()
    ).data

    project = co["projects"]
    contractor = project["contractors"]
    project_id = project["id"]

    # Fetch change events for this CO's project (confirmed/signed)
    change_events = (
        db.table("change_events")
        .select("*")
        .eq("project_id", project_id)
        .in_("status", ["confirmed", "signed"])
        .execute()
    ).data

    if not change_events:
        logger.warning(f"No confirmed change events for CO {change_order_id}")
        return

    # Fetch team members
    team_members = (
        db.table("project_team_members")
        .select("*")
        .eq("project_id", project_id)
        .eq("receives_bulletins", True)
        .execute()
    ).data

    if not team_members:
        logger.info(f"No team members to notify for project {project_id}")
        return

    # Generate bulletin number
    existing_count = (
        db.table("document_bulletins")
        .select("id", count="exact")
        .eq("project_id", project_id)
        .execute()
    ).count or 0
    bulletin_number = f"DB-{datetime.now().strftime('%Y')}-{existing_count + 1:03d}"

    # Generate content via AI
    bulletin_content, metadata = await generate_bulletin_content(
        change_events=change_events,
        change_order=co,
        project=project,
    )

    # Prepare recipients list
    recipients = [
        {"name": m["name"], "email": m["email"], "role": m.get("role", "")}
        for m in team_members
    ]

    now = datetime.now(timezone.utc).isoformat()

    # Store bulletin record
    bulletin_data = {
        "project_id": project_id,
        "change_order_id": change_order_id,
        "bulletin_number": bulletin_number,
        "title": bulletin_content.get("title", f"Changes — {co['order_number']}"),
        "summary_text": bulletin_content.get("summary_text", ""),
        "affected_areas": bulletin_content.get("affected_areas", []),
        "distribution_list": [
            {**r, "sent_at": now} for r in recipients
        ],
    }

    result = db.table("document_bulletins").insert(bulletin_data).execute()
    bulletin = result.data[0]

    # Generate PDF
    try:
        pdf_url = await generate_bulletin_pdf(
            bulletin=bulletin,
            change_order=co,
            project=project,
            contractor_name=contractor["name"],
            recipients=recipients,
        )

        db.table("document_bulletins").update(
            {"pdf_url": pdf_url}
        ).eq("id", bulletin["id"]).execute()

        bulletin["pdf_url"] = pdf_url
    except Exception as e:
        logger.error(f"Failed to generate bulletin PDF: {e}")
        pdf_url = None

    # Send email to each team member
    for member in team_members:
        try:
            html = render_document_bulletin(
                recipient_name=member["name"],
                project_name=project["name"],
                bulletin_number=bulletin_number,
                title=bulletin_content.get("title", ""),
                summary_text=bulletin_content.get("summary_text", ""),
                affected_areas=bulletin_content.get("affected_areas", []),
                order_number=co["order_number"],
                pdf_url=pdf_url,
            )

            await send_email(
                to=member["email"],
                subject=(
                    f"[SiteTrace] Document Bulletin {bulletin_number} — "
                    f"{project['name']}"
                ),
                html=html,
            )
        except Exception as e:
            logger.error(
                f"Failed to send bulletin to {member['email']}: {e}"
            )

    # Record state transition
    db.table("state_transitions").insert(
        {
            "entity_type": "document_bulletin",
            "entity_id": bulletin["id"],
            "from_status": None,
            "to_status": "distributed",
            "actor_type": "system",
            "metadata": {
                "change_order_id": change_order_id,
                "recipients_count": len(team_members),
                "ai_model": metadata.get("model_used"),
                "ai_tokens": metadata.get("tokens_used"),
            },
        }
    ).execute()

    logger.info(
        f"Bulletin {bulletin_number} distributed to {len(team_members)} "
        f"team members for CO {co['order_number']}"
    )
