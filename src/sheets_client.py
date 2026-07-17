from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Iterable

import gspread
from google.oauth2.service_account import Credentials

from .models import Company, CuratedRelease
from .settings import Settings, validate_service_account_json


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

COMPANY_HEADERS = [
    "company_name",
    "list_url",
    "enabled",
    "source_type",
    "config_json",
    "notes",
]

RELEASE_HEADERS = [
    "published_on",
    "company_name",
    "title",
    "paragraph",
    "url",
    "fetched_at",
    "decision_reason",
    "original_title",
]


class SheetsClient:
    def __init__(self, settings: Settings) -> None:
        info = validate_service_account_json(settings.google_service_account_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        self._gc = gspread.authorize(creds)
        self._book = self._gc.open_by_key(settings.spreadsheet_id)
        self.companies_sheet_name = settings.companies_sheet
        self.releases_sheet_name = settings.releases_sheet

    def ensure_schema(self) -> None:
        self._ensure_worksheet(self.companies_sheet_name, COMPANY_HEADERS)
        self._ensure_worksheet(self.releases_sheet_name, RELEASE_HEADERS)

    def _ensure_worksheet(self, title: str, headers: list[str]) -> gspread.Worksheet:
        try:
            ws = self._book.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self._book.add_worksheet(title=title, rows=2000, cols=len(headers) + 2)
            ws.append_row(headers, value_input_option="USER_ENTERED")
            return ws

        existing = ws.row_values(1)
        if existing != headers:
            if not existing:
                ws.append_row(headers, value_input_option="USER_ENTERED")
            else:
                # Keep existing headers if already present; do not clobber user edits.
                pass
        return ws

    def load_companies(self) -> list[Company]:
        ws = self._book.worksheet(self.companies_sheet_name)
        rows = ws.get_all_records()
        companies: list[Company] = []
        for row in rows:
            name = str(row.get("company_name") or "").strip()
            list_url = str(row.get("list_url") or "").strip()
            source_type = str(row.get("source_type") or "").strip()
            if not (name and list_url and source_type):
                continue
            enabled_raw = str(row.get("enabled") or "TRUE").strip().lower()
            enabled = enabled_raw in {"1", "true", "yes", "y", "有効"}
            config_raw = str(row.get("config_json") or "").strip()
            config = json.loads(config_raw) if config_raw else {}
            companies.append(
                Company(
                    name=name,
                    list_url=list_url,
                    enabled=enabled,
                    source_type=source_type,
                    config=config,
                    notes=str(row.get("notes") or ""),
                )
            )
        return companies

    def seed_companies_if_empty(self, companies: Iterable[Company]) -> int:
        existing = self.load_companies()
        if existing:
            return 0
        ws = self._book.worksheet(self.companies_sheet_name)
        values = [COMPANY_HEADERS]
        for company in companies:
            values.append(
                [
                    company.name,
                    company.list_url,
                    "TRUE" if company.enabled else "FALSE",
                    company.source_type,
                    json.dumps(company.config, ensure_ascii=False),
                    company.notes,
                ]
            )
        ws.clear()
        ws.update(range_name="A1", values=values, value_input_option="USER_ENTERED")
        return len(values) - 1

    def existing_urls(self) -> set[str]:
        ws = self._book.worksheet(self.releases_sheet_name)
        records = ws.get_all_records()
        urls: set[str] = set()
        for row in records:
            url = str(row.get("url") or "").strip()
            if url:
                urls.add(url)
        return urls

    def append_releases(self, releases: list[CuratedRelease]) -> int:
        if not releases:
            return 0
        ws = self._book.worksheet(self.releases_sheet_name)
        rows = []
        for item in releases:
            rows.append(
                [
                    item.published_on.isoformat(),
                    item.company,
                    item.title,
                    item.paragraph,
                    item.url,
                    item.fetched_at.replace(tzinfo=timezone.utc).isoformat(),
                    item.reason,
                    item.original_title,
                ]
            )
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        return len(rows)
