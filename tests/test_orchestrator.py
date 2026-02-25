"""Tests for the AI orchestrator pipeline."""
import os
import pytest

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.agents.orchestrator import _deduplicate_proposals
from app.models.change_event import ChangeEventProposal


def _make_proposal(description: str, confidence: float = 0.9) -> tuple:
    return (
        ChangeEventProposal(
            is_change_event=True,
            confidence=confidence,
            description=description,
        ),
        {"prompt_version": "text_detection:v1", "model_used": "test", "tokens_used": 100, "processing_time_ms": 50},
    )


class TestDeduplication:
    def test_no_duplicates(self):
        proposals = [
            _make_proposal("Change floor tile to porcelain in bathroom"),
            _make_proposal("Add extra electrical outlet in kitchen"),
        ]
        result = _deduplicate_proposals(proposals)
        assert len(result) == 2

    def test_exact_duplicate_removed(self):
        proposals = [
            _make_proposal("Change floor tile to porcelain in bathroom"),
            _make_proposal("Change floor tile to porcelain in bathroom"),
        ]
        result = _deduplicate_proposals(proposals)
        assert len(result) == 1

    def test_near_duplicate_removed(self):
        proposals = [
            _make_proposal("Change floor tile to porcelain in bathroom"),
            _make_proposal("Change floor tile to porcelain in the bathroom"),
        ]
        result = _deduplicate_proposals(proposals)
        assert len(result) == 1

    def test_different_areas_kept(self):
        proposals = [
            _make_proposal("Change floor tile to porcelain in bathroom"),
            _make_proposal("Change floor tile to porcelain in kitchen"),
        ]
        result = _deduplicate_proposals(proposals)
        assert len(result) == 2

    def test_empty_list(self):
        result = _deduplicate_proposals([])
        assert len(result) == 0

    def test_single_proposal(self):
        proposals = [_make_proposal("Add window in bedroom")]
        result = _deduplicate_proposals(proposals)
        assert len(result) == 1

    def test_three_similar_keep_one(self):
        proposals = [
            _make_proposal("instalar porcelanato 60x60 en baño principal"),
            _make_proposal("instalar porcelanato 60x60 en baño principal ahora"),
            _make_proposal("instalar porcelanato 60x60 en el baño principal"),
        ]
        result = _deduplicate_proposals(proposals)
        assert len(result) == 1
