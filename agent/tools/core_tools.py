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
    """
    Fetches the customer's purchase history and returns their RFM profile.
    Returns segment (new/repeat/high_value/dormant), churn_risk,
    rfm_score, and last_purchased_product_id.
    
    Args:
        customer_id: The customer's phone number (e.g. '+919876543210').
        customer_name: Optional display name for the customer.
        
    Returns:
        A dict with keys: segment, rfm_score, rfm_recency, rfm_frequency,
        rfm_monetary, last_purchased_product, days_since_last_purchase,
        churn_risk.
    """
    # Try cache first
    cached = get_cached_customer_profile(customer_id)
    if cached:
        return cached

    async with SessionLocal() as db:
        customer = await upsert_customer(db, phone=customer_id, name=customer_name)
        purchases_orm = await get_customer_purchases(db, customer_id)
        
        purchases = [
            {
                "product_id": p.product_id,
                "amount": p.amount,
                "purchased_at": p.purchased_at,
            }
            for p in purchases_orm
        ]
        
        rfm = calculate_rfm(purchases)
        segment = assign_segment(rfm)
        # Churn thresholds calibrated for welding B2B project-based buying cycles
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
            "days_since_last_purchase": rfm["recency_days"],
            "churn_risk": churn_risk,
        }
        
        # Async Redis cache if you want to make cache client async, 
        # for now run in executor or if it's fast sync keep it
        await asyncio.to_thread(cache_customer_profile, customer_id, profile)
        return profile


async def get_cross_sell_options(product_id: str, max_suggestions: int = 3) -> dict:
    """
    Given the customer's last purchased product ID, returns a list of
    complementary product IDs that can be recommended as cross-sell items.
    Only call this tool when the customer has a known last purchase.
    """
    return await asyncio.to_thread(_cross_sell_lookup, product_id, max_suggestions)


async def get_product_info(product_id: str) -> dict:
    """
    Looks up a product by its ID and returns its name, price, and description.
    Use this to resolve product IDs into human-readable names before writing
    the final WhatsApp message.
    """
    def _read():
        try:
            with open(_COMMON_LOOKUPS_DIR / "products.json", encoding="utf-8") as f:
                return json.load(f).get(product_id, {})
        except Exception as e:
            logger.error(f"get_product_info failed: {e}")
            return {}
    return await asyncio.to_thread(_read)


async def get_message_template(template_key: str) -> str:
    """
    Returns the raw WhatsApp message template string for a given template key.
    Use this as a starting point, then fill in the placeholders naturally.
    """
    def _read():
        try:
            with open(_AGENT_LOOKUPS_DIR / "message_templates.json", encoding="utf-8") as f:
                templates = json.load(f)
            return templates.get(template_key, templates.get("general_reply", "Hi {name}!"))
        except Exception as e:
            logger.error(f"get_message_template failed: {e}")
            return "Hi! Thanks for reaching out. 😊"
    return await asyncio.to_thread(_read)
