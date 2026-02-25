from abc import ABC, abstractmethod
from app.models.ingest_event import IngestEventCreate


class BaseIngestor(ABC):
    """Abstract base class for all input channel ingestors.

    All channels (Gmail, Outlook, WhatsApp, manual, API) produce IngestEvents
    through this interface. The processing pipeline consumes IngestEvents,
    never raw channel-specific data.
    """

    @abstractmethod
    async def fetch_new_messages(self, integration: dict) -> list[IngestEventCreate]:
        """Fetch new messages from the channel and return IngestEvent payloads.

        Args:
            integration: Row from the integrations table with credentials.

        Returns:
            List of IngestEventCreate objects ready to be inserted.
        """
        ...

    @abstractmethod
    async def download_attachment(self, integration: dict, ref: dict) -> bytes:
        """Download an attachment given a channel-specific reference.

        Args:
            integration: Row from the integrations table with credentials.
            ref: Channel-specific reference to the attachment (from attachments JSONB).

        Returns:
            Raw bytes of the attachment.
        """
        ...
