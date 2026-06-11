# WISO-AI — M2 Task 2.2 / Step 9 Runbook (Option 2)

## Run the Historical Ingestion Pipeline from a LOCAL Machine

**Scope:** End-to-end procedure to execute `backend.pipelines.ingest_historical`
from a local workstation (Ubuntu/Linux assumed; macOS notes inline) against
AlloyDB (staging), starting from a completely clean machine.

**When to use this option:** Cloud Shell is unavailable, or you need to
iterate locally (debugger, IDE, longer sessions without Cloud Shell timeouts).

**When NOT to use it:** if Cloud Shell works for you, prefer it — it skips
all of Step 0 (GCP auth comes pre-configured there).

**Expected result:** 26 fetched → 16 valid → 16 inserted with 768-dim embeddings.

---

## Key Concepts (read before starting)

1. **Same rule as always: AlloyDB only accepts connections from authorized
   IPs, and the IP must belong to the machine running the pipeline.** Here,
   that's your local machine's **public IPv4** (your ISP-assigned address).
2. **Your home/office IP can change.** ISPs rotate addresses (DHCP lease
   renewals, router reboots). Verify your current IP before every run, same
   as you would with Cloud Shell.
3. **Two separate GCP authentications exist locally** and both are needed:
   - `gcloud auth login` → authenticates the **gcloud CLI** (for
     `gcloud alloydb ...` commands).
   - `gcloud auth application-default login` → creates **Application
     Default Credentials (ADC)**, which is what the **Python client
     libraries** (BigQuery, Vertex AI) use. Skipping this one is the #1
     cause of `DefaultCredentialsError` when running the pipeline locally.
4. **Watch out for IPv6.** Home connections often prefer IPv6;
   `curl ifconfig.me` may return an IPv6 address, which AlloyDB rejects.
   Always force IPv4 with `curl -4`.
5. **Environment variables live only in the current shell session** — same
   as Cloud Shell. Symptom of lost exports: pipeline logs
   `Connecting to AlloyDB 10.187.0.2` (private IP fallback).
6. `--authorized-external-networks` **replaces** the whole list. If Cloud
   Shell (or a teammate) also needs access, include all IPs in one
   comma-separated call.

---

## Step 0 — One-time machine setup

### 0.1 Install the gcloud CLI

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates gnupg curl
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
  | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list
sudo apt-get update && sudo apt-get install -y google-cloud-cli

# macOS: brew install --cask google-cloud-sdk

# Verify
gcloud --version
```

### 0.2 Authenticate — BOTH commands are required

```bash
# 1. CLI auth (for gcloud commands: alloydb update/describe, etc.)
gcloud auth login

# 2. Application Default Credentials (for the Python libraries:
#    BigQuery client, Vertex AI client used inside the pipeline)
gcloud auth application-default login

# 3. Set the default project and the ADC quota project
gcloud config set project ragai-staging
gcloud auth application-default set-quota-project ragai-staging
```

Both `login` commands open a browser → sign in with your Google account →
authorize. Credentials persist on disk (`~/.config/gcloud/`), so this is
one-time per machine.

### 0.3 Verify GCP access

```bash
gcloud config get-value project
# Expected: ragai-staging

# Quick ADC smoke test (BigQuery read access)
gcloud auth application-default print-access-token > /dev/null \
  && echo "✅ ADC OK" || echo "❌ ADC missing — re-run step 0.2"
```

### 0.4 Python environment

The pipeline was validated on Python 3.12 (Cloud Shell). Check your local
version and use a virtual environment to keep dependencies isolated:

```bash
python3 --version
# 3.10+ should work; 3.12 is the validated reference.
# Ubuntu 22.04 ships 3.10 — if you need 3.12:
#   sudo add-apt-repository ppa:deadsnakes/ppa
#   sudo apt-get install -y python3.12 python3.12-venv
```

### 0.5 GitHub access (only if the repo is private or you need to push)

```bash
# GitHub CLI (Ubuntu)
sudo apt-get install -y gh

gh auth login        # → GitHub.com → HTTPS → Login with a web browser
gh auth setup-git
gh auth status
```

> If the repo is public, cloning needs no credentials — this step is only
> required for `git push` (commits, PRs).

---

## Step 1 — Clone the repo and install dependencies

```bash
cd ~
git clone https://github.com/devmm4git/wisorag-corrections.git
cd wisorag-corrections
git checkout develop
git pull origin develop

# Virtual environment (recommended locally — unlike Cloud Shell,
# your machine has other Python projects to protect)
python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

> ⚠️ Remember to `source .venv/bin/activate` in every new terminal before
> running the pipeline. Symptom of forgetting:
> `ModuleNotFoundError: No module named 'asyncpg'` (or google.cloud, etc.)

---

## Step 2 — Get your LOCAL public IPv4

