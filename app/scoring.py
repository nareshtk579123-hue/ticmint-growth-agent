"""
Transparent 100-point Lead Qualification Rubric for Ticmint Growth Agent.
Evaluates raw signals and AI analysis to compute a transparent, defensible score.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import List, Tuple
from app.models import (
    BuyerFit,
    ComplaintCategory,
    IntentCategory,
    PriorityLevel,
    RawSignal,
    ScoreBreakdown,
    SignalAnalysis,
)


class LeadScorer:
    """Computes transparent, defensible lead qualification scores based on a 100-point rubric."""

    # Rubric Weights
    MAX_PAIN_SCORE: int = 30
    MAX_INTENT_SCORE: int = 25
    MAX_ICP_SCORE: int = 25
    MAX_RECENCY_SCORE: int = 10
    MAX_EVIDENCE_SCORE: int = 10

    # Qualification Thresholds
    THRESHOLD_HIGH_PRIORITY: int = 75
    THRESHOLD_QUALIFIED: int = 50

    # Competitor keywords that heighten evidence credibility
    COMPETITOR_PATTERNS = [
        re.compile(r"\b(eventbrite|ticketmaster|luma|tito|splashthat|cvent|dice|universe|bizzabo|ticketleap)\b", re.IGNORECASE),
        re.compile(r"\b(stripe\s+fees|ticketing\s+fees|service\s+fee|per[- ]ticket\s+fee)\b", re.IGNORECASE),
    ]

    @classmethod
    def score_signal(cls, signal: RawSignal, analysis: SignalAnalysis) -> ScoreBreakdown:
        """
        Evaluate a signal against the 100-point rubric.
        Returns detailed sub-scores and priority tier.
        """
        notes: List[str] = []

        # 1. Hard suppression checks
        if not analysis.is_event_related:
            notes.append("Suppressed: Not related to event hosting or organization")
            return ScoreBreakdown(
                ticketing_pain=0,
                switching_intent=0,
                icp_fit=0,
                recency=0,
                evidence_quality=0,
                total_score=0,
                priority=PriorityLevel.DISQUALIFIED,
                qualification_notes=notes,
            )

        if not analysis.has_ticketing_pain and analysis.complaint_category == ComplaintCategory.NONE:
            notes.append("Suppressed: Zero ticketing or registration pain expressed")
            return ScoreBreakdown(
                ticketing_pain=0,
                switching_intent=0,
                icp_fit=0,
                recency=0,
                evidence_quality=0,
                total_score=0,
                priority=PriorityLevel.DISQUALIFIED,
                qualification_notes=notes,
            )

        # 2. Pain Score (0 - 30)
        pain_score, pain_notes = cls._calculate_pain_score(analysis, signal)
        notes.extend(pain_notes)

        # 3. Switching Intent Score (0 - 25)
        intent_score, intent_notes = cls._calculate_intent_score(analysis)
        notes.extend(intent_notes)

        # 4. ICP Fit Score (0 - 25)
        icp_score, icp_notes = cls._calculate_icp_score(analysis, signal)
        notes.extend(icp_notes)

        # 5. Recency Score (0 - 10)
        recency_score, recency_notes = cls._calculate_recency_score(signal.published_at)
        notes.extend(recency_notes)

        # 6. Evidence Quality Score (0 - 10)
        evidence_score, evidence_notes = cls._calculate_evidence_score(signal, analysis)
        notes.extend(evidence_notes)

        total_score = pain_score + intent_score + icp_score + recency_score + evidence_score

        # Determine Priority
        # Business rule: HIGH priority tier (immediate sales SDR outreach) requires both
        # a high rubric score (>= 75) AND enterprise/agency/conference organizer fit (BuyerFit.HIGH).
        # Smaller meetups or workshops (BuyerFit.MEDIUM) are qualified for self-serve/nurture (MEDIUM priority).
        if total_score >= cls.THRESHOLD_HIGH_PRIORITY and analysis.buyer_fit == BuyerFit.HIGH:
            priority = PriorityLevel.HIGH
            notes.append(f"Tier: High-priority enterprise/agency opportunity ({total_score}/100) - immediate sales review")
        elif total_score >= cls.THRESHOLD_QUALIFIED:
            priority = PriorityLevel.MEDIUM
            notes.append(f"Tier: Qualified lead ({total_score}/100) - self-serve / nurture candidate")
        else:
            priority = PriorityLevel.LOW
            notes.append(f"Tier: Low priority ({total_score}/100) - retain for trend analysis")

        return ScoreBreakdown(
            ticketing_pain=pain_score,
            switching_intent=intent_score,
            icp_fit=icp_score,
            recency=recency_score,
            evidence_quality=evidence_score,
            total_score=total_score,
            priority=priority,
            qualification_notes=notes,
        )

    @classmethod
    def _calculate_pain_score(cls, analysis: SignalAnalysis, signal: RawSignal) -> Tuple[int, List[str]]:
        notes = []
        if not analysis.has_ticketing_pain:
            return 0, ["Pain: No specific ticketing pain (0/30)"]

        category_weights = {
            ComplaintCategory.FEES_EXTORTION: 28,
            ComplaintCategory.BRANDING_LIMITATION: 26,
            ComplaintCategory.DATA_LOCKIN: 27,
            ComplaintCategory.CHECKOUT_CONVERSION: 25,
            ComplaintCategory.INTEGRATIONS_APIS: 24,
            ComplaintCategory.PAYMENT_PAYOUT_DELAYS: 26,
            ComplaintCategory.GENERAL_EVENT_TECH: 18,
            ComplaintCategory.NONE: 0,
        }

        base = category_weights.get(analysis.complaint_category, 15)

        # Bonus for specific competitor mentions in the raw text
        competitor_hit = any(pat.search(signal.text) for pat in cls.COMPETITOR_PATTERNS)
        if competitor_hit:
            base = min(cls.MAX_PAIN_SCORE, base + 2)
            notes.append("Pain: Explicit competitor/fee frustration cited (+2)")

        notes.append(f"Pain: Category '{analysis.complaint_category.value}' scored {base}/{cls.MAX_PAIN_SCORE}")
        return base, notes

    @classmethod
    def _calculate_intent_score(cls, analysis: SignalAnalysis) -> Tuple[int, List[str]]:
        intent_weights = {
            IntentCategory.EVALUATING_ALTERNATIVES: 25,
            IntentCategory.BUILDING_IN_HOUSE: 22,
            IntentCategory.SEEKING_FEEDBACK: 18,
            IntentCategory.SHARING_FRUSTRATION: 12,
            IntentCategory.INFORMATIONAL: 4,
            IntentCategory.NOT_EVENT_RELATED: 0,
        }
        score = intent_weights.get(analysis.intent, 5)
        return score, [f"Intent: '{analysis.intent.value}' scored {score}/{cls.MAX_INTENT_SCORE}"]

    @classmethod
    def _calculate_icp_score(cls, analysis: SignalAnalysis, signal: RawSignal) -> Tuple[int, List[str]]:
        fit_weights = {
            BuyerFit.HIGH: 25,     # Confirmed event organizer/agency
            BuyerFit.MEDIUM: 18,   # Community manager / founder
            BuyerFit.LOW: 8,       # General user / spectator
            BuyerFit.UNKNOWN: 10,
        }
        score = fit_weights.get(analysis.buyer_fit, 10)

        # Keyword boost if author explicitly identifies role in post
        author_role_pattern = re.compile(
            r"\b(we host|i organize|our conference|our agency|we run an annual|our event|ticket sales)\b",
            re.IGNORECASE
        )
        if author_role_pattern.search(signal.text):
            score = min(cls.MAX_ICP_SCORE, score + 3)
            return score, [f"ICP: Active event host self-identified in text ({score}/{cls.MAX_ICP_SCORE})"]

        return score, [f"ICP: Fit level '{analysis.buyer_fit.value}' scored {score}/{cls.MAX_ICP_SCORE}"]

    @classmethod
    def _calculate_recency_score(cls, published_at_iso: str) -> Tuple[int, List[str]]:
        try:
            # Handle various ISO timestamp formats
            clean_iso = published_at_iso.replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age_days = (now - dt).total_seconds() / 86400.0

            if age_days < 7:
                return 10, [f"Recency: Fresh signal (< 7 days old: {age_days:.1f}d) (10/10)"]
            elif age_days < 30:
                return 8, [f"Recency: Recent signal (< 30 days old: {age_days:.1f}d) (8/10)"]
            elif age_days < 90:
                return 5, [f"Recency: Relevant (< 90 days old: {age_days:.1f}d) (5/10)"]
            elif age_days < 180:
                return 2, [f"Recency: Aging signal (< 180 days: {age_days:.1f}d) (2/10)"]
            else:
                return 0, [f"Recency: Stale signal (> 180 days: {age_days:.1f}d) (0/10)"]
        except Exception:
            return 5, ["Recency: Timestamp unparseable, assigned default (5/10)"]

    @classmethod
    def _calculate_evidence_score(cls, signal: RawSignal, analysis: SignalAnalysis) -> Tuple[int, List[str]]:
        quote = analysis.evidence_quote.strip()
        score = 0
        notes = []

        if not quote:
            return 0, ["Evidence: No direct quote extracted (0/10)"]

        # Verifiable quote matches signal text
        if quote.lower() in signal.text.lower():
            score += 6
            notes.append("Evidence: Verbatim quote matches source text (+6)")
        else:
            score += 3
            notes.append("Evidence: Paraphrased quote partially found (+3)")

        # Specificity checks
        if len(quote) >= 40:
            score += 2
            notes.append("Evidence: Detailed context (>40 chars) (+2)")

        if signal.url.startswith("http"):
            score += 2
            notes.append("Evidence: Verifiable public URL (+2)")

        final_score = min(cls.MAX_EVIDENCE_SCORE, score)
        return final_score, [f"Evidence: Total evidence score ({final_score}/{cls.MAX_EVIDENCE_SCORE})"]
