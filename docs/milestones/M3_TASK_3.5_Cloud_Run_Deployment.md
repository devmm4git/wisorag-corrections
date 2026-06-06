# M3 — Task 3.5: Cloud Run Deployment

## Overview

| Field | Value |
|-------|-------|
| **Milestone** | M3 — FastAPI Backend & RAG API |
| **Task** | 3.5 |
| **Branch** | `feat/m3-task-3.5-cloud-run` |
| **Status** | ✅ Done |
| **Depends on** | Task 3.4 ✅ (PR #16) |
| **GCP Project** | `ragai-staging` |
| **Region** | `us-central1` |
| **Service URL** | `https://wiso-ai-api-353440068506.us-central1.run.app` |
| **Swagger URL** | `https://wiso-ai-api-353440068506.us-central1.run.app/docs` |

## Objective

Deploy the WISO-AI FastAPI application to GCP Cloud Run.
Build the Docker image via Cloud Build, push to Artifact Registry,
and deploy to Cloud Run with VPC connector for private AlloyDB access.

## Files Created

| File | Location | Description |
|------|----------|-------------|
| `Dockerfile` | repo root `/` | Container definition — Python 3.11-slim, uvicorn, port 8080 |
| `.dockerignore` | repo root `/` | Excludes .git, .venv, docs, infra from image |
| `cloudbuild.yaml` | repo root `/` | CI/CD pipeline — lint → test → build → push → deploy |
| `backend/config/settings.py` | existing file | Added `port: int = 8080` field |

## Cloud Run Configuration

| Parameter | Value |
|-----------|-------|
| **Image** | `us-central1-docker.pkg.dev/ragai-staging/wiso-ai/wiso-ai-api:latest` |
| **Service Account** | `rag-api-sa@ragai-staging.iam.gserviceaccount.com` |
| **VPC Connector** | `wiso-ai-vpc-connector` → `subnet-vpc-connector (10.0.5.0/28)` |
| **VPC Egress** | `all-traffic` |
| **Min instances** | 1 |
| **Max instances** | 10 |
| **Memory** | 2Gi |
| **CPU** | 2 |
| **Timeout** | 60s |
| **Concurrency** | 80 |
| **Auth** | `--no-allow-unauthenticated` (IAM required) |

---

## Prerequisites — One-time GCP Setup

These steps are performed ONCE before the first deploy.
They do NOT need to be repeated on subsequent deploys.

### 1. Enable required APIs

```bash
gcloud services enable \
    run.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    vpcaccess.googleapis.com \
    --project=ragai-staging
```

> `vpcaccess.googleapis.com` — required for VPC connector (Cloud Run → AlloyDB private network).

### 2. Create Artifact Registry repository

**What it is:** Private Docker image registry in GCP. Cloud Run pulls the image from here before deploying.

```
docker build → image → Artifact Registry → Cloud Run pulls → deploys container
```

```bash
gcloud artifacts repositories create wiso-ai \
    --repository-format=docker \
    --location=us-central1 \
    --description="WISO-AI Docker images" \
    --project=ragai-staging
```

### 3. Configure Docker authentication

Allows Docker to push/pull images to Artifact Registry using GCP credentials.

```bash
gcloud auth configure-docker us-central1-docker.pkg.dev
```

### 4. Create VPC connector subnet

**What it is:** VPC Access Connector is the bridge that allows Cloud Run (which lives in Google's public infrastructure) to reach AlloyDB (which has a private IP `10.187.0.2` inside the VPC).

```
Cloud Run (Google infra)
    ↓ vpc-connector
subnet-vpc-connector (10.0.5.0/28) — inside wiso-ai-vpc
    ↓ TCP/5432 private
AlloyDB 10.187.0.2
```

> **Critical:** VPC connectors require a dedicated `/28` subnet. Existing `/24` subnets cannot be used directly.

```bash
gcloud compute networks subnets create subnet-vpc-connector \
    --network=wiso-ai-vpc \
    --region=us-central1 \
    --range=10.0.5.0/28 \
    --project=ragai-staging
```

### 5. Create VPC connector

```bash
gcloud compute networks vpc-access connectors create wiso-ai-vpc-connector \
    --region=us-central1 \
    --subnet=subnet-vpc-connector \
    --subnet-project=ragai-staging \
    --min-instances=2 \
    --max-instances=3 \
    --machine-type=e2-micro \
    --project=ragai-staging
```

### 6. Enable VPC peering custom routes

Required so the VPC connector can reach AlloyDB's IP (`10.187.0.2`)
which is assigned via Private Service Access VPC peering.

```bash
gcloud compute networks peerings update servicenetworking-googleapis-com \
    --network=wiso-ai-vpc \
    --export-custom-routes \
    --import-custom-routes \
    --project=ragai-staging
```

### 7. Grant IAM permissions

#### Cloud Build SA — Storage access

```bash
PROJECT_NUMBER=$(gcloud projects describe ragai-staging --format="value(projectNumber)")

gcloud projects add-iam-policy-binding ragai-staging \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/storage.admin"

gcloud projects add-iam-policy-binding ragai-staging \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/cloudbuild.builds.builder"
```

#### rag-api-sa — Secret Manager access

```bash
gcloud projects add-iam-policy-binding ragai-staging \
    --member="serviceAccount:rag-api-sa@ragai-staging.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

> This was missing on first deploy attempt — Cloud Run failed with:
> `Permission denied on secret ALLOYDB_PRIMARY_PASSWORD for rag-api-sa`

### 8. Fix AlloyDB password (remove special character)

The original password `WisoAI2024#Staging` contained `#` which caused
pydantic-settings to parse it incorrectly (truncated at `#`).
Password was updated to remove the `#`:

```bash
# Update AlloyDB user password
gcloud alloydb users set-password postgres \
    --cluster=wiso-ai-cluster \
    --region=us-central1 \
    --password="WisoAI2024Staging" \
    --project=ragai-staging

# Update Secret Manager to match
echo -n "WisoAI2024Staging" | gcloud secrets versions add ALLOYDB_PRIMARY_PASSWORD \
    --data-file=- \
    --project=ragai-staging
```

> **Root cause:** `#` in passwords injected as env vars is interpreted as
> a comment character — everything after `#` is ignored.
> **Rule:** Never use `#` in passwords stored as env var secrets.

---

## Deploy — Build & Push Image

> **Important:** `docker push` from Cloud Shell fails due to network restrictions.
> Use `gcloud builds submit` instead — it runs the build and push
> entirely within GCP infrastructure, bypassing Cloud Shell network limits.

### Clone and pull latest code

```bash
cd ~/wisorag-corrections
git pull origin develop
```

### Build and push via Cloud Build

```bash
gcloud builds submit \
    --tag us-central1-docker.pkg.dev/ragai-staging/wiso-ai/wiso-ai-api:latest \
    --project=ragai-staging \
    .
```

Expected output:
```
STATUS: SUCCESS
IMAGES: us-central1-docker.pkg.dev/ragai-staging/wiso-ai/wiso-ai-api:latest
DURATION: ~1M38S
```

---

## Deploy — Cloud Run

```bash
gcloud run deploy wiso-ai-api \
    --image=us-central1-docker.pkg.dev/ragai-staging/wiso-ai/wiso-ai-api:latest \
    --region=us-central1 \
    --platform=managed \
    --no-allow-unauthenticated \
    --service-account=rag-api-sa@ragai-staging.iam.gserviceaccount.com \
    --set-secrets=ALLOYDB_PASSWORD=ALLOYDB_PRIMARY_PASSWORD:latest \
    --set-env-vars=ALLOYDB_HOST=10.187.0.2,ALLOYDB_DATABASE=wiso_ai_db,ALLOYDB_USER=postgres,VERTEX_AI_PROJECT=ragai-staging,VERTEX_AI_LOCATION=us-central1,BIGQUERY_PROJECT=simula-ipd-produ,ENVIRONMENT=dev \
    --vpc-connector=wiso-ai-vpc-connector \
    --vpc-egress=all-traffic \
    --min-instances=1 \
    --max-instances=10 \
    --memory=2Gi \
    --cpu=2 \
    --timeout=60 \
    --concurrency=80
```

> **Note:** `--vpc-egress=all-traffic` is included in the deploy command directly
> to avoid needing a separate `gcloud run services update` afterwards.

---

## Verify Deployment

### Get service URL

```bash
gcloud run services describe wiso-ai-api \
    --region=us-central1 \
    --format="value(status.url)"
```

### Health check

```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
    https://wiso-ai-api-353440068506.us-central1.run.app/ai/health
```

Expected response:
```json
{
  "status": "healthy",
  "alloydb": "connected",
  "vertex_ai": "reachable",
  "latency_p95_ms": null,
  "active_instances": 1,
  "uptime_seconds": 25
}
```

### Swagger UI

```
https://wiso-ai-api-353440068506.us-central1.run.app/docs
```

---

## Troubleshooting Log — Issues Encountered

| # | Error | Root Cause | Fix Applied |
|---|-------|-----------|-------------|
| 1 | `docker push` — `connect: connection refused` | Cloud Shell network restrictions block direct push to Artifact Registry | Replaced with `gcloud builds submit` |
| 2 | `storage.objects.get access denied` on Cloud Build | Compute SA missing `storage.admin` role | Added `roles/storage.admin` + `roles/cloudbuild.builds.builder` |
| 3 | `Permission denied on secret ALLOYDB_PRIMARY_PASSWORD` | `rag-api-sa` missing `secretmanager.secretAccessor` role | Added `roles/secretmanager.secretAccessor` to `rag-api-sa` |
| 4 | `alloydb: unreachable` — VPC connector range error | VPC connector created with `10.8.0.0/28` outside VPC subnets — can't reach AlloyDB peering IP | Recreated connector using dedicated `subnet-vpc-connector (10.0.5.0/28)` |
| 5 | `alloydb: unreachable` — peering routes | VPC connector traffic doesn't traverse VPC peerings by default | Enabled `export-custom-routes` + `import-custom-routes` on `servicenetworking-googleapis-com` peering |
| 6 | `invalid literal for int() with base 10: 'WisoAI2024'` | Password `WisoAI2024#Staging` — `#` truncated by env var parsing | Removed `#` from password — updated AlloyDB + Secret Manager |

---

## Network Architecture

```
Cloud Run (wiso-ai-api)
    ↓ --vpc-egress=all-traffic
wiso-ai-vpc-connector
    ↓ subnet-vpc-connector (10.0.5.0/28)
wiso-ai-vpc (wiso-ai-vpc)
    ↓ VPC peering (servicenetworking-googleapis-com)
    ↓ export-custom-routes + import-custom-routes enabled
AlloyDB Primary — 10.187.0.2 (TCP/5432 private)
```

> Cloud Run does NOT live inside the VPC directly.
> The VPC connector bridges Google's public infrastructure to the private VPC.
> AlloyDB is accessed via private IP only — never via public IP (35.253.120.250).

---

## Git Workflow

### 1. Crear branch

```bash
git checkout develop
git pull origin develop
git checkout -b feat/m3-task-3.5-cloud-run
```

### 2. Crear archivos

```
Dockerfile          → repo root
.dockerignore       → repo root
cloudbuild.yaml     → repo root
backend/config/settings.py → add port: int = 8080
```

### 3. Validar con flake8

```bash
flake8 backend/ --max-line-length=100 --exclude=__pycache__,.venv
# Sin output → ✅ limpio
```

### 4. Commit y push

```bash
git add .
git commit -m "feat(infra): Cloud Run deployment + Dockerfile + cloudbuild.yaml — Task 3.5"
git push origin feat/m3-task-3.5-cloud-run
```

### 5. PR en GitHub

```
base:     develop
compare:  feat/m3-task-3.5-cloud-run
title:    feat(infra): Cloud Run deployment + Dockerfile + cloudbuild.yaml — Task 3.5
reviewer: wmssaas-project
merge:    Squash and merge
```

### 6. Cleanup post-merge

```bash
git checkout develop
git pull origin develop
git branch -D feat/m3-task-3.5-cloud-run
```

---

## M3 — Milestone Completo

```
MILESTONE 3 — FastAPI Backend & RAG API
├── Task 3.1  FastAPI app setup + health endpoint       ✅ DONE (PR #13)
├── Task 3.2  POST /corrective-actions/ingest          ✅ DONE (PR #14)
├── Task 3.3  POST /corrective-actions/search          ✅ DONE (PR #15)
├── Task 3.4  POST /corrective-actions/feedback        ✅ DONE (PR #16)
└── Task 3.5  Cloud Run deployment                     ✅ DONE
```

**API live:**
```
https://wiso-ai-api-353440068506.us-central1.run.app
https://wiso-ai-api-353440068506.us-central1.run.app/docs
```

## References

- `Dockerfile` — Python 3.11-slim, uvicorn, port 8080
- `cloudbuild.yaml` — lint → test → build → push → deploy pipeline
- `backend/config/settings.py` — `port: int = 8080` added
- `backend/db/alloydb.py` — `check_connection()` uses `get_write_pool()`
- Secret: `ALLOYDB_PRIMARY_PASSWORD` version 2 (without `#`)
- VPC Connector: `wiso-ai-vpc-connector` → `subnet-vpc-connector (10.0.5.0/28)`

---
*Owner: rag-sp@mm4.me | June 2026*
*Deployed by: daviddeveps@gmail.com (GCP Owner)*
