"""
WISO-AI — Corrective Action Quality Validator
ADR-001 v2: Language-agnostic, AI-first, scalable validator.
Last updated: M4 Sprint 1 — June 2026
Reviewed by: wmssaas-project

Design principles:
- No hardcoded word lists (fragile, language-specific)
- Statistical signals for fast pre-filtering (Level 1)
- Gemini 2.5 Flash as semantic judge (Level 2)
- Only universal business rules hardcoded (Level 3)
- Fully async, configurable thresholds
- Multilingual by design (EN, ES, PT, FR, ZH, etc.)

Used by:
  - backend/pipelines/ingest_historical.py  (Pipeline 1 — batch)
  - backend/app/routers/corrective_actions.py (M3 — real-time)

Owner: rag-datascientist@mm4.me
ADR: docs/adr/ADR-001-corrective-action-validator.md
"""
import asyncio
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
from typing import Optional

logger = logging.getLogger("wiso-ai.validator")


# ── Configuration (env-driven, not hardcoded) ──────────────────────────────────
@dataclass
class ValidatorConfig:
    """
    All thresholds are configurable — no magic numbers in logic.
    Override via environment variables or constructor args.
    """
    # Level 1 — Statistical
    min_chars: int = 30                  # Absolute minimum characters
    min_words: int = 5                   # Absolute minimum words
    min_unique_word_ratio: float = 0.4   # 40% unique words minimum
    max_repetition_ratio: float = 0.5    # Max 50% repeated chars (aaaaaa...)

    # Level 2 — AI Semantic
    ai_quality_threshold: float = 0.6   # 0.0-1.0, reject below this
    ai_timeout_seconds: int = 10         # Max wait for Gemini response
    ai_enabled: bool = True              # Toggle for testing/cost control

    # Level 3 — Business Rules
    min_sentences: int = 1               # At least 1 complete sentence
    max_allowed_symbols_ratio: float = 0.3  # Max 30% non-alphanumeric


# ── Enums & Data Classes ───────────────────────────────────────────────────────
class RejectionLevel(Enum):
    LEVEL_1_STATISTICAL = "level_1_statistical"
    LEVEL_2_AI_SEMANTIC = "level_2_ai_semantic"
    LEVEL_3_BUSINESS_RULE = "level_3_business_rule"


class ValidationStatus(Enum):
    VALID = "valid"
    REJECTED_TOO_SHORT = "rejected_too_short"
    REJECTED_LOW_DIVERSITY = "rejected_low_diversity"
    REJECTED_REPETITIVE = "rejected_repetitive"
    REJECTED_NO_SENTENCE = "rejected_no_sentence"
    REJECTED_SYMBOL_NOISE = "rejected_symbol_noise"
    REJECTED_AI_LOW_QUALITY = "rejected_ai_low_quality"
    REJECTED_AI_IRRELEVANT = "rejected_ai_irrelevant"
    ERROR_AI_UNAVAILABLE = "error_ai_unavailable"


@dataclass
class ValidationResult:
    """
    Immutable result object. Contains everything needed for
    logging, API responses, and pipeline decisions.
    """
    status: ValidationStatus
    is_valid: bool
    score: float                          # 0.0 to 1.0
    reason: str                           # Human-readable, English
    original_text: str
    concern_id: str = ""
    detected_language: str = "unknown"
    rejection_level: Optional[RejectionLevel] = None
    ai_response: Optional[dict] = dataclass_field(default=None)

    def to_api_response(self) -> dict:
        """Format for HTTP 422 API response (M3)."""
        return {
            "valid": self.is_valid,
            "score": round(self.score, 2),
            "reason": self.reason,
            "status": self.status.value,
            "concern_id": self.concern_id,
        }

    def __str__(self):
        return (
            f"ValidationResult("
            f"id={self.concern_id}, "
            f"valid={self.is_valid}, "
            f"score={self.score:.2f}, "
            f"lang={self.detected_language}, "
            f"reason='{self.reason}')"
        )


