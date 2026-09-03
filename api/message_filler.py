"""Message filler module."""
import json
import logging
from litellm import acompletion

from config.settings import settings
from config.prompts import MESSAGE_FILL_SYSTEM_PROMPT, MESSAGE_FILL_USER_TEMPLATE

logger = logging.getLogger(__name__)

async def fill_message_template(template_str: str, data_dict: dict) -> str:
    """Uses LLM to fill in a message template with data in the correct language."""
    logger.info(
        "[fill_message_template] START template_len=%d data_keys=%s",
        len(template_str), list(data_dict.keys())
    )
    data_context = json.dumps(data_dict, ensure_ascii=False)
    user_prompt = MESSAGE_FILL_USER_TEMPLATE.format(
        template=template_str,
        data=data_context
    )

    try:
        logger.debug("[fill_message_template] Calling LLM model=%s", settings.ollama_model)
        response = await acompletion(
            model=f"ollama_chat/{settings.ollama_model}",
            api_base=settings.ollama_api_base,
            messages=[
                {"role": "system", "content": MESSAGE_FILL_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=150,
        )
        result = response.choices[0].message.content.strip()
        logger.info(
            "[fill_message_template] DONE filled_len=%d preview=%s",
            len(result), result[:80]
        )
        return result
    except Exception as exc:
        logger.error(
            "[fill_message_template] LLM FAILED error=%s — using string replacement fallback",
            exc, exc_info=True
        )
        fallback_msg = template_str
        for key, value in data_dict.items():
            fallback_msg = fallback_msg.replace(f"{{{key}}}", str(value))
        logger.info("[fill_message_template] FALLBACK result_len=%d", len(fallback_msg))
        return fallback_msg
