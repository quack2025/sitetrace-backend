import httpx
from loguru import logger
from app.config import get_settings


async def send_email(to: str, subject: str, html: str) -> bool:
    """Send an email via Resend API.

    Returns True if sent successfully, False otherwise.
    Does not raise — notification failures should not break the pipeline.
    """
    settings = get_settings()

    if not settings.resend_api_key:
        logger.warning(
            f"Resend API key not configured — skipping email to {to}: {subject}"
        )
        return False

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": f"{settings.resend_from_name} <{settings.resend_from_email}>",
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
                timeout=10.0,
            )

            if resp.status_code in (200, 201):
                data = resp.json()
                logger.info(
                    f"Email sent via Resend (id={data.get('id', 'unknown')}, to={to})"
                )
                return True
            else:
                logger.error(
                    f"Resend API error {resp.status_code}: {resp.text[:200]} "
                    f"(to={to}, subject={subject[:50]})"
                )
                return False

    except httpx.TimeoutException:
        logger.error(f"Resend API timeout sending to {to}")
        return False
    except Exception as e:
        logger.error(f"Failed to send email via Resend to {to}: {e}")
        return False
