"""Tests for configuration loading."""
import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.config import get_settings


class TestConfig:
    def test_defaults(self):
        settings = get_settings()
        assert settings.confidence_threshold == 0.70
        assert settings.max_processing_time_seconds == 90
        assert settings.poll_interval_seconds == 300
        assert settings.jwt_algorithm == "HS256"
        assert settings.action_token_expire_hours == 48
        assert settings.max_attachment_size_mb == 25

    def test_supabase_configured(self):
        settings = get_settings()
        assert settings.supabase_url
        assert settings.supabase_service_key

    def test_jwt_secret_set(self):
        settings = get_settings()
        assert len(settings.jwt_secret) >= 20
