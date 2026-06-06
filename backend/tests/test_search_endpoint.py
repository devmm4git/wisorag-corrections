"""
Unit tests — POST /corrective-actions/search

Task 3.3 — RAG retrieval endpoint
"""

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app=app)

VALID_PAYLOAD = {
    "department": "PAINT",
    "product_line": "RANGER",
    "concern_description": "LEFT REAR BLACKOUT TAPE DAMAGED during final assembly",
    "plant": "MAP",
    "top_k": 3,
}

MOCK_ROWS = [
    {
        "alloydb_id": 1,
        "concern_id": "C_20240101_001",
        "department": "PAINT",
        "product_line": "RANGER",
        "concern_description": "Tape damaged on left rear panel",
        "corrective_action": "Replaced tape at station 16S, adjusted PSI to 45.",
        "similarity": 0.91,
        "feedback_score": 0.85,
        "effective_score": 0.7735,
        "mttr_minutes": 18,
    },
]


def test_search_success_200():
    """Valid payload returns 200 with results."""
    with (
        patch(
            "backend.app.routers.search.embed_query",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ),
        patch(
            "backend.app.routers.search.search_similar",
            new_callable=AsyncMock,
            return_value=MOCK_ROWS,
        ),
    ):
        response = client.post("/corrective-actions/search", json=VALID_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["result_count"] == 1
    assert len(body["results"]) == 1


def test_search_result_schema():
    """Result contains all required fields including effective_score."""
    with (
        patch(
            "backend.app.routers.search.embed_query",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ),
        patch(
            "backend.app.routers.search.search_similar",
            new_callable=AsyncMock,
            return_value=MOCK_ROWS,
        ),
    ):
        response = client.post("/corrective-actions/search", json=VALID_PAYLOAD)

    result = response.json()["results"][0]
    required = {
        "alloydb_id", "concern_id", "department", "product_line",
        "concern_description", "corrective_action",
        "similarity", "feedback_score", "effective_score",
    }
    assert required.issubset(result.keys())


def test_search_no_results_404():
    """Empty results from AlloyDB returns 404."""
    with (
        patch(
            "backend.app.routers.search.embed_query",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ),
        patch(
            "backend.app.routers.search.search_similar",
            new_callable=AsyncMock,
            return_value=[],
        ),
    ):
        response = client.post("/corrective-actions/search", json=VALID_PAYLOAD)

    assert response.status_code == 404


def test_search_embedding_failure_500():
    """Vertex AI failure returns 500."""
    with patch(
        "backend.app.routers.search.embed_query",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Embedding generation failed: timeout"),
    ):
        response = client.post("/corrective-actions/search", json=VALID_PAYLOAD)

    assert response.status_code == 500


def test_search_alloydb_failure_500():
    """AlloyDB failure returns 500."""
    with (
        patch(
            "backend.app.routers.search.embed_query",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ),
        patch(
            "backend.app.routers.search.search_similar",
            new_callable=AsyncMock,
            side_effect=RuntimeError("AlloyDB search failed: connection timeout"),
        ),
    ):
        response = client.post("/corrective-actions/search", json=VALID_PAYLOAD)

    assert response.status_code == 500


def test_search_missing_required_field_422():
    """Missing department returns 422 from Pydantic."""
    payload = {**VALID_PAYLOAD}
    del payload["department"]
    response = client.post("/corrective-actions/search", json=payload)
    assert response.status_code == 422


def test_search_top_k_default():
    """top_k defaults to 5 when not provided."""
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "top_k"}
    with (
        patch(
            "backend.app.routers.search.embed_query",
            new_callable=AsyncMock,
            return_value=[0.1] * 768,
        ),
        patch(
            "backend.app.routers.search.search_similar",
            new_callable=AsyncMock,
            return_value=MOCK_ROWS,
        ) as mock_search,
    ):
        client.post("/corrective-actions/search", json=payload)
        call_kwargs = mock_search.call_args.kwargs
        assert call_kwargs["top_k"] == 5
