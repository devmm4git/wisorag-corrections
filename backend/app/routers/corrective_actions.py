"""
Router — POST /corrective-actions/ingest

Milestone: M3 — FastAPI Backend & RAG API
Task: 3.2
Auth: Service Account new-corrective-action-sa@ragai-staging.iam.gserviceaccount.com
"""

import logging

from fastapi import APIRouter, HTTPException

from backend.app.models.corrective_action import (
    CorrectiveActionRequest,
    CorrectiveActionResponse,
)
from backend.pipelines.sync_new_ca import sync_new_corrective_action

logger = logging.getLogger("wiso-ai.routers.corrective_actions")

router = APIRouter(prefix="/corrective-actions", tags=["corrective-actions"])


@router.post(
    "/ingest",
    response_model=CorrectiveActionResponse,
    status_code=201,
    summary="Ingest new corrective action into RAG knowledge base",
    description=(
        "Validates, embeds and inserts a corrective action into AlloyDB. "
        "Available for RAG retrieval within 30 seconds."
    ),
)
async def ingest_corrective_action(
    request: CorrectiveActionRequest,
) -> CorrectiveActionResponse:
    """Receive, validate, embed and store a new corrective action.

    Args:
        request: Validated corrective action payload from WISOHUB.

    Returns:
        CorrectiveActionResponse: Result with alloydb_id and embedding_dims on success.

    Raises:
        HTTPException 400: L1 validation failed.
        HTTPException 409: concern_id already exists in AlloyDB.
        HTTPException 422: AI quality check failed.
        HTTPException 500: Vertex AI or AlloyDB failure.
    """
    logger.info("Ingest request received — concern_id=%s", request.concern_id)

    record = request.model_dump()
    result = await sync_new_corrective_action(record)

    if result.success:
        logger.info(
            "Ingest success — concern_id=%s alloydb_id=%s latency_ms=%.1f",
            request.concern_id,
            result.alloydb_id,
            result.latency_ms or 0,
        )
        return CorrectiveActionResponse(**result.to_api_response())

    reason = result.rejection_reason or ""
    logger.warning("Ingest rejected — concern_id=%s reason=%s", request.concern_id, reason)

    if "already exists" in reason:
        raise HTTPException(status_code=409, detail=result.to_api_response())
    if "Embedding" in reason or "AlloyDB insert" in reason:
        raise HTTPException(status_code=500, detail=result.to_api_response())
    if "AI quality" in reason:
        raise HTTPException(status_code=422, detail=result.to_api_response())
    raise HTTPException(status_code=400, detail=result.to_api_response())
