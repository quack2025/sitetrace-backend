import json
import time
from pathlib import Path
from loguru import logger
from anthropic import Anthropic
from app.config import get_settings
from app.models.change_event import ChangeEventProposal

PROMPT_DIR = Path(__file__).parent / "prompts" / "text_detection"


def _load_prompt(version: str = "v1") -> str:
    prompt_file = PROMPT_DIR / f"{version}.txt"
    return prompt_file.read_text(encoding="utf-8")


async def detect_changes_in_text(
    text: str,
    subject: str = "",
    project_name: str = "",
    project_type: str = "",
    scope_summary: str = "",
    key_materials: str = "",
    prompt_version: str = "v1",
) -> tuple[list[ChangeEventProposal], dict]:
    """Analyze text for construction change events.

    Returns:
        Tuple of (list of proposals, metadata dict with model/tokens/timing info)
    """
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)

    prompt_template = _load_prompt(prompt_version)
    system_prompt = prompt_template.format(
        project_name=project_name or "Unknown",
        project_type=project_type or "Unknown",
        scope_summary=scope_summary or "Not provided",
        key_materials=key_materials or "Not specified",
    )

    user_message = f"Subject: {subject}\n\n{text}" if subject else text

    start_time = time.time()

    response = client.messages.create(
        model="claude-sonnet-4-5-20250514",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    elapsed_ms = int((time.time() - start_time) * 1000)
    model_used = "claude-sonnet-4-5-20250514"
    tokens_used = response.usage.input_tokens + response.usage.output_tokens

    # Parse response
    raw_text = response.content[0].text.strip()

    # Extract JSON from response (handle markdown code blocks)
    if "```json" in raw_text:
        raw_text = raw_text.split("```json")[1].split("```")[0].strip()
    elif "```" in raw_text:
        raw_text = raw_text.split("```")[1].split("```")[0].strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse Claude response as JSON: {raw_text[:200]}")
        return [], {
            "prompt_version": f"text_detection:{prompt_version}",
            "model_used": model_used,
            "tokens_used": tokens_used,
            "processing_time_ms": elapsed_ms,
            "error": "JSON parse failed",
        }

    changes = parsed.get("changes", [])
    proposals = []

    for change in changes:
        if not change.get("is_change_event", False):
            continue
        proposals.append(
            ChangeEventProposal(
                is_change_event=True,
                confidence=change.get("confidence", 0.5),
                description=change.get("description", ""),
                area=change.get("area"),
                material_from=change.get("material_from"),
                material_to=change.get("material_to"),
                requester_name=change.get("requester_name"),
                urgency=change.get("urgency", "normal"),
            )
        )

    metadata = {
        "prompt_version": f"text_detection:{prompt_version}",
        "model_used": model_used,
        "tokens_used": tokens_used,
        "processing_time_ms": elapsed_ms,
    }

    logger.info(
        f"Text detector: {len(proposals)} changes found "
        f"(tokens: {tokens_used}, time: {elapsed_ms}ms)"
    )

    return proposals, metadata
