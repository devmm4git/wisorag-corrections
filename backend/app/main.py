"""
WISO-AI FastAPI application entrypoint.

Milestone 3 — FastAPI Backend & RAG API
GCP Project: ragai-staging
Repo: github.com/devmm4git/wisorag-corrections
"""

import logging

from fastapi import FastAPI

from backend.app.routers import health, corrective_actions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("wiso-ai.main")

app = FastAPI(
    title="WISO-AI API",
    description=(
        "RAG-based corrective action recommendation system for WISOHUB. "
        "Built on Vertex AI (text-embedding-004 + Gemini) and AlloyDB pgvector."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Routers ───────────────────────────────────────────────────────────────
app.include_router(health.router)
app.include_router(corrective_actions.router)
# Task 3.2 → corrective_actions.ingest
# Task 3.3 → corrective_actions.search
# Task 3.4 → corrective_actions.feedback

logger.info("WISO-AI API started — Swagger at /docs")
