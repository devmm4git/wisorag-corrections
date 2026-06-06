# M3 — Task 3.1: FastAPI App Setup + Health Endpoint

## Overview

| Field | Value |
|-------|-------|
| **Milestone** | M3 — FastAPI Backend & RAG API |
| **Task** | 3.1 |
| **Branch** | `feat/m3-task-3.1-fastapi-setup` |
| **Status** | ✅ Done (PR #13) |
| **Depends on** | M2 ✅ |
| **Swagger tag** | `health` |
| **Service Account** | public (no auth) |

## Objective

Bootstrap the FastAPI application and implement the `GET /ai/health`
endpoint. Called by GCP Cloud Load Balancer every 10 seconds to verify
the Cloud Run instance is operational. Also callable by DevOps for
manual status checks.

## Files

| File | Action |
|------|--------|
| `backend/app/main.py` | CREATE — FastAPI app entrypoint, router registration |
| `backend/app/routers/health.py` | CREATE — GET /ai/health router |
| `backend/app/routers/__init__.py` | CREATE — empty |
| `backend/app/models/__init__.py` | CREATE — empty |
| `backend/app/middleware/__init__.py` | CREATE — empty |
| `backend/app/__init__.py` | CREATE — empty |
| `backend/db/alloydb.py` | UPDATE — add `check_connection()` function |
| `backend/tests/test_health.py` | CREATE — unit tests |

## Endpoint

```
GET /ai/health
Auth: none (public)
```

## Response Schema

| Field | Type | Description |
|-------|------|-------------|
| `status` | ENUM | `healthy` / `degraded` / `unhealthy` |
| `alloydb` | ENUM | `connected` / `unreachable` |
| `vertex_ai` | ENUM | `reachable` / `unreachable` |
| `latency_p95_ms` | INTEGER | p95 RAG latency last 5 min. Null if unavailable |
| `active_instances` | INTEGER | Cloud Run instances serving requests |
| `uptime_seconds` | INTEGER | Seconds since last cold start |

## HTTP Status Codes

| Code | status value | Condition | Load Balancer Action |
|------|-------------|-----------|----------------------|
| `200 OK` | `healthy` | AlloyDB connected + Vertex AI reachable | Instance stays in rotation |
| `200 OK` | `degraded` | One dependency slow but responding | Alert fires, instance stays |
| `503 Unavailable` | `unhealthy` | AlloyDB or Vertex AI unreachable | Removed after 2 consecutive failures |

## Response Examples

```json
// Healthy
{
  "status": "healthy",
  "alloydb": "connected",
  "vertex_ai": "reachable",
  "latency_p95_ms": null,
  "active_instances": 1,
  "uptime_seconds": 42
}

// Unhealthy
{
  "status": "unhealthy",
  "alloydb": "unreachable",
  "vertex_ai": "reachable",
  "latency_p95_ms": null,
  "active_instances": 1,
  "uptime_seconds": 320
}
```

## flake8 Errors Fixed

| File | Error | Fix Applied |
|------|-------|-------------|
| `backend/db/alloydb.py` | E302 — 2 blank lines expected | Added 2 blank lines before `check_connection()` |
| `backend/db/alloydb.py` | F821 — undefined name `get_pool` | Replaced with `get_write_pool()` |
| `backend/app/main.py` | W292 — no newline at end of file | Added trailing newline |
| `backend/app/routers/health.py` | W292 — no newline at end of file | Added trailing newline |
| `backend/tests/test_health.py` | F401 — `pytest` imported but unused | Removed unused import |
| `backend/tests/test_health.py` | W292 — no newline at end of file | Added trailing newline |

## Commit

```
feat(app): FastAPI app setup + health endpoint — Task 3.1
```

## PR

```
base:     develop
compare:  feat/m3-task-3.1-fastapi-setup
title:    feat(app): FastAPI app setup + health endpoint — Task 3.1
reviewer: wmssaas-project
merge:    Squash and merge — PR #13
```

## Run Locally

```bash
uvicorn backend.app.main:app --reload
# Swagger UI → http://localhost:8000/docs
# Health     → http://localhost:8000/ai/health
```

## References

- `backend/db/alloydb.py` — `check_connection()` uses `get_write_pool()`
- `backend/app/routers/health.py` — pings AlloyDB on every request
- CONTRIBUTING.md — git workflow and flake8 standards

---
*Owner: rag-sp@mm4.me | June 2026*

## Git Workflow

### 1. Crear branch
```bash
git checkout develop
git pull origin develop
git checkout -b feat/m3-task-3.1-fastapi-setup
```

### 2. Crear archivos y aplicar cambios
Ver sección **Files** arriba.

### 3. Validar con flake8
```bash
flake8 backend/ --max-line-length=100 --exclude=__pycache__,.venv
# Sin output → ✅ limpio
```

### 4. Commit y push
```bash
git add .
git commit -m "feat(app): FastAPI app setup + health endpoint — Task 3.1"
git push origin feat/m3-task-3.1-fastapi-setup
```

### 5. Abrir PR en GitHub
```
URL:      https://github.com/devmm4git/wisorag-corrections/pull/new/feat/m3-task-3.1-fastapi-setup
base:     develop
compare:  feat/m3-task-3.1-fastapi-setup
title:    feat(app): FastAPI app setup + health endpoint — Task 3.1
reviewer: wmssaas-project
merge:    Squash and merge → PR #13
```

### 6. Cleanup post-merge
```bash
git checkout develop
git pull origin develop
git branch -D feat/m3-task-3.1-fastapi-setup
```
