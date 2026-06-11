# WISO-AI — M2 Task 2.2 / Step 9 Runbook

## Run the Historical Ingestion Pipeline from Cloud Shell

**Scope:** End-to-end procedure to execute `backend.pipelines.ingest_historical`
from Google Cloud Shell against AlloyDB (staging), starting from a clean
environment (no repo cloned).

**Run frequency:** Once, or on-demand to re-ingest historical data.

**Expected result:** 26 fetched → 16 valid → 16 inserted with 768-dim embeddings.

---

## Key Concepts (read before starting)

1. **The pipeline runs on a machine, and AlloyDB only accepts connections
   from authorized IPs.** The IP you authorize must belong to the machine
   where you run the pipeline (Cloud Shell, in this runbook).
2. **Cloud Shell's egress IP changes between sessions.** Every new session
   requires re-authorization (Steps 2–4).
3. **Environment variables live only in the current shell session.** A new
   session or new tab loses them. Symptom: the pipeline logs
   `Connecting to AlloyDB 10.187.0.2` (private IP fallback) instead of the
   public IP — re-export and re-run.
4. **AlloyDB silently drops unauthorized connections.** There is no
   "connection refused" — the pipeline just hangs and eventually raises
   `TimeoutError`. Always run the connectivity test (Step 5) first.
5. `--authorized-external-networks` **replaces** the whole list, it does not
   append. Include every IP you need in a single comma-separated call.

---

## Step 0 — Clone the repo (first time only)

Open Cloud Shell from the GCP Console (`>_` icon, top right).

```bash
# Verify active project
gcloud config get-value project
# Expected: ragai-staging
# If not: gcloud config set project ragai-staging

# 1. Authenticate with GitHub CLI (pre-installed in Cloud Shell)
gh auth login
#    → GitHub.com → HTTPS → Login with a web browser
#    → it gives you an 8-character code, you open the URL in your browser,
#      paste the code, authorize, and you're done

# 2. Set up git with that credential
gh auth setup-git

# 3. Verify
gh auth status

# 4. Clone (or if it's already cloned, push/pull will now work)
git clone https://github.com/devmm4git/wisorag-corrections.git


# Clone the repo (skip if ~/wisorag-corrections already exists)
cd ~
git clone https://github.com/devmm4git/wisorag-corrections.git
cd wisorag-corrections
git checkout develop

# Install dependencies
pip install -r requirements.txt --user
```

> **Note:** Cloud Shell persists your `$HOME` directory between sessions,
> so the repo and pip packages usually survive. Software installed with
> `apt-get` does NOT persist.

---

## Step 1 — Position in the repo and update

```bash
cd ~/wisorag-corrections
git checkout develop
git pull origin develop
```

**Expected:** `Already up to date.` or a fast-forward merge.

---

## Step 2 — Get the current Cloud Shell IP (IPv4)

```bash
CS_IP=$(curl -s -4 ifconfig.me)
echo "Cloud Shell IP: $CS_IP"
```

**Checklist:**

- Output must be an **IPv4** address (e.g. `34.75.68.30`).
- If you see an IPv6 (contains `:`), the `-4` flag failed. Fallback:
  ```bash
  CS_IP=$(curl -s https://api.ipify.org)
  ```

> ⚠️ **Run this command on the machine where the pipeline will run.**
> Running it on your laptop gives you your laptop's IP — authorizing that
> will NOT let Cloud Shell connect.

---

## Step 3 — Authorize the IP in AlloyDB

```bash
gcloud alloydb instances update wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --project=ragai-staging \
  --authorized-external-networks=$CS_IP/32
```

- ⏱️ The operation is **asynchronous** and takes **1–3 minutes**. The
  command may return an `Operation ID` immediately — the change is NOT
  applied yet at that point.
- If the instance has no public IP (e.g. after a previous cleanup), add
  `--assign-inbound-public-ip=ASSIGN_IPV4` to the same command.
- If you get "another operation is in progress", wait a couple of minutes
  and retry.
- Use `/32` (exact IP). A typo like `/3` will be rejected as invalid.

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

- `cidrRange` shows **your `$CS_IP/32`**. If it still shows an old IP, the
  operation from Step 3 hasn't finished — wait and re-run the describe.
- Note the `publicIpAddress` (currently `34.60.92.141`). If it changed,
  use the new value in Steps 5–8.

---

## Step 5 — Test connectivity BEFORE running the pipeline

`nc` is **not installed** in Cloud Shell. Use one of these instead:

**Option A — Pure bash (no dependencies, fast TCP check):**

```bash
timeout 5 bash -c '</dev/tcp/34.60.92.141/5432' \
  && echo "✅ Port open" || echo "❌ No connection"
```

**Option B — Full check with psql (network + SSL + auth in one shot):**

```bash
PGPASSWORD='WisoAI2024#Staging' psql \
  "host=34.60.92.141 port=5432 user=postgres dbname=wiso_ai_db sslmode=require connect_timeout=5" \
  -c "SELECT 1;"
```

