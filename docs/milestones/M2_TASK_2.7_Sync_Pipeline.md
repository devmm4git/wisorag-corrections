# WISO-AI — M2 Task 2.7: Continuous Sync Pipeline
## `sync_new_ca.py` — Real-time corrective action ingestion

---

## Contexto

**¿Qué hace esta task?**
Construye el módulo Python que sincroniza nuevos corrective actions
en tiempo real hacia AlloyDB. Es llamado por el endpoint
`POST /corrective-actions/ingest` que se construye en M3.

**¿Por qué existe separado de `ingest_historical.py`?**

| | `ingest_historical.py` | `sync_new_ca.py` |
|---|---|---|
| **Modo** | Batch (26+ registros) | Real-time (1 registro) |
| **Frecuencia** | Una vez / pocas veces | Miles de veces al día |
| **Latencia** | No importa | < 30 segundos |
| **Llamado por** | CLI / Cloud Run Job | FastAPI endpoint (M3) |

---

## Flujo de trabajo Git

### Paso 1 — Crear branch desde develop actualizado

```bash
git checkout develop
git pull origin develop
git checkout -b feat/sync-new-ca-pipeline
git status
```

**Output esperado:**
```
Switched to a new branch 'feat/sync-new-ca-pipeline'
nothing to commit, working tree clean
```

---

### Paso 2 — Crear el archivo sync_new_ca.py

Archivo: `backend/pipelines/sync_new_ca.py`

