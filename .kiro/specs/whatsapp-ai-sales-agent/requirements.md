# Requirements Document

## Introduction

The WhatsApp AI Sales Agent is a configuration-driven analytical system that ingests stored WhatsApp conversation data, applies user-defined skills, playbooks, lookups, and formulas to extract actionable sales intelligence, and delivers recommendations to human sales agents. The system strictly operates within the boundaries of user-provided configuration — it does not make autonomous predictions, hallucinate product knowledge, or take actions outside its defined instruction set. Its primary goal is to improve sales outcomes through cross-selling, up-selling, offer targeting, churn prevention, sentiment-aware prioritization, purchase intent scoring, customer segmentation, re-engagement campaigns, and outreach timing optimization.

---

## Glossary

- **Agent**: The WhatsApp AI Sales Agent system described in this document.
- **Conversation**: A stored WhatsApp message thread between a business and a single customer contact.
- **Message**: An individual text, media, or structured message within a Conversation.
- **Conversation_Store**: The persistent data layer where all WhatsApp Conversations and Messages are stored.
- **Skill**: A named, user-defined unit of analytical capability (e.g., "DetectChurnRisk", "ScorePurchaseIntent") that the Agent can execute.
- **Playbook**: A user-defined sequential or conditional workflow that chains Skills together for a specific sales scenario.
- **Lookup**: A user-defined reference table or key-value map that the Agent consults to resolve product names, categories, pricing tiers, or customer segments.
- **Formula**: A user-defined deterministic expression or scoring function used to calculate a numeric output (e.g., intent score, churn risk score) from conversation attributes.
- **Instruction_Set**: The complete collection of Skills, Playbooks, Lookups, and Formulas configured by the user that governs Agent behavior.
- **Recommendation**: An actionable suggestion produced by the Agent for a human sales agent, strictly derived from the Instruction_Set.
- **Grounded_Output**: Any Agent output that is fully traceable to a specific Skill, Playbook, Lookup, or Formula in the Instruction_Set — never autonomously inferred.
- **Hallucination**: Any Agent output that cannot be traced to the Instruction_Set; such outputs are prohibited.
- **Cross_Sell_Opportunity**: A Recommendation for a product or service complementary to a customer's known purchases, as defined in a Lookup.
- **Up_Sell_Opportunity**: A Recommendation for a higher-tier or premium version of a product the customer already uses or has expressed interest in, as defined in a Lookup.
- **Offer**: A promotion, discount, bundle, or special price defined in a Lookup and matched to a customer via a Playbook.
- **Churn_Risk_Score**: A numeric value produced by a Formula indicating the likelihood a customer will disengage, based on conversation pattern attributes.
- **Sentiment_Score**: A numeric value produced by a Formula measuring the positivity or negativity of a customer's recent messages.
- **Intent_Score**: A numeric value produced by a Formula indicating the likelihood a customer will make a purchase.
- **Segment**: A named customer group defined in a Lookup, assigned by the Agent based on Formula outputs.
- **Dormant_Customer**: A customer whose last Conversation occurred beyond a user-configured inactivity threshold.
- **Outreach_Window**: A time range recommended for contacting a specific customer, calculated by a Formula.
- **Dashboard**: The reporting interface that surfaces aggregated insights, Recommendation summaries, and performance metrics.
- **Sales_Agent**: The human operator who receives and acts on Agent Recommendations.
- **Audit_Log**: An immutable record linking every Agent output to the specific Instruction_Set element that produced it.

---

## Requirements

---

### Requirement 1: Conversation Ingestion and Indexing

**User Story:** As a Sales_Agent, I want the Agent to continuously read from the Conversation_Store so that all stored WhatsApp conversations are available for analysis without manual import.

#### Acceptance Criteria

1. THE Agent SHALL connect to the Conversation_Store using user-configured connection credentials.
2. WHEN a new Conversation or Message is written to the Conversation_Store, THE Agent SHALL ingest the new data within 5 minutes of its availability.
3. THE Agent SHALL index each Message with the following fields: contact identifier, message timestamp, message direction (inbound/outbound), and message content.
4. IF the Conversation_Store is temporarily unavailable, THEN THE Agent SHALL retry the connection at user-configured intervals and resume ingestion from the last successfully processed position upon reconnection.
5. THE Agent SHALL support batch ingestion of historical Conversations from the Conversation_Store on initial setup.
6. WHEN a Message contains media (image, audio, document) without a text transcription, THE Agent SHALL record the media type and skip content-level analysis for that Message, logging the skip in the Audit_Log.
7. THE Agent SHALL deduplicate Messages using a unique message identifier so that the same Message is not analyzed more than once.

