import json
from pathlib import Path
from loguru import logger
from anthropic import Anthropic
from app.config import get_settings
from app.database import get_supabase

PROMPT_FILE = Path(__file__).parent / "prompts" / "project_routing" / "v1.txt"


async def route_email_to_project(
    sender_email: str,
    sender_name: str,
    subject: str,
    body_preview: str,
    contractor_id: str,
) -> str | None:
    """Route an incoming email to the correct project using cascading logic.

    Returns project_id or None if no match.
    """
    db = get_supabase()

    # Fetch active projects for this contractor
    projects = (
        db.table("projects")
        .select("id, name, address, client_name, client_email, project_type")
        .eq("contractor_id", contractor_id)
        .eq("status", "active")
        .execute()
    ).data

    if not projects:
        return None

    # Step 1: Match by client_email
    for project in projects:
        if project.get("client_email", "").lower() == sender_email.lower():
            logger.info(
                f"Email routed to project {project['id']} by client_email match"
            )
            return project["id"]

    # Step 2: Match by keywords in subject vs project name
    subject_lower = subject.lower()
    for project in projects:
        project_name_lower = project["name"].lower()
        # Check if project name or significant part appears in subject
        words = project_name_lower.split()
        if len(words) >= 2:
            if any(w in subject_lower for w in words if len(w) > 3):
                logger.info(
                    f"Email routed to project {project['id']} by subject keyword match"
                )
                return project["id"]

    # Step 3: If only one active project, assign to it
    if len(projects) == 1:
        logger.info(
            f"Email routed to project {projects[0]['id']} (only active project)"
        )
        return projects[0]["id"]

    # Step 4: Use Claude for ambiguous cases
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)

    projects_list = "\n".join(
        f"- {p['id']}: {p['name']} (client: {p['client_name']}, email: {p['client_email']}, type: {p.get('project_type', 'N/A')})"
        for p in projects
    )

    prompt = PROMPT_FILE.read_text(encoding="utf-8").format(
        projects_list=projects_list,
        sender_email=sender_email,
        sender_name=sender_name,
        subject=subject,
        body_preview=body_preview[:500],
    )

    response = client.messages.create(
        model="claude-sonnet-4-5-20250514",
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    try:
        result = json.loads(raw)
        project_id = result.get("project_id")
        confidence = result.get("confidence", 0)

        if project_id and confidence >= 0.7:
            logger.info(
                f"Email routed to project {project_id} by AI "
                f"(confidence: {confidence:.2f}, reason: {result.get('reason', '')})"
            )
            return project_id
    except (json.JSONDecodeError, KeyError):
        logger.warning(f"AI project routing failed to parse: {raw[:200]}")

    # No match found
    logger.info("Email could not be routed to any project — will be unassigned")
    return None
