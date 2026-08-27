"""Conversation ingestion, analysis, and review-draft creation workflow."""
import json
import logging
from datetime import datetime
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

from agent.agent import run_agent
from api.conversation_parser import parse_conversation
from api.fetcher import (
    fetch_customer_history_records,
    fetch_unprocessed_messages,
    group_messages_by_customer,
    mark_messages_processed,
)
from config.settings import settings
from db.database import SessionLocal
from db.models import ConversationMessage, ProcessingBatch, ReviewDraft
from db.queries import get_customer_conversation, get_message_by_meta_id, upsert_customer
from skills.cross_sell_agent.scripts.cross_sell_helper import get_cross_sell_suggestions
from skills.parser.scripts.sentiment import classify_sentiment

_PRODUCTS_PATH = Path(__file__).parent.parent / "lookups" / "products.json"


def _find_mentioned_products(messages: list[str]) -> list[dict]:
    with open(_PRODUCTS_PATH, encoding="utf-8") as product_file:
        products = json.load(product_file)

    combined = " ".join(messages).lower()
    mentioned = []
    for product_id, product in products.items():
        product_name = str(product.get("name", ""))
        if product_id.lower() in combined or (product_name and product_name.lower() in combined):
            mentioned.append({"product_id": product_id, "product_name": product_name})

    return mentioned


async def analyze_conversation(events: list[dict]) -> dict:
    """Run LLM parser skill style extraction, then deterministic recommendation logic."""
    parser_output = await parse_conversation(events)
    messages = [event.get("text", "") for event in events]
    mentioned = _find_mentioned_products(messages)
    parser_mentioned = parser_output.get("mentioned_products", [])
    if isinstance(parser_mentioned, list):
        for item in parser_mentioned:
            if isinstance(item, dict):
                item = item.get("normalized_product_id") or item.get("raw_text") or ""
            if not isinstance(item, str) or not item:
                continue
            for product in mentioned:
                if product["product_name"].lower() == item.lower() or product["product_id"].lower() == item.lower():
                    break
            else:
                mentioned.append({"product_id": item, "product_name": item})

    with open(_PRODUCTS_PATH, encoding="utf-8") as product_file:
        products = json.load(product_file)

    keyword_sentiment = classify_sentiment(messages[-3:])
    sentiment = parser_output.get("sentiment") or keyword_sentiment
    if keyword_sentiment == "negative":
        sentiment = "negative"

    recommendations = []
    for mentioned_product in mentioned:
        match = get_cross_sell_suggestions(
            mentioned_product["product_id"], settings.max_recommendations
        )
        recommendations.extend(
            {
                "source_product_id": mentioned_product["product_id"],
                "product_id": suggested_id,
                "product_name": products.get(suggested_id, {}).get("name", suggested_id),
                "reason": match["reason"],
            }
            for suggested_id in match["suggestions"]
        )
    return {
        "parser": parser_output,
        "customer_intent": parser_output.get("customer_intent", "general"),
        "purchase_signals": bool(parser_output.get("purchase_signals", False)),
        "sentiment": sentiment,
        "mentioned_products": mentioned,
        "cross_sell_recommendations": recommendations,
        "message_count": len(messages),
        "latest_message": messages[-1] if messages else "",
        "raw_summary": parser_output.get("raw_summary", messages[-1] if messages else ""),
    }


async def create_batch() -> str:
    batch_id = str(uuid4())
    async with SessionLocal() as db:
        db.add(ProcessingBatch(id=batch_id, status="processing"))
        await db.commit()
    return batch_id


async def _ingest_records(batch_id: str, records: list[dict]) -> None:
    async with SessionLocal() as db:
        for record in records:
            await upsert_customer(db, phone=record["customer_id"])
            if await get_message_by_meta_id(db, record["id"]):
                continue
            db.add(ConversationMessage(
                meta_message_id=record["id"],
                batch_id=batch_id,
                customer_id=record["customer_id"],
                raw_content=record.get("raw_content", record["message_text"]),
                parsed_text=record["message_text"],
                parsed_data=json.dumps(
                    {
                        "normalized_event": {
                            "meta_message_id": record["id"],
                            "job_id": record.get("job_id"),
                            "whatsapp_message_id": record.get("whatsapp_message_id"),
                            "sender": record.get("sender"),
                            "recipient": record.get("recipient"),
                            "direction": record.get("direction"),
                            "message_type": record.get("message_type"),
                            "status": record.get("status"),
                            "text": record.get("message_text"),
                            "created_at": record.get("timestamp"),
                        }
                    },
                    ensure_ascii=False,
                ),
                source_timestamp=record.get("timestamp"),
            ))
        await db.commit()


