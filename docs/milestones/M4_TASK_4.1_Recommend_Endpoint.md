# M4 — Task 4.1: POST /ai/recommend (Gemini LLM Endpoint)

> **Proyecto:** WISO-AI / IPQ-AI — FXVIEW COMPANY  
> **Vendor:** XOF India  
> **Milestone:** M4 — React & SwiftUI Frontend Integration + UAT  
> **Task:** 4.1 — Backend: Gemini LLM Recommend Endpoint  
> **Branch:** `feat/m4-task-4.1-recommend-endpoint`  
> **Estado:** ✅ COMPLETADO  
> **Fecha:** Junio 2026  

---

## Objetivo

Implementar el endpoint `POST /ai/recommend` — el único endpoint de backend pendiente
al inicio de M4. Este endpoint es el core del sistema WISO-AI: recibe un concern de
calidad del Tip Board y retorna una recomendación generada por Gemini LLM basada en
corrective actions históricas similares.

**Desbloquea:** Task 4.2 (React) y Task 4.4 (SwiftUI) — ambas dependen de este endpoint.

---

## Endpoint

```
POST /ai/recommend
```

### Request

```json
{
  "plant": "MAP",
  "department": "PAINT",
  "product_line": "RANGER",
  "concern_description": "LEFT REAR BLACKOUT TAPE DAMAGED",
  "concern_id": "C_20240508_001",
  "collection_point": "16S LEFT REAR",
  "severity": "A",
  "charged_zone": "P TEAM 7",
  "vin_number": "TLE19823"
}
```

### Response

```json
{
  "recommendation": "Verify tape adhesion at station 16S...",
  "confidence_score": 0.87,
  "latency_ms": 3240,
  "fallback_scope": "LOCAL",
  "request_id": "req_abc123def456",
  "sources": [
    {
      "chunk_id": "MAP_PAINT_RANGER_20241101_C003",
      "similarity": 0.91,
      "effective_score": 0.87,
      "resolution_time_min": 18
    }
  ]
}
```

---

## Flujo interno

```
React/SwiftUI → POST /ai/recommend
    ↓
embed_query(concern_description)          ← retriever.py (existente)
    ↓
search_similar(dept, product_line, top_k=5)  ← retriever.py (existente)
    ↓
build_prompt(concern, top_k_results)      ← llm_chain.py (nuevo)
    ↓
Gemini LLM via Vertex AI                  ← llm_chain.py (nuevo)
    ↓
200 OK → RecommendResponse
```

---

## Archivos creados

| Archivo | Descripción |
|---|---|
| `backend/app/models/recommend.py` | Pydantic models: `RecommendRequest`, `RecommendResponse`, `SourceItem` |
| `backend/rag/llm_chain.py` | Gemini call + prompt builder (`build_prompt`, `call_gemini`) |
| `backend/app/routers/recommend.py` | FastAPI router — orquesta retriever + LLM chain |
| `backend/tests/test_recommend_endpoint.py` | 6 unit tests con mocks |

### Modificaciones

| Archivo | Cambio |
|---|---|
| `backend/app/main.py` | Registro del nuevo router: `app.include_router(recommend_router)` |
| `backend/rag/llm_chain.py` | Import corregido: `vertexai.preview.generative_models` (compatibilidad con `google-cloud-aiplatform==1.38.1`) |

---

## Modelo Gemini

```
Modelo:  gemini-pro (Vertex AI)
SDK:     google-cloud-aiplatform==1.38.1
Import:  vertexai.preview.generative_models.GenerativeModel
```

> **Nota técnica:** Se intentó actualizar el SDK a `1.156.0` pero generó conflicto con
> `langchain-google-vertexai==0.0.1` que pinea exactamente `1.38.1`. Decisión: mantener
> `1.38.1` y usar `vertexai.preview.generative_models` — compatible y sin riesgo para
> los endpoints de M3 ya en producción.

---

## Prompt Template

```
You are a manufacturing quality assistant. Based on similar historical cases,
suggest a corrective action for this concern.

CONCERN: {concern_description}
PLANT: {plant} | DEPARTMENT: {department} | SEVERITY: {severity}

SIMILAR HISTORICAL CASES:
{top_k_results}

Provide a concise, actionable recommendation in 2-3 sentences.
End with: "Based on {N} similar cases in {department}."
```

---

## Latency Budget

| Componente | Target |
|---|---|
| `embed_query` (Vertex AI) | < 100ms |
| `search_similar` (AlloyDB HNSW) | < 100ms |
| Gemini LLM generation | < 3,000ms |
| API overhead | < 200ms |
| **TOTAL end-to-end** | **< 5,000ms** |

---

## Tests

```
backend/tests/test_recommend_endpoint.py

test_recommend_success                    PASSED
test_recommend_no_results                 PASSED
test_recommend_missing_concern_description PASSED
test_recommend_missing_plant              PASSED
test_recommend_embed_failure              PASSED
test_recommend_gemini_failure             PASSED

6 passed — todos con mocks (sin llamadas reales a GCP)
```

**Estrategia de mocks:**
- `embed_query` → `AsyncMock` retorna vector `[0.1] * 768`
- `search_similar` → `AsyncMock` retorna lista de resultados simulados
- `call_gemini` → `Mock` retorna `(texto, latency_ms)`

---

## Error Handling

| Escenario | HTTP Code | Detalle |
|---|---|---|
| `embed_query` falla | `502` | `"Embedding service unavailable"` |
| `search_similar` falla | `502` | `"Vector search failed"` |
| Sin resultados similares | `404` | `"No similar historical cases found"` |
| Gemini falla | `502` | `"LLM service unavailable"` |
| Request inválido | `422` | Validación Pydantic automática |

---

## Git Workflow

```bash
# Branch
git checkout -b feat/m4-task-4.1-recommend-endpoint

# Validación pre-commit
flake8 backend/ --max-line-length=100 --exclude=__pycache__,.venv
# Output: (vacío — código limpio ✅)

pytest backend/tests/test_recommend_endpoint.py -v
# Output: 6 passed ✅

# Commit
git add .
git commit -m "feat(recommend): add POST /ai/recommend Gemini LLM endpoint — Task 4.1"
git push origin feat/m4-task-4.1-recommend-endpoint

# PR
# base: develop | reviewer: wmssaas-project | Squash and merge
```

---

## Definición de Done ✅

- [x] Endpoint `POST /ai/recommend` implementado y registrado en `main.py`
- [x] Pydantic models con Pydantic V2 (`json_schema_extra`)
- [x] `llm_chain.py` con `build_prompt` y `call_gemini` separados del router
- [x] 6 tests unitarios — todos PASSED
- [x] `flake8` — sin errores
- [x] Import SDK corregido para compatibilidad con `google-cloud-aiplatform==1.38.1`
- [x] `requirements.txt` sin cambios (stack M3 preservado)
- [x] Branch pusheado — PR abierto hacia `develop`

---

## Siguiente task desbloqueada

Con `POST /ai/recommend` live, se desbloquean en **paralelo**:

- **Task 4.2** — React: `AIRecommendationPanel` component
- **Task 4.4** — SwiftUI: `AIRecommendationView`

> ⚠️ Recordatorio: Para Tasks 4.2–4.5 (frontend), consultar con Manager (rag-sp)
> antes de arrancar — el approach de frontend será simplificado respecto al plan original.

---

*Documento generado al cierre de Task 4.1 — Junio 2026*  
*Owner: rag-sp@mm4.me | Proyecto: WISO-AI / IPQ-AI*