**Expected (Option B):**

```
 ?column?
----------
        1
(1 row)
```

### If Option B fails with `password authentication failed`

The network path is fine (you reached Postgres), but the password doesn't
match. Reset it to the documented value:

```bash
gcloud alloydb users set-password postgres \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --project=ragai-staging \
  --password='WisoAI2024#Staging'
```

Then re-run Option B. ⚠️ This changes the password for everyone — notify
any teammate who connects to this instance.

---

## Step 6 — Export environment variables

> ⚠️ Exports live **only in the current shell session**. Re-run this block
> in every new session/tab, in the SAME terminal where you'll run Step 7.

```bash
export ALLOYDB_HOST="34.60.92.141"      # public IP from Step 4
export ALLOYDB_PASSWORD='WisoAI2024#Staging'
export ALLOYDB_DATABASE="wiso_ai_db"
export ALLOYDB_USER="postgres"
export BIGQUERY_PROJECT="simula-ipd-produ"
export VERTEX_AI_PROJECT="ragai-staging"
export VERTEX_AI_LOCATION="us-central1"
export ENVIRONMENT="dev"

# Sanity check — saves you from a silent fallback to the private IP
echo "HOST: $ALLOYDB_HOST"
# Must print: HOST: 34.60.92.141
```

**Notes:**

- Single quotes around the password are **mandatory** (the `#` character
  would otherwise start a bash comment).
- The `#` is safe in the Python code because `asyncpg.create_pool()` uses
  named parameters, not a connection URL (see "AlloyDB connection fix" in
  the main task doc).

---

## Step 7 — Run the pipeline

```bash
python -m backend.pipelines.ingest_historical
```

**First line to verify in the log:**

```
[INFO] Target : AlloyDB 34.60.92.141/wiso_ai_db
```

If it says `10.187.0.2` instead → exports were lost → go back to Step 6.

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
  BigQuery source (C011–C018, C020, C025). Documented, do not fix here.
- `Gemini Pro unavailable ... skipping Level 2` → vertexai SDK version
  incompatibility. L2 semantic validation is skipped; L1 still applies.
  Tracked as a pending item for M3.

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

> Alternative without IP authorization: run the same query from
> **AlloyDB Studio** in the GCP Console (connects internally, no
> authorized network required).

---

## Step 9 — Cleanup (only when fully done)

```bash
# Remove the temporary public IP from the instance
gcloud alloydb instances update wiso-ai-primary \
  --cluster=wiso-ai-cluster \
  --region=us-central1 \
  --project=ragai-staging \
  --assign-inbound-public-ip=NO_PUBLIC_IP
```

> ⚠️ Skip this if you plan to re-run the ingestion soon — otherwise you'll
> need to re-enable the public IP and re-authorize (Steps 2–4) next time.

---

## Troubleshooting Quick Reference

| Symptom                                                                      | Root cause                                                                                                              | Fix                                                                                                 |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Pipeline hangs at `Connecting to AlloyDB <public IP>...` then `TimeoutError` | Cloud Shell IP not in authorized networks (IP changed since last session)                                               | Steps 2–4: get current IP, authorize, verify                                                        |
| Log shows `Connecting to AlloyDB 10.187.0.2...` (private IP)                 | Env vars lost (new session/tab) — settings fell back to default                                                         | Step 6: re-export, verify with `echo $ALLOYDB_HOST`                                                 |
| `FATAL: password authentication failed for user "postgres"`                  | Password mismatch (network is fine — you reached the server)                                                            | Step 5: `gcloud alloydb users set-password`                                                         |
| `nc: command not found`                                                      | netcat not preinstalled in Cloud Shell                                                                                  | Use `timeout 5 bash -c '</dev/tcp/HOST/5432'` or psql                                               |
| `authorized network CIDR range "...:...:.../32" is not a valid IPv4 range`   | `curl ifconfig.me` returned IPv6                                                                                        | Use `curl -s -4 ifconfig.me`                                                                        |
| Authorized IP looks wrong after update                                       | `describe` ran before the async operation finished, or the IP was captured on the wrong machine (laptop vs Cloud Shell) | Wait 1–3 min and re-describe; always run Step 2 on the machine running the pipeline                 |
| `another operation is in progress` on update                                 | Previous instance update still running                                                                                  | Wait and retry; check with `gcloud alloydb operations describe <OPERATION_ID> --region=us-central1` |

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

- **Secret Manager:** the staging password currently lives in this doc,
  shell exports, and command history. Migrate to
  `gcloud secrets versions access` before M3.
- **Gemini L2 validation:** fix the `vertexai.generative_models` import
  incompatibility so Level 2 semantic validation runs.
- **Long-term:** package the pipeline as a Cloud Run Job inside the VPC
  to eliminate the public IP / authorized networks dance entirely.

---

_Last updated: June 2026 — validated end-to-end (16 inserted, 0 failed)._
