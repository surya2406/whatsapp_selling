"""graph/nodes/parser.py — Node 2: LLM conversation parser + product matcher."""
import json
import logging
import re
from pathlib import Path
from graph.state import AgentState
from api.conversation_parser import parse_conversation
from skills.parser.scripts.sentiment import classify_sentiment
from skills.cross_sell_agent.scripts.cross_sell_helper import get_cross_sell_suggestions
from config.settings import settings

logger = logging.getLogger(__name__)

_PRODUCTS_PATH = Path(__file__).parent.parent.parent / "lookups" / "products.json"

_ELECTRODE_TYPES = [
    "6013", "7018", "7016", "6011", "6010",
    "308L", "309L", "316L", "312", "310", "347",
    "E308", "E309", "E316",
]
_ELECTRODE_PATTERN = re.compile(
    r'\b(' + '|'.join(re.escape(e) for e in _ELECTRODE_TYPES) + r')\b',
    re.IGNORECASE,
)
_DIAMETER_PATTERN = re.compile(r'\b(1\.6|2|2\.5|3|3\.15|4|5)(?:\s*mm)?\b')


def _find_mentioned_products(messages: list[str]) -> list[dict]:
    """Match products from text using electrode codes and exact name/ID match."""
    try:
        with open(_PRODUCTS_PATH, encoding="utf-8") as f:
            products = json.load(f)
    except Exception as e:
        logger.error("[parser] Failed to load products.json: %s", e)
        return []

    combined = " ".join(messages).lower()
    mentioned_types = [t.upper() for t in _ELECTRODE_PATTERN.findall(combined)]
    mentioned_diameters = _DIAMETER_PATTERN.findall(combined)
    mentioned = []
    seen_ids = set()

    for product_id, product in products.items():
        if product_id in seen_ids:
            continue
        product_name = str(product.get("name", ""))
        matched = False
        if product_id.lower() in combined or (product_name and product_name.lower() in combined):
            matched = True
        if not matched:
            for etype in mentioned_types:
                if etype in product_name.upper():
                    if mentioned_diameters:
                        for diam in mentioned_diameters:
                            variants = [diam, diam.replace(".", "")]
                            if diam == "3":
                                variants += ["3.15", "315"]
                            if any(v in product_name.upper() or v in product_name for v in variants):
                                matched = True
                                break
                    else:
                        matched = True
                if matched:
                    break
        if matched:
            mentioned.append({"product_id": product_id, "product_name": product_name})
            seen_ids.add(product_id)

    return mentioned


async def parser_node(state: AgentState) -> dict:
    """LLM-based conversation parser + deterministic product matcher."""
    customer_id = state["customer_id"]
    events = state.get("conversation_events", [])
    purchased_products = state.get("purchased_products", [])
    logger.info("[parser_node] START customer_id=%s events=%d", customer_id, len(events))

    # LLM parse
    parser_output = await parse_conversation(events)
    messages = [e.get("text", "") for e in events]

    # Product matching
    mentioned = _find_mentioned_products(messages)

    # Merge LLM-detected products
    parser_mentioned = parser_output.get("mentioned_products", [])
    if isinstance(parser_mentioned, list):
        try:
            with open(_PRODUCTS_PATH, encoding="utf-8") as f:
                products = json.load(f)
        except Exception:
            products = {}
        for item in parser_mentioned:
            if isinstance(item, dict):
                item = item.get("normalized_product_id") or item.get("raw_text") or ""
            if not isinstance(item, str) or not item:
                continue
            for p in mentioned:
                if p["product_name"].lower() == item.lower() or p["product_id"].lower() == item.lower():
                    break
            else:
                mentioned.append({"product_id": item, "product_name": item})

    # Fallback to past purchases if nothing mentioned
    if not mentioned and purchased_products:
        try:
            with open(_PRODUCTS_PATH, encoding="utf-8") as f:
                products = json.load(f)
        except Exception:
            products = {}
        for pid in purchased_products[:2]:
            pname = products.get(pid, {}).get("name", pid)
            mentioned.append({"product_id": pid, "product_name": pname, "source": "past_purchase"})
        logger.info("[parser_node] No product in message — using past purchases: %s", [m["product_id"] for m in mentioned])

    # Sentiment
    keyword_sentiment = classify_sentiment(messages[-3:])
    sentiment = parser_output.get("sentiment") or keyword_sentiment
    if keyword_sentiment == "negative":
        sentiment = "negative"

    # Cross-sell recommendations
    try:
        with open(_PRODUCTS_PATH, encoding="utf-8") as f:
            products_catalog = json.load(f)
    except Exception:
        products_catalog = {}

    recommendations = []
    for m in mentioned:
        match = get_cross_sell_suggestions(m["product_id"], settings.max_recommendations)
        for sid in match["suggestions"]:
            recommendations.append({
                "source_product_id": m["product_id"],
                "product_id": sid,
                "product_name": products_catalog.get(sid, {}).get("name", sid),
                "reason": match["reason"],
            })

    latest_msg = messages[-1] if messages else ""
    summary = parser_output.get("raw_summary", latest_msg)

    logger.info(
        "[parser_node] DONE customer_id=%s intent=%s sentiment=%s "
        "mentioned=%d recommendations=%d",
        customer_id, parser_output.get("customer_intent"), sentiment,
        len(mentioned), len(recommendations)
    )

    return {
        "parser_output": parser_output,
        "customer_intent": parser_output.get("customer_intent", "general"),
        "purchase_signals": bool(parser_output.get("purchase_signals", False)),
        "sentiment": sentiment,
        "language": parser_output.get("language", "english"),
        "mentioned_products": mentioned,
        "cross_sell_recommendations": recommendations,
        "conversation_summary": summary[:300] if len(summary) > 300 else summary,
    }
