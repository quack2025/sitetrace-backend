"""Image classification agent — uses Claude vision to classify construction images.

Classifies images into: annotated_plan, reference_image, field_photo, document, other.
"""
import json
import time
import base64
from pathlib import Path
from dataclasses import dataclass
from loguru import logger
from anthropic import Anthropic
from app.config import get_settings

PROMPT_DIR = Path(__file__).parent / "prompts" / "image_classification"


@dataclass
class ImageClassification:
    """Result of image classification."""
    image_type: str  # annotated_plan | reference_image | field_photo | document | other
    confidence: float
    description: str


def _load_prompt(version: str = "v1") -> str:
    prompt_file = PROMPT_DIR / f"{version}.txt"
    return prompt_file.read_text(encoding="utf-8")


async def classify_image(
    image_base64: str,
    media_type: str = "image/jpeg",
    prompt_version: str = "v1",
) -> tuple[ImageClassification, dict]:
    """Classify a construction image using Claude vision.

    Args:
        image_base64: Base64-encoded image data.
        media_type: MIME type of the image (image/jpeg, image/png, etc).
        prompt_version: Which prompt version to use.

    Returns:
        Tuple of (classification result, metadata dict).
    """
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)

    system_prompt = _load_prompt(prompt_version)
    start_time = time.time()

    response = client.messages.create(
        model="claude-sonnet-4-5-20250514",
        max_tokens=512,
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
                        "text": "Classify this construction image.",
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
        logger.error(f"Failed to parse classifier response: {raw_text[:200]}")
        parsed = {"type": "other", "confidence": 0.0, "description": "Parse error"}

    valid_types = {"annotated_plan", "reference_image", "field_photo", "document", "other"}
    image_type = parsed.get("type", "other")
    if image_type not in valid_types:
        logger.warning(f"Unknown image type '{image_type}', defaulting to 'other'")
        image_type = "other"

    classification = ImageClassification(
        image_type=image_type,
        confidence=parsed.get("confidence", 0.0),
        description=parsed.get("description", ""),
    )

    metadata = {
        "prompt_version": f"image_classification:{prompt_version}",
        "model_used": "claude-sonnet-4-5-20250514",
        "tokens_used": tokens_used,
        "processing_time_ms": elapsed_ms,
    }

    logger.info(
        f"Image classified: {classification.image_type} "
        f"(confidence={classification.confidence:.2f}, "
        f"tokens={tokens_used}, time={elapsed_ms}ms)"
    )

    return classification, metadata
