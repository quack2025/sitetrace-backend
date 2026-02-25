"""Image processing pipeline — normalize images for AI analysis.

Supports: JPEG, PNG, WebP, HEIC/HEIF (iPhone).
Applies different processing profiles based on image type.
"""
import io
import base64
from dataclasses import dataclass
from loguru import logger

from PIL import Image, ImageEnhance

# Register HEIF opener if available
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:
    HEIF_SUPPORTED = False
    logger.warning("pillow-heif not available — HEIC images will not be supported")


@dataclass
class ProcessedImage:
    """Result of image normalization."""
    image_bytes: bytes
    base64_data: str
    format_original: str
    format_output: str
    width: int
    height: int
    file_size_original: int
    file_size_output: int


# Processing profiles per image type
PROFILES = {
    "annotated_plan": {
        "max_dimension": 3000,
        "quality": 92,
        "contrast_factor": 1.2,
        "strip_exif": False,
    },
    "reference_image": {
        "max_dimension": 2000,
        "quality": 88,
        "contrast_factor": None,
        "strip_exif": True,
    },
    "field_photo": {
        "max_dimension": 2000,
        "quality": 85,
        "contrast_factor": None,
        "strip_exif": True,
    },
    "document": {
        "max_dimension": 2500,
        "quality": 90,
        "contrast_factor": 1.1,
        "strip_exif": True,
    },
    "default": {
        "max_dimension": 2000,
        "quality": 85,
        "contrast_factor": None,
        "strip_exif": True,
    },
}


def _detect_format(filename: str, file_bytes: bytes) -> str:
    """Detect image format from filename and magic bytes."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext in ("heic", "heif"):
        return "HEIC"
    if ext == "webp":
        return "WEBP"
    if ext in ("jpg", "jpeg"):
        return "JPEG"
    if ext == "png":
        return "PNG"

    # Check magic bytes
    if file_bytes[:4] == b"\x89PNG":
        return "PNG"
    if file_bytes[:2] == b"\xff\xd8":
        return "JPEG"
    if file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP":
        return "WEBP"

    return "UNKNOWN"


async def normalize_image(
    file_bytes: bytes,
    filename: str,
    image_type: str | None = None,
) -> ProcessedImage:
    """Normalize an image for AI processing.

    Args:
        file_bytes: Raw image bytes.
        filename: Original filename (used for format detection).
        image_type: Classification from image_classifier agent.
                    One of: annotated_plan, reference_image, field_photo, document, other.

    Returns:
        ProcessedImage with normalized bytes, base64, and metadata.
    """
    original_size = len(file_bytes)
    original_format = _detect_format(filename, file_bytes)

    if original_format == "HEIC" and not HEIF_SUPPORTED:
        raise ValueError("HEIC format not supported — install pillow-heif")

    profile = PROFILES.get(image_type or "default", PROFILES["default"])

    # Open image
    img = Image.open(io.BytesIO(file_bytes))

    # Convert RGBA/P to RGB for JPEG output
    if img.mode in ("RGBA", "P", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if "A" in img.mode else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # Resize if too large
    max_dim = profile["max_dimension"]
    w, h = img.size
    if max(w, h) > max_dim:
        ratio = max_dim / max(w, h)
        new_w = int(w * ratio)
        new_h = int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        logger.debug(f"Resized {w}x{h} → {new_w}x{new_h}")

    # Apply contrast enhancement if specified
    if profile["contrast_factor"]:
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(profile["contrast_factor"])

    # Strip EXIF if specified (by saving without exif)
    output = io.BytesIO()
    save_kwargs = {"format": "JPEG", "quality": profile["quality"]}
    if not profile["strip_exif"]:
        # Preserve EXIF if available
        exif = img.info.get("exif")
        if exif:
            save_kwargs["exif"] = exif

    img.save(output, **save_kwargs)
    output_bytes = output.getvalue()

    # Encode to base64 for Claude API
    b64 = base64.b64encode(output_bytes).decode("utf-8")

    result = ProcessedImage(
        image_bytes=output_bytes,
        base64_data=b64,
        format_original=original_format,
        format_output="JPEG",
        width=img.size[0],
        height=img.size[1],
        file_size_original=original_size,
        file_size_output=len(output_bytes),
    )

    logger.info(
        f"Image normalized: {filename} ({original_format} → JPEG, "
        f"{original_size // 1024}KB → {len(output_bytes) // 1024}KB, "
        f"{result.width}x{result.height}, profile={image_type or 'default'})"
    )

    return result
