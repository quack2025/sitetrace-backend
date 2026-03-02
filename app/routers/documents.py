from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from uuid import UUID
from datetime import datetime, timezone
from loguru import logger
from app.auth import get_current_contractor
from app.database import get_supabase
from app.models.document import (
    DocumentCreate,
    DocumentUpdate,
    DocumentVersionCreate,
    DocumentResponse,
    DocumentHealthResponse,
    AffectedDocumentCreate,
    AffectedDocumentResponse,
)
from app.routers.projects import _verify_project_ownership

router = APIRouter(prefix="/api/v1", tags=["documents"])


# ── Document CRUD ──

@router.post(
    "/projects/{project_id}/documents",
    response_model=DocumentResponse,
    status_code=201,
)
async def create_document(
    project_id: UUID,
    body: DocumentCreate,
    contractor: dict = Depends(get_current_contractor),
):
    """Register a project document (metadata + optional external URL)."""
    _verify_project_ownership(project_id, contractor["id"])
    db = get_supabase()

    data = body.model_dump(exclude_none=True)
    data["project_id"] = str(project_id)
    data["uploaded_by"] = contractor["id"]

    result = db.table("project_documents").insert(data).execute()
    return result.data[0]


@router.post(
    "/projects/{project_id}/documents/upload",
    response_model=DocumentResponse,
    status_code=201,
)
async def upload_document(
    project_id: UUID,
    file: UploadFile = File(...),
    category: str = Form(...),
    name: str = Form(...),
    notes: str = Form(None),
    contractor: dict = Depends(get_current_contractor),
):
    """Upload a document file to Supabase Storage."""
    _verify_project_ownership(project_id, contractor["id"])
    db = get_supabase()

    content = await file.read()
    storage_path = f"{project_id}/{category}/{file.filename}"

    # Upload to Supabase Storage
    db.storage.from_("project-documents").upload(
        path=storage_path,
        file=content,
        file_options={"content-type": file.content_type or "application/octet-stream"},
    )

    data = {
        "project_id": str(project_id),
        "category": category,
        "name": name,
        "storage_path": storage_path,
        "mime_type": file.content_type,
        "file_size_bytes": len(content),
        "uploaded_by": contractor["id"],
        "notes": notes,
    }
    result = db.table("project_documents").insert(data).execute()
    logger.info(f"Uploaded document {name} to {storage_path}")
    return result.data[0]


@router.get(
    "/projects/{project_id}/documents",
    response_model=list[DocumentResponse],
)
async def list_documents(
    project_id: UUID,
    status: str | None = None,
    category: str | None = None,
    contractor: dict = Depends(get_current_contractor),
):
    _verify_project_ownership(project_id, contractor["id"])
    db = get_supabase()

    query = (
        db.table("project_documents")
        .select("*")
        .eq("project_id", str(project_id))
    )
    if status:
        query = query.eq("status", status)
    if category:
        query = query.eq("category", category)

    result = query.order("category").order("name").order("version", desc=True).execute()
    return result.data


@router.put("/documents/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: UUID,
    body: DocumentUpdate,
    contractor: dict = Depends(get_current_contractor),
):
    db = get_supabase()
    doc = _verify_document_ownership(db, document_id, contractor["id"])

    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = (
        db.table("project_documents")
        .update(data)
        .eq("id", str(document_id))
        .execute()
    )
    return result.data[0]


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    db = get_supabase()
    _verify_document_ownership(db, document_id, contractor["id"])
    db.table("project_documents").delete().eq("id", str(document_id)).execute()


# ── Versioning ──