```python
"""
WISO-AI — Continuous Sync Pipeline
Pipeline 3: Real-time sync for new corrective actions.

Called by: POST /corrective-actions/ingest (M3 FastAPI endpoint)

Flow:
    1. Field validation (Level 1/2/3) — CorrectiveActionFieldValidator
    2. Semantic validation (ADR-001)  — CorrectiveActionValidator
    3. Generate embedding (Vertex AI) — text-embedding-004 (768 dims)
    4. INSERT into AlloyDB            — corrective_actions_vectors
    5. Return SyncResult

Target latency: < 30 seconds end-to-end
Design: Single record — no batching, no loops

Owner: rag-dataengineer@mm4.me
Milestone: M2 — Task 2.7
Called by: backend/app/routers/corrective_actions.py (M3)
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import asyncpg
from google.cloud import aiplatform

from backend.config.settings import settings
from backend.rag.corrective_action_validator import (
    CorrectiveActionFieldValidator,
    CorrectiveActionValidator,
    ValidatorConfig,
    ValidationResult,
)

logger = logging.getLogger("wiso-ai.sync")


# ── Result Object ──────────────────────────────────────────────────────────────
@dataclass
class SyncResult:
    """
    Result of a sync operation.
    Used by M3 API to build HTTP response.

    success=True  → HTTP 201 Created
    success=False → HTTP 422 Unprocessable Entity
    """
    success: bool
    concern_id: str
    alloydb_id: Optional[int] = None       # id del registro insertado
    rejection_reason: Optional[str] = None  # razón de rechazo si success=False
    embedding_dims: int = 0                 # 768 si se generó embedding
    latency_ms: float = 0.0                # latencia total en ms

    def to_api_response(self) -> dict:
        """Format for HTTP API response (M3)."""
        if self.success:
            return {
                "success": True,
                "concern_id": self.concern_id,
                "alloydb_id": self.alloydb_id,
                "embedding_dims": self.embedding_dims,
                "latency_ms": round(self.latency_ms, 2),
                "message": "Corrective action synced successfully."
            }
        return {
            "success": False,
            "concern_id": self.concern_id,
            "rejection_reason": self.rejection_reason,
            "message": "Corrective action rejected — not synced."
        }


# ── Embedding ──────────────────────────────────────────────────────────────────
def generate_single_embedding(text: str) -> list[float]:
    """
    Generate a single 768-dim embedding via Vertex AI.
    No batching — single record for real-time performance.
    """
    aiplatform.init(
        project=settings.vertex_ai_project,
        location=settings.vertex_ai_location
    )
    from vertexai.language_models import TextEmbeddingModel
    model = TextEmbeddingModel.from_pretrained(settings.embedding_model)
    result = model.get_embeddings([text])
    return result[0].values


# ── Chunk text ─────────────────────────────────────────────────────────────────
def build_chunk_text(record: dict) -> str:
    """
    Build semantic chunk text — ONLY Concern + Corrective Action.
    No metadata in embedding (ADR-002).
    """
    concern = record.get('concern_description', '').strip()
    corrective = record.get('corrective_action', '').strip()
    return f"Concern: {concern}\n\nCorrective Action: {corrective}"


# ── AlloyDB Insert ─────────────────────────────────────────────────────────────
async def insert_single_record(
    record: dict,
    embedding: list[float]
) -> Optional[int]:
    """
    Insert a single validated record into AlloyDB.
    Returns the alloydb id of the inserted record, or None if failed.
    """
    pool = await asyncpg.create_pool(
        host=settings.alloydb_host,
        port=settings.alloydb_port,
        database=settings.alloydb_database,
        user=settings.alloydb_user,
        password=settings.alloydb_password,
        ssl='require',
        min_size=1,
        max_size=1,
    )

    insert_query = """
        INSERT INTO corrective_actions_vectors (
            concern_id, plant, department,
            concern_description, corrective_action,
            severity, collection_point, product_line,
            charged_zone, chunk_text, embedding
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::vector
        )
        ON CONFLICT DO NOTHING
        RETURNING id
    """

    try:
        chunk_text = build_chunk_text(record)
        embedding_str = f"[{','.join(map(str, embedding))}]"

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                insert_query,
                record.get('concern_id'),
                record.get('plant'),
                record.get('department'),
                record.get('concern_description'),
                record.get('corrective_action'),
                record.get('severity'),
                record.get('collection_point'),
                record.get('product_line'),
                record.get('charged_zone'),
                chunk_text,
                embedding_str
            )
            if row:
                return row['id']
            return None
    finally:
        await pool.close()


# ── Main Sync Function ─────────────────────────────────────────────────────────
async def sync_new_corrective_action(record: dict) -> SyncResult:
    """
    Main entry point for real-time corrective action sync.
    Called by: POST /corrective-actions/ingest (M3 FastAPI)

    Args:
        record: dict with corrective action fields from WISOHUB

    Returns:
        SyncResult — check .success before building HTTP response

    Example:
        result = await sync_new_corrective_action({
            "concern_id": "C099",
            "department": "PAINT",
            "product_line": "RANGER",
            "concern_description": "Paint run on door lower section",
            "corrective_action": "Adjusted gun pressure from 45 to 38 PSI..."
        })
        if result.success:
            return JSONResponse(result.to_api_response(), status_code=201)
        else:
            return JSONResponse(result.to_api_response(), status_code=422)
    """
    import time
    start_time = time.time()
    concern_id = record.get('concern_id', 'UNKNOWN')

    logger.info(f"[{concern_id}] Sync started")

    # ── Step 1: Field Validation (Level 1/2/3) ────────────────────────────
    field_validator = CorrectiveActionFieldValidator()
    field_result = field_validator.validate(record)

    if field_result is not None:
        logger.warning(f"[{concern_id}] Field validation failed: {field_result.reason}")
        return SyncResult(
            success=False,
            concern_id=concern_id,
            rejection_reason=field_result.reason,
            latency_ms=(time.time() - start_time) * 1000
        )

    # ── Step 2: Semantic Validation (ADR-001) ─────────────────────────────
    semantic_validator = CorrectiveActionValidator(
        config=ValidatorConfig(
            ai_enabled=True,
            ai_quality_threshold=0.6,
            min_chars=30,
            min_words=5
        )
    )

    semantic_result: ValidationResult = await semantic_validator.validate(
        corrective_action=record.get('corrective_action', ''),
        concern_id=concern_id,
        concern_description=record.get('concern_description', '')
    )

    if not semantic_result.is_valid:
        logger.warning(f"[{concern_id}] Semantic validation failed: {semantic_result.reason}")
        return SyncResult(
            success=False,
            concern_id=concern_id,
            rejection_reason=semantic_result.reason,
            latency_ms=(time.time() - start_time) * 1000
        )

    # ── Step 3: Generate Embedding ────────────────────────────────────────
    chunk_text = build_chunk_text(record)
    logger.info(f"[{concern_id}] Generating embedding...")

    try:
        embedding = generate_single_embedding(chunk_text)
        logger.info(f"[{concern_id}] Embedding generated ({len(embedding)} dims)")
    except Exception as e:
        logger.error(f"[{concern_id}] Embedding failed: {e}")
        return SyncResult(
            success=False,
            concern_id=concern_id,
            rejection_reason=f"Embedding generation failed: {str(e)}",
            latency_ms=(time.time() - start_time) * 1000
        )

    # ── Step 4: Insert to AlloyDB ─────────────────────────────────────────
    logger.info(f"[{concern_id}] Inserting into AlloyDB...")

    try:
        alloydb_id = await insert_single_record(record, embedding)

        if alloydb_id is None:
            logger.warning(f"[{concern_id}] Already exists in AlloyDB — skipped")
            return SyncResult(
                success=False,
                concern_id=concern_id,
                rejection_reason="Record already exists in AlloyDB (ON CONFLICT DO NOTHING).",
                latency_ms=(time.time() - start_time) * 1000
            )

        latency = (time.time() - start_time) * 1000
        logger.info(
            f"[{concern_id}] Sync complete — "
            f"alloydb_id={alloydb_id}, "
            f"latency={latency:.0f}ms"
        )

        return SyncResult(
            success=True,
            concern_id=concern_id,
            alloydb_id=alloydb_id,
            embedding_dims=len(embedding),
            latency_ms=latency
        )

    except Exception as e:
        logger.error(f"[{concern_id}] AlloyDB insert failed: {e}")
        return SyncResult(
            success=False,
            concern_id=concern_id,
            rejection_reason=f"AlloyDB insert failed: {str(e)}",
            latency_ms=(time.time() - start_time) * 1000
        )
```

