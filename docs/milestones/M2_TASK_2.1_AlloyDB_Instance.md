# WISO-AI — M2 Task 2.1: AlloyDB Instance
## Cluster, Instance, Database, pgvector

---

## Context

**What does this task do?**
Creates the AlloyDB cluster and primary instance inside `wiso-ai-vpc`,
creates the `wiso_ai_db` database, enables `pgvector` extension,
and creates the `corrective_actions_vectors` table with all indexes.

**Why AlloyDB over Cloud SQL or Postgres?**
AlloyDB natively supports `pgvector` for vector similarity search
with HNSW indexes — required for RAG retrieval at <100ms latency.

**Prerequisites:** Task 2.0 (Network Infrastructure) must be complete.

---

## Architecture created

```
AlloyDB Cluster: wiso-ai-cluster (us-central1)
└── Primary Instance: wiso-ai-primary
    ├── CPU: 2 vCPU
    ├── Private IP: 10.187.0.2
    ├── SSL Mode: ENCRYPTED_ONLY
    └── Database: wiso_ai_db
        ├── Extension: pgvector
        └── Table: corrective_actions_vectors
            ├── HNSW index (embedding vector_cosine_ops)
            └── btree indexes (department, product_line, plant)
```

---

## Git Workflow

### Step 1 — No code changes required
This task is GCP infrastructure + SQL.
Commands run in Cloud Shell or terminal with gcloud/psql.

---

## Step 2 — Create AlloyDB Cluster

```bash
gcloud alloydb clusters create wiso-ai-cluster \
  --region=us-central1 \
  --password=WisoAI2024#Staging \
  --network=wiso-ai-vpc \
  --project=ragai-staging
```

> ⏱️ Takes 3-5 minutes.

**Expected output:**
```
Created cluster [wiso-ai-cluster].
```

---

## Step 3 — Create Primary Instance

```bash
gcloud alloydb instances create wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --instance-type=PRIMARY \
  --cpu-count=2 \
  --project=ragai-staging
```

> ⏱️ Takes 5-10 minutes.

**Expected output:**
```
Created instance [wiso-ai-primary].
```

---

## Step 4 — Get Private IP

```bash
gcloud alloydb instances describe wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --format="value(ipAddress)" \
  --project=ragai-staging
```

**Expected output:**
```
10.187.0.2
```

---

## Step 5 — Store Credentials in Secret Manager

```bash
# Store password
echo -n "WisoAI2024#Staging" | gcloud secrets create ALLOYDB_PRIMARY_PASSWORD \
  --data-file=- --project=ragai-staging

# Store connection URL
echo -n "postgresql://postgres:WisoAI2024#Staging@10.187.0.2:5432/wiso_ai_db" | \
  gcloud secrets create ALLOYDB_PRIMARY_URL \
  --data-file=- --project=ragai-staging
```

---

## Step 6 — Connect to AlloyDB

AlloyDB uses private IP only. To connect from Cloud Shell
(which is outside the VPC), enable a temporary public IP:

```bash
# Get Cloud Shell current IP
CURRENT_IP=$(curl -s ifconfig.me)
echo "Cloud Shell IP: $CURRENT_IP"

# Enable temporary public IP + authorize Cloud Shell
gcloud alloydb instances update wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --assign-inbound-public-ip=ASSIGN_IPV4 \
  --database-flags=password.enforce_complexity=on \
  --authorized-external-networks="${CURRENT_IP}/32" \
  --project=ragai-staging

# Get public IP
PUBLIC_IP=$(gcloud alloydb instances describe wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --format="value(publicIpAddress)" \
  --project=ragai-staging)
echo "Public IP: $PUBLIC_IP"

# Connect
PGPASSWORD='WisoAI2024#Staging' psql \
  "host=${PUBLIC_IP} port=5432 user=postgres dbname=postgres sslmode=require"
```

> ⚠️ Cloud Shell IP changes frequently. Re-run the update command
> if you get a connection timeout.

---

## Step 7 — Create Database and Table

Run this SQL in psql or AlloyDB Studio:

```sql
-- Create database
CREATE DATABASE wiso_ai_db;

-- Connect to it
\c wiso_ai_db

-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Create main table
CREATE TABLE corrective_actions_vectors (
    -- Identifier
    id                  SERIAL PRIMARY KEY,

    -- Traceability
    concern_id          VARCHAR(50)     NOT NULL,

    -- Metadata — hard filters (WHERE clause)
    plant               VARCHAR(100),
    department          VARCHAR(100),
    severity            VARCHAR(10),
    collection_point    VARCHAR(100),
    product_line        VARCHAR(100),
    charged_zone        VARCHAR(100),

    -- Original text
    concern_description TEXT,
    corrective_action   TEXT,

    -- Embedding — IMMUTABLE, never modified
    chunk_text          TEXT            NOT NULL,
    embedding           vector(768),

    -- Feedback — UPDATE only, no re-embedding
    feedback_score      FLOAT           DEFAULT 0.0,
    accept_count        INTEGER         DEFAULT 0,
    reject_count        INTEGER         DEFAULT 0,

    -- Temporal context
    resolved_at         TIMESTAMP,
    mttr_minutes        INTEGER,

    -- Audit
    created_at          TIMESTAMP       DEFAULT NOW(),
    updated_at          TIMESTAMP       DEFAULT NOW()
);

-- HNSW index for semantic search <100ms
-- m=16: connections per node (precision/memory balance)
-- ef_construction=64: index quality at build time
-- vector_cosine_ops: cosine similarity for text embeddings
CREATE INDEX idx_embedding_hnsw
    ON corrective_actions_vectors
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Hard filter indexes (WHERE clause)
CREATE INDEX idx_department
    ON corrective_actions_vectors (department);

CREATE INDEX idx_product_line
    ON corrective_actions_vectors (product_line);

CREATE INDEX idx_plant
    ON corrective_actions_vectors (plant);

-- Composite index — most common RAG query
-- WHERE department = 'PAINT' AND product_line = 'RANGER'
CREATE INDEX idx_department_product_line
    ON corrective_actions_vectors (department, product_line);
```

---

## Step 8 — Verify

```sql
-- Verify table structure and indexes
\d corrective_actions_vectors

-- Test pgvector
SELECT '[1,2,3]'::vector(3);

-- Test table is empty and ready
SELECT COUNT(*) FROM corrective_actions_vectors;
```

**Expected output:**
```
 count
-------
     0
```

---

## Step 9 — Remove Temporary Public IP

```bash
gcloud alloydb instances update wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --assign-inbound-public-ip=NO_PUBLIC_IP \
  --project=ragai-staging
```

> Always remove public IP when done. Production uses private IP only.

---

## Task Summary

| Resource | Value | Status |
|---|---|---|
| Cluster | `wiso-ai-cluster` | ✅ |
| Instance | `wiso-ai-primary` | ✅ READY |
| CPU | 2 vCPU | ✅ |
| Private IP | `10.187.0.2` | ✅ |
| SSL Mode | `ENCRYPTED_ONLY` | ✅ |
| Database | `wiso_ai_db` | ✅ |
| Extension | `pgvector` | ✅ |
| Table | `corrective_actions_vectors` | ✅ |
| HNSW Index | `idx_embedding_hnsw` (m=16, ef=64) | ✅ |
| Filter Indexes | `idx_department`, `idx_product_line`, `idx_plant`, `idx_department_product_line` | ✅ |
| Secrets | `ALLOYDB_PRIMARY_PASSWORD`, `ALLOYDB_PRIMARY_URL` | ✅ |

*Last updated: June 2026 — M2 Task 2.1 closed*
