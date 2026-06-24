# WISO-AI — Project Structure Guide

**Project:** IPQ-AI / WISO-AI  
**Repo:** `wisorag-corrections` (org: `devmm4git`)  
**Main branch:** `develop`  
**Date:** June 2026  
**Owner:** rag-sp@mm4.me

---

## Full Repository Tree

```
wisorag-corrections/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── middleware/
│   │   ├── models/
│   │   │   ├── corrective_action.py
│   │   │   ├── feedback.py
│   │   │   ├── recommend.py
│   │   │   └── search.py
│   │   └── routers/
│   │       ├── corrective_actions.py
│   │       ├── feedback.py
│   │       ├── health.py
│   │       ├── recommend.py
│   │       └── search.py
│   ├── config/
│   │   └── settings.py
│   ├── db/
│   │   ├── alloydb.py
│   │   ├── alloydb.sql
│   │   ├── bifquery.sql
│   │   └── business_rules.sql
│   ├── pipelines/
│   │   ├── ingest_historical.py
│   │   └── sync_new_ca.py
│   ├── rag/
│   │   ├── corrective_action_validator.py
│   │   ├── feedback_handler.py
│   │   ├── llm_chain.py
│   │   └── retriever.py
│   └── tests/
│       ├── test_feedback_endpoint.py
│       ├── test_health.py
│       ├── test_ingest_endpoint.py
│       ├── test_recommend_endpoint.py
│       ├── test_search_endpoint.py
│       ├── test_sync_new_ca.py
│       └── test_validator.py
├── cloudbuild.yaml
├── conftest.py
├── Dockerfile
├── docs/
│   ├── api/
│   │   └── POST_corrective_actions_ingest.md
│   ├── milestones/
│   │   └── (one MD file per completed task)
│   └── standards/
│       └── CONTRIBUTING.md
├── infra/
│   └── environments/
│       ├── dev/
│       ├── prod/
│       └── uat/
├── pytest.ini
├── README.md
└── requirements.txt
```

---

## `/backend` — All Python Code

The root of all executable code in the project. The Dockerfile points here to build the image that runs on Cloud Run. No Python code lives outside this folder.

---

## `/backend/app` — The FastAPI Application (public face of the system)

Everything the outside world (WISOHUB, HTML dashboard, React) sees and consumes. Split into three subfolders with clearly separated responsibilities.

### `/backend/app/main.py`

The application entry point. Instantiates FastAPI, registers all routers, configures CORS and global middleware. This is the first file `uvicorn` executes when the server starts.

```
uvicorn backend.app.main:app --host 0.0.0.0 --port 8080
```

### `/backend/app/routers` — HTTP Endpoints

One file per route group. Defines what happens when each HTTP request arrives.

| File | Endpoint | Description |
|---|---|---|
| `recommend.py` | `POST /ai/recommend` | Receives concern from Process Coach → embed → RAG search → Gemini → returns recommendation |
| `corrective_actions.py` | `POST /corrective-actions/ingest` | Receives new CA from WISOHUB → validates → embeds → saves to AlloyDB |
| `search.py` | `POST /corrective-actions/search` | Direct vector search in AlloyDB without going through Gemini |
| `feedback.py` | `POST /ai/feedback` | Receives 👍/👎 from coach → updates `feedback_score` in AlloyDB |
| `health.py` | `GET /ai/health` | Verifies connectivity to AlloyDB and Vertex AI |

### `/backend/app/models` — Pydantic Contracts (Swagger source of truth)

Define exactly what JSON each endpoint accepts and returns. FastAPI reads these classes and automatically generates the documentation at `/docs` (Swagger UI). If a request does not match the contract, FastAPI rejects it with HTTP 422 before the router processes anything.

| File | Classes defined |
|---|---|
| `recommend.py` | `RecommendRequest`, `RecommendResponse`, `SourceItem` |
| `corrective_action.py` | `CorrectiveActionRequest`, `CorrectiveActionResponse` |
| `feedback.py` | `FeedbackRequest`, `FeedbackResponse` |
| `search.py` | `SearchRequest`, `SearchResponse` |

