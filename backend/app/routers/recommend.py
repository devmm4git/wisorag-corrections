# backend/app/routers/recommend.py
import logging
import uuid
from fastapi import APIRouter, HTTPException

from backend.app.models.recommend import RecommendRequest, RecommendResponse, SourceItem
from backend.rag.retriever import embed_query, search_similar
from backend.rag.llm_chain import build_prompt, call_gemini

logger = logging.getLogger("wiso-ai.recommend")
router = APIRouter(prefix="/ai", tags=["AI"])


@router.post("/recommend", response_model=RecommendResponse)
async def recommend(payload: RecommendRequest) -> RecommendResponse:
    """
    Generate an AI corrective action recommendation for a quality concern.
    Calls RAG retrieval + Gemini LLM. Latency target: < 5,000ms total.
    """
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    logger.info("recommend request_id=%s concern_id=%s", request_id, payload.concern_id)

    # Step 1: embed the concern query
    try:
        query_embedding = await embed_query(payload.concern_description)
    except Exception as e:
        logger.error("embed_query failed: %s", e)
        raise HTTPException(status_code=502, detail="Embedding service unavailable")

    # Step 2: retrieve similar historical cases
    try:
        results = await search_similar(
            query_vector=query_embedding,
            department=payload.department,
            product_line=payload.product_line,
            top_k=5,
        )
    except Exception as e:
        logger.error("search_similar failed: %s", e)
        raise HTTPException(status_code=502, detail="Vector search failed")

    if not results:
        raise HTTPException(
            status_code=404,
            detail="No similar historical cases found for this concern.",
        )

    # Step 3: build prompt + call Gemini
    prompt = build_prompt(
        concern_description=payload.concern_description,
        plant=payload.plant,
        department=payload.department,
        severity=payload.severity,
        top_k_results=results,
    )

    try:
        recommendation_text, latency_ms = call_gemini(prompt)
    except Exception as e:
        logger.error("Gemini call failed: %s", e)
        raise HTTPException(status_code=502, detail="LLM service unavailable")

    # Step 4: build sources list + confidence_score
    sources = [
        SourceItem(
            chunk_id=r.get("concern_id", "unknown"),
            similarity=round(r.get("similarity", 0.0), 4),
            effective_score=round(r.get("effective_score", 0.0), 4),
            resolution_time_min=r.get("mttr_minutes"),
            concern_description=r.get("concern_description"),
            corrective_action=r.get("corrective_action"),
        )
        for r in results
    ]

    confidence_score = round(
        sum(s.effective_score for s in sources) / len(sources), 4
    )

    return RecommendResponse(
        recommendation=recommendation_text,
        confidence_score=confidence_score,
        latency_ms=latency_ms,
        fallback_scope="LOCAL",
        request_id=request_id,
        sources=sources,
    )
