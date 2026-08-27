"""
Redis cache helpers.
Keys follow the pattern documented in PLAN.md §11.
All values are stored as JSON strings.
"""
import json
import logging
from typing import Any, Optional

import redis
from config.settings import settings

logger = logging.getLogger(__name__)

# ─── Key patterns ─────────────────────────────────────────────────────────────
KEY_PROFILE = "profile:{customer_id}"
KEY_SEGMENT = "segment:{customer_id}"
KEY_OFFERS_ACTIVE = "offers:active"
KEY_RULES_CROSS_SELL = "rules:cross_sell"
KEY_CONV_SUMMARY = "conv_summary:{customer_id}"


def get_redis() -> redis.Redis:
    """Return a Redis connection. Lazy singleton per call."""
    return redis.from_url(settings.redis_url, decode_responses=True)


def set_cache(key: str, value: Any, ttl_seconds: int = 3600) -> bool:
    """Store a value in Redis as JSON. Returns True on success."""
    try:
        r = get_redis()
        r.setex(key, ttl_seconds, json.dumps(value))
        return True
    except Exception as e:
        logger.warning(f"Redis set failed for key={key}: {e}")
        return False


def get_cache(key: str) -> Optional[Any]:
    """Retrieve and deserialize a value from Redis. Returns None on miss or error."""
    try:
        r = get_redis()
        raw = r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Redis get failed for key={key}: {e}")
        return None


def delete_cache(key: str) -> bool:
    """Delete a key from Redis. Returns True on success."""
    try:
        r = get_redis()
        r.delete(key)
        return True
    except Exception as e:
        logger.warning(f"Redis delete failed for key={key}: {e}")
        return False


# ─── Convenience wrappers ─────────────────────────────────────────────────────

def cache_customer_profile(customer_id: str, profile: dict) -> None:
    key = KEY_PROFILE.format(customer_id=customer_id)
    set_cache(key, profile, ttl_seconds=settings.profile_cache_ttl_seconds)


def get_cached_customer_profile(customer_id: str) -> Optional[dict]:
    key = KEY_PROFILE.format(customer_id=customer_id)
    return get_cache(key)


def invalidate_customer_profile(customer_id: str) -> None:
    delete_cache(KEY_PROFILE.format(customer_id=customer_id))
    delete_cache(KEY_SEGMENT.format(customer_id=customer_id))


def cache_conv_summary(customer_id: str, summary: dict) -> None:
    key = KEY_CONV_SUMMARY.format(customer_id=customer_id)
    set_cache(key, summary, ttl_seconds=900)  # 15 min


def get_cached_conv_summary(customer_id: str) -> Optional[dict]:
    key = KEY_CONV_SUMMARY.format(customer_id=customer_id)
    return get_cache(key)


def invalidate_conv_summary(customer_id: str) -> None:
    delete_cache(KEY_CONV_SUMMARY.format(customer_id=customer_id))


def cache_active_offers(offers: list) -> None:
    set_cache(KEY_OFFERS_ACTIVE, offers, ttl_seconds=settings.offers_cache_ttl_seconds)


def get_cached_active_offers() -> Optional[list]:
    return get_cache(KEY_OFFERS_ACTIVE)


def cache_cross_sell_rules(rules: dict) -> None:
    set_cache(KEY_RULES_CROSS_SELL, rules, ttl_seconds=21600)  # 6 hours


def get_cached_cross_sell_rules() -> Optional[dict]:
    return get_cache(KEY_RULES_CROSS_SELL)
