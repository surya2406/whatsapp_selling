# WhatsApp AI Sales Agent — Full Project Plan

> **Goal:** Analyze stored WhatsApp conversations → identify cross-sell / up-sell opportunities → send personalized offers → improve client sales automatically.
> **Principle:** LLM thinks and routes. Tools are deterministic lookups. Zero hallucination on recommendations.

---

## Table of Contents

1. [Core Design Philosophy](#1-core-design-philosophy)
2. [Full Tech Stack](#2-full-tech-stack)
3. [System Architecture](#3-system-architecture)
4. [Multi-Agent Design](#4-multi-agent-design)
5. [File & Folder Structure](#5-file--folder-structure)
6. [Agent Behavior — Step by Step](#6-agent-behavior--step-by-step)
7. [Skills Reference](#7-skills-reference)
8. [Playbooks Reference](#8-playbooks-reference)
9. [Lookup Tables Reference](#9-lookup-tables-reference)
10. [Database Schema](#10-database-schema)
11. [Redis Cache Strategy](#11-redis-cache-strategy)
12. [LLM Usage — Where & Why](#12-llm-usage--where--why)
13. [Additional Revenue Features](#13-additional-revenue-features)
14. [Build Sequence — Week by Week](#14-build-sequence--week-by-week)
15. [Migration Path — SQLite to PostgreSQL](#15-migration-path--sqlite-to-postgresql)
16. [Environment & Config](#16-environment--config)

---

## 1. Core Design Philosophy

### The Golden Rule
```
LLM is allowed to → parse conversation text, decide which agents to call, fill message templates
LLM is NOT allowed to → decide which product to recommend, set offer %, make predictions
```

### Why This Prevents Hallucination
Every product recommendation, offer, and cross-sell suggestion comes from a JSON lookup file that you control. The LLM only reads these results and writes them into a natural-sounding WhatsApp message. If a product is not in your `products.json`, the agent cannot recommend it — ever.

### Three-Layer Separation

| Layer | Who decides | How |
|---|---|---|
| Routing layer | Supervisor LLM | Reads conversation → decides which specialist agents to call |
| Recommendation layer | Pure Python + JSON | Deterministic lookup — no LLM involved |
| Language layer | Message-fill LLM | Fills a template with the lookup results |

---

## 2. Full Tech Stack

| Component | Tool | Why |
|---|---|---|
| Agent orchestration | LangGraph 0.2+ | State machine = maps perfectly to playbook steps; conditional edges = only needed agents run |
| LLM calls | Anthropic SDK (claude-sonnet-4-6) | Direct control, no LangChain wrapper overhead |
| API server | FastAPI + Uvicorn | Async, fast, perfect for WhatsApp webhooks |
| Task queue | Celery + Redis | 5000+ customers need async processing; peak load handling |
| Primary database | SQLite (→ PostgreSQL later) | SQLAlchemy ORM — zero code change on migration |
| Cache | Redis | Customer profile cache (1hr TTL) — avoids DB hit per message |
| Data validation | Pydantic v2 | All skill inputs/outputs are typed; no silent data errors |
| Config management | Pydantic Settings + .env | Environment-based config |
| Testing | Pytest + pytest-asyncio | Async-compatible testing |
| Containerization | Docker + docker-compose | FastAPI + Celery + Redis + SQLite in one command |

### Why LangGraph over other frameworks

| Framework | Hallucination control | Stateful playbooks | Our verdict |
|---|---|---|---|
| LangGraph | High — state machine, you control every edge | Native — graph nodes = playbook steps | ✅ Chosen |
| Pure Anthropic SDK | Maximum — but high boilerplate | Manual build required | Backup option |
| CrewAI | Low — agents decide freely | Partial | ❌ Skip |
| AutoGen | Low — agents chat freely | None | ❌ Skip |
| Pydantic AI | High — but no playbook concept | None | Too limited |

---

## 3. System Architecture

### Request Flow (Scheduled / Polled from Meta Engine DB)

```
Customer sends WhatsApp message → Stored in Meta Engine DB (messages table)
        │
        ▼
Celery Beat Scheduler (or Manual Trigger)
  └── Fetches new, unprocessed messages from Meta Engine DB
  └── Pushes tasks to Redis queue
        │
        ▼
Celery worker picks up task
        │
        ▼
LangGraph agent starts
  ├── Step 1: Conversation Parser    (LLM — extracts intent, products, signals)
  ├── Step 2: Customer Profiler      (pure Python — RFM score, segment, churn risk)
  ├── Step 3: Supervisor Agent       (LLM — decides which specialists to call)
  │       ├── → Cross-sell Agent    (if product purchased detected)
  │       ├── → Up-sell Agent       (if upgrade opportunity detected)
  │       ├── → Offer Agent         (if customer is offer-eligible)
  │       └── → Direct Reply        (if general query, no sales opportunity)
  ├── Step 4: Results Aggregator     (pure Python — combines specialist outputs)
  └── Step 5: Message Generator      (LLM — fills template with results)
        │
        ▼
Agent stores raw/parsed context and generated draft in local SQLite DB
        │
        ▼
Human reviews, edits, approves, or rejects the draft
        │
        ▼
Approved message is sent through Meta Engine and delivery is audited in SQLite
```

### Scale Architecture (5000+ customers)

```
Peak load (e.g., sale day — 1000 messages/hr)
        │
        ▼
FastAPI (multiple workers via Uvicorn)
        │
        ▼
Redis Queue (messages never lost even if workers are busy)
        │
        ▼
Celery workers (scale horizontally — add more workers on high load)
        │
        ▼
Redis Profile Cache (avoid hitting DB for every message)
        │
        ▼
SQLite / PostgreSQL
```

---

## 4. Multi-Agent Design

### ReAct Reasoning Loop (Supervisor internals)

The supervisor agent uses the ReAct pattern — Reason → Act → Observe → Reason again:

```
Think: "Customer bought face wash last week. High-value segment. Sentiment positive."
Act:   call get_customer_profile(customer_id)
Observe: { segment: "high_value", last_product: "PROD_001", churn_risk: "low" }
Think: "PROD_001 has cross-sell rule. Customer is VIP. I should call cross_sell_agent + offer_agent."
Done:  route to [cross_sell_agent, offer_agent]
```

The supervisor loops until it has enough information to make a routing decision. It never decides WHAT to recommend — only WHO to call.

### Specialist Agents (deterministic — no LLM)

Each specialist is a pure Python function that reads from lookup JSON files:

```
cross_sell_agent  → reads cross_sell_rules.json → returns product list
up_sell_agent     → reads upsell_rules.json     → returns upgrade option
offer_agent       → reads offers.json           → returns ranked offer list
direct_reply      → returns None (no recommendation)
```

### Conditional Routing — Only Needed Agents Run

```python
# Example: supervisor decision → only matching agents are invoked
def route_to_agents(state):
    needed = []
    if state["purchased_product"]:  needed.append("cross_sell_agent")
    if state["upgrade_eligible"]:   needed.append("up_sell_agent")
    if state["offer_eligible"]:     needed.append("offer_agent")
    if not needed:                  needed.append("direct_reply")
    return needed
    # Agents not in this list → never run for this customer message
```

---

## 5. File & Folder Structure

```
whatsapp-sales-agent/
│
├── agent/
│   ├── __init__.py
│   ├── state.py                  # AgentState TypedDict — shared state across all nodes
│   ├── graph.py                  # LangGraph graph definition — nodes + edges
│   ├── nodes/
│   │   ├── __init__.py
│   │   ├── parser.py             # Node 1: parse conversation (LLM)
│   │   ├── profiler.py           # Node 2: build RFM profile (pure Python)
│   │   ├── supervisor.py         # Node 3: routing supervisor (LLM + ReAct)
│   │   ├── cross_sell.py         # Specialist: cross-sell lookup (pure Python)
│   │   ├── up_sell.py            # Specialist: up-sell lookup (pure Python)
│   │   ├── offer_agent.py        # Specialist: offer ranker (pure Python)
│   │   ├── aggregator.py         # Node: combine specialist results (pure Python)
│   │   └── message_fill.py       # Node: fill template (LLM)
│   └── tools/
│       ├── __init__.py
│       ├── profile_tool.py       # Tool: get_customer_profile (used by supervisor)
│       ├── conversation_tool.py  # Tool: get_conversation_summary (used by supervisor)
│       └── sentiment_tool.py     # Tool: check_sentiment (used by supervisor)
│
├── skills/
│   ├── __init__.py
│   ├── cross_sell.py             # Pure function: lookup cross-sell rules
│   ├── up_sell.py                # Pure function: lookup up-sell rules
│   ├── offer_ranker.py           # Pure function: rank active offers for customer
│   ├── sentiment.py              # Pure function: classify conversation sentiment
│   ├── rfm.py                    # Pure function: calculate RFM score
│   └── timing.py                 # Pure function: best send time from chat history
│
├── playbooks/
│   ├── new_customer.json         # Flow for first-time buyers
│   ├── repeat_buyer.json         # Flow for 2+ purchase customers
│   ├── high_value.json           # VIP customer flow
│   ├── dormant.json              # Inactive > X days
│   └── post_purchase.json        # Follow-up after a sale (3 days later)
│
├── lookups/
│   ├── products.json             # Full product catalog
│   ├── offers.json               # Active offers with conditions and expiry
│   ├── segments.json             # Segment thresholds (what makes someone VIP etc.)
│   ├── cross_sell_rules.json     # "If customer bought A → suggest B, C"
│   ├── upsell_rules.json         # "If customer has X → offer upgrade Y"
│   └── message_templates.json    # WhatsApp message templates per scenario
│
├── config/
│   ├── __init__.py
│   ├── settings.py               # Pydantic Settings — reads from .env
│   └── prompts.py                # All LLM system prompts as Python constants
│
├── db/
│   ├── __init__.py
│   ├── database.py               # SQLAlchemy engine + session setup
│   ├── models.py                 # ORM models: Customer, Conversation, Offer, Feedback
│   ├── queries.py                # All DB query functions
│   └── migrations/               # Alembic migration files (when moving to Postgres)
│
├── api/
│   ├── __init__.py
│   ├── main.py                   # FastAPI app instance
│   ├── fetcher.py                # Service to fetch messages from Meta Engine DB
│   ├── tasks.py                  # Celery task definitions
│   └── dependencies.py           # FastAPI dependency injection (DB session etc.)
│
├── cache/
│   ├── __init__.py
│   └── redis_client.py           # Redis connection + get/set/invalidate helpers
│
├── tests/
│   ├── __init__.py
│   ├── test_skills.py            # Unit tests for each skill (no LLM needed)
│   ├── test_graph.py             # Integration test for LangGraph flow
│   ├── test_fetcher.py           # DB fetcher integration tests
│   └── fixtures/
│       ├── sample_conversations.json
│       └── sample_customers.json
│
├── scripts/
│   ├── seed_lookups.py           # Populate products.json, offers.json etc.
│   └── backfill_profiles.py      # Build RFM profiles for existing customers
│
├── .env.example                  # Template for environment variables
├── .gitignore
├── docker-compose.yml            # FastAPI + Celery + Redis
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## 6. Agent Behavior — Step by Step

### Step 1 — Message Fetched
Existing WhatsApp automation stores messages in `meta engine db` (`messages` table).
`api/fetcher.py` (run via Celery Beat or cron) fetches new, unprocessed messages.
Raw and parsed messages are stored locally with the Meta message ID for deduplication and audit.
Pushes `process_message` Celery task to Redis queue with message payload.

### Step 2 — Conversation Parsing (LLM)
`nodes/parser.py` sends last 10 messages to Claude with a strict extraction prompt.

**Prompt constraint:** "Extract ONLY what is present in the conversation. Return JSON with these exact keys. Do not infer or add anything not explicitly stated."

**Output shape (Pydantic-validated):**
```json
{
  "customer_intent": "enquiry | purchase_signal | complaint | general",
  "mentioned_products": ["PROD_001"],
  "purchase_signals": true,
  "sentiment": "positive | negative | neutral",
  "raw_summary": "Customer asked about moisturizer after buying face wash"
}
```

### Step 3 — Customer Profile Building (pure Python)
`nodes/profiler.py` queries SQLite for this customer's history.
Calculates RFM score. Assigns segment from `segments.json`.

**Profile shape:**
```json
{
  "customer_id": "CUST_123",
  "segment": "high_value",
  "rfm_score": { "recency": 3, "frequency": 8, "monetary": 4200 },
  "last_purchased_product": "PROD_001",
  "days_since_last_purchase": 7,
  "churn_risk": "low",
  "offer_eligible": true,
  "upgrade_eligible": true
}
```

### Step 4 — Supervisor Routing (LLM + ReAct)
`nodes/supervisor.py` uses a ReAct agent with 3 tools:
- `get_customer_profile` — reads from Redis cache (or DB)
- `get_conversation_summary` — returns parsed result from Step 2
- `check_eligibility` — pure logic: is customer offer-eligible?

Supervisor decides which specialist agents to call. It cannot recommend products directly — it only routes.

### Step 5 — Specialist Agents Run (pure Python)
Only the agents decided by supervisor in Step 4 are invoked.
Each reads its corresponding lookup JSON and returns results.

**Cross-sell agent example:**
```python
def cross_sell_agent(state: AgentState) -> dict:
    rules = load_lookup("cross_sell_rules.json")
    product_id = state["profile"]["last_purchased_product"]
    rule = rules.get(product_id)
    if not rule:
        return {"cross_sell_results": []}
    return {
        "cross_sell_results": rule["suggest"],
        "cross_sell_reason": rule["reason"]
    }
    # No LLM. No prediction. Purely what you defined in the JSON.
```

### Step 6 — Aggregation (pure Python)
`nodes/aggregator.py` combines all specialist results.
Deduplicates product suggestions. Picks top 1-2 recommendations (configurable).
Selects the right message template from `message_templates.json`.

### Step 7 — Message Filling (LLM)
`nodes/message_fill.py` calls Claude with the aggregated results and a template.

**Prompt constraint:** "Fill in the template below using ONLY the provided product and offer. Do not add extra products, discounts, or claims not in the data."

**Input:**
```
Template: "Hi {name}! Since you loved {product_name}, you might also like {suggestion}. {offer_text}"
Name: Priya
Product name: Face wash
Suggestion: Moisturizer SPF 30
Offer text: Get 10% off this week with code CARE10
```

**Output:** A natural, friendly WhatsApp message in the customer's preferred language.

### Step 8 — Human Review, Send & Log
Generated messages remain `pending_review` until a human edits/approves or rejects them.
Only an approved message is sent via your WhatsApp automation API.
Record saved: which template, which products suggested, which offer, timestamp.
Feedback loop: when customer replies or purchases, update their profile.

---

## 7. Skills Reference

All skills are pure Python functions. No LLM. Inputs and outputs are Pydantic-validated.

### `skills/rfm.py` — RFM Scorer
- Input: list of purchase records from DB
- Output: `{ recency_days, frequency_count, monetary_total, rfm_score (1-5) }`
- Used by: profiler node

### `skills/cross_sell.py` — Cross-sell Lookup
- Input: `product_id`
- Output: list of suggested `product_id`s from `cross_sell_rules.json`
- Used by: cross-sell specialist agent

### `skills/up_sell.py` — Up-sell Lookup
- Input: `product_id`, `customer_tier`
- Output: single upgrade product from `upsell_rules.json`
- Used by: up-sell specialist agent

### `skills/offer_ranker.py` — Offer Ranker
- Input: `customer_segment`, `purchased_products`
- Logic: filter `offers.json` by eligibility → sort by discount value → return top 1
- Output: single best offer object
- Used by: offer specialist agent

### `skills/sentiment.py` — Sentiment Classifier
- Input: last 3 message texts
- Logic: keyword matching against positive/negative word lists (no LLM)
- Output: `"positive" | "negative" | "neutral"`
- Used by: supervisor tool + sentiment gate before any offer

### `skills/timing.py` — Best Send Time
- Input: customer's historical message timestamps from DB
- Logic: find most frequent hour + day of week when customer responds
- Output: `{ best_hour: 18, best_day: "friday" }`
- Used by: Celery scheduler for delayed sends

---

## 8. Playbooks Reference

Playbooks are JSON files that define the recommended flow per customer segment. The supervisor reads the relevant playbook to guide its routing decisions.

### `playbooks/new_customer.json`
```json
{
  "name": "New customer flow",
  "trigger": { "segment": "new", "max_orders": 1 },
  "sentiment_gate": true,
  "steps": [
    { "step": 1, "action": "check_sentiment", "on_negative": "send_empathy_template" },
    { "step": 2, "action": "offer_agent", "filter": "welcome_offers_only" },
    { "step": 3, "action": "send_message", "template": "new_customer_welcome" }
  ]
}
```

### `playbooks/repeat_buyer.json`
```json
{
  "name": "Repeat buyer flow",
  "trigger": { "segment": "repeat", "min_orders": 2 },
  "sentiment_gate": true,
  "steps": [
    { "step": 1, "action": "check_sentiment", "on_negative": "send_empathy_template" },
    { "step": 2, "action": "cross_sell_agent", "input": "last_purchased_product" },
    { "step": 3, "action": "offer_agent", "filter": "loyalty_offers_only" },
    { "step": 4, "action": "send_message", "template": "repeat_buyer_offer" }
  ]
}
```

### `playbooks/high_value.json`
```json
{
  "name": "VIP customer flow",
  "trigger": { "segment": "high_value", "min_orders": 10 },
  "sentiment_gate": true,
  "steps": [
    { "step": 1, "action": "check_sentiment", "on_negative": "route_to_human" },
    { "step": 2, "action": "up_sell_agent" },
    { "step": 3, "action": "cross_sell_agent" },
    { "step": 4, "action": "offer_agent", "filter": "vip_offers_only" },
    { "step": 5, "action": "send_message", "template": "vip_personalized" }
  ]
}
```

### `playbooks/dormant.json`
```json
{
  "name": "Dormant customer win-back",
  "trigger": { "segment": "dormant", "inactive_days": 60 },
  "sentiment_gate": false,
  "steps": [
    { "step": 1, "action": "offer_agent", "filter": "winback_offers_only" },
    { "step": 2, "action": "send_message", "template": "winback_we_miss_you" }
  ]
}
```

### `playbooks/post_purchase.json`
```json
{
  "name": "Post-purchase follow-up",
  "trigger": { "days_after_purchase": 3 },
  "sentiment_gate": false,
  "steps": [
    { "step": 1, "action": "cross_sell_agent", "input": "purchased_product" },
    { "step": 2, "action": "send_message", "template": "post_purchase_followup" }
  ]
}
```

---

## 9. Lookup Tables Reference

These files are your ground truth. The agent can only recommend what is in these files.

### `lookups/products.json`
```json
{
  "PROD_001": {
    "name": "Face Wash",
    "category": "skincare",
    "price": 299,
    "tier": "basic"
  },
  "PROD_045": {
    "name": "Moisturizer SPF 30",
    "category": "skincare",
    "price": 499,
    "tier": "mid"
  }
}
```

### `lookups/cross_sell_rules.json`
```json
{
  "PROD_001": {
    "product_name": "Face Wash",
    "suggest": ["PROD_045", "PROD_089"],
    "reason": "Customers who bought face wash commonly add moisturizer and toner"
  },
  "PROD_010": {
    "product_name": "Running Shoes",
    "suggest": ["PROD_022", "PROD_031"],
    "reason": "Socks and insoles are frequent add-ons"
  }
}
```

### `lookups/upsell_rules.json`
```json
{
  "PROD_001": {
    "product_name": "Face Wash",
    "upgrade_to": "PROD_100",
    "upgrade_name": "Premium Face Wash with Vitamin C",
    "price_difference": 200,
    "eligible_segments": ["repeat", "high_value"]
  }
}
```

### `lookups/offers.json`
```json
{
  "OFFER_001": {
    "name": "Welcome 15% off",
    "discount_percent": 15,
    "code": "WELCOME15",
    "eligible_segments": ["new"],
    "valid_until": "2025-12-31",
    "applicable_products": "all"
  },
  "OFFER_002": {
    "name": "VIP Bundle Deal",
    "discount_percent": 20,
    "code": "VIP20",
    "eligible_segments": ["high_value"],
    "valid_until": "2025-12-31",
    "applicable_products": ["PROD_045", "PROD_100"]
  }
}
```

### `lookups/segments.json`
```json
{
  "new":        { "max_orders": 1 },
  "repeat":     { "min_orders": 2, "max_orders": 9 },
  "high_value": { "min_orders": 10, "or_min_spend": 5000 },
  "dormant":    { "inactive_days": 60 }
}
```

### `lookups/message_templates.json`
```json
{
  "new_customer_welcome": "Hi {name}! 👋 Welcome! Since you tried {product_name}, you might love {suggestion}. Use code {offer_code} for {discount}% off!",
  "repeat_buyer_offer":   "Hi {name}! Great to hear from you. Customers who bought {product_name} also love {suggestion}. Special deal for you: {offer_text}",
  "vip_personalized":     "Hi {name}! As one of our valued customers, here's something exclusive: {suggestion} — {offer_text}",
  "winback_we_miss_you":  "Hi {name}! It's been a while. We'd love to have you back. Here's {discount}% off your next order: {offer_code}",
  "post_purchase_followup": "Hi {name}! Hope you're enjoying {product_name}. You might also like {suggestion} — pairs perfectly with it!",
  "send_empathy_template": "Hi {name}, thank you for reaching out. We're here to help — what can we do for you today?",
  "route_to_human":       "[HUMAN_AGENT_NEEDED] VIP customer with negative sentiment — {customer_id}"
}
```

---

## 10. Database Schema

### Table: `customers`
| Column | Type | Notes |
|---|---|---|
| id | TEXT (PK) | WhatsApp number or CRM ID |
| name | TEXT | |
| phone | TEXT | |
| segment | TEXT | new / repeat / high_value / dormant |
| rfm_recency | INTEGER | Days since last purchase |
| rfm_frequency | INTEGER | Total orders |
| rfm_monetary | REAL | Total spend |
| churn_risk | TEXT | low / medium / high |
| preferred_language | TEXT | For message generation |
| created_at | DATETIME | |
| updated_at | DATETIME | |

### Table: `agent_responses` (Replaces `conversations`)
*Note: Raw messages are kept in `meta engine db`. This table only stores our agent's output.*
| Column | Type | Notes |
|---|---|---|
| id | INTEGER (PK) | Auto-increment |
| customer_id | TEXT (FK) | References customers.id |
| meta_message_id | TEXT | Reference to message in meta engine db |
| parsed_intent | TEXT | JSON string from parser node |
| generated_response | TEXT | The final message generated by the LLM |
| created_at | DATETIME | |

### Table: `recommendations`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER (PK) | |
| customer_id | TEXT (FK) | |
| recommended_products | TEXT | JSON array of product IDs |
| offer_id | TEXT | |
| template_used | TEXT | |
| sent_at | DATETIME | |
| converted | BOOLEAN | Did customer purchase after this? |
| conversion_at | DATETIME | |

### Table: `purchases`
| Column | Type | Notes |
|---|---|---|
| id | INTEGER (PK) | |
| customer_id | TEXT (FK) | |
| product_id | TEXT | |
| amount | REAL | |
| purchased_at | DATETIME | |

---

## 11. Redis Cache Strategy

### What is cached

| Key pattern | Value | TTL | Reason |
|---|---|---|---|
| `profile:{customer_id}` | CustomerProfile JSON | 1 hour | Avoid DB hit per message |
| `segment:{customer_id}` | segment string | 1 hour | RFM calc is expensive |
| `offers:active` | list of active offer IDs | 30 min | Offers don't change often |
| `rules:cross_sell` | full cross_sell_rules.json | 6 hours | Static lookup |
| `conv_summary:{customer_id}` | last parsed summary | 15 min | Avoid re-parsing same conversation |

### Cache invalidation
- Customer makes a purchase → invalidate `profile:{customer_id}` and `segment:{customer_id}`
- Offer expires or is updated → invalidate `offers:active`
- New message arrives → invalidate `conv_summary:{customer_id}`

---

## 12. LLM Usage — Where & Why

Only two nodes call the LLM. Everything else is pure Python.

### Node 1 — Conversation Parser
**Why LLM:** Natural language understanding — extracting structured intent from free-form WhatsApp messages.
**Strict prompt:** Returns only a fixed JSON schema. Pydantic validates the output before it's used.
**Fallback:** If parsing fails or output is invalid → mark intent as "general", skip all specialist agents, send a polite reply.

### Node 2 — Supervisor (ReAct agent)
**Why LLM:** Needs to reason about customer context and decide routing. This is the only "thinking" step.
**Tools available to supervisor:** `get_customer_profile`, `get_conversation_summary`, `check_eligibility` — all return structured data from DB or cache. Supervisor cannot call cross-sell or product lookup directly.
**Strict prompt:** "You can only route to agents. You cannot make product recommendations. Your output must be a JSON list of agent names to call."

### Node 3 — Message Generator
**Why LLM:** Natural, human-sounding WhatsApp messages — templates alone feel robotic.
**Strict prompt:** "Fill the template ONLY with the provided data. Do not add products, prices, discounts, or claims not given to you."
**Fallback:** If generation fails → send raw template string as-is.

---

## 13. Additional Revenue Features

These are beyond cross-sell and up-sell — each directly increases revenue.

### A. Bundle Detector
If a customer mentions 2+ related products in one conversation → agent auto-suggests a bundle offer from `bundles.json`.
Purely lookup-based: you define which products bundle well. No prediction.

### B. Churn Alert + Win-back
RFM score drops below threshold → Celery scheduled task auto-triggers `dormant.json` playbook → sends win-back message with a discount.
No manual monitoring needed.

### C. Sentiment Gate
Before ANY offer is sent → sentiment check runs.
If `"negative"` → skip offer entirely → send empathy template OR route to human agent.
Prevents tone-deaf selling to frustrated customers.

### D. A/B Template Testing
Store which template variant was sent per customer.
After 30 days → compare conversion rates.
Auto-rotate to the winning variant via `config/settings.py` flag.

### E. Best Time to Send
From chat history → find the hour + day the customer typically responds.
Celery schedules the offer send for that window instead of instant.
Increases open rate without any extra cost.

### F. Post-Purchase Follow-up
3 days after a purchase → Celery auto-triggers `post_purchase.json`.
Asks for feedback + suggests a complementary product.
No manual tracking needed.

### G. Conversion Feedback Loop
When a customer purchases after receiving an offer → mark `recommendations.converted = true`.
Over time → see which cross-sell rules, offers, and templates actually convert.
Use this data to improve your `cross_sell_rules.json` and `offers.json`.

---

## 14. Build Sequence — Week by Week

### Week 1 — Foundation
- Set up folder structure and git repo
- `db/models.py` + `db/database.py` (SQLite + SQLAlchemy)
- `config/settings.py` (Pydantic Settings + .env)
- `cache/redis_client.py` (Redis helpers)
- Populate `lookups/` JSON files with your actual products and rules
- `scripts/seed_lookups.py`

### Week 2 — Core Skills
- `skills/rfm.py` — RFM calculator
- `skills/sentiment.py` — sentiment classifier
- `skills/cross_sell.py` — cross-sell lookup
- `skills/up_sell.py` — up-sell lookup
- `skills/offer_ranker.py` — offer ranker
- Write unit tests for all skills (`tests/test_skills.py`)
- Skills should pass tests with 0 LLM calls

### Week 3 — Agent Graph
- `agent/state.py` — AgentState TypedDict
- `agent/nodes/parser.py` — conversation parser (LLM)
- `agent/nodes/profiler.py` — profile builder (pure Python)
- `agent/nodes/supervisor.py` — ReAct supervisor (LLM)
- `agent/nodes/cross_sell.py`, `up_sell.py`, `offer_agent.py` — specialists
- `agent/nodes/aggregator.py` + `message_fill.py`
- `agent/graph.py` — wire everything together
- `config/prompts.py` — all prompts as constants

### Week 4 — API + Queue + Fetcher
- `api/main.py` — FastAPI app
- `api/fetcher.py` — Integration with Meta Engine DB to fetch messages
- `api/tasks.py` — Celery task: `process_message`
- `docker-compose.yml` — FastAPI + Celery + Redis
- Integration test: fetch a sample message from Meta Engine DB → verify full flow runs

### Week 5 — Testing with Real Data
- Feed 50–100 real historical conversations
- Check parser output accuracy
- Check cross-sell rule matching
- Tune `prompts.py` for your language/tone
- Tune `segments.json` thresholds for your customer base

### Week 6 — Additional Features
- `skills/timing.py` + Celery beat for scheduled sends
- A/B template tracking in `recommendations` table
- Churn alert scheduled job
- Post-purchase follow-up Celery task
- Sentiment gate tuning

---

## 15. Migration Path — SQLite to PostgreSQL

Zero application code change required. Only change the `DATABASE_URL` in `.env`:

```bash
# .env — now
DATABASE_URL=sqlite:///./conversations.db

# .env — later (just change this one line)
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/salesdb
```

SQLAlchemy handles everything else. Run Alembic migrations for schema creation on Postgres.

**When to migrate:** When SQLite write locks become a bottleneck. Typically above 200 concurrent Celery workers or 50,000+ conversation records. For 5,000 customers you likely have months before this is needed.

---

## 16. Environment & Config

### `.env.example`
```
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6

# Database
DATABASE_URL=sqlite:///./conversations.db

# Redis
REDIS_URL=redis://localhost:6379/0

# Meta Engine Database
META_ENGINE_DB_URL=postgresql://user:pass@host:5432/meta_engine

# Agent config
MAX_CONVERSATION_HISTORY=10
PROFILE_CACHE_TTL_SECONDS=3600
OFFERS_CACHE_TTL_SECONDS=1800
MAX_RECOMMENDATIONS=2
SENTIMENT_GATE_ENABLED=true
DORMANT_THRESHOLD_DAYS=60
POST_PURCHASE_FOLLOWUP_DAYS=3

# A/B Testing
AB_TESTING_ENABLED=false
AB_VARIANT_RATIO=0.5
```

### `config/settings.py`
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    anthropic_api_key: str
    anthropic_model: str = "claude-sonnet-4-6"
    database_url: str
    redis_url: str
    meta_engine_db_url: str
    max_conversation_history: int = 10
    profile_cache_ttl_seconds: int = 3600
    max_recommendations: int = 2
    sentiment_gate_enabled: bool = True
    dormant_threshold_days: int = 60
    post_purchase_followup_days: int = 3

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## Summary

| What | Decision |
|---|---|
| Framework | LangGraph — state machine maps to playbooks |
| LLM role | Parse conversation + supervisor routing + fill message |
| Recommendations | 100% from JSON lookup files — deterministic |
| Hallucination prevention | Tools are pure Python, Pydantic-validated output |
| Scale | Celery + Redis queue — handles 5000+ concurrent customers |
| DB now | SQLite |
| DB later | PostgreSQL — change one .env line |
| Cache | Redis — profile + active offers |
| First thing to build | Week 1: folder structure + DB models + lookup JSON files |
