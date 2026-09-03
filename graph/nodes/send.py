"""graph/nodes/send.py — Node 8: Send approved WhatsApp message via Meta API."""
import logging
from graph.state import AgentState
from api.sender import send_whatsapp_message
from db.database import SessionLocal
from db.models import ReviewDraft

logger = logging.getLogger(__name__)


async def send_node(state: AgentState) -> dict:
    """Sends the approved generated_message to the customer via Meta WhatsApp API."""
    customer_id = state["customer_id"]
    draft_id = state["draft_id"]
    message = state.get("generated_message", "")

    if state.get("error"):
        logger.info("[send_node] Skipping send — draft was rejected or errored draft_id=%s", draft_id)
        return {}

    logger.info(
        "[send_node] START customer_id=%s draft_id=%s message_len=%d",
        customer_id, draft_id, len(message)
    )

    if not message:
        logger.warning("[send_node] Empty message — nothing to send for draft_id=%s", draft_id)
        return {"error": "Empty message — send skipped"}

    try:
        await send_whatsapp_message(customer_id=customer_id, message=message)
        logger.info("[send_node] SENT customer_id=%s draft_id=%s", customer_id, draft_id)

        # Mark draft as sent
        db_id = state.get("db_draft_id")
        if db_id:
            async with SessionLocal() as db:
                draft = await db.get(ReviewDraft, db_id)
                if draft:
                    draft.status = "sent"
                    await db.commit()


        return {}

    except Exception as exc:
        logger.error(
            "[send_node] FAILED to send customer_id=%s draft_id=%s error=%s",
            customer_id, draft_id, exc, exc_info=True
        )
        return {"error": str(exc)}
