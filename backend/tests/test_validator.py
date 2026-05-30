"""
WISO-AI — Unit Tests: Corrective Action Validator
Tests Level 1 (statistical) only — no AI calls in unit tests.

Run: pytest backend/tests/ -v
"""
import pytest
import asyncio
from backend.rag.corrective_action_validator import (
    CorrectiveActionValidator,
    ValidatorConfig,
    ValidationStatus,
)


# ── Config for tests — AI disabled ────────────────────────────────────────────
TEST_CONFIG = ValidatorConfig(
    ai_enabled=False,   # Never call Gemini in unit tests
    min_chars=30,
    min_words=5,
)


@pytest.fixture
def validator():
    return CorrectiveActionValidator(config=TEST_CONFIG)


# ── Level 1: Too short ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_rejects_empty_text(validator):
    result = await validator.validate("", concern_id="TEST-001")
    assert result.is_valid is False
    assert result.status == ValidationStatus.REJECTED_TOO_SHORT


@pytest.mark.asyncio
async def test_rejects_single_word(validator):
    result = await validator.validate("ok", concern_id="TEST-002")
    assert result.is_valid is False
    assert result.status == ValidationStatus.REJECTED_TOO_SHORT


@pytest.mark.asyncio
async def test_rejects_vague_short_phrase(validator):
    result = await validator.validate("ya quedo", concern_id="TEST-003")
    assert result.is_valid is False


# ── Level 1: Repetition ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_rejects_character_repetition(validator):
    result = await validator.validate(
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        concern_id="TEST-004"
    )
    assert result.is_valid is False


# ── Level 3: Business rules ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_rejects_symbol_noise(validator):
    result = await validator.validate(
        "!!!??? *** @@@ ### $$$",
        concern_id="TEST-005"
    )
    assert result.is_valid is False


# ── Valid cases ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_accepts_english_corrective_action(validator):
    result = await validator.validate(
        "Adjusted spray gun pressure from 45 to 38 PSI. "
        "Verified adhesion on 5 consecutive units. "
        "Root cause: worn nozzle tip replaced.",
        concern_id="C006"
    )
    assert result.is_valid is True
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_accepts_spanish_corrective_action(validator):
    result = await validator.validate(
        "Se calibró la presión del pistola de pintura de 45 a 38 PSI. "
        "Se verificó la adhesión en 5 unidades consecutivas. "
        "Causa raíz: boquilla desgastada reemplazada.",
        concern_id="C007"
    )
    assert result.is_valid is True


@pytest.mark.asyncio
async def test_result_contains_concern_id(validator):
    result = await validator.validate(
        "Replaced worn tape applicator nozzle on station P-165. "
        "Adjusted pressure from 45 to 38 PSI. Verified adhesion.",
        concern_id="C001"
    )
    assert result.concern_id == "C001"


@pytest.mark.asyncio
async def test_valid_result_has_api_response_format(validator):
    result = await validator.validate(
        "Replaced worn tape applicator nozzle on station P-165. "
        "Adjusted pressure from 45 to 38 PSI. Verified adhesion.",
        concern_id="C001"
    )
    api_response = result.to_api_response()
    assert "valid" in api_response
    assert "score" in api_response
    assert "reason" in api_response
    assert "status" in api_response
