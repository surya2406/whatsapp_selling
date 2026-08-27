"""
Best Send Time — pure Python, no LLM.
Analyses historical message timestamps to find the best hour and day to reach this customer.
"""
from collections import Counter
from datetime import datetime
from typing import Optional


DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def get_best_send_time(message_timestamps: list) -> dict:
    """
    Input: list of datetime objects (or ISO strings) representing when the customer has messaged.
    Output: {
        'best_hour': int (0-23),
        'best_day': str (e.g., 'friday'),
        'confidence': 'high' | 'low'  # low if < 5 data points
    }

    Falls back to 10:00 AM Friday if not enough data.
    """
    if not message_timestamps:
        return {"best_hour": 10, "best_day": "friday", "confidence": "low"}

    datetimes = []
    for ts in message_timestamps:
        if isinstance(ts, datetime):
            datetimes.append(ts)
        else:
            try:
                datetimes.append(datetime.fromisoformat(str(ts)))
            except (ValueError, TypeError):
                continue

    if len(datetimes) < 5:
        return {"best_hour": 10, "best_day": "friday", "confidence": "low"}

    hour_counts = Counter(dt.hour for dt in datetimes)
    day_counts = Counter(dt.weekday() for dt in datetimes)

    best_hour = hour_counts.most_common(1)[0][0]
    best_day_idx = day_counts.most_common(1)[0][0]
    best_day = DAYS[best_day_idx]

    return {
        "best_hour": best_hour,
        "best_day": best_day,
        "confidence": "high",
    }
