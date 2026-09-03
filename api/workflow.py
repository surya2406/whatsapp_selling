"""Conversation ingestion, analysis, and review-draft creation workflow."""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

# Electrode type codes customers commonly mention in messages
_ELECTRODE_TYPES = [
    "6013", "7018", "7016", "6011", "6010",
    "308L", "309L", "316L", "312", "310", "347",
    "E308", "E309", "E316",
]
_ELECTRODE_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(e) for e in _ELECTRODE_TYPES) + r')\b',
    re.IGNORECASE,
)
_DIAMETER_PATTERN = re.compile(
    r'\b(1\.6|2|2\.5|3|3\.15|4|5)(?:\s*mm)?\b'
)

logger = logging.getLogger(__name__)

from agent.agent import run_agent
from api.conversation_parser import parse_conversation, _extract_json_object
from api.message_filler import fill_message_template

from api.fetcher import (
    fetch_customer_history_records,
    fetch_unprocessed_messages,
    group_messages_by_customer,
    mark_messages_processed,
    sync_customer_orders,
)
from config.settings import settings
from db.database import SessionLocal
from db.models import ConversationMessage, ProcessingBatch, ReviewDraft
from db.queries import get_customer_conversation, get_message_by_meta_id, upsert_customer
from skills.cross_sell_agent.scripts.cross_sell_helper import get_cross_sell_suggestions
from skills.parser.scripts.sentiment import classify_sentiment

_PRODUCTS_PATH = Path(__file__).parent.parent / "lookups" / "products.json"


def _find_mentioned_products(messages: list[str]) -> list[dict]:
    """Match products from customer messages using electrode type codes and exact name/id.

    Customers rarely type full product names (e.g. '6013-SB-12-WOT'). They say
    '6013 3mm' or '6013 rod'. This function extracts electrode type codes and
    diameters from the message and matches them against product name fields.
    Falls back to exact ID/name substring match as well.
    """
    with open(_PRODUCTS_PATH, encoding="utf-8") as product_file:
        products = json.load(product_file)

    combined = " ".join(messages).lower()

    # Extract electrode types and diameters mentioned by the customer
    mentioned_types = [t.upper() for t in _ELECTRODE_PATTERN.findall(combined)]
    mentioned_diameters = _DIAMETER_PATTERN.findall(combined)

    mentioned = []
    seen_ids = set()

    for product_id, product in products.items():
        if product_id in seen_ids:
            continue
        product_name = str(product.get("name", ""))
        product_name_upper = product_name.upper()

        matched = False

        # 1. Exact ID or full name substring match (original logic)
        if product_id.lower() in combined or (product_name and product_name.lower() in combined):
            matched = True

        # 2. Electrode type code match (e.g. customer says "6013", product name contains "6013")
        if not matched:
            for etype in mentioned_types:
                if etype in product_name_upper:
                    # If customer also specified a diameter, narrow the match
                    if mentioned_diameters:
                        for diam in mentioned_diameters:
                            # Normalise: "3" and "3.15" both mean 3.15mm in welding
                            diam_variants = [diam, diam.replace(".", "")]
                            if diam == "3":
                                diam_variants += ["3.15", "315"]
                            if any(v in product_name_upper or v in product_name for v in diam_variants):
                                matched = True
                                break
                    else:
                        # No diameter specified — match any size for that electrode type
                        matched = True
                if matched:
                    break

        if matched:
            mentioned.append({"product_id": product_id, "product_name": product_name})
            seen_ids.add(product_id)

    return mentioned


async def analyze_conversation(events: list[dict], customer_id: str | None = None) -> dict:
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

    # If no product was mentioned in conversation, check customer's past purchases
    if not mentioned and customer_id:
        try:
            async with SessionLocal() as db:
                from db.queries import get_customer_purchases
                past_purchases = await get_customer_purchases(db, customer_id)
                for p in past_purchases[:2]:
                    pid = p.product_id
                    pname = products.get(pid, {}).get("name", pid)
                    mentioned.append({"product_id": pid, "product_name": pname, "source": "past_purchase"})
        except Exception as exc:
            logger.warning(f"Could not load past purchases for {customer_id}: {exc}")

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

    # Sync customer order history from custom_layer if available
    try:
        await sync_customer_orders(customer_id)
    except Exception as exc:
        logger.warning(f"Failed to sync orders for {customer_id}: {exc}")

    analysis = await analyze_conversation(events, customer_id=customer_id)
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

    # 2. Supervisor Routing
    agents_to_call = await route_conversation(customer_id, analysis)
    
    generated_message = ""
    summary = analysis.get("raw_summary") or analysis["latest_message"]
    
    if "direct_reply" in agents_to_call and "cross_sell_agent" not in agents_to_call:
        # 3a. Direct Reply fallback
        customer_name = ""  # Could fetch from DB if needed
        generated_message = await generate_direct_reply(customer_name, summary)
    else:
        # 3b. Run Cross-Sell Agent
        result = await run_agent(
            customer_id=customer_id,
            customer_name="",
            raw_messages=texts,
        )
        if result.get("error") or not result.get("generated_message"):
            raise RuntimeError(result.get("error") or "Agent returned an empty draft")
        
        # 4. Message Fill
        agent_json = _extract_json_object(result["generated_message"])
        candidate_body = ""
        if agent_json:
            msg_t = agent_json.get("message_template", {})
            if isinstance(msg_t, dict) and msg_t.get("body"):
                candidate_body = msg_t["body"]
            elif agent_json.get("message"):
                candidate_body = str(agent_json["message"])

        if candidate_body:
            generated_message = candidate_body
        elif not agent_json or "template_key" not in agent_json:
            logger.warning(f"Agent did not return valid JSON or template. Raw output: {result['generated_message']}")
            generated_message = candidate_body

        else:
            template_key = agent_json["template_key"]
            template_data = agent_json.get("template_data", {})
            # Fetch actual template string using core tool or direct load. 
            # For simplicity, we assume agent or core tools loaded it, but we need the actual template string.
            from agent.tools.core_tools import get_message_template
            try:
                template_str = await get_message_template(template_key)
                generated_message = await fill_message_template(template_str, template_data)
            except Exception as e:
                logger.error(f"Failed to fill message template: {e}")
                generated_message = result["generated_message"]

    # Guarantee non-empty authentic B2B WhatsApp sales copy
    if not generated_message or not generated_message.strip():
        recs = analysis.get("cross_sell_recommendations", [])
        rec_name = recs[0].get("product_name", "Abrasive Cut-Off Wheels") if recs else "Abrasive Cut-Off Wheels"
        rec_id = recs[0].get("product_id", "") if recs else ""
        prod_label = f"{rec_name} ({rec_id})" if rec_id else rec_name
        generated_message = (
            f"Hello, thank you for your recent order with Troudz Industrial Supplies. "
            f"Based on your welding requirements, we have ready stock of high-performance {prod_label} "
            f"for metal fabrication and cutting operations. "
            f"Please let us know if you would like us to include this in your next supply delivery with volume pricing."
        )


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
            generated_message=generated_message,
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
