# Part B: Alternative Agent Architectures

This document details the architectural blueprints for the three alternative growth engineering tracks not selected for active implementation in Part A:
- **Track 2: Review-Site Sentiment Agent**
- **Track 3: Multi-Tool Orchestration Agent**
- **Track 4: Funnel Measurement Agent**

Each proposal adheres strictly to the six required engineering specifications.

---

## 1. Track 2: Review-Site Sentiment Agent

### 1. Signal and Source
- **Data Sources:** Public B2B SaaS review platforms (G2, Capterra, Trustpilot, Software Advice) and community forums (Reddit r/eventplanning, r/conferencetech).
- **Ingestion Mechanism:** Scheduled headless HTTP scrapers with polite rate limiting (1 request per 3 seconds) and public review feed endpoints using ScraperAPI / BrightData residential proxies to avoid CAPTCHA blocks.
- **Refresh Cadence:** Weekly full sync (Saturday midnight UTC) with daily delta crawls targeting 1–3 star reviews for major competitors (Eventbrite, Cvent, Ticketmaster, Splashthat, Tito).
- **Volume:** ~250–400 negative competitor reviews captured globally per month.

### 2. Agent Decision Logic
- **Sentiment & Feature Extraction:** An LLM extracts:
  1. Primary complaint taxonomy: exorbitant per-ticket fees, forced third-party branding, withheld payout escrow, checkout abandonment, poor attendee data export.
  2. Reviewer profile verification: Confirms the reviewer is an event host/organizer rather than an attendee.
  3. Company domain extraction: Matches reviewer identity or organization against Apollo.io / Clearbit enrichment APIs.
- **Match Scoring:** Evaluates whether Ticmint's core architecture (white-label domain, direct Stripe payouts, 0% attendee hijack) directly resolves the reviewer's grievance.

### 3. Action Taken
- Drafts a highly contextual, grievance-specific comparison brief and cold outreach sequence addressed to the event organizer.
- Generates a "Competitive Battlecard" entry flagging trending weaknesses in competitor platforms to equip Ticmint's sales team.
- Stashes the enriched lead and review quote into HubSpot CRM under the `Competitor Churn Prospect` pipeline.

### 4. Human Approval Boundary
- **Mandatory Review:** The agent *never* sends automated outreach directly to reviewers. An SDR must verify company identity, review authentic quotation accuracy, and approve the email sequence in HubSpot before sending.
- **Autonomous Action:** The agent is permitted to auto-update competitive battlecard matrices and internal Slack alerts (`#intel-competitor-watch`).

### 5. Biggest Failure Mode
- **Reviewer Anonymity & Misattribution:** Many negative reviews are posted under pseudonyms (e.g., "Verified Reviewer - Mid-Market") or by attendees angry about ticket refunds rather than event producers. Misidentifying an attendee as an organizer or sending unsolicited cold outreach to an unrelated corporate domain damages brand reputation.
- **Mitigation:** Strict attribution confidence threshold (>= 0.85). If the organization cannot be verified via public records or domain matching, the record is flagged for market intelligence only and suppressed from outbound sales.

### 6. Estimated Monthly Cost
- **Scraper Proxies (BrightData / ScraperAPI):** $49/mo (50,000 requests)
- **Data Enrichment API (Apollo.io Basic):** $99/mo (1,000 enrichments)
- **LLM Reasoning (Gemini 2.5 Flash):** ~$8/mo (~400 reviews * 1.5k tokens)
- **Compute (GitHub Actions / Cloud Run):** Free tier / $5/mo
- **Total Production Cost:** **~$161/month**

---

## 2. Track 3: Multi-Tool Orchestration Agent

### 1. Signal and Source
- **Data Sources:** 
  1. Google Analytics 4 (Data API: daily sessions, traffic channel, landing page bounce rate).
  2. Google Search Console API (impressions, clicks, average position per query).
  3. Stripe API / Ticmint Database (checkout starts, completed registrations, Gross Merchandise Value, processing fees).
  4. HubSpot CRM / Cal.com (demo requests booked, sales pipeline velocity).
- **Ingestion Mechanism:** Asynchronous REST API consumers running on a centralized orchestrator via OAuth 2.0 service tokens.
- **Refresh Cadence:** Hourly incremental ingestion for transactions and demo bookings; daily snapshot at 02:00 UTC for search and analytics.

### 2. Agent Decision Logic
- **Cross-Funnel Stitching:** Joins disparate data sets on UTC date, campaign UTM parameters, and referral URLs:
  $$\text{CAC} = \frac{\text{Ad Spend (Google/Meta)}}{\text{New Organizers with }> \$1k\text{ GMV}}$$
