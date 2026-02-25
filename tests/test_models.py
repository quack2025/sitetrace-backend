"""Tests for Pydantic models validation."""
import os
import pytest
from decimal import Decimal
from uuid import uuid4

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.models.project import ProjectCreate, ProjectUpdate, ProjectResponse
from app.models.change_event import ChangeEventProposal, ChangeEventCreate, ChangeEventUpdate
from app.models.change_order import ChangeOrderItemCreate, ChangeOrderResponse
from app.models.ingest_event import IngestEventCreate


class TestProjectModels:
    def test_project_create_minimal(self):
        p = ProjectCreate(name="Test Project", client_name="John", client_email="john@test.com")
        assert p.name == "Test Project"
        assert p.currency == "USD"
        assert p.scope_summary is None

    def test_project_create_full(self):
        p = ProjectCreate(
            name="Luxury Condo Remodel",
            address="123 Main St",
            client_name="Jane Doe",
            client_email="jane@example.com",
            project_type="remodel",
            scope_summary="Full kitchen and bathroom remodel with marble counters",
            key_materials=[{"type": "marble", "area": "kitchen"}],
            original_budget=Decimal("150000.00"),
            currency="USD",
            gmail_label="condo-remodel",
        )
        assert p.project_type == "remodel"
        assert p.scope_summary.startswith("Full kitchen")
        assert len(p.key_materials) == 1

    def test_project_update_partial(self):
        p = ProjectUpdate(scope_summary="Updated scope")
        assert p.scope_summary == "Updated scope"
        assert p.name is None


class TestChangeEventModels:
    def test_proposal_from_ai(self):
        p = ChangeEventProposal(
            is_change_event=True,
            confidence=0.92,
            description="Change floor tile from ceramic to porcelain in bathroom",
            area="Master bathroom",
            material_from="Ceramic 30x30",
            material_to="Porcelain 60x60",
            requester_name="Client",
            urgency="normal",
        )
        assert p.confidence == 0.92
        assert p.is_change_event is True

    def test_proposal_no_change(self):
        p = ChangeEventProposal(is_change_event=False, confidence=1.0)
        assert p.description == ""

    def test_manual_create(self):
        c = ChangeEventCreate(
            description="Add electrical outlet in garage",
            area="Garage",
        )
        assert c.description == "Add electrical outlet in garage"

    def test_update_only_description(self):
        u = ChangeEventUpdate(description="Updated description")
        assert u.area is None


class TestChangeOrderModels:
    def test_item_create_with_cost(self):
        item = ChangeOrderItemCreate(
            description="Porcelain tile 60x60",
            category="material",
            quantity=Decimal("25"),
            unit="sqm",
            unit_cost=Decimal("45.00"),
        )
        assert item.quantity == Decimal("25")
        assert item.unit_cost == Decimal("45.00")

    def test_item_defaults(self):
        item = ChangeOrderItemCreate(description="General labor")
        assert item.quantity == Decimal("1")
        assert item.unit == "unit"
        assert item.unit_cost == Decimal("0")


class TestIngestEventModels:
    def test_gmail_ingest_event(self):
        ie = IngestEventCreate(
            channel="gmail",
            raw_payload={"subject": "Re: Kitchen changes", "body": "Please use marble instead"},
            sender_email="client@test.com",
            sender_name="Client Name",
            subject="Re: Kitchen changes",
            external_message_id="gmail-abc123",
        )
        assert ie.channel == "gmail"
        assert ie.external_message_id == "gmail-abc123"

    def test_manual_ingest_event(self):
        ie = IngestEventCreate(
            channel="manual",
            raw_payload={"description": "Phone call change request"},
        )
        assert ie.channel == "manual"
        assert ie.external_message_id is None
