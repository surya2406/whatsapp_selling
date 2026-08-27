"""
Unit tests for all skills — zero LLM calls.
Skills must pass all tests in pure Python.
"""
import pytest
from datetime import datetime, timedelta

from skills.profiler.scripts.rfm import calculate_rfm, assign_segment
from skills.parser.scripts.sentiment import classify_sentiment
from skills.cross_sell_agent.scripts.cross_sell_helper import get_cross_sell_suggestions
from skills.timing.scripts.timing_helper import get_best_send_time


# ── RFM Tests ──────────────────────────────────────────────────────────────────

class TestRFM:
    def test_empty_purchases_returns_defaults(self):
        result = calculate_rfm([])
        assert result["frequency_count"] == 0
        assert result["rfm_score"] == 1
        assert result["last_purchased_product"] is None

    def test_recent_frequent_buyer_gets_high_score(self):
        now = datetime.utcnow()
        purchases = [
            {"product_id": "PROD_001", "amount": 500, "purchased_at": now - timedelta(days=2)},
            {"product_id": "PROD_045", "amount": 800, "purchased_at": now - timedelta(days=10)},
            {"product_id": "PROD_089", "amount": 300, "purchased_at": now - timedelta(days=20)},
        ]
        result = calculate_rfm(purchases)
        assert result["rfm_score"] >= 3
        assert result["frequency_count"] == 3
        assert result["last_purchased_product"] == "PROD_001"

    def test_dormant_customer_assigned_dormant_segment(self):
        now = datetime.utcnow()
        rfm = {
            "recency_days": 90,
            "frequency_count": 3,
            "monetary_total": 900,
        }
        segment = assign_segment(rfm)
        assert segment == "dormant"

    def test_high_value_customer_by_spend(self):
        rfm = {
            "recency_days": 5,
            "frequency_count": 2,
            "monetary_total": 6000,
        }
        segment = assign_segment(rfm)
        assert segment == "high_value"

    def test_new_customer_segment(self):
        rfm = {
            "recency_days": 1,
            "frequency_count": 1,
            "monetary_total": 299,
        }
        segment = assign_segment(rfm)
        assert segment == "new"


# ── Sentiment Tests ─────────────────────────────────────────────────────────────

class TestSentiment:
    def test_positive_messages(self):
        messages = ["I love the product!", "Thanks so much, great quality"]
        assert classify_sentiment(messages) == "positive"

    def test_negative_messages(self):
        messages = ["I want a refund", "Terrible quality, very disappointed"]
        assert classify_sentiment(messages) == "negative"

    def test_neutral_messages(self):
        messages = ["Hello", "When will the order arrive?"]
        assert classify_sentiment(messages) == "neutral"

    def test_empty_returns_neutral(self):
        assert classify_sentiment([]) == "neutral"

    def test_negative_beats_positive(self):
        # Negative should win even with some positive words
        messages = ["I love this brand but the product is terrible and I want a refund"]
        assert classify_sentiment(messages) == "negative"


# ── Cross-sell Tests ─────────────────────────────────────────────────────────────

class TestCrossSell:
    def test_known_product_returns_suggestions(self):
        result = get_cross_sell_suggestions("FG000008")
        assert len(result["suggestions"]) > 0
        assert result["product_id"] == "FG000008"

    def test_unknown_product_returns_empty(self):
        result = get_cross_sell_suggestions("PROD_UNKNOWN")
        assert result["suggestions"] == []

    def test_max_suggestions_respected(self):
        result = get_cross_sell_suggestions("FG000008", max_suggestions=1)
        assert len(result["suggestions"]) <= 1





# ── Timing Tests ─────────────────────────────────────────────────────────────────

class TestTiming:
    def test_empty_timestamps_returns_defaults(self):
        result = get_best_send_time([])
        assert result["confidence"] == "low"
        assert result["best_hour"] == 10

    def test_insufficient_data_returns_low_confidence(self):
        ts = [datetime.utcnow() - timedelta(hours=i) for i in range(3)]
        result = get_best_send_time(ts)
        assert result["confidence"] == "low"

    def test_sufficient_data_returns_high_confidence(self):
        # 10 messages all at 18:00 on Fridays
        base = datetime(2026, 8, 21, 18, 0, 0)  # A Friday at 18:00
        ts = [base + timedelta(weeks=i) for i in range(10)]
        result = get_best_send_time(ts)
        assert result["confidence"] == "high"
        assert result["best_hour"] == 18
        assert result["best_day"] == "friday"
