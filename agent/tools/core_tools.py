import json
import logging
from pathlib import Path
import asyncio

from db.database import SessionLocal
from db.queries import get_customer_purchases, upsert_customer
from skills.profiler.scripts.rfm import calculate_rfm, assign_segment
from skills.cross_sell_agent.scripts.cross_sell_helper import get_cross_sell_suggestions as _cross_sell_lookup
from cache.redis_client import cache_customer_profile, get_cached_customer_profile

logger = logging.getLogger(__name__)

# Common lookups shared across all agents (products, segments, etc.)
_COMMON_LOOKUPS_DIR = Path(__file__).parent.parent.parent / "lookups"
# Cross-sell agent specific lookups (message templates, cross-sell rules, etc.)
_AGENT_LOOKUPS_DIR = Path(__file__).parent.parent.parent / "skills" / "cross_sell_agent" / "assets" / "lookups"


async def get_customer_profile(customer_id: str, customer_name: str = "") -> dict:
    """Fetches the customer's RFM profile from DB (or Redis cache)."""
    logger.info("[get_customer_profile] START customer_id=%s", customer_id)
    cached = get_cached_customer_profile(customer_id)
    if cached:
        logger.info("[get_customer_profile] CACHE HIT customer_id=%s segment=%s", customer_id, cached.get("segment"))
        return cached
    logger.debug("[get_customer_profile] Cache miss — querying DB for customer_id=%s", customer_id)
    try:
        async with SessionLocal() as db:
            customer = await upsert_customer(db, phone=customer_id, name=customer_name)
            purchases_orm = await get_customer_purchases(db, customer_id)
            purchases = [{"product_id": p.product_id, "amount": p.amount, "purchased_at": p.purchased_at} for p in purchases_orm]
            logger.debug("[get_customer_profile] Loaded %d purchases for customer_id=%s", len(purchases), customer_id)
            rfm = calculate_rfm(purchases)
            segment = assign_segment(rfm)
            if rfm["recency_days"] > 120:
                churn_risk = "high"
            elif rfm["recency_days"] > 90:
                churn_risk = "medium"
            else:
                churn_risk = "low"
            profile = {
                "customer_id": customer_id,
                "name": customer.name or customer_name,
                "segment": segment,
                "rfm_score": rfm["rfm_score"],
                "rfm_recency": rfm["recency_days"],
                "rfm_frequency": rfm["frequency_count"],
                "rfm_monetary": rfm["monetary_total"],
                "last_purchased_product": rfm["last_purchased_product"],
                "purchased_products": list(dict.fromkeys(p["product_id"] for p in purchases if p.get("product_id"))),
                "days_since_last_purchase": rfm["recency_days"],
                "churn_risk": churn_risk,
            }
            await asyncio.to_thread(cache_customer_profile, customer_id, profile)
            logger.info(
                "[get_customer_profile] DONE customer_id=%s segment=%s rfm_score=%s purchases=%d churn_risk=%s last_product=%s",
                customer_id, segment, rfm["rfm_score"], len(purchases), churn_risk, rfm["last_purchased_product"]
            )
            return profile
    except Exception as exc:
        logger.error("[get_customer_profile] FAILED customer_id=%s error=%s", customer_id, exc, exc_info=True)
        raise


async def get_cross_sell_options(product_id: str, max_suggestions: int = 3) -> dict:
    """Returns complementary product IDs for cross-sell based on last purchased product."""
    logger.info("[get_cross_sell_options] START product_id=%s max=%d", product_id, max_suggestions)
    try:
        result = await asyncio.to_thread(_cross_sell_lookup, product_id, max_suggestions)
        logger.info("[get_cross_sell_options] DONE product_id=%s suggestions=%s reason=%s", product_id, result.get("suggestions"), result.get("reason"))
        return result
    except Exception as exc:
        logger.error("[get_cross_sell_options] FAILED product_id=%s error=%s", product_id, exc, exc_info=True)
        raise


async def get_product_info(product_id: str) -> dict:
    """Looks up a product by its ID and returns its name, price, and description."""
    logger.info("[get_product_info] START product_id=%s", product_id)
    def _read():
        try:
            with open(_COMMON_LOOKUPS_DIR / "products.json", encoding="utf-8") as f:
                return json.load(f).get(product_id, {})
        except Exception as e:
            logger.error("[get_product_info] File read failed product_id=%s error=%s", product_id, e)
            return {}
    try:
        result = await asyncio.to_thread(_read)
        if result:
            logger.info("[get_product_info] DONE product_id=%s name=%s", product_id, result.get("name", "unknown"))
        else:
            logger.warning("[get_product_info] Product NOT FOUND in catalog product_id=%s", product_id)
        return result
    except Exception as exc:
        logger.error("[get_product_info] FAILED product_id=%s error=%s", product_id, exc, exc_info=True)
        raise


async def get_message_template(template_key: str) -> str:
    """Returns the raw WhatsApp message template string for a given template key."""
    logger.info("[get_message_template] START template_key=%s", template_key)
    def _read():
        try:
            with open(_AGENT_LOOKUPS_DIR / "message_templates.json", encoding="utf-8") as f:
                templates = json.load(f)
            return templates.get(template_key, templates.get("general_reply", "Hi {name}!"))
        except Exception as e:
            logger.error("[get_message_template] File read failed key=%s error=%s", template_key, e)
            return "Hi! Thanks for reaching out."
    try:
        result = await asyncio.to_thread(_read)
        logger.info("[get_message_template] DONE template_key=%s len=%d", template_key, len(result))
        return result
    except Exception as exc:
        logger.error("[get_message_template] FAILED key=%s error=%s", template_key, exc, exc_info=True)
        raise
