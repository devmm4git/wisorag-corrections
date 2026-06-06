"""
RAG retriever — AlloyDB vector search.

Generates query embedding via Vertex AI text-embedding-004 (768 dims)
and retrieves top-K similar corrective actions using HNSW cosine index.

ADR-002: chunk_text = concern_description + corrective_action only.
effective_score = similarity * feedback_score — calculated in Python,
never persisted in AlloyDB.
"""

import logging
from typing import Optional

from vertexai.language_models import TextEmbeddingModel

from backend.db.alloydb import get_write_pool

logger = logging.getLogger("wiso-ai.rag.retriever")

EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIMS = 768


async def embed_query(text: str) -> list[float]:
    """Generate a 768-dim embedding for the query text via Vertex AI.

    Args:
        text: The concern description to embed.

    Returns:
        list[float]: 768-dimensional embedding vector.

    Raises:
        RuntimeError: If Vertex AI embedding call fails.
    """
    try:
        model = TextEmbeddingModel.from_pretrained(EMBEDDING_MODEL)
        embeddings = model.get_embeddings([text])
        vector = embeddings[0].values
        if len(vector) != EMBEDDING_DIMS:
            raise RuntimeError(
                f"Unexpected embedding dims: {len(vector)} (expected {EMBEDDING_DIMS})"
            )
        logger.info("Query embedded — dims=%d", len(vector))
        return vector
    except Exception as exc:
        logger.error("Vertex AI embedding failed: %s", exc)
        raise RuntimeError(f"Embedding generation failed: {exc}") from exc


async def search_similar(
    department: str,
    product_line: str,
    query_vector: list[float],
    plant: Optional[str] = None,
    top_k: int = 5,
) -> list[dict]:
    """Retrieve top-K similar corrective actions from AlloyDB.

    Uses HNSW cosine index for fast approximate nearest-neighbor search.
    Applies hard filters on department and product_line.
    effective_score = similarity * feedback_score (transient — never persisted).

    Args:
        department: Hard filter — only returns records from this department.
        product_line: Hard filter — only returns records for this product line.
        query_vector: 768-dim embedding of the concern description.
        plant: Optional additional filter on plant.
        top_k: Number of results to return. Default 5.

    Returns:
        list[dict]: Top-K records sorted by cosine distance (HNSW index).

    Raises:
        RuntimeError: If AlloyDB query fails.
    """
    pool = await get_write_pool()

    vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    base_query = """
        SELECT
            id,
            concern_id,
            department,
            product_line,
            concern_description,
            corrective_action,
            1 - (embedding <=> $1::vector) AS similarity,
            feedback_score,
            mttr_minutes
        FROM corrective_actions_vectors
        WHERE department = $2
          AND product_line = $3
    """

    params = [vector_str, department, product_line]

    if plant:
        base_query += " AND plant = $4"
        params.append(plant)
        base_query += " ORDER BY embedding <=> $1::vector LIMIT $5"
        params.append(top_k)
    else:
        base_query += " ORDER BY embedding <=> $1::vector LIMIT $4"
        params.append(top_k)

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(base_query, *params)

        results = []
        for row in rows:
            similarity = float(row["similarity"])
            feedback_score = float(row["feedback_score"])
            effective_score = round(similarity * feedback_score, 6)
            results.append({
                "alloydb_id": row["id"],
                "concern_id": row["concern_id"],
                "department": row["department"],
                "product_line": row["product_line"],
                "concern_description": row["concern_description"],
                "corrective_action": row["corrective_action"],
                "similarity": round(similarity, 6),
                "feedback_score": round(feedback_score, 6),
                "effective_score": effective_score,
                "mttr_minutes": row["mttr_minutes"],
            })

        logger.info(
            "Search complete — dept=%s product_line=%s results=%d",
            department, product_line, len(results),
        )
        return results

    except Exception as exc:
        logger.error("AlloyDB search failed: %s", exc)
        raise RuntimeError(f"AlloyDB search failed: {exc}") from exc