async def _create_customer_draft(
    batch_id: str, customer_id: str, source_message_ids: list[str]
) -> ReviewDraft:
    async with SessionLocal() as db:
        local_messages = await get_customer_conversation(
            db, customer_id, settings.max_conversation_history
        )
        events = []
        for message in local_messages:
            normalized = {}
            if message.parsed_data:
                try:
                    normalized = json.loads(message.parsed_data).get("normalized_event", {})
                except Exception:
                    normalized = {}
            events.append(
                {
                    "meta_message_id": message.meta_message_id,
                    "direction": normalized.get("direction", "incoming"),
                    "message_type": normalized.get("message_type", "text"),
                    "status": normalized.get("status", ""),
                    "text": message.parsed_text,
                    "created_at": normalized.get("created_at") or message.source_timestamp,
                }
            )

    analysis = await analyze_conversation(events)
    texts = [event.get("text", "") for event in events]
    source_id_set = set(source_message_ids)
    async with SessionLocal() as db:
        local_messages = await get_customer_conversation(
            db, customer_id, settings.max_conversation_history
        )
        for message in local_messages:
            if message.meta_message_id in source_id_set:
                existing = {}
                if message.parsed_data:
                    try:
                        existing = json.loads(message.parsed_data)
                    except Exception:
                        existing = {}
                existing["parser_output"] = analysis.get("parser", {})
                existing["analysis"] = analysis
                message.parsed_data = json.dumps(existing, ensure_ascii=False)
        await db.commit()

    result = await run_agent(
        customer_id=customer_id,
        customer_name="",
        raw_messages=texts,
    )
    if result.get("error") or not result.get("generated_message"):
        raise RuntimeError(result.get("error") or "Agent returned an empty draft")

    summary = analysis.get("raw_summary") or analysis["latest_message"]
    if len(summary) > 300:
        summary = summary[:297] + "..."
    review_reason = None
    if analysis["sentiment"] == "negative":
        review_reason = "Negative sentiment detected; verify that no sales offer is sent."

    async with SessionLocal() as db:
        draft = ReviewDraft(
            batch_id=batch_id,
            customer_id=customer_id,
            source_message_ids=json.dumps(source_message_ids),
            conversation_summary=summary,
            analysis=json.dumps(analysis),
            sentiment=analysis["sentiment"],
            generated_message=result["generated_message"],
            status="pending_review",
            manual_review_reason=review_reason,
        )
        db.add(draft)
        await db.commit()
        await db.refresh(draft)
        return draft


async def fetch_analyze_and_create_drafts(batch_id: str | None = None) -> dict:
    batch_id = batch_id or await create_batch()
    logger.info(f"Starting batch {batch_id}: Fetching unprocessed messages from Meta Engine...")
    
    messages = await fetch_unprocessed_messages(limit=10)
    if not messages:
        logger.info(f"Batch {batch_id}: No new messages found.")
        async with SessionLocal() as db:
            batch = await db.get(ProcessingBatch, batch_id)
            batch.status = "completed"
            batch.completed_at = datetime.utcnow()
            await db.commit()
        return {"status": "no_messages", "batch_id": batch_id}

    grouped = group_messages_by_customer(messages)
    logger.info(f"Batch {batch_id}: Found {len(messages)} messages from {len(grouped)} customers.")
    
    drafts_created = 0
    manual_review = 0
    errors = []

    for customer_id, new_messages in grouped.items():
        logger.info(f"Batch {batch_id}: Processing customer {customer_id} ({len(new_messages)} new msgs)")
        try:
            history = await fetch_customer_history_records(
                customer_id, settings.max_conversation_history
            )
            records_by_id = {
                record["id"]: record for record in [*history, *new_messages]
            }
            await _ingest_records(batch_id, list(records_by_id.values()))
            source_ids = [message["id"] for message in new_messages]
            draft = await _create_customer_draft(batch_id, customer_id, source_ids)
            drafts_created += 1
            manual_review += int(bool(draft.manual_review_reason))
            await mark_messages_processed(source_ids)
            logger.info(f"Batch {batch_id}: Successfully created draft for {customer_id}")
        except Exception as exc:
            logger.error(f"Batch {batch_id}: Error processing {customer_id} - {exc}")
            errors.append(f"{customer_id}: {exc}")

    async with SessionLocal() as db:
        batch = await db.get(ProcessingBatch, batch_id)
        batch.customers_processed = len(grouped) - len(errors)
        batch.drafts_created = drafts_created
        batch.manual_review_required = manual_review
        batch.skipped = len(errors)
        batch.status = "pending_review" if drafts_created else "failed"
        batch.error = "\n".join(errors) or None
        batch.completed_at = datetime.utcnow()
        await db.commit()

        logger.info(
            f"Batch {batch_id} complete. Processed {batch.customers_processed} customers, "
            f"Created {batch.drafts_created} drafts, {batch.manual_review_required} need manual review, {batch.skipped} skipped."
        )

    return {
        "status": "pending_review" if drafts_created else "failed",
        "batch_id": batch_id,
        "customers_processed": len(grouped) - len(errors),
        "drafts_created": drafts_created,
        "manual_review_required": manual_review,
        "skipped": len(errors),
        "errors": errors,
    }


async def create_manual_draft(
    customer_id: str, customer_name: str, raw_messages: list[str]
) -> dict:
    batch_id = await create_batch()
    records = [
        {
            "id": f"manual-{uuid4()}",
            "customer_id": customer_id,
            "job_id": "manual",
            "whatsapp_message_id": None,
            "sender": customer_id,
            "recipient": customer_id,
            "direction": "incoming",
            "message_type": "text",
            "status": "manual",
            "raw_content": text,
            "message_text": text,
            "timestamp": datetime.utcnow().isoformat(),
        }
        for text in raw_messages
    ]
    await _ingest_records(batch_id, records)

    if customer_name:
        async with SessionLocal() as db:
            customer = await upsert_customer(db, phone=customer_id, name=customer_name)
            if not customer.name:
                customer.name = customer_name
                await db.commit()

    draft = await _create_customer_draft(
        batch_id, customer_id, [record["id"] for record in records]
    )
    async with SessionLocal() as db:
        batch = await db.get(ProcessingBatch, batch_id)
        batch.status = "pending_review"
        batch.customers_processed = 1
        batch.drafts_created = 1
        batch.manual_review_required = int(bool(draft.manual_review_reason))
        batch.completed_at = datetime.utcnow()
        await db.commit()
    return {"status": "pending_review", "batch_id": batch_id, "draft_id": draft.id}
