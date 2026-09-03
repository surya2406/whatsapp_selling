"""
FastAPI Application
Provides health check, manual trigger, and status endpoints.
The primary processing is done by Celery — this is the management API.
"""
import logging
import json
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update, func
from pathlib import Path

from api.dependencies import get_db
from db.database import init_db
from config.settings import settings
from config.logging_config import setup_logging

# Initialise structured logging as the very first thing
setup_logging(level="INFO")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize local SQLite DB on startup."""
    logger.info("======================================================")
    logger.info(" WhatsApp AI Sales Agent — API Starting Up")
    logger.info(" Model: %s @ %s", settings.ollama_model, settings.ollama_api_base)
    logger.info("======================================================")
    await init_db()
    logger.info("Local DB initialized successfully.")
    yield
    from graph.checkpointer import close_checkpointer
    await close_checkpointer()
    logger.info("WhatsApp AI Sales Agent — API Shutting Down.")




app = FastAPI(
    title="WhatsApp AI Sales Agent",
    description=(
        "Multi-agent LangGraph pipeline that reads messages from Meta Engine DB, "
        "analyzes them, and generates personalized sales recommendations."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Mount static folder for Frontend UI
_STATIC_DIR = Path(__file__).parent.parent / "static"
if not _STATIC_DIR.exists():
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ── Frontend Web Dashboard ───────────────────────────────────────────────────

@app.get("/", response_class=FileResponse, tags=["Frontend"])
async def serve_dashboard():
    """Serves the Troudz WhatsApp AI Sales Copilot frontend dashboard."""
    index_file = _STATIC_DIR / "index.html"
    if not index_file.exists():
        return HTMLResponse("<h1>Frontend loading... please refresh in a moment</h1>")
    return FileResponse(str(index_file))


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok", "model": settings.ollama_model}



# ── API 1: Data Ingestion Pipeline ────────────────────────────────────────────
# Fetches from Meta Engine + custom_layer (orders) and stores in local SQLite DB.
# LangGraph is NOT involved here — straight sequential pipeline.

class IngestRequest(BaseModel):
    limit: int = 10


@app.post("/api/ingest", tags=["Pipeline"])
async def ingest_pipeline(req: IngestRequest = IngestRequest()):
    """
    API 1 — Data Ingestion: Pull messages from Meta Engine and orders from custom_layer,
    parse and store in local SQLite DB for cross-sell processing.
    """
    logger.info("[API1] POST /api/ingest limit=%d", req.limit)
    from api.workflow import fetch_analyze_and_create_drafts, create_batch
    batch_id = await create_batch()
    result = await fetch_analyze_and_create_drafts(batch_id=batch_id)
    logger.info("[API1] Ingest done: %s", result)
    return result


# ── API 2: LangGraph Cross-Sell Agent ─────────────────────────────────────────
# Reads data from local DB, runs LangGraph graph, returns draft for HITL review.

_graph_instance = None
_checkpointer_instance = None


async def _get_graph():
    """Lazily build and cache the LangGraph graph + checkpointer."""
    global _graph_instance, _checkpointer_instance
    if _graph_instance is None:
        from graph.graph import build_graph
        from graph.checkpointer import get_checkpointer
        _checkpointer_instance = await get_checkpointer()
        _graph_instance = build_graph(_checkpointer_instance)
        logger.info("[API2] LangGraph graph initialised")
    return _graph_instance


@app.post("/api/run-cross-sell/{customer_id}", tags=["Pipeline"])
async def run_cross_sell(customer_id: str):
    """
    API 2 — LangGraph Cross-Sell: Reads customer data from local DB, runs the
    LangGraph multi-agent graph, generates a draft, and pauses for HITL review.
    Returns draft_id to use with the HITL resume endpoints.
    """
    import uuid
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    logger.info("[API2] POST /api/run-cross-sell customer_id=%s thread_id=%s", customer_id, thread_id)

    graph = await _get_graph()
    initial_state = {
        "customer_id": customer_id,
        "draft_id": thread_id,
    }

    try:
        # Graph runs until interrupt() in save_draft_node
        await graph.ainvoke(initial_state, config=config)
        logger.info("[API2] Graph paused at HITL interrupt thread_id=%s", thread_id)
        
        # Read the paused state to retrieve interrupt payload
        state = await graph.aget_state(config)
        interrupt_info = {}
        if state.tasks and state.tasks[0].interrupts:
            interrupt_info = state.tasks[0].interrupts[0].value

        return {
            "status": "pending_review",
            "thread_id": thread_id,
            "draft_id": interrupt_info.get("draft_id"),
            "customer_id": customer_id,
            "preview": interrupt_info.get("preview"),
            "sentiment": interrupt_info.get("sentiment"),
            "manual_review_reason": interrupt_info.get("manual_review_reason"),
        }
    except Exception as exc:
        logger.error("[API2] Graph failed customer_id=%s error=%s", customer_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/drafts/{draft_id}/approve", tags=["HITL"])
async def lg_approve_draft(draft_id: str, db: AsyncSession = Depends(get_db)):
    """
    HITL: Approve the draft. Resumes LangGraph thread and sends WhatsApp message,
    or approves existing DB draft and sends.
    """
    from langgraph.types import Command
    from api.sender import send_whatsapp_message
    from db.models import ReviewDraft

    logger.info("[HITL] Approve draft_id=%s", draft_id)
    config = {"configurable": {"thread_id": draft_id}}
    graph = await _get_graph()

    # Try LangGraph thread resume first
    try:
        await graph.ainvoke(Command(resume={"action": "approve"}), config=config)
        return {"status": "approved_and_sent", "draft_id": draft_id}
    except Exception as exc:
        logger.debug("[HITL] LangGraph thread resume skipped (%s), checking DB draft", exc)

    # Fallback to DB ReviewDraft update
    try:
        int_id = int(draft_id)
        draft = await db.get(ReviewDraft, int_id)
        if draft and draft.status in {"pending_review", "send_failed"}:
            draft.status = "approved"
            msg = draft.final_message or draft.generated_message
            outbound_id = await send_whatsapp_message(draft.customer_id, msg)
            draft.status = "sent"
            draft.meta_outbound_message_id = outbound_id
            draft.sent_at = datetime.utcnow()
            await db.commit()
            return {"status": "approved_and_sent", "draft_id": int_id, "meta_message_id": outbound_id}
    except Exception as db_exc:
        logger.error("[HITL] DB approve fallback failed: %s", db_exc)

    return {"status": "approved", "draft_id": draft_id}


@app.post("/api/drafts/{draft_id}/reject", tags=["HITL"])
async def lg_reject_draft(draft_id: str, db: AsyncSession = Depends(get_db)):
    """
    HITL: Reject the draft. Graph ends without sending.
    """
    from langgraph.types import Command
    from db.models import ReviewDraft

    logger.info("[HITL] Reject draft_id=%s", draft_id)
    config = {"configurable": {"thread_id": draft_id}}
    graph = await _get_graph()
    try:
        await graph.ainvoke(Command(resume={"action": "reject"}), config=config)
        return {"status": "rejected", "draft_id": draft_id}
    except Exception as exc:
        logger.debug("[HITL] LangGraph thread reject skipped (%s), updating DB draft", exc)

    try:
        int_id = int(draft_id)
        draft = await db.get(ReviewDraft, int_id)
        if draft:
            draft.status = "rejected"
            await db.commit()
            return {"status": "rejected", "draft_id": int_id}
    except Exception as db_exc:
        logger.error("[HITL] DB reject fallback failed: %s", db_exc)

    return {"status": "rejected", "draft_id": draft_id}


class EditRequest(BaseModel):
    edited_message: str = Field(min_length=1)


@app.put("/api/drafts/{draft_id}/edit", tags=["HITL"])
async def lg_edit_draft(draft_id: str, req: EditRequest, db: AsyncSession = Depends(get_db)):
    """
    HITL: Edit the draft message, then approve and send.
    """
    from langgraph.types import Command
    from api.sender import send_whatsapp_message
    from db.models import ReviewDraft

    logger.info("[HITL] Edit draft_id=%s msg_len=%d", draft_id, len(req.edited_message))
    config = {"configurable": {"thread_id": draft_id}}
    graph = await _get_graph()
    try:
        await graph.ainvoke(
            Command(resume={"action": "edit", "edited_message": req.edited_message}),
            config=config
        )
        return {"status": "edited_and_sent", "draft_id": draft_id}
    except Exception as exc:
        logger.debug("[HITL] LangGraph thread edit skipped (%s), updating DB draft", exc)

    try:
        int_id = int(draft_id)
        draft = await db.get(ReviewDraft, int_id)
        if draft:
            draft.generated_message = req.edited_message
            draft.final_message = req.edited_message
            draft.status = "approved"
            outbound_id = await send_whatsapp_message(draft.customer_id, req.edited_message)
            draft.status = "sent"
            draft.meta_outbound_message_id = outbound_id
            draft.sent_at = datetime.utcnow()
            await db.commit()
            return {"status": "edited_and_sent", "draft_id": int_id, "meta_message_id": outbound_id}
    except Exception as db_exc:
        logger.error("[HITL] DB edit fallback failed: %s", db_exc)

    return {"status": "edited_and_sent", "draft_id": draft_id}


# ── Dashboard Helper Endpoints ───────────────────────────────────────────────

@app.get("/api/dashboard/stats", tags=["Dashboard"])
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)):
    """Summary stats for the frontend dashboard."""
    from db.models import Customer, Order, Purchase, ReviewDraft, ConversationMessage

    c_count = (await db.execute(select(func.count()).select_from(Customer))).scalar() or 0
    o_count = (await db.execute(select(func.count()).select_from(Order))).scalar() or 0
    p_count = (await db.execute(select(func.count()).select_from(Purchase))).scalar() or 0
    m_count = (await db.execute(select(func.count()).select_from(ConversationMessage))).scalar() or 0

    drafts_pending = (await db.execute(select(func.count()).select_from(ReviewDraft).filter(ReviewDraft.status == "pending_review"))).scalar() or 0
    drafts_approved = (await db.execute(select(func.count()).select_from(ReviewDraft).filter(ReviewDraft.status.in_(["approved", "sent"])))).scalar() or 0
    drafts_rejected = (await db.execute(select(func.count()).select_from(ReviewDraft).filter(ReviewDraft.status == "rejected"))).scalar() or 0
    drafts_total = (await db.execute(select(func.count()).select_from(ReviewDraft))).scalar() or 0



    return {
        "customers_total": c_count,
        "orders_total": o_count,
        "purchases_total": p_count,
        "messages_total": m_count,
        "drafts_pending": drafts_pending,
        "drafts_approved": drafts_approved,
        "drafts_rejected": drafts_rejected,
        "drafts_total": drafts_total,
        "engine_status": "active",
        "model": settings.ollama_model,
    }


@app.get("/api/dashboard/customers", tags=["Dashboard"])
async def get_dashboard_customers(db: AsyncSession = Depends(get_db)):
    """List of all customers with profile summary for the explorer."""
    from db.models import Customer

    result = await db.execute(select(Customer).order_by(Customer.updated_at.desc(), Customer.id))
    customers = result.scalars().all()
    return [
        {
            "id": c.id,
            "phone": c.phone,
            "name": c.name or "Unknown Customer",
            "segment": c.segment or "new",
            "rfm_recency": c.rfm_recency or 0,
            "rfm_frequency": c.rfm_frequency or 0,
            "rfm_monetary": c.rfm_monetary or 0.0,
            "churn_risk": c.churn_risk or "low",
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in customers
    ]


@app.get("/api/dashboard/customer/{customer_id}", tags=["Dashboard"])
async def get_dashboard_customer_detail(customer_id: str, db: AsyncSession = Depends(get_db)):
    """Deep-dive data for a specific customer: profile, orders, and messages."""
    from db.models import Customer, Order, Purchase, ConversationMessage

    cust = await db.get(Customer, customer_id)
    if not cust:
        raise HTTPException(status_code=404, detail="Customer not found")

    orders_res = await db.execute(select(Order).filter(Order.customer_id == customer_id).order_by(Order.created_at.desc()))
    orders = orders_res.scalars().all()

    purchases_res = await db.execute(select(Purchase).filter(Purchase.customer_id == customer_id).order_by(Purchase.purchased_at.desc()))
    purchases = purchases_res.scalars().all()

    messages_res = await db.execute(
        select(ConversationMessage)
        .filter(ConversationMessage.customer_id == customer_id)
        .order_by(ConversationMessage.id.desc())
        .limit(30)
    )
    messages = list(reversed(messages_res.scalars().all()))

    return {
        "customer": {
            "id": cust.id,
            "phone": cust.phone,
            "name": cust.name or "Unknown Customer",
            "segment": cust.segment or "new",
            "rfm_recency": cust.rfm_recency or 0,
            "rfm_frequency": cust.rfm_frequency or 0,
            "rfm_monetary": cust.rfm_monetary or 0.0,
            "churn_risk": cust.churn_risk or "low",
        },
        "orders": [
            {
                "id": o.id,
                "current_state": o.current_state,
                "total_amount": o.total_amount,
                "raw_order_items": json.loads(o.raw_order_items) if o.raw_order_items else [],
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in orders
        ],
        "purchases": [
            {
                "product_id": p.product_id,
                "amount": p.amount,
                "purchased_at": p.purchased_at.isoformat() if p.purchased_at else None,
            }
            for p in purchases
        ],
        "messages": [
            {
                "id": m.id,
                "text": m.parsed_text,
                "created_at": m.source_timestamp,
            }
            for m in messages
        ],
    }


@app.get("/api/dashboard/orders", tags=["Dashboard"])
async def get_dashboard_orders(db: AsyncSession = Depends(get_db)):
    """List all synced orders from the local database."""
    from db.models import Order
    res = await db.execute(select(Order).order_by(Order.created_at.desc()).limit(100))
    orders = res.scalars().all()
    return [
        {
            "id": o.id,
            "order_id": o.id,
            "customer_id": o.customer_id,
            "phone_number": o.phone_number,
            "current_state": o.current_state,
            "total_amount": o.total_amount,
            "raw_order_items": json.loads(o.raw_order_items) if o.raw_order_items else [],
            "created_at": o.created_at.isoformat() if o.created_at else None,
        }
        for o in orders
    ]





@app.post("/trigger/fetch", tags=["Manual"])
async def trigger_fetch():
    """
    Manually trigger the Meta Engine DB fetch and enqueue tasks.
    Useful for testing without waiting for Celery beat.
    """
    from api.tasks import fetch_and_process
    from api.workflow import create_batch

    batch_id = await create_batch()
    result = fetch_and_process.delay(batch_id)
    return {"status": "processing", "batch_id": batch_id, "task_id": str(result.id)}


class ProcessRequest(BaseModel):
    customer_id: str
    customer_name: str = ""
    messages: list[str]


@app.post("/trigger/process", tags=["Manual"])
def trigger_process(req: ProcessRequest):
    """
    Manually trigger agent processing for a specific customer with provided messages.
    Useful for testing the full pipeline.
    """
    from api.tasks import process_message
    result = process_message.delay(
        customer_id=req.customer_id,
        customer_name=req.customer_name,
        meta_message_ids=["manual"],
        raw_messages=req.messages,
    )
    return {"status": "triggered", "task_id": str(result.id)}


@app.get("/task/{task_id}", tags=["Manual"])
async def get_task_status(task_id: str):
    """Check the status of a Celery task."""
    from api.tasks import celery_app
    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": result.result if result.ready() else None,
    }


# ── Manual review draft ───────────────────────────────────────────────────────

@app.post("/api/chat", tags=["Agent"])
async def direct_chat(req: ProcessRequest):
    """
    Compatibility endpoint: generate a draft, but never send it automatically.
    """
    from api.workflow import create_manual_draft

    result = await create_manual_draft(
        customer_id=req.customer_id,
        customer_name=req.customer_name,
        raw_messages=req.messages,
    )
    return result


# ── Batch and human review workflow ──────────────────────────────────────────

class DraftEditRequest(BaseModel):
    message: str = Field(min_length=1)
    reviewed_by: str = Field(min_length=1, max_length=200)


class DraftActionRequest(BaseModel):
    reviewed_by: str = Field(min_length=1, max_length=200)


def _draft_response(draft):
    return {
        "id": draft.id,
        "batch_id": draft.batch_id,
        "customer_id": draft.customer_id,
        "source_message_ids": json.loads(draft.source_message_ids),
        "conversation_summary": draft.conversation_summary,
        "analysis": json.loads(draft.analysis) if draft.analysis else {},
        "sentiment": draft.sentiment,
        "generated_message": draft.generated_message,
        "final_message": draft.final_message,
        "status": draft.status,
        "manual_review_reason": draft.manual_review_reason,
        "reviewed_by": draft.reviewed_by,
        "meta_message_id": draft.meta_outbound_message_id,
        "send_error": draft.send_error,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
        "sent_at": draft.sent_at.isoformat() if draft.sent_at else None,
    }


@app.get("/batches/{batch_id}", tags=["Review"])
async def get_batch(batch_id: str, db: AsyncSession = Depends(get_db)):
    from db.models import ProcessingBatch

    batch = await db.get(ProcessingBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {
        "batch_id": batch.id,
        "status": batch.status,
        "customers_processed": batch.customers_processed,
        "drafts_created": batch.drafts_created,
        "manual_review_required": batch.manual_review_required,
        "skipped": batch.skipped,
        "error": batch.error,
    }


@app.get("/review/drafts", tags=["Review"])
async def list_review_drafts(
    status: str = "pending_review",
    batch_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    from db.models import ReviewDraft

    query = select(ReviewDraft).order_by(ReviewDraft.created_at.desc()).limit(100)
    if status:

        query = query.filter(ReviewDraft.status == status)
    if batch_id:
        query = query.filter(ReviewDraft.batch_id == batch_id)
    result = await db.execute(query)
    return [_draft_response(draft) for draft in result.scalars().all()]



@app.get("/review/drafts/{draft_id}", tags=["Review"])
async def get_review_draft(draft_id: int, db: AsyncSession = Depends(get_db)):
    from db.models import ReviewDraft

    draft = await db.get(ReviewDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _draft_response(draft)


@app.delete("/review/drafts/mock", tags=["Review"])
async def delete_mock_drafts(db: AsyncSession = Depends(get_db)):
    """Delete legacy mock/test drafts from SQLite DB."""
    from db.models import ReviewDraft
    from sqlalchemy import delete
    stmt = delete(ReviewDraft).where(ReviewDraft.id < 37)
    res = await db.execute(stmt)
    await db.commit()
    logger.info("[Review] Deleted %d legacy mock drafts", res.rowcount)
    return {"deleted": res.rowcount}


@app.delete("/review/drafts/all", tags=["Review"])
async def delete_all_drafts(db: AsyncSession = Depends(get_db)):
    """Delete all drafts for a fresh start."""
    from db.models import ReviewDraft
    from sqlalchemy import delete
    stmt = delete(ReviewDraft)
    res = await db.execute(stmt)
    await db.commit()
    logger.info("[Review] Cleared all %d drafts", res.rowcount)
    return {"deleted": res.rowcount}



@app.get("/conversations/{customer_id}", tags=["Review"])
async def get_conversation_history(
    customer_id: str, limit: int = 50, db: AsyncSession = Depends(get_db)
):
    from db.models import ConversationMessage

    limit = min(max(limit, 1), 200)
    result = await db.execute(
        select(ConversationMessage)
        .filter(ConversationMessage.customer_id == customer_id)
        .order_by(ConversationMessage.id.desc())
        .limit(limit)
    )
    messages = list(reversed(result.scalars().all()))
    return [
        {
            "meta_message_id": message.meta_message_id,
            "raw_content": message.raw_content,
            "parsed_text": message.parsed_text,
            "parsed_data": json.loads(message.parsed_data) if message.parsed_data else {},
            "source_timestamp": message.source_timestamp,
        }
        for message in messages
    ]


@app.patch("/review/drafts/{draft_id}", tags=["Review"])
async def edit_review_draft(
    draft_id: int, req: DraftEditRequest, db: AsyncSession = Depends(get_db)
):
    from db.models import ReviewDraft

    draft = await db.get(ReviewDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status not in {"pending_review", "send_failed"}:
        raise HTTPException(status_code=409, detail=f"Cannot edit a {draft.status} draft")
    draft.final_message = req.message
    draft.reviewed_by = req.reviewed_by
    draft.reviewed_at = datetime.utcnow()
    draft.status = "pending_review"
    draft.send_error = None
    await db.commit()
    await db.refresh(draft)
    return _draft_response(draft)


@app.post("/review/drafts/{draft_id}/reject", tags=["Review"])
async def reject_review_draft(
    draft_id: int, req: DraftActionRequest, db: AsyncSession = Depends(get_db)
):
    from db.models import ReviewDraft

    draft = await db.get(ReviewDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status != "pending_review":
        raise HTTPException(status_code=409, detail=f"Cannot reject a {draft.status} draft")
    draft.status = "rejected"
    draft.reviewed_by = req.reviewed_by
    draft.reviewed_at = datetime.utcnow()
    await db.commit()
    return _draft_response(draft)


@app.post("/review/drafts/{draft_id}/approve", tags=["Review"])
async def approve_review_draft(
    draft_id: int, req: DraftActionRequest, db: AsyncSession = Depends(get_db)
):
    from api.sender import send_whatsapp_message
    from db.models import ReviewDraft

    draft = await db.get(ReviewDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.status not in {"pending_review", "send_failed"}:
        raise HTTPException(status_code=409, detail=f"Cannot approve a {draft.status} draft")

    final_message = draft.final_message or draft.generated_message
    claim = await db.execute(
        update(ReviewDraft)
        .where(
            ReviewDraft.id == draft_id,
            ReviewDraft.status.in_({"pending_review", "send_failed"}),
        )
        .values(
            status="sending",
            final_message=final_message,
            reviewed_by=req.reviewed_by,
            reviewed_at=datetime.utcnow(),
            send_error=None,
        )
    )
    if claim.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Draft is already being processed")
    await db.commit()
    await db.refresh(draft)

    try:
        outbound_id = await send_whatsapp_message(draft.customer_id, final_message)
    except Exception as exc:
        draft.status = "send_failed"
        draft.send_error = str(exc)
        await db.commit()
        raise HTTPException(status_code=502, detail=f"Meta send failed: {exc}") from exc

    draft.status = "sent"
    draft.meta_outbound_message_id = outbound_id
    draft.sent_at = datetime.utcnow()
    await db.commit()
    await db.refresh(draft)
    return _draft_response(draft)


# ── Customer responses ────────────────────────────────────────────────────────

@app.get("/responses/{customer_id}", tags=["Data"])
async def get_customer_responses(customer_id: str, db: AsyncSession = Depends(get_db)):
    """Get all generated agent responses for a customer."""
    from db.models import AgentResponse
    result = await db.execute(
        select(AgentResponse)
        .filter(AgentResponse.customer_id == customer_id)
        .order_by(AgentResponse.created_at.desc())
        .limit(20)
    )
    responses = result.scalars().all()
    return [
        {
            "id": r.id,
            "meta_message_id": r.meta_message_id,
            "generated_response": r.generated_response,
            "agents_called": r.agents_called,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in responses
    ]


@app.get("/recommendations/{customer_id}", tags=["Data"])
async def get_customer_recommendations(customer_id: str, db: AsyncSession = Depends(get_db)):
    """Get all recommendations sent to a customer."""
    from db.models import Recommendation
    result = await db.execute(
        select(Recommendation)
        .filter(Recommendation.customer_id == customer_id)
        .order_by(Recommendation.sent_at.desc())
        .limit(20)
    )
    recs = result.scalars().all()
    return [
        {
            "id": r.id,
            "recommended_products": r.recommended_products,
            "offer_id": r.offer_id,
            "template_used": r.template_used,
            "converted": r.converted,
            "sent_at": r.sent_at.isoformat() if r.sent_at else None,
        }
        for r in recs
    ]
