"""Tests for image classifier and visual change detection agents."""
import os
import json
import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.agents.image_classifier import classify_image, ImageClassification
from app.agents.visual_change import extract_changes_from_image
from app.models.change_event import ChangeEventProposal


def _mock_anthropic_response(text: str, input_tokens=100, output_tokens=50):
    """Create a mock Anthropic API response."""
    response = MagicMock()
    content_block = MagicMock()
    content_block.text = text
    response.content = [content_block]
    response.usage = MagicMock()
    response.usage.input_tokens = input_tokens
    response.usage.output_tokens = output_tokens
    return response


class TestImageClassifier:
    @pytest.mark.asyncio
    @patch("app.agents.image_classifier.Anthropic")
    async def test_classify_annotated_plan(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            json.dumps({
                "type": "annotated_plan",
                "confidence": 0.95,
                "description": "Architectural floor plan with red markup annotations"
            })
        )

        classification, metadata = await classify_image(
            image_base64="base64data",
            media_type="image/jpeg",
        )

        assert classification.image_type == "annotated_plan"
        assert classification.confidence == 0.95
        assert "floor plan" in classification.description
        assert metadata["model_used"] == "claude-sonnet-4-5-20250514"
        assert metadata["tokens_used"] == 150

    @pytest.mark.asyncio
    @patch("app.agents.image_classifier.Anthropic")
    async def test_classify_field_photo(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            json.dumps({
                "type": "field_photo",
                "confidence": 0.88,
                "description": "Construction site showing water damage"
            })
        )

        classification, _ = await classify_image("base64data")
        assert classification.image_type == "field_photo"
        assert classification.confidence == 0.88

    @pytest.mark.asyncio
    @patch("app.agents.image_classifier.Anthropic")
    async def test_classify_handles_markdown_json(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            '```json\n{"type": "reference_image", "confidence": 0.90, "description": "Tile sample"}\n```'
        )

        classification, _ = await classify_image("base64data")
        assert classification.image_type == "reference_image"

    @pytest.mark.asyncio
    @patch("app.agents.image_classifier.Anthropic")
    async def test_classify_invalid_json_defaults_to_other(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            "This is not JSON at all"
        )

        classification, _ = await classify_image("base64data")
        assert classification.image_type == "other"
        assert classification.confidence == 0.0

    @pytest.mark.asyncio
    @patch("app.agents.image_classifier.Anthropic")
    async def test_classify_unknown_type_defaults_to_other(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            json.dumps({"type": "invalid_type", "confidence": 0.5, "description": "test"})
        )

        classification, _ = await classify_image("base64data")
        assert classification.image_type == "other"


class TestVisualChangeAgent:
    @pytest.mark.asyncio
    @patch("app.agents.visual_change.Anthropic")
    async def test_extract_from_annotated_plan(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            json.dumps({
                "changes": [
                    {
                        "is_change_event": True,
                        "confidence": 0.85,
                        "description": "Wall moved 2ft south in living room",
                        "area": "Living Room",
                        "material_from": None,
                        "material_to": None,
                        "urgency": "normal",
                    }
                ]
            })
        )

        proposals, metadata = await extract_changes_from_image(
            image_base64="base64data",
            image_type="annotated_plan",
            project_name="Test Project",
        )

        assert len(proposals) == 1
        assert proposals[0].description == "Wall moved 2ft south in living room"
        assert proposals[0].area == "Living Room"
        assert metadata["image_type"] == "annotated_plan"

    @pytest.mark.asyncio
    @patch("app.agents.visual_change.Anthropic")
    async def test_extract_multiple_changes(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            json.dumps({
                "changes": [
                    {
                        "is_change_event": True,
                        "confidence": 0.90,
                        "description": "Flooring changed from hardwood to tile",
                        "area": "Kitchen",
                        "material_from": "hardwood",
                        "material_to": "porcelain tile",
                        "urgency": "normal",
                    },
                    {
                        "is_change_event": True,
                        "confidence": 0.75,
                        "description": "Additional window added to north wall",
                        "area": "Kitchen",
                        "material_from": None,
                        "material_to": None,
                        "urgency": "normal",
                    },
                ]
            })
        )

        proposals, _ = await extract_changes_from_image(
            image_base64="base64data",
            image_type="field_photo",
        )
        assert len(proposals) == 2
        assert proposals[0].material_from == "hardwood"
        assert proposals[0].material_to == "porcelain tile"

    @pytest.mark.asyncio
    async def test_skip_other_image_type(self):
        """Images classified as 'other' should be skipped without API call."""
        proposals, metadata = await extract_changes_from_image(
            image_base64="base64data",
            image_type="other",
        )
        assert len(proposals) == 0
        assert metadata.get("skipped") is True

    @pytest.mark.asyncio
    async def test_skip_document_image_type(self):
        """Images classified as 'document' should be skipped (handled by doc pipeline)."""
        proposals, metadata = await extract_changes_from_image(
            image_base64="base64data",
            image_type="document",
        )
        assert len(proposals) == 0
        assert metadata.get("skipped") is True

    @pytest.mark.asyncio
    @patch("app.agents.visual_change.Anthropic")
    async def test_no_changes_found(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            json.dumps({"changes": []})
        )

        proposals, _ = await extract_changes_from_image(
            image_base64="base64data",
            image_type="reference_image",
        )
        assert len(proposals) == 0

    @pytest.mark.asyncio
    @patch("app.agents.visual_change.Anthropic")
    async def test_filters_non_change_events(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            json.dumps({
                "changes": [
                    {
                        "is_change_event": False,
                        "confidence": 0.3,
                        "description": "Standard construction progress",
                    },
                    {
                        "is_change_event": True,
                        "confidence": 0.80,
                        "description": "Unexpected pipe relocation",
                        "area": "Basement",
                        "urgency": "urgent",
                    },
                ]
            })
        )

        proposals, _ = await extract_changes_from_image(
            image_base64="base64data",
            image_type="field_photo",
        )
        assert len(proposals) == 1
        assert proposals[0].urgency == "urgent"

    @pytest.mark.asyncio
    @patch("app.agents.visual_change.Anthropic")
    async def test_handles_json_parse_error(self, mock_anthropic_cls):
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_anthropic_response(
            "I cannot analyze this image properly."
        )

        proposals, metadata = await extract_changes_from_image(
            image_base64="base64data",
            image_type="annotated_plan",
        )
        assert len(proposals) == 0
        assert "error" in metadata
