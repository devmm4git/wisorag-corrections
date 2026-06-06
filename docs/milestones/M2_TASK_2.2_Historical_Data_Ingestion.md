# WISO-AI — M2 Task 2.2: Historical Data Ingestion
## BigQuery → Validate → Embed → AlloyDB (Batch Pipeline)

---

## Context

**What does this task do?**
Builds and runs Pipeline 1 — the batch ingestion pipeline that reads
historical corrective actions from BigQuery, validates them, generates
embeddings via Vertex AI, and inserts them into AlloyDB.

**Run frequency:** Once (or on-demand to re-ingest historical data).
**Records:** 26 fetched → 16 valid → 16 inserted with 768-dim embeddings.

**Prerequisites:** Tasks 2.0 and 2.1 must be complete.

---

## Pipeline Flow

```
BigQuery (simula-ipd-produ.tipbord_historical.corrective_actions)
    ↓ fetch_from_bigquery()
    26 records fetched
    ↓ CorrectiveActionFieldValidator (L1/L2/L3)
    26/26 passed field validation
    ↓ CorrectiveActionValidator (ADR-001)
    16 valid, 10 rejected (text too short)
    ↓ build_chunk_text() — ADR-002: Concern + CA only
    16 chunk texts
    ↓ generate_embeddings() — Vertex AI text-embedding-004
    16 embeddings × 768 dims
    ↓ insert_to_alloydb()
    16 inserted, 0 failed ✅
```

---

## Key Design Decisions

### ADR-002 — Embedding separation from metadata
```
chunk_text = "Concern: [concern_description]
              Corrective Action: [corrective_action]"

department, product_line, plant → separate columns (hard filters)
NOT included in embedding text
```

**Why?** Including metadata in the embedding contaminates semantic
search with filter terms. The vector should represent the semantic
meaning of the problem and solution only.

### Field Validation Levels
```
L1 REQUIRED     → concern_id, concern_description, corrective_action
                  Hard reject if missing
L2 QUASI-REQ    → department, product_line
                  Warning — enters AlloyDB but won't appear in filtered retrieval
L3 OPTIONAL     → plant, severity, collection_point, charged_zone,
                  resolved_at, mttr_minutes
                  Info — enters with NULL values
```

---

## Git Workflow

### Step 1 — Create branch from updated develop

```bash
git checkout develop
git pull origin develop
git checkout -b feat/m2-data-pipeline
git status
```

**Expected output:**
```
Switched to a new branch 'feat/m2-data-pipeline'
nothing to commit, working tree clean
```

---

### Step 2 — Files created/modified

| File | Action | Description |
|---|---|---|
| `backend/config/settings.py` | Created | Pydantic Settings — env vars |
| `backend/db/alloydb.py` | Created | Connection pool config |
| `backend/db/alloydb.sql` | Created | Full DDL with HNSW indexes |
| `backend/db/bifquery.sql` | Created | BigQuery feedback_log DDL |
| `backend/db/business_rules.sql` | Created | Feedback UPDATE rules |
| `backend/pipelines/ingest_historical.py` | Created | Main pipeline |
| `backend/rag/corrective_action_validator.py` | Created | ADR-001 + Field validator |
| `backend/tests/test_validator.py` | Created | Unit tests |
| `conftest.py` | Created | pytest path config |
| `pytest.ini` | Created | pytest config |
| `requirements.txt` | Created | Dependencies |

---

### Step 3 — Key code: ingest_historical.py

```python
# Pipeline flow — run_pipeline()

# Step 1: Fetch from BigQuery
records = fetch_from_bigquery()

# Step 1.5: Field validation (L1/L2/L3)
field_validator = CorrectiveActionFieldValidator()
field_valid_records = [r for r in records if field_validator.validate(r) is None]

# Step 2: Semantic validation (ADR-001)
valid_records, rejected = await validate_batch(records, config=validator_config)

# Step 3: Build chunk texts (ADR-002: semantic only)
chunk_texts = [build_chunk_text(r) for r in valid_records]
# chunk_text = "Concern: X\n\nCorrective Action: Y"

# Step 4: Generate embeddings
embeddings = generate_embeddings(chunk_texts)
# 768 dims per embedding via Vertex AI text-embedding-004

# Step 5: Insert to AlloyDB
inserted = await insert_to_alloydb(valid_records, embeddings)
```

---

### Step 4 — Key code: AlloyDB connection fix

```python
# CORRECT — named params avoid # char issue in password
pool = await asyncpg.create_pool(
    host=settings.alloydb_host,
    port=settings.alloydb_port,
    database=settings.alloydb_database,
    user=settings.alloydb_user,
    password=settings.alloydb_password,
    ssl='require',  # AlloyDB ENCRYPTED_ONLY mode
)

# WRONG — # in password breaks the URL
pool = await asyncpg.create_pool(
    "postgresql://postgres:WisoAI2024#Staging@10.187.0.2:5432/wiso_ai_db"
)
```

