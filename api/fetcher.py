"""
Meta Engine message ingestion and normalization module.
"""
from datetime import datetime
import json
import logging
from typing import Any
from collections import defaultdict
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import text

from config.settings import settings

logger = logging.getLogger(__name__)

_meta_engine: AsyncEngine | None = None
_custom_layer_engine: AsyncEngine | None = None


def get_meta_engine() -> AsyncEngine:
    """Returns singleton async SQLAlchemy engine for Meta Engine MySQL DB."""
    global _meta_engine
    if _meta_engine is None:
        _meta_engine = create_async_engine(
            settings.meta_engine_db_url,
            echo=False,
            pool_recycle=3600,
            pool_pre_ping=True,
        )
    return _meta_engine


def get_custom_layer_engine() -> AsyncEngine:
    """Returns singleton async SQLAlchemy engine for custom_layer MySQL DB (orders table)."""
    global _custom_layer_engine
    if _custom_layer_engine is None:
        db_url = settings.custom_layer_db_url or settings.meta_engine_db_url
        _custom_layer_engine = create_async_engine(
            db_url,
            echo=False,
            pool_recycle=3600,
            pool_pre_ping=True,
        )
    return _custom_layer_engine


def extract_message_content(raw_content: Any, message_type: str = "text") -> str:
    """Extract human-readable text from raw WhatsApp message payloads."""
    if raw_content is None:
        return ""

    if isinstance(raw_content, str):
        raw_str = raw_content.strip()
        if raw_str.startswith("{") and raw_str.endswith("}"):
            try:
                data = json.loads(raw_str)
            except Exception:
                data = raw_str
        else:
            data = raw_str
    else:
        data = raw_content

    if not isinstance(data, dict):
        return str(data)

    mtype = (message_type or "").lower()

    if mtype == "interactive" or "interactive" in data:
        interactive = data.get("interactive", data)
        body = interactive.get("body", {})
        if isinstance(body, dict) and "text" in body:
            return str(body["text"])
        if "button_reply" in interactive:
            return str(interactive["button_reply"].get("title", ""))
        if "list_reply" in interactive:
            return str(interactive["list_reply"].get("title", ""))

    if mtype == "template" or "template_name" in data:
        tname = data.get("template_name", "template")
        params = data.get("parameters", {})
        return f"Template: {tname} (Parameters: {params})"

    if mtype in {"document", "image", "video", "audio"} or "caption" in data:
        if "caption" in data:
            return str(data["caption"])
        if "filename" in data:
            return f"[{mtype.capitalize()}: {data['filename']}]"
        return f"[{mtype.capitalize()} attachment]"

    if "text" in data and isinstance(data["text"], dict):
        return str(data["text"].get("body", ""))

    if "body" in data:
        return str(data["body"])

    return json.dumps(data, ensure_ascii=False)


def group_messages_by_customer(messages: list[dict]) -> dict[str, list[dict]]:
    """Group list of message dicts by customer_id."""
    grouped = defaultdict(list)
    for msg in messages:
        cust_id = msg.get("customer_id")
        if cust_id:
            grouped[cust_id].append(msg)
    return dict(grouped)


