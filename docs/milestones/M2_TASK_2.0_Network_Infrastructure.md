# WISO-AI — M2 Task 2.0: Network Infrastructure
## VPC, Subnets, Firewall, Cloud NAT

---

## Context

**What does this task do?**
Creates the complete network infrastructure in GCP that isolates
all WISO-AI components in a private, secure VPC. Nothing is exposed
to the public internet by default.

**Why before AlloyDB?**
AlloyDB requires Private Service Access to be configured before
the cluster is created. Network first, then database.

**GCP Project:** `ragai-staging`
**Region:** `us-central1`

---

## Architecture created

```
wiso-ai-vpc (custom VPC)
├── subnet-api      10.0.1.0/24  ← Cloud Run FastAPI (M3)
├── subnet-data     10.0.2.0/24  ← AlloyDB + pgvector
├── subnet-ai       10.0.3.0/24  ← Vertex AI PSC
└── subnet-pipeline 10.0.4.0/24  ← ETL Pipelines

Private Service Access (/16)
└── VPC Peering → servicenetworking.googleapis.com
    └── Allows AlloyDB private IP

Firewall Rules:
├── wiso-ai-allow-internal      → TCP/UDP/ICMP between subnets
├── wiso-ai-allow-alloydb       → TCP:5432 from api + pipeline subnets
├── wiso-ai-allow-alloydb-proxy → TCP:5433 (Auth Proxy)
└── wiso-ai-allow-https-egress  → TCP:443 outbound

Cloud Router: wiso-ai-router
Cloud NAT:    wiso-ai-nat
```

---

## Git Workflow

### Step 1 — No code changes required
This task is pure GCP infrastructure — no Python files modified.
All commands run directly in Cloud Shell or terminal with gcloud.

---

## Step 2 — Create VPC

```bash
gcloud compute networks create wiso-ai-vpc \
  --subnet-mode=custom \
  --project=ragai-staging
```

**Expected output:**
```
Created [https://www.googleapis.com/compute/v1/projects/ragai-staging/global/networks/wiso-ai-vpc].
NAME          SUBNET_MODE  BGP_ROUTING_MODE  IPV4_RANGE  GATEWAY_IPV4
wiso-ai-vpc   CUSTOM       REGIONAL
```

---

## Step 3 — Create Subnets

```bash
# Subnet API (Cloud Run FastAPI)
gcloud compute networks subnets create subnet-api \
  --network=wiso-ai-vpc --region=us-central1 \
  --range=10.0.1.0/24 --project=ragai-staging

# Subnet DATA (AlloyDB + pgvector)
gcloud compute networks subnets create subnet-data \
  --network=wiso-ai-vpc --region=us-central1 \
  --range=10.0.2.0/24 --project=ragai-staging

# Subnet AI (Vertex AI PSC)
gcloud compute networks subnets create subnet-ai \
  --network=wiso-ai-vpc --region=us-central1 \
  --range=10.0.3.0/24 --project=ragai-staging

# Subnet PIPELINE (ETL Pipelines)
gcloud compute networks subnets create subnet-pipeline \
  --network=wiso-ai-vpc --region=us-central1 \
  --range=10.0.4.0/24 --project=ragai-staging
```

---

## Step 4 — Private Service Access (required for AlloyDB)

```bash
# Reserve /16 IP range for Google-managed services
gcloud compute addresses create google-managed-services-wiso \
  --global --purpose=VPC_PEERING --prefix-length=16 \
  --network=wiso-ai-vpc --project=ragai-staging

# VPC Peering with Google
gcloud services vpc-peerings connect \
  --service=servicenetworking.googleapis.com \
  --ranges=google-managed-services-wiso \
  --network=wiso-ai-vpc --project=ragai-staging
```

---

## Step 5 — Firewall Rules

