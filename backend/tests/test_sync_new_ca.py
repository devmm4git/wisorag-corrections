"""
WISO-AI — Unit Tests: Continuous Sync Pipeline
Tests sync_new_corrective_action() without real DB or AI calls.

Run: pytest backend/tests/test_sync_new_ca.py -v
"""
import pytest

from backend.pipelines.sync_new_ca import (
    sync_new_corrective_action,
    build_chunk_text,
    SyncResult,
)


# ── Test build_chunk_text ──────────────────────────────────────────────────────
def test_build_chunk_text_correct_format():
    record = {
        "concern_description": "Paint run on left door",
        "corrective_action": "Adjusted gun pressure to 38 PSI",
        "department": "PAINT",  # Should NOT appear in chunk_text
    }
    result = build_chunk_text(record)
    assert "Concern: Paint run on left door" in result
    assert "Corrective Action: Adjusted gun pressure to 38 PSI" in result
    assert "PAINT" not in result  # ADR-002: no metadata in embedding


def test_build_chunk_text_strips_whitespace():
    record = {
        "concern_description": "  Paint run  ",
        "corrective_action": "  Adjusted pressure  ",
    }
    result = build_chunk_text(record)
    assert "Concern: Paint run" in result
    assert "Corrective Action: Adjusted pressure" in result


# ── Test SyncResult ────────────────────────────────────────────────────────────
def test_sync_result_success_api_response():
    result = SyncResult(
        success=True,
        concern_id="C099",
        alloydb_id=42,
        embedding_dims=768,
        latency_ms=1250.5
    )
    response = result.to_api_response()
    assert response["success"] is True
    assert response["alloydb_id"] == 42
    assert response["embedding_dims"] == 768


def test_sync_result_failure_api_response():
    result = SyncResult(
        success=False,
        concern_id="C099",
        rejection_reason="Text too short"
    )
    response = result.to_api_response()
    assert response["success"] is False
    assert response["rejection_reason"] == "Text too short"


# ── Test sync_new_corrective_action ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_rejects_missing_required_fields():
    record = {
        "concern_id": "C099",
        "department": "PAINT",
        # Missing concern_description and corrective_action
    }
    result = await sync_new_corrective_action(record)
    assert result.success is False
    assert "concern_description" in result.rejection_reason or \
           "corrective_action" in result.rejection_reason


@pytest.mark.asyncio
async def test_rejects_short_corrective_action():
    record = {
        "concern_id": "C099",
        "department": "PAINT",
        "product_line": "RANGER",
        "concern_description": "Paint run on door",
        "corrective_action": "ok",  # Too short
    }
    result = await sync_new_corrective_action(record)
    assert result.success is False
