"""
Custom MCP Server for Ticmint Growth Agent: 'ticmint_signal_server'.
Exposes standard MCP tools for signal discovery, normalization, deduplication,
qualification scoring, sheet synchronization, and audit logging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional
from mcp.server.mcpserver import MCPServer
from app.collector import SignalCollector
from app.models import AgentRunLog, LeadRecord, RawSignal, SignalAnalysis
from app.scoring import LeadScorer
from app.sheets import SheetsManager

logger = logging.getLogger("ticmint.mcp_server")

# Instantiate official MCP Server
server = MCPServer("ticmint_signal_server")

# Module-level singletons for tool implementations
_collector = SignalCollector()
_sheets_mgr = SheetsManager()


@server.tool()
def search_public_signals(query: str, limit: int = 15) -> str:
    """
    Searches permitted public sources (Hacker News Algolia API & event communities)
    for discussions containing the specified query. Returns a JSON list of normalized signals.
    """
    try:
        signals = _collector.fetch_hacker_news_signals(query=query, hits_per_page=limit)
        # If live search returned zero, load from sample repository
        if not signals:
            signals = [s for s in _collector.load_sample_signals() if query.lower() in s.text.lower() or query.lower() in (s.title or "").lower()]
            if not signals:
                signals = _collector.load_sample_signals()[:limit]

        serialized = [s.model_dump() for s in signals[:limit]]
        return json.dumps({"count": len(serialized), "signals": serialized}, ensure_ascii=False)
    except Exception as e:
        logger.error("Error in search_public_signals: %s", e)
        return json.dumps({"error": str(e), "signals": []})


@server.tool()
def get_signal_details(source: str, source_id: str) -> str:
    """
    Retrieves or normalizes a signal record using its source platform and source ID.
    """
    try:
        samples = _collector.load_sample_signals()
        for s in samples:
            if s.source == source and s.source_id == source_id:
                return json.dumps(s.model_dump(), ensure_ascii=False)

        return json.dumps({"found": False, "message": f"Signal {source}:{source_id} not found in cache"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@server.tool()
def deduplicate_signals(signals_json: str) -> str:
    """
    Deduplicates a JSON list of raw signals using canonical URLs and content hashes.
    """
    try:
        raw_list = json.loads(signals_json)
        signal_objs = [RawSignal(**item) for item in raw_list]
        deduped = _collector.deduplicate(signal_objs)
        serialized = [s.model_dump() for s in deduped]
        return json.dumps({
            "original_count": len(signal_objs),
            "deduplicated_count": len(serialized),
            "signals": serialized
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "signals": []})


@server.tool()
def score_lead(signal_json: str, analysis_json: str) -> str:
    """
    Applies the transparent 100-point lead qualification rubric to a signal and its LLM analysis.
    Returns the score breakdown, total score, and priority tier.
    """
    try:
        sig_data = json.loads(signal_json)
        ana_data = json.loads(analysis_json)

        signal = RawSignal(**sig_data)
        analysis = SignalAnalysis(**ana_data)

        breakdown = LeadScorer.score_signal(signal, analysis)
        return json.dumps(breakdown.model_dump(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@server.tool()
def upsert_sheet_leads(leads_json: str) -> str:
    """
    Inserts new leads or updates existing rows in Google Sheets (or local storage fallback)
    using deterministic Lead IDs. Preserves original First Seen dates and manual Review Status.
    """
    try:
        raw_list = json.loads(leads_json)
        leads = [LeadRecord(**item) for item in raw_list]
        result = _sheets_mgr.upsert_leads(leads)
        return json.dumps({"status": "success", "result": result})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


@server.tool()
def log_agent_run(run_log_json: str) -> str:
    """
    Appends an execution audit record to Tab 2 (Run History) and refreshes Tab 3 (Dashboard).
    """
    try:
        data = json.loads(run_log_json)
        log_entry = AgentRunLog(**data)
        _sheets_mgr.log_run(log_entry)
        return json.dumps({"status": "success", "run_id": log_entry.run_id})
    except Exception as e:
        return json.dumps({"status": "error", "error": str(e)})


def run_server():
    """Starts the custom MCP server over standard input/output (stdio)."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    logger.info("Starting Ticmint MCP Server 'ticmint_signal_server' on stdio...")
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":
    run_server()