async def fetch_unprocessed_messages(limit: int = 50) -> list[dict]:
    """Fetch recent inbound messages from Meta Engine DB.

    NOTE: The meta_engine.message table has no 'is_processed' column.
    We fetch incoming messages ordered by created_at DESC so the latest
    conversations are ingested for cross-sell analysis.
    """
    engine = get_meta_engine()
    direction_col = settings.meta_engine_direction_col  # 'direction'
    query = text(
        f"SELECT id, {settings.meta_engine_sender_col}, {settings.meta_engine_body_col}, "
        f"{settings.meta_engine_timestamp_col}, {settings.meta_engine_recipient_col}, message_type "
        f"FROM {settings.meta_engine_messages_table} "
        f"WHERE {direction_col} = 'incoming' "
        f"ORDER BY {settings.meta_engine_timestamp_col} DESC "
        f"LIMIT :limit"
    )

    try:
        async with engine.connect() as conn:
            result = await conn.execute(query, {"limit": limit})
            rows = result.fetchall()

            messages = []
            for row in rows:
                row_id = str(row[0])
                customer_id = str(row[1])   # sender = customer phone
                raw_body = row[2]
                timestamp = str(row[3]) if row[3] is not None else ""
                recipient = str(row[4]) if row[4] else None
                message_type = str(row[5]) if len(row) > 5 and row[5] else "text"
                parsed_text = extract_message_content(raw_body, message_type)

                messages.append(
                    {
                        "id": row_id,
                        "customer_id": customer_id,
                        "message_text": parsed_text,
                        "raw_content": str(raw_body),
                        "timestamp": timestamp,
                        "job_id": None,
                        "whatsapp_message_id": None,
                        "sender": customer_id,
                        "recipient": recipient,
                        "direction": "incoming",
                        "message_type": message_type,
                        "status": "received",
                    }
                )
            logger.info(
                "[fetch_unprocessed_messages] Fetched %d incoming messages from meta_engine",
                len(messages)
            )
            return messages
    except Exception as exc:
        logger.error("[fetch_unprocessed_messages] Failed: %s", exc)
        return []


async def fetch_customer_history_records(customer_id: str, limit: int = 10) -> list[dict]:
    """Fetch recent message history for a specific customer from Meta Engine DB."""
    engine = get_meta_engine()
    query = text(
        f"SELECT id, {settings.meta_engine_sender_col}, {settings.meta_engine_body_col}, "
        f"{settings.meta_engine_timestamp_col} "
        f"FROM {settings.meta_engine_messages_table} "
        f"WHERE {settings.meta_engine_sender_col} = :customer_id "
        f"   OR {settings.meta_engine_recipient_col} = :customer_id "
        f"ORDER BY {settings.meta_engine_timestamp_col} DESC "
        f"LIMIT :limit"
    )

    try:
        async with engine.connect() as conn:
            result = await conn.execute(query, {"customer_id": customer_id, "limit": limit})
            rows = result.fetchall()

            history = []
            for row in reversed(rows):
                row_id = str(row[0])
                sender = str(row[1])
                raw_body = row[2]
                timestamp = str(row[3]) if len(row) > 3 and row[3] is not None else ""
                parsed_text = extract_message_content(raw_body)

                history.append(
                    {
                        "id": row_id,
                        "customer_id": customer_id,
                        "message_text": parsed_text,
                        "raw_content": str(raw_body),
                        "timestamp": timestamp,
                        "job_id": None,
                        "whatsapp_message_id": None,
                        "sender": sender,
                        "recipient": customer_id if sender != customer_id else None,
                        "direction": "incoming" if sender == customer_id else "outgoing",
                        "message_type": "text",
                        "status": "received",
                    }
                )
            return history
    except Exception as exc:
        logger.error(f"Failed to fetch history for customer {customer_id}: {exc}")
        return []


async def mark_messages_processed(message_ids: list[str]) -> None:
    """Mark messages as processed.

    NOTE: meta_engine.message has no 'is_processed' column so we skip the UPDATE.
    Messages are deduplicated at the local DB level (ConversationMessage.message_id UNIQUE).
    """
    if not message_ids:
        return
    logger.debug(
        "[mark_messages_processed] Skipping UPDATE — meta_engine.message has no is_processed column. "
        "Deduplication is handled by local DB. ids=%d",
        len(message_ids)
    )


# ─── Order ingestion and synchronization ──────────────────────────────────────

