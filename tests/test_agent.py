"""
End-to-end integration tests for TicmintGrowthAgent execution runner.
"""

from __future__ import annotations

import pytest
from app.agent import TicmintGrowthAgent
from app.config import config


@pytest.mark.asyncio
async def test_agent_dry_run():
    agent = TicmintGrowthAgent(dry_run=True, max_signals=5)
    run_log = await agent.run(search_queries=['"white label ticketing"'])

    assert run_log.run_status == "SUCCESS"
    assert run_log.sources_checked == 1
    assert run_log.records_retrieved > 0
    assert run_log.llm_errors == 0
    assert run_log.sheet_errors == 0


@pytest.mark.asyncio
async def test_agent_live_local_execution():
    agent = TicmintGrowthAgent(dry_run=False, max_signals=5)
    run_log = await agent.run(search_queries=['"event ticketing" fees'])

    assert run_log.run_status == "SUCCESS"
    assert run_log.qualified_leads > 0
    assert config.LOCAL_SHEET_JSON_PATH.exists()
    assert config.LOCAL_SHEET_CSV_PATH.exists()
