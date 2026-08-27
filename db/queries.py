"""
All database query helper functions.
These are pure SQLAlchemy queries — no business logic here.
"""
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from db.models import (
    AgentResponse,
    ConversationMessage,
    Customer,
    ProcessingBatch,
    Purchase,
    Recommendation,
    ReviewDraft,
)


# ─── Customer queries ─────────────────────────────────────────────────────────

async def get_customer_by_id(db: AsyncSession, customer_id: str) -> Optional[Customer]:
    result = await db.execute(select(Customer).filter(Customer.id == customer_id))
    return result.scalars().first()


async def get_customer_by_phone(db: AsyncSession, phone: str) -> Optional[Customer]:
    result = await db.execute(select(Customer).filter(Customer.phone == phone))
    return result.scalars().first()


async def upsert_customer(db: AsyncSession, phone: str, name: str = None) -> Customer:
    """Get existing customer or create a new one."""
    customer = await get_customer_by_phone(db, phone)
    if not customer:
        customer = Customer(id=phone, phone=phone, name=name or "")
        db.add(customer)
        await db.commit()
        await db.refresh(customer)
    return customer


async def update_customer_profile(db: AsyncSession, customer_id: str, **kwargs) -> Customer:
    customer = await get_customer_by_id(db, customer_id)
    if customer:
        for key, value in kwargs.items():
            if hasattr(customer, key):
                setattr(customer, key, value)
        customer.updated_at = datetime.utcnow()
        await db.commit()
        await db.refresh(customer)
    return customer


# ─── Purchase queries ─────────────────────────────────────────────────────────

async def get_customer_purchases(db: AsyncSession, customer_id: str) -> list[Purchase]:
    result = await db.execute(
        select(Purchase)
        .filter(Purchase.customer_id == customer_id)
        .order_by(Purchase.purchased_at.desc())
    )
    return list(result.scalars().all())


async def get_last_purchase(db: AsyncSession, customer_id: str) -> Optional[Purchase]:
    result = await db.execute(
        select(Purchase)
        .filter(Purchase.customer_id == customer_id)
        .order_by(Purchase.purchased_at.desc())
    )
    return result.scalars().first()


async def add_purchase(db: AsyncSession, customer_id: str, product_id: str, amount: float) -> Purchase:
    purchase = Purchase(
        customer_id=customer_id,
        product_id=product_id,
        amount=amount,
        purchased_at=datetime.utcnow(),
    )
    db.add(purchase)
    await db.commit()
    await db.refresh(purchase)
    return purchase


# ─── Agent response queries ───────────────────────────────────────────────────

async def save_agent_response(
    db: AsyncSession,
    customer_id: str,
    meta_message_id: str,
    parsed_intent: str,
    generated_response: str,
    agents_called: str,
) -> AgentResponse:
    response = AgentResponse(
        customer_id=customer_id,
        meta_message_id=meta_message_id,
        parsed_intent=parsed_intent,
        generated_response=generated_response,
        agents_called=agents_called,
    )
    db.add(response)
    await db.commit()
    await db.refresh(response)
    return response


# ─── Recommendation queries ───────────────────────────────────────────────────

async def save_recommendation(
    db: AsyncSession,
    customer_id: str,
    recommended_products: str,
    offer_id: str,
    template_used: str,
    ab_variant: str = None,
) -> Recommendation:
    rec = Recommendation(
        customer_id=customer_id,
        recommended_products=recommended_products,
        offer_id=offer_id,
        template_used=template_used,
        ab_variant=ab_variant,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return rec


async def mark_recommendation_converted(db: AsyncSession, recommendation_id: int) -> Recommendation:
    result = await db.execute(select(Recommendation).filter(Recommendation.id == recommendation_id))
    rec = result.scalars().first()
    if rec:
        rec.converted = True
        rec.conversion_at = datetime.utcnow()
        await db.commit()
        await db.refresh(rec)
    return rec


# ─── Ingestion and human review queries ───────────────────────────────────────

async def get_message_by_meta_id(db: AsyncSession, meta_message_id: str):
    result = await db.execute(
        select(ConversationMessage).filter(
            ConversationMessage.meta_message_id == meta_message_id
        )
    )
    return result.scalars().first()


async def get_customer_conversation(
    db: AsyncSession, customer_id: str, limit: int = 10
) -> list[ConversationMessage]:
    result = await db.execute(
        select(ConversationMessage)
        .filter(ConversationMessage.customer_id == customer_id)
        .order_by(ConversationMessage.id.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))


async def get_review_draft(db: AsyncSession, draft_id: int):
    result = await db.execute(select(ReviewDraft).filter(ReviewDraft.id == draft_id))
    return result.scalars().first()


async def get_processing_batch(db: AsyncSession, batch_id: str):
    result = await db.execute(
        select(ProcessingBatch).filter(ProcessingBatch.id == batch_id)
    )
    return result.scalars().first()


# ─── Dormant customer query ───────────────────────────────────────────────────

async def get_dormant_customers(db: AsyncSession, threshold_days: int) -> list[Customer]:
    """Returns customers who have not purchased in threshold_days days."""
    cutoff = datetime.utcnow() - timedelta(days=threshold_days)
    
    # Simpler approach: get all customers whose last purchase is older than cutoff
    subq = (
        select(Purchase.customer_id)
        .filter(Purchase.purchased_at >= cutoff)
        .distinct()
        .subquery()
    )
    
    result = await db.execute(
        select(Customer)
        .filter(~Customer.id.in_(subq))
        .filter(Customer.rfm_frequency > 0)  # Has at least one purchase
    )
    return list(result.scalars().all())
