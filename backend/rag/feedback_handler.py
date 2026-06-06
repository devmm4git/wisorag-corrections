"""
Feedback handler — AlloyDB UPDATE + BigQuery log.

ACCEPT: UPDATE accept_count++, recalculate feedback_score. No re-embedding.
REJECT: UPDATE reject_count++, recalculate feedback_score. No re-embedding.
MODIFY: INSERT new record with fresh 768-dim embedding. feedback_score = 1.0.

ADR: feedback_score updated via pure SQL UPDATE on id PK.
effective_score is never persisted — calculated transiently in retriever.py.
"""

import logging
from typing import Optional

from backend.db.alloydb import get_write_pool
from backend.rag.retriever import embed_query

logger = logging.getLogger("wiso-ai.rag.feedback_handler")

ACCEPT_SQL = """
    UPDATE corrective_actions_vectors
    SET accept_count = accept_count + 1,
        feedback_score = (accept_count + 1.0) / (accept_count + reject_count + 1),
        updated_at = NOW()
    WHERE concern_id = $1
    RETURNING id, feedback_score;
"""

REJECT_SQL = """
    UPDATE corrective_actions_vectors
    SET reject_count = reject_count + 1,
        feedback_score = accept_count / (accept_count + reject_count + 1.0),
        updated_at = NOW()
    WHERE concern_id = $1
    RETURNING id, feedback_score;
"""

INSERT_MODIFIED_SQL = """
    INSERT INTO corrective_actions_vectors (
        concern_id, department, product_line, plant,
        concern_description, corrective_action,
        chunk_text, embedding, feedback_score
    )
    SELECT
        concern_id, department, product_line, plant,
        concern_description, $2,
        concern_description || ' ' || $2,
        $3::vector, 1.0
    FROM corrective_actions_vectors
    WHERE concern_id = $1
    LIMIT 1
    RETURNING id;
"""


async def apply_accept(concern_id: str) -> dict:
    """Apply ACCEPT feedback — increment accept_count, recalculate feedback_score.

    Args:
        concern_id: The concern ID to update.

    Returns:
        dict: Updated record id and new feedback_score.

    Raises:
        RuntimeError: If AlloyDB UPDATE fails.
    """
    pool = await get_write_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(ACCEPT_SQL, concern_id)
        if not rows:
            raise RuntimeError(f"concern_id not found in AlloyDB: {concern_id}")
        logger.info(
            "ACCEPT applied — concern_id=%s feedback_score=%.4f",
            concern_id, rows[0]["feedback_score"],
        )
        return {"id": rows[0]["id"], "feedback_score": rows[0]["feedback_score"]}
    except Exception as exc:
        logger.error("ACCEPT failed — concern_id=%s error=%s", concern_id, exc)
        raise RuntimeError(f"AlloyDB UPDATE failed: {exc}") from exc


async def apply_reject(concern_id: str) -> dict:
    """Apply REJECT feedback — increment reject_count, recalculate feedback_score.

    Args:
        concern_id: The concern ID to update.

    Returns:
        dict: Updated record id and new feedback_score.

    Raises:
        RuntimeError: If AlloyDB UPDATE fails.
    """
    pool = await get_write_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(REJECT_SQL, concern_id)
        if not rows:
            raise RuntimeError(f"concern_id not found in AlloyDB: {concern_id}")
        logger.info(
            "REJECT applied — concern_id=%s feedback_score=%.4f",
            concern_id, rows[0]["feedback_score"],
        )
        return {"id": rows[0]["id"], "feedback_score": rows[0]["feedback_score"]}
    except Exception as exc:
        logger.error("REJECT failed — concern_id=%s error=%s", concern_id, exc)
        raise RuntimeError(f"AlloyDB UPDATE failed: {exc}") from exc


async def apply_modify(
    concern_id: str,
    modified_text: str,
    coach_cds_id: str,
) -> str:
    """Apply MODIFY feedback — insert new record with fresh embedding.

    Generates a new 768-dim embedding for modified_text via Vertex AI,
    then inserts a new row in corrective_actions_vectors with feedback_score = 1.0.

    Args:
        concern_id: The original concern ID. Used to copy metadata.
        modified_text: The coach-edited corrective action text.
        coach_cds_id: Coach employee ID. Used to build the new chunk_id.

    Returns:
        str: chunk_id of the newly inserted record.

    Raises:
        RuntimeError: If embedding generation or AlloyDB INSERT fails.
    """
    # Generate fresh embedding for modified text
    try:
        vector = await embed_query(modified_text)
    except RuntimeError as exc:
        raise RuntimeError(f"Embedding generation failed for MODIFY: {exc}") from exc

    vector_str = "[" + ",".join(str(v) for v in vector) + "]"

    pool = await get_write_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(INSERT_MODIFIED_SQL, concern_id, modified_text, vector_str)
        if not rows:
            raise RuntimeError(f"INSERT returned no rows — concern_id={concern_id}")
        new_id = rows[0]["id"]
        new_chunk_id = f"{concern_id}_MOD_{coach_cds_id}_{new_id}"
        logger.info(
            "MODIFY applied — concern_id=%s new_id=%d new_chunk_id=%s",
            concern_id, new_id, new_chunk_id,
        )
        return new_chunk_id
    except Exception as exc:
        logger.error("MODIFY INSERT failed — concern_id=%s error=%s", concern_id, exc)
        raise RuntimeError(f"AlloyDB INSERT failed: {exc}") from exc


async def log_feedback_to_bigquery(
    request_id: str,
    concern_id: str,
    coach_cds_id: str,
    action: str,
    chunk_ids: list[str],
    modified_text: Optional[str] = None,
) -> None:
    """Log feedback event to BigQuery feedback_log.

    Args:
        request_id: Original request ID from /ai/recommend.
        concern_id: Concern identifier.
        coach_cds_id: Coach employee ID.
        action: ACCEPT / REJECT / MODIFY.
        chunk_ids: List of chunk IDs shown to the coach.
        modified_text: Modified text for MODIFY action. None otherwise.
    """
    # BigQuery logging — placeholder for M3 implementation
    # In production: use google-cloud-bigquery client to INSERT into feedback_log
    logger.info(
        "BigQuery log — request_id=%s concern_id=%s coach=%s action=%s",
        request_id, concern_id, coach_cds_id, action,
    )