---

### Step 5 — Run flake8 before committing

```bash
flake8 backend/ --max-line-length=100 --exclude=__pycache__,.venv
# No output → clean ✅
```

---

### Step 6 — Commit and push

```bash
git add .
git commit -m "feat(m2): Historical data ingestion pipeline + CA validator

Pipeline 1: BigQuery → Validate → Embed → AlloyDB
- fetch_from_bigquery(): reads corrective_actions table
- CorrectiveActionFieldValidator: L1/L2/L3 field validation
- CorrectiveActionValidator (ADR-001): semantic quality check
- build_chunk_text() (ADR-002): Concern + CA only, no metadata
- generate_embeddings(): Vertex AI text-embedding-004 (768 dims)
- insert_to_alloydb(): asyncpg with ssl=require

Milestone: M2 — Task 2.2"

git push origin feat/m2-data-pipeline
```

---

### Step 7 — Verify CI in GitHub Actions

Go to: `github.com/devmm4git/wisorag-corrections/actions`

Verify:
- ✅ Lint with flake8
- ✅ Run tests

---

### Step 8 — Open PR

```
base: develop
compare: feat/m2-data-pipeline
Title: feat(m2): Historical data ingestion pipeline + CA validator
```

Review with `wmssaas-project` → Approve → Squash and merge

---

### Step 9 — Run pipeline in Cloud Shell

```bash
cd ~/wisorag-corrections
git pull origin develop

export ALLOYDB_HOST="34.60.92.141"      # temporary public IP
export ALLOYDB_PASSWORD='WisoAI2024#Staging'
export ALLOYDB_DATABASE="wiso_ai_db"
export ALLOYDB_USER="postgres"
export BIGQUERY_PROJECT="simula-ipd-produ"
export VERTEX_AI_PROJECT="ragai-staging"
export VERTEX_AI_LOCATION="us-central1"
export ENVIRONMENT="dev"

python -m backend.pipelines.ingest_historical
```

**Expected output:**
```
[INFO] WISO-AI Historical Ingestion Pipeline — START
[INFO] Fetched 26 records from BigQuery
[INFO] Field validation: 26/26 records passed Level 1
[INFO] Batch complete — Valid: 16, Rejected: 10/26
[INFO] Generated 16 embeddings (768 dims each)
[INFO] AlloyDB: 16 inserted, 0 failed
[INFO] WISO-AI Historical Ingestion Pipeline — COMPLETE
  Total fetched   : 26
  Valid records   : 16
  Rejected        : 10
  Inserted        : 16
  Success rate    : 61.5%
```

---

### Step 10 — Verify in AlloyDB

```bash
PGPASSWORD='WisoAI2024#Staging' psql \
  "host=34.60.92.141 port=5432 user=postgres dbname=wiso_ai_db sslmode=require" \
  -c "SELECT COUNT(*) as total, COUNT(embedding) as with_embeddings FROM corrective_actions_vectors;"
```

**Expected output:**
```
 total | with_embeddings
-------+-----------------
    16 |              16
```

---

### Step 11 — Clean up

```bash
git checkout develop
git pull origin develop
git branch -D feat/m2-data-pipeline

# Remove temporary public IP from AlloyDB
gcloud alloydb instances update wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --assign-inbound-public-ip=NO_PUBLIC_IP \
  --project=ragai-staging
```

---

## Rejected records — known data quality issues

| Concern ID | Reason |
|---|---|
| C011 | Text too short: 1 word, 2 chars |
| C012 | Text too short: 1 word, 5 chars |
| C013 | Text too short: 2 words, 6 chars |
| C014 | Text too short: 3 words, 15 chars |
| C015 | Text too short: 3 words, 16 chars |
| C016 | Text too short: 2 words, 9 chars |
| C017 | Text too short: 2 words, 7 chars |
| C018 | Text too short: 3 words, 20 chars |
| C020 | Text too short: 5 words, 22 chars |
| C025 | Text too short: 1 word, 9 chars |

These are dirty records in the BigQuery source — logged as rejected,
not inserted into AlloyDB.

---

## Task Summary

| Item | Value | Status |
|---|---|---|
| Records fetched | 26 | ✅ |
| Field validation | 26/26 passed | ✅ |
| Semantic validation | 16 valid, 10 rejected | ✅ |
| Embeddings generated | 16 × 768 dims | ✅ |
| Records inserted | 16 | ✅ |
| Failed inserts | 0 | ✅ |
| Success rate | 61.5% | ✅ |

*Last updated: June 2026 — M2 Task 2.2 closed*
