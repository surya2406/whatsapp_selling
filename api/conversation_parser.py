"""LLM parser for normalized Meta conversation events."""
import json
import logging
from pathlib import Path

from litellm import acompletion

from config.settings import settings
from config.prompts import PARSER_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_PARSER_SKILL_PATH = _ROOT / "skills" / "parser" / "SKILL.md"
_PLAYBOOK_DIR = _ROOT / "playbooks"


def _load_reference_context() -> str:
    skill_text = _PARSER_SKILL_PATH.read_text(encoding="utf-8") if _PARSER_SKILL_PATH.exists() else ""
    playbook_notes = []
    for name in ["new_customer.json", "repeat_buyer.json", "high_value.json", "post_purchase.json"]:
        path = _PLAYBOOK_DIR / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            playbook_notes.append(
                {
                    "name": data.get("name", name),
                    "sentiment_gate": data.get("sentiment_gate", True),
                    "steps": data.get("steps", []),
                }
            )
        except Exception:
            continue
    return (
        "Use this parser skill specification as authoritative:\n"
        f"{skill_text}\n\n"
        "Use these playbook hints for routing relevance (do not hallucinate fields):\n"
        f"{json.dumps(playbook_notes, ensure_ascii=False)}"
    )


def _extract_json_object(raw_text: str) -> dict:
    raw_text = (raw_text or "").strip()
    if not raw_text:
        return {}
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw_text[start:end + 1])
        except json.JSONDecodeError:
            return {}
    return {}


def fallback_parse(events: list[dict]) -> dict:
    customer_lines = [event.get("text", "") for event in events if event.get("direction") == "incoming"]
    combined = " ".join(customer_lines).lower()
    if any(k in combined for k in ["refund", "complaint", "issue", "problem", "bad", "failed"]):
        intent = "complaint"
        sentiment = "negative"
    elif any(k in combined for k in ["buy", "order", "price", "quote", "need"]):
        intent = "purchase_signal"
        sentiment = "neutral"
    elif customer_lines:
        intent = "enquiry"
        sentiment = "neutral"
    else:
        intent = "general"
        sentiment = "neutral"

    return {
        "customer_intent": intent,
        "mentioned_products": [],
        "purchase_signals": intent == "purchase_signal",
        "sentiment": sentiment,
        "raw_summary": customer_lines[-1] if customer_lines else "No customer input found.",
    }


async def parse_conversation(events: list[dict]) -> dict:
    if not events:
        return fallback_parse(events)

    normalized = [
        {
            "meta_message_id": event.get("meta_message_id"),
            "direction": event.get("direction", ""),
            "message_type": event.get("message_type", ""),
            "status": event.get("status", ""),
            "text": event.get("text", ""),
            "created_at": event.get("created_at") or event.get("timestamp"),
        }
        for event in events
    ]

    user_prompt = (
        "Parse the following normalized Meta Engine conversation events. "
        "Return JSON only with keys: customer_intent, mentioned_products, purchase_signals, sentiment, raw_summary.\n\n"
        f"Events:\n{json.dumps(normalized, ensure_ascii=False)}"
    )

    try:
        response = await acompletion(
            model=f"ollama_chat/{settings.ollama_model}",
            api_base=settings.ollama_api_base,
            messages=[
                {
                    "role": "system",
                    "content": f"{PARSER_SYSTEM_PROMPT}\n\n{_load_reference_context()}",
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
            max_tokens=500,
        )
        content = response.choices[0].message.content
        parsed = _extract_json_object(content)
        if not parsed:
            raise ValueError("Parser returned non-JSON output")
        return parsed
    except Exception as exc:
        logger.warning("LLM parser failed, using fallback parser: %s", exc)
        return fallback_parse(events)