def _parse_datetime(val: Any) -> datetime:
    """Safely convert string or datetime into datetime object."""
    if isinstance(val, datetime):
        return val
    if not val:
        return datetime.utcnow()
    val_str = str(val).strip()
    try:
        return datetime.fromisoformat(val_str.replace(" ", "T"))
    except Exception:
        try:
            return datetime.strptime(val_str, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return datetime.utcnow()


def parse_order_items(raw_order_items: Any) -> list[dict]:
    """Parse raw order_items JSON payload into structured product line items."""
    if not raw_order_items:
        return []
    items = raw_order_items
    if isinstance(raw_order_items, str):
        try:
            items = json.loads(raw_order_items)
        except Exception as e:
            logger.warning(f"Failed to parse order_items JSON string: {e}")
            return []
    if not isinstance(items, list):
        if isinstance(items, dict):
            items = [items]
        else:
            return []

    parsed = []
    for it in items:
        if not isinstance(it, dict):
            continue
        pid = str(it.get("product_retailer_id") or it.get("product_id") or "").strip()
        if not pid:
            continue
        try:
            qty = int(it.get("quantity", 1))
        except (ValueError, TypeError):
            qty = 1
        try:
            price = float(it.get("item_price", it.get("price", 0.0)))
        except (ValueError, TypeError):
            price = 0.0
        try:
            amt = float(it.get("amount", qty * price))
        except (ValueError, TypeError):
            amt = qty * price

        parsed.append({
            "product_id": pid,
            "quantity": qty,
            "unit_price": price,
            "amount": amt,
            "currency": it.get("currency", "INR"),
        })
    return parsed


async def fetch_customer_orders(phone_number: str, limit: int = 50) -> list[dict]:
    """Fetch customer orders from custom_layer orders table."""
    engine = get_custom_layer_engine()
    clean_phone = phone_number.replace("+", "").strip()
    phone_with_plus = f"+{clean_phone}"

    query = text(
        f"SELECT order_id, whatsapp_message_id, phone_number, order_items, party_code, "
        f"order_confirm, current_state, created_at, updated_at "
        f"FROM `{settings.orders_table_name}` "
        f"WHERE phone_number = :clean_phone OR phone_number = :phone_with_plus "
        f"ORDER BY created_at DESC "
        f"LIMIT :limit"
    )


    try:
        async with engine.connect() as conn:
            result = await conn.execute(query, {
                "clean_phone": clean_phone,
                "phone_with_plus": phone_with_plus,
                "limit": limit
            })
            rows = result.fetchall()

            orders = []
            for row in rows:
                orders.append({
                    "order_id": str(row[0]),
                    "whatsapp_message_id": str(row[1]) if row[1] else None,
                    "phone_number": str(row[2]),
                    "order_items": row[3],
                    "party_code": str(row[4]) if row[4] else None,
                    "order_confirm": str(row[5]) if row[5] is not None else "0",
                    "current_state": str(row[6]) if row[6] else "UNKNOWN",
                    "created_at": _parse_datetime(row[7]),
                    "updated_at": _parse_datetime(row[8]) if len(row) > 8 and row[8] else None,
                })
            return orders
    except Exception as exc:
        logger.error(f"Failed to fetch orders for customer {phone_number}: {exc}")
        return []


async def sync_customer_orders(customer_id: str, orders_data: list[dict] | None = None) -> list[dict]:
    """
    Sync orders from custom_layer into local DB:
    1. Upsert Customer.
    2. Upsert Order records.
    3. For non-failed confirmed/completed orders, upsert Purchase line items.
    4. Recalculate customer RFM profile and update cache.
    """
    from db.database import SessionLocal
    from db.models import Purchase
    from db.queries import upsert_customer, upsert_order, get_customer_purchases, get_customer_by_id
    from skills.profiler.scripts.rfm import calculate_rfm, assign_segment
    from cache.redis_client import cache_customer_profile
    from sqlalchemy.future import select

    if orders_data is None:
        orders_data = await fetch_customer_orders(customer_id)

    if not orders_data:
        return []

    async with SessionLocal() as db:
        await upsert_customer(db, phone=customer_id)

        synced_orders = []
        for o in orders_data:
            order_id = str(o["order_id"])
            phone = str(o.get("phone_number", customer_id))
            raw_items = o.get("order_items", "[]")
            if isinstance(raw_items, (list, dict)):
                raw_items_str = json.dumps(raw_items)
            else:
                raw_items_str = str(raw_items)

            parsed_items = parse_order_items(raw_items)
            total_amount = sum(item["amount"] for item in parsed_items)
            current_state = str(o.get("current_state", "UNKNOWN"))
            order_confirm = str(o.get("order_confirm", "0"))
            created_at = _parse_datetime(o.get("created_at"))
            updated_at = _parse_datetime(o.get("updated_at")) if o.get("updated_at") else created_at

            await upsert_order(
                db=db,
                order_id=order_id,
                customer_id=customer_id,
                phone_number=phone,
                current_state=current_state,
                total_amount=total_amount,
                raw_order_items=raw_items_str,
                whatsapp_message_id=o.get("whatsapp_message_id"),
                party_code=o.get("party_code"),
                order_confirm=order_confirm,
                created_at=created_at,
                updated_at=updated_at,
            )

            # Exclude explicitly Failed orders from purchases table
            is_failed = current_state.lower() == "failed"
            is_valid_purchase = not is_failed and (
                current_state.lower() == "completed"
                or order_confirm == "1"
                or "pending" in current_state.lower()
            )

            if is_valid_purchase:
                for item in parsed_items:
                    stmt = select(Purchase).filter(
                        Purchase.order_id == order_id,
                        Purchase.product_id == item["product_id"],
                    )
                    existing_purchase = (await db.execute(stmt)).scalars().first()
                    if existing_purchase:
                        existing_purchase.quantity = item["quantity"]
                        existing_purchase.unit_price = item["unit_price"]
                        existing_purchase.amount = item["amount"]
                        existing_purchase.purchased_at = created_at
                    else:
                        db.add(Purchase(
                            order_id=order_id,
                            customer_id=customer_id,
                            product_id=item["product_id"],
                            quantity=item["quantity"],
                            unit_price=item["unit_price"],
                            amount=item["amount"],
                            purchased_at=created_at,
                        ))

            synced_orders.append({
                "order_id": order_id,
                "current_state": current_state,
                "total_amount": total_amount,
                "items_count": len(parsed_items),
                "is_valid_purchase": is_valid_purchase,
            })

        await db.commit()

        # Recalculate customer RFM profile
        purchases_orm = await get_customer_purchases(db, customer_id)
        purchases = [
            {
                "product_id": p.product_id,
                "amount": p.amount,
                "purchased_at": p.purchased_at,
            }
            for p in purchases_orm
        ]
        rfm = calculate_rfm(purchases)
        segment = assign_segment(rfm)

        customer = await get_customer_by_id(db, customer_id)
        if customer:
            customer.segment = segment
            customer.rfm_recency = rfm["recency_days"]
            customer.rfm_frequency = rfm["frequency_count"]
            customer.rfm_monetary = rfm["monetary_total"]
            customer.churn_risk = "high" if rfm["recency_days"] > 120 else ("medium" if rfm["recency_days"] > 90 else "low")
            await db.commit()

            profile = {
                "customer_id": customer_id,
                "name": customer.name or "",
                "segment": segment,
                "rfm_score": rfm["rfm_score"],
                "rfm_recency": rfm["recency_days"],
                "rfm_frequency": rfm["frequency_count"],
                "rfm_monetary": rfm["monetary_total"],
                "last_purchased_product": rfm["last_purchased_product"],
                "purchased_products": list(dict.fromkeys(p["product_id"] for p in purchases if p.get("product_id"))),
                "days_since_last_purchase": rfm["recency_days"],
                "churn_risk": customer.churn_risk,
            }
            cache_customer_profile(customer_id, profile)

    return synced_orders

