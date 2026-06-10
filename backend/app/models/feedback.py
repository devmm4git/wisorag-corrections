"""
Pydantic models — POST /corrective-actions/feedback

Feedback loop endpoint.
Coach actions: ACCEPT, REJECT, MODIFY.
- ACCEPT / REJECT: pure SQL UPDATE on feedback_score — no re-embedding.
- MODIFY: INSERT new record with fresh 768-dim embedding — feedback_score = 1.0.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class FeedbackAction(str, Enum):
    """Valid feedback actions from the Process Coach."""

    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    MODIFY = "MODIFY"


class FeedbackRequest(BaseModel):
    """Request model for POST /corrective-actions/feedback."""

    request_id: str = Field(..., description="request_id returned by /ai/recommend.")
    alloydb_id: int = Field(..., description="PK id of the specific AlloyDB record to update.")
    chunk_ids: list[str] = Field(
        ..., description="chunk_id values shown to the coach. One per source document."
    )
    action: FeedbackAction = Field(..., description="Coach decision: ACCEPT / REJECT / MODIFY.")
    modified_text: Optional[str] = Field(
        None, description="Required when action=MODIFY. Triggers new embedding + INSERT."
    )
    coach_cds_id: str = Field(..., description="Coach employee ID. Stored in BigQuery.")
    concern_id: str = Field(..., description="Original concern ID. Links to Tip Board event.")


class FeedbackResponse(BaseModel):
    """Response model for POST /corrective-actions/feedback."""

    status: str = Field(..., description="Result: 'recorded'.")
    action_applied: FeedbackAction
    new_chunk_id: Optional[str] = Field(
        None, description="For MODIFY only: chunk_id of the newly inserted record."
    )
    error: Optional[str] = None
    error_code: Optional[str] = None
