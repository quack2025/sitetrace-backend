# SiteTrace Backend — Claude Code Instructions

## Project
SiteTrace is an AI-powered construction change order detection platform.
Backend: Python 3.12, FastAPI, Supabase, Celery, Redis, Claude API.

## Key Rules
- Always use `gen_random_uuid()` (never `uuid_generate_v4()`)
- Always use `PyJWT` (never `python-jose`)
- All agents return `list[ChangeEventProposal]` (never a single result)
- Every status change must create a `state_transitions` record
- Prompts are versioned in `app/agents/prompts/{name}/v{n}.txt`
- `change_events` must record `prompt_version`, `model_used`, `tokens_used`, `processing_time_ms`
- Use `loguru` for all logging (never `print()` or stdlib `logging`)
- All API endpoints under `/api/v1/`
- Supabase service key is used server-side only — never expose it
- Never log API keys, tokens, or email content

## Architecture
- Input channels → `ingest_events` table (via `BaseIngestor` abstraction)
- Processing: `ingest_events` → Celery task → orchestrator → AI agents → `change_events`
- N:N relationship: `change_event_sources` links ingest_events to change_events
- Change orders have `change_order_items` for line-item costs
- `state_transitions` table provides event sourcing for audit trail

## Testing
```bash
pytest tests/ -v
```

## Running locally
```bash
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app worker --loglevel=info
celery -A app.workers.celery_app beat --loglevel=info
```