### `/backend/app/middleware` — Cross-cutting Layer

Code that runs on **every request** before reaching the router. Currently prepared for:

- **Authentication** — validate that the request comes from an authorized source
- **Logging** — record every call for auditing and debugging
- **Rate limiting** — protect endpoints against abuse

---

## `/backend/config` — Configuration and Secrets

### `settings.py`

Uses `pydantic-settings` to read all environment variables at startup. In Cloud Run, these variables come from Secret Manager. No credentials are ever hardcoded.

Key variables managed:

```
ALLOYDB_HOST, ALLOYDB_USER, ALLOYDB_PASSWORD, ALLOYDB_DATABASE
VERTEX_AI_PROJECT, GEMINI_LOCATION
ENVIRONMENT (dev | uat | prod)
```

---

## `/backend/db` — Database Layer

### `alloydb.py`

Manages connection pools to AlloyDB (Primary + Read Replicas). Exposes reusable functions `get_write_pool()` and `check_connection()` used by all routers and pipelines. No direct connections are ever opened outside this module.

### `alloydb.sql`

Complete DDL for the main table `corrective_actions_vectors`, including the HNSW vector index (m=16, ef=64, cosine distance). This is the source of truth for the AlloyDB schema.

### `bifquery.sql`

DDL for the `feedback_log` table in BigQuery (project `simula-ipd-produ`). Logs every 👍/👎 from the coach for quality analytics — analytics-only and does not affect real-time retrieval.

### `business_rules.sql`

The SQL UPDATE queries that apply feedback to `feedback_score`. When a coach accepts a recommendation, `accept_count` increases; when rejected, `reject_count` increases. `feedback_score` is recalculated as a proportion. No re-embedding occurs.

---

## `/backend/pipelines` — Data Pipelines

Scripts that move data between systems. These are not HTTP endpoints — they are standalone Python processes.

### `ingest_historical.py` — Pipeline 1

Batch load from BigQuery (`tipbord_historical.corrective_actions`) into AlloyDB. Ran once at project start to load the 25 historical records. Can run periodically to sync new historical data.

```
BigQuery (25 historical CAs) → ETL Python → embed → AlloyDB
```

### `sync_new_ca.py` — Pipeline 3

Real-time synchronization. Called from `POST /corrective-actions/ingest` every time WISOHUB registers a new corrective action. Must complete in under 30 seconds.

```
WISOHUB → POST /ingest → sync_new_ca.py → embed → AlloyDB
```

---

## `/backend/rag` — RAG Intelligence Layer

The heart of the system. All Retrieval-Augmented Generation logic lives here. Routers never call AlloyDB or Vertex AI directly — they always go through this module.

### `retriever.py`

Two main functions:

- `embed_query(text)` — Calls Vertex AI (`text-embedding-004`, 768 dims) to convert the coach's concern into a vector
- `search_similar(query_vector, department, product_line, top_k)` — Runs HNSW search in AlloyDB with hard filters on `department` and `product_line`, returns top-K most similar historical cases with their `effective_score`

### `llm_chain.py`

- `build_prompt(concern, plant, department, severity, top_k_results)` — Builds the dynamic prompt sent to Gemini, injecting retrieved historical cases as context
- `call_gemini(prompt)` — Calls `gemini-2.5-flash` via `google-genai` SDK with `vertexai=True` and `GEMINI_LOCATION=global`, returns the recommendation text and latency in ms

### `feedback_handler.py`

Applies feedback logic to `corrective_actions_vectors` in AlloyDB. Executes the UPDATE on `accept_count` / `reject_count` / `feedback_score`. No re-embedding — the vector is immutable.

### `corrective_action_validator.py`

Three-level validator (ADR-001):

- **L1 — Statistical:** Required fields present (`concern_id`, `concern_description`, `corrective_action`)
- **L2 — AI:** Quasi-required fields (`department`, `product_line`) — rejects if missing
- **L3 — Business:** Plant rules, severity, collection point validation

---

## `/backend/tests` — Test Suite

One test file per module or endpoint. All run with `pytest` before every PR (CI via GitHub Actions).

