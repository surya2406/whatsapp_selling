"""
graph/graph.py — Main LangGraph StateGraph builder.

Builds the full WhatsApp cross-sell pipeline:

  load_customer_data_node
      -> parser_node
      -> supervisor_node
           |-- cross_sell_agent -> message_fill_node -> save_draft_node [interrupt] -> send_node
           '-- direct_reply    ----------------------> save_draft_node [interrupt] -> send_node

thread_id = draft_id (UUID per cross-sell cycle) — enables isolated HITL resume.
"""
import logging
from langgraph.graph import StateGraph, START, END
from graph.state import AgentState
from graph.nodes.load_customer_data import load_customer_data_node
from graph.nodes.parser import parser_node
from graph.nodes.supervisor import supervisor_node
from graph.nodes.cross_sell import cross_sell_node
from graph.nodes.direct_reply import direct_reply_node
from graph.nodes.message_fill import message_fill_node
from graph.nodes.save_draft import save_draft_node
from graph.nodes.send import send_node

logger = logging.getLogger(__name__)


def _route_after_supervisor(state: AgentState) -> str:
    """Conditional edge: route to cross_sell or direct_reply based on supervisor decision."""
    agents = state.get("agents_to_call", ["direct_reply"])
    if "cross_sell_agent" in agents:
        logger.debug("[graph] Routing -> cross_sell_node agents=%s", agents)
        return "cross_sell_node"
    logger.debug("[graph] Routing -> direct_reply_node agents=%s", agents)
    return "direct_reply_node"


def _should_send(state: AgentState) -> str:
    """Conditional edge after save_draft: only send if not rejected/errored."""
    if state.get("error"):
        logger.debug("[graph] Draft rejected/errored — ending without send")
        return END
    return "send_node"


def build_graph(checkpointer):
    """Compile the LangGraph StateGraph with the given checkpointer."""
    logger.info("[graph] Building LangGraph StateGraph")

    builder = StateGraph(AgentState)

    # ── Register all nodes ────────────────────────────────────────────────────
    builder.add_node("load_customer_data_node", load_customer_data_node)
    builder.add_node("parser_node", parser_node)
    builder.add_node("supervisor_node", supervisor_node)
    builder.add_node("cross_sell_node", cross_sell_node)
    builder.add_node("direct_reply_node", direct_reply_node)
    builder.add_node("message_fill_node", message_fill_node)
    builder.add_node("save_draft_node", save_draft_node)
    builder.add_node("send_node", send_node)

    # ── Define edges ──────────────────────────────────────────────────────────
    builder.add_edge(START, "load_customer_data_node")
    builder.add_edge("load_customer_data_node", "parser_node")
    builder.add_edge("parser_node", "supervisor_node")

    # Conditional: cross_sell vs direct_reply
    builder.add_conditional_edges(
        "supervisor_node",
        _route_after_supervisor,
        {
            "cross_sell_node": "cross_sell_node",
            "direct_reply_node": "direct_reply_node",
        },
    )

    # cross_sell path -> message_fill -> save_draft
    builder.add_edge("cross_sell_node", "message_fill_node")
    builder.add_edge("message_fill_node", "save_draft_node")

    # direct_reply path -> save_draft (skips message_fill, message already done)
    builder.add_edge("direct_reply_node", "save_draft_node")

    # After HITL interrupt+resume in save_draft: send or end
    builder.add_conditional_edges(
        "save_draft_node",
        _should_send,
        {
            "send_node": "send_node",
            END: END,
        },
    )

    builder.add_edge("send_node", END)

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("[graph] StateGraph compiled successfully")
    return graph
