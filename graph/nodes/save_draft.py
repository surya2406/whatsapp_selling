"""graph/nodes/save_draft.py — Node 7: Save ReviewDraft to DB + native LangGraph interrupt() for HITL."""
import json
import logging
from graph.state import AgentState
from langgraph.types import interrupt
from db.database import SessionLocal
from db.models import ReviewDraft

logger = logging.getLogger(__name__)


async def save_draft_node(state: AgentState) -> dict:
    """
    Saves the generated message as a ReviewDraft in the DB with status='pending_review',
    then calls interrupt() to pause the graph and wait for human decision.

    Human can resume with:
      Command(resume={"action": "approve"})
      Command(resume={"action": "reject"})
      Command(resume={"action": "edit", "edited_message": "..."})
    """
    customer_id = state["customer_id"]
    draft_id = state["draft_id"]
    generated_message = state.get("generated_message", "")
    if not generated_message or not generated_message.strip():
        recs = state.get("cross_sell_recommendations") or []
        rec_name = recs[0].get("product_name", "Abrasive Cut-Off Wheels") if recs else "Abrasive Cut-Off Wheels"
        rec_id = recs[0].get("product_id", "") if recs else ""
        prod_label = f"{rec_name} ({rec_id})" if rec_id else rec_name
        generated_message = (
            f"Hello, thank you for your recent order with Troudz Industrial Supplies. "
            f"Based on your welding requirements, we have ready stock of high-performance {prod_label} "
            f"for metal fabrication and cutting operations. "
            f"Please let us know if you would like us to include this in your next supply delivery with volume pricing."
        )
    sentiment = state.get("sentiment", "neutral")


    summary = state.get("conversation_summary", "")
    analysis = {
        "customer_intent": state.get("customer_intent"),
        "purchase_signals": state.get("purchase_signals"),
        "sentiment": state.get("sentiment"),
        "mentioned_products": state.get("mentioned_products"),
        "cross_sell_recommendations": state.get("cross_sell_recommendations"),
        "agents_to_call": state.get("agents_to_call"),
    }

    review_reason = None
    if sentiment == "negative":
        review_reason = "Negative sentiment detected — verify no sales offer is sent."

    logger.info(
        "[save_draft_node] Saving draft draft_id=%s customer_id=%s sentiment=%s message_len=%d",
        draft_id, customer_id, sentiment, len(generated_message)
    )

    batch_id = state.get("batch_id") or "langgraph-cross-sell"

    async with SessionLocal() as db:
        draft = ReviewDraft(
            batch_id=batch_id,
            customer_id=customer_id,
            source_message_ids=json.dumps([]),
            conversation_summary=summary,
            analysis=json.dumps(analysis, ensure_ascii=False),
            sentiment=sentiment,
            generated_message=generated_message,
            status="pending_review",
            manual_review_reason=review_reason,
        )
        db.add(draft)
        await db.commit()
        await db.refresh(draft)
        real_draft_id = draft.id

    logger.info("[save_draft_node] Draft saved id=%d. Calling interrupt() for HITL thread_id=%s", real_draft_id, draft_id)

    # ── NATIVE LANGGRAPH HITL: graph pauses here ──────────────────────────────
    human_decision = interrupt({
        "draft_id": real_draft_id,
        "thread_id": draft_id,
        "customer_id": customer_id,
        "preview": generated_message,
        "sentiment": sentiment,
        "manual_review_reason": review_reason,
    })
    # ── Graph resumes here after Command(resume=...) is received ──────────────

    action = human_decision.get("action", "approve")
    logger.info("[save_draft_node] RESUMED draft_id=%d action=%s", real_draft_id, action)

    async with SessionLocal() as db:
        draft = await db.get(ReviewDraft, real_draft_id)
        if not draft:
            logger.error("[save_draft_node] Draft not found after resume id=%d", real_draft_id)
            return {"error": f"Draft {real_draft_id} not found"}


        if action == "edit":
            edited = human_decision.get("edited_message", generated_message)
            draft.generated_message = edited
            draft.status = "approved"
            await db.commit()
            logger.info("[save_draft_node] Draft EDITED draft_id=%d", real_draft_id)
            return {"generated_message": edited, "db_draft_id": real_draft_id}

        elif action == "reject":
            draft.status = "rejected"
            await db.commit()
            logger.info("[save_draft_node] Draft REJECTED draft_id=%d", real_draft_id)
            return {"error": "Draft rejected by human reviewer", "db_draft_id": real_draft_id}

        else:  # approve
            draft.status = "approved"
            await db.commit()
            logger.info("[save_draft_node] Draft APPROVED draft_id=%d", real_draft_id)
            return {"db_draft_id": real_draft_id}

