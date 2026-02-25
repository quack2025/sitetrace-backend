"""Tests for JWT action token generation and verification."""
import os
import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4

# Set required env vars before importing app modules
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.notifications.token_service import generate_action_token


class TestGenerateActionToken:
    def test_generates_confirm_token(self):
        ce_id = uuid4()
        token = generate_action_token(change_event_id=ce_id, action="confirm")
        assert isinstance(token, str)
        assert len(token) > 50  # JWT tokens are long

    def test_generates_reject_token(self):
        ce_id = uuid4()
        token = generate_action_token(change_event_id=ce_id, action="reject")
        assert isinstance(token, str)

    def test_generates_sign_token_with_client_email(self):
        co_id = uuid4()
        token = generate_action_token(
            change_order_id=co_id,
            action="sign",
            client_email="client@example.com",
        )
        assert isinstance(token, str)

    def test_different_actions_produce_different_tokens(self):
        ce_id = uuid4()
        t1 = generate_action_token(change_event_id=ce_id, action="confirm")
        t2 = generate_action_token(change_event_id=ce_id, action="reject")
        assert t1 != t2

    def test_token_is_decodable(self):
        import jwt
        ce_id = uuid4()
        token = generate_action_token(change_event_id=ce_id, action="confirm")
        payload = jwt.decode(token, "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef", algorithms=["HS256"])
        assert payload["action"] == "confirm"
        assert payload["change_event_id"] == str(ce_id)
        assert "exp" in payload
        assert "iat" in payload

    def test_custom_expiry(self):
        import jwt
        ce_id = uuid4()
        token = generate_action_token(
            change_event_id=ce_id, action="confirm", expires_hours=1
        )
        payload = jwt.decode(token, "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef", algorithms=["HS256"])
        # Token should expire within ~1 hour
        from datetime import datetime, timezone
        exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
        iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        diff = (exp - iat).total_seconds()
        assert 3500 < diff < 3700  # ~1 hour


class TestVerifyActionToken:
    @patch("app.notifications.token_service.get_supabase")
    def test_verify_valid_token(self, mock_db):
        # Mock: token not found in notifications (not used yet)
        mock_result = MagicMock()
        mock_result.data = None
        mock_db.return_value.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = mock_result

        from app.notifications.token_service import verify_action_token
        ce_id = uuid4()
        token = generate_action_token(change_event_id=ce_id, action="confirm")
        payload = verify_action_token(token)
        assert payload["action"] == "confirm"
        assert payload["change_event_id"] == str(ce_id)

    @patch("app.notifications.token_service.get_supabase")
    def test_verify_used_token_raises_410(self, mock_db):
        # Mock: token found and already used
        mock_result = MagicMock()
        mock_result.data = {"action_token_used_at": "2026-01-01T00:00:00"}
        mock_db.return_value.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = mock_result

        from fastapi import HTTPException
        from app.notifications.token_service import verify_action_token

        ce_id = uuid4()
        token = generate_action_token(change_event_id=ce_id, action="confirm")
        with pytest.raises(HTTPException) as exc_info:
            verify_action_token(token)
        assert exc_info.value.status_code == 410

    @patch("app.notifications.token_service.get_supabase")
    def test_verify_expired_token_raises_401(self, mock_db):
        mock_result = MagicMock()
        mock_result.data = None
        mock_db.return_value.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = mock_result

        from fastapi import HTTPException
        from app.notifications.token_service import verify_action_token

        # Create an already-expired token
        ce_id = uuid4()
        token = generate_action_token(
            change_event_id=ce_id, action="confirm", expires_hours=0
        )
        # Token with 0 hours = already expired (or about to)
        import time
        time.sleep(1)

        with pytest.raises(HTTPException) as exc_info:
            verify_action_token(token)
        assert exc_info.value.status_code == 401
