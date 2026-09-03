"""graph/nodes/cross_sell.py — Node 4: LangGraph ReAct cross-sell agent (replaces Google ADK)."""
import logging
from graph.state import AgentState
from langchain_ollama import ChatOllama
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent
from config.settings import settings
from config.prompts import SUPERVISOR_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

# ── LangChain @tool wrappers around existing core_tools logic ─────────────────

@tool
async def get_customer_profile_tool(customer_id: str) -> dict:
    """Get the customer's RFM profile, segment, purchased products, and churn risk."""
    from agent.tools.core_tools import get_customer_profile
    return await get_customer_profile(customer_id)


@tool
async def get_cross_sell_options_tool(product_id: str) -> dict:
    """Get complementary product recommendations for a purchased product ID."""
    from agent.tools.core_tools import get_cross_sell_options
    return await get_cross_sell_options(product_id)


@tool
async def get_product_info_tool(product_id: str) -> dict:
    """Get name, price, and description for a product ID."""
    from agent.tools.core_tools import get_product_info
    return await get_product_info(product_id)


@tool
async def get_message_template_tool(template_key: str) -> str:
    """Get the WhatsApp message template string for the given template key."""
    from agent.tools.core_tools import get_message_template
    return await get_message_template(template_key)


from skills.loader import load_skill, get_available_skills_prompt

CORE_AGENT_SYSTEM_PROMPT = f"""You are the Troudz WhatsApp B2B Sales Copilot for industrial welding and cutting supplies in South India.

{get_available_skills_prompt()}

Core Workflow:
1. When analyzing the customer and recommending products, you can call `load_skill('cross-sell-agent')` to review the playbooks and rules.
2. Check customer profile and past orders via `get_customer_profile_tool`.
3. Select complementary cross-sell options via `get_cross_sell_options_tool` and product details via `get_product_info_tool`.
4. Pick the appropriate template key via `get_message_template_tool`.
5. Return ONLY a JSON object with this schema:
{{
  "template_key": "<chosen template key>",
  "template_data": {{
    "name": "<customer name>",
    "product_name": "<purchased product name>",
    "suggestion": "<recommended product name>",
    "discount": "<discount if applicable, else empty string>",
    "offer_code": "<offer code if applicable, else empty string>"
  }}
}}

Important: Always produce output in clean, professional B2B English."""


# ── Build LangGraph ReAct agent with On-Demand Skills ──────────────────────────

_llm = ChatOllama(
    model=settings.ollama_model,
    base_url=settings.ollama_api_base,
    temperature=0,
)

_cross_sell_react_agent = create_react_agent(
    model=_llm,
    tools=[
        load_skill,
        get_customer_profile_tool,
        get_cross_sell_options_tool,
        get_product_info_tool,
        get_message_template_tool,
    ],
    prompt=CORE_AGENT_SYSTEM_PROMPT,
)



async def cross_sell_node(state: AgentState) -> dict:
    """Runs the LangGraph ReAct cross-sell agent with tools."""
    customer_id = state["customer_id"]
    customer_name = state.get("customer_name", "")
    mentioned = state.get("mentioned_products", [])
    purchased = state.get("purchased_products", [])
    sentiment = state.get("sentiment", "neutral")

    logger.info(
        "[cross_sell_node] START customer_id=%s name=%s mentioned=%d purchased=%d sentiment=%s",
        customer_id, customer_name, len(mentioned), len(purchased), sentiment
    )

    # Build input prompt for the agent
    prompt = (
        f"Customer ID: {customer_id}\n"
        f"Customer Name: {customer_name or 'Anna'}\n"
        f"Past Purchased Products: {purchased}\n"
        f"Products Mentioned in Message: {[m['product_id'] for m in mentioned]}\n"
        f"Sentiment: {sentiment}\n\n"
        "Use your tools to find the best cross-sell recommendation and select the right message template. "
        "Return only the JSON object as described."
    )

    try:
        result = await _cross_sell_react_agent.ainvoke({
            "messages": [HumanMessage(content=prompt)]
        })
        agent_output = result["messages"][-1].content
        logger.info(
            "[cross_sell_node] DONE customer_id=%s output_len=%d preview=%s",
            customer_id, len(agent_output), agent_output[:100]
        )
        return {"agent_output": agent_output}

    except Exception as exc:
        logger.warning(
            "[cross_sell_node] LLM call unavailable (%s) — using deterministic cross-sell rules",
            exc
        )

        import json
        recs = state.get("cross_sell_recommendations", [])
        base_product_name = "Welding Electrodes"
        suggested_name = "Abrasive Cut-Off Wheels"

        if recs:
            suggested_name = recs[0].get("product_name") or recs[0].get("product_id") or suggested_name
        mentioned_prods = state.get("mentioned_products", [])
        if mentioned_prods:
            base_product_name = mentioned_prods[0].get("product_name") or mentioned_prods[0].get("product_id") or base_product_name

        fallback_data = {
            "template_key": "cross_sell_only",
            "template_data": {
                "name": customer_name or "Anna",
                "product_name": base_product_name,
                "suggestion": suggested_name,
                "discount": "10%",
                "offer_code": "WELDER10",
            },
        }
        return {"agent_output": json.dumps(fallback_data), "error": str(exc)}

