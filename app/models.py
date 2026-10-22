"""
Pydantic data models for the Ticmint Growth Intelligence Agent.
Provides schema enforcement, validation, and serialization.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl, field_validator


class ComplaintCategory(str, Enum):
    FEES_EXTORTION = "fees_extortion"
    BRANDING_LIMITATION = "branding_limitation"
    DATA_LOCKIN = "data_lockin"
    CHECKOUT_CONVERSION = "checkout_conversion"
    INTEGRATIONS_APIS = "integrations_apis"
    PAYMENT_PAYOUT_DELAYS = "payment_payout_delays"
    GENERAL_EVENT_TECH = "general_event_tech"
    NONE = "none"


class IntentCategory(str, Enum):
    EVALUATING_ALTERNATIVES = "evaluating_alternatives"
    SHARING_FRUSTRATION = "sharing_frustration"
    SEEKING_FEEDBACK = "seeking_feedback"
    BUILDING_IN_HOUSE = "building_in_house"
    INFORMATIONAL = "informational"
    NOT_EVENT_RELATED = "not_event_related"


class BuyerFit(str, Enum):
    HIGH = "high"        # Event organizer, agency director, festival operator, enterprise lead
    MEDIUM = "medium"    # Community manager, meetup organizer, startup founder with ticketed event
    LOW = "low"          # Individual attendee, casual commentator, spectator
    UNKNOWN = "unknown"  # Insufficient context to determine buyer persona


class PriorityLevel(str, Enum):
    HIGH = "HIGH"        # 75 - 100 points
    MEDIUM = "MEDIUM"    # 50 - 74 points
    LOW = "LOW"          # < 50 points (held for monitoring)
    DISQUALIFIED = "DISQUALIFIED"  # False positives, spam, privacy restricted


class RawSignal(BaseModel):
    """Raw public signal collected from internet communities or RSS feeds."""

    source: str = Field(description="Signal origin, e.g. 'hacker_news', 'rss_feed', 'community'")
    source_id: str = Field(description="Unique source ID from the platform")
    author: str = Field(default="anonymous", description="Public username or author name")
    title: Optional[str] = Field(default=None, description="Title of discussion thread or post")
    text: str = Field(description="Body text of the post or comment")
    url: str = Field(description="Public URL pointing to the signal")
    canonical_url: str = Field(description="Canonicalized URL for deduplication")
    published_at: str = Field(description="ISO-8601 published timestamp")
    collected_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 collection timestamp"
    )
    content_hash: str = Field(default="", description="SHA256 hash of canonical URL and text")

    def model_post_init(self, __context):
        if not self.content_hash:
            raw_key = f"{self.source}:{self.canonical_url}:{self.text[:120]}"
            self.content_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()

    @classmethod
    def generate_lead_id(cls, source: str, canonical_url: str) -> str:
        """Deterministic, stable lead ID based on source and canonical URL."""
        return hashlib.sha256(f"{source.lower()}:{canonical_url.strip().lower()}".encode("utf-8")).hexdigest()[:16]


class SignalAnalysis(BaseModel):
    """Structured LLM analysis of a raw signal."""

    is_event_related: bool = Field(description="True if post discusses organizing, hosting, or ticketing an event")
    has_ticketing_pain: bool = Field(description="True if post cites friction with ticketing/registration software")
    complaint_category: ComplaintCategory = Field(default=ComplaintCategory.NONE, description="Primary pain category")
    intent: IntentCategory = Field(default=IntentCategory.INFORMATIONAL, description="Commercial or switching intent")
    buyer_fit: BuyerFit = Field(default=BuyerFit.UNKNOWN, description="ICP fit based on organizer persona")
    evidence_quote: str = Field(default="", description="Verbatim quote from post demonstrating the pain")
    reasoning: str = Field(description="Defensible business reasoning for qualification")
    outreach_draft: str = Field(default="", description="Contextual, evidence-grounded outreach draft")
    needs_human_review: bool = Field(default=True, description="Always true for automated growth drafts")


class ScoreBreakdown(BaseModel):
    """Transparent 100-point rubric breakdown."""

    ticketing_pain: int = Field(ge=0, le=30, description="Pain severity & specificity (0-30)")
    switching_intent: int = Field(ge=0, le=25, description="Switching/evaluating intent (0-25)")
    icp_fit: int = Field(ge=0, le=25, description="Event organizer / agency persona fit (0-25)")
    recency: int = Field(ge=0, le=10, description="Post recency (0-10)")
    evidence_quality: int = Field(ge=0, le=10, description="Verifiability and quote strength (0-10)")
    total_score: int = Field(ge=0, le=100, description="Aggregate score (0-100)")
    priority: PriorityLevel = Field(default=PriorityLevel.LOW, description="Lead tier")
    qualification_notes: List[str] = Field(default_factory=list, description="Rule-based audit log notes")


class LeadRecord(BaseModel):
    """Persistent, qualified lead record stored in Google Sheets and local storage."""

    lead_id: str = Field(description="Unique stable hash identifier")
    first_seen: str = Field(description="ISO-8601 timestamp when first detected")
    last_seen: str = Field(description="ISO-8601 timestamp of most recent run seeing this signal")
    source: str = Field(description="Source platform name")
    author: str = Field(description="Public author handle")
    source_url: str = Field(description="Direct URL to public conversation")
    evidence_quote: str = Field(description="Direct quotation of the complaint")
    complaint_category: str = Field(description="Categorized ticketing problem")
    intent: str = Field(description="Detected intent")
    buyer_fit: str = Field(description="Buyer ICP fit")
    lead_score: int = Field(description="Total 0-100 lead qualification score")
    priority: str = Field(description="HIGH, MEDIUM, LOW, or DISQUALIFIED")
    score_breakdown: ScoreBreakdown = Field(description="Detailed scoring criteria")
    outreach_draft: str = Field(description="Personalized outreach draft referencing the real complaint")
    review_status: str = Field(default="PENDING_HUMAN_REVIEW", description="PENDING_HUMAN_REVIEW, APPROVED, REJECTED, CONTACTED")
    last_updated: str = Field(description="ISO-8601 timestamp of last analysis update")

    def to_sheet_row(self) -> List[str]:
        """Convert lead record to tabular list of strings for Google Sheets Tab 1."""
        return [
            self.lead_id,
            self.first_seen,
            self.last_seen,
            self.source,
            self.author,
            self.source_url,
            self.evidence_quote,
            self.complaint_category,
            self.intent,
            self.buyer_fit,
            str(self.lead_score),
            self.priority,
            self.outreach_draft,
            self.review_status,
            self.last_updated,
        ]

    @classmethod
    def sheet_headers(cls) -> List[str]:
        """Header names for Google Sheets Tab 1 (Qualified Leads)."""
        return [
            "Lead ID",
            "First Seen",
            "Last Seen",
            "Source",
            "Author",
            "Source URL",
            "Evidence Quote",
            "Complaint Category",
            "Intent",
            "ICP Fit",
            "Lead Score",
            "Priority",
            "Outreach Draft",
            "Review Status",
            "Last Updated",
        ]


class AgentRunLog(BaseModel):
    """Audit log entry for an agent execution run (Tab 2: Run History)."""

    run_id: str = Field(description="Unique run execution ID")
    started_at: str = Field(description="ISO-8601 execution start time")
    completed_at: str = Field(description="ISO-8601 execution end time")
    sources_checked: int = Field(default=0, description="Count of sources queried")
    records_retrieved: int = Field(default=0, description="Raw records ingested")
    duplicates_filtered: int = Field(default=0, description="Duplicate records discarded")
    qualified_leads: int = Field(default=0, description="Leads scoring >= 50 points")
    high_priority_leads: int = Field(default=0, description="Leads scoring >= 75 points")
    llm_errors: int = Field(default=0, description="Failed LLM calls")
    sheet_errors: int = Field(default=0, description="Failed sheet write/update attempts")
    run_status: str = Field(default="SUCCESS", description="SUCCESS, WARNING, or FAILED")
    summary_message: str = Field(default="", description="Human-readable run outcome")

    def to_sheet_row(self) -> List[str]:
        """Convert run log to tabular list of strings for Google Sheets Tab 2."""
        return [
            self.run_id,
            self.started_at,
            self.completed_at,
            str(self.sources_checked),
            str(self.records_retrieved),
            str(self.duplicates_filtered),
            str(self.qualified_leads),
            str(self.high_priority_leads),
            str(self.llm_errors),
            str(self.sheet_errors),
            self.run_status,
            self.summary_message,
        ]

    @classmethod
    def sheet_headers(cls) -> List[str]:
        """Header names for Google Sheets Tab 2 (Run History)."""
        return [
            "Run ID",
            "Started At",
            "Completed At",
            "Sources Checked",
            "Records Retrieved",
            "Duplicates Filtered",
            "Qualified Leads",
            "High Priority Leads",
            "LLM Errors",
            "Sheet Errors",
            "Run Status",
            "Summary Message",
        ]
