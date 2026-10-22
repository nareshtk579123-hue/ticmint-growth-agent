"""
Unit tests for transparent 100-point lead qualification rubric.
Tests pain calculations, intent scoring, ICP persona fit, recency, evidence quality, and hard suppression.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import pytest
from app.models import (
    BuyerFit,
    ComplaintCategory,
    IntentCategory,
    PriorityLevel,
    RawSignal,
    SignalAnalysis,
)
from app.scoring import LeadScorer


@pytest.fixture
def base_signal() -> RawSignal:
    now_iso = datetime.now(timezone.utc).isoformat()
    return RawSignal(
        source="hacker_news",
        source_id="hn_test_01",
        author="conf_organizer",
        title="Eventbrite fees are too high",
        text="We host an annual tech conference for 800 attendees. Eventbrite fees are taking 8.5% and card processing fees. We need a white-label alternative with custom domain checkout.",
        url="https://news.ycombinator.com/item?id=999901",
        canonical_url="https://news.ycombinator.com/item?id=999901",
        published_at=now_iso,
    )


def test_high_priority_qualification(base_signal: RawSignal):
    analysis = SignalAnalysis(
        is_event_related=True,
        has_ticketing_pain=True,
        complaint_category=ComplaintCategory.FEES_EXTORTION,
        intent=IntentCategory.EVALUATING_ALTERNATIVES,
        buyer_fit=BuyerFit.HIGH,
        evidence_quote="Eventbrite fees are taking 8.5% and card processing fees",
        reasoning="Conference director actively seeking white-label alternative due to excessive fees.",
        outreach_draft="Hi conf_organizer, saw your note on fees...",
        needs_human_review=True,
    )

    score = LeadScorer.score_signal(base_signal, analysis)
    assert score.total_score >= 75
    assert score.priority == PriorityLevel.HIGH
    assert score.ticketing_pain >= 25
    assert score.switching_intent == 25
    assert score.icp_fit >= 20
    assert score.recency == 10
    assert score.evidence_quality >= 8


def test_hard_suppression_non_event(base_signal: RawSignal):
    analysis = SignalAnalysis(
        is_event_related=False,
        has_ticketing_pain=False,
        complaint_category=ComplaintCategory.NONE,
        intent=IntentCategory.NOT_EVENT_RELATED,
        buyer_fit=BuyerFit.LOW,
        evidence_quote="",
        reasoning="Post is about customer support software, not event ticketing.",
        outreach_draft="",
        needs_human_review=False,
    )

    score = LeadScorer.score_signal(base_signal, analysis)
    assert score.total_score == 0
    assert score.priority == PriorityLevel.DISQUALIFIED
    assert any("Not related to event hosting" in n for n in score.qualification_notes)


def test_hard_suppression_zero_pain(base_signal: RawSignal):
    analysis = SignalAnalysis(
        is_event_related=True,
        has_ticketing_pain=False,
        complaint_category=ComplaintCategory.NONE,
        intent=IntentCategory.INFORMATIONAL,
        buyer_fit=BuyerFit.HIGH,
        evidence_quote="",
        reasoning="Event announcement with no ticketing dissatisfaction.",
        outreach_draft="",
        needs_human_review=False,
    )

    score = LeadScorer.score_signal(base_signal, analysis)
    assert score.total_score == 0
    assert score.priority == PriorityLevel.DISQUALIFIED


def test_recency_decay():
    now = datetime.now(timezone.utc)

    fresh_iso = (now - timedelta(days=2)).isoformat()
    month_old_iso = (now - timedelta(days=20)).isoformat()
    old_iso = (now - timedelta(days=200)).isoformat()

    fresh_score, _ = LeadScorer._calculate_recency_score(fresh_iso)
    assert fresh_score == 10

    month_score, _ = LeadScorer._calculate_recency_score(month_old_iso)
    assert month_score == 8

    old_score, _ = LeadScorer._calculate_recency_score(old_iso)
    assert old_score == 0


def test_medium_priority_tier_for_small_workshops(base_signal: RawSignal):
    # Medium ICP fit (workshop host) should qualify as MEDIUM priority (50-74), not HIGH
    analysis = SignalAnalysis(
        is_event_related=True,
        has_ticketing_pain=True,
        complaint_category=ComplaintCategory.FEES_EXTORTION,
        intent=IntentCategory.EVALUATING_ALTERNATIVES,
        buyer_fit=BuyerFit.MEDIUM,
        evidence_quote="Eventbrite fees are taking 8.5%",
        reasoning="Small workshop organizer seeking cheaper option.",
        outreach_draft="Hi, here is a demo...",
        needs_human_review=True,
    )

    score = LeadScorer.score_signal(base_signal, analysis)
    assert score.total_score >= 50
    assert score.priority == PriorityLevel.MEDIUM
