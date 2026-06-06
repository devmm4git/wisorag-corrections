"""
Unit tests — POST /corrective-actions/feedback

Task 3.4 — Feedback endpoint
"""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app=app)

VALID_ACCEPT = {
    "request_id": "req_20240508_131523_abc123",
    "chunk_ids": ["MAP_PAINT_RANGER_20241101_C003"],
    "action": "ACCEPT",
    "coach_cds_id": "CDS12345",
    "concern_id": "C_20240508_001",
}

VALID_REJECT = {**VALID_ACCEPT, "action": "REJECT"}

VALID_MODIFY = {
    **VALID_ACCEPT,
    "action": "MODIFY",
    "modified_text": (
        "Inspector verified tape at station 16S, adjusted applicator to 40 PSI. "
        "Confirmed adhesion on 5 consecutive units."
    ),
}


def test_feedback_accept_200():
    """ACCEPT action returns 200 with status=recorded."""
    with (
        patch(
            "backend.app.routers.feedback.apply_accept",
            new_callable=AsyncMock,
            return_value={"id": 1, "feedback_score": 0.9},
        ),
        patch(
            "backend.app.routers.feedback.log_feedback_to_bigquery",
            new_callable=AsyncMock,
        ),
    ):
        response = client.post("/corrective-actions/feedback", json=VALID_ACCEPT)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "recorded"
    assert body["action_applied"] == "ACCEPT"
    assert body["new_chunk_id"] is None


def test_feedback_reject_200():
    """REJECT action returns 200 with status=recorded."""
    with (
        patch(
            "backend.app.routers.feedback.apply_reject",
            new_callable=AsyncMock,
            return_value={"id": 1, "feedback_score": 0.4},
        ),
        patch(
            "backend.app.routers.feedback.log_feedback_to_bigquery",
            new_callable=AsyncMock,
        ),
    ):
        response = client.post("/corrective-actions/feedback", json=VALID_REJECT)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "recorded"
    assert body["action_applied"] == "REJECT"


def test_feedback_modify_200():
    """MODIFY action returns 200 with new_chunk_id."""
    with (
        patch(
            "backend.app.routers.feedback.apply_modify",
            new_callable=AsyncMock,
            return_value="C_20240508_001_MOD_CDS12345_42",
        ),
        patch(
            "backend.app.routers.feedback.log_feedback_to_bigquery",
            new_callable=AsyncMock,
        ),
    ):
        response = client.post("/corrective-actions/feedback", json=VALID_MODIFY)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "recorded"
    assert body["action_applied"] == "MODIFY"
    assert body["new_chunk_id"] == "C_20240508_001_MOD_CDS12345_42"


def test_feedback_modify_missing_text_400():
    """MODIFY without modified_text returns 400."""
    payload = {**VALID_ACCEPT, "action": "MODIFY"}
    response = client.post("/corrective-actions/feedback", json=payload)
    assert response.status_code == 400


def test_feedback_invalid_action_422():
    """Invalid action value returns 422 from Pydantic."""
    payload = {**VALID_ACCEPT, "action": "APPROVE"}
    response = client.post("/corrective-actions/feedback", json=payload)
    assert response.status_code == 422


def test_feedback_chunk_not_found_404():
    """concern_id not found in AlloyDB returns 404."""
    with (
        patch(
            "backend.app.routers.feedback.apply_accept",
            new_callable=AsyncMock,
            side_effect=RuntimeError("concern_id not found in AlloyDB: C_20240508_001"),
        ),
        patch(
            "backend.app.routers.feedback.log_feedback_to_bigquery",
            new_callable=AsyncMock,
        ),
    ):
        response = client.post("/corrective-actions/feedback", json=VALID_ACCEPT)

    assert response.status_code == 404


def test_feedback_alloydb_failure_500():
    """AlloyDB failure returns 500."""
    with (
        patch(
            "backend.app.routers.feedback.apply_accept",
            new_callable=AsyncMock,
            side_effect=RuntimeError("AlloyDB UPDATE failed: connection timeout"),
        ),
        patch(
            "backend.app.routers.feedback.log_feedback_to_bigquery",
            new_callable=AsyncMock,
        ),
    ):
        response = client.post("/corrective-actions/feedback", json=VALID_ACCEPT)

    assert response.status_code == 500


def test_feedback_missing_required_field_422():
    """Missing coach_cds_id returns 422 from Pydantic."""
    payload = {**VALID_ACCEPT}
    del payload["coach_cds_id"]
    response = client.post("/corrective-actions/feedback", json=payload)
    assert response.status_code == 422
