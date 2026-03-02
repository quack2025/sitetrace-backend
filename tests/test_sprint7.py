"""Tests for Sprint 7 — Document Center + Bulletins."""
import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4
from datetime import datetime, timezone

os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-jwt-tokens-minimum-64-chars-long-1234567890abcdef")
os.environ.setdefault("ANTHROPIC_API_KEY", "")


# ── Pydantic Models ──

class TestTeamMemberModels:
    def test_team_member_create(self):
        from app.models.team_member import TeamMemberCreate
        m = TeamMemberCreate(
            name="John Doe",
            email="john@example.com",
            role="superintendent",
        )
        assert m.name == "John Doe"
        assert m.receives_bulletins is True  # default

    def test_team_member_create_defaults(self):
        from app.models.team_member import TeamMemberCreate
        m = TeamMemberCreate(name="Jane", email="jane@test.com")
        assert m.role is None
        assert m.receives_bulletins is True
        assert m.phone is None

    def test_team_member_update_partial(self):
        from app.models.team_member import TeamMemberUpdate
        u = TeamMemberUpdate(role="foreman")
        dumped = u.model_dump(exclude_none=True)
        assert dumped == {"role": "foreman"}

    def test_team_member_response(self):
        from app.models.team_member import TeamMemberResponse
        r = TeamMemberResponse(
            id=uuid4(),
            project_id=uuid4(),
            name="Jane",
            email="jane@test.com",
            receives_bulletins=True,
        )
        assert r.role is None
        assert r.phone is None


class TestDocumentModels:
    def test_document_create(self):
        from app.models.document import DocumentCreate
        d = DocumentCreate(category="architectural_plans", name="Floor Plan Rev A")
        assert d.category == "architectural_plans"
        assert d.external_url is None

    def test_document_version_create(self):
        from app.models.document import DocumentVersionCreate
        v = DocumentVersionCreate(notes="Updated to match change order CO-2025-003")
        assert v.external_url is None
        assert v.notes == "Updated to match change order CO-2025-003"

    def test_document_health_response(self):
        from app.models.document import DocumentHealthResponse
        h = DocumentHealthResponse(
            total=10,
            current=7,
            superseded=2,
            draft=1,
            categories={"architectural_plans": 3, "electrical": 2, "finishes": 2},
        )
        assert h.total == 10
        assert len(h.categories) == 3

    def test_affected_document_create_defaults(self):
        from app.models.document import AffectedDocumentCreate
        a = AffectedDocumentCreate(document_id=uuid4())
        assert a.impact_type == "supersedes"
        assert a.notes is None


class TestBulletinModels:
    def test_bulletin_response(self):
        from app.models.bulletin import BulletinResponse
        b = BulletinResponse(
            id=uuid4(),
            project_id=uuid4(),
            bulletin_number="DB-2026-001",
            title="Kitchen Backsplash Material Change",
            summary_text="Changed from ceramic tile to porcelain.",
            affected_areas=[
                {"category": "finishes", "description": "Backsplash spec", "action": "Wait for Rev B"},
            ],
        )
        assert b.bulletin_number == "DB-2026-001"
        assert len(b.affected_areas) == 1
        assert b.pdf_url is None


# ── Email Templates ──

class TestDocumentBulletinTemplate:
    def test_render_document_bulletin(self):
        from app.notifications.email_templates import render_document_bulletin
        html = render_document_bulletin(
            recipient_name="Mike",
            project_name="Luxury Condo Tower",
            bulletin_number="DB-2026-002",
            title="HVAC Spec Update",
            summary_text="Changed HVAC system from Model X to Model Y.\nAll ductwork plans need revision.",
            affected_areas=[
                {
                    "category": "mechanical",
                    "description": "HVAC system specs",
                    "action": "DO NOT USE Rev C. Wait for Rev D.",
                },
            ],
            order_number="CO-2026-005",
            pdf_url="https://storage.example.com/bulletin.pdf",
        )
        assert "Document Bulletin DB-2026-002" in html
        assert "Mike" in html
        assert "Luxury Condo Tower" in html
        assert "HVAC Spec Update" in html
        assert "CO-2026-005" in html
        assert "Mechanical" in html  # category title-cased
        assert "DO NOT USE Rev C" in html
        assert "bulletin.pdf" in html
        assert "SiteTrace" in html

    def test_render_document_bulletin_no_pdf(self):
        from app.notifications.email_templates import render_document_bulletin
        html = render_document_bulletin(
            recipient_name="Sarah",
            project_name="Office Remodel",
            bulletin_number="DB-2026-001",
            title="Paint Change",
            summary_text="Changed paint color from white to eggshell.",
            affected_areas=[],
            order_number="CO-2026-001",
            pdf_url=None,
        )
        assert "Sarah" in html
        assert "View Full Bulletin PDF" not in html

    def test_render_document_bulletin_empty_areas(self):
        from app.notifications.email_templates import render_document_bulletin
        html = render_document_bulletin(
            recipient_name="Bob",
            project_name="House Build",
            bulletin_number="DB-2026-003",
            title="Minor Change",
            summary_text="Minor adjustment.",
            affected_areas=[],
            order_number="CO-2026-010",
        )
        # Should not contain the affected table
        assert "Category" not in html or "Action Required" not in html


