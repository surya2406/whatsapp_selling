"""graph/nodes/supervisor.py — Node 3: LLM routing supervisor."""
import json
import logging
from graph.state import AgentState
from litellm import acompletion
from config.settings import settings
from config.prompts import SUPERVISOR_SYSTEM_PROMPT, SUPERVISOR_USER_TEMPLATE
from cache.redis_client import get_cached_customer_profile

logger = logging.getLogger(__name__)


def _extract_agents(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "agents_to_call" in data:
            return data["agents_to_call"]
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(raw[start:end + 1])
            if isinstance(data, dict) and "agents_to_call" in data:
                return data["agents_to_call"]
        except json.JSONDecodeError:
            pass
    return []


async def supervisor_node(state: AgentState) -> dict:
    """Decides which agents to call based on customer profile + conversation analysis."""
    customer_id = state["customer_id"]
    logger.info(
        "[supervisor_node] START customer_id=%s intent=%s sentiment=%s purchase_signals=%s",
        customer_id, state.get("customer_intent"), state.get("sentiment"), state.get("purchase_signals")
    )

    profile_data = get_cached_customer_profile(customer_id)
    if not profile_data:
        logger.warning("[supervisor_node] No cached profile for customer_id=%s", customer_id)
    profile_ctx = json.dumps(profile_data, ensure_ascii=False) if profile_data else "No profile available."

    analysis_ctx = json.dumps({
        "customer_intent": state.get("customer_intent"),
        "purchase_signals": state.get("purchase_signals"),
        "sentiment": state.get("sentiment"),
        "mentioned_products": state.get("mentioned_products"),
        "purchased_products": state.get("purchased_products"),
    }, ensure_ascii=False)

    system_prompt = f"{SUPERVISOR_SYSTEM_PROMPT}\n\nPROFILE:\n{profile_ctx}\n\nANALYSIS:\n{analysis_ctx}"

    try:
        response = await acompletion(
            model=f"ollama_chat/{settings.ollama_model}",
            api_base=settings.ollama_api_base,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": SUPERVISOR_USER_TEMPLATE.format(customer_id=customer_id)},
            ],
            temperature=0,
            max_tokens=200,
        )
        content = response.choices[0].message.content
        agents = _extract_agents(content)
        if not agents:
            logger.warning("[supervisor_node] Defaulting to cross_sell_agent for cross-selling recommendations")
            agents = ["cross_sell_agent"]
        logger.info("[supervisor_node] DONE customer_id=%s agents_to_call=%s", customer_id, agents)
        return {"agents_to_call": agents}

    except Exception as exc:
        logger.warning("[supervisor_node] LLM FAILED error=%s — fallback to cross_sell_agent", exc)
        return {"agents_to_call": ["cross_sell_agent"]}

