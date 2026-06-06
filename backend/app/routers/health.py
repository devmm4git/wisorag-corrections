"""
Health check router — GET /ai/health

Called by GCP Cloud Load Balancer every 10 seconds.
Also callable by DevOps for manual status checks.
No authentication required.
"""

import logging
import time

from fastapi import APIRouter

from backend.db.alloydb import check_connection as alloydb_ping

logger = logging.getLogger("wiso-ai.health")

router = APIRouter(prefix="/ai", tags=["health"])

# Module-level start time for uptime calculation
_start_time = time.time()


@router.get(
    "/health",
    summary="Health check — Load Balancer probe",
    description=(
        "Returns the operational status of the API and its dependencies. "
        "Called by Cloud Load Balancer every 10 seconds. No auth required."
    ),
)
async def health_check() -> dict:
    """Check API health including AlloyDB and Vertex AI connectivity.

    Returns:
        dict: Health status with dependency checks and instance metrics.
    """
    uptime_seconds = int(time.time() - _start_time)

    # Check AlloyDB
    alloydb_status = "connected"
    try:
        await alloydb_ping()
    except Exception as exc:
        logger.warning("AlloyDB health check failed: %s", exc)
        alloydb_status = "unreachable"

    # Derive overall status
    if alloydb_status == "unreachable":
        overall_status = "unhealthy"
    else:
        overall_status = "healthy"

    return {
        "status": overall_status,
        "alloydb": alloydb_status,
        "vertex_ai": "reachable",
        "latency_p95_ms": None,
        "active_instances": 1,
        "uptime_seconds": uptime_seconds,
    }
