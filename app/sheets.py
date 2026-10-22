"""
Google Sheets Client and Local Storage Manager for Ticmint Growth Agent.
Handles idempotent lead upserts, run history auditing, and KPI dashboard management.
Provides automatic fallback to structured local JSON/CSV when Google API credentials are not configured.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from app.config import config
from app.models import AgentRunLog, LeadRecord

logger = logging.getLogger("ticmint.sheets")

TAB_LEADS = "Qualified Leads"
TAB_RUN_HISTORY = "Run History"
TAB_DASHBOARD = "Dashboard"


class SheetsManager:
    """Manages reading, upserting, and logging leads into Google Sheets or local persistent storage."""

    def __init__(
        self,
        spreadsheet_id: Optional[str] = None,
        service_account_json: Optional[str] = None,
        raw_service_json: Optional[str] = None,
    ):
        self.spreadsheet_id = spreadsheet_id or config.GOOGLE_SHEET_ID
        self.service_account_json = service_account_json or config.GOOGLE_SERVICE_ACCOUNT_JSON
        self.raw_service_json = raw_service_json or config.GOOGLE_SERVICE_ACCOUNT_RAW_JSON

        self.service = None
        self.is_live_google = False

        self._init_google_service()

    def _init_google_service(self):
        """Attempts to initialize authenticated Google Sheets API client."""
        if not self.spreadsheet_id:
            logger.info("No GOOGLE_SHEET_ID provided. SheetsManager running in Local Storage mode.")
            return

        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds = None
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]

            if self.raw_service_json:
                info = json.loads(self.raw_service_json)
                creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
            elif self.service_account_json and Path(self.service_account_json).exists():
                creds = service_account.Credentials.from_service_account_file(self.service_account_json, scopes=scopes)

            if creds:
                self.service = build("sheets", "v4", credentials=creds, cache_discovery=False)
                self.is_live_google = True
                logger.info("Successfully connected to Google Sheets API (Spreadsheet ID: %s)", self.spreadsheet_id)
                self._ensure_sheets_exist()
        except Exception as e:
            logger.warning("Could not initialize Google Sheets client: %s. Using Local Storage mode.", e)
            self.service = None
            self.is_live_google = False

    def _ensure_sheets_exist(self):
        """Creates the 3 tabs and headers if they do not exist in the Google Spreadsheet."""
        if not self.is_live_google or not self.service:
            return
        try:
            spreadsheet = self.service.spreadsheets().get(spreadsheetId=self.spreadsheet_id).execute()
            sheet_names = [s["properties"]["title"] for s in spreadsheet.get("sheets", [])]

            requests = []
            for tab_name in [TAB_LEADS, TAB_RUN_HISTORY, TAB_DASHBOARD]:
                if tab_name not in sheet_names:
                    requests.append({"addSheet": {"properties": {"title": tab_name}}})

            if requests:
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": requests}
                ).execute()
                logger.info("Created missing tabs in Google Sheet: %s", [r["addSheet"]["properties"]["title"] for r in requests])

            # Write headers if empty
            for tab_name, headers in [(TAB_LEADS, LeadRecord.sheet_headers()), (TAB_RUN_HISTORY, AgentRunLog.sheet_headers())]:
                result = self.service.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{tab_name}'!A1:Z1"
                ).execute()
                if not result.get("values"):
                    self.service.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"'{tab_name}'!A1",
                        valueInputOption="RAW",
                        body={"values": [headers]}
                    ).execute()
        except Exception as e:
            logger.error("Error ensuring tabs in Google Sheets: %s", e)

    def upsert_leads(self, leads: List[LeadRecord]) -> Dict[str, int]:
        """
        Idempotently inserts new leads or updates existing leads based on Lead ID.
        Preserves original First Seen and manual Review Status.
        """
        if self.is_live_google:
            return self._upsert_google_sheets(leads)
        return self._upsert_local(leads)

    def log_run(self, run_log: AgentRunLog):
        """Appends run execution audit record and updates dashboard metrics."""
        if self.is_live_google:
            self._log_run_google(run_log)
        else:
            self._log_run_local(run_log)

    # ------------------ Local Storage Implementation ------------------

    def _load_local_data(self) -> Dict[str, Any]:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        if config.LOCAL_SHEET_JSON_PATH.exists():
            try:
                with open(config.LOCAL_SHEET_JSON_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "leads": {},
            "run_history": [],
            "dashboard": {},
        }

    def _save_local_data(self, data: Dict[str, Any]):
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.LOCAL_SHEET_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        # Also write tabular CSV for convenient viewing/importing
        with open(config.LOCAL_SHEET_CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(LeadRecord.sheet_headers())
            for lead_dict in data.get("leads", {}).values():
                record = LeadRecord(**lead_dict)
                writer.writerow(record.to_sheet_row())

    def _upsert_local(self, leads: List[LeadRecord]) -> Dict[str, int]:
        data = self._load_local_data()
        existing_leads = data.get("leads", {})

        inserted_count = 0
        updated_count = 0

        for lead in leads:
            lid = lead.lead_id
            if lid in existing_leads:
                # Update existing lead: preserve first_seen and review_status
                prev = existing_leads[lid]
                lead.first_seen = prev.get("first_seen", lead.first_seen)
                lead.review_status = prev.get("review_status", lead.review_status)
                existing_leads[lid] = lead.model_dump()
                updated_count += 1
            else:
                existing_leads[lid] = lead.model_dump()
                inserted_count += 1

        data["leads"] = existing_leads
        self._update_local_dashboard(data)
        self._save_local_data(data)

        logger.info("Local storage upsert complete: %d inserted, %d updated", inserted_count, updated_count)
        return {"inserted": inserted_count, "updated": updated_count}

    def _log_run_local(self, run_log: AgentRunLog):
        data = self._load_local_data()
        history = data.get("run_history", [])
        history.insert(0, run_log.model_dump())
        data["run_history"] = history
        self._update_local_dashboard(data)
        self._save_local_data(data)

    def _update_local_dashboard(self, data: Dict[str, Any]):
        leads = data.get("leads", {})
        total_leads = len(leads)
        high_priority = sum(1 for l in leads.values() if l.get("priority") == "HIGH")
        medium_priority = sum(1 for l in leads.values() if l.get("priority") == "MEDIUM")

        category_counts: Dict[str, int] = {}
        for l in leads.values():
            cat = l.get("complaint_category", "none")
            category_counts[cat] = category_counts.get(cat, 0) + 1

        data["dashboard"] = {
            "total_qualified_leads": total_leads,
            "high_priority_count": high_priority,
            "medium_priority_count": medium_priority,
            "complaint_distribution": category_counts,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------ Google Sheets Implementation ------------------

    def _upsert_google_sheets(self, leads: List[LeadRecord]) -> Dict[str, int]:
        try:
            # 1. Read existing rows to index by Lead ID and find row numbers
            result = self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{TAB_LEADS}'!A:O"
            ).execute()

            rows = result.get("values", [])
            headers = rows[0] if rows else LeadRecord.sheet_headers()
            existing_id_map: Dict[str, int] = {}  # lead_id -> row_index (1-based)
            existing_row_data: Dict[str, List[str]] = {}

            for idx, r in enumerate(rows[1:], start=2):
                if r and len(r) > 0:
                    lead_id = r[0].strip()
                    existing_id_map[lead_id] = idx
                    existing_row_data[lead_id] = r

            inserted_rows = []
            updates = []
            inserted_count = 0
            updated_count = 0

            for lead in leads:
                lid = lead.lead_id
                if lid in existing_id_map:
                    row_idx = existing_id_map[lid]
                    old_row = existing_row_data[lid]
                    # Preserve First Seen (col 2, index 1) and Review Status (col 14, index 13)
                    if len(old_row) > 1 and old_row[1]:
                        lead.first_seen = old_row[1]
                    if len(old_row) > 13 and old_row[13]:
                        lead.review_status = old_row[13]

                    row_vals = lead.to_sheet_row()
                    updates.append({
                        "range": f"'{TAB_LEADS}'!A{row_idx}:O{row_idx}",
                        "values": [row_vals]
                    })
                    updated_count += 1
                else:
                    inserted_rows.append(lead.to_sheet_row())
                    inserted_count += 1

            # Execute batch update for existing rows
            if updates:
                self.service.spreadsheets().values().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"valueInputOption": "RAW", "data": updates}
                ).execute()

            # Append new rows
            if inserted_rows:
                self.service.spreadsheets().values().append(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{TAB_LEADS}'!A1",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": inserted_rows}
                ).execute()

            # Update dashboard tab with live formulas & summary
            self._update_google_dashboard()

            logger.info("Google Sheets upsert complete: %d inserted, %d updated", inserted_count, updated_count)
            return {"inserted": inserted_count, "updated": updated_count}

        except Exception as e:
            logger.error("Failed to upsert leads into Google Sheets: %s. Falling back to local copy.", e)
            return self._upsert_local(leads)

    def _log_run_google(self, run_log: AgentRunLog):
        try:
            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{TAB_RUN_HISTORY}'!A1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [run_log.to_sheet_row()]}
            ).execute()
        except Exception as e:
            logger.error("Failed to append run history to Google Sheets: %s", e)
            self._log_run_local(run_log)

    def _update_google_dashboard(self):
        """Populates Tab 3 (Dashboard) with high-level KPI formulas and metrics."""
        try:
            dashboard_rows = [
                ["TICMINT GROWTH INTELLIGENCE DASHBOARD", ""],
                ["Last Refresh", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")],
                ["", ""],
                ["Key Metric", "Live Value"],
                ["Total Qualified Leads Tracked", f"=COUNTA('{TAB_LEADS}'!A2:A)"],
                ["High Priority Leads (Score >= 75)", f'=COUNTIF(\'{TAB_LEADS}\'!L2:L, "HIGH")'],
                ["Medium Priority Leads (50-74)", f'=COUNTIF(\'{TAB_LEADS}\'!L2:L, "MEDIUM")'],
                ["Pending Human Review", f'=COUNTIF(\'{TAB_LEADS}\'!N2:N, "PENDING_HUMAN_REVIEW")'],
                ["", ""],
                ["Complaint Breakdown", "Count"],
                ["Fees & Extortion", f'=COUNTIF(\'{TAB_LEADS}\'!H2:H, "fees_extortion")'],
                ["Branding Limitations", f'=COUNTIF(\'{TAB_LEADS}\'!H2:H, "branding_limitation")'],
                ["Data Lock-in & Ownership", f'=COUNTIF(\'{TAB_LEADS}\'!H2:H, "data_lockin")'],
                ["Checkout Drop-off", f'=COUNTIF(\'{TAB_LEADS}\'!H2:H, "checkout_conversion")'],
                ["Payout / Escrow Delays", f'=COUNTIF(\'{TAB_LEADS}\'!H2:H, "payment_payout_delays")'],
                ["APIs / Webhooks", f'=COUNTIF(\'{TAB_LEADS}\'!H2:H, "integrations_apis")'],
            ]
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{TAB_DASHBOARD}'!A1",
                valueInputOption="USER_ENTERED",
                body={"values": dashboard_rows}
            ).execute()
        except Exception as e:
            logger.warning("Could not refresh dashboard tab in Google Sheets: %s", e)
