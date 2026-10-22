"""
Public Signal Collector for Ticmint Growth Agent.
Queries permitted public sources (Hacker News Algolia API, public RSS feeds)
and normalizes records into structured RawSignal models.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
import httpx
from app.config import config
from app.models import RawSignal

logger = logging.getLogger("ticmint.collector")


def canonicalize_url(raw_url: str) -> str:
    """
    Strips tracking query parameters (utm_*, ref, etc.) and fragments
    to ensure stable deduplication across different search hits.
    """
    if not raw_url:
        return ""
    try:
        parsed = urlparse(raw_url.strip())
        # Filter tracking params
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        cleaned_params = {
            k: v for k, v in query_params.items()
            if not (k.startswith("utm_") or k in ("ref", "fbclid", "gclid", "source", "t"))
        }
        encoded_query = urlencode(cleaned_params, doseq=True)
        cleaned = urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            encoded_query,
            ""  # drop fragment
        ))
        return cleaned
    except Exception:
        return raw_url.strip().lower()


class SignalCollector:
    """Collects and normalizes public discussions from permitted APIs and RSS feeds."""

    HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"

    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout
        self.client = httpx.Client(
            timeout=self.timeout,
            headers={"User-Agent": config.USER_AGENT}
        )

    def close(self):
        self.client.close()

    def fetch_hacker_news_signals(self, query: str, hits_per_page: int = 15) -> List[RawSignal]:
        """
        Query Hacker News Algolia search API for a given query string.
        Extracts both stories and comments discussing ticketing frictions.
        """
        signals: List[RawSignal] = []
        params = {
            "query": query,
            "tags": "(story,comment)",
            "hitsPerPage": hits_per_page,
            "numericFilters": "points>=0",
        }

        try:
            response = self.client.get(self.HN_SEARCH_URL, params=params)
            if response.status_code != 200:
                logger.warning("Hacker News API returned status %s for query '%s'", response.status_code, query)
                return []

            data = response.json()
            hits = data.get("hits", [])

            for hit in hits:
                story_id = hit.get("story_id") or hit.get("objectID")
                object_id = hit.get("objectID")
                title = hit.get("story_title") or hit.get("title") or ""
                author = hit.get("author") or "anonymous"
                raw_text = hit.get("comment_text") or hit.get("story_text") or title or ""

                # Strip HTML tags returned by Algolia comments
                clean_text = re.sub(r"<[^>]+>", " ", raw_text).strip()
                if not clean_text or len(clean_text) < 25:
                    continue

                # Build public URL pointing directly to the item
                item_url = f"https://news.ycombinator.com/item?id={object_id}"
                canonical = canonicalize_url(item_url)

                # Published date
                created_at = hit.get("created_at") or datetime.now(timezone.utc).isoformat()

                signal = RawSignal(
                    source="hacker_news",
                    source_id=f"hn_{object_id}",
                    author=author,
                    title=title if title else None,
                    text=clean_text,
                    url=item_url,
                    canonical_url=canonical,
                    published_at=created_at,
                )
                signals.append(signal)

        except Exception as e:
            logger.error("Error querying Hacker News API for '%s': %s", query, e)

        return signals

    def load_sample_signals(self) -> List[RawSignal]:
        """Loads vetted sample signals from local JSON file."""
        if not config.SAMPLE_SIGNALS_PATH.exists():
            return []
        try:
            with open(config.SAMPLE_SIGNALS_PATH, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            signals = []
            for item in raw_data:
                canonical = canonicalize_url(item.get("canonical_url", item.get("url", "")))
                sig = RawSignal(
                    source=item.get("source", "sample"),
                    source_id=item.get("source_id", "sample_id"),
                    author=item.get("author", "anonymous"),
                    title=item.get("title"),
                    text=item.get("text", ""),
                    url=item.get("url", ""),
                    canonical_url=canonical,
                    published_at=item.get("published_at", datetime.now(timezone.utc).isoformat()),
                )
                signals.append(sig)
            return signals
        except Exception as e:
            logger.error("Failed to load sample signals: %s", e)
            return []

    def collect_all_signals(
        self,
        queries: Optional[List[str]] = None,
        max_total: int = 25,
        include_samples: bool = True
    ) -> List[RawSignal]:
        """
        Executes signal collection across target queries.
        Combines live hits with vetted sample signals to guarantee high-quality test coverage.
        """
        queries = queries or config.TARGET_SEARCH_QUERIES[:3]
        collected: List[RawSignal] = []

        # 1. Fetch live public signals from Hacker News Algolia
        for query in queries:
            live_signals = self.fetch_hacker_news_signals(query=query, hits_per_page=10)
            collected.extend(live_signals)
            if len(collected) >= max_total:
                break

        # 2. If live search returned few results or in offline/testing mode, augment with vetted samples
        if include_samples or len(collected) < 5:
            samples = self.load_sample_signals()
            collected.extend(samples)

        # 3. Deduplicate by canonical URL
        deduped = self.deduplicate(collected)
        return deduped[:max_total]

    @staticmethod
    def deduplicate(signals: List[RawSignal]) -> List[RawSignal]:
        """Removes duplicate signals based on canonical URL and source ID."""
        seen_keys = set()
        unique_signals: List[RawSignal] = []

        for sig in signals:
            key = (sig.source, sig.canonical_url)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            unique_signals.append(sig)

        return unique_signals
