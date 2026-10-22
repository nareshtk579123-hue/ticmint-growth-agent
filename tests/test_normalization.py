"""
Unit tests for data normalization, URL canonicalization, and deduplication.
"""

from __future__ import annotations

from app.collector import canonicalize_url, SignalCollector
from app.models import RawSignal


def test_canonicalize_url_strips_tracking():
    raw_url = "https://news.ycombinator.com/item?id=12345&utm_source=twitter&utm_medium=social&ref=producthunt#comment-section"
    expected = "https://news.ycombinator.com/item?id=12345"
    assert canonicalize_url(raw_url) == expected


def test_canonicalize_url_preserves_functional_params():
    raw_url = "https://example.com/discussion?topic=ticketing&page=2&utm_campaign=winter"
    canonical = canonicalize_url(raw_url)
    assert "utm_campaign" not in canonical
    assert "topic=ticketing" in canonical
    assert "page=2" in canonical


def test_deduplicate_signals_collapses_duplicates():
    sig1 = RawSignal(
        source="hacker_news",
        source_id="hn_100",
        author="user_a",
        text="Eventbrite is taking high fees on our summit.",
        url="https://news.ycombinator.com/item?id=100&utm_source=slack",
        canonical_url="https://news.ycombinator.com/item?id=100",
        published_at="2026-10-18T10:00:00Z",
    )
    sig2 = RawSignal(
        source="hacker_news",
        source_id="hn_100",
        author="user_a",
        text="Eventbrite is taking high fees on our summit.",
        url="https://news.ycombinator.com/item?id=100&utm_source=twitter",
        canonical_url="https://news.ycombinator.com/item?id=100",
        published_at="2026-10-18T10:00:00Z",
    )
    sig3 = RawSignal(
        source="hacker_news",
        source_id="hn_200",
        author="user_b",
        text="We need custom domain ticketing.",
        url="https://news.ycombinator.com/item?id=200",
        canonical_url="https://news.ycombinator.com/item?id=200",
        published_at="2026-10-19T10:00:00Z",
    )

    deduped = SignalCollector.deduplicate([sig1, sig2, sig3])
    assert len(deduped) == 2
    canonical_urls = [s.canonical_url for s in deduped]
    assert canonical_urls == [
        "https://news.ycombinator.com/item?id=100",
        "https://news.ycombinator.com/item?id=200",
    ]


def test_deterministic_lead_id_generation():
    id1 = RawSignal.generate_lead_id("hacker_news", "https://news.ycombinator.com/item?id=123")
    id2 = RawSignal.generate_lead_id("HACKER_NEWS", "  https://news.ycombinator.com/item?id=123  ")
    assert id1 == id2
    assert len(id1) == 16