---

### Paso 3 — Crear test para sync_new_ca.py

Archivo: `backend/tests/test_sync_new_ca.py`

```python
"""
WISO-AI — Unit Tests: Continuous Sync Pipeline
Tests sync_new_corrective_action() without real DB or AI calls.

Run: pytest backend/tests/test_sync_new_ca.py -v
"""
import pytest
from unittest.mock import AsyncMock, patch
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
```

---

### Paso 4 — Verificar flake8 localmente (SIEMPRE antes del commit)

flake8 es el **linter local** — verifica estilo y errores antes de hacer push.
Si no sale nada → código limpio ✅. Si sale algo → corregir antes del commit.

```bash
flake8 backend/ --max-line-length=100 --exclude=__pycache__,.venv
```

Output esperado (código limpio):
```
(ninguna salida — 0 errores)
```

---

### Paso 5 — Commit y push

```bash
git add backend/pipelines/sync_new_ca.py
git add backend/tests/test_sync_new_ca.py
git status

git commit -m "feat(pipeline): add sync_new_ca.py — real-time CA sync (Pipeline 3)

Real-time corrective action sync module for M3 API integration.

Flow:
  1. Field validation (Level 1/2/3) — CorrectiveActionFieldValidator
  2. Semantic validation (ADR-001)  — CorrectiveActionValidator
  3. Generate single embedding      — Vertex AI text-embedding-004
  4. INSERT into AlloyDB            — RETURNING id
  5. Return SyncResult

SyncResult.to_api_response() maps to:
  success=True  → HTTP 201 (M3)
  success=False → HTTP 422 (M3)

Target latency: < 30 seconds end-to-end
ADR-002: chunk_text = Concern + CA only (no metadata)

Tests:
  - test_build_chunk_text_correct_format
  - test_build_chunk_text_strips_whitespace
  - test_sync_result_success_api_response
  - test_sync_result_failure_api_response
  - test_rejects_missing_required_fields
  - test_rejects_short_corrective_action

Milestone: M2 — Task 2.7
Called by: backend/app/routers/corrective_actions.py (M3)"

git push origin feat/sync-new-ca-pipeline
```