```bash
MY_IP=$(curl -s -4 ifconfig.me)
echo "My public IPv4: $MY_IP"
```

**Checklist:**

- Must be **IPv4** (e.g. `187.131.136.38`). If you see `:` characters,
  it's IPv6 — the `-4` flag is mandatory on dual-stack home connections.
- Fallback if ifconfig.me misbehaves:
  ```bash
  MY_IP=$(curl -s https://api.ipify.org)
  ```

> ⚠️ This is your **router's public IP**, shared by your whole network.
> It can change when your ISP renews the lease — re-check before each
> working session.

---

## Step 3 — Authorize your IP in AlloyDB

```bash
gcloud alloydb instances update wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --project=ragai-staging \
  --authorized-external-networks=$MY_IP/32
```

- ⏱️ Asynchronous, takes **1–3 minutes**. An `Operation ID` returned
  immediately does NOT mean it's applied.
- If the instance has no public IP (after a cleanup), add
  `--assign-inbound-public-ip=ASSIGN_IPV4`.
- To keep Cloud Shell access alive at the same time, pass both IPs:
  ```bash
  --authorized-external-networks=$MY_IP/32,<CLOUD_SHELL_IP>/32
  ```
- Use `/32` exactly. `/3` or any broad range will be rejected (or worse,
  accepted and dangerously open).

---

## Step 4 — Verify the authorization applied

```bash
gcloud alloydb instances describe wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --project=ragai-staging \
  --format="yaml(publicIpAddress, networkConfig.authorizedExternalNetworks)"
```

**Checklist:**

- `cidrRange` includes **your `$MY_IP/32`**. If it shows the old value,
  the operation hasn't finished — wait and re-describe.
- Note the `publicIpAddress` (currently `34.60.92.141`). If it changed,
  use the new value from here on.
- If it shows **34.75.68.30/32** → it's not done yet, wait ~30 seconds and repeat it
- If it **shows 187.131.136.38/32** → ✅ done, proceed to step 2

---

## Step 5 — Test connectivity BEFORE running the pipeline

Locally you have more tooling than Cloud Shell — `nc` usually exists:

**Option A — netcat (fast TCP check):**

```bash
nc -zv 34.60.92.141 5432
# If missing: sudo apt-get install -y netcat-openbsd
```

**Option B — Pure bash (zero dependencies):**

```bash
timeout 5 bash -c '</dev/tcp/34.60.92.141/5432' \
  && echo "✅ Port open" || echo "❌ No connection"
```

**Option C — Full check with psql (network + SSL + auth):**

```bash
# If psql is missing: sudo apt-get install -y postgresql-client
PGPASSWORD='WisoAI2024#Staging' psql \
  "host=34.60.92.141 port=5432 user=postgres dbname=wiso_ai_db sslmode=require connect_timeout=5" \
  -c "SELECT 1;"
```

**Expected (Option C):**

```
 ?column?
----------
        1
(1 row)
```

### If Option C fails with `password authentication failed`

Network is fine (you reached Postgres); the password doesn't match. Reset
it to the documented value:

```bash
gcloud alloydb users set-password postgres \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --project=ragai-staging \
  --password='WisoAI2024#Staging'
```

⚠️ This changes the password for everyone — notify teammates.

---

## Step 6 — Export environment variables

> ⚠️ Run in the SAME terminal where you'll run Step 7, with the venv
> already activated. Re-run in every new terminal.

```bash
export ALLOYDB_HOST="34.60.92.141"      # public IP from Step 4
export ALLOYDB_PASSWORD='WisoAI2024#Staging'
export ALLOYDB_DATABASE="wiso_ai_db"
export ALLOYDB_USER="postgres"
export BIGQUERY_PROJECT="simula-ipd-produ"
export VERTEX_AI_PROJECT="ragai-staging"
export VERTEX_AI_LOCATION="us-central1"
export ENVIRONMENT="dev"

# Sanity check
echo "HOST: $ALLOYDB_HOST"
# Must print: HOST: 34.60.92.141
```

**Notes:**

- Single quotes around the password are **mandatory** (`#` starts a bash
  comment otherwise).
- Optional convenience: save this block in an untracked `.env.local` file
  and load it with `source .env.local`. NEVER commit it (verify it's in
  `.gitignore`).

---

## Step 7 — Run the pipeline

```bash
cd ~/wisorag-corrections
source .venv/bin/activate    # if not already active
python -m backend.pipelines.ingest_historical
```

**First line to verify in the log:**

```
[INFO] Target : AlloyDB 34.60.92.141/wiso_ai_db
```

If it says `10.187.0.2` instead → exports were lost → back to Step 6.

**Expected final output:**

