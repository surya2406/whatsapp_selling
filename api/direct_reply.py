"""Direct Reply module for non-sales conversations."""
import logging
from litellm import acompletion

from config.settings import settings
from config.prompts import DIRECT_REPLY_SYSTEM_PROMPT, DIRECT_REPLY_USER_TEMPLATE

logger = logging.getLogger(__name__)

async def generate_direct_reply(customer_name: str, raw_summary: str) -> str:
    """Generate a simple professional B2B acknowledgement message."""
    user_prompt = DIRECT_REPLY_USER_TEMPLATE.format(
        raw_summary=raw_summary,
        customer_name=customer_name or "Anna"
    )

    try:
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
        return response.choices[0].message.content.strip()
    except Exception as exc:
        logger.error(f"Direct Reply generation failed: {exc}")
        return "Hi, thanks for reaching out. Let us know if you need any welding supplies."