- **Anomaly Detection:** Time-series z-score model evaluates 14-day rolling averages across key funnel steps. Flags anomalies if:
  - Checkout conversion drops $> 2.5\sigma$ while landing page traffic remains steady (indicates gateway or widget bug).
  - High-intent search clicks surge without corresponding demo requests (indicates landing page messaging disconnect).

### 3. Action Taken
- Compiles an executive Markdown & Slack digest every Monday at 08:00 UTC detailing funnel health, top-performing acquisition channels, and CAC:LTV trajectory.
- Automatically generates Looker Studio / Metabase data tables in BigQuery for leadership querying.
- Triggers high-priority PagerDuty / Slack alerts if checkout conversion drops below 15% during active event campaigns.

### 4. Human Approval Boundary
- **Autonomous Operations:** Reading read-only reporting APIs, data joining, warehousing into BigQuery, and posting Slack summaries.
- **Human Approval Required:** Modifying ad budgets, changing bidding strategies, updating CRM contact lifecycle stages, or pushing website changes.

### 5. Biggest Failure Mode
- **Attribution Breakage & Schema Drift:** UTM stripping in modern privacy browsers (iOS Safari Private Relay, Brave) combined with schema shifts in external APIs (e.g. GA4 dimension changes) leads to false attribution or broken pipelines.
- **Mitigation:** Strict dbt schema tests, fallback to first-party cookie session stitching, and automated reconciliation against Stripe source of truth.

### 6. Estimated Monthly Cost
- **Fivetran / Airbyte Cloud Connector:** Free tier / $60/mo
- **Google Cloud BigQuery Storage & Queries:** ~$15/mo
- **LLM Synthesis & Report Generation (Gemini 2.5 Flash):** ~$6/mo
- **Serverless Hosting (Cloud Run):** $10/mo
- **Total Production Cost:** **~$91/month**

---

## 3. Track 4: Funnel Measurement Agent

### 1. Signal and Source
- **Data Sources:** 
  1. Real browser user journeys via Playwright synthetic testing suite executed in headless Chromium.
  2. Production event tracking payloads (Segment, Google Tag Manager container, Meta Conversion API, PostHog events).
  3. Server-side purchase webhooks (Stripe `payment_intent.succeeded`).
- **Ingestion Mechanism:** Synthetic headless browser test runner simulating end-to-end organizer signup, event creation, ticket checkout, and receipt confirmation.
- **Refresh Cadence:** Synthetic checkout tests every 30 minutes; server-side tracking parity audits run every 4 hours.

### 2. Agent Decision Logic
- **Event Parity Audit:** Compares client-side JavaScript tracking events (`checkout_started`, `payment_info_entered`) against server-side Stripe transactions:
  $$\text{Tracking Discrepancy Rate} = \frac{|\text{Client Purchase Events} - \text{Stripe Succeeded Webhooks}|}{\text{Stripe Succeeded Webhooks}}$$
  If discrepancy exceeds 8% over a 2-hour window, the agent diagnoses ad-blocker suppression, browser cookie expiration, or broken tag firing.
- **Synthetic Test Evaluation:** Detects DOM selector shifts, slow API responses ($> 2.5$s on checkout widget), or broken iframe postMessage handlers.

### 3. Action Taken
- Pushes immediate error telemetry to Sentry and GitHub Issues with reproduction steps, HAR network logs, and screenshots of the broken checkout step.
- Posts real-time alert to Slack `#dev-alerts` specifying the exact broken script or attribution leakage point.
- Automatically logs tracking health scores to the internal Growth engineering dashboard.

### 4. Human Approval Boundary
- **Autonomous Operations:** Running synthetic browsers, listening to network traffic, logging anomalies, and filing GitHub triage tickets.
- **Human Approval Required:** Rolling back code deployments, modifying GTM tags in production, or toggling payment gateways.

### 5. Biggest Failure Mode
- **False-Positive Alert Fatigue:** Temporary CDN latency spikes, third-party payment gateway 3D-Secure redirects, or synthetic test network blips triggering critical alerts at 3 AM.
- **Mitigation:** Dual-confirmation rule: an alert is only triggered if two consecutive synthetic runs fail 5 minutes apart from distinct proxy IP locations.

### 6. Estimated Monthly Cost
- **Playwright Synthetic Test Runner (Cloud Run Jobs / Modal):** ~$35/mo (running 48 checks/day)
- **Proxy Network for Synthetic Browsers:** $20/mo
- **Sentry Error Monitoring (Developer Plan):** Free / $26/mo
- **LLM Root Cause Analyzer (Gemini 2.5 Flash):** ~$4/mo
- **Total Production Cost:** **~$85/month**