| File | What it tests | Tests |
|---|---|---|
| `test_health.py` | `GET /ai/health` — AlloyDB + Vertex AI connected | 3 |
| `test_ingest_endpoint.py` | `POST /corrective-actions/ingest` — valid and invalid cases | 6 |
| `test_search_endpoint.py` | `POST /corrective-actions/search` — vector search | 7 |
| `test_feedback_endpoint.py` | `POST /ai/feedback` — accept/reject/modify | 8 |
| `test_recommend_endpoint.py` | `POST /ai/recommend` — full RAG flow | — |
| `test_sync_new_ca.py` | Pipeline 3 — real-time sync | — |
| `test_validator.py` | Validator L1/L2/L3 — edge cases | — |

---

## `/docs` — Project Documentation

### `/docs/api`

Endpoint specs in Markdown — source of truth for the XOF team before implementing. `POST_corrective_actions_ingest.md` includes the Pydantic model and suggested router code.

### `/docs/milestones`

One MD file per completed task. Generated when closing each task. Contains: objectives, decisions made, commands executed, and final state. They are the technical history of the project.

### `/docs/standards`

`CONTRIBUTING.md` — Mandatory manual for any developer joining the project. Covers git workflow, repo structure, flake8 rules, and commit format.

---

## `/infra` — Infrastructure as Code (Terraform)

### `/infra/environments/dev` | `/uat` | `/prod`

Three environments in three separate GCP Projects (ADR-002). Each folder has its own Terraform variable files but shares the same modules. Deploying to production requires passing through dev and uat first.

| Environment | GCP Project | Purpose |
|---|---|---|
| `dev` | `ragai-dev` | XOF team development and testing |
| `uat` | `ragai-uat` | UAT with Ford Process Coaches |
| `prod` | `ragai-prod` | Production — MAP, FTM, Valencia plants |

> **Current status (M4):** Only `ragai-staging` is active. dev/uat/prod projects are created in M5.

---

## Root Files

| File | Purpose |
|---|---|
| `Dockerfile` | Single image for all environments — built with `gcloud builds submit` |
| `cloudbuild.yaml` | CI/CD pipeline in Cloud Build — build → push → deploy to Cloud Run |
| `requirements.txt` | Pinned Python dependencies (`fastapi==0.115.0`, `google-genai>=1.14.0`, etc.) |
| `pytest.ini` | pytest configuration — markers, paths, asyncio mode |
| `conftest.py` | Shared fixtures for the entire test suite |
| `README.md` | Quick onboarding — how to run the project locally |

---

## End-to-End Data Flow

```
Process Coach types concern in WISOHUB
         ↓
POST /ai/recommend
         ↓
middleware/          ← validates request
         ↓
routers/recommend.py
         ↓
rag/retriever.py     → embed_query()     → Vertex AI (text-embedding-004)
                     → search_similar()  → AlloyDB HNSW (dept + product_line filter)
         ↓
rag/llm_chain.py     → build_prompt()
                     → call_gemini()     → Vertex AI (gemini-2.5-flash, global)
         ↓
models/recommend.py  ← RecommendResponse (recommendation + sources + confidence_score)
         ↓
JSON response → WISOHUB Tip Board modal
         ↓
Coach clicks 👍/👎
         ↓
POST /ai/feedback
         ↓
rag/feedback_handler.py → UPDATE feedback_score in AlloyDB (no re-embedding)
                        → INSERT into BigQuery feedback_log (analytics only)
```

---

## Rules That Cannot Change Without an ADR

1. **Embedding model:** `text-embedding-004` (768 dims) — changing requires re-embedding the entire corpus
2. **chunk_text** = `concern_description + corrective_action` only (ADR-002)
3. **effective_score** = `similarity × feedback_score` — never persisted, always calculated in Python at retrieval time
4. **Feedback** operates on `alloydb_id` (integer PK), not on `concern_id`
5. **AlloyDB password** must never contain `#` — causes truncation in env var parsing

---

*Generated: June 2026 — M4 active*  
*Owner: rag-sp@mm4.me | Repo: devmm4git/wisorag-corrections*
