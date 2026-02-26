"""Rate limiting middleware using Redis sliding window.

Limits action endpoints (confirm, reject, sign) to 10 req/min per IP.
General API endpoints are not rate-limited to avoid impacting normal usage.
"""
import time
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger

# Paths that require rate limiting (action endpoints)
RATE_LIMITED_PATHS = {
    "/confirm",
    "/reject",
    "/sign",
    "/send",
    "/connect",
    "/subscribe",
}

MAX_REQUESTS = 10
WINDOW_SECONDS = 60


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limits action endpoints using Redis sliding window counter."""

    async def dispatch(self, request: Request, call_next):
        # Only rate-limit specific action endpoints
        path = request.url.path
        should_limit = any(path.endswith(p) for p in RATE_LIMITED_PATHS)

        if not should_limit:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:{client_ip}:{path}"

        try:
            import redis
            from app.config import get_settings
            settings = get_settings()
            r = redis.from_url(settings.redis_url)

            now = time.time()
            window_start = now - WINDOW_SECONDS

            pipe = r.pipeline()
            # Remove expired entries
            pipe.zremrangebyscore(key, 0, window_start)
            # Count remaining entries
            pipe.zcard(key)
            # Add current request
            pipe.zadd(key, {str(now): now})
            # Set TTL on the key
            pipe.expire(key, WINDOW_SECONDS)
            results = pipe.execute()

            request_count = results[1]

            if request_count >= MAX_REQUESTS:
                logger.warning(
                    f"Rate limit exceeded for {client_ip} on {path} "
                    f"({request_count}/{MAX_REQUESTS} in {WINDOW_SECONDS}s)"
                )
                raise HTTPException(
                    status_code=429,
                    detail={
                        "error": "Rate limit exceeded",
                        "limit": MAX_REQUESTS,
                        "window_seconds": WINDOW_SECONDS,
                        "retry_after": WINDOW_SECONDS,
                    },
                )

        except (ImportError, ConnectionError, Exception) as e:
            # If Redis is unavailable, allow the request but log warning
            if not isinstance(e, HTTPException):
                logger.debug(f"Rate limiter Redis unavailable, allowing request: {e}")

            if isinstance(e, HTTPException):
                raise

        response = await call_next(request)
        return response