---

### Requirement 2: Instruction_Set Management

**User Story:** As a Sales_Agent, I want to define and manage Skills, Playbooks, Lookups, and Formulas through a configuration interface so that I fully control what the Agent is allowed to analyze and recommend.

#### Acceptance Criteria

1. THE Agent SHALL provide an interface for the user to create, edit, activate, deactivate, and delete Skills, Playbooks, Lookups, and Formulas.
2. WHEN a Skill, Playbook, Lookup, or Formula is saved, THE Agent SHALL validate its syntax and structure before making it active.
3. IF a Skill, Playbook, Lookup, or Formula contains a syntax error or references an undefined dependency, THEN THE Agent SHALL reject the save operation and return a descriptive validation error identifying the invalid element.
4. THE Agent SHALL version each element of the Instruction_Set, retaining at least the 10 most recent versions per element.
5. WHEN the user deactivates a Skill, Playbook, Lookup, or Formula, THE Agent SHALL immediately stop applying it to new analyses without affecting previously generated Recommendations.
6. THE Agent SHALL allow the user to define a Lookup as a static key-value table or as a reference to an external file in CSV or JSON format.
7. THE Agent SHALL allow the user to define a Formula using a restricted expression language that supports arithmetic operators, comparison operators, boolean operators, and references to indexed Message fields and Lookup values.
8. WHEN a Formula references a Lookup key that does not exist in the active Lookup, THEN THE Agent SHALL treat the missing value as null and log the resolution gap in the Audit_Log.

---

### Requirement 3: Guardrails and Non-Hallucination Enforcement

**User Story:** As a Sales_Agent, I want every Agent output to be fully traceable to a specific element of the Instruction_Set so that I can trust that the Agent never invents or assumes information beyond what I have configured.

#### Acceptance Criteria

1. THE Agent SHALL only produce Recommendations and analysis outputs that are derivable from the active Instruction_Set.
2. WHEN producing a Recommendation, THE Agent SHALL attach a provenance record identifying the Skill, Playbook, Lookup, or Formula that produced it.
3. IF no active Skill, Playbook, or Formula applies to a Conversation, THEN THE Agent SHALL produce no output for that Conversation and record a no-match event in the Audit_Log.
4. THE Agent SHALL not use any large language model inference, external AI service, or statistical generalization to produce Recommendations unless the user has explicitly defined and activated a Skill that invokes such a service with a user-controlled prompt template.
5. WHERE an external AI service Skill is configured, THE Agent SHALL pass only conversation data explicitly listed in the Skill definition to that service, and SHALL include the service response verbatim in the Audit_Log alongside the prompt used.
6. THE Agent SHALL expose an Audit_Log query interface that allows the user to retrieve the full derivation chain for any Recommendation by Recommendation identifier.
7. WHEN the Instruction_Set is modified, THE Agent SHALL tag all subsequent Recommendations with the active Instruction_Set version so that outputs can be compared across configuration changes.

---

### Requirement 4: Cross-Sell Recommendation Engine

**User Story:** As a Sales_Agent, I want the Agent to identify cross-sell opportunities for each customer based on their conversation history and my defined product relationship Lookups so that I can offer complementary products at the right moment.

#### Acceptance Criteria

1. THE Agent SHALL evaluate each Conversation against the active cross-sell Playbook to identify Cross_Sell_Opportunities.
2. WHEN a customer's Conversation references a product or service matching a key in the cross-sell Lookup, THE Agent SHALL identify all associated complementary products defined in that Lookup entry.
3. THE Agent SHALL exclude from Cross_Sell_Opportunities any product that already appears as purchased or confirmed in the same customer's Conversation history, as determined by keyword patterns defined in the relevant Skill.
4. WHEN a Cross_Sell_Opportunity is identified, THE Agent SHALL produce a Recommendation containing: the customer contact identifier, the triggering product, the recommended complementary product, and the provenance record.
5. THE Agent SHALL rank multiple Cross_Sell_Opportunities for the same customer using a user-defined Formula that weights recency of mention and frequency of mention.
6. IF the cross-sell Lookup is empty or deactivated, THEN THE Agent SHALL produce no cross-sell Recommendations and log a configuration gap notice in the Audit_Log.

---

### Requirement 5: Up-Sell Recommendation Engine

