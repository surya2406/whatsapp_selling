from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_analysis_contains_sentiment_product_and_cross_sell():
    from api.workflow import analyze_conversation

    with patch("api.workflow.parse_conversation", new=AsyncMock(return_value={
        "customer_intent": "purchase_signal",
        "mentioned_products": [{"raw_text": "6013-SB-10-WOT", "normalized_product_id": "FG000008"}],
        "purchase_signals": True,
        "sentiment": "positive",
        "raw_summary": "Customer asked to buy 6013-SB-10-WOT",
    })):
        analysis = await analyze_conversation([
            {
                "text": "Thanks, I already bought 6013-SB-10-WOT and it is good",
                "direction": "incoming",
                "message_type": "text",
            }
        ])

    assert analysis["sentiment"] == "positive"
    assert analysis["mentioned_products"][0]["product_id"] == "FG000008"
    assert analysis["cross_sell_recommendations"]
    assert analysis["cross_sell_recommendations"][0]["reason"]


@pytest.mark.asyncio
async def test_sender_posts_reviewed_message_and_returns_id():
    from api.sender import send_whatsapp_message

    response = AsyncMock()
    response.raise_for_status = lambda: None
    response.json = lambda: {"message_id": "wamid.123"}
    client = AsyncMock()
    client.post.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client

    with (
        patch("api.sender.settings.meta_send_api_url", "https://meta.test/send"),
        patch("api.sender.httpx.AsyncClient", return_value=context),
    ):
        message_id = await send_whatsapp_message("+919876543210", "Reviewed text")

    assert message_id == "wamid.123"
    client.post.assert_awaited_once()
    assert client.post.await_args.kwargs["json"] == {
        "customer_id": "+919876543210",
        "message": "Reviewed text",
    }
