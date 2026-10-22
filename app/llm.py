"""
LLM Reasoning Engine for Ticmint Growth Agent.
Integrates with Google Gemini API for structured classification, pain point extraction,
and evidence-grounded outreach drafting. Includes a robust deterministic heuristic fallback.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional
from app.config import config
from app.models import (
    BuyerFit,
    ComplaintCategory,
    IntentCategory,
    RawSignal,
    SignalAnalysis,
)

logger = logging.getLogger("ticmint.llm")


ANALYSIS_SYSTEM_PROMPT = """You are an expert B2B Growth Engineer and Lead Qualification Specialist for Ticmint.
Ticmint is a white-label event ticketing and registration platform that provides:
1. Complete brand ownership (custom domains, custom checkout CSS, zero third-party branding)
2. Direct payment payouts via organizer's Stripe/merchant account (zero escrow delays)
3. 100% attendee data ownership (no marketing to your attendees, full CSV/webhook exports)
4. Ultra-low, transparent fee structure compared to Eventbrite or legacy vendors.

Analyze the provided public discussion snippet and answer these 5 critical questions:
1. Is this actually about organising or hosting an event?
2. Is there a specific problem with the current ticketing or registration process?
3. Is the person or organisation a plausible customer for a white-label ticketing platform?
4. How strong is the evidence of intent to change or evaluate alternatives?
5. What relevant, non-generic outreach would be appropriate?

STRICT RULES FOR OUTREACH DRAFTING:
- Reference the EXACT complaint or words used in the post.
- Connect their specific pain directly to Ticmint's capability (e.g. white-label custom domain, direct Stripe payouts, attendee data ownership).
- DO NOT invent facts, fake company names, revenue numbers, or imaginary email addresses.
- If the post is irrelevant or an attendee complaining about ticket prices, set is_event_related to false, has_ticketing_pain to false, and leave outreach_draft empty.

