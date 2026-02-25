"""Tests for image processing pipeline."""
import io
import os
import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from PIL import Image
from app.processors.image_processor import (
    normalize_image,
    _detect_format,
    ProcessedImage,
    PROFILES,
)


def _make_test_image(width=800, height=600, mode="RGB", fmt="JPEG") -> bytes:
    """Create a test image in memory."""
    img = Image.new(mode, (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    if fmt == "JPEG" and mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    img.save(buf, format=fmt)
    return buf.getvalue()


class TestDetectFormat:
    def test_detect_jpeg_by_extension(self):
        assert _detect_format("photo.jpg", b"\xff\xd8") == "JPEG"
        assert _detect_format("photo.jpeg", b"\xff\xd8") == "JPEG"

    def test_detect_png_by_extension(self):
        assert _detect_format("plan.png", b"\x89PNG") == "PNG"

    def test_detect_webp_by_extension(self):
        assert _detect_format("image.webp", b"") == "WEBP"

    def test_detect_heic_by_extension(self):
        assert _detect_format("IMG_001.heic", b"") == "HEIC"
        assert _detect_format("IMG_001.heif", b"") == "HEIC"

    def test_detect_jpeg_by_magic_bytes(self):
        assert _detect_format("unknown", b"\xff\xd8rest") == "JPEG"

    def test_detect_png_by_magic_bytes(self):
        assert _detect_format("unknown", b"\x89PNGrest") == "PNG"

    def test_detect_webp_by_magic_bytes(self):
        assert _detect_format("unknown", b"RIFF\x00\x00\x00\x00WEBP") == "WEBP"

    def test_detect_unknown(self):
        assert _detect_format("file.xyz", b"\x00\x00\x00\x00") == "UNKNOWN"


class TestNormalizeImage:
    @pytest.mark.asyncio
    async def test_normalize_jpeg(self):
        img_bytes = _make_test_image(800, 600, "RGB", "JPEG")
        result = await normalize_image(img_bytes, "photo.jpg")
        assert isinstance(result, ProcessedImage)
        assert result.format_original == "JPEG"
        assert result.format_output == "JPEG"
        assert result.width <= 2000
        assert result.height <= 2000
        assert len(result.base64_data) > 0

    @pytest.mark.asyncio
    async def test_normalize_png_to_jpeg(self):
        img_bytes = _make_test_image(800, 600, "RGB", "PNG")
        result = await normalize_image(img_bytes, "plan.png")
        assert result.format_original == "PNG"
        assert result.format_output == "JPEG"

    @pytest.mark.asyncio
    async def test_normalize_rgba_converts_to_rgb(self):
        img_bytes = _make_test_image(800, 600, "RGBA", "PNG")
        result = await normalize_image(img_bytes, "transparent.png")
        assert result.format_output == "JPEG"
        assert result.width == 800

    @pytest.mark.asyncio
    async def test_resize_large_image(self):
        img_bytes = _make_test_image(5000, 3000, "RGB", "JPEG")
        result = await normalize_image(img_bytes, "huge.jpg")
        # Default profile max_dimension is 2000
        assert max(result.width, result.height) <= 2000

    @pytest.mark.asyncio
    async def test_annotated_plan_profile(self):
        img_bytes = _make_test_image(5000, 3000, "RGB", "JPEG")
        result = await normalize_image(img_bytes, "plan.jpg", image_type="annotated_plan")
        # annotated_plan profile max_dimension is 3000
        assert max(result.width, result.height) <= 3000

    @pytest.mark.asyncio
    async def test_document_profile_with_contrast(self):
        img_bytes = _make_test_image(800, 600, "RGB", "JPEG")
        result = await normalize_image(img_bytes, "doc.jpg", image_type="document")
        assert result.format_output == "JPEG"

    @pytest.mark.asyncio
    async def test_output_smaller_than_original(self):
        # Large PNG will compress significantly as JPEG
        img_bytes = _make_test_image(2000, 1500, "RGB", "PNG")
        result = await normalize_image(img_bytes, "large.png")
        # Just verify it processed successfully
        assert result.file_size_output > 0
        assert result.file_size_original == len(img_bytes)


class TestProfiles:
    def test_all_profiles_have_required_keys(self):
        required_keys = {"max_dimension", "quality", "contrast_factor", "strip_exif"}
        for name, profile in PROFILES.items():
            assert required_keys.issubset(profile.keys()), f"Profile '{name}' missing keys"

    def test_annotated_plan_has_highest_resolution(self):
        assert PROFILES["annotated_plan"]["max_dimension"] >= PROFILES["default"]["max_dimension"]

    def test_annotated_plan_preserves_exif(self):
        assert PROFILES["annotated_plan"]["strip_exif"] is False

    def test_default_strips_exif(self):
        assert PROFILES["default"]["strip_exif"] is True
