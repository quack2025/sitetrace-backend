from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
import sys

from app.config import get_settings
from app.routers import (
    projects,
    change_events,
    change_orders,
    integrations,
    notifications,
    webhooks,
    events_stream,
    gmail_oauth,
    outlook_oauth,
    timeline,
    billing,
)
from app.middleware.rate_limiter import RateLimitMiddleware

# Configure loguru
logger.remove()
logger.add(sys.stderr, format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}", level="INFO")

app = FastAPI(
    title="SiteTrace API",
    description="AI-powered construction change order detection and management",
    version="1.0.0",
)

# Middleware
settings = get_settings()
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.app_base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(projects.router)
app.include_router(change_events.router)
app.include_router(change_orders.router)
app.include_router(integrations.router)
app.include_router(notifications.router)
app.include_router(webhooks.router)
app.include_router(events_stream.router)
app.include_router(gmail_oauth.router)
app.include_router(outlook_oauth.router)
app.include_router(timeline.router)
app.include_router(billing.router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with dependency status."""
    health = {
        "status": "ok",
        "version": "1.0.0",
        "dependencies": {},
    }

    # Check Supabase
    try:
        from app.database import get_supabase
        db = get_supabase()
        db.table("contractors").select("id").limit(1).execute()
        health["dependencies"]["supabase"] = "ok"
    except Exception as e:
        health["dependencies"]["supabase"] = f"error: {str(e)[:100]}"
        health["status"] = "degraded"

    # Check Redis
    try:
        import redis
        r = redis.from_url(settings.redis_url)
        r.ping()
        health["dependencies"]["redis"] = "ok"
    except Exception as e:
        health["dependencies"]["redis"] = f"error: {str(e)[:100]}"
        health["status"] = "degraded"

    # Check Anthropic API key is set
    health["dependencies"]["anthropic"] = (
        "ok" if settings.anthropic_api_key else "not configured"
    )

    # Check Resend API key is set
    health["dependencies"]["resend"] = (
        "ok" if settings.resend_api_key else "not configured"
    )

    # Check Stripe
    health["dependencies"]["stripe"] = (
        "ok" if settings.stripe_secret_key else "not configured"
    )

    # Queue metrics (Celery)
    try:
        from app.workers.celery_app import celery_app
        inspect = celery_app.control.inspect(timeout=2.0)
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        active_count = sum(len(v) for v in active.values())
        pending_count = sum(len(v) for v in reserved.values())
        health["queue"] = {
            "active_tasks": active_count,
            "pending_tasks": pending_count,
            "workers": list(active.keys()),
        }
    except Exception as e:
        health["queue"] = {"error": str(e)[:100]}

    return health
