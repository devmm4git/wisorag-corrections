# WISO-AI — API Contracts

**Base URL:** `https://wiso-ai-api-353440068506.us-central1.run.app`  
**Swagger UI:** `https://wiso-ai-api-353440068506.us-central1.run.app/docs`  
**Content-Type:** `application/json`  
**Auth:** Bearer token (GCP)

---

## Endpoints Summary

| Method | Path | Purpose |
|---|---|---|
| GET | `/ai/health` | Service health check |
| POST | `/ai/recommend` | Get AI recommendation for a concern |
| POST | `/ai/feedback` | Submit accept / reject feedback |
| POST | `/corrective-actions/ingest` | Ingest new corrective action |
| POST | `/corrective-actions/search` | Vector search (no Gemini) |

---

---

## 1. GET `/ai/health`

Checks connectivity to AlloyDB and Vertex AI. No request body required.

### Response `200 OK`

```json
{
  "status": "healthy",
  "alloydb": "connected",
  "vertex_ai": "reachable"
}
```

### Response `503 Service Unavailable`

```json
{
  "status": "unhealthy",
  "alloydb": "disconnected",
  "vertex_ai": "reachable"
}
```

---

---

## 2. POST `/ai/recommend`

Main endpoint. Receives a quality concern from the Process Coach, runs RAG retrieval against AlloyDB, calls Gemini, and returns an AI-generated corrective action recommendation.

**Latency target: < 5,000 ms**

### Request Body

| Field | Type | Required | Description | Example |
|---|---|---|---|---|
| `plant` | string | ✅ | Plant code | `"MAP"` |
| `department` | string | ✅ | Manufacturing department | `"PAINT"` |
| `product_line` | string | ✅ | Vehicle product line | `"RANGER"` |
| `concern_description` | string | ✅ Min 5 chars | Concern text typed by coach | `"LEFT REAR BLACKOUT TAPE DAMAGED"` |
| `concern_id` | string | ✅ | Unique concern identifier | `"C_20240508_001"` |
| `collection_point` | string | ❌ | Physical location in plant | `"16S LEFT REAR"` |
| `severity` | string | ❌ | Severity level (A, B, C) | `"A"` |
| `charged_zone` | string | ❌ | Team responsibility zone | `"P TEAM 7"` |
| `vin_number` | string | ❌ | Affected vehicle VIN | `"TLE19823"` |

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

### Response `200 OK`

| Field | Type | Description | Example |
|---|---|---|---|
| `recommendation` | string | Gemini-generated corrective action text | `"Verify tape adhesion at station 16S..."` |
| `confidence_score` | float (0.0–1.0) | Average effective_score of sources used | `0.87` |
| `latency_ms` | integer | Total pipeline latency in milliseconds | `3240` |
| `fallback_scope` | string | Retrieval scope used (`LOCAL` / `CROSS_PLANT` / `DEPT_ONLY`) | `"LOCAL"` |
| `request_id` | string | Unique request identifier | `"req_abc123def456"` |
| `sources` | array | Historical cases used as context (see SourceItem below) | `[...]` |

**SourceItem fields:**

| Field | Type | Description |
|---|---|---|
| `alloydb_id` | integer | Primary key in AlloyDB — use this for feedback |
| `chunk_id` | string | concern_id of the historical case |
| `similarity` | float | Cosine similarity score (0.0–1.0) |
| `effective_score` | float | similarity × feedback_score |
| `resolution_time_min` | integer \| null | How long it took to resolve |
| `concern_description` | string \| null | Original concern text |
| `corrective_action` | string \| null | Historical corrective action applied |

```json
{
  "recommendation": "Verify tape adhesion at station 16S. Replace damaged tape on affected units and adjust applicator pressure to 45 PSI. Inspect 5 consecutive units before resuming production. Based on 3 similar cases in PAINT.",
  "confidence_score": 0.87,
  "latency_ms": 3240,
  "fallback_scope": "LOCAL",
  "request_id": "req_abc123def456",
  "sources": [
    {
      "alloydb_id": 12,
      "chunk_id": "C_20240101_042",
      "similarity": 0.9341,
      "effective_score": 0.9341,
      "resolution_time_min": 18,
      "concern_description": "LEFT REAR TAPE PEELING AT STATION 16S",
      "corrective_action": "Replaced tape and recalibrated applicator pressure."
    }
  ]
}
```

### Error Responses

| HTTP Code | Condition |
|---|---|
| `404 Not Found` | No similar historical cases found in AlloyDB |
| `502 Bad Gateway` | Vertex AI embedding service unavailable |
| `502 Bad Gateway` | Gemini LLM service unavailable |
| `422 Unprocessable` | Request body fails validation (missing required field) |

```json
{ "detail": "No similar historical cases found for this concern." }
{ "detail": "Embedding service unavailable" }
{ "detail": "LLM service unavailable" }
```

---

---

