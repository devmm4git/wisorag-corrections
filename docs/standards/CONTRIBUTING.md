# WISO-AI — Contributing Guide

## Workflow, structure and repository standards

> For any developer joining the project.
> Read this before making your first commit.

---

## Tech Stack

```
Python 3.11 · FastAPI · AlloyDB (pgvector) · Vertex AI · BigQuery · GCP · GitHub Actions
```

---

## Monorepo Structure

```
wisorag-corrections/
├── .github/
│   ├── workflows/
│   │   └── ci.yml                          ← GitHub Actions CI (flake8 + pytest)
│   └── PULL_REQUEST_TEMPLATE.md            ← Mandatory PR template
├── backend/
│   ├── app/
│   │   ├── middleware/                      ← Auth, logging, rate limiting (M3)
│   │   ├── models/                         ← Pydantic request/response models (M3)
│   │   └── routers/                        ← FastAPI endpoints (M3)
│   ├── config/
│   │   └── settings.py                     ← Pydantic Settings — env vars
│   ├── db/
│   │   ├── alloydb.py                      ← Connection pools
│   │   ├── alloydb.sql                     ← Full DDL with HNSW indexes
│   │   ├── bifquery.sql                    ← BigQuery feedback_log DDL
│   │   └── business_rules.sql              ← Feedback UPDATE rules
│   ├── pipelines/
│   │   ├── ingest_historical.py            ← Pipeline 1: BigQuery → AlloyDB (batch)
│   │   └── sync_new_ca.py                  ← Pipeline 3: real-time sync (called by M3 API)
│   ├── rag/
│   │   └── corrective_action_validator.py  ← ADR-001 validator + Field validator L1/2/3
│   └── tests/
│       ├── test_validator.py               ← ADR-001 unit tests
│       └── test_sync_new_ca.py             ← Sync pipeline unit tests
├── docs/
│   ├── api/
│   │   └── POST_corrective_actions_ingest.md  ← Swagger source of truth (M3)
│   └── standards/
│       └── CONTRIBUTING.md                 ← This file
├── infra/
│   └── environments/
│       ├── dev/                            ← Terraform dev
│       ├── uat/                            ← Terraform UAT
│       └── prod/                           ← Terraform prod
├── conftest.py                             ← pytest path config
├── pytest.ini                              ← pytest config
├── README.md
└── requirements.txt
```

---

## Git Workflow

### Golden rule

**Never commit directly to `develop` or `main`. Always via PR.**

### Step by step

```bash
# 1. Always start from updated develop
git checkout develop
git pull origin develop

# 2. Create branch
git checkout -b feat/descriptive-name     # new feature
git checkout -b fix/bug-name              # bug fix
git checkout -b docs/doc-name             # documentation only
git checkout -b refactor/name             # restructure without logic change
git checkout -b ci/name                   # CI/CD changes

# 3. Make changes in VS Code

# 4. Run flake8 BEFORE committing (mandatory)
flake8 backend/ --max-line-length=100 --exclude=__pycache__,.venv
# No output → clean code ✅
# Any output → fix before continuing

# 5. Commit and push
git add .
git commit -m "type(scope): short description"
git push origin feat/descriptive-name

# 6. Open PR on GitHub
# base: develop ← IMPORTANT
# compare: feat/descriptive-name
# Assign reviewer: wmssaas-project

# 7. Review + Approve + Squash and merge

# 8. Clean up local branch
git checkout develop
git pull origin develop
git branch -D feat/descriptive-name
```

---

## Branch Naming

| Prefix      | When to use                         | Example                      |
| ----------- | ----------------------------------- | ---------------------------- |
| `feat/`     | New feature                         | `feat/sync-new-ca-pipeline`  |
| `fix/`      | Bug fix                             | `fix/alloydb-connection-ssl` |
| `docs/`     | Documentation only                  | `docs/api-endpoint-spec`     |
| `refactor/` | Restructure without behavior change | `refactor/validator-levels`  |
| `ci/`       | CI/CD changes                       | `ci/add-coverage-report`     |
| `hotfix/`   | Urgent production fix               | `hotfix/embedding-timeout`   |

---

## Conventional Commits

```
feat(scope):     new feature
fix(scope):      bug fix
docs(scope):     documentation only
refactor(scope): restructure without behavior change
test(scope):     add or modify tests
ci(scope):       CI/CD changes
chore(scope):    maintenance tasks
```

**Real examples from this project:**

```
feat(pipeline): add sync_new_ca.py — real-time CA sync (Pipeline 3)
fix(pipeline): use named params and ssl=require for AlloyDB connection
docs(api): add POST /corrective-actions/ingest endpoint spec
fix(ci): resolve flake8 errors in field validator
```

---

## Code Standards

- **Linter:** flake8, max-line-length=100
- **Python:** 3.11
- **Tests:** pytest + pytest-asyncio
- **No `__init__.py`** — use `pythonpath = .` in pytest.ini
- **Type hints** on all public functions
- **Docstrings** on all public classes and functions
- **Logging** using `logger = logging.getLogger("wiso-ai.module")`

---

## Protected Branches

| Branch    | Rules                                                         |
| --------- | ------------------------------------------------------------- |
| `main`    | 1 approval required, no force push, no delete, linear history |
| `develop` | 1 approval required, no force push, no delete, linear history |

---

## CI — GitHub Actions

Runs automatically on every push and PR:

```
1. Checkout code
2. Setup Python 3.11
3. Install dependencies (requirements.txt)
4. flake8 — linting
5. pytest — unit tests
```

If CI fails → PR cannot be merged.

---

## Required Environment Variables

```bash
# AlloyDB
ALLOYDB_HOST=10.187.0.2          # Private IP (production)
ALLOYDB_PORT=5432
ALLOYDB_DATABASE=wiso_ai_db
ALLOYDB_USER=postgres
ALLOYDB_PASSWORD=...              # GCP Secret Manager

# Vertex AI
VERTEX_AI_PROJECT=ragai-staging
VERTEX_AI_LOCATION=us-central1

# BigQuery
BIGQUERY_PROJECT=simula-ipd-produ

# General
ENVIRONMENT=dev                   # dev | uat | prod
```

---

_Last updated: June 2026 — M2 closed_
_Owner: rag-sp@mm4.me_
