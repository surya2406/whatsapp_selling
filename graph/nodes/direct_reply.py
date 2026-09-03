"""graph/nodes/direct_reply.py — Node 5: Simple B2B acknowledgement (non-sales path)."""
import logging
from graph.state import AgentState
from litellm import acompletion
from config.settings import settings
from config.prompts import DIRECT_REPLY_SYSTEM_PROMPT, DIRECT_REPLY_USER_TEMPLATE

logger = logging.getLogger(__name__)


async def direct_reply_node(state: AgentState) -> dict:
    """Generates a professional B2B reply for non-sales or negative sentiment conversations."""
    customer_id = state["customer_id"]
    customer_name = state.get("customer_name", "")
    summary = state.get("conversation_summary", state.get("mentioned_products", ""))
    logger.info(
        "[direct_reply_node] START customer_id=%s sentiment=%s",
        customer_id, state.get("sentiment")
    )

    user_prompt = DIRECT_REPLY_USER_TEMPLATE.format(
        raw_summary=summary,
        customer_name=customer_name or "Anna"
    )

    try:
        logger.debug("[direct_reply_node] Calling LLM model=%s", settings.ollama_model)
        response = await acompletion(
            model=f"ollama_chat/{settings.ollama_model}",
            api_base=settings.ollama_api_base,
            messages=[
                {"role": "system", "content": DIRECT_REPLY_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=150,
        )
        message = response.choices[0].message.content.strip()
        logger.info(
            "[direct_reply_node] DONE customer_id=%s reply_len=%d preview=%s",
            customer_id, len(message), message[:80]
        )
        return {"agent_output": message, "generated_message": message}

    except Exception as exc:
        logger.error(
            "[direct_reply_node] FAILED customer_id=%s error=%s",
            customer_id, exc, exc_info=True
        )
        fallback = "Hi, thanks for reaching out. Let us know if you need any welding supplies."
        return {"agent_output": fallback, "generated_message": fallback}
