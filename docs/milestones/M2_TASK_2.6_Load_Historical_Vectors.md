# WISO-AI — M2 Task 2.6: Load Historical Vectors into AlloyDB
## Final execution of Pipeline 1 with correct architecture

---

## Context

**What does this task do?**
Executes the final, definitive run of `ingest_historical.py` with
all fixes applied — correct schema, semantic-only embeddings (ADR-002),
field validator (L1/L2/L3), and HNSW index already in place.

**This is the production-ready historical data load.**

**Prerequisites:**
- Task 2.2 (pipeline code merged and CI passing)
- Task 2.3/2.4 (ADR-002 chunking + embeddings implemented)
- Task 2.5 (HNSW index created)
- AlloyDB table cleaned (`DELETE FROM corrective_actions_vectors`)

---

## Final state after this task

```
corrective_actions_vectors:
├── 16 records with 768-dim embeddings
├── chunk_text = Concern + CA only (ADR-002)
├── department, product_line, plant as separate columns
├── HNSW index active
└── All filter indexes active
```

---

## Git Workflow

### Step 1 — No code changes required
This task is operational — running the already-merged pipeline code.
All code changes were done in Tasks 2.2, 2.3, 2.4.

---

## Step 2 — Ensure table is clean before re-ingesting

If re-running after a failed attempt:

```bash
PGPASSWORD='WisoAI2024#Staging' psql \
  "host=34.60.92.141 port=5432 user=postgres dbname=wiso_ai_db sslmode=require" \
  -c "SELECT COUNT(*) FROM corrective_actions_vectors;"
```

If count > 0 and you need a clean slate:

```sql
DELETE FROM corrective_actions_vectors;
-- ON CONFLICT DO NOTHING is safe to re-run, but DELETE ensures clean state
```

---

## Step 3 — Update Cloud Shell IP authorization

Cloud Shell IP changes frequently. Always update before connecting:

```bash
CURRENT_IP=$(curl -s ifconfig.me)
echo "Current IP: $CURRENT_IP"

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
echo "AlloyDB public IP: $PUBLIC_IP"
```

> ⏱️ Operation takes 2-3 minutes.

---

## Step 4 — Pull latest code and set environment variables

```bash
cd ~/wisorag-corrections
git pull origin develop

export ALLOYDB_HOST="34.60.92.141"       # public IP (temporary)
export ALLOYDB_PASSWORD='WisoAI2024#Staging'
export ALLOYDB_DATABASE="wiso_ai_db"
export ALLOYDB_USER="postgres"
export BIGQUERY_PROJECT="simula-ipd-produ"
export VERTEX_AI_PROJECT="ragai-staging"
export VERTEX_AI_LOCATION="us-central1"
export ENVIRONMENT="dev"
```

---

## Step 5 — Run the pipeline

```bash
python -m backend.pipelines.ingest_historical
```

**Expected output:**
```
[INFO] WISO-AI Historical Ingestion Pipeline — START
[INFO] Environment  : dev
[INFO] Source       : simula-ipd-produ.tipbord_historical
[INFO] Target       : AlloyDB 34.60.92.141/wiso_ai_db
[INFO] Embedding    : text-embedding-004 (768 dims)
[INFO] Fetched 26 records from BigQuery
[INFO] Validating fields for 26 records...
[INFO] [C001] FIELD INFO L3: Missing optional fields: ['charged_zone', 'resolved_at', 'mttr_minutes']
...
[INFO] Field validation: 26/26 records passed Level 1
[INFO] Validating 26 corrective actions (ADR-001)...
[INFO] [C001] VALID (lang=en)
...
[WARNING] [C011] L1 REJECT: Text too short: 1 words, 2 chars.
...
[INFO] Batch complete — Valid: 16, Rejected: 10/26
[INFO] Generated 16 embeddings (768 dims each)
[INFO] Connecting to AlloyDB 34.60.92.141...
[INFO] Inserted: C001
[INFO] Inserted: C001B
...
[INFO] AlloyDB: 16 inserted, 0 failed
[INFO] WISO-AI Historical Ingestion Pipeline — COMPLETE
  Total fetched   : 26
  Valid records   : 16
  Rejected        : 10
  Inserted        : 16
  Success rate    : 61.5%
```

---

## Step 6 — Verify data in AlloyDB

```bash
PGPASSWORD='WisoAI2024#Staging' psql \
  "host=34.60.92.141 port=5432 user=postgres dbname=wiso_ai_db sslmode=require" << 'EOF'

-- Count records
SELECT COUNT(*) as total_records,
       COUNT(embedding) as with_embeddings
FROM corrective_actions_vectors;

-- Preview records
SELECT concern_id, department, product_line,
       LEFT(chunk_text, 60) as chunk_preview
FROM corrective_actions_vectors
ORDER BY id;

-- Verify chunk_text does NOT contain metadata
SELECT concern_id,
       chunk_text NOT LIKE '%Department:%' as no_dept_in_chunk,
       chunk_text NOT LIKE '%Plant:%' as no_plant_in_chunk
FROM corrective_actions_vectors
LIMIT 5;

EOF
```

**Expected output:**
```
 total_records | with_embeddings
---------------+-----------------
            16 |              16

 concern_id | department | product_line | chunk_preview
------------+------------+--------------+-------------------------------------------
 C001       | PAINT      | RANGER       | Concern: LEFT REAR BLACKOUT TAPE DAMAGED
 ...

 concern_id | no_dept_in_chunk | no_plant_in_chunk
------------+------------------+-------------------
 C001       | t                | t                ← ADR-002 verified ✅
```

---

## Step 7 — Remove temporary public IP

```bash
gcloud alloydb instances update wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --assign-inbound-public-ip=NO_PUBLIC_IP \
  --project=ragai-staging
```

---

## Common Issues

### Connection timeout
**Cause:** Cloud Shell IP changed since last authorization.
**Fix:** Re-run Step 3 with current IP.

### `password authentication failed`
**Cause:** `#` in password breaks URL string format.
**Fix:** Always use named params in asyncpg, not connection URL string.

### `column X does not exist`
**Cause:** Code references a column that was dropped (e.g., `chunk_id`).
**Fix:** Pull latest code from develop — `git pull origin develop`.

### `ON CONFLICT DO NOTHING` — 0 inserted
**Cause:** Records already exist from a previous run.
**Fix:** Run `DELETE FROM corrective_actions_vectors;` before re-ingesting.

---

## Task Summary

| Item | Value | Status |
|---|---|---|
| Records fetched from BigQuery | 26 | ✅ |
| Field validation L1 | 26/26 passed | ✅ |
| Field validation L3 warnings | charged_zone, resolved_at, mttr_minutes NULL | ✅ |
| ADR-001 semantic validation | 16 valid, 10 rejected | ✅ |
| Embeddings generated | 16 × 768 dims | ✅ |
| Records inserted | 16 | ✅ |
| chunk_text semantic only | Verified (no metadata) | ✅ |
| HNSW index active | Yes | ✅ |

*Last updated: June 2026 — M2 Task 2.6 closed*
