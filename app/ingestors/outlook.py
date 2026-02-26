"""Outlook channel ingestor using Microsoft Graph API.

Implements the BaseIngestor interface for Microsoft Outlook / Exchange
email accounts via MSAL + Graph API.
"""
import base64
import httpx
from datetime import datetime, timedelta, timezone
from loguru import logger
from app.ingestors.base import BaseIngestor
from app.models.ingest_event import IngestEventCreate
from app.config import get_settings
from app.database import get_supabase

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


class OutlookIngestor(BaseIngestor):
    """Outlook/Exchange channel ingestor using Microsoft Graph API."""

    async def _refresh_token_if_needed(self, integration: dict) -> str:
        """Refresh OAuth token if expired, return valid access token."""
        settings = get_settings()

        if integration.get("token_expires_at"):
            expires = datetime.fromisoformat(integration["token_expires_at"])
            if expires > datetime.now(timezone.utc):
                return integration["access_token"]

        # Refresh the token via MSAL
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                MS_TOKEN_URL,
                data={
                    "client_id": settings.outlook_client_id,
                    "client_secret": settings.outlook_client_secret,
                    "refresh_token": integration["refresh_token"],
                    "grant_type": "refresh_token",
                    "scope": "https://graph.microsoft.com/Mail.Read offline_access",
                },
            )
            resp.raise_for_status()
            tokens = resp.json()

        new_access_token = tokens["access_token"]
        expires_in = tokens.get("expires_in", 3600)
        new_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        new_refresh_token = tokens.get("refresh_token", integration["refresh_token"])

        # Update in database
        db = get_supabase()
        db.table("integrations").update(
            {
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "token_expires_at": new_expires_at.isoformat(),
            }
        ).eq("id", integration["id"]).execute()

        return new_access_token

    async def fetch_new_messages(self, integration: dict) -> list[IngestEventCreate]:
        """Fetch new emails via Microsoft Graph API."""
        access_token = await self._refresh_token_if_needed(integration)
        db = get_supabase()

        # Query for messages received in last 7 days
        after_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        filter_query = f"receivedDateTime ge {after_date}"

        headers = {"Authorization": f"Bearer {access_token}"}
        events: list[IngestEventCreate] = []

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GRAPH_API_BASE}/me/messages",
                headers=headers,
                params={
                    "$filter": filter_query,
                    "$top": 50,
                    "$select": "id,subject,from,receivedDateTime,body,hasAttachments",
                    "$orderby": "receivedDateTime desc",
                },
            )
            resp.raise_for_status()
            messages = resp.json().get("value", [])

            for msg in messages:
                msg_id = msg["id"]

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

                # Extract sender
                from_data = msg.get("from", {}).get("emailAddress", {})
                sender_email = from_data.get("address", "")
                sender_name = from_data.get("name", "")

                # Extract body text (prefer text/plain, fallback to html stripped)
                body = msg.get("body", {})
                body_text = body.get("content", "")
                if body.get("contentType") == "html":
                    body_text = self._strip_html(body_text)

                # Get attachment references if present
                attachments = []
                if msg.get("hasAttachments"):
                    att_resp = await client.get(
                        f"{GRAPH_API_BASE}/me/messages/{msg_id}/attachments",
                        headers=headers,
                        params={
                            "$select": "id,name,contentType,size,isInline",
                        },
                    )
                    if att_resp.status_code == 200:
                        for att in att_resp.json().get("value", []):
                            if att.get("isInline"):
                                continue
                            attachments.append({
                                "message_id": msg_id,
                                "attachment_id": att["id"],
                                "filename": att.get("name", ""),
                                "mime_type": att.get("contentType", ""),
                                "size": att.get("size", 0),
                            })

                received_at = None
                if msg.get("receivedDateTime"):
                    try:
                        received_at = datetime.fromisoformat(
                            msg["receivedDateTime"].replace("Z", "+00:00")
                        )
                    except ValueError:
                        received_at = datetime.now(timezone.utc)

                events.append(
                    IngestEventCreate(
                        channel="outlook",
                        raw_payload={
                            "subject": msg.get("subject", ""),
                            "body": body_text,
                            "from": sender_email,
                            "date": msg.get("receivedDateTime", ""),
                        },
                        attachments=attachments,
                        sender_email=sender_email,
                        sender_name=sender_name,
                        subject=msg.get("subject", ""),
                        external_message_id=msg_id,
                        received_at=received_at,
                    )
                )

        logger.info(
            f"Outlook ingestor: {len(events)} new messages found "
            f"(integration: {integration['id']})"
        )
        return events

    async def download_attachment(self, integration: dict, ref: dict) -> bytes:
        """Download an Outlook attachment by message_id and attachment_id."""
        access_token = await self._refresh_token_if_needed(integration)
        msg_id = ref["message_id"]
        att_id = ref["attachment_id"]

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{GRAPH_API_BASE}/me/messages/{msg_id}/attachments/{att_id}",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            resp.raise_for_status()
            data = resp.json()

            # Graph API returns base64-encoded content in contentBytes
            content_bytes = data.get("contentBytes", "")
            return base64.b64decode(content_bytes)

    @staticmethod
    def _strip_html(html: str) -> str:
        """Simple HTML tag stripping for email body extraction."""
        import re
        # Remove script and style blocks
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text).strip()
        # Decode common HTML entities
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&nbsp;", " ").replace("&quot;", '"')
        return text
