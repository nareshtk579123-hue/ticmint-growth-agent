"""
Configuration and settings management for Ticmint Growth Agent.
Loads configuration from environment variables and provides structured defaults.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Load .env file from project root if present
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Config:
    """Application configuration."""

    # Project Paths
    ROOT_DIR: Path = PROJECT_ROOT
    DATA_DIR: Path = PROJECT_ROOT / "data"
    SAMPLE_SIGNALS_PATH: Path = DATA_DIR / "sample_signals.json"
    LABELED_SET_PATH: Path = DATA_DIR / "labeled_evaluation_set.json"
    LOCAL_SHEET_JSON_PATH: Path = DATA_DIR / "local_sheet_export.json"
    LOCAL_SHEET_CSV_PATH: Path = DATA_DIR / "local_sheet_export.csv"

    # LLM Settings (Gemini API)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

    # Google Sheets Settings
    GOOGLE_SERVICE_ACCOUNT_JSON: str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    GOOGLE_SERVICE_ACCOUNT_RAW_JSON: str = os.getenv("GOOGLE_SERVICE_ACCOUNT_RAW_JSON", "").strip()
    GOOGLE_SHEET_ID: str = os.getenv("GOOGLE_SHEET_ID", "").strip()

    # Agent Execution Controls
    RUN_MODE: str = os.getenv("RUN_MODE", "live").lower()
    DRY_RUN: bool = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")
    MAX_SIGNALS_PER_RUN: int = int(os.getenv("MAX_SIGNALS_PER_RUN", "25"))
    HTTP_TIMEOUT_SECONDS: float = float(os.getenv("HTTP_TIMEOUT_SECONDS", "12.0"))

    # Qualification Thresholds (100-point rubric)
    MIN_SCORE_QUALIFIED: int = int(os.getenv("MIN_LEAD_SCORE_QUALIFIED", "50"))
    MIN_SCORE_HIGH_PRIORITY: int = int(os.getenv("MIN_LEAD_SCORE_HIGH_PRIORITY", "75"))

    # Search queries for Hacker News Algolia API & communities
    TARGET_SEARCH_QUERIES: List[str] = [
        "\"event ticketing\" fees",
        "\"ticketing platform\" alternative",
        "\"event registration\" frustrated",
        "\"white label ticketing\" recommendation",
        "\"ticketing platform\" custom domain",
        "\"event organiser\" checkout issues",
        "Eventbrite alternative fees",
        "Luma alternative white label",
    ]

    # RSS Feeds for public event organizer blogs and communities
    RSS_FEEDS: List[str] = [
        "https://news.ycombinator.com/rss",
    ]

    # User Agent for HTTP requests
    USER_AGENT: str = "TicmintGrowthAgent/1.0 (+https://ticmint.com/growth-listener)"

    @classmethod
    def has_gemini_key(cls) -> bool:
        return bool(cls.GEMINI_API_KEY)

    @classmethod
    def has_google_sheets_config(cls) -> bool:
        has_auth = bool(cls.GOOGLE_SERVICE_ACCOUNT_RAW_JSON or (cls.GOOGLE_SERVICE_ACCOUNT_JSON and Path(cls.GOOGLE_SERVICE_ACCOUNT_JSON).exists()))
        return has_auth and bool(cls.GOOGLE_SHEET_ID)


config = Config()
