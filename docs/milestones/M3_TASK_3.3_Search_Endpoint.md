# M3 — Task 3.3: POST /corrective-actions/search (RAG Retrieval)

## Overview

| Field | Value |
|-------|-------|
| **Milestone** | M3 — FastAPI Backend & RAG API |
| **Task** | 3.3 |
| **Branch** | `feat/m3-task-3.3-search-endpoint` |
| **Status** | ✅ Done (PR #15) |
| **Depends on** | Task 3.2 ✅ (PR #14) |
| **Swagger tag** | `corrective-actions` |
| **Service Account** | `rag-api-sa@ragai-staging.iam.gserviceaccount.com` |

## Objective

Implement `POST /corrective-actions/search` — the core RAG retrieval endpoint.
Receives a concern description, generates a 768-dim query embedding via
Vertex AI `text-embedding-004`, and retrieves top-K similar corrective actions
from AlloyDB using the HNSW cosine index with hard filters on department and product_line.

## Files

| File | Action |
|------|--------|
| `backend/app/models/search.py` | CREATE — Pydantic request/response/result models |
| `backend/rag/retriever.py` | CREATE — embed_query() + search_similar() |
| `backend/app/routers/search.py` | CREATE — FastAPI router |
| `backend/app/main.py` | UPDATE — register search router |
| `backend/tests/test_search_endpoint.py` | CREATE — unit tests (7 tests) |

## Endpoint

```
POST /corrective-actions/search
Auth: rag-api-sa@ragai-staging.iam.gserviceaccount.com
```

## Input Parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `department` | STRING | YES | Hard filter — WHERE department = $dept |
| `product_line` | STRING | YES | Hard filter — WHERE product_line = $line |
| `concern_description` | STRING | YES | Used to generate the 768-dim query embedding |
| `plant` | STRING | NO | Optional additional filter |
| `top_k` | INTEGER | NO | Results to return. Default 5, max 20 |

## Output Parameters

| Field | Type | Description |
|-------|------|-------------|
| `success` | BOOLEAN | Always true on 200 |
| `query` | STRING | The concern_description used as query |
| `results` | ARRAY | Top-K SearchResult objects |
| `result_count` | INTEGER | Number of results returned |
| `latency_ms` | FLOAT | Total end-to-end latency |
| `message` | STRING | Human-readable confirmation |

### SearchResult fields

| Field | Type | Description |
|-------|------|-------------|
| `alloydb_id` | INTEGER | Primary key in corrective_actions_vectors |
| `concern_id` | STRING | Original concern identifier |
| `department` | STRING | Manufacturing department |
| `product_line` | STRING | Vehicle product line |
| `concern_description` | STRING | Original concern text |
| `corrective_action` | STRING | Historical action taken |
| `similarity` | FLOAT | Cosine similarity 0.0–1.0 |
| `feedback_score` | FLOAT | Feedback weight 0.0–1.0 |
| `effective_score` | FLOAT | similarity × feedback_score — transient, never persisted |
| `mttr_minutes` | INTEGER | Mean time to resolution (nullable) |

## HTTP Status Codes

| Code | Condition |
|------|-----------|
| `200 OK` | Results found and returned |
| `404 Not Found` | No records match department + product_line filters |
| `422 Unprocessable` | Required field missing (Pydantic) |
| `500 Internal Error` | Vertex AI embedding failed |
| `500 Internal Error` | AlloyDB vector search failed |

## RAG Query Pattern

```sql
SELECT
    id,
    concern_id,
    department,
    product_line,
    concern_description,
    corrective_action,
    1 - (embedding <=> $1::vector) AS similarity,
    feedback_score,
    mttr_minutes
FROM corrective_actions_vectors
WHERE department = $2
  AND product_line = $3
ORDER BY embedding <=> $1::vector   -- HNSW index used here
LIMIT $4;
```

> `effective_score = similarity × feedback_score` calculated in Python — NEVER persisted in AlloyDB.

## Backend Flow

```
POST /corrective-actions/search
    ↓
SearchRequest (Pydantic validation)
    ↓
embed_query(concern_description)
— Vertex AI text-embedding-004 → 768-dim vector
    ↓
search_similar(department, product_line, query_vector, plant, top_k)
— AlloyDB HNSW cosine search with hard filters
    ↓
effective_score = similarity × feedback_score  [Python — transient]
    ↓
200 OK — SearchResponse { success, query, results, result_count, latency_ms }
```

## Key Constraints

- Embedding model: `text-embedding-004` — 768 dims — IMMUTABLE (same as ingestion)
- `department` + `product_line` are hard filters — never mix departments
- `effective_score` is calculated transiently in Python — never stored in AlloyDB
- HNSW index (`idx_embedding_hnsw`) used for cosine similarity search
- `top_k` default = 5, max = 20

## Request Example

```json
{
  "department": "PAINT",
  "product_line": "RANGER",
  "concern_description": "LEFT REAR BLACKOUT TAPE DAMAGED during final assembly",
  "plant": "MAP",
  "top_k": 3
}
```

## Response Example

```json
{
  "success": true,
  "query": "LEFT REAR BLACKOUT TAPE DAMAGED during final assembly",
  "results": [
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
      "mttr_minutes": 18
    }
  ],
  "result_count": 1,
  "latency_ms": 1243.5,
  "message": "Found 1 similar corrective actions."
}
```

## Tests

| Test | Result |
|------|--------|
| `test_search_success_200` | ✅ PASSED |
| `test_search_result_schema` | ✅ PASSED |
| `test_search_no_results_404` | ✅ PASSED |
| `test_search_embedding_failure_500` | ✅ PASSED |
| `test_search_alloydb_failure_500` | ✅ PASSED |
| `test_search_missing_required_field_422` | ✅ PASSED |
| `test_search_top_k_default` | ✅ PASSED |

```
7 passed, 4 warnings in 3.79s
```

> Warnings son del entorno local (Python 3.10, starlette deprecation) — no bloqueantes.

## flake8 Errors Fixed

| File | Error | Fix Applied |
|------|-------|-------------|
| `backend/rag/retriever.py` | F401 — `time` imported but unused | Removed unused import |
| `backend/app/models/search.py` | W292 — no newline at end of file | Added trailing newline |
| `backend/tests/test_search_endpoint.py` | W292 — no newline at end of file | Added trailing newline |

## Git Workflow

### 1. Crear branch
```bash
git checkout develop
git pull origin develop
git checkout -b feat/m3-task-3.3-search-endpoint
```

### 2. Crear archivos
Ver sección **Files** arriba.

### 3. Validar con flake8
```bash
flake8 backend/ --max-line-length=100 --exclude=__pycache__,.venv
# Sin output → ✅ limpio
```

### 4. Correr tests
```bash
pytest backend/tests/test_search_endpoint.py -v
# 7 passed ✅
```

### 5. Commit y push
```bash
git add .
git commit -m "feat(api): POST /corrective-actions/search RAG retrieval — Task 3.3"
git push origin feat/m3-task-3.3-search-endpoint
```

### 6. PR en GitHub
```
base:     develop
compare:  feat/m3-task-3.3-search-endpoint
title:    feat(api): POST /corrective-actions/search RAG retrieval — Task 3.3
reviewer: wmssaas-project
merge:    Squash and merge → PR #15
```

### 7. Cleanup post-merge
```bash
git checkout develop
git pull origin develop
git branch -D feat/m3-task-3.3-search-endpoint
```

## References

- `backend/rag/retriever.py` — `embed_query()` + `search_similar()`
- `backend/db/alloydb.py` — `get_write_pool()`
- ADR-002: chunk_text = concern_description + corrective_action only
- AlloyDB index: `idx_embedding_hnsw` (HNSW, cosine, m=16, ef_construction=64)
- AlloyDB index: `idx_department_product_line` (composite hard filter)

---
*Owner: rag-sp@mm4.me | June 2026*
