# backend/rag/llm_chain.py
import logging
import time
from typing import List, Dict, Any

import google.generativeai as genai

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
    Call Gemini via google-generativeai SDK using Application Default Credentials.
    Targets Vertex AI backend — uses GCP billing, no API key needed.
    Latency budget: < 3,000ms.
    """
    genai.configure(
        api_key=settings.gemini_api_key,
    )

    model = genai.GenerativeModel("gemini-2.0-flash")

    start = time.monotonic()
    response = model.generate_content(prompt)
    latency_ms = int((time.monotonic() - start) * 1000)

    text = response.text.strip()
    logger.info("Gemini responded in %dms", latency_ms)
    return text, latency_ms
