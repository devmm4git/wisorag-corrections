"""
WISO-AI — AlloyDB Connection Manager
Two pools: read (replica) and write (primary).
NEVER write to replica. NEVER read from primary when replica available.
"""
import asyncpg
import logging
from backend.config.settings import settings

logger = logging.getLogger(__name__)

_write_pool = None


async def get_write_pool():
    """Returns connection pool for write operations (INSERT, UPDATE)."""
    global _write_pool
    if _write_pool is None:
        connection_string = (
            f"postgresql://{settings.alloydb_user}:"
            f"{settings.alloydb_password}@"
            f"{settings.alloydb_host}:"
            f"{settings.alloydb_port}/"
            f"{settings.alloydb_database}"
        )
        _write_pool = await asyncpg.create_pool(connection_string)
        logger.info("AlloyDB write pool created")
    return _write_pool


async def close_pools():
    """Close all connection pools gracefully."""
    global _write_pool
    if _write_pool is not None:
        await _write_pool.close()
        _write_pool = None
        logger.info("AlloyDB pools closed")
