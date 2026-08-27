"""
agent/agent.py — WhatsApp Cross-Sell Agent (Google ADK)

Follows the proper ADK pattern:
  - root_agent variable (required by ADK)
  - SkillToolset pointing to the skills/ directory
  - LiteLlm for local Ollama model
  - Python tools for DB, lookups, and profile access

Skills directory structure (ADK L1/L2/L3):
  skills/cross_sell_agent/
    SKILL.md              ← L1 metadata + L2 instructions
    references/           ← L3 extended guidance docs
      workflow.md
    assets/               ← L3 data resources
      playbooks/          ← segment-based playbooks
      lookups/            ← product catalog + cross-sell rules
    scripts/              ← L3 executable helpers
      cross_sell_helper.py

Run with:
  adk web    (from the whatsapp_selling_agent/ directory)
  adk run agent
"""

import json
import logging
import os
from pathlib import Path

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from config.settings import settings
from cache.redis_client import cache_customer_profile, get_cached_customer_profile
from agent.tools.core_tools import get_customer_profile, get_cross_sell_options, get_product_info, get_message_template

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
_LOOKUPS_DIR = Path(__file__).parent.parent / "lookups"
_SKILLS_DIR = Path(__file__).parent.parent / "skills"

# ── Ensure LiteLLM uses correct Ollama endpoint ────────────────────────────────
os.environ.setdefault("OLLAMA_API_BASE", settings.ollama_api_base)





# ══════════════════════════════════════════════════════════════════════════════
#  ROOT AGENT
#  This is the required entry point for `adk run` and `adk web`.
# ══════════════════════════════════════════════════════════════════════════════

root_agent = Agent(
    name="whatsapp_cross_sell_agent",
    model=LiteLlm(model=f"ollama_chat/{settings.ollama_model}"),
    description=(
        "A WhatsApp sales agent that reads customer purchase history and "
        "recommends the best complementary products using cross-sell rules."
    ),
    instruction=(
        "You are a WhatsApp sales assistant. You will receive raw JSON message payloads "
        "directly from the Meta WhatsApp API database. "
        "Read the supplied JSON messages to understand the conversation history, profile the customer with the available "
        "tools, resolve mentioned or previously purchased product IDs, find cross-sell "
        "options, and compose a warm WhatsApp draft. Use only products returned by tools."
    ),
    tools=[
        get_customer_profile,
        get_cross_sell_options,
        get_product_info,
        get_message_template,
    ],
)

# ══════════════════════════════════════════════════════════════════════════════
#  API RUNNER SUPPORT
# ══════════════════════════════════════════════════════════════════════════════

_session_service = InMemorySessionService()

async def create_session(user_id: str) -> str:
    """Create a new ADK session and return its session ID."""
    session = await _session_service.create_session(
        app_name=root_agent.name,
        user_id=user_id,
    )
    return session.id

async def run_agent(
    customer_id: str,
    customer_name: str,
    raw_messages: list[str],
    session_id: str | None = None,
) -> dict:
    """
    Run the root_agent for a batch of WhatsApp messages.
    Creates a new session if none is provided.
    """
    if session_id is None:
        session_id = await create_session(user_id=customer_id)

    conversation_text = "\n".join(
        f"[{i+1}] {msg}" for i, msg in enumerate(raw_messages[-10:])
    )
    user_message = (
        f"Customer: {customer_name} (ID: {customer_id})\n"
        f"Messages:\n{conversation_text}"
    )

    runner = Runner(
        agent=root_agent,
        app_name=root_agent.name,
        session_service=_session_service,
    )
    new_message = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=user_message)],
    )

    try:
        generated_message = ""
        async for event in runner.run_async(
            user_id=customer_id,
            session_id=session_id,
            new_message=new_message,
        ):
            if event.is_final_response():
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        text = getattr(part, "text", None)
                        if text:
                            generated_message = text
                break

        logger.info(
            f"ADK agent complete: customer={customer_id} "
            f"message_len={len(generated_message)}"
        )
        return {
            "generated_message": generated_message,
            "session_id": session_id,
            "error": None,
        }

    except Exception as e:
        logger.error(f"ADK agent failed for customer={customer_id}: {e}")
        return {
            "generated_message": "",
            "session_id": session_id,
            "error": str(e),
        }
