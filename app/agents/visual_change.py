"""Visual change detection agent — extracts change events from classified images.

Uses Claude vision with image-type-specific prompts to extract construction
change proposals from annotated plans, reference images, and field photos.
"""
import json
import time
from pathlib import Path
from loguru import logger
from anthropic import Anthropic
from app.config import get_settings
from app.models.change_event import ChangeEventProposal

PROMPT_DIR = Path(__file__).parent / "prompts" / "visual_change"


def _load_prompt(version: str = "v1") -> str:
    prompt_file = PROMPT_DIR / f"{version}.txt"
    return prompt_file.read_text(encoding="utf-8")


async def extract_changes_from_image(
    image_base64: str,
    image_type: str,
    media_type: str = "image/jpeg",
    project_name: str = "",
    project_type: str = "",
    scope_summary: str = "",
    key_materials: str = "",
    prompt_version: str = "v1",
) -> tuple[list[ChangeEventProposal], dict]:
    """Extract construction change events from a classified image.

    Args:
        image_base64: Base64-encoded image data.
        image_type: Classification from image_classifier (annotated_plan, etc).
        media_type: MIME type (image/jpeg, image/png, etc).
        project_name: Name of the project for context.
        project_type: Type of construction project.
        scope_summary: Original project scope description.
        key_materials: Key materials specified in the project.
        prompt_version: Which prompt version to use.

    Returns:
        Tuple of (list of change proposals, metadata dict).
    """
    # Skip unclassifiable images
    if image_type in ("other", "document"):
        logger.info(f"Skipping visual change detection for image_type={image_type}")
        return [], {
            "prompt_version": f"visual_change:{prompt_version}",
            "model_used": "claude-sonnet-4-5-20250514",
            "tokens_used": 0,
            "processing_time_ms": 0,
            "skipped": True,
            "reason": f"image_type={image_type}",
        }

    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)

    prompt_template = _load_prompt(prompt_version)
    system_prompt = prompt_template.format(
        image_type=image_type,
        project_name=project_name or "Unknown",
        project_type=project_type or "Unknown",
        scope_summary=scope_summary or "Not provided",
        key_materials=key_materials or "Not specified",
    )

    start_time = time.time()

    response = client.messages.create(
        model="claude-sonnet-4-5-20250514",
        max_tokens=2048,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_base64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Analyze this image for construction changes.",
                    },
                ],
            }
        ],
    )

    elapsed_ms = int((time.time() - start_time) * 1000)
    tokens_used = response.usage.input_tokens + response.usage.output_tokens

    raw_text = response.content[0].text.strip()

    # Extract JSON from response
    if "```json" in raw_text:
        raw_text = raw_text.split("```json")[1].split("```")[0].strip()
    elif "```" in raw_text:
        raw_text = raw_text.split("```")[1].split("```")[0].strip()

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse visual change response: {raw_text[:200]}")
        return [], {
            "prompt_version": f"visual_change:{prompt_version}",
            "model_used": "claude-sonnet-4-5-20250514",
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
        "prompt_version": f"visual_change:{prompt_version}",
        "model_used": "claude-sonnet-4-5-20250514",
        "tokens_used": tokens_used,
        "processing_time_ms": elapsed_ms,
        "image_type": image_type,
    }

    logger.info(
        f"Visual change detector ({image_type}): {len(proposals)} changes found "
        f"(tokens={tokens_used}, time={elapsed_ms}ms)"
    )

    return proposals, metadata
