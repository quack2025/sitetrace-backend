"""AI agent that generates Document Bulletins from change order data.

Uses Claude to synthesize change event details into clear, actionable
bulletins that field workers can understand at a glance.
"""
import json
import time
from pathlib import Path
from loguru import logger
from anthropic import Anthropic
from app.config import get_settings

PROMPT_DIR = Path(__file__).parent / "prompts" / "bulletin_generator"


def _load_prompt(version: str = "v1") -> str:
    prompt_file = PROMPT_DIR / f"{version}.txt"
    return prompt_file.read_text(encoding="utf-8")


async def generate_bulletin_content(
    change_events: list[dict],
    change_order: dict,
    project: dict,
    prompt_version: str = "v1",
) -> tuple[dict, dict]:
    """Generate bulletin content from change order data.

    Args:
        change_events: List of change event records linked to the CO.
        change_order: The change order record.
        project: The project record.
        prompt_version: Prompt version to use.

    Returns:
        Tuple of (bulletin_content dict, metadata dict).
    """
    settings = get_settings()

    if not settings.anthropic_api_key:
        logger.warning("Anthropic API key not configured, generating fallback bulletin")
        return _fallback_bulletin(change_events, change_order), {
            "model_used": "fallback",
            "tokens_used": 0,
            "processing_time_ms": 0,
        }

    client = Anthropic(api_key=settings.anthropic_api_key)

    prompt_template = _load_prompt(prompt_version)
    system_prompt = prompt_template.format(
        project_name=project.get("name", "Unknown"),
        project_type=project.get("project_type", "Unknown"),
        client_name=project.get("client_name", "Unknown"),
    )

    # Build user message with all change event details
    changes_text = _format_changes_for_prompt(change_events, change_order)

    start_time = time.time()

    response = client.messages.create(
        model="claude-sonnet-4-5-20250514",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": changes_text}],
    )

    elapsed_ms = int((time.time() - start_time) * 1000)

    raw_text = response.content[0].text.strip()
    # Strip markdown code fence if present
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3].strip()

    try:
        bulletin_content = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse bulletin JSON: {raw_text[:500]}")
        bulletin_content = _fallback_bulletin(change_events, change_order)

    metadata = {
        "model_used": response.model,
        "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
        "processing_time_ms": elapsed_ms,
        "prompt_version": prompt_version,
    }

    logger.info(
        f"Generated bulletin for CO {change_order.get('order_number')}: "
        f"{metadata['tokens_used']} tokens in {elapsed_ms}ms"
    )

    return bulletin_content, metadata


def _format_changes_for_prompt(
    change_events: list[dict],
    change_order: dict,
) -> str:
    """Format change events into a clear prompt for Claude."""
    lines = [
        f"Change Order: {change_order.get('order_number', 'N/A')}",
        f"Description: {change_order.get('description', 'N/A')}",
        f"Total: ${change_order.get('total', 0):,.2f}",
        "",
        "## Changes Approved:",
    ]

    for i, ce in enumerate(change_events, 1):
        lines.append(f"\n### Change {i}")
        lines.append(f"- Description: {ce.get('description', 'N/A')}")
        lines.append(f"- Area: {ce.get('area', 'Not specified')}")
        if ce.get("material_from"):
            lines.append(f"- Material FROM: {ce['material_from']}")
        if ce.get("material_to"):
            lines.append(f"- Material TO: {ce['material_to']}")
        lines.append(f"- Confidence: {ce.get('confidence_score', 0):.0%}")

    return "\n".join(lines)


def _fallback_bulletin(
    change_events: list[dict],
    change_order: dict,
) -> dict:
    """Generate a basic bulletin without AI when API key is not available."""
    changes_summary = []
    affected = []

    for ce in change_events:
        desc = ce.get("description", "Change detected")
        area = ce.get("area", "General")
        changes_summary.append(f"- {desc}")

        if ce.get("material_from") and ce.get("material_to"):
            changes_summary.append(
                f"  Changed from: {ce['material_from']} → {ce['material_to']}"
            )

        affected.append({
            "category": area.lower().replace(" ", "_"),
            "description": desc,
            "action": f"Verify documents related to {area} are up to date.",
        })

    summary = (
        f"Change Order {change_order.get('order_number', 'N/A')} has been signed.\n\n"
        f"## Changes:\n" + "\n".join(changes_summary) + "\n\n"
        f"Please verify that all project documents affected by these changes "
        f"are updated to their latest versions."
    )

    return {
        "title": f"Changes Approved — {change_order.get('order_number', 'CO')}",
        "summary_text": summary,
        "affected_areas": affected,
    }
