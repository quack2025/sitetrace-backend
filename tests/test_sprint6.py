"""Tests for Sprint 6 — Rate limiting, billing, monitoring."""
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")


# ── Rate Limiter tests ──

from app.middleware.rate_limiter import RATE_LIMITED_PATHS, MAX_REQUESTS, WINDOW_SECONDS


class TestRateLimiterConfig:
    def test_rate_limited_paths_exist(self):
        assert "/sign" in RATE_LIMITED_PATHS
        assert "/confirm" in RATE_LIMITED_PATHS
        assert "/reject" in RATE_LIMITED_PATHS
        assert "/send" in RATE_LIMITED_PATHS
        assert "/subscribe" in RATE_LIMITED_PATHS

    def test_rate_limit_values(self):
        assert MAX_REQUESTS == 10
        assert WINDOW_SECONDS == 60


# ── Subscription Guard tests ──

from app.middleware.subscription_guard import PLAN_LIMITS


class TestPlanLimits:
    def test_starter_has_limit(self):
        assert PLAN_LIMITS["starter"] == 3

    def test_pro_is_unlimited(self):
        assert PLAN_LIMITS["pro"] is None


# ── Billing Plans tests ──

from app.routers.billing import PLANS


class TestBillingPlans:
    def test_starter_plan(self):
        assert "starter" in PLANS
        assert PLANS["starter"]["price_monthly"] == 200
        assert PLANS["starter"]["max_active_projects"] == 3

    def test_pro_plan(self):
        assert "pro" in PLANS
        assert PLANS["pro"]["price_monthly"] == 300
        assert PLANS["pro"]["max_active_projects"] is None


# ── Webhook Handler tests ──

class TestStripeWebhook:
    @pytest.mark.asyncio
    @patch("app.routers.webhooks.get_supabase")
    async def test_subscription_created(self, mock_db_fn):
        from app.routers.webhooks import stripe_webhook

        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        request = MagicMock()
        request.json = AsyncMock(return_value={
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "customer": "cus_test123",
                    "id": "sub_test456",
                    "status": "active",
                    "current_period_end": 1740000000,
                    "metadata": {"plan": "starter"},
                },
            },
        })

        result = await stripe_webhook(request)
        assert result["received"] is True
        mock_db.table.assert_called_with("contractor_subscriptions")

    @pytest.mark.asyncio
    @patch("app.routers.webhooks.get_supabase")
    async def test_subscription_deleted(self, mock_db_fn):
        from app.routers.webhooks import stripe_webhook

        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        request = MagicMock()
        request.json = AsyncMock(return_value={
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "customer": "cus_test123",
                },
            },
        })

        result = await stripe_webhook(request)
        assert result["received"] is True

    @pytest.mark.asyncio
    @patch("app.routers.webhooks.get_supabase")
    async def test_payment_failed(self, mock_db_fn):
        from app.routers.webhooks import stripe_webhook

        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        request = MagicMock()
        request.json = AsyncMock(return_value={
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "customer": "cus_test123",
                },
            },
        })

        result = await stripe_webhook(request)
        assert result["received"] is True

    @pytest.mark.asyncio
    async def test_unknown_event_type(self):
        from app.routers.webhooks import stripe_webhook

        request = MagicMock()
        request.json = AsyncMock(return_value={
            "type": "unknown.event",
            "data": {"object": {}},
        })

        with patch("app.routers.webhooks.get_supabase"):
            result = await stripe_webhook(request)
            assert result["received"] is True


# ── Config tests ──

class TestConfigStripe:
    def test_stripe_defaults(self):
        from app.config import Settings
        # Settings should have stripe fields with defaults
        s = Settings(
            supabase_url="https://test.supabase.co",
            supabase_service_key="test",
            supabase_anon_key="test",
            anthropic_api_key="test",
            jwt_secret="test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef",
        )
        assert s.stripe_secret_key == ""
        assert s.stripe_webhook_secret == ""
        assert s.stripe_prices == {"starter": "", "pro": ""}