```
[INFO] AlloyDB: 16 inserted, 0 failed
[INFO] WISO-AI Historical Ingestion Pipeline — COMPLETE
  Total fetched   : 26
  Valid records   : 16
  Rejected        : 10
  Inserted        : 16
  Success rate    : 61.5%
```

**Expected warnings (not errors):**

- `10 records rejected — rejected_too_short` → known dirty data in the
  BigQuery source (C011–C018, C020, C025).
- `Gemini Pro unavailable ... skipping Level 2` → vertexai SDK version
  issue; L2 skipped, L1 applies. Pending fix for M3.

---

## Step 8 — Verify in AlloyDB

```bash
PGPASSWORD='WisoAI2024#Staging' psql \
  "host=34.60.92.141 port=5432 user=postgres dbname=wiso_ai_db sslmode=require" \
  -c "SELECT COUNT(*) as total, COUNT(embedding) as with_embeddings FROM corrective_actions_vectors;"
```

**Expected:**

```
 total | with_embeddings
-------+-----------------
    16 |              16
```

> No-IP alternative: run the same query from **AlloyDB Studio** in the
> GCP Console (connects internally, no authorized network needed).

---

## Step 9 — Cleanup (only when fully done)

```bash
# Remove your local IP from authorized networks AND/OR remove the
# temporary public IP entirely:
gcloud alloydb instances update wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --project=ragai-staging \
  --assign-inbound-public-ip=NO_PUBLIC_IP

# Deactivate the venv
deactivate
```

> ⚠️ Skip the public-IP removal if you plan to re-run soon.

---

## Troubleshooting Quick Reference

| Symptom                                                                      | Root cause                                                                        | Fix                                                                                              |
| ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Pipeline hangs at `Connecting to AlloyDB <public IP>...` then `TimeoutError` | Your local public IP is not authorized (or it changed since last session)         | Steps 2–4                                                                                        |
| Log shows `Connecting to AlloyDB 10.187.0.2...`                              | Env vars lost (new terminal)                                                      | Step 6, verify with `echo $ALLOYDB_HOST`                                                         |
| `google.auth.exceptions.DefaultCredentialsError`                             | ADC not configured — `gcloud auth login` alone is NOT enough for Python libraries | Step 0.2: `gcloud auth application-default login`                                                |
| `403 ... quota project` or `userProject` errors from BigQuery/Vertex         | ADC quota project not set                                                         | `gcloud auth application-default set-quota-project ragai-staging`                                |
| `ModuleNotFoundError: No module named 'asyncpg'` (or google.cloud)           | venv not activated, or deps not installed                                         | `source .venv/bin/activate` + `pip install -r requirements.txt`                                  |
| `FATAL: password authentication failed for user "postgres"`                  | Password mismatch (network is fine)                                               | Step 5: `gcloud alloydb users set-password`                                                      |
| `authorized network CIDR range "...:..." is not a valid IPv4 range`          | curl returned IPv6 (dual-stack home connection)                                   | Use `curl -s -4 ifconfig.me`                                                                     |
| Connection worked yesterday, times out today                                 | ISP rotated your public IP                                                        | Re-run Steps 2–4                                                                                 |
| Timeout even with correct IP authorized                                      | Corporate/hotel network blocks outbound port 5432                                 | Test with `nc -zv` from another network (e.g. phone hotspot) to confirm; use Cloud Shell instead |
| `another operation is in progress` on update                                 | Previous instance update still running                                            | Wait 1–3 min; check `gcloud alloydb operations describe <ID> --region=us-central1`               |

---

## Known Data Quality Rejections (expected)

| Concern ID | Reason                            |
| ---------- | --------------------------------- |
| C011       | Text too short: 1 word, 2 chars   |
| C012       | Text too short: 1 word, 5 chars   |
| C013       | Text too short: 2 words, 6 chars  |
| C014       | Text too short: 3 words, 15 chars |
| C015       | Text too short: 3 words, 16 chars |
| C016       | Text too short: 2 words, 9 chars  |
| C017       | Text too short: 2 words, 7 chars  |
| C018       | Text too short: 3 words, 20 chars |
| C020       | Text too short: 5 words, 22 chars |
| C025       | Text too short: 1 word, 9 chars   |

Dirty records in the BigQuery source — logged as rejected, never inserted.

---

## Pending Items (for M3)

- **Secret Manager:** the staging password lives in docs, shell exports,
  and command history. Migrate to `gcloud secrets versions access`.
- **Gemini L2 validation:** fix the `vertexai.generative_models` import
  incompatibility so Level 2 semantic validation runs.
- **Long-term:** package the pipeline as a Cloud Run Job inside the VPC —
  removes the public IP / authorized-networks dance for BOTH options.

---

_Last updated: June 2026 — companion to the Cloud Shell runbook
(M2_TASK_2.2_Step9_Ingestion_Runbook.md)._
