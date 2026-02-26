"""Embedding-based semantic deduplication for change events.

Uses OpenAI text-embedding-3-small to generate embeddings and cosine
similarity to detect duplicate or near-duplicate change events within
the same project.
"""
import httpx
import math
from uuid import UUID
from loguru import logger
from app.config import get_settings
from app.database import get_supabase

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536

# Thresholds
DUPLICATE_THRESHOLD = 0.92    # Merge — same change, different sources
POSSIBLE_DUP_THRESHOLD = 0.80  # Flag — similar but might be different


async def generate_embedding(text: str) -> list[float]:
    """Generate an embedding vector for the given text using OpenAI API.

    Args:
        text: The text to embed.

    Returns:
        List of floats representing the embedding vector.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        logger.warning("No OpenAI API key configured, skipping embedding generation")
        return []

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": EMBEDDING_MODEL,
                "input": text[:8000],  # Truncate to model limit
                "dimensions": EMBEDDING_DIMENSION,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["data"][0]["embedding"]


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


async def find_similar_change_events(
    project_id: UUID,
    description: str,
    exclude_id: UUID | None = None,
) -> list[dict]:
    """Find change events in the same project that are semantically similar.

    Args:
        project_id: Project to search within.
        description: Description text to compare against.
        exclude_id: Optional CE ID to exclude from results.

    Returns:
        List of dicts with: change_event_id, similarity, status.
        Sorted by similarity descending.
    """
    db = get_supabase()

    # Generate embedding for the new description
    new_embedding = await generate_embedding(description)
    if not new_embedding:
        return []

    # Fetch existing change events with embeddings in the same project
    query = (
        db.table("change_events")
        .select("id, description, embedding, status")
        .eq("project_id", str(project_id))
        .not_.is_("embedding", "null")
    )
    if exclude_id:
        query = query.neq("id", str(exclude_id))

    existing = query.execute()

    results = []
    for ce in existing.data:
        if not ce.get("embedding"):
            continue
        sim = cosine_similarity(new_embedding, ce["embedding"])
        if sim >= POSSIBLE_DUP_THRESHOLD:
            results.append({
                "change_event_id": ce["id"],
                "similarity": round(sim, 4),
                "status": ce["status"],
                "description": ce["description"][:100],
                "is_duplicate": sim >= DUPLICATE_THRESHOLD,
                "is_possible_duplicate": POSSIBLE_DUP_THRESHOLD <= sim < DUPLICATE_THRESHOLD,
            })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results


async def check_and_handle_duplicates(
    project_id: UUID,
    description: str,
    ingest_event_id: UUID,
) -> dict:
    """Check if a proposed change event is a duplicate and handle accordingly.

    Returns:
        dict with:
        - action: "merge" | "flag" | "create"
        - existing_id: UUID of existing CE if merge/flag
        - similarity: float if match found
    """
    similar = await find_similar_change_events(project_id, description)

    if not similar:
        return {"action": "create"}

    best_match = similar[0]

    if best_match["is_duplicate"]:
        # Merge: link the ingest_event to the existing change_event
        db = get_supabase()
        db.table("change_event_sources").insert(
            {
                "change_event_id": best_match["change_event_id"],
                "ingest_event_id": str(ingest_event_id),
                "relevance_score": best_match["similarity"],
            }
        ).execute()

        logger.info(
            f"Merged duplicate: ingest_event {ingest_event_id} → "
            f"existing CE {best_match['change_event_id']} "
            f"(similarity: {best_match['similarity']})"
        )

        return {
            "action": "merge",
            "existing_id": best_match["change_event_id"],
            "similarity": best_match["similarity"],
        }

    elif best_match["is_possible_duplicate"]:
        logger.info(
            f"Possible duplicate found for ingest_event {ingest_event_id}: "
            f"CE {best_match['change_event_id']} "
            f"(similarity: {best_match['similarity']})"
        )
        return {
            "action": "flag",
            "existing_id": best_match["change_event_id"],
            "similarity": best_match["similarity"],
        }

    return {"action": "create"}
