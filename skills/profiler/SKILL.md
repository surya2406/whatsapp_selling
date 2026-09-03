---
name: profiler
description: >-
  Analyzes customer purchase history to calculate RFM (Recency, Frequency, Monetary)
  scores and assign lifecycle segments.
---

# Customer Profiler Skill

This skill calculates the RFM score and segment for a customer based on their purchase history synced from the `orders` table.
It is implemented purely in Python to ensure accurate mathematical calculations, rather than using an LLM.

## Segmentation Rules (Calibrated for B2B Welding Domain)
- **dormant**: No purchases in the last 120 days (project-based purchasing cycle)
- **high_value**: Total spend >= ₹50,000 or frequency >= 10 orders
- **repeat**: Frequency >= 2 orders
- **new**: First time purchaser (<= 1 order)