Return ONLY a valid JSON object matching this exact schema:
{
  "is_event_related": boolean,
  "has_ticketing_pain": boolean,
  "complaint_category": "fees_extortion" | "branding_limitation" | "data_lockin" | "checkout_conversion" | "integrations_apis" | "payment_payout_delays" | "general_event_tech" | "none",
  "intent": "evaluating_alternatives" | "sharing_frustration" | "seeking_feedback" | "building_in_house" | "informational" | "not_event_related",
  "buyer_fit": "high" | "medium" | "low" | "unknown",
  "evidence_quote": "Exact verbatim words from the snippet representing the problem",
  "reasoning": "Clear, defensible explanation of why this is or isn't a qualified growth opportunity",
  "outreach_draft": "Concise, professional, non-pushy message specifically addressing their cited issue",
  "needs_human_review": true
}
"""


class LLMAnalyzer:
    """Analyzes raw public signals using Google Gemini or deterministic fallback rules."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model = model or config.GEMINI_MODEL
        self._client = None
        if self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning("Could not initialize google-genai client: %s. Using heuristic fallback.", e)

    def analyze_signal(self, signal: RawSignal) -> SignalAnalysis:
        """
        Analyzes a signal. Uses Gemini API if configured; otherwise gracefully
        falls back to deterministic heuristic pattern analysis.
        """
        if self._client:
            try:
                return self._analyze_with_gemini(signal)
            except Exception as e:
                logger.error("Gemini API error on signal %s: %s. Falling back to heuristic analyzer.", signal.source_id, e)

        return self._analyze_heuristic(signal)

    def _analyze_with_gemini(self, signal: RawSignal) -> SignalAnalysis:
        prompt = f"""
SOURCE: {signal.source}
AUTHOR: {signal.author}
TITLE: {signal.title or 'N/A'}
URL: {signal.url}
TEXT:
{signal.text}

Analyze this signal now and return ONLY the JSON object.
"""
        response = self._client.models.generate_content(
            model=self.model,
            contents=[ANALYSIS_SYSTEM_PROMPT, prompt],
        )

        raw_response = response.text.strip()
        # Strip markdown code blocks if wrapped by model
        if raw_response.startswith("```"):
            raw_response = re.sub(r"^```(?:json)?\s*", "", raw_response)
            raw_response = re.sub(r"\s*```$", "", raw_response)

        data = json.loads(raw_response)

        return SignalAnalysis(
            is_event_related=bool(data.get("is_event_related", False)),
            has_ticketing_pain=bool(data.get("has_ticketing_pain", False)),
            complaint_category=ComplaintCategory(data.get("complaint_category", "none")),
            intent=IntentCategory(data.get("intent", "informational")),
            buyer_fit=BuyerFit(data.get("buyer_fit", "unknown")),
            evidence_quote=str(data.get("evidence_quote", "")).strip(),
            reasoning=str(data.get("reasoning", "")).strip(),
            outreach_draft=str(data.get("outreach_draft", "")).strip(),
            needs_human_review=True,
        )

    def _analyze_heuristic(self, signal: RawSignal) -> SignalAnalysis:
        """
        Deterministic, rule-based fallback analyzer.
        Extracts verbatim quotes, classifies pain, and generates evidence-grounded outreach.
        """
        text = signal.text
        title = signal.title or ""
        combined = f"{title} {text}".lower()

        # 1. Check for negative non-event indicators (support ticketing, airline tickets, parking tickets, gaming, code repos, saas churn)
        non_event_patterns = [
            r"parking\s+ticket",
            r"airline\s+ticket",
            r"support\s+ticket",
            r"zendesk|freshdesk|jira|intercom",
            r"jwt\s+ticket|kerberos|rpc|microservices",
            r"board\s+game|ticket\s+to\s+ride",
            r"lottery\s+ticket|raffle\s+ticket",
            r"cli\s+written\s+in|open\s+source\s+ticket|stars\s+appreciated",
            r"calculate\s+churn|saas\s+subscriptions?",
        ]
        if any(re.search(pat, combined) for pat in non_event_patterns):
            return SignalAnalysis(
                is_event_related=False,
                has_ticketing_pain=False,
                complaint_category=ComplaintCategory.NONE,
                intent=IntentCategory.NOT_EVENT_RELATED,
                buyer_fit=BuyerFit.LOW,
                evidence_quote="",
                reasoning="Discussion involves customer support tickets, IT security, transport tickets, or SaaS metrics, not event ticketing.",
                outreach_draft="",
                needs_human_review=False,
            )

        # 2. Check if author is a ticket BUYER/fan complaining about concert prices (not an organizer)
        fan_patterns = [
            r"bought\s+a\s+ticket|tried\s+to\s+buy",
            r"taylor\s+swift|concert\s+tickets|scalper|live\s+nation",
            r"virtual\s+queue|ticketmaster\s+fees\s+are\s+a\s+scam",
        ]
        if any(re.search(pat, combined) for pat in fan_patterns) and not re.search(r"we\s+host|we\s+organize|our\s+conference", combined):
            return SignalAnalysis(
                is_event_related=False,
                has_ticketing_pain=False,
                complaint_category=ComplaintCategory.NONE,
                intent=IntentCategory.SHARING_FRUSTRATION,
                buyer_fit=BuyerFit.LOW,
                evidence_quote="",
                reasoning="Consumer/attendee complaining about ticket purchasing or scalping, not an event organizer.",
                outreach_draft="",
                needs_human_review=False,
            )

        # 3. Check for organizer pain categories
        is_organizer = bool(re.search(r"we\s+host|i\s+organize|our\s+conference|our\s+agency|we\s+run|annual|attendees|ticketed|our\s+university|hackathons?|non[- ]profits?|symposium|summit|festival|tournament", combined))
        complaint = ComplaintCategory.NONE
        evidence_quote = ""
        intent = IntentCategory.INFORMATIONAL
        buyer_fit = BuyerFit.HIGH if is_organizer else BuyerFit.MEDIUM

        # Category checks
        if re.search(r"fee|fees|cut|percentage|gouged|taking\s+nearly|expensive|cost|charging\s+organizers|contract\s+upfront", combined):
            complaint = ComplaintCategory.FEES_EXTORTION
            match = re.search(r"([^.?!]*(?:fees?|cut|taking\s+nearly|gouged|charging|contract)[^.?!]*)", text, re.IGNORECASE)
            if match:
                evidence_quote = match.group(1).strip()
        elif re.search(r"brand|white[- ]label|custom\s+domain|logo|plastering", combined):
            complaint = ComplaintCategory.BRANDING_LIMITATION
            match = re.search(r"([^.?!]*(?:white[- ]label|brand|custom\s+domain|logo)[^.?!]*)", text, re.IGNORECASE)
            if match:
                evidence_quote = match.group(1).strip()
        elif re.search(r"data\s+lock|export|hubspot|salesforce|contact\s+data|own\s+the\s+attendee", combined):
            complaint = ComplaintCategory.DATA_LOCKIN
            match = re.search(r"([^.?!]*(?:data|export|contact|attendee)[^.?!]*)", text, re.IGNORECASE)
            if match:
                evidence_quote = match.group(1).strip()
        elif re.search(r"payout|withheld|revenue\s+until|bankrupt|escrow|merchant|real[- ]time\s+as\s+tickets\s+sell", combined):
            complaint = ComplaintCategory.PAYMENT_PAYOUT_DELAYS
            match = re.search(r"([^.?!]*(?:payout|withheld|revenue|merchant)[^.?!]*)", text, re.IGNORECASE)
            if match:
                evidence_quote = match.group(1).strip()
        elif re.search(r"checkout|conversion|abandonment|account\s+wall|vat|invoice|refuse\s+to\s+buy|sepa|crashed|under\s+load", combined):
            complaint = ComplaintCategory.CHECKOUT_CONVERSION
            match = re.search(r"([^.?!]*(?:checkout|abandonment|invoice|conversion|refuse\s+to\s+buy|crashed)[^.?!]*)", text, re.IGNORECASE)
            if match:
                evidence_quote = match.group(1).strip()
        elif re.search(r"webhook|zapier|integration|api|tracking\s+pixel|tag\s+manager|iframe", combined):
            complaint = ComplaintCategory.INTEGRATIONS_APIS
            match = re.search(r"([^.?!]*(?:webhook|zapier|api|integration|tracking\s+pixel|iframe)[^.?!]*)", text, re.IGNORECASE)
            if match:
                evidence_quote = match.group(1).strip()
        elif re.search(r"nightmare\s+to\s+maintain|custom\s+seat|approval\s+workflow|seat[- ]map", combined):
            complaint = ComplaintCategory.GENERAL_EVENT_TECH
            match = re.search(r"([^.?!]*(?:nightmare|custom\s+seat|maintain|approval)[^.?!]*)", text, re.IGNORECASE)
            if match:
                evidence_quote = match.group(1).strip()
        elif re.search(r"ticket|registration", combined):
            complaint = ComplaintCategory.GENERAL_EVENT_TECH
            evidence_quote = text[:80].strip()

        # Intent detection
        if re.search(r"alternative|recommend|looking\s+for|what\s+tools|anyone\s+found|what\s+do\s+you\s+use|we\s+need\s+a|replacing\s+our|actively\s+reviewing", combined):
            intent = IntentCategory.EVALUATING_ALTERNATIVES
        elif re.search(r"building\s+an?\s+in[- ]house|custom\s+seat|nightmare\s+to\s+maintain", combined):
            intent = IntentCategory.BUILDING_IN_HOUSE
        elif re.search(r"frustrated|annoying|worst\s+part|killing|crashed|refuse\s+to\s+buy|lost\s+\d+|outrageous", combined):
            intent = IntentCategory.SHARING_FRUSTRATION
        elif re.search(r"case\s+study|announcing", combined):
            intent = IntentCategory.INFORMATIONAL

        has_pain = complaint != ComplaintCategory.NONE
        if complaint == ComplaintCategory.GENERAL_EVENT_TECH and not re.search(r"nightmare|frustrated|annoying|difficult|problem|tedious", combined):
            has_pain = False

        # Draft evidence-based outreach
        outreach_draft = ""
        if has_pain and is_organizer:
            quote_snippet = f'"{evidence_quote[:60]}..."' if evidence_quote else "your ticketing infrastructure requirements"
            if complaint == ComplaintCategory.FEES_EXTORTION:
                outreach_draft = (
                    f"Hi {signal.author}, saw your discussion regarding {quote_snippet}. "
                    "At Ticmint, we built a white-label ticketing platform that connects directly to your own Stripe "
                    "account with flat, transparent fees (no percentage cuts or surprise per-ticket penalties). "
                    "Happy to share a 3-minute sandbox demo if you're evaluating alternatives for your upcoming event."
                )
            elif complaint == ComplaintCategory.BRANDING_LIMITATION:
                outreach_draft = (
                    f"Hi {signal.author}, noticed your post about {quote_snippet}. "
                    "Ticmint is designed specifically for event operators and agencies requiring complete white-label registration: "
                    "custom subdomains, fully styleable embedded checkouts, and zero vendor co-branding. "
                    "Would be glad to share how our webhook integrations and custom styling work."
                )
            elif complaint == ComplaintCategory.PAYMENT_PAYOUT_DELAYS:
                outreach_draft = (
                    f"Hi {signal.author}, read your note on {quote_snippet}. "
                    "Withholding ticket proceeds creates serious cashflow headaches for live event production. "
                    "Ticmint routes all ticket payments straight into your own Stripe/merchant balance in real-time, "
                    "so you never have to wait weeks after an event to access your capital."
                )
            elif complaint == ComplaintCategory.DATA_LOCKIN:
                outreach_draft = (
                    f"Hi {signal.author}, completely agree on {quote_snippet}. "
                    "You should own 100% of your attendee relationships. Ticmint never emails or markets to your attendees, "
                    "and gives you unmasked CSV exports plus instant webhook sync into your CRM/HubSpot."
                )
            else:
                outreach_draft = (
                    f"Hi {signal.author}, saw your post highlighting {quote_snippet}. "
                    "Ticmint offers a modern white-label ticketing and registration solution built for operators needing "
                    "clean checkout conversion, direct payouts, and full data control. Happy to compare notes if helpful."
                )

        reasoning = (
            f"Detected event organizer discussing {complaint.value} with intent '{intent.value}'. "
            f"ICP fit is {buyer_fit.value} based on self-identification and technical requirements."
        )

        return SignalAnalysis(
            is_event_related=True,
            has_ticketing_pain=has_pain,
            complaint_category=complaint,
            intent=intent,
            buyer_fit=buyer_fit,
            evidence_quote=evidence_quote or text[:70],
            reasoning=reasoning,
            outreach_draft=outreach_draft,
            needs_human_review=True,
        )