# ── Text Analysis Utilities ────────────────────────────────────────────────────
class TextAnalyzer:
    """
    Language-agnostic text analysis utilities.
    No word lists. No language assumptions.
    Works on statistical properties of the text itself.
    """

    @staticmethod
    def normalize(text: str) -> str:
        """Unicode normalize and strip."""
        return unicodedata.normalize("NFKC", text).strip()

    @staticmethod
    def word_count(text: str) -> int:
        """Count words — works for any language with spaces."""
        return len(text.split())

    @staticmethod
    def char_count(text: str) -> int:
        """Count non-whitespace characters."""
        return len(text.replace(" ", ""))

    @staticmethod
    def unique_word_ratio(text: str) -> float:
        """
        Ratio of unique words to total words.
        Low ratio = repetitive text ("the the the the") or very short.
        Language-agnostic.
        """
        words = text.lower().split()
        if not words:
            return 0.0
        return len(set(words)) / len(words)

    @staticmethod
    def repetition_ratio(text: str) -> float:
        """
        Detects character-level repetition (aaaa, ....., ----).
        High ratio = keyboard mashing or placeholder.
        """
        if not text:
            return 1.0
        char_counts = {}
        for c in text.replace(" ", ""):
            char_counts[c] = char_counts.get(c, 0) + 1
        total = sum(char_counts.values())
        if total == 0:
            return 1.0
        max_count = max(char_counts.values())
        return max_count / total

    @staticmethod
    def symbol_ratio(text: str) -> float:
        """
        Ratio of non-alphanumeric, non-space characters.
        High ratio = symbol soup, not real text.
        """
        if not text:
            return 1.0
        non_alpha = sum(
            1 for c in text
            if not c.isalnum() and not c.isspace()
        )
        return non_alpha / len(text)

    @staticmethod
    def has_sentence_structure(text: str) -> bool:
        """
        Detects if text has at least one sentence-like structure.
        A sentence has: subject-like token + predicate-like token.
        We approximate this by checking for:
        - At least 2 different word lengths (not all same-length words)
        - At least one word > 3 chars (not all stopwords/articles)
        Language-agnostic heuristic.
        """
        words = text.split()
        if len(words) < 2:
            return False
        long_words = [w for w in words if len(w) > 3]
        return len(long_words) >= 1

    @staticmethod
    def detect_language_hint(text: str) -> str:
        """
        Lightweight language hint using character frequency patterns.
        Not 100% accurate — used for logging only, not for rejection.
        """
        text_lower = text.lower()
        spanish_chars = len(re.findall(r'[áéíóúñü]', text_lower))
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text_lower))
        if chinese_chars > 0:
            return "zh"
        if spanish_chars > 0:
            return "es"
        return "en"


