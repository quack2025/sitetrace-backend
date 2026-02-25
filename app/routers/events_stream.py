"""SSE (Server-Sent Events) endpoint for real-time frontend updates.

The frontend connects with EventSource to receive live notifications:
- change_event.created — new change detected
- change_event.confirmed / change_event.updated — status changes
- change_order.sent — CO sent to client
- change_order.signed — client signed
- processing.completed / processing.failed — pipeline status
"""
import json
import asyncio
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse
from loguru import logger
from app.auth import get_current_contractor
from app.config import get_settings

router = APIRouter(prefix="/api/v1/events", tags=["events"])


async def _event_generator(request: Request, contractor_id: str):
    """Async generator that yields SSE events from Redis pub/sub."""
    settings = get_settings()
    channel = f"sse:{contractor_id}"

    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url)
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)

        logger.info(f"SSE client connected: contractor={contractor_id}")

        # Send heartbeat to confirm connection
        yield {"event": "connected", "data": json.dumps({"status": "ok"})}

        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")

                parsed = json.loads(data)
                yield {
                    "event": parsed.get("type", "message"),
                    "data": json.dumps(parsed.get("data", {})),
                }
            else:
                # Send keepalive every 15 seconds
                await asyncio.sleep(15)
                yield {"event": "keepalive", "data": ""}

        await pubsub.unsubscribe(channel)
        await r.close()
        logger.info(f"SSE client disconnected: contractor={contractor_id}")

    except ImportError:
        logger.warning("redis.asyncio not available, using polling fallback")
        yield {"event": "connected", "data": json.dumps({"status": "ok", "mode": "polling"})}

        from app.events.publisher import get_fallback_events

        while True:
            if await request.is_disconnected():
                break

            events = get_fallback_events(contractor_id)
            for event in events:
                yield {
                    "event": event.get("type", "message"),
                    "data": json.dumps(event.get("data", {})),
                }

            await asyncio.sleep(5)

    except Exception as e:
        logger.error(f"SSE stream error for contractor={contractor_id}: {e}")
        yield {"event": "error", "data": json.dumps({"error": str(e)[:100]})}


@router.get("/stream")
async def events_stream(
    request: Request,
    contractor: dict = Depends(get_current_contractor),
):
    """SSE endpoint — connect with EventSource from the frontend.

    Example (JavaScript):
        const es = new EventSource('/api/v1/events/stream', {
            headers: { 'Authorization': 'Bearer <token>' }
        });
        es.addEventListener('change_event.created', (e) => {
            const data = JSON.parse(e.data);
            console.log('New change:', data);
        });
    """
    return EventSourceResponse(
        _event_generator(request, contractor["id"]),
        media_type="text/event-stream",
    )
