from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
)
from sqlalchemy.orm import relationship
from db.database import Base


class Customer(Base):
    """Represents a customer known to the agent (identified by phone number)."""
    __tablename__ = "customers"

    id = Column(String(50), primary_key=True)      # WhatsApp phone number
    name = Column(String(200), nullable=True)
    phone = Column(String(50), nullable=False, unique=True)
    segment = Column(String(30), default="new")    # new | repeat | high_value | dormant
    rfm_recency = Column(Integer, default=0)       # Days since last purchase
    rfm_frequency = Column(Integer, default=0)     # Total orders
    rfm_monetary = Column(Float, default=0.0)      # Total spend
    churn_risk = Column(String(20), default="low") # low | medium | high
    preferred_language = Column(String(10), default="en")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    agent_responses = relationship("AgentResponse", back_populates="customer")
    recommendations = relationship("Recommendation", back_populates="customer")
    purchases = relationship("Purchase", back_populates="customer")
    orders = relationship("Order", back_populates="customer")
    conversation_messages = relationship("ConversationMessage", back_populates="customer")
    review_drafts = relationship("ReviewDraft", back_populates="customer")


class ProcessingBatch(Base):
    """One scheduled or manually triggered Meta Engine ingestion run."""
    __tablename__ = "processing_batches"

    id = Column(String(36), primary_key=True)
    status = Column(String(30), nullable=False, default="processing")
    customers_processed = Column(Integer, nullable=False, default=0)
    drafts_created = Column(Integer, nullable=False, default=0)
    manual_review_required = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    messages = relationship("ConversationMessage", back_populates="batch")
    drafts = relationship("ReviewDraft", back_populates="batch")


class ConversationMessage(Base):
    """Local, auditable copy of Meta Engine conversation context."""
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meta_message_id = Column(String(100), nullable=False, unique=True, index=True)
    batch_id = Column(String(36), ForeignKey("processing_batches.id"), nullable=True)
    customer_id = Column(String(50), ForeignKey("customers.id"), nullable=False, index=True)
    raw_content = Column(Text, nullable=False)
    parsed_text = Column(Text, nullable=False)
    parsed_data = Column(Text, nullable=True)
    source_timestamp = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    batch = relationship("ProcessingBatch", back_populates="messages")
    customer = relationship("Customer", back_populates="conversation_messages")


class ReviewDraft(Base):
    """Generated message held for human review before WhatsApp delivery."""
    __tablename__ = "review_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(36), ForeignKey("processing_batches.id"), nullable=False, index=True)
    customer_id = Column(String(50), ForeignKey("customers.id"), nullable=False, index=True)
    source_message_ids = Column(Text, nullable=False)
    conversation_summary = Column(Text, nullable=True)
    analysis = Column(Text, nullable=True)
    sentiment = Column(String(20), nullable=False, default="neutral")
    generated_message = Column(Text, nullable=False)
    final_message = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="pending_review", index=True)
    manual_review_reason = Column(Text, nullable=True)
    reviewed_by = Column(String(200), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    meta_outbound_message_id = Column(String(200), nullable=True)
    send_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True)

    batch = relationship("ProcessingBatch", back_populates="drafts")
    customer = relationship("Customer", back_populates="review_drafts")


class AgentResponse(Base):
    """
    Stores the agent's analysis and generated response for each processed message.
    Legacy generated-response log. New reviewed messages are stored in ReviewDraft.
    """
    __tablename__ = "agent_responses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String(50), ForeignKey("customers.id"), nullable=False)
    meta_message_id = Column(String(100), nullable=True)   # Reference to meta engine DB row
    parsed_intent = Column(Text, nullable=True)             # JSON string from parser node
    generated_response = Column(Text, nullable=True)        # Final LLM-generated message
    agents_called = Column(Text, nullable=True)             # JSON list of agent names called
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="agent_responses")


class Recommendation(Base):
    """Tracks which products and offers were recommended to each customer."""
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(String(50), ForeignKey("customers.id"), nullable=False)
    recommended_products = Column(Text, nullable=True)  # JSON array of product IDs
    offer_id = Column(String(50), nullable=True)
    template_used = Column(String(100), nullable=True)
    ab_variant = Column(String(10), nullable=True)      # "A" | "B" | None
    sent_at = Column(DateTime, default=datetime.utcnow)
    converted = Column(Boolean, default=False)
    conversion_at = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="recommendations")


class Order(Base):
    """Auditable local record of customer orders synced from custom_layer/Meta Engine DB."""
    __tablename__ = "orders"

    id = Column(String(50), primary_key=True)  # order_id from orders table
    customer_id = Column(String(50), ForeignKey("customers.id"), nullable=False, index=True)
    phone_number = Column(String(50), nullable=False)
    whatsapp_message_id = Column(String(100), nullable=True)
    party_code = Column(String(50), nullable=True)
    current_state = Column(String(50), nullable=False)  # Completed | ORDER_CONFIRMATION_PENDING | Failed etc.
    order_confirm = Column(String(10), nullable=True, default="0")
    total_amount = Column(Float, nullable=False, default=0.0)
    raw_order_items = Column(Text, nullable=False)  # Raw JSON array of items
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("Customer", back_populates="orders")
    purchases = relationship("Purchase", back_populates="order")


class Purchase(Base):
    """Records of customer purchases (fed from orders table or manual import)."""
    __tablename__ = "purchases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(50), ForeignKey("orders.id"), nullable=True, index=True)
    customer_id = Column(String(50), ForeignKey("customers.id"), nullable=False, index=True)
    product_id = Column(String(50), nullable=False, index=True)
    quantity = Column(Integer, nullable=False, default=1)
    unit_price = Column(Float, nullable=False, default=0.0)
    amount = Column(Float, nullable=False, default=0.0)
    purchased_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="purchases")
    order = relationship("Order", back_populates="purchases")

