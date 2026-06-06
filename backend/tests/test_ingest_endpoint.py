"""
Unit tests — POST /corrective-actions/ingest

Task 3.2 — Ingest endpoint
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)

VALID_PAYLOAD = {
    "concern_id": "C_20240508_001",
    "concern_description": "LEFT REAR BLACKOUT TAPE DAMAGED during final assembly",
    "corrective_action": (
        "Verified tape adhesion at station 165, replaced tape on 3 units, adjusted to 45 PSI."
    ),
    "department": "PAINT",
    "product_line": "RANGER",
    "plant": "MAP",
    "severity": "A",
    "resolution_time_min": 18,
    "coach_cds_id": "CDS12345",
    "vin_number": "TLE19823",
}


def _mock_result(success: bool, reason: str = None) -> MagicMock:
    """Build a mock result object returned by sync_new_corrective_action."""
    result = MagicMock()
    result.success = success
    result.alloydb_id = 17 if success else None
    result.latency_ms = 6956.4 if success else None
    result.rejection_reason = reason
    result.to_api_response.return_value = {
        "success": success,
        "concern_id": "C_20240508_001",
        "alloydb_id": 17 if success else None,
        "embedding_dims": 768 if success else None,
        "latency_ms": 6956.4 if success else None,
        "message": "Corrective action synced successfully." if success else "Rejected.",
        "rejection_reason": reason,
    }
    return result


def test_ingest_success_201():
    """Valid payload returns 201 with alloydb_id and embedding_dims."""
    with patch(
        "backend.app.routers.corrective_actions.sync_new_corrective_action",
        new_callable=AsyncMock,
        return_value=_mock_result(True),
    ):
        response = client.post("/corrective-actions/ingest", json=VALID_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["alloydb_id"] == 17
    assert body["embedding_dims"] == 768


def test_ingest_missing_required_field_400():
    """Missing corrective_action returns 400."""
    payload = {**VALID_PAYLOAD}
    del payload["corrective_action"]

    response = client.post("/corrective-actions/ingest", json=payload)
    assert response.status_code == 422  # Pydantic L1 catches before router


def test_ingest_corrective_action_too_short_400():
    """corrective_action under 30 chars returns 422 from Pydantic."""
    payload = {**VALID_PAYLOAD, "corrective_action": "Too short"}
    response = client.post("/corrective-actions/ingest", json=payload)
    assert response.status_code == 422


def test_ingest_duplicate_409():
    """Duplicate concern_id returns 409."""
    with patch(
        "backend.app.routers.corrective_actions.sync_new_corrective_action",
        new_callable=AsyncMock,
        return_value=_mock_result(False, "Record already exists in AlloyDB"),
    ):
        response = client.post("/corrective-actions/ingest", json=VALID_PAYLOAD)

    assert response.status_code == 409


def test_ingest_embedding_failure_500():
    """Vertex AI failure returns 500."""
    with patch(
        "backend.app.routers.corrective_actions.sync_new_corrective_action",
        new_callable=AsyncMock,
        return_value=_mock_result(False, "Embedding generation failed: timeout"),
    ):
        response = client.post("/corrective-actions/ingest", json=VALID_PAYLOAD)

    assert response.status_code == 500


def test_ingest_response_schema():
    """Success response contains all required fields."""
    with patch(
        "backend.app.routers.corrective_actions.sync_new_corrective_action",
        new_callable=AsyncMock,
        return_value=_mock_result(True),
    ):
        response = client.post("/corrective-actions/ingest", json=VALID_PAYLOAD)

    body = response.json()
    required = {"success", "concern_id", "alloydb_id", "embedding_dims", "latency_ms", "message"}
    assert required.issubset(body.keys())
