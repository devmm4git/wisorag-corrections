# WISO-AI — Guía de Estructura del Proyecto

**Proyecto:** IPQ-AI / WISO-AI  
**Repo:** `wisorag-corrections` (org: `devmm4git`)  
**Branch principal:** `develop`  
**Fecha:** Junio 2026  
**Owner:** rag-sp@mm4.me

---

## Árbol completo del repositorio

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
│   │   └── (archivos MD por tarea)
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

## `/backend` — Todo el código Python

Es la raíz de todo el código ejecutable del proyecto. El Dockerfile apunta aquí para construir la imagen que corre en Cloud Run. Ningún código Python vive fuera de esta carpeta.

---

## `/backend/app` — La aplicación FastAPI (cara pública del sistema)

Todo lo que el mundo exterior (WISOHUB, dashboard HTML, React) ve y consume. Se divide en tres subcarpetas con responsabilidades separadas.

### `/backend/app/main.py`

El punto de entrada de la aplicación. Instancia FastAPI, registra todos los routers, configura CORS y el middleware global. Es el primer archivo que ejecuta `uvicorn` al arrancar el servidor.

```
uvicorn backend.app.main:app --host 0.0.0.0 --port 8080
```

### `/backend/app/routers` — Endpoints HTTP

Un archivo por grupo de rutas. Define qué sucede cuando llega cada request HTTP.

| Archivo | Endpoint | Descripción |
|---|---|---|
| `recommend.py` | `POST /ai/recommend` | Recibe el concern del Process Coach → embed → RAG search → Gemini → devuelve recomendación |
| `corrective_actions.py` | `POST /corrective-actions/ingest` | Recibe CA nueva de WISOHUB → valida → embeddea → guarda en AlloyDB |
| `search.py` | `POST /corrective-actions/search` | Búsqueda vectorial directa en AlloyDB sin pasar por Gemini |
| `feedback.py` | `POST /ai/feedback` | Recibe 👍/👎 del coach → actualiza `feedback_score` en AlloyDB |
| `health.py` | `GET /ai/health` | Verifica conectividad con AlloyDB y Vertex AI |

### `/backend/app/models` — Contratos Pydantic (fuente del Swagger)

Definen exactamente qué JSON acepta cada endpoint y qué JSON devuelve. FastAPI lee estas clases y genera automáticamente la documentación en `/docs` (Swagger UI). Si el request no cumple el contrato, FastAPI lo rechaza con HTTP 422 antes de que el router procese nada.

| Archivo | Clases que define |
|---|---|
| `recommend.py` | `RecommendRequest`, `RecommendResponse`, `SourceItem` |
| `corrective_action.py` | `CorrectiveActionRequest`, `CorrectiveActionResponse` |
| `feedback.py` | `FeedbackRequest`, `FeedbackResponse` |
| `search.py` | `SearchRequest`, `SearchResponse` |

### `/backend/app/middleware` — Capa transversal

Código que se ejecuta en **cada request** antes de llegar al router. Actualmente preparado para:

- **Autenticación** — validar que el request viene de una fuente autorizada
- **Logging** — registrar llamadas para auditoría y debugging
- **Rate limiting** — proteger los endpoints contra abuso

---

## `/backend/config` — Configuración y secretos

### `settings.py`

Usa `pydantic-settings` para leer todas las variables de entorno al arrancar. En Cloud Run estas variables vienen de Secret Manager. Nunca hay credenciales hardcodeadas en el código.

Variables clave que gestiona:

```
ALLOYDB_HOST, ALLOYDB_USER, ALLOYDB_PASSWORD, ALLOYDB_DATABASE
VERTEX_AI_PROJECT, GEMINI_LOCATION
ENVIRONMENT (dev | uat | prod)
```

---

## `/backend/db` — Capa de base de datos

### `alloydb.py`

Maneja los connection pools hacia AlloyDB (Primary + Read Replicas). Expone funciones reutilizables `get_write_pool()` y `check_connection()` que todos los routers y pipelines usan. Nunca se abre una conexión directa fuera de este módulo.