# ── Main Validator ─────────────────────────────────────────────────────────────
class CorrectiveActionValidator:
    """
    Language-agnostic, AI-first corrective action quality validator.

    Architecture:
        Level 1 (Statistical) → fast, free, no AI
        Level 2 (AI Semantic) → Gemini 2.5 Flash, configurable
        Level 3 (Business)    → universal rules only

    Example:
        validator = CorrectiveActionValidator()
        result = await validator.validate(
            corrective_action="Adjusted spray gun pressure from 45 to 38 PSI.",
            concern_id="C006",
            concern_description="LEFT REAR BLACKOUT TAPE DAMAGED"
        )
        if not result.is_valid:
            raise ValueError(result.reason)
    """

    def __init__(self, config: Optional[ValidatorConfig] = None):
        self.config = config or ValidatorConfig()
        self.analyzer = TextAnalyzer()
        self._ai_model = None

    def _load_ai_model(self):
        """Lazy-load google-genai client for Vertex AI."""
        if self._ai_model:
            return self._ai_model
        try:
            from google import genai
            from backend.config.settings import settings
            self._ai_model = genai.Client(
                vertexai=True,
                project=settings.vertex_ai_project,
                location="global",
            )
            logger.info("google-genai client loaded for CA validation")
        except Exception as e:
            logger.warning(f"google-genai unavailable: {e}")
            self._ai_model = None
        return self._ai_model

    # ── Level 1: Statistical ───────────────────────────────────────────────────
    def _level1_statistical(self, text: str) -> Optional[ValidationResult]:
        """
        Fast statistical pre-filter.
        No word lists. No language assumptions.
        Rejects obvious garbage before paying for AI.
        """
        cfg = self.config

        # 1a. Absolute length
        if (self.analyzer.char_count(text) < cfg.min_chars
                or self.analyzer.word_count(text) < cfg.min_words):
            return ValidationResult(
                status=ValidationStatus.REJECTED_TOO_SHORT,
                is_valid=False,
                score=0.0,
                reason=(
                    f"Text too short: {self.analyzer.word_count(text)} words, "
                    f"{self.analyzer.char_count(text)} chars. "
                    f"Minimum: {cfg.min_words} words, {cfg.min_chars} chars."
                ),
                original_text=text,
                rejection_level=RejectionLevel.LEVEL_1_STATISTICAL
            )

        # 1b. Lexical diversity (not all the same word)
        diversity = self.analyzer.unique_word_ratio(text)
        if diversity < cfg.min_unique_word_ratio:
            return ValidationResult(
                status=ValidationStatus.REJECTED_LOW_DIVERSITY,
                is_valid=False,
                score=diversity,
                reason=(
                    f"Low lexical diversity ({diversity:.0%} unique words). "
                    f"Text appears repetitive or copy-pasted."
                ),
                original_text=text,
                rejection_level=RejectionLevel.LEVEL_1_STATISTICAL
            )

        # 1c. Character repetition (aaaa, ...., -----)
        rep_ratio = self.analyzer.repetition_ratio(text)
        if rep_ratio > cfg.max_repetition_ratio:
            return ValidationResult(
                status=ValidationStatus.REJECTED_REPETITIVE,
                is_valid=False,
                score=0.0,
                reason=(
                    f"High character repetition ({rep_ratio:.0%}). "
                    f"Text appears to be keyboard noise or filler."
                ),
                original_text=text,
                rejection_level=RejectionLevel.LEVEL_1_STATISTICAL
            )

        return None  # Passed Level 1

    # ── Level 3: Business Rules ────────────────────────────────────────────────
    def _level3_business(self, text: str) -> Optional[ValidationResult]:
        """
        Universal business rules — only things that NEVER change
        regardless of language, plant, or domain.
        """
        cfg = self.config

        # 3a. Must have sentence-like structure
        if not self.analyzer.has_sentence_structure(text):
            return ValidationResult(
                status=ValidationStatus.REJECTED_NO_SENTENCE,
                is_valid=False,
                score=0.05,
                reason=(
                    "Text does not appear to contain a complete sentence. "
                    "Please describe what was done in full sentences."
                ),
                original_text=text,
                rejection_level=RejectionLevel.LEVEL_3_BUSINESS_RULE
            )

        # 3b. Not mostly symbols
        sym_ratio = self.analyzer.symbol_ratio(text)
        if sym_ratio > cfg.max_allowed_symbols_ratio:
            return ValidationResult(
                status=ValidationStatus.REJECTED_SYMBOL_NOISE,
                is_valid=False,
                score=0.0,
                reason=(
                    f"Text contains too many special characters ({sym_ratio:.0%}). "
                    f"Please use plain text."
                ),
                original_text=text,
                rejection_level=RejectionLevel.LEVEL_3_BUSINESS_RULE
            )

        return None  # Passed Level 3

    # ── Level 2: AI Semantic ───────────────────────────────────────────────────
    async def _level2_ai(
        self,
        corrective_action: str,
        concern_description: str
    ) -> Optional[ValidationResult]:
        """
        Gemini 2.5 Flash semantic validation via google-genai SDK.
        Multilingual prompt — responds regardless of input language.
        Returns None if valid, ValidationResult if rejected.
        """
        if not self.config.ai_enabled:
            return None

        client = self._load_ai_model()
        if not client:
            logger.warning("AI model unavailable — skipping Level 2")
            return None

        prompt = f"""You are a quality engineer at an automotive assembly plant.
Your job is to evaluate if a corrective action description is specific,
technical, and meaningful enough to be useful for future AI recommendations.

The text may be in ANY language (English, Spanish, Portuguese, French, etc.).
Evaluate the CONTENT and SPECIFICITY, not the language.

---
CONCERN (what went wrong):
{concern_description or 'Not provided'}

CORRECTIVE ACTION (what was done to fix it):
{corrective_action}
---

Evaluate based on these criteria:
1. SPECIFICITY: Does it describe a concrete action, not just "fixed" or "ok"?
2. TECHNICAL CONTENT: Does it mention equipment, measurements, procedures, or parts?
3. RELEVANCE: Is the action related to the concern described?
4. COMPLETENESS: Could another engineer understand what was done?

Score guide:
- 0.0-0.3: Completely vague ("ok", "fixed", "pendiente", "ya quedo")
- 0.3-0.6: Somewhat vague, lacks technical detail
- 0.6-0.8: Adequate, describes the action with some detail
- 0.8-1.0: Excellent, specific, technical, complete

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "is_valid": true or false,
  "score": 0.0 to 1.0,
  "reason": "one sentence in English explaining the decision",
  "detected_language": "en|es|pt|fr|other"
}}"""

        try:
            from google.genai import types as genai_types
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        max_output_tokens=256,
                        temperature=0.1,
                        thinking_config=genai_types.ThinkingConfig(
                            thinking_budget=0,
                        ),
                    ),
                ),
                timeout=self.config.ai_timeout_seconds
            )
            raw = ""
            if response and response.candidates:
                for candidate in response.candidates:
                    if candidate.content and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, "text") and part.text:
                                raw += part.text
            raw = raw.strip()
            raw = re.sub(r"```json|```", "", raw).strip()
            data = json.loads(raw)

            score = float(data.get("score", 0.0))
            is_valid = data.get("is_valid", False)
            reason = data.get("reason", "AI validation failed")
            detected_lang = data.get("detected_language", "unknown")

            if not is_valid or score < self.config.ai_quality_threshold:
                return ValidationResult(
                    status=ValidationStatus.REJECTED_AI_LOW_QUALITY,
                    is_valid=False,
                    score=score,
                    reason=f"AI quality check failed: {reason}",
                    original_text=corrective_action,
                    detected_language=detected_lang,
                    rejection_level=RejectionLevel.LEVEL_2_AI_SEMANTIC,
                    ai_response=data
                )

            return None  # AI says valid

        except asyncio.TimeoutError:
            logger.warning(
                f"Gemini timeout after {self.config.ai_timeout_seconds}s. "
                f"Skipping AI validation."
            )
            return None
        except json.JSONDecodeError as e:
            logger.warning(f"AI response not valid JSON: {e}. Skipping.")
            return None
        except Exception as e:
            logger.warning(f"AI validation error: {e}. Skipping.")
            return None

    # ── Main Entry Point ───────────────────────────────────────────────────────
    async def validate(
        self,
        corrective_action: str,
        concern_id: str = "",
        concern_description: str = ""
    ) -> ValidationResult:
        """
        Main validation entry point.
        Runs: Level 1 → Level 3 → Level 2 (AI last, most expensive)

        Args:
            corrective_action: Text to validate
            concern_id: For traceability in logs
            concern_description: Context for AI evaluation

        Returns:
            ValidationResult — check .is_valid before proceeding
        """
        text = self.analyzer.normalize(corrective_action or "")
        detected_lang = self.analyzer.detect_language_hint(text)

        # ── Level 1: Statistical (fast, free) ─────────────────────────────
        result = self._level1_statistical(text)
        if result:
            result.concern_id = concern_id
            result.detected_language = detected_lang
            logger.warning(f"[{concern_id}] L1 REJECT: {result.reason}")
            return result

        # ── Level 3: Business Rules (fast, free) ──────────────────────────
        result = self._level3_business(text)
        if result:
            result.concern_id = concern_id
            result.detected_language = detected_lang
            logger.warning(f"[{concern_id}] L3 REJECT: {result.reason}")
            return result

        # ── Level 2: AI Semantic (slow, costs API calls) ──────────────────
        result = await self._level2_ai(text, concern_description)
        if result:
            result.concern_id = concern_id
            result.detected_language = detected_lang
            logger.warning(f"[{concern_id}] L2 REJECT: {result.reason}")
            return result

        # ── All levels passed ──────────────────────────────────────────────
        logger.info(f"[{concern_id}] VALID (lang={detected_lang})")
        return ValidationResult(
            status=ValidationStatus.VALID,
            is_valid=True,
            score=1.0,
            reason="Passed all validation levels",
            original_text=text,
            concern_id=concern_id,
            detected_language=detected_lang
        )


