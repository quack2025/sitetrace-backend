"""Tests for PDF generation pipeline."""
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.pdf.change_order_generator import _format_decimal, _format_date


class TestFormatHelpers:
    def test_format_decimal_float(self):
        assert _format_decimal(1234.5) == "1,234.50"

    def test_format_decimal_int(self):
        assert _format_decimal(1000) == "1,000.00"

    def test_format_decimal_string(self):
        assert _format_decimal("99.9") == "99.90"

    def test_format_decimal_zero(self):
        assert _format_decimal(0) == "0.00"

    def test_format_decimal_none(self):
        assert _format_decimal(None) == "0.00"

    def test_format_date_iso_string(self):
        result = _format_date("2026-02-25T14:30:00+00:00")
        assert "February" in result
        assert "25" in result
        assert "2026" in result

    def test_format_date_none(self):
        assert _format_date(None) == "—"

    def test_format_date_empty_string(self):
        assert _format_date("") == "—"

    def test_format_date_invalid(self):
        result = _format_date("not-a-date")
        assert isinstance(result, str)


class TestPdfTemplate:
    """Test that the Jinja2 template renders without errors."""

    def test_template_renders_minimal(self):
        from jinja2 import Environment, FileSystemLoader
        from pathlib import Path

        template_dir = Path(__file__).parent.parent / "app" / "pdf" / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("change_order.html")

        html = template.render(
            order_number="CO-2026-001",
            generated_date="February 25, 2026",
            project_name="Test Project",
            client_name="Test Client",
            contractor_name="Test Contractor",
            project_type="Residential",
            detection_date="February 20, 2026",
            confirmation_date="February 22, 2026",
            description="Change flooring from hardwood to tile",
            area="Kitchen",
            material_from="Hardwood",
            material_to="Porcelain Tile",
            items=[
                {
                    "description": "Remove existing hardwood",
                    "category": "labor",
                    "quantity": "1",
                    "unit": "lot",
                    "unit_cost": "500.00",
                    "total_cost": "500.00",
                },
                {
                    "description": "Porcelain tile material",
                    "category": "material",
                    "quantity": "100",
                    "unit": "sqft",
                    "unit_cost": "8.50",
                    "total_cost": "850.00",
                },
            ],
            currency="USD",
            subtotal="1,350.00",
            markup_percent=15.0,
            markup_amount="202.50",
            tax_percent=8.0,
            tax_amount="124.20",
            total="1,676.70",
            evidence_images=[],
            original_message="Client requested tile instead of hardwood for the kitchen area.",
            message_timestamp="February 20, 2026 at 09:15 AM",
            signed_at=None,
            signed_by_email="",
            signed_from_ip="",
            doc_version="v1.0",
        )

        assert "CO-2026-001" in html
        assert "Test Project" in html
        assert "Change flooring" in html
        assert "Remove existing hardwood" in html
        assert "Porcelain tile material" in html
        assert "1,350.00" in html
        assert "1,676.70" in html

    def test_template_renders_with_signature(self):
        from jinja2 import Environment, FileSystemLoader
        from pathlib import Path

        template_dir = Path(__file__).parent.parent / "app" / "pdf" / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("change_order.html")

        html = template.render(
            order_number="CO-2026-002",
            generated_date="February 25, 2026",
            project_name="Signed Project",
            client_name="John Client",
            contractor_name="Jane Contractor",
            project_type="Commercial",
            detection_date="February 20, 2026",
            confirmation_date="February 22, 2026",
            description="Signed change order",
            area="",
            material_from="",
            material_to="",
            items=[],
            currency="USD",
            subtotal="0.00",
            markup_percent=0,
            markup_amount="0.00",
            tax_percent=0,
            tax_amount="0.00",
            total="0.00",
            evidence_images=[],
            original_message="",
            message_timestamp="",
            signed_at="February 25, 2026 at 02:30 PM",
            signed_by_email="john@client.com",
            signed_from_ip="192.168.1.1",
            doc_version="v1.0",
        )

        assert "Digitally Approved" in html
        assert "john@client.com" in html
        assert "192.168.1.1" in html

    def test_template_renders_no_materials(self):
        """Template should not show material section when no materials specified."""
        from jinja2 import Environment, FileSystemLoader
        from pathlib import Path

        template_dir = Path(__file__).parent.parent / "app" / "pdf" / "templates"
        env = Environment(loader=FileSystemLoader(str(template_dir)))
        template = env.get_template("change_order.html")

        html = template.render(
            order_number="CO-2026-003",
            generated_date="February 25, 2026",
            project_name="No Materials",
            client_name="Client",
            contractor_name="Contractor",
            project_type="Residential",
            detection_date="",
            confirmation_date="",
            description="General change",
            area="",
            material_from="",
            material_to="",
            items=[],
            currency="USD",
            subtotal="0.00",
            markup_percent=0,
            markup_amount="0.00",
            tax_percent=0,
            tax_amount="0.00",
            total="0.00",
            evidence_images=[],
            original_message="",
            message_timestamp="",
            signed_at=None,
            signed_by_email="",
            signed_from_ip="",
            doc_version="v1.0",
        )

        # Material Change section should not appear
        assert "Material Change" not in html


class TestStoragePaths:
    def test_evidence_path(self):
        from app.processors.storage import evidence_path
        path = evidence_path(
            project_id=uuid4(),
            change_event_id=uuid4(),
            filename="photo.jpg",
            processed=False,
        )
        assert "original_photo.jpg" in path

    def test_evidence_path_processed(self):
        from app.processors.storage import evidence_path
        path = evidence_path(
            project_id=uuid4(),
            change_event_id=uuid4(),
            filename="photo.jpg",
            processed=True,
        )
        assert "processed_photo.jpg" in path

    def test_change_order_path(self):
        from app.processors.storage import change_order_path
        pid = uuid4()
        path = change_order_path(project_id=pid, order_number="CO-2026-001")
        assert str(pid) in path
        assert "CO-2026-001.pdf" in path
