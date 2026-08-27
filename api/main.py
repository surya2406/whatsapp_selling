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
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from api.dependencies import get_db
from db.database import init_db
from config.settings import settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize local SQLite DB on startup."""
    logger.info("Starting WhatsApp AI Sales Agent API...")
    await init_db()
    logger.info("Local DB initialized.")
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="WhatsApp AI Sales Agent",
    description=(
        "Multi-agent LangGraph pipeline that reads messages from Meta Engine DB, "
        "analyzes them, and generates personalized sales recommendations."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
def health_check():
    return {"status": "ok", "model": settings.ollama_model}


# ── Manual trigger ────────────────────────────────────────────────────────────

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
