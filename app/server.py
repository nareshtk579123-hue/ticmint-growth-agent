"""
FastAPI Server & Real-Time Event Hub for Ticmint Growth Intelligence Agent.
Serves the modern frontend dashboard and streams live execution progress over Server-Sent Events (SSE).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from app.agent import TicmintGrowthAgent
from app.config import config
from app.models import AgentRunLog, LeadRecord
from app.sheets import SheetsManager

logger = logging.getLogger("ticmint.server")

app = FastAPI(title="Ticmint Growth Intelligence Dashboard", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

# Broadcaster queue list for connected SSE clients
_subscribers: List[asyncio.Queue] = []
_current_agent_task: asyncio.Task | None = None
_latest_run_state: Dict[str, Any] = {
    "is_running": False,
    "current_stage": "idle",
    "progress_percent": 0,
    "status_message": "Ready to launch",
    "logs": [],
}


async def broadcast_event(event_type: str, data: Dict[str, Any]):
    """Broadcasts a structured event to all active SSE browser connections."""
    message = json.dumps({"event": event_type, "data": data})
    for q in list(_subscribers):
        try:
            await q.put(message)
        except Exception:
            if q in _subscribers:
                _subscribers.remove(q)


async def agent_progress_bridge(event_type: str, data: Dict[str, Any]):
    """Bridges agent callback events into the live web broadcast queue and state store."""
    stage = _latest_run_state.get("current_stage", "idle")
    progress = _latest_run_state.get("progress_percent", 0)
    msg = ""

    if event_type == "run_started":
        stage = "mcp_handshake"
        progress = 10
        msg = f"Connecting to MCP Server 'ticmint_signal_server' (Run ID: {data.get('run_id')})..."
    elif event_type == "mcp_connected":
        stage = "querying_sources"
        progress = 20
        msg = f"MCP Server initialized. Tools available: {len(data.get('tools', []))}. Starting public signal search..."
    elif event_type == "query_started":
        msg = f"Querying Hacker News Algolia API: {data.get('query')}"
        progress = min(progress + 5, 40)
    elif event_type == "query_completed":
        msg = f"Found {data.get('count')} signals for query. Total pool: {data.get('total_pool')} records."
    elif event_type == "dedup_started":
        stage = "deduplicating"
        progress = 45
        msg = f"Deduplicating {data.get('total_collected')} collected signals using canonical URLs..."
    elif event_type == "dedup_completed":
        stage = "ai_analysis"
        progress = 55
        msg = f"Deduplication complete. {data.get('unique_count')} unique discussions retained ({data.get('duplicates_filtered')} duplicates removed)."
    elif event_type == "analysis_started":
        msg = f"Beginning Gemini AI intent classification & pain point extraction on {data.get('target_count')} signals..."
        progress = 60
    elif event_type == "signal_evaluated":
        author = data.get("author")
        score = data.get("score")
        tier = data.get("priority")
        category = data.get("category")
        is_qual = data.get("is_qualified")
        msg = f"Evaluated @{author}: Score {score}/100 [{tier}] - Category: {category} ({'QUALIFIED' if is_qual else 'FILTERED'})"
        progress = min(60 + int((data.get("index", 1) / max(data.get("total", 1), 1)) * 25), 85)
    elif event_type == "sheet_sync_started":
        stage = "google_sheets_sync"
        progress = 90
        msg = f"Synchronizing {data.get('count')} qualified leads to Google Sheets (Tab: 'Qualified Leads')..."
    elif event_type == "sheet_sync_completed":
        res = data.get("result", {})
        msg = f"Google Sheets updated successfully: {res.get('inserted', 0)} inserted, {res.get('updated', 0)} updated."
        progress = 95
    elif event_type == "run_completed":
        stage = "completed"
        progress = 100
        _latest_run_state["is_running"] = False
        msg = "Run completed successfully! Google Sheets & Dashboard refreshed."

    _latest_run_state["current_stage"] = stage
    _latest_run_state["progress_percent"] = progress
    _latest_run_state["status_message"] = msg
    _latest_run_state["logs"].append({"timestamp": data.get("timestamp"), "event": event_type, "message": msg})

    await broadcast_event(event_type, {
        "stage": stage,
        "progress": progress,
        "message": msg,
        "payload": data,
    })


@app.get("/api/config")
async def get_config():
    """Returns application configuration details."""
    return {
        "spreadsheet_id": config.GOOGLE_SHEET_ID,
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEET_ID}/edit" if config.GOOGLE_SHEET_ID else None,
        "has_google_auth": config.has_google_sheets_config(),
        "gemini_model": config.GEMINI_MODEL,
        "has_gemini_key": config.has_gemini_key(),
        "min_qualified_score": config.MIN_SCORE_QUALIFIED,
        "min_high_priority_score": config.MIN_SCORE_HIGH_PRIORITY,
    }


@app.get("/api/leads")
async def get_leads():
    """Returns stored leads from Google Sheets or local storage."""
    mgr = SheetsManager()
    local_data = mgr._load_local_data()
    leads_dict = local_data.get("leads", {})
    leads_list = list(leads_dict.values())
    leads_list.sort(key=lambda x: x.get("lead_score", 0), reverse=True)
    return {
        "count": len(leads_list),
        "leads": leads_list,
        "dashboard": local_data.get("dashboard", {}),
    }


@app.get("/api/history")
async def get_history():
    """Returns run execution history."""
    mgr = SheetsManager()
    local_data = mgr._load_local_data()
    return {
        "history": local_data.get("run_history", [])[:15],
    }


@app.post("/api/run")
async def trigger_run(request: Request):
    """Triggers an agent run."""
    global _current_agent_task, _latest_run_state

    if _latest_run_state.get("is_running", False):
        return {"status": "busy", "message": "An agent run is already in progress."}

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    limit = int(body.get("limit", 10))
    query = body.get("query", "").strip() or None
    queries = [query] if query else None

    _latest_run_state["is_running"] = True
    _latest_run_state["current_stage"] = "starting"
    _latest_run_state["progress_percent"] = 5
    _latest_run_state["status_message"] = "Initializing agent..."
    _latest_run_state["logs"] = []

    async def run_task():
        agent = TicmintGrowthAgent(dry_run=False, max_signals=limit, callback=agent_progress_bridge)
        try:
            await agent.run(search_queries=queries)
        except Exception as e:
            logger.error("Agent execution error: %s", e)
            await broadcast_event("run_failed", {"error": str(e)})
            _latest_run_state["is_running"] = False
            _latest_run_state["current_stage"] = "failed"
            _latest_run_state["status_message"] = f"Error: {str(e)}"

    _current_agent_task = asyncio.create_task(run_task())
    return {"status": "started", "message": "Agent execution initiated."}


@app.get("/api/events")
async def event_stream():
    """Server-Sent Events endpoint streaming live progress and log updates."""
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.append(queue)

    async def event_generator() -> AsyncGenerator[str, None]:
        # Send initial state snapshot
        init_payload = json.dumps({"event": "initial_state", "data": _latest_run_state})
        yield f"data: {init_payload}\n\n"
        try:
            while True:
                data = await queue.get()
                yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in _subscribers:
                _subscribers.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# Mount static files and root fallback
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Ticmint Dashboard - Static files not found</h1>"


def run():
    import os
    port = int(os.getenv("PORT", "8080"))
    logger.info("Starting Ticmint Dashboard at http://127.0.0.1:%d", port)
    uvicorn.run("app.server:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    run()
