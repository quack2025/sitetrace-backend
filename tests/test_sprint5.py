"""Tests for Sprint 5 — Integrations, Embeddings, Timeline."""
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")


# ── CF Transformer tests ──

from app.integrations.transformers.cf_transformer import (
    transform_to_cf_format,
    _map_category,
    _map_status,
)


class TestCFTransformer:
    def test_transform_basic(self):
        co = {
            "id": str(uuid4()),
            "order_number": "CO-2026-001",
            "description": "Kitchen flooring change",
            "status": "draft",
            "subtotal": 1000,
            "markup_percent": 15,
            "markup_amount": 150,
            "tax_percent": 8,
            "tax_amount": 92,
            "total": 1242,
            "currency": "USD",
            "projects": {
                "name": "Smith Residence",
                "client_name": "John Smith",
                "contractors": {"name": "ABC Builders"},
            },
        }
        items = [
            {
                "description": "Tile installation",
                "category": "labor",
                "quantity": 100,
                "unit": "sqft",
                "unit_cost": 5,
                "total_cost": 500,
                "notes": "",
            },
        ]

        result = transform_to_cf_format(co, items, "cf-proj-123")

        assert result["order_number"] == "CO-2026-001"
        assert result["project_id"] == "cf-proj-123"
        assert result["source"] == "sitetrace"
        assert result["client_name"] == "John Smith"
        assert len(result["items"]) == 1
        assert result["items"][0]["category"] == "LABOR"
        assert result["items"][0]["unit_price"] == 5.0

    def test_transform_without_items(self):
        co = {
            "id": str(uuid4()),
            "order_number": "CO-2026-002",
            "description": "Empty CO",
            "status": "signed",
            "subtotal": 0,
            "markup_percent": 0,
            "markup_amount": 0,
            "tax_percent": 0,
            "tax_amount": 0,
            "total": 0,
            "currency": "USD",
            "projects": {"name": "P", "client_name": "C", "contractors": {"name": "N"}},
        }

        result = transform_to_cf_format(co)
        assert result["items"] == []
        assert result["status"] == "APPROVED"
        assert "project_id" not in result  # No cf_project_id provided

    def test_map_category_all(self):
        assert _map_category("labor") == "LABOR"
        assert _map_category("material") == "MATERIAL"
        assert _map_category("equipment") == "EQUIPMENT"
        assert _map_category("subcontract") == "SUBCONTRACT"
        assert _map_category("other") == "OTHER"
        assert _map_category("unknown") == "OTHER"

    def test_map_status_all(self):
        assert _map_status("draft") == "PENDING"
        assert _map_status("sent_to_client") == "SUBMITTED"
        assert _map_status("signed") == "APPROVED"
        assert _map_status("unknown") == "PENDING"


# ── Embeddings tests ──

from app.agents.embeddings import cosine_similarity


class TestCosineSimlarity:
    def test_identical_vectors(self):
        vec = [1.0, 0.0, 0.0]
        assert abs(cosine_similarity(vec, vec) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert abs(cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(cosine_similarity(a, b) - (-1.0)) < 1e-6

    def test_similar_vectors(self):
        a = [1.0, 0.9, 0.1]
        b = [1.0, 0.8, 0.2]
        sim = cosine_similarity(a, b)
        assert sim > 0.95  # Very similar

    def test_empty_vectors(self):
        assert cosine_similarity([], []) == 0.0

    def test_mismatched_lengths(self):
        assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


# ── Outlook ingestor tests ──

from app.ingestors.outlook import OutlookIngestor


class TestOutlookIngestor:
    def test_strip_html_basic(self):
        html = "<p>Hello <b>World</b></p>"
        assert "Hello" in OutlookIngestor._strip_html(html)
        assert "World" in OutlookIngestor._strip_html(html)
        assert "<p>" not in OutlookIngestor._strip_html(html)

    def test_strip_html_script_tags(self):
        html = '<div>Before<script>alert("x")</script>After</div>'
        result = OutlookIngestor._strip_html(html)
        assert "alert" not in result
        assert "Before" in result
        assert "After" in result

    def test_strip_html_entities(self):
        html = "Hello &amp; World &lt;test&gt;"
        result = OutlookIngestor._strip_html(html)
        assert "Hello & World <test>" == result

    def test_strip_html_empty(self):
        assert OutlookIngestor._strip_html("") == ""

    def test_strip_html_plain_text(self):
        assert OutlookIngestor._strip_html("Just plain text") == "Just plain text"


# ── Timeline model tests ──

from app.routers.timeline import TimelineItem
from datetime import datetime, timezone


class TestTimelineItem:
    def test_create_timeline_item(self):
        item = TimelineItem(
            timestamp=datetime.now(timezone.utc),
            type="change_event",
            entity_id=str(uuid4()),
            title="Change detected",
            description="Kitchen flooring",
            metadata={"status": "proposed"},
        )
        assert item.type == "change_event"
        assert item.metadata["status"] == "proposed"

    def test_default_metadata(self):
        item = TimelineItem(
            timestamp=datetime.now(timezone.utc),
            type="notification",
            entity_id=str(uuid4()),
            title="Notification sent",
        )
        assert item.metadata == {}
        assert item.description == ""
