"""
RFM Scorer — pure Python, no LLM.
Calculates Recency, Frequency, Monetary values and assigns a 1-5 score per axis.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

LOOKUPS_DIR = Path(__file__).parent.parent.parent.parent / "lookups"


def _load_segments() -> dict:
    with open(LOOKUPS_DIR / "segments.json") as f:
        return json.load(f)


def calculate_rfm(purchases: list) -> dict:
    """
    Input: list of purchase dicts with keys: { product_id, amount, purchased_at (datetime) }
    Output: {
        recency_days: int,
        frequency_count: int,
        monetary_total: float,
        rfm_score: int (1-5),
        last_purchased_product: str | None
    }
    """
    if not purchases:
        return {
            "recency_days": 9999,
            "frequency_count": 0,
            "monetary_total": 0.0,
            "rfm_score": 1,
            "last_purchased_product": None,
        }

    now = datetime.utcnow()

    # Sort by date descending
    sorted_purchases = sorted(
        purchases,
        key=lambda p: p["purchased_at"] if isinstance(p["purchased_at"], datetime) else datetime.fromisoformat(str(p["purchased_at"])),
        reverse=True,
    )

    last_purchase_dt = sorted_purchases[0]["purchased_at"]
    if not isinstance(last_purchase_dt, datetime):
        last_purchase_dt = datetime.fromisoformat(str(last_purchase_dt))

    recency_days = (now - last_purchase_dt).days
    frequency_count = len(purchases)
    monetary_total = sum(float(p.get("amount", 0)) for p in purchases)
    last_purchased_product = sorted_purchases[0].get("product_id")

    rfm_score = _compute_rfm_score(recency_days, frequency_count, monetary_total)

    return {
        "recency_days": recency_days,
        "frequency_count": frequency_count,
        "monetary_total": monetary_total,
        "rfm_score": rfm_score,
        "last_purchased_product": last_purchased_product,
    }


def _compute_rfm_score(recency_days: int, frequency: int, monetary: float) -> int:
    """Returns a combined RFM score from 1 (low value) to 5 (high value)."""
    # Recency score (lower days = higher score)
    if recency_days <= 7:
        r = 5
    elif recency_days <= 30:
        r = 4
    elif recency_days <= 60:
        r = 3
    elif recency_days <= 120:
        r = 2
    else:
        r = 1

    # Frequency score
    if frequency >= 10:
        f = 5
    elif frequency >= 6:
        f = 4
    elif frequency >= 3:
        f = 3
    elif frequency >= 2:
        f = 2
    else:
        f = 1

    # Monetary score — calibrated for welding B2B (single electrode box = ₹1,830+)
    if monetary >= 100000:
        m = 5
    elif monetary >= 50000:
        m = 4
    elif monetary >= 20000:
        m = 3
    elif monetary >= 5000:
        m = 2
    else:
        m = 1

    # Weighted average: recency and frequency matter more for WhatsApp sales
    weighted = (r * 2 + f * 2 + m * 1) / 5
    return max(1, min(5, round(weighted)))


def assign_segment(rfm_result: dict) -> str:
    """
    Assigns a customer segment based on RFM result.
    Returns one of: 'new', 'repeat', 'high_value', 'dormant'
    """
    segments = _load_segments()
    frequency = rfm_result["frequency_count"]
    recency_days = rfm_result["recency_days"]
    monetary = rfm_result["monetary_total"]

    # Dormant check first
    dormant_threshold = segments.get("dormant", {}).get("inactive_days", 60)
    if recency_days >= dormant_threshold and frequency > 0:
        return "dormant"

    # High value
    hv = segments.get("high_value", {})
    if frequency >= hv.get("min_orders", 10) or monetary >= hv.get("or_min_spend", 5000):
        return "high_value"

    # Repeat
    repeat = segments.get("repeat", {})
    if frequency >= repeat.get("min_orders", 2):
        return "repeat"

    # Default: new
    return "new"
