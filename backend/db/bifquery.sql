-- ============================================================
-- WISO-AI — BigQuery Feedback Log
-- Project: simula-ipd-produ
-- Dataset: tipbord_historical
-- Tabla: feedback_log
-- Particionada por fecha para analytics eficiente
-- ============================================================

CREATE TABLE IF NOT EXISTS
  `simula-ipd-produ.tipbord_historical.feedback_log` (

    -- ── Identificador del evento ───────────────────────────
    event_id          STRING        NOT NULL,

    -- ── FK → AlloyDB corrective_actions_vectors.id ─────────
    vector_id         INT64         NOT NULL,

    -- ── FK → Concern original en WISOHUB ──────────────────
    concern_id        STRING        NOT NULL,

    -- ── Acción del coach ──────────────────────────────────
    action            STRING        NOT NULL,
    -- valores: ACCEPT | REJECT | MODIFY

    -- ── Quién dio el feedback ─────────────────────────────
    coach_cds_id      STRING        NOT NULL,

    -- ── Contexto — repetido para analytics sin JOIN ───────
    plant_id          STRING,
    department        STRING,
    product_line      STRING,

    -- ── Scores al momento del feedback ───────────────────
    similarity_score  FLOAT64,
    effective_score   FLOAT64,
    -- effective_score = similarity_score × feedback_score

    -- ── Solo si action = MODIFY ───────────────────────────
    modified_text     STRING,

    -- ── Contexto de sesión ────────────────────────────────
    session_id        STRING,

    -- ── Timestamp ─────────────────────────────────────────
    created_at        TIMESTAMP     NOT NULL,
    partition_date    DATE          NOT NULL
    -- partition_date = DATE(created_at)
)
PARTITION BY partition_date
CLUSTER BY department, product_line, action
OPTIONS (
  description = 'WISO-AI feedback log — coach accept/reject/modify events',
  require_partition_filter = FALSE
);