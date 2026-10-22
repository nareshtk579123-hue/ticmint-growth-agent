"""
Unit tests for SheetsManager: idempotent upserts, row preservation, and local fallback storage.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from app.config import config
from app.models import AgentRunLog, LeadRecord, PriorityLevel, ScoreBreakdown
from app.sheets import SheetsManager


@pytest.fixture
def clean_local_storage(tmp_path: Path, monkeypatch):
    test_json = tmp_path / "test_sheet.json"
    test_csv = tmp_path / "test_sheet.csv"
    monkeypatch.setattr(config, "LOCAL_SHEET_JSON_PATH", test_json)
    monkeypatch.setattr(config, "LOCAL_SHEET_CSV_PATH", test_csv)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    return test_json, test_csv


def make_lead(lead_id: str, score: int = 80, first_seen: str = "2026-10-18T10:00:00Z", review_status: str = "PENDING_HUMAN_REVIEW") -> LeadRecord:
    breakdown = ScoreBreakdown(
        ticketing_pain=28,
        switching_intent=25,
        icp_fit=20,
        recency=10,
        evidence_quality=8,
        total_score=score,
        priority=PriorityLevel.HIGH if score >= 75 else PriorityLevel.MEDIUM,
        qualification_notes=["Qualified"],
    )
    return LeadRecord(
        lead_id=lead_id,
        first_seen=first_seen,
        last_seen=first_seen,
        source="hacker_news",
        author="test_author",
        source_url="https://news.ycombinator.com/item?id=123",
        evidence_quote="High ticketing fees",
        complaint_category="fees_extortion",
        intent="evaluating_alternatives",
        buyer_fit="high",
        lead_score=score,
        priority=breakdown.priority.value,
        score_breakdown=breakdown,
        outreach_draft="Hello, test draft",
        review_status=review_status,
        last_updated=first_seen,
    )


def test_idempotent_local_upsert(clean_local_storage):
    test_json, test_csv = clean_local_storage
    mgr = SheetsManager()

    lead_a = make_lead("lead_01", score=80, first_seen="2026-10-18T10:00:00Z")

    # 1. First run: insert 1 new lead
    res1 = mgr.upsert_leads([lead_a])
    assert res1["inserted"] == 1
    assert res1["updated"] == 0

    with open(test_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "lead_01" in data["leads"]
    assert data["leads"]["lead_01"]["lead_score"] == 80

    # User manually reviews and marks it APPROVED in the sheet
    data["leads"]["lead_01"]["review_status"] = "APPROVED"
    with open(test_json, "w", encoding="utf-8") as f:
        json.dump(data, f)

    # 2. Second run: same lead seen again with updated score and new timestamp
    lead_a_updated = make_lead("lead_01", score=85, first_seen="2026-10-20T12:00:00Z")
    lead_a_updated.last_seen = "2026-10-20T12:00:00Z"
    lead_a_updated.outreach_draft = "Updated draft"

    res2 = mgr.upsert_leads([lead_a_updated])
    assert res2["inserted"] == 0
    assert res2["updated"] == 1

    # Verify First Seen and Review Status were preserved, but score & draft were updated
    with open(test_json, "r", encoding="utf-8") as f:
        data_after = json.load(f)
    saved = data_after["leads"]["lead_01"]
    assert saved["first_seen"] == "2026-10-18T10:00:00Z"  # Preserved!
    assert saved["review_status"] == "APPROVED"            # Preserved human review!
    assert saved["lead_score"] == 85                      # Updated!
    assert saved["outreach_draft"] == "Updated draft"      # Updated!


def test_log_run_and_dashboard_metrics(clean_local_storage):
    test_json, _ = clean_local_storage
    mgr = SheetsManager()

    lead1 = make_lead("lead_01", score=85)
    lead2 = make_lead("lead_02", score=65)
    mgr.upsert_leads([lead1, lead2])

    run_log = AgentRunLog(
        run_id="run_test_99",
        started_at="2026-10-20T10:00:00Z",
        completed_at="2026-10-20T10:01:00Z",
        sources_checked=3,
        records_retrieved=15,
        duplicates_filtered=5,
        qualified_leads=2,
        high_priority_leads=1,
        llm_errors=0,
        sheet_errors=0,
        run_status="SUCCESS",
        summary_message="Test run completed successfully",
    )
    mgr.log_run(run_log)

    with open(test_json, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert len(data["run_history"]) == 1
    assert data["run_history"][0]["run_id"] == "run_test_99"
    assert data["dashboard"]["total_qualified_leads"] == 2
    assert data["dashboard"]["high_priority_count"] == 1
    assert data["dashboard"]["medium_priority_count"] == 1
