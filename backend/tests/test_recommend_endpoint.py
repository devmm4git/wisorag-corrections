# backend/tests/test_recommend_endpoint.py
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

VALID_PAYLOAD = {
    "plant": "MAP",
    "department": "PAINT",
    "product_line": "RANGER",
    "concern_description": "LEFT REAR BLACKOUT TAPE DAMAGED",
    "concern_id": "C_TEST_001",
    "severity": "A",
}

MOCK_RESULTS = [
    {
        "concern_id": "MAP_PAINT_001",
        "concern_description": "Tape damaged at rear",
        "corrective_action": "Replace tape at 16S station",
        "similarity": 0.91,
        "effective_score": 0.87,
        "mttr_minutes": 18,
    }
]


@patch("backend.app.routers.recommend.embed_query", new_callable=AsyncMock)
@patch("backend.app.routers.recommend.search_similar", new_callable=AsyncMock)
@patch("backend.app.routers.recommend.call_gemini")
def test_recommend_success(mock_gemini, mock_search, mock_embed):
    mock_embed.return_value = [0.1] * 768
    mock_search.return_value = MOCK_RESULTS
    mock_gemini.return_value = ("Replace tape at 16S. Based on 1 similar cases in PAINT.", 1200)

    response = client.post("/ai/recommend", json=VALID_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert "recommendation" in data
    assert "confidence_score" in data
    assert "sources" in data
    assert data["latency_ms"] == 1200


@patch("backend.app.routers.recommend.embed_query", new_callable=AsyncMock)
@patch("backend.app.routers.recommend.search_similar", new_callable=AsyncMock)
def test_recommend_no_results(mock_search, mock_embed):
    mock_embed.return_value = [0.1] * 768
    mock_search.return_value = []

    response = client.post("/ai/recommend", json=VALID_PAYLOAD)
    assert response.status_code == 404


def test_recommend_missing_concern_description():
    payload = {**VALID_PAYLOAD}
    del payload["concern_description"]
    response = client.post("/ai/recommend", json=payload)
    assert response.status_code == 422


def test_recommend_missing_plant():
    payload = {**VALID_PAYLOAD}
    del payload["plant"]
    response = client.post("/ai/recommend", json=payload)
    assert response.status_code == 422


@patch("backend.app.routers.recommend.embed_query", new_callable=AsyncMock)
def test_recommend_embed_failure(mock_embed):
    mock_embed.side_effect = Exception("Vertex AI timeout")
    response = client.post("/ai/recommend", json=VALID_PAYLOAD)
    assert response.status_code == 502


@patch("backend.app.routers.recommend.embed_query", new_callable=AsyncMock)
@patch("backend.app.routers.recommend.search_similar", new_callable=AsyncMock)
@patch("backend.app.routers.recommend.call_gemini")
def test_recommend_gemini_failure(mock_gemini, mock_search, mock_embed):
    mock_embed.return_value = [0.1] * 768
    mock_search.return_value = MOCK_RESULTS
    mock_gemini.side_effect = Exception("Gemini unavailable")
    response = client.post("/ai/recommend", json=VALID_PAYLOAD)
    assert response.status_code == 502
