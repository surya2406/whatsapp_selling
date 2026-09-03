"""
graph/state.py — Shared state for the LangGraph WhatsApp Cross-Sell Pipeline.

All data flows through this single typed dict across all nodes.
thread_id = draft_id (UUID) — one thread per cross-sell draft cycle.
"""
from typing import Optional
from typing_extensions import TypedDict


class AgentState(TypedDict):
    # ── API Input ──────────────────────────────────────────────────────────────
    customer_id: str              # phone number e.g. "919876543210"
    draft_id: str                 # UUID — used as LangGraph thread_id

    # ── After load_customer_data_node ─────────────────────────────────────────
    customer_name: str
    conversation_events: list     # last N normalized messages from local DB
    purchased_products: list      # past product IDs from orders table
    last_purchased_product: Optional[str]

    # ── After parser_node ─────────────────────────────────────────────────────
    parser_output: dict
    customer_intent: str
    purchase_signals: bool
    sentiment: str                # positive | neutral | negative
    mentioned_products: list      # [{product_id, product_name}]
    cross_sell_recommendations: list

    # ── After supervisor_node ─────────────────────────────────────────────────
    agents_to_call: list          # ["cross_sell_agent"] or ["direct_reply"]

    # ── After cross_sell_node or direct_reply_node ────────────────────────────
    agent_output: str

    # ── After message_fill_node ───────────────────────────────────────────────
    generated_message: str

    # ── Draft metadata ────────────────────────────────────────────────────────
    conversation_summary: str
    manual_review_reason: Optional[str]

    # ── Error tracking ────────────────────────────────────────────────────────
    error: Optional[str]
