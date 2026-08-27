"""
Integration tests for the fetcher — mocks the MySQL meta engine DB.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestFetcher:
    def test_extract_message_content_variants(self):
        from api.fetcher import extract_message_content

        interactive_payload = '{"interactive": {"body": {"text": "Confirm order"}}}'
        template_payload = '{"template_name": "payment_confirmation", "parameters": {"1": "ORD-1001"}}'
        document_payload = '{"caption": "Invoice attached"}'

        assert extract_message_content(interactive_payload, "interactive") == "Confirm order"
        assert "payment_confirmation" in extract_message_content(template_payload, "template")
        assert extract_message_content(document_payload, "document") == "Invoice attached"

    def test_group_messages_by_customer(self):
        from api.fetcher import group_messages_by_customer

        messages = [
            {"id": "1", "customer_id": "CUST_A", "message_text": "Hello", "timestamp": "2026-01-01"},
            {"id": "2", "customer_id": "CUST_B", "message_text": "Hi", "timestamp": "2026-01-01"},
            {"id": "3", "customer_id": "CUST_A", "message_text": "Is this available?", "timestamp": "2026-01-01"},
        ]

        grouped = group_messages_by_customer(messages)
        assert "CUST_A" in grouped
        assert "CUST_B" in grouped
        assert len(grouped["CUST_A"]) == 2
        assert len(grouped["CUST_B"]) == 1

    def test_group_empty_messages(self):
        from api.fetcher import group_messages_by_customer

        grouped = group_messages_by_customer([])
        assert grouped == {}

    @pytest.mark.asyncio
    @patch("api.fetcher.get_meta_engine")
    async def test_fetch_unprocessed_messages_queries_db(self, mock_engine):
        """Verifies the fetcher constructs and runs the right query."""
        from api.fetcher import fetch_unprocessed_messages
        from unittest.mock import AsyncMock

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("1", "+919876543210", "Hello", "2026-01-01 10:00:00"),
            ("2", "+919876543211", "Hi", "2026-01-01 10:01:00"),
        ]
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = mock_result
        mock_engine.return_value.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.return_value.connect.return_value.__aexit__ = AsyncMock(return_value=False)

        results = await fetch_unprocessed_messages(limit=10)
        assert len(results) == 2
        assert results[0]["customer_id"] == "+919876543210"
        assert results[0]["message_text"] == "Hello"