---

### Paso 6 — Verificar CI en GitHub Actions

Ir a: `github.com/devmm4git/wisorag-corrections/actions`

Verificar que el workflow **CI — WISO-AI Pipeline** pasa:
- ✅ Lint with flake8
- ✅ Run tests

---

### Paso 7 — Abrir PR

```
URL: github.com/devmm4git/wisorag-corrections/pull/new/feat/sync-new-ca-pipeline
base: develop
compare: feat/sync-new-ca-pipeline
Title: feat(pipeline): add sync_new_ca.py — real-time CA sync (Pipeline 3)
```

Review con `wmssaas-project` → Approve → Squash and merge

---

### Paso 8 — Limpiar branches

```bash
git checkout develop
git pull origin develop
git branch -D feat/sync-new-ca-pipeline
git branch
```

---

### Paso 9 — Probar manualmente (opcional)

Desde Cloud Shell, crear un script de prueba rápida:

```bash
cd ~/wisorag-corrections
git pull origin develop

cat > /tmp/test_sync.py << 'EOF'
import asyncio
import sys
sys.path.insert(0, '/home/daviddeveps/wisorag-corrections')

from backend.pipelines.sync_new_ca import sync_new_corrective_action

test_record = {
    "concern_id": "C099_TEST",
    "department": "PAINT",
    "product_line": "RANGER",
    "plant": "MAP",
    "severity": "A",
    "collection_point": "165-Q LEFT REAR",
    "concern_description": "Paint run detected on left door lower section during final inspection",
    "corrective_action": (
        "Adjusted spray gun pressure from 45 to 38 PSI on station P-165. "
        "Cleaned nozzle tip and verified spray pattern. "
        "Inspected 5 consecutive units — zero defects confirmed."
    )
}

async def main():
    result = await sync_new_corrective_action(test_record)
    print(f"\nResult: {result.to_api_response()}")

asyncio.run(main())
EOF

export ALLOYDB_HOST="34.60.92.141"
export ALLOYDB_PASSWORD='WisoAI2024#Staging'
export ALLOYDB_DATABASE="wiso_ai_db"
export ALLOYDB_USER="postgres"
export VERTEX_AI_PROJECT="ragai-staging"
export VERTEX_AI_LOCATION="us-central1"
export ENVIRONMENT="dev"

python /tmp/test_sync.py
```

**Output esperado:**
```json
{
  "success": true,
  "concern_id": "C099_TEST",
  "alloydb_id": 17,
  "embedding_dims": 768,
  "latency_ms": 8500.0,
  "message": "Corrective action synced successfully."
}
```

---

## Resumen de archivos creados/modificados

| Archivo | Acción | Descripción |
|---|---|---|
| `backend/pipelines/sync_new_ca.py` | ✅ Creado | Pipeline 3 — real-time sync |
| `backend/tests/test_sync_new_ca.py` | ✅ Creado | Unit tests sin DB ni AI |

## Estado al cierre de Task 2.7

```
MILESTONE 2 — Data Pipeline & AlloyDB Vectorization
├── ✅ Task 2.0  Network Infrastructure (wiso-ai-vpc)
├── ✅ Task 2.1  AlloyDB Instance + Database + pgvector
├── ✅ Task 2.2  Historical Data Ingestion
├── ✅ Task 2.3  Text Chunking (ADR-002: semantic only)
├── ✅ Task 2.4  Vertex AI Embeddings (768 dims)
├── ✅ Task 2.5  AlloyDB Vector Index (HNSW m=16)
├── ✅ Task 2.6  Load Historical Vectors (16 records)
└── ✅ Task 2.7  Continuous Sync Pipeline (sync_new_ca.py)
```
