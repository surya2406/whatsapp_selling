"""graph/checkpointer.py — LangGraph SQLite checkpointer setup."""
import logging
import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger(__name__)

DB_PATH = "whatsapp_agent.db"
_conn = None
_saver = None


async def get_checkpointer() -> AsyncSqliteSaver:
    """Return an initialized AsyncSqliteSaver backed by SQLite."""
    global _conn, _saver
    if _saver is None:
        logger.info("[checkpointer] Initializing AsyncSqliteSaver at %s", DB_PATH)
        _conn = await aiosqlite.connect(DB_PATH)
        _saver = AsyncSqliteSaver(_conn)
        await _saver.setup()
        logger.info("[checkpointer] AsyncSqliteSaver setup complete")
    return _saver


async def close_checkpointer():
    """Close checkpointer connection on shutdown."""
    global _conn, _saver
    if _conn is not None:
        await _conn.close()
        _conn = None
        _saver = None
        logger.info("[checkpointer] Connection closed")

