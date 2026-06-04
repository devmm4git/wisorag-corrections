"""
WISO-AI — Continuous Sync Pipeline
Pipeline 3: Real-time sync for new corrective actions.

Called by: POST /corrective-actions/ingest (M3 FastAPI endpoint)

Flow:
    1. Field validation (Level 1/2/3) — CorrectiveActionFieldValidator
    2. Semantic validation (ADR-001)  — CorrectiveActionValidator
    3. Generate embedding (Vertex AI) — text-embedding-004 (768 dims)
    4. INSERT into AlloyDB            — corrective_actions_vectors
    5. Return SyncResult

Target latency: < 30 seconds end-to-end
Design: Single record — no batching, no loops

Owner: rag-dataengineer@mm4.me
Milestone: M2 — Task 2.7
Called by: backend/app/routers/corrective_actions.py (M3)
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import asyncpg
from google.cloud import aiplatform

from backend.config.settings import settings
from backend.rag.corrective_action_validator import (
    CorrectiveActionFieldValidator,
    CorrectiveActionValidator,
    ValidatorConfig,
    ValidationResult,
)

logger = logging.getLogger("wiso-ai.sync")


# ── Result Object ──────────────────────────────────────────────────────────────
@dataclass
class SyncResult:
    """
    Result of a sync operation.
    Used by M3 API to build HTTP response.

    success=True  → HTTP 201 Created
    success=False → HTTP 422 Unprocessable Entity
    """
    success: bool
    concern_id: str
    alloydb_id: Optional[int] = None       # id del registro insertado
    rejection_reason: Optional[str] = None  # razón de rechazo si success=False
    embedding_dims: int = 0                 # 768 si se generó embedding
    latency_ms: float = 0.0                # latencia total en ms

    def to_api_response(self) -> dict:
        """Format for HTTP API response (M3)."""
        if self.success:
            return {
                "success": True,
                "concern_id": self.concern_id,
                "alloydb_id": self.alloydb_id,
                "embedding_dims": self.embedding_dims,
                "latency_ms": round(self.latency_ms, 2),
                "message": "Corrective action synced successfully."
            }
        return {
            "success": False,
            "concern_id": self.concern_id,
            "rejection_reason": self.rejection_reason,
            "message": "Corrective action rejected — not synced."
        }


# ── Embedding ──────────────────────────────────────────────────────────────────
def generate_single_embedding(text: str) -> list[float]:
    """
    Generate a single 768-dim embedding via Vertex AI.
    No batching — single record for real-time performance.
    """
    aiplatform.init(
        project=settings.vertex_ai_project,
        location=settings.vertex_ai_location
    )
    from vertexai.language_models import TextEmbeddingModel
    model = TextEmbeddingModel.from_pretrained(settings.embedding_model)
    result = model.get_embeddings([text])
    return result[0].values


# ── Chunk text ─────────────────────────────────────────────────────────────────
def build_chunk_text(record: dict) -> str:
    """
    Build semantic chunk text — ONLY Concern + Corrective Action.
    No metadata in embedding (ADR-002).
    """
    concern = record.get('concern_description', '').strip()
    corrective = record.get('corrective_action', '').strip()
    return f"Concern: {concern}\n\nCorrective Action: {corrective}"


# ── AlloyDB Insert ─────────────────────────────────────────────────────────────
async def insert_single_record(
    record: dict,
    embedding: list[float]
) -> Optional[int]:
    """
    Insert a single validated record into AlloyDB.
    Returns the alloydb id of the inserted record, or None if failed.
    """
    pool = await asyncpg.create_pool(
        host=settings.alloydb_host,
        port=settings.alloydb_port,
        database=settings.alloydb_database,
        user=settings.alloydb_user,
        password=settings.alloydb_password,
        ssl='require',
        min_size=1,
        max_size=1,
    )

    insert_query = """
        INSERT INTO corrective_actions_vectors (
            concern_id, plant, department,
            concern_description, corrective_action,
            severity, collection_point, product_line,
            charged_zone, chunk_text, embedding
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::vector
        )
        ON CONFLICT DO NOTHING
        RETURNING id
    """

    try:
        chunk_text = build_chunk_text(record)
        embedding_str = f"[{','.join(map(str, embedding))}]"

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                insert_query,
                record.get('concern_id'),
                record.get('plant'),
                record.get('department'),
                record.get('concern_description'),
                record.get('corrective_action'),
                record.get('severity'),
                record.get('collection_point'),
                record.get('product_line'),
                record.get('charged_zone'),
                chunk_text,
                embedding_str
            )
            if row:
                return row['id']
            return None
    finally:
        await pool.close()


# ── Main Sync Function ─────────────────────────────────────────────────────────
async def sync_new_corrective_action(record: dict) -> SyncResult:
    """
    Main entry point for real-time corrective action sync.
    Called by: POST /corrective-actions/ingest (M3 FastAPI)

    Args:
        record: dict with corrective action fields from WISOHUB

    Returns:
        SyncResult — check .success before building HTTP response

    Example:
        result = await sync_new_corrective_action({
            "concern_id": "C099",
            "department": "PAINT",
            "product_line": "RANGER",
            "concern_description": "Paint run on door lower section",
            "corrective_action": "Adjusted gun pressure from 45 to 38 PSI..."
        })
        if result.success:
            return JSONResponse(result.to_api_response(), status_code=201)
        else:
            return JSONResponse(result.to_api_response(), status_code=422)
    """
    import time
    start_time = time.time()
    concern_id = record.get('concern_id', 'UNKNOWN')

    logger.info(f"[{concern_id}] Sync started")

    # ── Step 1: Field Validation (Level 1/2/3) ────────────────────────────
    field_validator = CorrectiveActionFieldValidator()
    field_result = field_validator.validate(record)

    if field_result is not None:
        logger.warning(f"[{concern_id}] Field validation failed: {field_result.reason}")
        return SyncResult(
            success=False,
            concern_id=concern_id,
            rejection_reason=field_result.reason,
            latency_ms=(time.time() - start_time) * 1000
        )

    # ── Step 2: Semantic Validation (ADR-001) ─────────────────────────────
    semantic_validator = CorrectiveActionValidator(
        config=ValidatorConfig(
            ai_enabled=True,
            ai_quality_threshold=0.6,
            min_chars=30,
            min_words=5
        )
    )

    semantic_result: ValidationResult = await semantic_validator.validate(
        corrective_action=record.get('corrective_action', ''),
        concern_id=concern_id,
        concern_description=record.get('concern_description', '')
    )

    if not semantic_result.is_valid:
        logger.warning(f"[{concern_id}] Semantic validation failed: {semantic_result.reason}")
        return SyncResult(
            success=False,
            concern_id=concern_id,
            rejection_reason=semantic_result.reason,
            latency_ms=(time.time() - start_time) * 1000
        )

    # ── Step 3: Generate Embedding ────────────────────────────────────────
    chunk_text = build_chunk_text(record)
    logger.info(f"[{concern_id}] Generating embedding...")

    try:
        embedding = generate_single_embedding(chunk_text)
        logger.info(f"[{concern_id}] Embedding generated ({len(embedding)} dims)")
    except Exception as e:
        logger.error(f"[{concern_id}] Embedding failed: {e}")
        return SyncResult(
            success=False,
            concern_id=concern_id,
            rejection_reason=f"Embedding generation failed: {str(e)}",
            latency_ms=(time.time() - start_time) * 1000
        )

    # ── Step 4: Insert to AlloyDB ─────────────────────────────────────────
    logger.info(f"[{concern_id}] Inserting into AlloyDB...")

    try:
        alloydb_id = await insert_single_record(record, embedding)

        if alloydb_id is None:
            logger.warning(f"[{concern_id}] Already exists in AlloyDB — skipped")
            return SyncResult(
                success=False,
                concern_id=concern_id,
                rejection_reason="Record already exists in AlloyDB (ON CONFLICT DO NOTHING).",
                latency_ms=(time.time() - start_time) * 1000
            )

        latency = (time.time() - start_time) * 1000
        logger.info(
            f"[{concern_id}] Sync complete — "
            f"alloydb_id={alloydb_id}, "
            f"latency={latency:.0f}ms"
        )

        return SyncResult(
            success=True,
            concern_id=concern_id,
            alloydb_id=alloydb_id,
            embedding_dims=len(embedding),
            latency_ms=latency
        )

    except Exception as e:
        logger.error(f"[{concern_id}] AlloyDB insert failed: {e}")
        return SyncResult(
            success=False,
            concern_id=concern_id,
            rejection_reason=f"AlloyDB insert failed: {str(e)}",
            latency_ms=(time.time() - start_time) * 1000
        )