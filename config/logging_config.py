"""
config/logging_config.py — Centralized logging setup.

Call `setup_logging()` once from api/main.py startup.
All modules use `logging.getLogger(__name__)` — no further config needed.

Log format example:
  2026-09-02 21:05:01 | INFO  | api.workflow                       | [_create_customer_draft] START customer=919876543210
  2026-09-02 21:05:02 | ERROR | agent.tools.core_tools             | [get_customer_profile] FAILED: Connection refused
"""
import logging
import sys


LOG_FORMAT = "%(asctime)s | %(levelname)-5s | %(name)-35s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger. Call once at application startup."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicate logs on reload
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(numeric_level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(handler)

    # Suppress noisy third-party libs — only WARNING+ from these
    for noisy_lib in [
        "httpx", "httpcore", "litellm", "aiomysql",
        "aiosqlite", "sqlalchemy.engine", "openai", "urllib3",
    ]:
        logging.getLogger(noisy_lib).setLevel(logging.WARNING)

    logging.info("Logging initialised at level=%s", level.upper())