**User Story:** As a Sales_Agent, I want the Agent to identify up-sell opportunities based on conversation signals and my defined product tier Lookups so that I can propose premium upgrades to customers who are ready for them.

#### Acceptance Criteria

1. THE Agent SHALL evaluate each Conversation against the active up-sell Playbook to identify Up_Sell_Opportunities.
2. WHEN a customer's Conversation contains signals matching patterns defined in the up-sell Skill (e.g., price inquiry, volume inquiry, feature inquiry), THE Agent SHALL look up the next product tier in the up-sell Lookup.
3. THE Agent SHALL only recommend an upgrade tier that exists as an explicit entry in the up-sell Lookup; THE Agent SHALL not infer or extrapolate tiers beyond the Lookup contents.
4. WHEN an Up_Sell_Opportunity is identified, THE Agent SHALL produce a Recommendation containing: the customer contact identifier, the current product or tier, the recommended upgrade, the triggering signal text, and the provenance record.
5. THE Agent SHALL apply a user-defined Formula to score each Up_Sell_Opportunity before surfacing it, and SHALL only surface Recommendations whose score meets or exceeds a user-configured minimum threshold.
6. IF the up-sell Lookup is empty or deactivated, THEN THE Agent SHALL produce no up-sell Recommendations and log a configuration gap notice in the Audit_Log.

---

### Requirement 6: Offer and Promotion Targeting

**User Story:** As a Sales_Agent, I want the Agent to match customers to relevant offers and promotions based on their conversation behavior and my defined offer Lookups so that I can send targeted promotions with higher conversion likelihood.

#### Acceptance Criteria

1. THE Agent SHALL evaluate each active Offer in the Offer Lookup against each customer's Conversation profile to determine eligibility.
2. WHEN a customer's Conversation attributes satisfy the eligibility conditions defined in the Offer entry, THE Agent SHALL generate a targeted Offer Recommendation for that customer.
3. THE Agent SHALL support eligibility conditions based on: product mentions, Segment membership, Intent_Score range, Sentiment_Score range, and last interaction recency.
4. WHEN an Offer has an expiry date configured, THE Agent SHALL cease generating Recommendations for that Offer after the expiry date.
5. THE Agent SHALL not recommend the same Offer to the same customer more than a user-configured maximum number of times within a user-configured time window.
6. WHEN multiple Offers are eligible for the same customer, THE Agent SHALL rank them using a user-defined Formula and surface only the top N Offers, where N is user-configured.

---

### Requirement 7: Churn Risk Detection

**User Story:** As a Sales_Agent, I want the Agent to calculate a Churn_Risk_Score for each customer based on conversation patterns and my defined Formula so that I can proactively engage at-risk customers before they disengage.

#### Acceptance Criteria

1. THE Agent SHALL calculate a Churn_Risk_Score for each customer using the user-defined churn risk Formula applied to conversation attributes.
2. THE churn risk Formula SHALL support input variables including: days since last inbound message, number of messages in the last 30 days, Sentiment_Score trend direction, and number of unresolved complaint keywords detected.
3. WHEN a customer's Churn_Risk_Score meets or exceeds a user-configured alert threshold, THE Agent SHALL generate a churn risk Recommendation for the Sales_Agent.
4. THE churn risk Recommendation SHALL contain: the customer contact identifier, the Churn_Risk_Score, the Formula input values that drove the score, and the provenance record.
5. THE Agent SHALL recalculate each customer's Churn_Risk_Score after each new Message is ingested.
6. IF the churn risk Formula is deactivated, THEN THE Agent SHALL produce no churn risk Recommendations and log a configuration gap notice in the Audit_Log.

---

### Requirement 8: Sentiment Analysis and Follow-Up Prioritization

**User Story:** As a Sales_Agent, I want the Agent to compute a Sentiment_Score for each customer's recent messages using my defined Formula so that I can prioritize follow-ups with dissatisfied or at-risk customers first.

#### Acceptance Criteria

1. THE Agent SHALL compute a Sentiment_Score for each customer by applying the user-defined sentiment Formula to the most recent N inbound messages, where N is user-configured.
2. THE sentiment Formula SHALL support keyword-based scoring using a user-defined Lookup that maps keywords or phrases to positive, neutral, or negative numeric weights.
3. WHEN a customer's Sentiment_Score falls below a user-configured negative threshold, THE Agent SHALL flag the customer for priority follow-up and generate a sentiment alert Recommendation.
4. THE sentiment alert Recommendation SHALL contain: the customer contact identifier, the Sentiment_Score, the keywords that contributed most to the score, and the provenance record.
5. THE Agent SHALL display customers sorted by Sentiment_Score on the Dashboard so that the most negative scores appear at the top of the follow-up queue.
6. THE Agent SHALL update each customer's Sentiment_Score after each new inbound Message is ingested.

