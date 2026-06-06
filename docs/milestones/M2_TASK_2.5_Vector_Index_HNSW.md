# WISO-AI — M2 Task 2.5: AlloyDB Vector Index Setup
## HNSW Index for <100ms semantic search

---

## Context

**What does this task do?**
Creates the HNSW (Hierarchical Navigable Small World) vector index
on the `embedding` column of `corrective_actions_vectors`, plus
btree indexes on hard filter columns.

**Why is this critical?**
Without the index, every semantic search performs a full table scan:

```
Without HNSW (full scan):
  16 records    → fast (no problem now)
  100,000 records → 3-5 seconds ❌
  1,000,000 records → minutes ❌

With HNSW:
  100,000 records → <10ms ✅
  1,000,000 records → <50ms ✅
  SAD target → <100ms ✅
```

**Prerequisites:** Task 2.1 (AlloyDB table created) and Task 2.4
(embeddings inserted) must be complete.

---

## How HNSW Works

```
Think of a city with 3 layers of maps:

Layer 3 (macro) → only main highways
Layer 2 (mid)   → important avenues
Layer 1 (micro) → all streets

Search process:
1. Enter at macro layer → find approximate zone
2. Go down to mid layer → get closer
3. Go down to micro layer → find exact neighbors

Result: arrives in milliseconds without scanning everything
```

### Parameters explained

```
m = 16
└── Connections per node in the graph
    Higher = more precise, more memory
    16 is the standard for production RAG systems

ef_construction = 64
└── Quality of the index at build time
    Higher = better quality, slower to build
    64 is the standard balance for staging

vector_cosine_ops
└── Cosine similarity — standard for text embeddings
    Measures angle between vectors (direction, not magnitude)
    Best for semantic similarity tasks
```

---

## Git Workflow

### Step 1 — No code changes required
This task is SQL only. Commands run in Cloud Shell or psql.

The SQL was added to `backend/db/alloydb.sql` as documentation (PR #8).

---

## Step 2 — Connect to AlloyDB

```bash
# Update Cloud Shell IP authorization if needed
CURRENT_IP=$(curl -s ifconfig.me)
gcloud alloydb instances update wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --assign-inbound-public-ip=ASSIGN_IPV4 \
  --database-flags=password.enforce_complexity=on \
  --authorized-external-networks="${CURRENT_IP}/32" \
  --project=ragai-staging

# Connect
PGPASSWORD='WisoAI2024#Staging' psql \
  "host=34.60.92.141 port=5432 user=postgres dbname=wiso_ai_db sslmode=require"
```

---

## Step 3 — Create Indexes

```sql
-- HNSW index for semantic search <100ms
CREATE INDEX idx_embedding_hnsw
  ON corrective_actions_vectors
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Hard filter indexes (WHERE clause)
CREATE INDEX IF NOT EXISTS idx_department
  ON corrective_actions_vectors (department);

CREATE INDEX IF NOT EXISTS idx_product_line
  ON corrective_actions_vectors (product_line);

CREATE INDEX IF NOT EXISTS idx_plant
  ON corrective_actions_vectors (plant);

-- Composite index — most common RAG query pattern
-- WHERE department = 'PAINT' AND product_line = 'RANGER'
CREATE INDEX IF NOT EXISTS idx_department_product_line
  ON corrective_actions_vectors (department, product_line);
```

---

## Step 4 — Verify Indexes

```sql
\d corrective_actions_vectors
```

**Expected output:**
```
Indexes:
    "corrective_actions_vectors_pkey" PRIMARY KEY, btree (id)
    "idx_department" btree (department)
    "idx_department_product_line" btree (department, product_line)
    "idx_embedding_hnsw" hnsw (embedding vector_cosine_ops) WITH (m='16', ef_construction='64')
    "idx_plant" btree (plant)
    "idx_product_line" btree (product_line)
```

---

## Step 5 — Update alloydb.sql documentation

```bash
git checkout develop
git pull origin develop
git checkout -b docs/update-alloydb-sql-with-indexes
```

Update `backend/db/alloydb.sql` to include the index creation
statements (so any developer can recreate the schema from scratch).

```bash
git add backend/db/alloydb.sql
git commit -m "docs(db): update alloydb.sql with HNSW and filter indexes

Added all indexes to DDL:
- idx_embedding_hnsw (HNSW, m=16, ef_construction=64)
- idx_department (hard filter)
- idx_product_line (hard filter)
- idx_plant (hard filter)
- idx_department_product_line (composite — most common RAG query)"

git push origin docs/update-alloydb-sql-with-indexes
```

PR → merge → clean up.

---

## Step 6 — Test semantic search (optional)

```sql
-- Test that HNSW index is used in query plan
EXPLAIN (ANALYZE, BUFFERS)
SELECT concern_id, department, product_line,
       1 - (embedding <=> '[0.1, 0.2, ...]'::vector(768)) AS similarity
FROM corrective_actions_vectors
WHERE department = 'PAINT'
  AND product_line = 'RANGER'
ORDER BY embedding <=> '[0.1, 0.2, ...]'::vector(768)
LIMIT 5;
```

Look for `Index Scan using idx_embedding_hnsw` in the output.

---

## Step 7 — Clean up

```bash
git checkout develop
git pull origin develop
git branch -D docs/update-alloydb-sql-with-indexes

# Remove temporary public IP
gcloud alloydb instances update wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --assign-inbound-public-ip=NO_PUBLIC_IP \
  --project=ragai-staging
```

---

## Task Summary

| Index | Type | Columns | Purpose | Status |
|---|---|---|---|---|
| `corrective_actions_vectors_pkey` | PRIMARY KEY btree | `id` | Row identifier | ✅ |
| `idx_embedding_hnsw` | HNSW | `embedding` | Semantic search <100ms | ✅ |
| `idx_department` | btree | `department` | Hard filter | ✅ |
| `idx_product_line` | btree | `product_line` | Hard filter | ✅ |
| `idx_plant` | btree | `plant` | Hard filter | ✅ |
| `idx_department_product_line` | btree | `department, product_line` | Most common RAG query | ✅ |

*Last updated: June 2026 — M2 Task 2.5 closed*