@router.post(
    "/documents/{document_id}/new-version",
    response_model=DocumentResponse,
    status_code=201,
)
async def create_new_version(
    document_id: UUID,
    body: DocumentVersionCreate,
    contractor: dict = Depends(get_current_contractor),
):
    """Create a new version of a document. Automatically supersedes the previous version."""
    db = get_supabase()
    old_doc = _verify_document_ownership(db, document_id, contractor["id"])

    if old_doc["status"] != "current":
        raise HTTPException(
            status_code=400,
            detail="Can only create new versions of current documents",
        )

    # Create new version
    new_data = {
        "project_id": old_doc["project_id"],
        "category": old_doc["category"],
        "name": old_doc["name"],
        "version": old_doc["version"] + 1,
        "status": "current",
        "external_url": body.external_url or old_doc.get("external_url"),
        "mime_type": body.mime_type or old_doc.get("mime_type"),
        "uploaded_by": contractor["id"],
        "notes": body.notes,
    }
    new_result = db.table("project_documents").insert(new_data).execute()
    new_doc = new_result.data[0]

    # Supersede old version
    now = datetime.now(timezone.utc).isoformat()
    db.table("project_documents").update({
        "status": "superseded",
        "superseded_by": new_doc["id"],
        "superseded_at": now,
    }).eq("id", str(document_id)).execute()

    logger.info(
        f"Document {old_doc['name']} upgraded v{old_doc['version']} → v{new_doc['version']}"
    )
    return new_doc


# ── Document Health ──

@router.get(
    "/projects/{project_id}/document-health",
    response_model=DocumentHealthResponse,
)
async def get_document_health(
    project_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    """Summary of document statuses for the project dashboard."""
    _verify_project_ownership(project_id, contractor["id"])
    db = get_supabase()

    docs = (
        db.table("project_documents")
        .select("status, category")
        .eq("project_id", str(project_id))
        .execute()
    ).data

    counts = {"current": 0, "superseded": 0, "draft": 0}
    categories: dict[str, int] = {}
    for doc in docs:
        counts[doc["status"]] = counts.get(doc["status"], 0) + 1
        if doc["status"] == "current":
            categories[doc["category"]] = categories.get(doc["category"], 0) + 1

    return DocumentHealthResponse(
        total=len(docs),
        current=counts["current"],
        superseded=counts["superseded"],
        draft=counts["draft"],
        categories=categories,
    )


# ── CO ↔ Document Linking ──

@router.post(
    "/change-orders/{co_id}/affected-documents",
    response_model=AffectedDocumentResponse,
    status_code=201,
)
async def link_affected_document(
    co_id: UUID,
    body: AffectedDocumentCreate,
    contractor: dict = Depends(get_current_contractor),
):
    """Link a change order to a document it affects."""
    db = get_supabase()

    # Verify CO ownership
    co = (
        db.table("change_orders")
        .select("*, projects!inner(contractor_id)")
        .eq("id", str(co_id))
        .maybe_single()
        .execute()
    ).data
    if not co or co["projects"]["contractor_id"] != contractor["id"]:
        raise HTTPException(status_code=404, detail="Change order not found")

    data = {
        "change_order_id": str(co_id),
        "document_id": str(body.document_id),
        "impact_type": body.impact_type,
        "notes": body.notes,
    }
    result = db.table("change_order_documents").insert(data).execute()

    # Fetch with document details
    linked = (
        db.table("change_order_documents")
        .select("*, project_documents(*)")
        .eq("id", result.data[0]["id"])
        .single()
        .execute()
    ).data

    return _format_affected_doc(linked)


@router.get(
    "/change-orders/{co_id}/affected-documents",
    response_model=list[AffectedDocumentResponse],
)
async def list_affected_documents(
    co_id: UUID,
    contractor: dict = Depends(get_current_contractor),
):
    db = get_supabase()

    co = (
        db.table("change_orders")
        .select("*, projects!inner(contractor_id)")
        .eq("id", str(co_id))
        .maybe_single()
        .execute()
    ).data
    if not co or co["projects"]["contractor_id"] != contractor["id"]:
        raise HTTPException(status_code=404, detail="Change order not found")

    result = (
        db.table("change_order_documents")
        .select("*, project_documents(*)")
        .eq("change_order_id", str(co_id))
        .order("created_at")
        .execute()
    )
    return [_format_affected_doc(r) for r in result.data]


# ── Helpers ──

def _verify_document_ownership(db, document_id: UUID, contractor_id: str) -> dict:
    doc = (
        db.table("project_documents")
        .select("*, projects!inner(contractor_id)")
        .eq("id", str(document_id))
        .maybe_single()
        .execute()
    ).data
    if not doc or doc["projects"]["contractor_id"] != contractor_id:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _format_affected_doc(row: dict) -> dict:
    doc_data = row.pop("project_documents", None)
    result = {**row, "document": doc_data}
    return result
