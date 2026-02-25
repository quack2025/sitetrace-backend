import base64
import httpx
from datetime import datetime, timedelta, timezone
from loguru import logger
from app.ingestors.base import BaseIngestor
from app.models.ingest_event import IngestEventCreate
from app.config import get_settings
from app.database import get_supabase

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


class GmailIngestor(BaseIngestor):
    """Gmail channel ingestor using Gmail API."""

    async def _refresh_token_if_needed(self, integration: dict) -> str:
        """Refresh OAuth token if expired, return valid access token."""
        settings = get_settings()

        if integration.get("token_expires_at"):
            expires = datetime.fromisoformat(integration["token_expires_at"])
            if expires > datetime.now(timezone.utc):
                return integration["access_token"]

        # Refresh the token
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.gmail_client_id,
                    "client_secret": settings.gmail_client_secret,
                    "refresh_token": integration["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            tokens = resp.json()

        new_access_token = tokens["access_token"]
        expires_in = tokens.get("expires_in", 3600)
        new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        # Update in database
        db = get_supabase()
        db.table("integrations").update(
            {
                "access_token": new_access_token,
                "token_expires_at": new_expires_at.isoformat(),
            }
        ).eq("id", integration["id"]).execute()

        return new_access_token

    async def fetch_new_messages(self, integration: dict) -> list[IngestEventCreate]:
        access_token = await self._refresh_token_if_needed(integration)
        db = get_supabase()

        # Query Gmail for recent messages (last 7 days)
        after_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime(
            "%Y/%m/%d"
        )
        query = f"after:{after_date}"

        headers = {"Authorization": f"Bearer {access_token}"}
        events: list[IngestEventCreate] = []

        async with httpx.AsyncClient() as client:
            # List messages
            resp = await client.get(
                f"{GMAIL_API_BASE}/users/me/messages",
                headers=headers,
                params={"q": query, "maxResults": 50},
            )
            resp.raise_for_status()
            messages = resp.json().get("messages", [])

            for msg_ref in messages:
                msg_id = msg_ref["id"]

                # Check deduplication
                existing = (
                    db.table("ingest_events")
                    .select("id")
                    .eq("external_message_id", msg_id)
                    .maybe_single()
                    .execute()
                )
                if existing.data:
                    continue

                # Fetch full message
                msg_resp = await client.get(
                    f"{GMAIL_API_BASE}/users/me/messages/{msg_id}",
                    headers=headers,
                    params={"format": "full"},
                )
                msg_resp.raise_for_status()
                msg_data = msg_resp.json()

                # Extract headers
                msg_headers = {
                    h["name"].lower(): h["value"]
                    for h in msg_data.get("payload", {}).get("headers", [])
                }

                # Extract body text
                body_text = self._extract_body(msg_data.get("payload", {}))

                # Extract attachment metadata
                attachments = self._extract_attachment_refs(
                    msg_data.get("payload", {}), msg_id
                )

                events.append(
                    IngestEventCreate(
                        channel="gmail",
                        raw_payload={
                            "subject": msg_headers.get("subject", ""),
                            "body": body_text,
                            "from": msg_headers.get("from", ""),
                            "date": msg_headers.get("date", ""),
                        },
                        attachments=attachments,
                        sender_email=self._parse_email(msg_headers.get("from", "")),
                        sender_name=self._parse_name(msg_headers.get("from", "")),
                        subject=msg_headers.get("subject", ""),
                        external_message_id=msg_id,
                        received_at=datetime.now(timezone.utc),
                    )
                )

        logger.info(
            f"Gmail ingestor: {len(events)} new messages found "
            f"(integration: {integration['id']})"
        )
        return events

    async def download_attachment(self, integration: dict, ref: dict) -> bytes:
        """Download a Gmail attachment by message_id and attachment_id."""
        access_token = await self._refresh_token_if_needed(integration)
        msg_id = ref["message_id"]
        att_id = ref["attachment_id"]

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GMAIL_API_BASE}/users/me/messages/{msg_id}/attachments/{att_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", "")
            return base64.urlsafe_b64decode(data)

    def _extract_body(self, payload: dict) -> str:
        """Recursively extract plain text body from Gmail payload."""
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get(
            "data"
        ):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode(
                "utf-8", errors="replace"
            )

        for part in payload.get("parts", []):
            text = self._extract_body(part)
            if text:
                return text
        return ""

    def _extract_attachment_refs(
        self, payload: dict, message_id: str
    ) -> list[dict]:
        """Extract attachment references from Gmail payload."""
        attachments = []
        for part in payload.get("parts", []):
            if part.get("filename") and part.get("body", {}).get("attachmentId"):
                attachments.append(
                    {
                        "message_id": message_id,
                        "attachment_id": part["body"]["attachmentId"],
                        "filename": part["filename"],
                        "mime_type": part.get("mimeType", ""),
                        "size": part.get("body", {}).get("size", 0),
                    }
                )
            # Check nested parts
            attachments.extend(self._extract_attachment_refs(part, message_id))
        return attachments

    @staticmethod
    def _parse_email(from_header: str) -> str:
        if "<" in from_header and ">" in from_header:
            return from_header.split("<")[1].split(">")[0]
        return from_header.strip()

    @staticmethod
    def _parse_name(from_header: str) -> str:
        if "<" in from_header:
            return from_header.split("<")[0].strip().strip('"')
        return ""
