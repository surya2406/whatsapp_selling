"""Supervisor routing module."""
import json
import logging
from litellm import acompletion

from config.settings import settings
from config.prompts import SUPERVISOR_SYSTEM_PROMPT, SUPERVISOR_USER_TEMPLATE
from cache.redis_client import get_cached_customer_profile

logger = logging.getLogger(__name__)

def _extract_json_array(raw_text: str) -> list[str]:
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return []
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict) and "agents_to_call" in data:
            return data["agents_to_call"]
        return []
    except json.JSONDecodeError:
        pass
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(raw_text[start:end + 1])
            if isinstance(data, dict) and "agents_to_call" in data:
                return data["agents_to_call"]
        except json.JSONDecodeError:
            pass
    return ["direct_reply"]  # Fallback

async def route_conversation(customer_id: str, analysis: dict) -> list[str]:
    """Determine which agents should process the conversation."""
    profile_data = await get_cached_customer_profile(customer_id)
    profile_context = json.dumps(profile_data, ensure_ascii=False) if profile_data else "No profile available."
    
    analysis_context = json.dumps({
        "customer_intent": analysis.get("customer_intent"),
        "purchase_signals": analysis.get("purchase_signals"),
        "sentiment": analysis.get("sentiment"),
        "mentioned_products": analysis.get("mentioned_products"),
    }, ensure_ascii=False)

    system_prompt = f"{SUPERVISOR_SYSTEM_PROMPT}\n\nPROFILE:\n{profile_context}\n\nANALYSIS:\n{analysis_context}"
    user_prompt = SUPERVISOR_USER_TEMPLATE.format(customer_id=customer_id)

    try:
        response = await acompletion(
            model=f"ollama_chat/{settings.ollama_model}",
            api_base=settings.ollama_api_base,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=200,
        )
        content = response.choices[0].message.content
        agents = _extract_json_array(content)
        if not agents:
            agents = ["direct_reply"]
        return agents
    except Exception as exc:
        logger.warning(f"Supervisor routing failed: {exc}, falling back to cross_sell_agent or direct_reply")
        if analysis.get("purchase_signals") or analysis.get("mentioned_products"):
            return ["cross_sell_agent"]
        return ["direct_reply"]
