"""
Cross-sell Lookup — pure Python, no LLM.
Reads cross_sell_rules.json and returns suggested product IDs.
"""
import json
from pathlib import Path

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
    Input: product_id (e.g., 'PROD_001'), max_suggestions (default 2)
    Output: {
        'suggestions': ['PROD_045', 'PROD_089'],
        'reason': 'Customers who bought ...',
        'product_id': 'PROD_001'
    }
    Returns empty suggestions if no rule found.
    """
    rules = _load_rules()
    rule = rules.get(product_id)

    if not rule:
        return {"suggestions": [], "reason": "", "product_id": product_id}

    suggestions = rule.get("suggest", [])[:max_suggestions]
    return {
        "suggestions": suggestions,
        "reason": rule.get("reason", ""),
        "product_id": product_id,
    }
