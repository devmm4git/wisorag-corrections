"""
Unit tests — GET /ai/health

Task 3.1 — FastAPI app setup + health endpoint
"""

from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from backend.app.main import app

client = TestClient(app)


def test_health_healthy():
    """Health endpoint returns 200 and status=healthy when AlloyDB is up."""
    with patch(
        "backend.app.routers.health.alloydb_ping",
        new_callable=AsyncMock,
    ):
        response = client.get("/ai/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["alloydb"] == "connected"
    assert body["vertex_ai"] == "reachable"
    assert isinstance(body["uptime_seconds"], int)


def test_health_unhealthy_alloydb():
    """Health endpoint returns unhealthy when AlloyDB is unreachable."""
    with patch(
        "backend.app.routers.health.alloydb_ping",
        new_callable=AsyncMock,
        side_effect=Exception("Connection refused"),
    ):
        response = client.get("/ai/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["alloydb"] == "unreachable"


def test_health_response_schema():
    """Health response contains all required fields."""
    with patch(
        "backend.app.routers.health.alloydb_ping",
        new_callable=AsyncMock,
    ):
        response = client.get("/ai/health")

    body = response.json()
    required_fields = {
        "status", "alloydb", "vertex_ai",
        "latency_p95_ms", "active_instances", "uptime_seconds",
    }
    assert required_fields.issubset(body.keys())
