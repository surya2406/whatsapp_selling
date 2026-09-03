"""
Celery task definitions for background batch polling and message processing.
"""
import asyncio
import logging
from celery import Celery

from config.settings import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "whatsapp_sales_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "fetch-and-process-every-minute": {
            "task": "api.tasks.fetch_and_process",
            "schedule": 60.0,
        },
    },
)


@celery_app.task(name="api.tasks.fetch_and_process")
def fetch_and_process(batch_id: str | None = None) -> dict:
    """Periodic or manual Celery task to fetch unread messages and create review drafts."""
    from api.workflow import fetch_analyze_and_create_drafts

    logger.info(f"Celery task started: fetch_and_process (batch_id={batch_id})")
    try:
        result = asyncio.run(fetch_analyze_and_create_drafts(batch_id))
        return result
    except Exception as e:
        logger.error(f"Celery fetch_and_process failed: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task(name="api.tasks.process_message")
def process_message(
    customer_id: str,
    customer_name: str,
    meta_message_ids: list[str],
    raw_messages: list[str],
) -> dict:
    """Celery task to run draft creation for a specific customer on demand."""
    from api.workflow import create_manual_draft

    logger.info(f"Celery task started: process_message (customer_id={customer_id})")
    try:
        result = asyncio.run(
            create_manual_draft(
                customer_id=customer_id,
                customer_name=customer_name,
                raw_messages=raw_messages,
            )
        )
        return result
    except Exception as e:
        logger.error(f"Celery process_message failed: {e}")
        return {"status": "error", "error": str(e)}
