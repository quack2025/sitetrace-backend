from uuid import UUID
from loguru import logger
from app.database import get_supabase


async def upload_file(
    bucket: str,
    path: str,
    file_bytes: bytes,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload a file to Supabase Storage and return the path."""
    db = get_supabase()
    db.storage.from_(bucket).upload(path, file_bytes, {"content-type": content_type})
    logger.info(f"Uploaded {path} to bucket {bucket} ({len(file_bytes)} bytes)")
    return path


async def generate_signed_url(
    bucket: str, path: str, expires: int = 3600
) -> str:
    """Generate a signed URL for temporary access to a file."""
    db = get_supabase()
    result = db.storage.from_(bucket).create_signed_url(path, expires)
    return result["signedURL"]


def evidence_path(project_id: UUID, change_event_id: UUID, filename: str, processed: bool = False) -> str:
    prefix = "processed" if processed else "original"
    return f"{project_id}/{change_event_id}/{prefix}_{filename}"


def change_order_path(project_id: UUID, order_number: str) -> str:
    return f"{project_id}/{order_number}.pdf"
