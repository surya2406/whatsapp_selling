# Cross-Sell Workflow Reference

## Sentiment Rules
- If customer message contains: "refund", "damage", "broken", "terrible", "worst" → **negative**
  → Skip all product recommendations. Use `general_reply` template with empathy.
- If message contains: "love", "great", "amazing", "happy", "good" → **positive**
  → Proceed with cross-sell recommendation.
- Otherwise → **neutral** → Proceed normally.

## Segment → Playbook Mapping
| Segment      | Playbook File              | Message Tone          |
|-------------|----------------------------|-----------------------|
| new          | playbooks/new_customer.json | Welcoming, discovery  |
| repeat       | playbooks/repeat_buyer.json | Friendly, loyalty     |
| high_value   | playbooks/high_value.json   | VIP, exclusive        |
| dormant      | playbooks/dormant.json      | Win-back, miss you    |

## Message Template Keys
| Situation                   | Template Key             |
|-----------------------------|--------------------------|
| Has cross-sell suggestions  | `cross_sell_only`        |
| New customer                | `new_customer_welcome`   |
| VIP customer with recs      | `vip_personalized`       |
| Dormant / win-back          | `winback_we_miss_you`    |
| Complaint / general         | `general_reply`          |

## Anti-Hallucination Rule
**CRITICAL:** Only recommend products that appear in `lookups/cross_sell_rules.json`
under the customer's `last_purchased_product` key. Never invent product IDs.

## Price Formatting
- Always show price as `₹{price}` (Indian Rupee symbol).
- Example: "Moisturizer SPF 30 — ₹499"
