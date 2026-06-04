# WISO-AI — RAG System for WISOHUB

**Client:** FXVIEW Company  
**Vendor:** XOF India  
**Stack:** Python · FastAPI · AlloyDB · Vertex AI · GCP

## Overview

AI-powered corrective action recommendation system. When a quality concern
tips at 30 minutes in WISOHUB, WISO-AI semantically searches historical
corrective actions and generates a recommendation via Vertex AI LLM.

## Architecture

BigQuery (historical data)
└── Python ETL Pipeline
└── Vertex AI Embeddings (text-embedding-004, 768 dims)
└── AlloyDB + pgvector (HNSW index, <100ms search)
└── FastAPI RAG Engine
└── Vertex AI LLM (Gemini Pro)
└── WISOHUB (React + SwiftUI)

## Project Structure

- `backend/pipelines/` — Data ingestion & sync pipelines
- `backend/rag/` — RAG orchestration (retriever, embedder, prompt)
- `backend/app/` — FastAPI REST API
- `backend/db/` — AlloyDB & BigQuery connectors
- `infra/` — Terraform IaC (dev/uat/prod)

## Environments

| Environment | GCP Project   | Branch  |
| ----------- | ------------- | ------- |
| Sandbox     | ragai-staging | develop |
| UAT         | ragai-uat     | uat     |
| Production  | ragai-prod    | main    |

## Setup

See `docs/` for full setup guide.

## Team

- AI PM: rag-sp@mm4.me
- Architect: rag-architect@mm4.me
- Data Engineer: rag-dataengineer@mm4.me
- ML Engineer: rag-mlengineer@mm4.me
- DevOps: rag-devops@mm4.me