---

### Requirement 9: Purchase Intent Scoring

**User Story:** As a Sales_Agent, I want the Agent to score each customer's purchase intent using my defined Formula and keyword Lookups so that I can focus outreach efforts on customers most likely to convert.

#### Acceptance Criteria

1. THE Agent SHALL calculate an Intent_Score for each customer using the user-defined intent Formula applied to conversation attributes.
2. THE intent Formula SHALL support input variables including: frequency of product inquiry keywords, frequency of pricing inquiry keywords, frequency of availability inquiry keywords, and number of outbound Offer messages sent without a negative response.
3. THE Agent SHALL resolve product inquiry keywords, pricing inquiry keywords, and availability inquiry keywords exclusively from user-defined Lookups; THE Agent SHALL not infer intent signals beyond defined Lookup entries.
4. WHEN a customer's Intent_Score meets or exceeds a user-configured high-intent threshold, THE Agent SHALL generate a high-intent Recommendation flagging the customer for immediate Sales_Agent contact.
5. THE high-intent Recommendation SHALL contain: the customer contact identifier, the Intent_Score, the top contributing keyword matches, and the provenance record.
6. THE Agent SHALL recalculate each customer's Intent_Score after each new Message is ingested.

---

### Requirement 10: Customer Segmentation

**User Story:** As a Sales_Agent, I want the Agent to automatically assign each customer to a Segment based on their conversation behavior and my defined segmentation Formulas and Lookups so that I can apply Segment-specific Playbooks and Offers.

#### Acceptance Criteria

1. THE Agent SHALL assign each customer to exactly one active Segment by evaluating the user-defined segmentation Playbook.
2. THE segmentation Playbook SHALL evaluate each Segment's eligibility conditions in a user-defined priority order, assigning the first matching Segment.
3. THE Agent SHALL resolve Segment names and eligibility thresholds exclusively from the Segment Lookup; THE Agent SHALL not create or infer Segments beyond the Lookup contents.
4. WHEN a customer's Segment assignment changes due to new conversation data, THE Agent SHALL record the previous Segment, the new Segment, the timestamp of the change, and the Formula input values that caused the change in the Audit_Log.
5. THE Agent SHALL make each customer's current Segment available as an input variable to all other active Formulas and Playbooks.
6. IF no Segment eligibility condition matches a customer, THEN THE Agent SHALL assign the customer to a user-configured default Segment.

---

### Requirement 11: Re-engagement Campaign Targeting

**User Story:** As a Sales_Agent, I want the Agent to identify Dormant_Customers and recommend re-engagement actions using my defined Playbooks so that I can revive lapsed customer relationships.

#### Acceptance Criteria

1. THE Agent SHALL classify a customer as a Dormant_Customer when the number of days since their last inbound Message exceeds a user-configured inactivity threshold.
2. WHEN a customer is classified as a Dormant_Customer, THE Agent SHALL evaluate the active re-engagement Playbook and generate a re-engagement Recommendation.
3. THE re-engagement Recommendation SHALL contain: the customer contact identifier, the number of days since last inbound Message, the recommended re-engagement action or message template identifier from the re-engagement Lookup, and the provenance record.
4. THE Agent SHALL not generate more than one re-engagement Recommendation per customer per user-configured re-engagement cooldown period.
5. WHEN a Dormant_Customer sends a new inbound Message, THE Agent SHALL remove the Dormant_Customer classification and cancel any pending re-engagement Recommendations for that customer.
6. IF the re-engagement Lookup contains no applicable templates for a customer's Segment, THEN THE Agent SHALL log a configuration gap notice and produce no re-engagement Recommendation for that customer.

---

### Requirement 12: Optimal Outreach Timing

**User Story:** As a Sales_Agent, I want the Agent to recommend the best time window to contact each customer based on their historical message activity patterns and my defined timing Formula so that my outreach achieves higher response rates.

#### Acceptance Criteria