## 3. POST `/ai/feedback`

Submits coach feedback (accept or reject) for a recommendation. Updates `feedback_score` in AlloyDB — no re-embedding occurs. Also logs to BigQuery for analytics.

**Use `alloydb_id` from the `sources[]` array returned by `/ai/recommend`.**

### Request Body

| Field | Type | Required | Description | Example |
|---|---|---|---|---|
| `alloydb_id` | integer | ✅ | PK of the AlloyDB record to update | `12` |
| `action` | string | ✅ | One of: `"ACCEPT"`, `"REJECT"`, `"MODIFY"` | `"ACCEPT"` |
| `request_id` | string | ✅ | `request_id` from the `/ai/recommend` response | `"req_abc123def456"` |
| `modified_text` | string | ❌ | Required only if `action = "MODIFY"` | `"Adjusted action: ..."` |
| `concern_id` | string | ❌ | For audit log in BigQuery | `"C_20240508_001"` |

```json
{
  "alloydb_id": 12,
  "action": "ACCEPT",
  "request_id": "req_abc123def456",
  "concern_id": "C_20240508_001"
}
```

```json
{
  "alloydb_id": 12,
  "action": "MODIFY",
  "request_id": "req_abc123def456",
  "modified_text": "Replaced tape and added secondary inspection step at station 17.",
  "concern_id": "C_20240508_001"
}
```

### Response `200 OK`

| Field | Type | Description | Example |
|---|---|---|---|
| `success` | boolean | Operation result | `true` |
| `alloydb_id` | integer | Record updated | `12` |
| `action` | string | Action applied | `"ACCEPT"` |
| `new_feedback_score` | float | Updated score after applying feedback | `0.92` |
| `message` | string | Confirmation message | `"Feedback recorded successfully."` |

```json
{
  "success": true,
  "alloydb_id": 12,
  "action": "ACCEPT",
  "new_feedback_score": 0.92,
  "message": "Feedback recorded successfully."
}
```

### Error Responses

| HTTP Code | Condition |
|---|---|
| `404 Not Found` | `alloydb_id` does not exist |
| `400 Bad Request` | `action = "MODIFY"` but `modified_text` is missing |
| `422 Unprocessable` | Invalid `action` value |

---

---

## 4. POST `/corrective-actions/ingest`

Ingests a new corrective action into the RAG knowledge base. Validates, embeds via Vertex AI (`text-embedding-004`, 768 dims), and inserts into AlloyDB. Available for retrieval within 30 seconds.

**Called by WISOHUB automatically when a concern is resolved.**

### Request Body

| Field | Type | Required | Description | Example |
|---|---|---|---|---|
| `concern_id` | string | ✅ L1 | Unique concern identifier | `"C_20240508_001"` |
| `concern_description` | string | ✅ L1 | Original concern text | `"LEFT REAR BLACKOUT TAPE DAMAGED"` |
| `corrective_action` | string | ✅ L1 Min 30 chars | Action taken — minimum 5 words, 30 chars | `"Replaced tape and adjusted pressure..."` |
| `department` | string | ⚠️ L2 | Manufacturing department — used as hard filter | `"PAINT"` |
| `product_line` | string | ⚠️ L2 | Vehicle product line — used as hard filter | `"RANGER"` |
| `plant` | string | ❌ L3 | Plant code | `"MAP"` |
| `severity` | string | ❌ L3 | Severity level | `"A"` |
| `collection_point` | string | ❌ L3 | Physical location in plant | `"165-Q LEFT REAR"` |
| `charged_zone` | string | ❌ L3 | Team responsibility zone | `"P TEAM 7"` |
| `resolution_time_min` | integer | ❌ L3 | Minutes to resolve | `18` |
| `coach_cds_id` | string | ❌ | Coach ID — BigQuery audit only, NOT stored in AlloyDB | `"CDS12345"` |
| `vin_number` | string | ❌ | Affected VIN — BigQuery audit only, NOT stored in AlloyDB | `"TLE19823"` |

> **L1** = hard reject if missing (400) · **L2** = record ingested but won't appear in filtered searches · **L3** = stored as NULL if missing

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

### Response `201 Created`

| Field | Type | Description | Example |
|---|---|---|---|
| `success` | boolean | Operation result | `true` |
| `concern_id` | string | Processed concern ID | `"C_20240508_001"` |
| `alloydb_id` | integer | PK assigned in AlloyDB | `17` |
| `embedding_dims` | integer | Vector dimensions — always 768 | `768` |
| `latency_ms` | float | Total latency in ms. Target < 30,000 ms | `6956.4` |
| `message` | string | Confirmation message | `"Corrective action synced successfully."` |

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

### Error Responses

