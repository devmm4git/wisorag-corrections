# WISO-AI — M2 Task 2.3 & 2.4: Text Chunking + Vertex AI Embeddings
## ADR-002: Semantic chunking strategy + 768-dim embedding generation

---

## Context

**What does this task do?**
Defines and implements the text chunking strategy (ADR-002) and
the embedding generation pipeline using Vertex AI `text-embedding-004`.

**Why are 2.3 and 2.4 combined?**
They are tightly coupled — the chunk text directly feeds the
embedding model. The chunking strategy was defined alongside
the embedding implementation in `ingest_historical.py`.

**These were implemented as part of Task 2.2** — documented
separately for clarity.

---

## Task 2.3 — Text Chunking Strategy (ADR-002)

### The decision

```
WRONG — metadata in embedding (contaminates semantic search):
chunk_text = """
Department: PAINT
Plant: MAP
Severity: A
Collection Point: 165-Q LEFT REAR
Product Line: RANGER

Concern: LEFT REAR BLACKOUT TAPE DAMAGED
Corrective Action: Replaced tape applicator nozzle...
"""

CORRECT — semantic only (ADR-002):
chunk_text = """
Concern: LEFT REAR BLACKOUT TAPE DAMAGED

Corrective Action: Replaced tape applicator nozzle...
"""

Metadata stays as separate columns for hard filters:
WHERE department = 'PAINT' AND product_line = 'RANGER'
```

### Why this matters

```
RAG retrieval query:
    SELECT chunk_text, 1 - (embedding <=> $query_vector) AS similarity
    FROM corrective_actions_vectors
    WHERE department = 'PAINT'        ← hard filter (metadata column)
    AND product_line = 'RANGER'       ← hard filter (metadata column)
    ORDER BY embedding <=> $query_vector  ← semantic similarity
    LIMIT 5;

If metadata is IN the embedding:
→ "PAINT" has weight in the vector
→ May retrieve PAINT records that are NOT semantically similar
→ Confuses semantic similarity with filter terms ❌

If metadata is SEPARATE:
→ WHERE clause handles filtering efficiently
→ Vector search handles semantic similarity cleanly ✅
```

### Implementation — build_chunk_text()

```python
def build_chunk_text(record: dict) -> str:
    """
    Build semantic chunk text for embedding.
    ONLY Concern + Corrective Action — NO metadata.
    Metadata goes as separate columns for hard filters (WHERE clause).

    Design decision (ADR-002):
    - Embedding = semantic meaning of problem + solution
    - Metadata = department, plant, product_line (hard filters)
    """
    concern = record.get('concern_description', '').strip()
    corrective = record.get('corrective_action', '').strip()
    return f"Concern: {concern}\n\nCorrective Action: {corrective}"
```

---

## Task 2.4 — Vertex AI Embedding Generation

### Model used
```
Model:      text-embedding-004
Provider:   Google Vertex AI
Dimensions: 768
Project:    ragai-staging
Location:   us-central1
```

### Why text-embedding-004?
```
text-embedding-004 is Google's latest general-purpose embedding model.
768 dims is the standard for AlloyDB pgvector HNSW indexes.
Multilingual — supports EN, ES, PT, FR, ZH (required for WISOHUB).
Better semantic understanding than ada-002 for technical text.
```

### Implementation — generate_embeddings()

```python
def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Generate 768-dim embeddings via Vertex AI text-embedding-004.
    Processes in batches of 10 to respect API quotas.
    """
    aiplatform.init(
        project=settings.vertex_ai_project,
        location=settings.vertex_ai_location
    )

    from vertexai.language_models import TextEmbeddingModel
    model = TextEmbeddingModel.from_pretrained("text-embedding-004")

    embeddings = []
    batch_size = 10

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(texts) + batch_size - 1) // batch_size
        logger.info(f"Embedding batch {batch_num}/{total_batches}...")
        batch_embeddings = model.get_embeddings(batch)
        embeddings.extend([e.values for e in batch_embeddings])

    return embeddings  # list of list[float], each with 768 values
```

### Single record version — generate_single_embedding()

Used by `sync_new_ca.py` (Pipeline 3) for real-time sync:

```python
def generate_single_embedding(text: str) -> list[float]:
    """
    Generate a single 768-dim embedding.
    No batching — single record for real-time performance.
    """
    aiplatform.init(
        project=settings.vertex_ai_project,
        location=settings.vertex_ai_location
    )
    from vertexai.language_models import TextEmbeddingModel
    model = TextEmbeddingModel.from_pretrained("text-embedding-004")
    result = model.get_embeddings([text])
    return result[0].values
```

---

## Git Workflow

### Step 1 — These tasks were part of PR #5

```bash
git checkout develop
git pull origin develop
git checkout -b fix/chunk-text-semantic-only
```

---

### Step 2 — Changes made

Updated `backend/pipelines/ingest_historical.py`:

- `build_chunk_text()` → removed metadata from chunk text
- `insert_to_alloydb()` → removed `chunk_id` from INSERT

---

### Step 3 — Run flake8

```bash
flake8 backend/ --max-line-length=100 --exclude=__pycache__,.venv
# No output → clean ✅
```

---

### Step 4 — Commit and push

```bash
git add backend/pipelines/ingest_historical.py
git commit -m "fix(pipeline): separate embedding from metadata — ADR-002

Chunk text now contains ONLY semantic content:
  Concern: [text]
  Corrective Action: [text]

Metadata (department, plant, product_line, severity,
collection_point) stays as separate columns for hard
filters in WHERE clause — not embedded."

git push origin fix/chunk-text-semantic-only
```

---

### Step 5 — Verify embedding quality in AlloyDB

```bash
PGPASSWORD='WisoAI2024#Staging' psql \
  "host=34.60.92.141 port=5432 user=postgres dbname=wiso_ai_db sslmode=require" \
  -c "SELECT concern_id, department, product_line,
             LEFT(chunk_text, 80) as chunk_preview
      FROM corrective_actions_vectors
      ORDER BY id LIMIT 5;"
```

**Expected output — chunk_text must NOT contain department/plant:**
```
 concern_id | department | product_line | chunk_preview
------------+------------+--------------+-----------------------------------------------
 C001       | PAINT      | RANGER       | Concern: LEFT REAR BLACKOUT TAPE DAMAGED
            |            |              | Corrective Action: ...
```

✅ `PAINT` and `RANGER` appear as columns — NOT inside `chunk_text`.

---

### Step 6 — Clean up

```bash
git checkout develop
git pull origin develop
git branch -D fix/chunk-text-semantic-only
```

---

## Task Summary

| Item | Decision | Status |
|---|---|---|
| Chunking strategy | Concern + CA only (ADR-002) | ✅ |
| Metadata in embedding | NO — separate columns | ✅ |
| Embedding model | `text-embedding-004` | ✅ |
| Embedding dimensions | 768 | ✅ |
| Batch size | 10 records | ✅ |
| Multilingual support | Yes (EN, ES, PT, FR, ZH) | ✅ |
| Latency (batch) | ~1s per batch of 10 | ✅ |
| Latency (single) | ~2s per record | ✅ |

*Last updated: June 2026 — M2 Tasks 2.3 & 2.4 closed*
