from app.ingestors.base import BaseIngestor
from app.models.ingest_event import IngestEventCreate


class ManualIngestor(BaseIngestor):
    """Ingestor for manual change event entry via the API."""

    async def fetch_new_messages(self, integration: dict) -> list[IngestEventCreate]:
        # Manual ingestor doesn't poll — events are created directly via API
        return []

    async def download_attachment(self, integration: dict, ref: dict) -> bytes:
        # Manual attachments are uploaded directly, not fetched from external service
        raise NotImplementedError("Manual attachments are uploaded directly via API")
