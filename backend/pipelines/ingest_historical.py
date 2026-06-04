"""
WISO-AI — Historical Data Ingestion Pipeline
Pipeline 1: BigQuery (tipbord_historical) → AlloyDB (corrective_actions_vectors)

Flow:
    1. Fetch records from BigQuery
    2. Validate corrective action quality (ADR-001)
    3. Build chunk texts
    4. Generate embeddings via Vertex AI
    5. Insert valid records into AlloyDB

Usage:
    python -m backend.pipelines.ingest_historical

Owner: rag-dataengineer@mm4.me
Milestone: M2 - Task 2.2
"""
import asyncio
import logging
import sys

from google.cloud import bigquery
from google.cloud import aiplatform
import asyncpg

from backend.config.settings import settings
from backend.rag.corrective_action_validator import (
    validate_batch,
    ValidatorConfig,
    ValidationResult
)

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("wiso-ai.pipeline")


# ── Step 1: Fetch from BigQuery ────────────────────────────────────────────────
def fetch_from_bigquery() -> list[dict]:
    """
    Fetch all corrective actions from BigQuery.
    Source: simula-ipd-produ.tipbord_historical.corrective_actions
    """
    logger.info("Connecting to BigQuery...")
    client = bigquery.Client(project=settings.bigquery_project)

    query = f"""
        SELECT
            concern_id,
            plant,
            department,
            concern_description,
            corrective_action,
            severity,
            collection_point,
            product_line
        FROM `{settings.bigquery_project}.{settings.bigquery_dataset}.{settings.bigquery_table}`
        WHERE corrective_action IS NOT NULL
        AND concern_description IS NOT NULL
        ORDER BY concern_id
    """

    logger.info(
        f"Fetching from "
        f"{settings.bigquery_project}."
        f"{settings.bigquery_dataset}."
        f"{settings.bigquery_table}"
    )
    results = client.query(query).result()
    records = [dict(row) for row in results]
    logger.info(f"Fetched {len(records)} records from BigQuery")
    return records


# ── Step 2: Build chunk text ───────────────────────────────────────────────────
# ── Step 2: Build chunk text ───────────────────────────────────────────────────
def build_chunk_text(record: dict) -> str:
    """
    Build semantic chunk text for embedding.
    ONLY Concern + Corrective Action — NO metadata.
    Metadata goes as separate columns for hard filters (WHERE clause).

    Design decision (ADR-002):
    - Embedding = semantic meaning of the problem + solution
    - Metadata = department, plant, product_line (hard filters)
    This separation allows: WHERE department='PAINT' ORDER BY embedding <=> query
    """
    concern = record.get('concern_description', '').strip()
    corrective = record.get('corrective_action', '').strip()
    return f"Concern: {concern}\n\nCorrective Action: {corrective}"


# ── Step 2b: Build chunk ID ────────────────────────────────────────────────────
def build_chunk_id(record: dict) -> str:
    """
    Build semantic chunk ID for cross-system tracking.
    Format: DEPARTMENT_PRODUCTLINE_CONCERNID
    Example: PAINT_RANGER_C001
    Used in BigQuery feedback_log as FK.
    """
    dept = record.get('department', 'UNK').replace(' ', '').upper()
    pl = record.get('product_line', 'UNK').replace(' ', '').upper()
    cid = record.get('concern_id', 'UNK').upper()
    return f"{dept}_{pl}_{cid}"


# ── Step 3: Generate embeddings ────────────────────────────────────────────────
def generate_embeddings(texts: list[str]) -> list[list[float]]:
    """
    Generate 768-dim embeddings via Vertex AI text-embedding-004.
    Processes in batches to respect API quotas.
    """
    logger.info(f"Initializing Vertex AI embeddings for {len(texts)} texts...")
    aiplatform.init(
        project=settings.vertex_ai_project,
        location=settings.vertex_ai_location
    )

    from vertexai.language_models import TextEmbeddingModel
    model = TextEmbeddingModel.from_pretrained(settings.embedding_model)

    embeddings = []
    total_batches = (len(texts) + settings.batch_size - 1) // settings.batch_size

    for i in range(0, len(texts), settings.batch_size):
        batch = texts[i:i + settings.batch_size]
        batch_num = i // settings.batch_size + 1
        logger.info(f"Embedding batch {batch_num}/{total_batches} ({len(batch)} texts)...")
        batch_embeddings = model.get_embeddings(batch)
        embeddings.extend([e.values for e in batch_embeddings])

    logger.info(
        f"Generated {len(embeddings)} embeddings "
        f"({settings.embedding_dims} dims each)"
    )
    return embeddings


