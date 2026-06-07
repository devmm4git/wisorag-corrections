# backend/app/models/recommend.py
from pydantic import BaseModel, Field
from typing import Optional, List
import uuid


class RecommendRequest(BaseModel):
    """Request model for POST /ai/recommend."""

    model_config = {"json_schema_extra": {"example": {
        "plant": "MAP",
        "department": "PAINT",
        "product_line": "RANGER",
        "concern_description": "LEFT REAR BLACKOUT TAPE DAMAGED",
        "concern_id": "C_20240508_001",
        "collection_point": "16S LEFT REAR",
        "severity": "A",
        "charged_zone": "P TEAM 7",
        "vin_number": "TLE19823",
    }}}

    plant: str
    department: str
    product_line: str
    concern_description: str = Field(..., min_length=5)
    concern_id: str
    collection_point: Optional[str] = None
    severity: Optional[str] = None
    charged_zone: Optional[str] = None
    vin_number: Optional[str] = None


class SourceItem(BaseModel):
    """A single historical case used as source for the recommendation."""

    chunk_id: str
    similarity: float
    effective_score: float
    resolution_time_min: Optional[int] = None
    concern_description: Optional[str] = None
    corrective_action: Optional[str] = None


class RecommendResponse(BaseModel):
    """Response model for POST /ai/recommend."""

    model_config = {"json_schema_extra": {"example": {
        "recommendation": "Verify tape adhesion at station 16S...",
        "confidence_score": 0.87,
        "latency_ms": 3240,
        "fallback_scope": "LOCAL",
        "request_id": "req_abc123def456",
        "sources": [],
    }}}

    recommendation: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    latency_ms: int
    fallback_scope: str
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:12]}")
    sources: List[SourceItem]
