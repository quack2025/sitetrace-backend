"""Document Bulletin PDF generator using WeasyPrint."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from loguru import logger
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.database import get_supabase
from app.processors.storage import upload_file, generate_signed_url

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _format_date(value) -> str:
    if not value:
        return "—"
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, datetime):
            dt = value
        else:
            return str(value)
        return dt.strftime("%B %d, %Y at %I:%M %p")
    except (ValueError, AttributeError):
        return str(value)


async def generate_bulletin_pdf(
    bulletin: dict,
    change_order: dict,
    project: dict,
    contractor_name: str,
    recipients: list[dict],
) -> str:
    """Generate a PDF for a document bulletin.

    Args:
        bulletin: The bulletin record.
        change_order: The change order record.
        project: The project record.
        contractor_name: Contractor company/name.
        recipients: List of team members receiving the bulletin.

    Returns:
        Signed URL to the generated PDF.
    """
    context = {
        "bulletin_number": bulletin["bulletin_number"],
        "title": bulletin["title"],
        "summary_text": bulletin["summary_text"],
        "affected_areas": bulletin.get("affected_areas", []),
        "created_at": _format_date(bulletin.get("created_at")),
        "project_name": project.get("name", "Unknown"),
        "client_name": project.get("client_name", "Unknown"),
        "contractor_name": contractor_name,
        "order_number": change_order.get("order_number", "N/A"),
        "co_description": change_order.get("description", ""),
        "co_total": f"{float(change_order.get('total', 0)):,.2f}",
        "signed_at": _format_date(change_order.get("signed_at")),
        "recipients": recipients,
    }

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("document_bulletin.html")
    html_content = template.render(**context)

    pdf_bytes = HTML(string=html_content).write_pdf()

    logger.info(
        f"Bulletin PDF generated for {bulletin['bulletin_number']}: "
        f"{len(pdf_bytes)} bytes"
    )

    # Upload to Supabase Storage
    storage_path = (
        f"{project['id']}/{bulletin['bulletin_number']}.pdf"
    )

    await upload_file(
        bucket="bulletins",
        path=storage_path,
        file_bytes=pdf_bytes,
        content_type="application/pdf",
    )

    pdf_url = await generate_signed_url("bulletins", storage_path)

    logger.info(f"Bulletin PDF uploaded to {storage_path}")
    return pdf_url
