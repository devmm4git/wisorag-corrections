# backend/rag/llm_chain.py
import logging
import time
from typing import List, Dict, Any

import vertexai
from vertexai.generative_models import GenerativeModel

from backend.config.settings import settings

logger = logging.getLogger("wiso-ai.llm_chain")

PROMPT_TEMPLATE = """You are a manufacturing quality assistant. \
Based on similar historical cases, suggest a corrective action for this concern.

CONCERN: {concern_description}
PLANT: {plant} | DEPARTMENT: {department} | SEVERITY: {severity}

SIMILAR HISTORICAL CASES:
{top_k_results}

Provide a concise, actionable recommendation in 2-3 sentences.
End with: "Based on {n_cases} similar cases in {department}."
"""


def _format_cases(results: List[Dict[str, Any]]) -> str:
    """Format top-K retrieval results into prompt text."""
    lines = []
    for i, r in enumerate(results, 1):
        lines.append(
            f"Case {i}: {r.get('concern_description', '')} → "
            f"{r.get('corrective_action', '')} "
            f"(resolved in {r.get('mttr_minutes', 'N/A')} min)"
        )
    return "\n".join(lines)


def build_prompt(
    concern_description: str,
    plant: str,
    department: str,
    severity: str,
    top_k_results: List[Dict[str, Any]],
) -> str:
    """Build the Gemini prompt from concern data and retrieved cases."""
    return PROMPT_TEMPLATE.format(
        concern_description=concern_description,
        plant=plant,
        department=department,
        severity=severity or "N/A",
        top_k_results=_format_cases(top_k_results),
        n_cases=len(top_k_results),
    )


def call_gemini(prompt: str) -> tuple[str, int]:
    """
    Call Gemini 3.5 Flash via Agent Platform (Vertex AI v1beta1).
    Uses Application Default Credentials via rag-api-sa.
    Latency budget: < 3,000ms.
    """
    vertexai.init(
        project=settings.vertex_ai_project,
        location=settings.vertex_ai_location,
        api_endpoint="aiplatform.googleapis.com",
    )
    model = GenerativeModel("gemini-3.5-flash")

    start = time.monotonic()
    response = model.generate_content(prompt)
    latency_ms = int((time.monotonic() - start) * 1000)

    text = response.text.strip()
    logger.info("Gemini 3.5 Flash responded in %dms", latency_ms)
    return text, latency_ms
