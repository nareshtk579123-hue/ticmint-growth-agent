"""
Ticmint Growth Intelligence Agent Runner.
Launches the custom MCP server as a subprocess, connects via the official MCP ClientSession,
and orchestrates the end-to-end signal collection, AI analysis, scoring, and sheet synchronization.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from app.config import config
from app.llm import LLMAnalyzer
from app.models import AgentRunLog, LeadRecord, RawSignal, ScoreBreakdown, SignalAnalysis

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ticmint.agent")


class TicmintGrowthAgent:
    """Autonomous Growth Engineering Agent connecting to custom MCP Server."""

    def __init__(self, dry_run: bool = False, max_signals: int = 25):
        self.dry_run = dry_run
        self.max_signals = max_signals
        self.llm = LLMAnalyzer()

    async def run(self, search_queries: Optional[List[str]] = None) -> AgentRunLog:
        """
        Executes the full agent lifecycle through the custom MCP server:
        1. Query public channels via MCP tool 'search_public_signals'
        2. Deduplicate signals via MCP tool 'deduplicate_signals'
        3. Perform AI reasoning & intent classification
        4. Score leads via MCP tool 'score_lead' (100-point rubric)
        5. Synchronize leads via MCP tool 'upsert_sheet_leads'
        6. Record execution audit via MCP tool 'log_agent_run'
        """
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(timezone.utc).isoformat()
        queries = search_queries or config.TARGET_SEARCH_QUERIES[:4]

        logger.info("=== Starting Ticmint Growth Agent Run [%s] ===", run_id)
        logger.info("Target search queries: %s", queries)

        records_retrieved = 0
        duplicates_filtered = 0
        qualified_leads: List[LeadRecord] = []
        high_priority_count = 0
        llm_errors = 0
        sheet_errors = 0
        run_status = "SUCCESS"

        # Define server subprocess parameters
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server"],
            env=None
        )

        try:
            async with stdio_client(server_params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools_resp = await session.list_tools()
                    registered_names = [t.name for t in tools_resp.tools]
                    logger.info("Connected to MCP Server. Available tools: %s", registered_names)

                    # 1. Search public signals across queries via MCP Tool
                    raw_signals_pool: List[Dict[str, Any]] = []
                    for query in queries:
                        logger.info("Invoking MCP tool 'search_public_signals' for: '%s'", query)
                        tool_result = await session.call_tool(
                            "search_public_signals",
                            {"query": query, "limit": 10}
                        )
                        content_text = tool_result.content[0].text if tool_result.content else "{}"
                        res_data = json.loads(content_text)
                        signals_found = res_data.get("signals", [])
                        raw_signals_pool.extend(signals_found)
                        logger.info("Retrieved %d signals for query '%s'", len(signals_found), query)

                    records_retrieved = len(raw_signals_pool)

                    # 2. Deduplicate signals via MCP Tool
                    logger.info("Invoking MCP tool 'deduplicate_signals' on %d collected records", records_retrieved)
                    dedup_result = await session.call_tool(
                        "deduplicate_signals",
                        {"signals_json": json.dumps(raw_signals_pool)}
                    )
                    dedup_data = json.loads(dedup_result.content[0].text)
                    unique_signals_dict = dedup_data.get("signals", [])
                    duplicates_filtered = records_retrieved - len(unique_signals_dict)
                    logger.info("Deduplication complete: %d unique records retained (%d duplicates removed)",
                                len(unique_signals_dict), duplicates_filtered)

                    # Truncate to maximum configured signals
                    target_signals = [RawSignal(**s) for s in unique_signals_dict[:self.max_signals]]

                    # 3. AI Intent Classification & Scoring
                    for sig in target_signals:
                        try:
                            # AI Analysis
                            analysis: SignalAnalysis = self.llm.analyze_signal(sig)

                            # Score Lead via MCP Tool
                            score_res = await session.call_tool(
                                "score_lead",
                                {
                                    "signal_json": json.dumps(sig.model_dump()),
                                    "analysis_json": json.dumps(analysis.model_dump())
                                }
                            )
                            score_dict = json.loads(score_res.content[0].text)
                            score_breakdown = ScoreBreakdown(**score_dict)

                            # If qualified (score >= 50), build LeadRecord
                            if score_breakdown.total_score >= config.MIN_SCORE_QUALIFIED:
                                lead_id = RawSignal.generate_lead_id(sig.source, sig.canonical_url)
                                now_iso = datetime.now(timezone.utc).isoformat()

                                lead_record = LeadRecord(
                                    lead_id=lead_id,
                                    first_seen=sig.published_at,
                                    last_seen=now_iso,
                                    source=sig.source,
                                    author=sig.author,
                                    source_url=sig.url,
                                    evidence_quote=analysis.evidence_quote,
                                    complaint_category=analysis.complaint_category.value,
                                    intent=analysis.intent.value,
                                    buyer_fit=analysis.buyer_fit.value,
                                    lead_score=score_breakdown.total_score,
                                    priority=score_breakdown.priority.value,
                                    score_breakdown=score_breakdown,
                                    outreach_draft=analysis.outreach_draft,
                                    review_status="PENDING_HUMAN_REVIEW",
                                    last_updated=now_iso,
                                )
                                qualified_leads.append(lead_record)
                                if score_breakdown.priority.value == "HIGH":
                                    high_priority_count += 1
                                logger.info("Qualified Lead [%s]: Score=%d, Priority=%s, Author=%s",
                                            lead_id, score_breakdown.total_score, score_breakdown.priority.value, sig.author)
                        except Exception as e:
                            llm_errors += 1
                            logger.error("Error analyzing signal %s: %s", sig.source_id, e)

                    # 4. Synchronize Qualified Leads to Google Sheets / Local Storage via MCP Tool
                    if not self.dry_run and qualified_leads:
                        logger.info("Invoking MCP tool 'upsert_sheet_leads' with %d leads", len(qualified_leads))
                        leads_payload = json.dumps([l.model_dump() for l in qualified_leads])
                        upsert_res = await session.call_tool(
                            "upsert_sheet_leads",
                            {"leads_json": leads_payload}
                        )
                        upsert_data = json.loads(upsert_res.content[0].text)
                        if upsert_data.get("status") == "error":
                            sheet_errors += 1
                            run_status = "WARNING"
                            logger.error("Sheet upsert error: %s", upsert_data.get("error"))
                    elif self.dry_run:
                        logger.info("[DRY RUN] Skipping sheet synchronization for %d qualified leads", len(qualified_leads))

                    # 5. Log Run History & Summary via MCP Tool
                    completed_at = datetime.now(timezone.utc).isoformat()
                    summary_msg = (
                        f"Processed {len(target_signals)} signals across {len(queries)} queries. "
                        f"Identified {len(qualified_leads)} qualified leads ({high_priority_count} HIGH priority). "
                        f"LLM errors: {llm_errors}, Sheet errors: {sheet_errors}."
                    )

                    run_log = AgentRunLog(
                        run_id=run_id,
                        started_at=started_at,
                        completed_at=completed_at,
                        sources_checked=len(queries),
                        records_retrieved=records_retrieved,
                        duplicates_filtered=duplicates_filtered,
                        qualified_leads=len(qualified_leads),
                        high_priority_leads=high_priority_count,
                        llm_errors=llm_errors,
                        sheet_errors=sheet_errors,
                        run_status=run_status,
                        summary_message=summary_msg,
                    )

                    if not self.dry_run:
                        await session.call_tool(
                            "log_agent_run",
                            {"run_log_json": json.dumps(run_log.model_dump())}
                        )

                    logger.info("=== Run [%s] Finished: %s ===", run_id, run_status)
                    self._print_terminal_summary(run_log, qualified_leads)
                    return run_log

        except Exception as e:
            logger.critical("Fatal failure in agent execution: %s", e, exc_info=True)
            completed_at = datetime.now(timezone.utc).isoformat()
            run_log = AgentRunLog(
                run_id=run_id,
                started_at=started_at,
                completed_at=completed_at,
                sources_checked=len(queries),
                records_retrieved=records_retrieved,
                duplicates_filtered=duplicates_filtered,
                qualified_leads=len(qualified_leads),
                high_priority_leads=high_priority_count,
                llm_errors=llm_errors,
                sheet_errors=sheet_errors + 1,
                run_status="FAILED",
                summary_message=f"Fatal exception: {str(e)}",
            )
            return run_log

    def _print_terminal_summary(self, run_log: AgentRunLog, leads: List[LeadRecord]):
        """Prints a human-readable summary table to stdout."""
        print("\n" + "=" * 78)
        print("           TICMINT GROWTH INTELLIGENCE RUN SUMMARY")
        print("=" * 78)
        print(f"Run ID:              {run_log.run_id}")
        print(f"Status:              {run_log.run_status}")
        print(f"Sources Queried:     {run_log.sources_checked}")
        print(f"Signals Ingested:    {run_log.records_retrieved}")
        print(f"Duplicates Filtered: {run_log.duplicates_filtered}")
        print(f"Qualified Leads:     {run_log.qualified_leads}")
        print(f"High-Priority Leads: {run_log.high_priority_leads}")
        print(f"Started At:          {run_log.started_at}")
        print(f"Completed At:        {run_log.completed_at}")
        print("-" * 78)

        if leads:
            print("TOP QUALIFIED LEADS IDENTIFIED:")
            sorted_leads = sorted(leads, key=lambda x: x.lead_score, reverse=True)
            for idx, lead in enumerate(sorted_leads[:5], start=1):
                print(f"\n[{idx}] Score: {lead.lead_score}/100 | Tier: {lead.priority} | Category: {lead.complaint_category}")
                print(f"    Author:  {lead.author} ({lead.source})")
                print(f"    URL:     {lead.source_url}")
                print(f"    Quote:   \"{lead.evidence_quote[:85]}...\"" if len(lead.evidence_quote) > 85 else f"    Quote:   \"{lead.evidence_quote}\"")
                print(f"    Draft:   {lead.outreach_draft[:110]}...")
        else:
            print("No new leads scored >= 50 in this execution run.")

        print("=" * 78 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Ticmint Growth Intelligence Agent")
    parser.add_argument("--dry-run", action="store_true", help="Run without persisting to sheets or disk")
    parser.add_argument("--limit", type=int, default=25, help="Maximum signals to process")
    parser.add_argument("--query", type=str, default="", help="Optional single search query override")

    args = parser.parse_args()
    queries = [args.query] if args.query else None

    agent = TicmintGrowthAgent(dry_run=args.dry_run, max_signals=args.limit)
    run_log = asyncio.run(agent.run(search_queries=queries))

    if run_log.run_status == "FAILED":
        sys.exit(1)


if __name__ == "__main__":
    main()
