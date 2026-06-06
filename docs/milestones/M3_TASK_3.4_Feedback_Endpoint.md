# M3 — Task 3.4: POST /corrective-actions/feedback

## Overview

| Field | Value |
|-------|-------|
| **Milestone** | M3 — FastAPI Backend & RAG API |
| **Task** | 3.4 |
| **Branch** | `feat/m3-task-3.4-feedback-endpoint` |
| **Status** | ✅ Done (PR #16) |
| **Depends on** | Task 3.3 ✅ (PR #15) |
| **Swagger tag** | `corrective-actions` |
| **Service Account** | `rag-api-sa@ragai-staging.iam.gserviceaccount.com` |

## Objective

Implement `POST /corrective-actions/feedback` — the feedback loop endpoint.
Records ACCEPT, REJECT, or MODIFY decisions from the Process Coach.
Updates retrieval weights in AlloyDB and logs the event to BigQuery.
No re-embedding for ACCEPT or REJECT. MODIFY triggers a new 768-dim embedding + INSERT.

## Files

| File | Action |
|------|--------|
| `backend/app/models/feedback.py` | CREATE — Pydantic request/response models + FeedbackAction enum |
| `backend/rag/feedback_handler.py` | CREATE — apply_accept(), apply_reject(), apply_modify(), log_feedback_to_bigquery() |
| `backend/app/routers/feedback.py` | CREATE — FastAPI router |
| `backend/app/main.py` | UPDATE — register feedback router |
| `backend/tests/test_feedback_endpoint.py` | CREATE — unit tests (8 tests) |

## Endpoint

```
POST /corrective-actions/feedback
Auth: rag-api-sa@ragai-staging.iam.gserviceaccount.com
```

## Input Parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `request_id` | STRING | YES | request_id returned by /ai/recommend |
| `chunk_ids` | ARRAY<STRING> | YES | chunk_id values shown to the coach |
| `action` | ENUM | YES | ACCEPT / REJECT / MODIFY |
| `modified_text` | STRING | MODIFY only | Coach-edited corrective action. Triggers new embedding + INSERT |
| `coach_cds_id` | STRING | YES | Coach employee ID. Stored in BigQuery |
| `concern_id` | STRING | YES | Original concern ID. Links to Tip Board event |

## Output Parameters

| Field | Type | Description |
|-------|------|-------------|
| `status` | STRING | Always 'recorded' on success |
| `action_applied` | ENUM | Echo of ACCEPT / REJECT / MODIFY |
| `new_chunk_id` | STRING | For MODIFY only: chunk_id of the newly inserted record |
| `error` | STRING | Human-readable error. Present only on failure |
| `error_code` | STRING | Machine-readable code for client-side handling |

## Backend Action per Feedback Type

| Action | AlloyDB Operation | BigQuery Log | Re-embedding? |
|--------|-------------------|--------------|---------------|
| **ACCEPT** | UPDATE accept_count++, feedback_score = (accept_count + 1.0) / (accept_count + reject_count + 1) | INSERT into feedback_log | NO — pure SQL UPDATE |
| **REJECT** | UPDATE reject_count++, feedback_score = accept_count / (accept_count + reject_count + 1.0) | INSERT into feedback_log | NO — pure SQL UPDATE |
| **MODIFY** | INSERT new record with modified_text + fresh 768-dim embedding. feedback_score = 1.0 | INSERT original + modified text for diff tracking | YES — Vertex AI call |

## HTTP Status Codes

| Code | error_code | Condition |
|------|-----------|-----------|
| `200 OK` | — | Feedback recorded. AlloyDB updated. BigQuery log inserted |
| `400 Bad Request` | `MODIFY_REQUIRES_TEXT` | action=MODIFY but modified_text is null or empty |
| `404 Not Found` | `CHUNK_NOT_FOUND` | concern_id not found in AlloyDB |
| `422 Unprocessable` | — | Required field missing or invalid action value (Pydantic) |
| `500 Internal Error` | `ALLOYDB_UPDATE_ERROR` | UPDATE or INSERT failed |

## Backend Flow

```
POST /corrective-actions/feedback
    ↓
FeedbackRequest (Pydantic validation — action enum, MODIFY check)
    ↓
ACCEPT → apply_accept(concern_id)
         UPDATE accept_count++, recalculate feedback_score
         No re-embedding ✅

REJECT → apply_reject(concern_id)
         UPDATE reject_count++, recalculate feedback_score
         No re-embedding ✅

MODIFY → apply_modify(concern_id, modified_text, coach_cds_id)
         embed_query(modified_text) → Vertex AI 768-dim vector
         INSERT new row, feedback_score = 1.0
         Returns new_chunk_id = {concern_id}_MOD_{coach_cds_id}_{new_id}
    ↓
log_feedback_to_bigquery(request_id, concern_id, coach_cds_id, action, chunk_ids)
    ↓
200 OK — FeedbackResponse { status, action_applied, new_chunk_id }
```

## Key Constraints

- `feedback_score` updated via pure SQL UPDATE on `concern_id` — no re-embedding for ACCEPT/REJECT
- `effective_score` is never persisted — calculated transiently in `retriever.py`
- MODIFY: new record inserted with `feedback_score = 1.0` (starts with max weight)
- MODIFY: metadata (department, product_line, plant) copied from original record via SELECT
- `coach_cds_id` and `chunk_ids` stored in BigQuery ONLY — not in AlloyDB
- Embedding model for MODIFY: `text-embedding-004` — 768 dims — IMMUTABLE

## Request Examples

```json
// ACCEPT
{
  "request_id": "req_20240508_131523_abc123",
  "chunk_ids": ["MAP_PAINT_RANGER_20241101_C003"],
  "action": "ACCEPT",
  "coach_cds_id": "CDS12345",
  "concern_id": "C_20240508_001"
}

// MODIFY
{
  "request_id": "req_20240508_131523_abc123",
  "chunk_ids": ["MAP_PAINT_RANGER_20241101_C003"],
  "action": "MODIFY",
  "modified_text": "Inspector verified tape at station 16S, adjusted applicator to 40 PSI. Confirmed adhesion on 5 consecutive units.",
  "coach_cds_id": "CDS12345",
  "concern_id": "C_20240508_001"
}
```

## Response Examples

```json
// ACCEPT / REJECT
{ "status": "recorded", "action_applied": "ACCEPT", "new_chunk_id": null }

// MODIFY
{ "status": "recorded", "action_applied": "MODIFY", "new_chunk_id": "C_20240508_001_MOD_CDS12345_42" }

// 400 — MODIFY without modified_text
{ "error": "modified_text is required when action=MODIFY.", "error_code": "MODIFY_REQUIRES_TEXT" }

// 404 — concern_id not found
{ "error": "concern_id not found in AlloyDB: C_20240508_001", "error_code": "CHUNK_NOT_FOUND" }
```

## Tests

| Test | Result |
|------|--------|
| `test_feedback_accept_200` | ✅ PASSED |
| `test_feedback_reject_200` | ✅ PASSED |
| `test_feedback_modify_200` | ✅ PASSED |
| `test_feedback_modify_missing_text_400` | ✅ PASSED |
| `test_feedback_invalid_action_422` | ✅ PASSED |
| `test_feedback_chunk_not_found_404` | ✅ PASSED |
| `test_feedback_alloydb_failure_500` | ✅ PASSED |
| `test_feedback_missing_required_field_422` | ✅ PASSED |

```
8 passed, 4 warnings in 3.84s
```

> Warnings son del entorno local (Python 3.10, starlette deprecation) — no bloqueantes.

## flake8

Sin errores — código limpio al primer intento.

## Git Workflow

### 1. Crear branch
```bash
git checkout develop
git pull origin develop
git checkout -b feat/m3-task-3.4-feedback-endpoint
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
pytest backend/tests/test_feedback_endpoint.py -v
# 8 passed ✅
```

### 5. Commit y push
```bash
git add .
git commit -m "feat(api): POST /corrective-actions/feedback — Task 3.4"
git push origin feat/m3-task-3.4-feedback-endpoint
```

### 6. PR en GitHub
```
base:     develop
compare:  feat/m3-task-3.4-feedback-endpoint
title:    feat(api): POST /corrective-actions/feedback — Task 3.4
reviewer: wmssaas-project
merge:    Squash and merge → PR #16
```

### 7. Cleanup post-merge
```bash
git checkout develop
git pull origin develop
git branch -D feat/m3-task-3.4-feedback-endpoint
```

## References

- `backend/rag/feedback_handler.py` — apply_accept(), apply_reject(), apply_modify()
- `backend/rag/retriever.py` — embed_query() reused for MODIFY embedding
- `backend/db/alloydb.py` — get_write_pool()
- `backend/db/business_rules.sql` — feedback UPDATE SQL rules
- ADR: feedback_score updated via pure SQL UPDATE — no re-embedding for ACCEPT/REJECT

---
*Owner: rag-sp@mm4.me | June 2026*
