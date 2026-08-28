"""Message filler module."""
import json
import logging
from litellm import acompletion

from config.settings import settings
from config.prompts import MESSAGE_FILL_SYSTEM_PROMPT, MESSAGE_FILL_USER_TEMPLATE

logger = logging.getLogger(__name__)

async def fill_message_template(template_str: str, data_dict: dict) -> str:
    """Uses LLM to fill in a message template with data in the correct language."""
    data_context = json.dumps(data_dict, ensure_ascii=False)
    user_prompt = MESSAGE_FILL_USER_TEMPLATE.format(
        template=template_str,
        data=data_context
    )

    try:
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
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error(f"Message Fill generation failed: {exc}")
        # Very basic fallback that might look messy but gets the job done if LLM fails
        fallback_msg = template_str
        for key, value in data_dict.items():
            fallback_msg = fallback_msg.replace(f"{{{key}}}", str(value))
        return fallback_msg
