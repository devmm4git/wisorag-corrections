"""
Pydantic models — POST /corrective-actions/search

RAG retrieval endpoint.
Receives a concern query, generates embedding, retrieves top-K
similar corrective actions from AlloyDB using HNSW cosine search.
"""

from typing import Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """Request model for POST /corrective-actions/search."""

    # Required — hard filters (WHERE clause in AlloyDB)
    department: str = Field(..., description="Manufacturing department. Hard filter.")
    product_line: str = Field(..., description="Vehicle product line. Hard filter.")
    concern_description: str = Field(
        ..., description="Concern text. Used to generate the query embedding."
    )

    # Optional filters
    plant: Optional[str] = Field(None, description="Plant identifier. Optional filter.")
    top_k: int = Field(5, ge=1, le=20, description="Number of results to return. Default 5.")


class SearchResult(BaseModel):
    """Single retrieved result from AlloyDB."""

    alloydb_id: int = Field(..., description="Primary key in corrective_actions_vectors.")
    concern_id: str
    department: str
    product_line: str
    concern_description: str
    corrective_action: str
    similarity: float = Field(..., description="Cosine similarity score. 0.0 to 1.0.")
    feedback_score: float = Field(..., description="Feedback weight. 0.0 to 1.0.")
    effective_score: float = Field(
        ..., description="similarity * feedback_score. Used for ranking."
    )
    mttr_minutes: Optional[int] = None


class SearchResponse(BaseModel):
    """Response model for POST /corrective-actions/search."""

    success: bool
    query: str = Field(..., description="The concern_description used as query.")
    results: list[SearchResult]
    result_count: int
    latency_ms: float
    message: str
