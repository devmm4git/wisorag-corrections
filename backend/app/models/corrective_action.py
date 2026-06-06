"""
Pydantic models — POST /corrective-actions/ingest

Validation levels:
    L1 — Required: concern_id, concern_description, corrective_action
    L2 — Quasi-required: department, product_line
    L3 — Optional: plant, severity, collection_point, charged_zone, resolution_time_min
    BigQuery only: coach_cds_id, vin_number (never written to AlloyDB)
"""

from typing import Optional

from pydantic import BaseModel, Field


class CorrectiveActionRequest(BaseModel):
    """Request model for POST /corrective-actions/ingest."""

    # L1 — Required
    concern_id: str = Field(..., description="Unique concern ID")
    concern_description: str = Field(..., description="Original concern text")
    corrective_action: str = Field(
        ...,
        min_length=30,
        description="Action taken by coach. Min 30 chars, min 5 words",
    )

    # L2 — Quasi-required (hard filters in retrieval)
    department: Optional[str] = Field(None, description="Manufacturing department")
    product_line: Optional[str] = Field(None, description="Vehicle product line")

    # L3 — Optional context
    plant: Optional[str] = None
    severity: Optional[str] = None
    collection_point: Optional[str] = None
    charged_zone: Optional[str] = None
    resolution_time_min: Optional[int] = None

    # BigQuery only — NOT stored in AlloyDB
    coach_cds_id: Optional[str] = None
    vin_number: Optional[str] = None


class CorrectiveActionResponse(BaseModel):
    """Response model for POST /corrective-actions/ingest."""

    success: bool
    concern_id: str
    alloydb_id: Optional[int] = None
    embedding_dims: Optional[int] = None
    latency_ms: Optional[float] = None
    message: str
    rejection_reason: Optional[str] = None
