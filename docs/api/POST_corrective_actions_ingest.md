# WISO-AI — Endpoint Documentation

## `POST /corrective-actions/ingest`

> **Milestone:** M3 — FastAPI Backend
> **Llamado por:** `backend/pipelines/sync_new_ca.py` (implementado en M2 Task 2.7)
> **Swagger tag:** `corrective-actions` > **Auth:** Service Account `new-corrective-action-sa@ragai-staging.iam.gserviceaccount.com`

---

## Descripción

Recibe un nuevo corrective action del Process Coach via WISOHUB.
Valida, genera embedding (Vertex AI `text-embedding-004`, 768 dims)
y lo inserta en AlloyDB — disponible para RAG en < 30 segundos.

---

## Input Parameters

| Campo                 | Descripción                                                     | Tipo    | Requerido | Nivel Validator                         | Ejemplo                                                            |
| --------------------- | --------------------------------------------------------------- | ------- | --------- | --------------------------------------- | ------------------------------------------------------------------ |
| `concern_id`          | ID único del concern                                            | STRING  | ✅ YES    | L1 — Rechazo duro si falta              | `C_20240508_001`                                                   |
| `concern_description` | Texto del problema                                              | STRING  | ✅ YES    | L1 — Sin esto no hay embedding          | `LEFT REAR BLACKOUT TAPE DAMAGED`                                  |
| `corrective_action`   | Acción tomada por el coach. Mín 30 chars, mín 5 palabras        | STRING  | ✅ YES    | L1 — Texto principal del embedding      | `Verified tape at 16S, replaced 3 units, set applicator to 45 PSI` |
| `department`          | Departamento de manufactura. Filtro duro en retrieval           | STRING  | ⚠️ QUASI  | L2 — Entra pero sin retrieval por dept  | `PAINT`                                                            |
| `product_line`        | Línea de producto. Filtro duro en retrieval                     | STRING  | ⚠️ QUASI  | L2 — Entra pero sin retrieval por línea | `RANGER`                                                           |
| `plant`               | Planta. Contexto de ubicación                                   | STRING  | NO        | L3 — Entra con NULL                     | `MAP`                                                              |
| `severity`            | Severidad A/B/C                                                 | STRING  | NO        | L3 — Entra con NULL                     | `A`                                                                |
| `collection_point`    | Estación física dentro de la planta                             | STRING  | NO        | L3 — Entra con NULL                     | `165-Q LEFT REAR`                                                  |
| `charged_zone`        | Zona de responsabilidad del equipo                              | STRING  | NO        | L3 — Entra con NULL                     | `P TEAM 7 SPILLOUT`                                                |
| `resolution_time_min` | Minutos de resolución. Se guarda como `mttr_minutes` en AlloyDB | INTEGER | NO        | L3 — Entra con NULL                     | `18`                                                               |
| `coach_cds_id`        | ID del coach. Solo va a BigQuery audit log, **NO a AlloyDB**    | STRING  | NO        | —                                       | `CDS12345`                                                         |
| `vin_number`          | VIN afectado. Solo va a BigQuery audit log, **NO a AlloyDB**    | STRING  | NO        | —                                       | `TLE19823`                                                         |

---

## Reglas de validación — Lo que ve el coach en WISOHUB

```
L1 — Rechazo duro (400 Bad Request):
├── concern_id falta o vacío
├── concern_description falta o vacía
└── corrective_action falta, vacía, < 5 palabras o < 30 chars
    → Mensaje al coach: "Por favor describe con más detalle la acción tomada"

L2 — Warning silencioso (el record entra, 201 Created):
├── department falta → record NO aparecerá en filtros por departamento
└── product_line falta → record NO aparecerá en filtros por línea
    → El coach NO ve este warning — solo en logs internos

L3 — Info silencioso (el record entra, 201 Created):
├── plant, severity, collection_point, charged_zone,
    resolution_time_min → entran como NULL
    → El coach NO ve este warning — solo en logs internos
```

---

## Campos que van a BigQuery (NO a AlloyDB)

