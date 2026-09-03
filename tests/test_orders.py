"""
Tests for order extraction, item parsing, synchronization, and cross-sell integration.
"""
import json
import pytest
from datetime import datetime

from api.fetcher import parse_order_items, sync_customer_orders
from db.database import init_db, SessionLocal
from db.queries import (
    get_customer_orders,
    get_customer_purchases,
    get_customer_purchased_products,
    get_customer_by_id,
)
from agent.tools.core_tools import get_customer_profile, get_cross_sell_options


@pytest.fixture(autouse=True)
async def setup_test_db():
    await init_db()


def test_parse_order_items_json_string():
    raw_json = '[{"currency": "INR", "quantity": 12, "item_price": 2980, "product_retailer_id": "FG000046"}, {"currency": "INR", "quantity": 3, "item_price": 3380, "product_retailer_id": "FG000066"}]'
    items = parse_order_items(raw_json)

    assert len(items) == 2
    assert items[0]["product_id"] == "FG000046"
    assert items[0]["quantity"] == 12
    assert items[0]["unit_price"] == 2980.0
    assert items[0]["amount"] == 12 * 2980.0

    assert items[1]["product_id"] == "FG000066"
    assert items[1]["quantity"] == 3
    assert items[1]["unit_price"] == 3380.0
    assert items[1]["amount"] == 3 * 3380.0


def test_parse_order_items_invalid_or_empty():
    assert parse_order_items("") == []
    assert parse_order_items(None) == []
    assert parse_order_items("invalid json") == []
    assert parse_order_items([]) == []


@pytest.mark.asyncio
async def test_sync_customer_orders_with_sample_data():
    customer_id = "919876543210"

    # User's exact 4 sample orders
    sample_orders = [
        {
            "order_id": "1",
            "whatsapp_message_id": "wamid.HBgMOTE5NDg4OTI0NzkzFQIAEhggQTUxMzVFNzM1MjgxMTAxQzYwNEYxOTA3RTFBNDI5MkUA",
            "phone_number": "919876543210",
            "order_items": '[{"currency": "INR", "quantity": 1, "item_price": 3380, "product_retailer_id": "FG000066"}]',
            "party_code": "DR002377",
            "order_confirm": "0",
            "current_state": "ORDER_CONFIRMATION_PENDING",
            "created_at": "2026-07-03 17:14:36",
            "updated_at": "2026-07-03 19:26:12",
        },
        {
            "order_id": "8",
            "whatsapp_message_id": "wamid.HBgMOTE5NDg4OTI0NzkzFQIAEhggQTVBQTJDRUY4NEM0RUMwOUMxNEVGRDhBQTIxRTI1MDQA",
            "phone_number": "919876543210",
            "order_items": '[{"currency": "INR", "quantity": 1, "item_price": 2980, "product_retailer_id": "FG000046"}]',
            "party_code": "DR002377",
            "order_confirm": "1",
            "current_state": "Failed",
            "created_at": "2026-07-03 20:13:18",
            "updated_at": "2026-07-03 20:13:52",
        },
        {
            "order_id": "12",
            "whatsapp_message_id": "wamid.HBgMOTE5NDg4OTI0NzkzFQIAEhgWM0VCMDU4Qzc0Qjk0MjkwNDQyRDREQwA=",
            "phone_number": "919876543210",
            "order_items": '[{"currency": "INR", "quantity": 12, "item_price": 2980, "product_retailer_id": "FG000046"}, {"currency": "INR", "quantity": 3, "item_price": 3380, "product_retailer_id": "FG000066"}]',
            "party_code": "DR002377",
            "order_confirm": "1",
            "current_state": "Completed",
            "created_at": "2026-07-07 11:25:57",
            "updated_at": "2026-07-07 11:26:40",
        },
        {
            "order_id": "40",
            "whatsapp_message_id": "wamid.HBgMOTE5NDg4OTI0NzkzFQIAEhgWM0VCMEM4N0ZEOTY5MEJEREI0REE2RAA=",
            "phone_number": "919876543210",
            "order_items": '[{"currency": "INR", "quantity": 2, "item_price": 2225, "product_retailer_id": "FG000098"}]',
            "party_code": "DR010039",
            "order_confirm": "1",
            "current_state": "PROFORMA_INVOICE_PENDING",
            "created_at": "2026-07-13 16:41:42",
            "updated_at": "2026-07-13 16:51:46",
        },
    ]

    synced = await sync_customer_orders(customer_id, orders_data=sample_orders)
    assert len(synced) == 4

    async with SessionLocal() as db:
        # Verify orders table
        orders = await get_customer_orders(db, customer_id)
        assert len(orders) == 4
        order_ids = {o.id for o in orders}
        assert order_ids == {"1", "8", "12", "40"}

        # Verify purchases table
        purchases = await get_customer_purchases(db, customer_id)
        # Order 8 (Failed) must NOT have generated purchases
        order_8_purchases = [p for p in purchases if p.order_id == "8"]
        assert len(order_8_purchases) == 0

        # Orders 1, 12, 40 are valid purchases:
        # Order 1: FG000066 (1 item)
        # Order 12: FG000046 and FG000066 (2 items)
        # Order 40: FG000098 (1 item)
        assert len(purchases) == 4

        purchased_pids = await get_customer_purchased_products(db, customer_id)
        assert "FG000066" in purchased_pids
        assert "FG000046" in purchased_pids
        assert "FG000098" in purchased_pids

    # Verify get_customer_profile tool returns accurate purchased_products
    profile = await get_customer_profile(customer_id)
    assert profile["customer_id"] == customer_id
    assert "FG000098" in profile["purchased_products"] or "FG000066" in profile["purchased_products"]
    assert profile["last_purchased_product"] is not None
    assert profile["rfm_frequency"] == 4
    assert profile["rfm_monetary"] > 0

    # Verify get_cross_sell_options recommends complementary products
    cross_sells = await get_cross_sell_options("FG000066")
    assert "suggestions" in cross_sells
    assert len(cross_sells["suggestions"]) > 0
