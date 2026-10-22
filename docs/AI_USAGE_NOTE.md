# AI Usage & Governance Note

This candid audit details how AI tools (Google Gemini 2.5 Flash / Claude) were utilized during the development of the Ticmint Growth Intelligence Agent, what was engineered and validated manually, initial failures detected during development, and the programmatic guardrails introduced to enforce reliable production behavior.

---

## 1. What AI Generated or Accelerated

* **Boilerplate Acceleration:** LLMs accelerated drafting initial Pydantic schema declarations (`RawSignal`, `SignalAnalysis`, `ScoreBreakdown`) and synthetic ground-truth test scenarios based on real event-industry forum posts.
* **Semantic Analysis & Classification:** In the production pipeline, the Gemini 2.5 Flash API is used to perform structured JSON extraction on unstructured forum discussions, classifying nuanced complaints (e.g. distinguishing between payout delays vs. checkout abandonment).
* **Contextual Outreach Drafting:** Generative models produced the initial wording for personalized cold drafts referencing exact complaint excerpts extracted from raw signals.

---

## 2. What Was Implemented and Verified Manually

* **MCP 2.x Architecture & Server Implementation:** The custom MCP server (`app/mcp_server.py`) and the `stdio_client` / `ClientSession` agent orchestration runner (`app/agent.py`) were manually designed and verified against the official Python MCP 2.x SDK specification.
* **Deterministic Scoring Rubric & Rules:** The 100-point transparent scoring algorithm (`app/scoring.py`) was manually constructed with explicit weights (Pain: 0–30, Intent: 0–25, ICP: 0–25, Recency: 0–10, Evidence: 0–10) rather than allowing an LLM to invent arbitrary scores.
* **Idempotency & Sheets Architecture:** The SHA256 deterministic key generation, column mapping, row preservation logic (protecting human review status and first-seen dates), and local offline JSON/CSV storage failover were hand-engineered and tested.
* **Test Suite & Benchmark Audit:** Built and ran an 18-test pytest suite and an empirical 32-record precision benchmark script (`data/evaluate_precision.py`).

---

## 3. Where AI Initially Gave an Incorrect or Unsupported Result

1. **Failure to Distinguish Ticket Buyers vs. Event Organizers:**
   - *Initial AI Defect:* In early iterations, prompt-based classification flagged music fans complaining about Ticketmaster/Live Nation concert ticket prices and dynamic pricing as "High-Priority Leads".
   - *Business Impact:* A fan buying concert tickets is a consumer, not a B2B buyer for Ticmint's white-label ticketing software. Treating them as a sales lead wastes SDR time.
2. **Hallucination of Organizer Metrics in Outreach Drafts:**
   - *Initial AI Defect:* The LLM occasionally invented details not present in the source text, such as: *"I saw you're planning an event for 5,000 people next month with a $20,000 budget..."*
   - *Business Impact:* Fabricating prospect details destroys credibility and trust in cold outreach.
3. **Misclassifying IT / Transit Tickets:**
   - *Initial AI Defect:* Posts discussing Kerberos / JWT microservice "tickets" or airline tickets were occasionally flagged as event registration discussions due to keyword collision on the word "ticket".

---

## 4. Programmatic Checks Added to Prevent Recurrence

* **Hard Suppression Rule Layer (`app/scoring.py`):**
  - Added deterministic regex suppression for non-event keywords (`parking ticket`, `airline ticket`, `jwt ticket`, `zendesk`, `support ticket`, `board game`).
  - Added regex filters disqualifying ticket buyers/fans (`bought a ticket`, `tried to buy`, `virtual queue`) unless the text explicitly contains organizer self-identification (`we host`, `our conference`, `we organize`, `our agency`).
* **Evidence Grounding Validator:**
  - Added strict algorithmic validation ensuring that the `evidence_quote` extracted by the LLM is a literal, verbatim substring of the raw source text before awarding evidence points ($+6$ bonus points).
* **Enterprise ICP Priority Gating:**
  - Enforced a rule requiring `buyer_fit == BuyerFit.HIGH` (verified conference, agency, or festival host) for any lead to enter the `HIGH` priority tier ($\ge 75$), ensuring smaller workshop hosts or casual meetups remain in the `MEDIUM` nurture tier.
* **Strict Anti-Hallucination Prompt Directives:**
  - Explicit system instructions forbidding the synthesis of company sizes, budgets, or contact information, with bounded fallback to standard technical value propositions.