# ── Bulletin Generator Agent ──

class TestBulletinGenerator:
    def test_load_prompt(self):
        from app.agents.bulletin_generator import _load_prompt
        prompt = _load_prompt("v1")
        assert "Document Bulletin" in prompt or "construction" in prompt
        assert "{project_name}" in prompt

    def test_format_changes_for_prompt(self):
        from app.agents.bulletin_generator import _format_changes_for_prompt
        changes = [
            {
                "description": "Backsplash tile changed",
                "area": "Kitchen",
                "material_from": "Ceramic 4x4",
                "material_to": "Porcelain 12x24",
                "confidence_score": 0.92,
            },
        ]
        co = {"order_number": "CO-2026-001", "description": "Kitchen changes", "total": 5500.00}
        text = _format_changes_for_prompt(changes, co)
        assert "CO-2026-001" in text
        assert "Backsplash tile changed" in text
        assert "Ceramic 4x4" in text
        assert "Porcelain 12x24" in text
        assert "Kitchen" in text

    def test_fallback_bulletin(self):
        from app.agents.bulletin_generator import _fallback_bulletin
        changes = [
            {
                "description": "Window size changed",
                "area": "Living Room",
                "material_from": "36x48 double-hung",
                "material_to": "48x60 casement",
            },
        ]
        co = {"order_number": "CO-2026-002"}
        result = _fallback_bulletin(changes, co)
        assert "title" in result
        assert "summary_text" in result
        assert "affected_areas" in result
        assert len(result["affected_areas"]) == 1
        assert result["affected_areas"][0]["category"] == "living_room"
        assert "CO-2026-002" in result["title"]

    @pytest.mark.asyncio
    async def test_generate_bulletin_content_no_api_key(self):
        from app.agents.bulletin_generator import generate_bulletin_content
        with patch("app.agents.bulletin_generator.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(anthropic_api_key="")
            content, meta = await generate_bulletin_content(
                change_events=[{"description": "Test change", "area": "General"}],
                change_order={"order_number": "CO-001"},
                project={"name": "Test Project"},
            )
        assert meta["model_used"] == "fallback"
        assert "title" in content


# ── Team Members Router ──

class TestTeamMembersRouter:
    @pytest.mark.asyncio
    @patch("app.routers.team_members.get_supabase")
    @patch("app.routers.team_members._verify_project_ownership")
    async def test_add_team_member(self, mock_verify, mock_db_fn):
        from app.routers.team_members import add_team_member
        from app.models.team_member import TeamMemberCreate

        project_id = uuid4()
        mock_verify.return_value = {"id": str(project_id), "name": "Test"}
        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{
                "id": str(uuid4()),
                "project_id": str(project_id),
                "name": "John",
                "email": "john@test.com",
                "role": "superintendent",
                "receives_bulletins": True,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }]
        )

        body = TeamMemberCreate(name="John", email="john@test.com", role="superintendent")
        result = await add_team_member(project_id, body, {"id": "contractor-1"})
        assert result["name"] == "John"
        mock_db.table.assert_called_with("project_team_members")


# ── Documents Router ──

class TestDocumentsRouter:
    @pytest.mark.asyncio
    @patch("app.routers.documents.get_supabase")
    @patch("app.routers.documents._verify_project_ownership")
    async def test_create_document(self, mock_verify, mock_db_fn):
        from app.routers.documents import create_document
        from app.models.document import DocumentCreate

        project_id = uuid4()
        mock_verify.return_value = {"id": str(project_id), "name": "Test"}
        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{
                "id": str(uuid4()),
                "project_id": str(project_id),
                "category": "architectural_plans",
                "name": "Floor Plan",
                "version": 1,
                "status": "current",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }]
        )

        body = DocumentCreate(category="architectural_plans", name="Floor Plan")
        result = await create_document(project_id, body, {"id": "contractor-1"})
        assert result["category"] == "architectural_plans"
        assert result["version"] == 1

    @pytest.mark.asyncio
    @patch("app.routers.documents.get_supabase")
    @patch("app.routers.documents._verify_project_ownership")
    async def test_document_health(self, mock_verify, mock_db_fn):
        from app.routers.documents import get_document_health

        project_id = uuid4()
        mock_verify.return_value = {"id": str(project_id), "name": "Test"}
        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[
                {"status": "current", "category": "architectural_plans"},
                {"status": "current", "category": "architectural_plans"},
                {"status": "current", "category": "electrical"},
                {"status": "superseded", "category": "architectural_plans"},
                {"status": "draft", "category": "finishes"},
            ]
        )

        result = await get_document_health(project_id, {"id": "contractor-1"})
        assert result.total == 5
        assert result.current == 3
        assert result.superseded == 1
        assert result.draft == 1
        assert result.categories["architectural_plans"] == 2
        assert result.categories["electrical"] == 1