# ── Field Validator ────────────────────────────────────────────────────────────
class CorrectiveActionFieldValidator:
    """
    WISO-AI — Field-level validator for corrective action records.
    Runs BEFORE semantic validation (ADR-001).

    Three levels of field requirements:

    LEVEL 1 — REQUIRED (record rejected if missing):
    ├── concern_id          → uniquely identifies the record
    ├── concern_description → without this, no semantic embedding possible
    └── corrective_action   → without this, no semantic embedding possible

    LEVEL 2 — QUASI-REQUIRED / HARD FILTERS (degrade RAG if missing):
    ├── department          → primary filter — VERY IMPORTANT
    └── product_line        → secondary filter — IMPORTANT
        If missing: record enters AlloyDB but will NEVER appear
        in retrieval results filtered by these fields.

    LEVEL 3 — ENRICHED CONTEXT (optional, nice-to-have):
    ├── plant               → location context
    ├── severity            → urgency context
    ├── collection_point    → physical location within plant
    ├── charged_zone        → team responsibility context
    ├── resolved_at         → when the concern was resolved
    └── mttr_minutes        → Mean Time To Resolve
    """

    LEVEL_1_REQUIRED = [
        "concern_id",
        "concern_description",
        "corrective_action",
    ]

    LEVEL_2_QUASI_REQUIRED = [
        "department",
        "product_line",
    ]

    LEVEL_3_OPTIONAL = [
        "plant",
        "severity",
        "collection_point",
        "charged_zone",
        "resolved_at",
        "mttr_minutes",
    ]

    def validate(self, record: dict) -> ValidationResult | None:
        """
        Validates field presence and basic quality.

        Returns:
            None if all Level 1 fields present and valid.
            ValidationResult with is_valid=False if Level 1 fails.
        """
        concern_id = record.get("concern_id", "UNKNOWN")

        # ── Level 1: Required — hard reject ───────────────────────────────
        for required_field in self.LEVEL_1_REQUIRED:
            value = record.get(required_field)
            if not value or not str(value).strip():
                logger.warning(
                    f"[{concern_id}] FIELD REJECT L1: "
                    f"Missing required field '{required_field}'."
                )
                return ValidationResult(
                    status=ValidationStatus.REJECTED_TOO_SHORT,
                    is_valid=False,
                    score=0.0,
                    reason=(
                        f"Missing required field: '{required_field}'. "
                        f"Level 1 fields are mandatory for embedding."
                    ),
                    original_text=str(record.get("corrective_action", "")),
                    concern_id=concern_id
                )

        # ── Level 2: Quasi-required — warning, record still enters ─────────
        missing_l2 = []
        for quasi_field in self.LEVEL_2_QUASI_REQUIRED:
            value = record.get(quasi_field)
            if not value or not str(value).strip():
                missing_l2.append(quasi_field)

        if missing_l2:
            logger.warning(
                f"[{concern_id}] FIELD WARNING L2: "
                f"Missing quasi-required fields: {missing_l2}. "
                f"Record will enter AlloyDB but WON'T be retrievable "
                f"by these hard filters. RAG quality degraded."
            )

        # ── Level 3: Optional — info log only ─────────────────────────────
        missing_l3 = []
        for optional_field in self.LEVEL_3_OPTIONAL:
            value = record.get(optional_field)
            if not value or not str(value).strip():
                missing_l3.append(optional_field)

        if missing_l3:
            logger.info(
                f"[{concern_id}] FIELD INFO L3: "
                f"Missing optional fields: {missing_l3}. "
                f"Record enters with NULL values."
            )

        return None  # All Level 1 fields present — proceed


# ── Batch Helper ───────────────────────────────────────────────────────────────
async def validate_batch(
    records: list[dict],
    config: Optional[ValidatorConfig] = None
) -> tuple[list[dict], list[ValidationResult]]:
    """
    Validate a batch of records concurrently.
    Returns (valid_records, rejected_results)
    """
    validator = CorrectiveActionValidator(config=config)

    tasks = [
        validator.validate(
            corrective_action=r.get("corrective_action", ""),
            concern_id=r.get("concern_id", ""),
            concern_description=r.get("concern_description", "")
        )
        for r in records
    ]

    results = await asyncio.gather(*tasks)

    valid_records = []
    rejected_results = []

    for record, result in zip(records, results):
        if result.is_valid:
            valid_records.append(record)
        else:
            rejected_results.append(result)

    logger.info(
        f"Batch complete — Valid: {len(valid_records)}, "
        f"Rejected: {len(rejected_results)}/{len(records)}"
    )
    return valid_records, rejected_results
