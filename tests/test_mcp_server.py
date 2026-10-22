"""
Integration tests for custom MCP Server 'ticmint_signal_server'.
Directly invokes all registered tools via server.call_tool to verify schemas and execution.
"""

from __future__ import annotations

import json
import pytest
from app.mcp_server import server
from app.sheets import SheetsManager
from app.models import (
    AgentRunLog,
    BuyerFit,
    ComplaintCategory,
    IntentCategory,
    LeadRecord,
    PriorityLevel,
    RawSignal,
    ScoreBreakdown,
    SignalAnalysis,
)


@pytest.mark.asyncio
async def test_search_public_signals_tool():
    result = await server.call_tool(
        "search_public_signals",
        {"query": "event ticketing", "limit": 3}
    )
    assert not result.is_error
    raw_text = result.content[0].text
    data = json.loads(raw_text)
    assert "count" in data
    assert "signals" in data
    assert isinstance(data["signals"], list)


@pytest.mark.asyncio
async def test_deduplicate_signals_tool():
    sig_data = [
        {
            "source": "hacker_news",
            "source_id": "hn_1",
            "author": "user1",
            "text": "Discussion text",
            "url": "https://news.ycombinator.com/item?id=1",
            "canonical_url": "https://news.ycombinator.com/item?id=1",
            "published_at": "2026-10-18T10:00:00Z"
        },
        {
            "source": "hacker_news",
            "source_id": "hn_1",
            "author": "user1",
            "text": "Discussion text",
            "url": "https://news.ycombinator.com/item?id=1&utm_source=twitter",
            "canonical_url": "https://news.ycombinator.com/item?id=1",
            "published_at": "2026-10-18T10:00:00Z"
        }
    ]

    result = await server.call_tool(
        "deduplicate_signals",
        {"signals_json": json.dumps(sig_data)}
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["original_count"] == 2
    assert data["deduplicated_count"] == 1


@pytest.mark.asyncio
async def test_score_lead_tool():
    sig = RawSignal(
        source="hacker_news",
        source_id="hn_99",
        author="conf_lead",
        text="We host an annual tech conference. Eventbrite fees are killing us.",
        url="https://news.ycombinator.com/item?id=99",
        canonical_url="https://news.ycombinator.com/item?id=99",
        published_at="2026-10-18T10:00:00Z",
    )
    ana = SignalAnalysis(
        is_event_related=True,
        has_ticketing_pain=True,
        complaint_category=ComplaintCategory.FEES_EXTORTION,
        intent=IntentCategory.EVALUATING_ALTERNATIVES,
        buyer_fit=BuyerFit.HIGH,
        evidence_quote="Eventbrite fees are killing us",
        reasoning="Qualified organizer lead",
        outreach_draft="Hi conf_lead...",
        needs_human_review=True,
    )

    result = await server.call_tool(
        "score_lead",
        {
            "signal_json": json.dumps(sig.model_dump()),
            "analysis_json": json.dumps(ana.model_dump())
        }
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["total_score"] >= 75
    assert data["priority"] == "HIGH"


@pytest.mark.asyncio
async def test_upsert_sheet_leads_tool(tmp_path, monkeypatch):
    import app.config as cfg
    import app.mcp_server as mcp
    monkeypatch.setattr(cfg.config, "LOCAL_SHEET_JSON_PATH", tmp_path / "sheet.json")
    monkeypatch.setattr(cfg.config, "LOCAL_SHEET_CSV_PATH", tmp_path / "sheet.csv")
    monkeypatch.setattr(cfg.config, "GOOGLE_SHEET_ID", "")
    monkeypatch.setattr(mcp, "_sheets_mgr", SheetsManager())

    breakdown = ScoreBreakdown(
        ticketing_pain=28, switching_intent=25, icp_fit=20, recency=10, evidence_quality=8,
        total_score=91, priority=PriorityLevel.HIGH, qualification_notes=["Top tier"]
    )
    lead = LeadRecord(
        lead_id="test_lead_mcp",
        first_seen="2026-10-18T10:00:00Z",
        last_seen="2026-10-18T10:00:00Z",
        source="hacker_news",
        author="alice",
        source_url="https://example.com/test",
        evidence_quote="Fees are high",
        complaint_category="fees_extortion",
        intent="evaluating_alternatives",
        buyer_fit="high",
        lead_score=91,
        priority="HIGH",
        score_breakdown=breakdown,
        outreach_draft="Hi Alice...",
        review_status="PENDING_HUMAN_REVIEW",
        last_updated="2026-10-18T10:00:00Z",
    )

    result = await server.call_tool(
        "upsert_sheet_leads",
        {"leads_json": json.dumps([lead.model_dump()])}
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["status"] == "success"
    assert data["result"]["inserted"] == 1


@pytest.mark.asyncio
async def test_log_agent_run_tool(tmp_path, monkeypatch):
    import app.config as cfg
    import app.mcp_server as mcp
    monkeypatch.setattr(cfg.config, "LOCAL_SHEET_JSON_PATH", tmp_path / "sheet.json")
    monkeypatch.setattr(cfg.config, "LOCAL_SHEET_CSV_PATH", tmp_path / "sheet.csv")
    monkeypatch.setattr(cfg.config, "GOOGLE_SHEET_ID", "")
    monkeypatch.setattr(mcp, "_sheets_mgr", SheetsManager())

    run_log = AgentRunLog(
        run_id="run_mcp_01",
        started_at="2026-10-20T12:00:00Z",
        completed_at="2026-10-20T12:01:00Z",
        sources_checked=2,
        records_retrieved=10,
        duplicates_filtered=2,
        qualified_leads=1,
        high_priority_leads=1,
        llm_errors=0,
        sheet_errors=0,
        run_status="SUCCESS",
        summary_message="MCP test run logged successfully",
    )

    result = await server.call_tool(
        "log_agent_run",
        {"run_log_json": json.dumps(run_log.model_dump())}
    )
    assert not result.is_error
    data = json.loads(result.content[0].text)
    assert data["status"] == "success"
    assert data["run_id"] == "run_mcp_01"