```
coach_cds_id  → BigQuery feedback_log — auditoría de quién ingresó el CA
vin_number    → BigQuery feedback_log — VIN del vehículo afectado
```

Estos campos se reciben en el payload pero NO se insertan en
`corrective_actions_vectors`. Se guardan en BigQuery para analytics.

---

## Output Parameters — 201 Created

| Campo            | Descripción                                  | Tipo    | Ejemplo                                  |
| ---------------- | -------------------------------------------- | ------- | ---------------------------------------- |
| `success`        | Resultado de la operación                    | BOOLEAN | `true`                                   |
| `concern_id`     | ID del concern procesado                     | STRING  | `C_20240508_001`                         |
| `alloydb_id`     | PK del registro en AlloyDB (`id` serial)     | INTEGER | `17`                                     |
| `embedding_dims` | Dimensiones del vector generado. Siempre 768 | INTEGER | `768`                                    |
| `latency_ms`     | Latencia total en ms. Target < 30,000ms      | FLOAT   | `6956.4`                                 |
| `message`        | Mensaje de confirmación                      | STRING  | `Corrective action synced successfully.` |

---

## Output Parameters — Error

| Campo              | Descripción               | Tipo    |
| ------------------ | ------------------------- | ------- |
| `success`          | Siempre `false` en error  | BOOLEAN |
| `concern_id`       | ID del concern que falló  | STRING  |
| `rejection_reason` | Razón legible del rechazo | STRING  |
| `message`          | Mensaje descriptivo       | STRING  |

---

## HTTP Status Codes

| HTTP Code            | Condición                                                               | `rejection_reason`                                                              | Acción del cliente                    |
| -------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------- |
| `201 Created`        | Record insertado exitosamente en AlloyDB                                | —                                                                               | Knowledge base actualizada            |
| `400 Bad Request`    | `concern_id`, `concern_description` o `corrective_action` falta o vacío | `Missing required field: 'X'`                                                   | Reintentar con payload completo       |
| `400 Bad Request`    | `corrective_action` < 5 palabras o < 30 chars                           | `Text too short: N words, N chars. Minimum: 5 words, 30 chars.`                 | Pedir al coach más detalle            |
| `400 Bad Request`    | Texto repetitivo o sin estructura semántica                             | `Low lexical diversity` / `Text does not appear to contain a complete sentence` | Pedir al coach descripción real       |
| `409 Conflict`       | `concern_id` ya existe en AlloyDB                                       | `Record already exists in AlloyDB`                                              | Idempotente — tratar como éxito       |
| `422 Unprocessable`  | AI validator rechaza calidad semántica                                  | `AI quality check failed: ...`                                                  | Log a BigQuery — revisar manualmente  |
| `500 Internal Error` | Vertex AI embedding falló o timeout                                     | `Embedding generation failed: ...`                                              | Retry con backoff exponencial (max 3) |
| `500 Internal Error` | AlloyDB INSERT falló                                                    | `AlloyDB insert failed: ...`                                                    | Alert DevOps — retry después de 30s   |

---

## Ejemplos completos — Request / Response

### ✅ Request exitoso

```json
{
  "concern_id": "C_20240508_001",
  "department": "PAINT",
  "product_line": "RANGER",
  "plant": "MAP",
  "severity": "A",
  "collection_point": "165-Q LEFT REAR",
  "concern_description": "LEFT REAR BLACKOUT TAPE DAMAGED during final assembly inspection",
  "corrective_action": "Verified tape adhesion at station 165, replaced tape on 3 units, adjusted applicator pressure to 45 PSI. Inspected 5 consecutive units with zero defects.",
  "resolution_time_min": 18,
  "coach_cds_id": "CDS12345",
  "vin_number": "TLE19823"
}
```

### ✅ Response 201 Created

```json
{
  "success": true,
  "concern_id": "C_20240508_001",
  "alloydb_id": 17,
  "embedding_dims": 768,
  "latency_ms": 6956.4,
  "message": "Corrective action synced successfully."
}
```

