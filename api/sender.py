"""Outbound Meta Engine HTTP client used after human approval."""
import httpx

from config.settings import settings


async def send_whatsapp_message(customer_id: str, message: str) -> str:
    if not settings.meta_send_api_url:
        raise RuntimeError("META_SEND_API_URL is not configured")

    headers = {}
    if settings.meta_send_api_token:
        headers["Authorization"] = f"Bearer {settings.meta_send_api_token}"

    async with httpx.AsyncClient(timeout=settings.meta_send_timeout_seconds) as client:
        response = await client.post(
            settings.meta_send_api_url,
            json={"customer_id": customer_id, "message": message},
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()

    message_id = data.get("message_id") or data.get("meta_message_id") or data.get("id")
    if not message_id:
        raise RuntimeError("Meta send API response did not contain a message ID")
    return str(message_id)
