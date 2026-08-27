---
name: profiler
description: >-
  Analyzes customer purchase history to calculate RFM (Recency, Frequency, Monetary)
  scores and assign lifecycle segments.
---

# Customer Profiler Skill

This skill calculates the RFM score and segment for a customer based on their purchase history.
It is implemented purely in Python to ensure accurate mathematical calculations, rather than using an LLM.

## Segmentation Rules
- **dormant**: No purchases in the last 60 days
- **high_value**: Total spend > $5000 or frequency > 10
- **repeat**: Frequency > 1
- **new**: First time purchaser
