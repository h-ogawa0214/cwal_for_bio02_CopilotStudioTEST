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
    "stock_code",
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
    "reference_url",
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
                missing = [header for header in headers if header not in existing]
                if missing:
                    start_col = len(existing) + 1
                    ws.update(
                        range_name=gspread.utils.rowcol_to_a1(1, start_col),
                        values=[missing],
                        value_input_option="USER_ENTERED",
                    )
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
                    stock_code=str(row.get("stock_code") or "").strip(),
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
            values.append(self._company_row(company))
        ws.clear()
        ws.update(range_name="A1", values=values, value_input_option="USER_ENTERED")
        return len(values) - 1

    def sync_companies(self, companies: Iterable[Company]) -> dict[str, int]:
        """Append missing companies and fill blank stock_code on existing rows."""
        self.ensure_schema()
        ws = self._book.worksheet(self.companies_sheet_name)
        values = ws.get_all_values()
        if not values:
            ws.update(
                range_name="A1",
                values=[COMPANY_HEADERS],
                value_input_option="USER_ENTERED",
            )
            values = [COMPANY_HEADERS]

        headers = values[0]
        # Ensure expected headers exist (ensure_schema may have appended at end).
        header_index = {name: idx for idx, name in enumerate(headers)}
        name_idx = header_index.get("company_name", 0)
        stock_idx = header_index.get("stock_code")

        existing_names = {
            row[name_idx].strip()
            for row in values[1:]
            if len(row) > name_idx and row[name_idx].strip()
        }
        appended = 0
        updated_codes = 0
        rows_to_append: list[list[str]] = []

        for company in companies:
            if company.name not in existing_names:
                rows_to_append.append(self._company_row(company))
                existing_names.add(company.name)
                appended += 1
                continue
            if not company.stock_code or stock_idx is None:
                continue
            for row_number, row in enumerate(values[1:], start=2):
                if len(row) <= name_idx or row[name_idx].strip() != company.name:
                    continue
                current = row[stock_idx].strip() if len(row) > stock_idx else ""
                if current:
                    break
                cell = gspread.utils.rowcol_to_a1(row_number, stock_idx + 1)
                ws.update(
                    range_name=cell,
                    values=[[company.stock_code]],
                    value_input_option="USER_ENTERED",
                )
                updated_codes += 1
                break

        if rows_to_append:
            # Pad rows to current sheet width if headers were extended in place.
            width = len(headers)
            padded = []
            for row in rows_to_append:
                mapped = [""] * width
                for header, value in zip(COMPANY_HEADERS, row):
                    if header in header_index:
                        mapped[header_index[header]] = value
                padded.append(mapped)
            ws.append_rows(padded, value_input_option="USER_ENTERED")

        return {"appended": appended, "updated_codes": updated_codes}

    @staticmethod
    def _company_row(company: Company) -> list[str]:
        return [
            company.name,
            company.stock_code,
            company.list_url,
            "TRUE" if company.enabled else "FALSE",
            company.source_type,
            json.dumps(company.config, ensure_ascii=False),
            company.notes,
        ]

    def existing_urls(self) -> set[str]:
        ws = self._book.worksheet(self.releases_sheet_name)
        records = ws.get_all_records()
        urls: set[str] = set()
        for row in records:
            url = str(row.get("url") or "").strip()
            if url:
                urls.add(url)
        return urls

    def upsert_releases(self, releases: list[CuratedRelease]) -> int:
        if not releases:
            self.sort_releases_by_date()
            return 0
        ws = self._book.worksheet(self.releases_sheet_name)
        values = ws.get_all_values()
        headers = values[0] if values else RELEASE_HEADERS
        url_index = headers.index("url")
        existing_rows = {
            row[url_index].strip(): row_number
            for row_number, row in enumerate(values[1:], start=2)
            if len(row) > url_index and row[url_index].strip()
        }
        rows_to_append = []
        for item in releases:
            row = [
                item.published_on.isoformat(),
                item.company,
                item.title,
                item.paragraph,
                item.url,
                item.fetched_at.replace(tzinfo=timezone.utc).isoformat(),
                item.reason,
                item.original_title,
                item.reference_url,
            ]
            existing_row = existing_rows.get(item.url)
            if existing_row:
                end = gspread.utils.rowcol_to_a1(existing_row, len(RELEASE_HEADERS))
                ws.update(
                    range_name=f"A{existing_row}:{end}",
                    values=[row],
                    value_input_option="USER_ENTERED",
                )
            else:
                rows_to_append.append(row)
        if rows_to_append:
            ws.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        self.sort_releases_by_date()
        return len(releases)

    def sort_releases_by_date(self) -> None:
        """Keep the releases sheet newest-first while leaving the header in place."""
        ws = self._book.worksheet(self.releases_sheet_name)
        values = ws.get_all_values()
        if len(values) <= 2:
            return
        headers = values[0]
        published_on_column = headers.index("published_on") + 1
        end_cell = gspread.utils.rowcol_to_a1(len(values), len(headers))
        ws.sort(
            (published_on_column, "des"),
            range=f"A2:{end_cell}",
        )

    # Compatibility for older callers.
    def append_releases(self, releases: list[CuratedRelease]) -> int:
        return self.upsert_releases(releases)
