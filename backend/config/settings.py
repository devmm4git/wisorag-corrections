"""
WISO-AI — Configuration Settings
Reads from environment variables and GCP Secret Manager.
NEVER hardcode credentials here.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # GCP Project
    gcp_project: str = "ragai-staging"
    gcp_region: str = "us-central1"

    # Environment
    environment: str = "dev"
    log_level: str = "INFO"

    # Gemini API
    gemini_api_key: str = ""

    # AlloyDB
    alloydb_host: str = "10.187.0.2"
    alloydb_port: int = 5432
    alloydb_database: str = "wiso_ai_db"
    alloydb_user: str = "postgres"
    alloydb_password: str = ""

    # BigQuery
    bigquery_project: str = "simula-ipd-produ"
    bigquery_dataset: str = "tipbord_historical"
    bigquery_table: str = "corrective_actions"

    # Vertex AI
    vertex_ai_project: str = "ragai-staging"
    vertex_ai_location: str = "us-central1"
    embedding_model: str = "text-embedding-004"
    embedding_dims: int = 768

    # Pipeline
    batch_size: int = 10
    max_chunk_size: int = 512
    chunk_overlap: int = 50

    # Server
    port: int = 8080

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
