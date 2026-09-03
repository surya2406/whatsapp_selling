"""
agent/agent.py — WhatsApp Cross-Sell Agent (100% LangGraph)

Replaced Google ADK with pure LangGraph StateGraph / ReAct agent.
Uses:
  - LangGraph create_react_agent
  - langchain_ollama ChatOllama
  - LangChain @tool wrappers
  - Past orders & purchase history based proactive cross-selling
"""
import json
import logging
from pathlib import Path
from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from config.settings import settings
from agent.tools.core_tools import (
    get_customer_profile,
    get_cross_sell_options,
    get_product_info,
    get_message_template,
)

logger = logging.getLogger(__name__)

# ── LangChain @tool definitions ───────────────────────────────────────────────

@tool
async def tool_customer_profile(customer_id: str, customer_name: str = "") -> dict:
    """Fetches the customer's purchase history, past orders, and returns their RFM profile and purchased products."""
    return await get_customer_profile(customer_id, customer_name)


@tool
async def tool_cross_sell_options(product_id: str, max_suggestions: int = 3) -> dict:
    """Given a purchased product ID, returns complementary product IDs that can be recommended as cross-sell items."""
    return await get_cross_sell_options(product_id, max_suggestions)


@tool
async def tool_product_info(product_id: str) -> dict:
    """Looks up a product by its ID and returns its name, price, and description."""
    return await get_product_info(product_id)


@tool
async def tool_message_template(template_key: str) -> str:
    """Returns the raw WhatsApp message template string for a given template key."""
    return await get_message_template(template_key)


from skills.loader import load_skill, get_available_skills_prompt

TOOLS = [
    load_skill,
    tool_customer_profile,
    tool_cross_sell_options,
    tool_product_info,
    tool_message_template,
]

SYSTEM_PROMPT = (
    "You are the Troudz WhatsApp B2B Sales Copilot for industrial welding supplies in South India.\n\n"
    f"{get_available_skills_prompt()}\n\n"
    "Guidelines:\n"
    "1. When analyzing customer purchase history or choosing playbooks, call load_skill('cross-sell-agent').\n"
    "2. Inspect the customer profile and past orders to recommend complementary products.\n"
    "3. Return ONLY a JSON object with this exact schema:\n"
    "{\n"
    '  "template_key": "<key of the chosen message template>",\n'
    '  "template_data": {\n'
    '    "name": "<customer name>",\n'
    '    "product_name": "<name of purchased/mentioned product>",\n'
    '    "suggestion": "<name of recommended product>",\n'
    '    "discount": "<discount amount if applicable, else empty string>",\n'
    '    "offer_code": "<offer code if applicable, else empty string>"\n'
    '  }\n'
    "}\n\n"
    "Important: Always produce output in clean, professional B2B English."
)

# ── LangGraph ReAct Agent ─────────────────────────────────────────────────────

llm = ChatOllama(
    model=settings.ollama_model,
    base_url=settings.ollama_api_base,
    temperature=0,
)

langgraph_agent = create_react_agent(
    model=llm,
    tools=TOOLS,
    prompt=SYSTEM_PROMPT,
)



async def run_agent(
    customer_id: str,
    customer_name: str,
    raw_messages: list[str],
    session_id: str | None = None,
) -> dict:
    """
    Run the LangGraph cross-sell agent for a customer.
    Replaces the previous ADK Runner.
    """
    logger.info("[run_agent] START customer_id=%s messages=%d", customer_id, len(raw_messages))
    conversation_text = "\n".join(
        f"[{i+1}] {msg}" for i, msg in enumerate(raw_messages[-10:])
    )
    user_prompt = (
        f"Customer: {customer_name or 'Anna'} (ID: {customer_id})\n"
        f"Recent Messages:\n{conversation_text}\n\n"
        "Check customer purchase history and past orders to recommend complementary cross-sell products."
    )

    try:
        result = await langgraph_agent.ainvoke({
            "messages": [HumanMessage(content=user_prompt)]
        })
        last_message = result["messages"][-1].content
        logger.info("[run_agent] DONE customer_id=%s output_len=%d", customer_id, len(last_message))
        return {
            "generated_message": last_message,
            "session_id": session_id or customer_id,
            "error": None,
        }
    except Exception as exc:
        logger.error("[run_agent] FAILED customer_id=%s error=%s", customer_id, exc, exc_info=True)
        return {
            "generated_message": "",
            "session_id": session_id or customer_id,
            "error": str(exc),
        }

