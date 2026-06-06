"""
Router — POST /corrective-actions/feedback

Feedback loop endpoint.
Milestone: M3 — FastAPI Backend & RAG API
Task: 3.4
Auth: Service Account rag-api-sa@ragai-staging.iam.gserviceaccount.com
"""

import logging

from fastapi import APIRouter, HTTPException

from backend.app.models.feedback import FeedbackAction, FeedbackRequest, FeedbackResponse
from backend.rag.feedback_handler import (
    apply_accept,
    apply_modify,
    apply_reject,
    log_feedback_to_bigquery,
)

logger = logging.getLogger("wiso-ai.routers.feedback")

router = APIRouter(prefix="/corrective-actions", tags=["corrective-actions"])


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=200,
    summary="Record coach feedback on AI recommendation",
    description=(
        "Records ACCEPT, REJECT, or MODIFY feedback from the Process Coach. "
        "Updates AlloyDB retrieval weights and logs to BigQuery. "
        "No re-embedding for ACCEPT or REJECT. "
        "MODIFY triggers new 768-dim embedding + INSERT."
    ),
)
async def record_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """Process coach feedback and update AlloyDB accordingly.

    Args:
        request: Feedback payload with action, chunk_ids, and coach info.

    Returns:
        FeedbackResponse: Confirmation with action_applied and optional new_chunk_id.

    Raises:
        HTTPException 400: MODIFY action missing modified_text.
        HTTPException 404: concern_id not found in AlloyDB.
        HTTPException 500: AlloyDB UPDATE/INSERT or Vertex AI failure.
    """
    logger.info(
        "Feedback received — concern_id=%s action=%s coach=%s",
        request.concern_id, request.action, request.coach_cds_id,
    )

    # Validate MODIFY requires modified_text
    if request.action == FeedbackAction.MODIFY and not request.modified_text:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "modified_text is required when action=MODIFY.",
                "error_code": "MODIFY_REQUIRES_TEXT",
            },
        )

    new_chunk_id = None

    try:
        if request.action == FeedbackAction.ACCEPT:
            await apply_accept(request.concern_id)

        elif request.action == FeedbackAction.REJECT:
            await apply_reject(request.concern_id)

        elif request.action == FeedbackAction.MODIFY:
            new_chunk_id = await apply_modify(
                concern_id=request.concern_id,
                modified_text=request.modified_text,
                coach_cds_id=request.coach_cds_id,
            )

    except RuntimeError as exc:
        error_msg = str(exc)
        if "not found" in error_msg:
            raise HTTPException(
                status_code=404,
                detail={"error": error_msg, "error_code": "CHUNK_NOT_FOUND"},
            )
        raise HTTPException(
            status_code=500,
            detail={"error": error_msg, "error_code": "ALLOYDB_UPDATE_ERROR"},
        )

    # Log to BigQuery (non-blocking)
    await log_feedback_to_bigquery(
        request_id=request.request_id,
        concern_id=request.concern_id,
        coach_cds_id=request.coach_cds_id,
        action=request.action.value,
        chunk_ids=request.chunk_ids,
        modified_text=request.modified_text,
    )

    logger.info(
        "Feedback recorded — concern_id=%s action=%s new_chunk_id=%s",
        request.concern_id, request.action, new_chunk_id,
    )

    return FeedbackResponse(
        status="recorded",
        action_applied=request.action,
        new_chunk_id=new_chunk_id,
    )
