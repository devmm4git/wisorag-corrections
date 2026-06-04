-- ============================================================
-- WISO-AI — AlloyDB Vector Store
-- Database: wiso_ai_db
-- Tabla: corrective_actions_vectors
-- ============================================================

-- Habilitar pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Tabla principal de vectores
CREATE TABLE corrective_actions_vectors (
    -- ── Identificador ─────────────────────────────────────
    id                  SERIAL PRIMARY KEY,

    -- ── Trazabilidad ──────────────────────────────────────
    concern_id          VARCHAR(50)     NOT NULL,

    -- ── Metadata — filtros duros (WHERE clause) ───────────
    plant               VARCHAR(100),
    department          VARCHAR(100),
    severity            VARCHAR(10),
    collection_point    VARCHAR(100),
    product_line        VARCHAR(100),
    charged_zone        VARCHAR(100),

    -- ── Texto original ────────────────────────────────────
    concern_description TEXT,
    corrective_action   TEXT,

    -- ── Embedding — INMUTABLE, nunca se modifica ──────────
    chunk_text          TEXT            NOT NULL,
    embedding           vector(768),

    -- ── Feedback — solo UPDATE, sin re-embedding ──────────
    feedback_score      FLOAT           DEFAULT 0.0,
    accept_count        INTEGER         DEFAULT 0,
    reject_count        INTEGER         DEFAULT 0,

    -- ── Contexto temporal ─────────────────────────────────
    resolved_at         TIMESTAMP,
    mttr_minutes        INTEGER,

    -- ── Auditoría ─────────────────────────────────────────
    created_at          TIMESTAMP       DEFAULT NOW(),
    updated_at          TIMESTAMP       DEFAULT NOW()
);

-- Índice HNSW para búsqueda semántica <100ms
-- m=16: conexiones por nodo (balance precisión/memoria)
-- ef_construction=64: calidad del índice en construcción
-- vector_cosine_ops: similitud coseno para embeddings de texto

CREATE INDEX idx_embedding_hnsw
  ON corrective_actions_vectors
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
  
-- Índices para filtros duros
CREATE INDEX idx_department
    ON corrective_actions_vectors (department);

CREATE INDEX idx_product_line
    ON corrective_actions_vectors (product_line);

CREATE INDEX idx_plant
    ON corrective_actions_vectors (plant);

CREATE INDEX idx_department_product_line
    ON corrective_actions_vectors (department, product_line);