### ❌ Response 400 — corrective_action muy corto

```json
{
  "success": false,
  "concern_id": "C_20240508_001",
  "rejection_reason": "Text too short: 1 words, 2 chars. Minimum: 5 words, 30 chars.",
  "message": "Corrective action rejected — not synced."
}
```

### ❌ Response 400 — campo requerido faltante

```json
{
  "success": false,
  "concern_id": "C_20240508_001",
  "rejection_reason": "Missing required field: 'concern_description'. Level 1 fields are mandatory for embedding.",
  "message": "Corrective action rejected — not synced."
}
```

### ❌ Response 409 — concern_id duplicado

```json
{
  "success": false,
  "concern_id": "C_20240508_001",
  "rejection_reason": "Record already exists in AlloyDB (ON CONFLICT DO NOTHING).",
  "message": "Corrective action rejected — not synced."
}
```

### ❌ Response 500 — Vertex AI falló

```json
{
  "success": false,
  "concern_id": "C_20240508_001",
  "rejection_reason": "Embedding generation failed: Vertex AI timeout after 10s.",
  "message": "Corrective action rejected — not synced."
}
```

---

## Implementación en M3 — FastAPI

```python
# backend/app/routers/corrective_actions.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from backend.pipelines.sync_new_ca import sync_new_corrective_action

router = APIRouter(prefix="/corrective-actions", tags=["corrective-actions"])


class CorrectiveActionRequest(BaseModel):
    # L1 — Required
    concern_id: str = Field(..., description="Unique concern ID")
    concern_description: str = Field(..., description="Original concern text")
    corrective_action: str = Field(..., min_length=30, description="Action taken. Min 30 chars")

    # L2 — Quasi-required (hard filters)
    department: Optional[str] = Field(None, description="Manufacturing department")
    product_line: Optional[str] = Field(None, description="Vehicle product line")

    # L3 — Optional context
    plant: Optional[str] = None
    severity: Optional[str] = None
    collection_point: Optional[str] = None
    charged_zone: Optional[str] = None
    resolution_time_min: Optional[int] = None

    # BigQuery only — NOT stored in AlloyDB
    coach_cds_id: Optional[str] = None
    vin_number: Optional[str] = None


class CorrectiveActionResponse(BaseModel):
    success: bool
    concern_id: str
    alloydb_id: Optional[int] = None
    embedding_dims: Optional[int] = None
    latency_ms: Optional[float] = None
    message: str
    rejection_reason: Optional[str] = None


@router.post(
    "/ingest",
    response_model=CorrectiveActionResponse,
    status_code=201,
    summary="Ingest new corrective action into RAG knowledge base",
    description="Validates, embeds and inserts a corrective action into AlloyDB. Available for RAG retrieval within 30 seconds."
)
async def ingest_corrective_action(request: CorrectiveActionRequest):
    record = request.model_dump()
    result = await sync_new_corrective_action(record)

    if result.success:
        return CorrectiveActionResponse(**result.to_api_response())

    # Map rejection reasons to HTTP status codes
    reason = result.rejection_reason or ""
    if "already exists" in reason:
        raise HTTPException(status_code=409, detail=result.to_api_response())
    if "Embedding" in reason or "AlloyDB insert" in reason:
        raise HTTPException(status_code=500, detail=result.to_api_response())
    raise HTTPException(status_code=400, detail=result.to_api_response())
```

---

## Notas para M3

- El Pydantic model mapea `resolution_time_min` → `mttr_minutes` antes de llamar a `sync_new_corrective_action()`
- `coach_cds_id` y `vin_number` se reciben en el payload pero `sync_new_ca.py` los ignora para AlloyDB
- En M3 se agrega la lógica para mandarlos a BigQuery `feedback_log`
- El Swagger se genera automáticamente con FastAPI — este doc es la fuente de verdad

---

_Documento generado: Junio 2026 | WISO-AI M2 cierre_
_Para usar en M3 — FastAPI endpoint implementation_