```bash
# Internal traffic between subnets
gcloud compute firewall-rules create wiso-ai-allow-internal \
  --network=wiso-ai-vpc --allow=tcp,udp,icmp \
  --source-ranges=10.0.0.0/16 --project=ragai-staging

# AlloyDB port 5432
gcloud compute firewall-rules create wiso-ai-allow-alloydb \
  --network=wiso-ai-vpc --allow=tcp:5432 \
  --source-ranges=10.0.1.0/24,10.0.4.0/24 --project=ragai-staging

# AlloyDB Auth Proxy port 5433
gcloud compute firewall-rules create wiso-ai-allow-alloydb-proxy \
  --network=wiso-ai-vpc --allow=tcp:5433 \
  --source-ranges=10.0.0.0/16,127.0.0.1/32 --project=ragai-staging

# HTTPS egress
gcloud compute firewall-rules create wiso-ai-allow-https-egress \
  --network=wiso-ai-vpc --allow=tcp:443 \
  --direction=EGRESS --destination-ranges=0.0.0.0/0 \
  --project=ragai-staging
```

---

## Step 6 — Cloud Router and NAT

```bash
gcloud compute routers create wiso-ai-router \
  --network=wiso-ai-vpc --region=us-central1 --project=ragai-staging

gcloud compute routers nats create wiso-ai-nat \
  --router=wiso-ai-router --region=us-central1 \
  --auto-allocate-nat-external-ips --nat-all-subnet-ip-ranges \
  --project=ragai-staging
```

---

## Step 7 — Full Validation

```bash
echo "=========================================="
echo "VALIDATING NETWORK INFRASTRUCTURE"
echo "=========================================="

echo "1. VPC:"
gcloud compute networks describe wiso-ai-vpc \
  --format="table(name,subnetMode)" \
  --project=ragai-staging

echo "2. SUBNETS:"
gcloud compute networks subnets list \
  --network=wiso-ai-vpc \
  --format="table(name,region,ipCidrRange)" \
  --project=ragai-staging

echo "3. FIREWALL RULES:"
gcloud compute firewall-rules list \
  --filter="network=wiso-ai-vpc" \
  --format="table(name,direction,allowed)" \
  --project=ragai-staging

echo "4. CLOUD ROUTER:"
gcloud compute routers list \
  --regions=us-central1 --project=ragai-staging

echo "5. CLOUD NAT:"
gcloud compute routers nats list \
  --router=wiso-ai-router --region=us-central1 \
  --project=ragai-staging

echo "6. PRIVATE SERVICE ACCESS:"
gcloud compute addresses list \
  --filter="name=google-managed-services-wiso" \
  --format="table(name,purpose,prefixLength,status)" \
  --project=ragai-staging

echo "7. VPC PEERING:"
gcloud services vpc-peerings list \
  --network=wiso-ai-vpc --project=ragai-staging
```

**Expected output:**
```
1. VPC: wiso-ai-vpc CUSTOM
2. SUBNETS: subnet-api, subnet-data, subnet-ai, subnet-pipeline
3. FIREWALL: 4 rules created
4. ROUTER: wiso-ai-router
5. NAT: wiso-ai-nat
6. IP RANGE: google-managed-services-wiso RESERVED
7. PEERING: servicenetworking.googleapis.com ACTIVE
```

---

## Task Summary

| Resource | Name | Status |
|---|---|---|
| VPC | `wiso-ai-vpc` | ✅ |
| Subnet API | `subnet-api` (10.0.1.0/24) | ✅ |
| Subnet DATA | `subnet-data` (10.0.2.0/24) | ✅ |
| Subnet AI | `subnet-ai` (10.0.3.0/24) | ✅ |
| Subnet PIPELINE | `subnet-pipeline` (10.0.4.0/24) | ✅ |
| Private Service Access | `google-managed-services-wiso` /16 | ✅ |
| VPC Peering | `servicenetworking.googleapis.com` | ✅ |
| Firewall | 4 rules | ✅ |
| Cloud Router | `wiso-ai-router` | ✅ |
| Cloud NAT | `wiso-ai-nat` | ✅ |

*Last updated: June 2026 — M2 Task 2.0 closed*