# ── Timeline Integration ──

class TestTimelineBulletinEvents:
    @pytest.mark.asyncio
    @patch("app.routers.timeline.get_supabase")
    @patch("app.routers.timeline._verify_project_ownership")
    async def test_timeline_includes_bulletin_events(self, mock_verify, mock_db_fn):
        from app.routers.timeline import get_project_timeline

        project_id = uuid4()
        mock_verify.return_value = {"id": str(project_id), "name": "Test Project"}

        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db

        # All sub-queries return empty except bulletins and documents
        empty_result = MagicMock(data=[])

        bulletin_id = str(uuid4())
        bulletin_result = MagicMock(data=[{
            "id": bulletin_id,
            "bulletin_number": "DB-2026-001",
            "title": "Kitchen Changes",
            "change_order_id": str(uuid4()),
            "affected_areas": [{"category": "finishes"}],
            "created_at": "2026-03-01T10:00:00Z",
        }])

        doc_id = str(uuid4())
        doc_result = MagicMock(data=[{
            "id": doc_id,
            "name": "Floor Plan",
            "category": "architectural_plans",
            "version": 2,
            "status": "current",
            "superseded_at": None,
            "created_at": "2026-03-01T09:00:00Z",
        }])

        # Set up chain: the table name determines the result
        def table_side_effect(name):
            mock_chain = MagicMock()
            if name == "document_bulletins":
                mock_chain.select.return_value.eq.return_value.execute.return_value = bulletin_result
            elif name == "project_documents":
                mock_chain.select.return_value.eq.return_value.execute.return_value = doc_result
            elif name == "state_transitions":
                mock_chain.select.return_value.in_.return_value.execute.return_value = empty_result
            else:
                mock_chain.select.return_value.eq.return_value.execute.return_value = empty_result
            return mock_chain

        mock_db.table = MagicMock(side_effect=table_side_effect)

        result = await get_project_timeline(project_id, 100, 0, {"id": "contractor-1"})

        item_types = [item.type for item in result.items]
        assert "bulletin" in item_types
        assert "document" in item_types  # version > 1 generates a document event

        bulletin_item = next(i for i in result.items if i.type == "bulletin")
        assert "DB-2026-001" in bulletin_item.title

        doc_item = next(i for i in result.items if i.type == "document")
        assert "Floor Plan" in doc_item.title
        assert "v2" in doc_item.title


# ── Bulletin PDF Generator ──

class TestBulletinPdfGenerator:
    def test_html_template_exists(self):
        from pathlib import Path
        template = Path("C:/Users/jorge/sitetrace-backend/app/pdf/templates/document_bulletin.html")
        assert template.exists()

    def test_template_has_required_placeholders(self):
        from pathlib import Path
        content = Path("C:/Users/jorge/sitetrace-backend/app/pdf/templates/document_bulletin.html").read_text()
        assert "bulletin_number" in content
        assert "project_name" in content
        assert "affected_areas" in content


# ── Bulletins Router ──

class TestBulletinsRouter:
    @pytest.mark.asyncio
    @patch("app.routers.bulletins.get_supabase")
    @patch("app.routers.bulletins._verify_project_ownership")
    async def test_list_bulletins(self, mock_verify, mock_db_fn):
        from app.routers.bulletins import list_bulletins

        project_id = uuid4()
        mock_verify.return_value = {"id": str(project_id), "name": "Test"}
        mock_db = MagicMock()
        mock_db_fn.return_value = mock_db
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[{
                "id": str(uuid4()),
                "project_id": str(project_id),
                "change_order_id": str(uuid4()),
                "bulletin_number": "DB-2026-001",
                "title": "Changes Approved",
                "summary_text": "Summary",
                "affected_areas": [],
                "distribution_list": [],
                "pdf_url": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }]
        )

        result = await list_bulletins(project_id, {"id": "contractor-1"})
        assert len(result) == 1
