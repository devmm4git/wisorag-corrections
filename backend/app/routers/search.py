"""
Router — POST /corrective-actions/search

RAG retrieval endpoint.
Milestone: M3 — FastAPI Backend & RAG API
Task: 3.3
Auth: Service Account rag-api-sa@ragai-staging.iam.gserviceaccount.com
"""

import logging
import time

from fastapi import APIRouter, HTTPException

from backend.app.models.search import SearchRequest, SearchResponse, SearchResult
from backend.rag.retriever import embed_query, search_similar

logger = logging.getLogger("wiso-ai.routers.search")

router = APIRouter(prefix="/corrective-actions", tags=["corrective-actions"])


@router.post(
    "/search",
    response_model=SearchResponse,
    status_code=200,
    summary="RAG vector search — retrieve similar corrective actions",
    description=(
        "Generates a query embedding from concern_description and retrieves "
        "top-K similar corrective actions from AlloyDB using HNSW cosine search. "
        "Hard filters: department + product_line."
    ),
)
async def search_corrective_actions(request: SearchRequest) -> SearchResponse:
    """Execute RAG retrieval for a given concern.

    Args:
        request: Search parameters including department, product_line and concern text.

    Returns:
        SearchResponse: Top-K results ranked by cosine similarity.

    Raises:
        HTTPException 400: Missing required fields.
        HTTPException 404: No results found after filtering.
        HTTPException 500: Vertex AI or AlloyDB failure.
    """
    start = time.time()
    logger.info(
        "Search request — dept=%s product_line=%s",
        request.department, request.product_line,
    )

    # Generate query embedding
    try:
        query_vector = await embed_query(request.concern_description)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Retrieve from AlloyDB
    try:
        rows = await search_similar(
            department=request.department,
            product_line=request.product_line,
            query_vector=query_vector,
            plant=request.plant,
            top_k=request.top_k,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="No similar corrective actions found for the given filters.",
        )

    latency_ms = round((time.time() - start) * 1000, 2)
    results = [SearchResult(**row) for row in rows]

    logger.info(
        "Search success — results=%d latency_ms=%.1f",
        len(results), latency_ms,
    )

    return SearchResponse(
        success=True,
        query=request.concern_description,
        results=results,
        result_count=len(results),
        latency_ms=latency_ms,
        message=f"Found {len(results)} similar corrective actions.",
    )