| HTTP Code | Condition | `rejection_reason` |
|---|---|---|
| `400 Bad Request` | Missing L1 required field | `"Missing required field: 'concern_description'."` |
| `400 Bad Request` | `corrective_action` too short | `"Text too short: 1 words, 2 chars. Minimum: 5 words, 30 chars."` |
| `409 Conflict` | `concern_id` already exists in AlloyDB | `"Record already exists in AlloyDB (ON CONFLICT DO NOTHING)."` |
| `422 Unprocessable` | AI quality check failed | `"AI quality check failed: ..."` |
| `500 Internal Error` | Vertex AI embedding failed | `"Embedding generation failed: Vertex AI timeout after 10s."` |
| `500 Internal Error` | AlloyDB INSERT failed | `"AlloyDB insert failed: ..."` |

```json
{
  "success": false,
  "concern_id": "C_20240508_001",
  "rejection_reason": "Text too short: 1 words, 2 chars. Minimum: 5 words, 30 chars.",
  "message": "Corrective action rejected — not synced."
}
```

> **409 Conflict** should be treated as idempotent success on the client side.  
> **500** → retry with exponential backoff, max 3 attempts.

---

---

## 5. POST `/corrective-actions/search`

Direct vector search against AlloyDB using HNSW cosine similarity. Does **not** call Gemini — returns raw historical cases ranked by similarity. Use for debugging or building custom UIs that need raw results.

### Request Body

| Field | Type | Required | Description | Example |
|---|---|---|---|---|
| `concern_description` | string | ✅ | Query text to search | `"tape damaged rear panel"` |
| `department` | string | ✅ | Hard filter — must match exactly | `"PAINT"` |
| `product_line` | string | ✅ | Hard filter — must match exactly | `"RANGER"` |
| `top_k` | integer | ❌ Default: 5 | Number of results to return (max 10) | `5` |

```json
{
  "concern_description": "tape damaged rear panel",
  "department": "PAINT",
  "product_line": "RANGER",
  "top_k": 5
}
```

### Response `200 OK`

| Field | Type | Description |
|---|---|---|
| `results` | array | List of matching historical cases |
| `count` | integer | Number of results returned |
| `latency_ms` | integer | Search latency in milliseconds |

**Each result item:**

| Field | Type | Description |
|---|---|---|
| `alloydb_id` | integer | PK in AlloyDB |
| `concern_id` | string | Original concern ID |
| `concern_description` | string | Historical concern text |
| `corrective_action` | string | Historical corrective action |
| `department` | string | Department |
| `product_line` | string | Product line |
| `similarity` | float | Cosine similarity (0.0–1.0) |
| `feedback_score` | float | Accumulated feedback score |
| `effective_score` | float | similarity × feedback_score |
| `resolution_time_min` | integer \| null | Resolution time |

```json
{
  "results": [
    {
      "alloydb_id": 12,
      "concern_id": "C_20240101_042",
      "concern_description": "LEFT REAR TAPE PEELING AT STATION 16S",
      "corrective_action": "Replaced tape and recalibrated applicator pressure.",
      "department": "PAINT",
      "product_line": "RANGER",
      "similarity": 0.9341,
      "feedback_score": 1.0,
      "effective_score": 0.9341,
      "resolution_time_min": 18
    }
  ],
  "count": 1,
  "latency_ms": 412
}
```

### Error Responses

| HTTP Code | Condition |
|---|---|
| `404 Not Found` | No results found for the given filters |
| `502 Bad Gateway` | Embedding service unavailable |

---

---

## HTTP Status Codes Reference

| Code | Meaning | When |
|---|---|---|
| `200 OK` | Success | GET health, POST search, POST feedback |
| `201 Created` | Record created | POST ingest (new record) |
| `400 Bad Request` | Client error — fix the request | Missing/invalid fields |
| `404 Not Found` | No data found | No similar cases, alloydb_id not found |
| `409 Conflict` | Duplicate record | concern_id already exists (treat as success) |
| `422 Unprocessable` | Schema validation failed | Wrong types, missing required fields |
| `502 Bad Gateway` | Upstream GCP service error | Vertex AI / Gemini unavailable |
| `500 Internal Error` | Server error | AlloyDB write failed |

---

## Key Rules for Frontend Developers

1. **Always use `alloydb_id`** (not `concern_id`) when calling `/ai/feedback` — this is the integer PK from `sources[]` in the recommend response.
2. **Save `request_id`** from the `/ai/recommend` response in component state — it's required for the feedback call.
3. **409 on `/ingest`** is safe to treat as success — the record already exists.
4. **500 on `/ingest`** → retry up to 3 times with exponential backoff before alerting.
5. **`department` and `product_line`** are hard filters — results will be empty if these don't exactly match values in AlloyDB (`PAINT`, `BIW`, `CHASSIS` / `RANGER`, `BRONCO`, `TRANSIT`).

---

*Document version: June 2026 — M4 active*  
*Owner: rag-sp@mm4.me*  
*Swagger: https://wiso-ai-api-353440068506.us-central1.run.app/docs*