### `alloydb.sql`

DDL completo de la tabla principal `corrective_actions_vectors`, incluyendo el índice HNSW para búsqueda vectorial (m=16, ef=64, distancia coseno). Es la fuente de verdad del esquema de AlloyDB.

### `bifquery.sql`

DDL de la tabla `feedback_log` en BigQuery (proyecto `simula-ipd-produ`). Registra cada 👍/👎 del coach para análisis de calidad — es analytics-only y no afecta el retrieval en tiempo real.

### `business_rules.sql`

Las queries SQL de UPDATE que aplican el feedback sobre `feedback_score`. Cuando un coach acepta una recomendación, `accept_count` sube; cuando rechaza, `reject_count` sube. El `feedback_score` se recalcula como proporción. No hay re-embedding.

---

## `/backend/pipelines` — Pipelines de datos

Scripts que mueven datos entre sistemas. No son endpoints HTTP — son procesos Python independientes.

### `ingest_historical.py` — Pipeline 1

Carga batch desde BigQuery (`tipbord_historical.corrective_actions`) hacia AlloyDB. Se ejecutó una vez al inicio del proyecto para cargar los 25 registros históricos. Puede ejecutarse periódicamente para sincronizar nuevos datos históricos.

```
BigQuery (25 CAs históricas) → ETL Python → embed → AlloyDB
```

### `sync_new_ca.py` — Pipeline 3

Sincronización en tiempo real. Se llama desde `POST /corrective-actions/ingest` cada vez que WISOHUB registra una nueva corrective action. Debe completarse en menos de 30 segundos.

```
WISOHUB → POST /ingest → sync_new_ca.py → embed → AlloyDB
```

---

## `/backend/rag` — Capa de inteligencia RAG

El corazón del sistema. Aquí vive toda la lógica de Retrieval-Augmented Generation. Los routers no llaman a AlloyDB ni a Vertex AI directamente — siempre pasan por este módulo.

### `retriever.py`

Dos funciones principales:

- `embed_query(text)` — Llama a Vertex AI (`text-embedding-004`, 768 dims) para convertir el concern del coach en un vector
- `search_similar(query_vector, department, product_line, top_k)` — Ejecuta la búsqueda HNSW en AlloyDB con filtros duros de `department` y `product_line`, retorna los top-K casos históricos más similares con su `effective_score`

### `llm_chain.py`

- `build_prompt(concern, plant, department, severity, top_k_results)` — Construye el prompt dinámico que se envía a Gemini, inyectando los casos históricos recuperados como contexto
- `call_gemini(prompt)` — Llama a `gemini-2.5-flash` via `google-genai` SDK con `vertexai=True` y `GEMINI_LOCATION=global`, retorna el texto de recomendación y la latencia en ms

### `feedback_handler.py`

Aplica la lógica de feedback sobre `corrective_actions_vectors` en AlloyDB. Ejecuta los UPDATE de `accept_count` / `reject_count` / `feedback_score`. No hay re-embedding — el vector es inmutable.

### `corrective_action_validator.py`

Validador en tres niveles (ADR-001):

- **L1 — Estadístico:** Campos requeridos presentes (`concern_id`, `concern_description`, `corrective_action`)
- **L2 — IA:** Campos quasi-requeridos (`department`, `product_line`) — rechaza si faltan
- **L3 — Negocio:** Reglas de planta, severidad, collection point

---

## `/backend/tests` — Suite de pruebas

Un archivo de test por módulo o endpoint. Todos corren con `pytest` antes de cada PR (CI en GitHub Actions).

| Archivo | Qué prueba | Tests |
|---|---|---|
| `test_health.py` | `GET /ai/health` — AlloyDB + Vertex AI conectados | 3 |
| `test_ingest_endpoint.py` | `POST /corrective-actions/ingest` — casos válidos e inválidos | 6 |
| `test_search_endpoint.py` | `POST /corrective-actions/search` — búsqueda vectorial | 7 |
| `test_feedback_endpoint.py` | `POST /ai/feedback` — accept/reject/modify | 8 |
| `test_recommend_endpoint.py` | `POST /ai/recommend` — flujo RAG completo | — |
| `test_sync_new_ca.py` | Pipeline 3 — sincronización tiempo real | — |
| `test_validator.py` | Validator L1/L2/L3 — casos edge | — |