# ── Step 4: Insert to AlloyDB ──────────────────────────────────────────────────
# ── Step 4: Insert to AlloyDB ──────────────────────────────────────────────────
async def insert_to_alloydb(
    records: list[dict],
    embeddings: list[list[float]]
) -> int:
    """
    Bulk insert validated records + embeddings into AlloyDB.
    Uses ON CONFLICT DO NOTHING for idempotency — safe to re-run.
    chunk_id is the semantic unique key for cross-system tracking.
    """
    logger.info(f"Connecting to AlloyDB {settings.alloydb_host}...")

    pool = await asyncpg.create_pool(
        host=settings.alloydb_host,
        port=settings.alloydb_port,
        database=settings.alloydb_database,
        user=settings.alloydb_user,
        password=settings.alloydb_password,
        ssl='require',
    )

    insert_query = """
        INSERT INTO corrective_actions_vectors (
            chunk_id,
            concern_id, plant, department,
            concern_description, corrective_action,
            severity, collection_point, product_line,
            charged_zone,
            chunk_text, embedding
        ) VALUES (
            $1,
            $2, $3, $4, $5, $6, $7, $8, $9, $10,
            $11, $12::vector
        )
        ON CONFLICT (chunk_id) DO NOTHING
    """

    inserted = 0
    failed = 0

    async with pool.acquire() as conn:
        for record, embedding in zip(records, embeddings):
            try:
                chunk_id = build_chunk_id(record)
                chunk_text = build_chunk_text(record)
                embedding_str = f"[{','.join(map(str, embedding))}]"

                await conn.execute(
                    insert_query,
                    chunk_id,
                    record.get('concern_id'),
                    record.get('plant'),
                    record.get('department'),
                    record.get('concern_description'),
                    record.get('corrective_action'),
                    record.get('severity'),
                    record.get('collection_point'),
                    record.get('product_line'),
                    record.get('charged_zone'),
                    chunk_text,
                    embedding_str
                )
                inserted += 1
                logger.info(f"Inserted: {chunk_id}")

            except Exception as e:
                logger.error(
                    f"Failed to insert {record.get('concern_id')}: {e}"
                )
                failed += 1

    await pool.close()
    logger.info(f"AlloyDB: {inserted} inserted, {failed} failed")
    return inserted


# ── Pipeline Report ────────────────────────────────────────────────────────────
def log_rejection_report(rejected: list[ValidationResult]):
    """Log a summary of all rejected corrective actions."""
    if not rejected:
        logger.info("No rejections — all records passed validation")
        return

    logger.warning(f"{'='*60}")
    logger.warning(f"REJECTION REPORT — {len(rejected)} records rejected")
    logger.warning(f"{'='*60}")

    by_status = {}
    for r in rejected:
        key = r.status.value
        by_status[key] = by_status.get(key, 0) + 1

    for status, count in sorted(by_status.items()):
        logger.warning(f"  {status}: {count}")

    logger.warning(f"{'='*60}")
    logger.warning("Rejected concern IDs:")
    for r in rejected:
        logger.warning(f"  [{r.concern_id}] {r.reason[:80]}")


# ── Main Orchestrator ──────────────────────────────────────────────────────────
async def run_pipeline():
    """
    Main pipeline orchestrator.
    BigQuery → Validate → Chunk → Embed → AlloyDB
    """
    logger.info("=" * 60)
    logger.info("WISO-AI Historical Ingestion Pipeline — START")
    logger.info(f"Environment  : {settings.environment}")
    logger.info(f"Source       : {settings.bigquery_project}.{settings.bigquery_dataset}")
    logger.info(f"Target       : AlloyDB {settings.alloydb_host}/{settings.alloydb_database}")
    logger.info(f"Embedding    : {settings.embedding_model} ({settings.embedding_dims} dims)")
    logger.info("=" * 60)

    # ── Step 1: Fetch ──────────────────────────────────────────────────────
    records = fetch_from_bigquery()
    if not records:
        logger.error("No records fetched from BigQuery. Aborting.")
        return

    # ── Step 2: Validate (ADR-001) ─────────────────────────────────────────
    logger.info(f"Validating {len(records)} corrective actions (ADR-001)...")
    validator_config = ValidatorConfig(
        ai_enabled=True,
        ai_quality_threshold=0.6,
        min_chars=30,
        min_words=5
    )
    valid_records, rejected = await validate_batch(
        records,
        config=validator_config
    )

    log_rejection_report(rejected)
    logger.info(
        f"Validation complete: "
        f"{len(valid_records)}/{len(records)} records valid"
    )

    if not valid_records:
        logger.error("No valid records after validation. Aborting.")
        return

    # ── Step 3: Build chunks ───────────────────────────────────────────────
    logger.info("Building chunk texts...")
    chunk_texts = [build_chunk_text(r) for r in valid_records]

    # ── Step 4: Generate embeddings ────────────────────────────────────────
    embeddings = generate_embeddings(chunk_texts)

    # ── Step 5: Insert to AlloyDB ──────────────────────────────────────────
    inserted = await insert_to_alloydb(valid_records, embeddings)

    # ── Summary ────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("WISO-AI Historical Ingestion Pipeline — COMPLETE")
    logger.info(f"  Total fetched   : {len(records)}")
    logger.info(f"  Valid records   : {len(valid_records)}")
    logger.info(f"  Rejected        : {len(rejected)}")
    logger.info(f"  Inserted        : {inserted}")
    logger.info(f"  Success rate    : {inserted/len(records)*100:.1f}%")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_pipeline())
