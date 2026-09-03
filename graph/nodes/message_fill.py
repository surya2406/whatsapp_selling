"""graph/nodes/message_fill.py — Node 6: Fill template with customer-specific data."""
import json
import logging
from api.conversation_parser import _extract_json_object
from graph.state import AgentState
from litellm import acompletion
from config.settings import settings
from config.prompts import MESSAGE_FILL_SYSTEM_PROMPT, MESSAGE_FILL_USER_TEMPLATE

logger = logging.getLogger(__name__)


async def message_fill_node(state: AgentState) -> dict:
    """Parses agent JSON output and fills the message template using LLM."""
    customer_id = state["customer_id"]
    agent_output = state.get("agent_output", "")
    logger.info(
        "[message_fill_node] START customer_id=%s agent_output_len=%d",
        customer_id, len(agent_output)
    )

    # Parse the JSON that cross_sell_node returned
    agent_json = _extract_json_object(agent_output)
    
    # 1. Check if agent already produced a filled message in JSON
    if agent_json:
        # Check common message keys produced by LLMs
        msg_template = agent_json.get("message_template", {})
        candidate_msg = ""
        if isinstance(msg_template, dict) and msg_template.get("body"):
            candidate_msg = msg_template["body"]
        elif agent_json.get("message"):
            candidate_msg = str(agent_json["message"])
        elif agent_json.get("body"):
            candidate_msg = str(agent_json["body"])
        elif agent_json.get("recommended_message"):
            candidate_msg = str(agent_json["recommended_message"])

        if candidate_msg and candidate_msg.strip():
            logger.info("[message_fill_node] Extracted direct message candidate len=%d", len(candidate_msg))
            return {"generated_message": candidate_msg.strip()}

    # 2. If template_key is provided, load template and fill it
    if not agent_json or "template_key" not in agent_json:
        logger.warning(
            "[message_fill_node] Agent did not return valid template_key or direct body. Raw: %s",
            agent_output[:300]
        )
        # Fallback to authentic B2B English message
        rec_item = ""
        if agent_json and isinstance(agent_json.get("cross_sell_recommendation"), dict):
            rec_item = agent_json["cross_sell_recommendation"].get("product_name") or agent_json["cross_sell_recommendation"].get("recommended_product_id") or ""
        rec_label = rec_item if rec_item else "high-performance Abrasive Cut-Off Wheels"
        fallback_text = (
            f"Hello, thank you for your recent order with Troudz Industrial Supplies. "
            f"Based on your requirements, we currently have ready stock of {rec_label} "
            f"engineered for precision metal cutting. Volume rates and immediate dispatch are available. "
            f"Please let us know if you would like us to include this in your upcoming shipment."
        )
        return {"generated_message": fallback_text}


    template_key = agent_json["template_key"]
    template_data = agent_json.get("template_data", {})
    language = state.get("language", "english")  # "tamil" | "english" | "tanglish"
    logger.debug(
        "[message_fill_node] template_key=%s language=%s data_keys=%s",
        template_key, language, list(template_data.keys())
    )

    # Load the template string — try language-specific variant first
    try:
        from agent.tools.core_tools import get_message_template
        # For English customers, try an _en variant (e.g. "repeat_buyer_offer_en")
        if language == "english":
            english_key = f"{template_key}_en"
            try:
                template_str = await get_message_template(english_key)
                logger.debug("[message_fill_node] Using English variant template_key=%s", english_key)
            except Exception:
                # No English variant — fall back to base template (LLM will translate tone)
                template_str = await get_message_template(template_key)
                logger.debug("[message_fill_node] No _en variant found, using base template_key=%s", template_key)
        else:
            template_str = await get_message_template(template_key)
    except Exception as exc:
        logger.error("[message_fill_node] Failed to load template key=%s: %s", template_key, exc)
        template_str = agent_output  # fallback

    # LLM fills the template in the right language and tone
    data_context = json.dumps(template_data, ensure_ascii=False)
    user_prompt = MESSAGE_FILL_USER_TEMPLATE.format(template=template_str, data=data_context)

    # Inject detected language so LLM matches customer's language
    language_instruction = (
        f"\n\nDETECTED CUSTOMER LANGUAGE: {language}. "
        f"Write the reply in {language} to match the customer."
    )
    system_prompt = MESSAGE_FILL_SYSTEM_PROMPT + language_instruction

    try:
        logger.debug("[message_fill_node] Calling LLM for template fill model=%s language=%s", settings.ollama_model, language)
        response = await acompletion(
            model=f"ollama_chat/{settings.ollama_model}",
            api_base=settings.ollama_api_base,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=200,
        )
        filled = response.choices[0].message.content.strip()
        logger.info(
            "[message_fill_node] DONE customer_id=%s language=%s filled_len=%d preview=%s",
            customer_id, language, len(filled), filled[:80]
        )
        return {"generated_message": filled}

    except Exception as exc:
        logger.error("[message_fill_node] LLM FAILED error=%s — string replace fallback", exc, exc_info=True)
        fallback = template_str
        for k, v in template_data.items():
            fallback = fallback.replace(f"{{{k}}}", str(v))
        logger.info("[message_fill_node] FALLBACK filled_len=%d", len(fallback))
        return {"generated_message": fallback}