---

## `/docs` — Documentación del proyecto

### `/docs/api`

Specs de cada endpoint en Markdown — son la fuente de verdad para el equipo XOF antes de implementar. `POST_corrective_actions_ingest.md` incluye el Pydantic model y el router sugerido.

### `/docs/milestones`

Un archivo MD por tarea completada. Se generan al cerrar cada tarea y contienen: objetivos, decisiones tomadas, comandos ejecutados, y estado final. Son el historial técnico del proyecto.

### `/docs/standards`

`CONTRIBUTING.md` — Manual obligatorio para cualquier developer que se una al proyecto. Cubre git workflow, estructura del repo, reglas de flake8, y formato de commits.

---

## `/infra` — Infraestructura como código (Terraform)

### `/infra/environments/dev` | `/uat` | `/prod`

Tres entornos en tres GCP Projects separados (ADR-002). Cada carpeta tiene sus propios archivos de variables Terraform pero comparte los mismos módulos. El deploy a producción requiere haber pasado primero por dev y uat.

| Entorno | GCP Project | Uso |
|---|---|---|
| `dev` | `ragai-dev` | Desarrollo y pruebas del equipo XOF |
| `uat` | `ragai-uat` | UAT con Process Coaches de Ford |
| `prod` | `ragai-prod` | Producción — plantas MAP, FTM, Valencia |

> **Estado actual (M4):** Solo `ragai-staging` está activo. Los proyectos dev/uat/prod se crean en M5.

---

## Archivos raíz

| Archivo | Propósito |
|---|---|
| `Dockerfile` | Imagen única para todos los entornos — construida con `gcloud builds submit` |
| `cloudbuild.yaml` | Pipeline CI/CD en Cloud Build — build → push → deploy a Cloud Run |
| `requirements.txt` | Dependencias Python con versiones pinneadas (`fastapi==0.115.0`, `google-genai>=1.14.0`, etc.) |
| `pytest.ini` | Configuración de pytest — markers, paths, modo asyncio |
| `conftest.py` | Fixtures compartidas para toda la suite de tests |
| `README.md` | Onboarding rápido — cómo correr el proyecto localmente |

---

## Flujo de datos end-to-end

```
Process Coach tipea concern en WISOHUB
         ↓
POST /ai/recommend
         ↓
middleware/         ← valida request
         ↓
routers/recommend.py
         ↓
rag/retriever.py    → embed_query()      → Vertex AI (text-embedding-004)
                    → search_similar()   → AlloyDB HNSW (filtro dept + product_line)
         ↓
rag/llm_chain.py    → build_prompt()
                    → call_gemini()      → Vertex AI (gemini-2.5-flash, global)
         ↓
models/recommend.py ← RecommendResponse (recommendation + sources + confidence_score)
         ↓
JSON response → WISOHUB Tip Board modal
         ↓
Coach hace 👍/👎
         ↓
POST /ai/feedback
         ↓
rag/feedback_handler.py → UPDATE feedback_score en AlloyDB (sin re-embedding)
                        → INSERT en BigQuery feedback_log (analytics)
```

---

## Reglas que NO se pueden cambiar sin un ADR

1. **Embedding model:** `text-embedding-004` (768 dims) — cambiar requiere re-embeddear todo el corpus
2. **chunk_text** = `concern_description + corrective_action` únicamente (ADR-002)
3. **effective_score** = `similarity × feedback_score` — nunca se persiste, siempre se calcula en Python
4. **Feedback** opera sobre `alloydb_id` (PK integer), no sobre `concern_id`
5. **AlloyDB password** nunca debe contener `#` — causa truncamiento en env vars

---

*Generado: Junio 2026 — M4 activo*  
*Owner: rag-sp@mm4.me | Repo: devmm4git/wisorag-corrections*
