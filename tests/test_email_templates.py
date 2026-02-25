"""Tests for email template rendering."""
import os

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.notifications.email_templates import (
    render_change_proposed,
    render_change_confirmed,
    render_client_sign_request,
    render_change_closed,
)


class TestChangeProposedTemplate:
    def test_renders_html(self):
        html = render_change_proposed(
            contractor_name="John Smith",
            project_name="Luxury Condo",
            description="Change floor tile from ceramic to porcelain",
            area="Master bathroom",
            confidence=0.92,
            confirm_url="https://api.sitetrace.ai/confirm?token=abc",
            reject_url="https://api.sitetrace.ai/reject?token=def",
            edit_url="https://app.sitetrace.ai/edit/123",
        )
        assert "John Smith" in html
        assert "Luxury Condo" in html
        assert "porcelain" in html
        assert "Master bathroom" in html
        assert "92%" in html
        assert "Confirm" in html
        assert "Reject" in html
        assert "SiteTrace" in html

    def test_high_confidence_badge(self):
        html = render_change_proposed(
            contractor_name="Test",
            project_name="Test",
            description="Change",
            area=None,
            confidence=0.92,
            confirm_url="",
            reject_url="",
            edit_url="",
        )
        assert "High Confidence" in html

    def test_low_confidence_badge(self):
        html = render_change_proposed(
            contractor_name="Test",
            project_name="Test",
            description="Change",
            area=None,
            confidence=0.65,
            confirm_url="",
            reject_url="",
            edit_url="",
        )
        assert "Review Recommended" in html

    def test_no_area(self):
        html = render_change_proposed(
            contractor_name="Test",
            project_name="Test",
            description="Change",
            area=None,
            confidence=0.85,
            confirm_url="",
            reject_url="",
            edit_url="",
        )
        # Should not have "Area" card when area is None
        assert html.count("Area") == 0 or "Area" not in html.split("card-label")[1] if "card-label" in html else True


class TestChangeConfirmedTemplate:
    def test_renders_with_co_url(self):
        html = render_change_confirmed(
            contractor_name="John",
            project_name="Condo Reno",
            description="New tile in bathroom",
            order_number="CO-2026-001",
            co_url="https://app.sitetrace.ai/co/123",
        )
        assert "CO-2026-001" in html
        assert "View Change Order" in html
        assert "Next steps" in html


class TestClientSignTemplate:
    def test_renders_with_total(self):
        html = render_client_sign_request(
            client_name="Jane Client",
            contractor_name="Bob Builder",
            project_name="Kitchen Remodel",
            order_number="CO-2026-005",
            description="Marble countertops upgrade",
            total="4,500.00",
            currency="USD",
            sign_url="https://api.sitetrace.ai/sign?token=xyz",
            pdf_url="https://storage.sitetrace.ai/co.pdf",
        )
        assert "Jane Client" in html
        assert "Bob Builder" in html
        assert "USD 4,500.00" in html
        assert "Approve" in html
        assert "CO-2026-005" in html


class TestChangeClosedTemplate:
    def test_renders_signed_info(self):
        html = render_change_closed(
            contractor_name="Bob",
            project_name="Project X",
            order_number="CO-2026-010",
            client_name="Alice",
            signed_at="2026-02-25 15:30:00",
            total="12,000.00",
            currency="USD",
            co_url="https://app.sitetrace.ai/co/456",
        )
        assert "Alice" in html
        assert "CO-2026-010" in html
        assert "USD 12,000.00" in html
        assert "closed" in html.lower()
