"""
Cross-sell Lookup — pure Python, no LLM.
Reads cross_sell_rules.json and returns suggested product IDs.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
LOOKUPS_DIR = Path(__file__).parent.parent / "assets" / "lookups"


_rules_cache: dict | None = None


def _load_rules() -> dict:
    global _rules_cache
    if _rules_cache is None:
        with open(LOOKUPS_DIR / "cross_sell_rules.json") as f:
            _rules_cache = json.load(f)
    return _rules_cache


def get_cross_sell_suggestions(product_id: str, max_suggestions: int = 2) -> dict:
    """
    Input: product_id (e.g., 'FG000046'), max_suggestions (default 2)
    Output: {
        'suggestions': ['FG000062', 'FG000104'],
        'reason': 'Customers who bought ...',
        'product_id': 'FG000046'
    }
    Returns empty suggestions if no rule found.
    """
    logger.debug("[get_cross_sell_suggestions] START product_id=%s max=%d", product_id, max_suggestions)
    try:
        rules = _load_rules()
    except Exception as exc:
        logger.error("[get_cross_sell_suggestions] Failed to load rules file error=%s", exc, exc_info=True)
        return {"suggestions": [], "reason": "", "product_id": product_id}

    rule = rules.get(product_id)

    if not rule:
        logger.warning("[get_cross_sell_suggestions] No rule found for product_id=%s", product_id)
        return {"suggestions": [], "reason": "", "product_id": product_id}

    suggestions = rule.get("suggest", [])[:max_suggestions]
    result = {
        "suggestions": suggestions,
        "reason": rule.get("reason", ""),
        "product_id": product_id,
    }
    logger.debug(
        "[get_cross_sell_suggestions] DONE product_id=%s suggestions=%s",
        product_id, suggestions
    )
    return result

