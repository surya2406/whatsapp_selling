"""graph/nodes/load_customer_data.py — Node 1: Load customer data from local DB."""
import json
import logging
from graph.state import AgentState
from db.database import SessionLocal
from db.queries import get_customer_conversation, get_customer_purchased_products, upsert_customer
from config.settings import settings

logger = logging.getLogger(__name__)


async def load_customer_data_node(state: AgentState) -> dict:
    """
    Reads customer conversation history and past purchased products from local SQLite DB.
    This node runs AFTER the ingest pipeline (API 1) has already populated the DB.
    """
    customer_id = state["customer_id"]
    logger.info("[load_customer_data_node] START customer_id=%s", customer_id)

    try:
        async with SessionLocal() as db:
            # Ensure customer row exists
            customer = await upsert_customer(db, phone=customer_id)
            customer_name = customer.name or ""

            # Get last N messages
            messages = await get_customer_conversation(db, customer_id, settings.max_conversation_history)
            events = []
            for msg in messages:
                normalized = {}
                if msg.parsed_data:
                    try:
                        normalized = json.loads(msg.parsed_data).get("normalized_event", {})
                    except Exception:
                        normalized = {}
                events.append({
                    "meta_message_id": msg.meta_message_id,
                    "direction": normalized.get("direction", "incoming"),
                    "message_type": normalized.get("message_type", "text"),
                    "text": msg.parsed_text,
                    "created_at": normalized.get("created_at") or msg.source_timestamp,
                })

            # Get all products customer has bought (from orders)
            purchased = await get_customer_purchased_products(db, customer_id)
            purchased_products = [p if isinstance(p, str) else p.product_id for p in purchased]
            last_purchased = purchased_products[0] if purchased_products else None


        logger.info(
            "[load_customer_data_node] DONE customer_id=%s name=%s events=%d "
            "purchased_products=%d last_product=%s",
            customer_id, customer_name, len(events), len(purchased_products), last_purchased
        )
        return {
            "customer_name": customer_name,
            "conversation_events": events,
            "purchased_products": purchased_products,
            "last_purchased_product": last_purchased,
        }

    except Exception as exc:
        logger.error(
            "[load_customer_data_node] FAILED customer_id=%s error=%s",
            customer_id, exc, exc_info=True
        )
        return {
            "customer_name": "",
            "conversation_events": [],
            "purchased_products": [],
            "last_purchased_product": None,
            "error": str(exc),
        }