1. THE Agent SHALL calculate an Outreach_Window for each customer by applying the user-defined timing Formula to the customer's historical inbound message timestamps.
2. THE timing Formula SHALL derive the Outreach_Window from the distribution of hours and days in which the customer has historically sent inbound messages, using statistical aggregates (mean, mode, or percentile) as specified by the user in the Formula definition.
3. THE Agent SHALL express the Outreach_Window as a day-of-week and hour-of-day range in the user-configured timezone.
4. WHEN a Sales_Agent views a customer's Recommendation list, THE Agent SHALL display the customer's current Outreach_Window alongside each Recommendation.
5. THE Agent SHALL recalculate each customer's Outreach_Window weekly or when a user-configured minimum number of new inbound messages have been received, whichever occurs first.
6. IF a customer has fewer inbound messages than a user-configured minimum sample size, THEN THE Agent SHALL display a "Insufficient data" indicator instead of an Outreach_Window.

---

### Requirement 13: Reporting and Insights Dashboard

**User Story:** As a Sales_Agent, I want a Dashboard that shows aggregated sales intelligence, Recommendation summaries, and performance metrics so that I can track the Agent's impact and make informed decisions.

#### Acceptance Criteria

1. THE Dashboard SHALL display a list of all pending Recommendations sorted by a user-configured priority attribute (Churn_Risk_Score, Intent_Score, Sentiment_Score, or Recommendation creation timestamp).
2. THE Dashboard SHALL display, for each customer, their current Segment, Churn_Risk_Score, Sentiment_Score, Intent_Score, and Outreach_Window in a single customer detail view.
3. THE Dashboard SHALL display aggregate metrics including: total Recommendations generated in a user-selected time range, Recommendations by type (cross-sell, up-sell, offer, churn risk, re-engagement, high-intent), and Recommendations marked as acted upon by Sales_Agents.
4. WHEN a Sales_Agent marks a Recommendation as acted upon, THE Dashboard SHALL record the action timestamp and the Sales_Agent identifier against that Recommendation.
5. THE Dashboard SHALL allow the user to filter the Recommendation list by Segment, Recommendation type, Churn_Risk_Score range, Intent_Score range, Sentiment_Score range, and date range.
6. THE Dashboard SHALL display a configuration health panel showing which Skills, Playbooks, Lookups, and Formulas are active and which have logged configuration gap notices in the last 7 days.
7. THE Dashboard SHALL refresh displayed data at a user-configured interval between 1 minute and 60 minutes.

---

### Requirement 14: Audit and Traceability

**User Story:** As a Sales_Agent, I want a complete and queryable Audit_Log for every Agent action and output so that I can verify compliance, diagnose issues, and demonstrate that no Hallucination has occurred.

#### Acceptance Criteria

1. THE Agent SHALL write an entry to the Audit_Log for every event including: Message ingestion, Skill execution, Formula evaluation, Recommendation generation, Recommendation delivery to Dashboard, Recommendation acted-upon marking, configuration gap notices, and Instruction_Set version changes.
2. EACH Audit_Log entry SHALL contain: a unique entry identifier, a UTC timestamp, the event type, the customer contact identifier (where applicable), the Instruction_Set version active at the time of the event, and the full input and output values of the event.
3. THE Audit_Log SHALL be append-only; existing entries SHALL NOT be modified or deleted through any user interface.
4. THE Agent SHALL retain Audit_Log entries for a minimum of 12 months.
5. WHEN the user queries the Audit_Log by Recommendation identifier, THE Agent SHALL return the complete derivation chain from raw Message data through each Skill, Formula, or Lookup evaluation to the final Recommendation.
6. THE Agent SHALL expose Audit_Log data in a structured, exportable format (JSON or CSV) for external compliance review.

---

### Requirement 15: Access Control and Data Privacy

**User Story:** As a Sales_Agent administrator, I want role-based access controls and data handling policies so that customer conversation data is protected and access to sensitive configurations is restricted.

#### Acceptance Criteria

1. THE Agent SHALL enforce user authentication before granting access to any interface, Dashboard view, or Audit_Log query.
2. THE Agent SHALL support at least two roles: Administrator (full access to Instruction_Set management, Audit_Log export, and configuration) and Analyst (read-only access to Dashboard, Recommendations, and Audit_Log queries).
3. WHEN an Analyst attempts to create, edit, or delete a Skill, Playbook, Lookup, or Formula, THE Agent SHALL deny the operation and return an authorization error.
4. THE Agent SHALL not display raw Message content in the Dashboard or Recommendation views beyond a user-configured excerpt length, measured in characters.
5. THE Agent SHALL store all conversation data and Audit_Log entries at rest using encryption with a user-managed key.
6. WHEN a user requests deletion of a customer's data, THE Agent SHALL remove all stored Messages and Recommendations for that customer and record the deletion event in the Audit_Log without exposing deleted content.
