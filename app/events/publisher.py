"""SSE event publisher using Redis pub/sub.

Events are published to Redis channels keyed by contractor_id.
The SSE endpoint subscribes to the channel for the authenticated contractor.
"""
import json
from loguru import logger
from app.config import get_settings

# In-memory fallback when Redis is not available (dev mode)
_fallback_queues: dict[str, list[dict]] = {}


async def publish_event(contractor_id: str, event_type: str, data: dict):
    """Publish an SSE event for a contractor.

    Args:
        contractor_id: UUID of the contractor to notify.
        event_type: Event type (e.g. 'change_event.created').
        data: Event payload dict.
    """
    message = json.dumps({
        "type": event_type,
        "data": data,
    })

    channel = f"sse:{contractor_id}"

    try:
        import redis as redis_lib
        settings = get_settings()
        r = redis_lib.from_url(settings.redis_url)
        r.publish(channel, message)
        logger.debug(f"SSE event published: {event_type} → {channel}")
    except Exception as e:
        # Fallback: store in memory (for dev without Redis)
        logger.warning(f"Redis publish failed, using in-memory fallback: {e}")
        if contractor_id not in _fallback_queues:
            _fallback_queues[contractor_id] = []
        _fallback_queues[contractor_id].append(json.loads(message))
        # Keep only last 100 events in memory
        _fallback_queues[contractor_id] = _fallback_queues[contractor_id][-100:]


def get_fallback_events(contractor_id: str) -> list[dict]:
    """Get and clear pending fallback events for a contractor."""
    events = _fallback_queues.pop(contractor_id, [])
    return events
