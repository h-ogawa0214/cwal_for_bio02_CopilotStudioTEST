from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Iterable

import gspread
from google.oauth2.service_account import Credentials

from .dedupe import canonicalize_url, release_fingerprint
from .metrics import RunMetrics
from .models import Company, CuratedRelease, DecisionRecord
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
    "crawl_mode",
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

DECISION_HEADERS = [
    "decided_at",
    "company_name",
    "published_on",
    "title",
    "url",
    "canonical_url",
    "fingerprint",
    "content_hash",
    "decision",
    "reason",
    "source_type",
    "model",
    "criteria_version",
]

METRICS_HEADERS = [
    "run_at",
    "candidates_seen",
    "candidates_new",
    "cache_hits",
    "kept",
    "discarded",
    "hard_discards",
    "heuristic_discards",
    "duplicates_skipped",
    "fetch_errors",
    "classify_calls",
    "editorial_calls",
    "prompt_tokens",
    "completion_tokens",
    "est_cost_usd",
    "site_only",
    "tdnet_only",
    "matched_site_tdnet",
    "source_stats_json",
]


class SheetsClient:
    def __init__(self, settings: Settings) -> None:
        info = validate_service_account_json(settings.google_service_account_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        self._gc = gspread.authorize(creds)
        self._book = self._gc.open_by_key(settings.spreadsheet_id)
        self.companies_sheet_name = settings.companies_sheet
        self.releases_sheet_name = settings.releases_sheet
        self.decisions_sheet_name = settings.decisions_sheet
        self.metrics_sheet_name = settings.metrics_sheet

    def ensure_schema(self) -> None:
        self._ensure_worksheet(self.companies_sheet_name, COMPANY_HEADERS)
        self._ensure_worksheet(self.releases_sheet_name, RELEASE_HEADERS)
        self._ensure_worksheet(self.decisions_sheet_name, DECISION_HEADERS)
        self._ensure_worksheet(self.metrics_sheet_name, METRICS_HEADERS)

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
            crawl_mode_raw = str(row.get("crawl_mode") or "live").strip().lower()
            crawl_mode = "shadow" if crawl_mode_raw == "shadow" else "live"
            companies.append(
                Company(
                    name=name,
                    list_url=list_url,
                    enabled=enabled,
                    source_type=source_type,
                    stock_code=str(row.get("stock_code") or "").strip(),
                    crawl_mode=crawl_mode,
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
        """Sync YAML authority fields and append missing companies.

        YAML owns: list_url, source_type, config_json, stock_code, crawl_mode default.
        Sheets may override: enabled, crawl_mode (if non-empty), notes.
        """
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
        header_index = {name: idx for idx, name in enumerate(headers)}
        name_idx = header_index.get("company_name", 0)

        existing_names = {
            row[name_idx].strip()
            for row in values[1:]
            if len(row) > name_idx and row[name_idx].strip()
        }
        appended = 0
        updated_fields = 0
        rows_to_append: list[list[str]] = []
        # Collect all cell edits and flush them in a single batch_update call to
        # stay under the Sheets "write requests per minute" quota (per-cell
        # updates for ~80 companies previously tripped a 429).
        pending_cells: list[dict] = []

        authority_fields = {
            "list_url": lambda c: c.list_url,
            "source_type": lambda c: c.source_type,
            "stock_code": lambda c: c.stock_code,
            "config_json": lambda c: json.dumps(c.config, ensure_ascii=False),
            "crawl_mode": lambda c: c.crawl_mode,
        }
        companies_by_name = {c.name: c for c in companies}

        for company in companies_by_name.values():
            if company.name not in existing_names:
                rows_to_append.append(self._company_row(company))
                existing_names.add(company.name)
                appended += 1

        for row_number, row in enumerate(values[1:], start=2):
            if len(row) <= name_idx:
                continue
            name = row[name_idx].strip()
            company = companies_by_name.get(name)
            if company is None:
                continue
            for field, getter in authority_fields.items():
                col_idx = header_index.get(field)
                if col_idx is None:
                    continue
                desired = getter(company)
                if field == "stock_code" and not desired:
                    continue
                current = row[col_idx].strip() if len(row) > col_idx else ""
                # Keep an explicit sheet crawl_mode once set.
                if field == "crawl_mode" and current:
                    continue
                if current == desired:
                    continue
                pending_cells.append(
                    {
                        "range": gspread.utils.rowcol_to_a1(row_number, col_idx + 1),
                        "values": [[desired]],
                    }
                )
                updated_fields += 1

        if pending_cells:
            ws.batch_update(pending_cells, value_input_option="USER_ENTERED")

        if rows_to_append:
            width = len(headers)
            padded = []
            for row in rows_to_append:
                mapped = [""] * width
                for header, value in zip(COMPANY_HEADERS, row):
                    if header in header_index:
                        mapped[header_index[header]] = value
                padded.append(mapped)
            ws.append_rows(padded, value_input_option="USER_ENTERED")

        return {"appended": appended, "updated_fields": updated_fields}

    @staticmethod
    def _company_row(company: Company) -> list[str]:
        return [
            company.name,
            company.stock_code,
            company.list_url,
            "TRUE" if company.enabled else "FALSE",
            company.source_type,
            company.crawl_mode,
            json.dumps(company.config, ensure_ascii=False),
            company.notes,
        ]

    def existing_urls(self) -> set[str]:
        urls, _ = self.existing_release_keys()
        return urls

    def existing_release_keys(self) -> tuple[set[str], set[str]]:
        """Return known URLs and soft fingerprints already stored in releases."""
        ws = self._book.worksheet(self.releases_sheet_name)
        records = ws.get_all_records()
        urls: set[str] = set()
        fingerprints: set[str] = set()
        for row in records:
            url = str(row.get("url") or "").strip()
            if url:
                urls.add(url)
                canonical = canonicalize_url(url)
                if canonical:
                    urls.add(canonical)
            company = str(row.get("company_name") or "").strip()
            published_on = str(row.get("published_on") or "").strip()
            title = str(row.get("original_title") or row.get("title") or "").strip()
            if company and title:
                fingerprints.add(release_fingerprint(company, published_on, title))
                display_title = str(row.get("title") or "").strip()
                if display_title and display_title != title:
                    fingerprints.add(
                        release_fingerprint(company, published_on, display_title)
                    )
        return urls, fingerprints

    def load_decision_cache(self, *, today: date | None = None) -> dict[str, DecisionRecord]:
        """Map fingerprint/canonical_url -> latest decision for same-day discard cache."""
        ws = self._book.worksheet(self.decisions_sheet_name)
        records = ws.get_all_records()
        cache: dict[str, DecisionRecord] = {}
        day = today or date.today()
        for row in records:
            decision = str(row.get("decision") or "").strip().lower()
            if decision not in {"keep", "discard", "hard_discard"}:
                continue
            decided_raw = str(row.get("decided_at") or "").strip()
            try:
                decided_at = datetime.fromisoformat(decided_raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            decided_day = decided_at.astimezone(timezone.utc).date()
            # Same-day discard cache prevents re-LLM across 9/12/17 runs.
            if decision in {"discard", "hard_discard"} and decided_day != day:
                continue
            record = DecisionRecord(
                decided_at=decided_at,
                company=str(row.get("company_name") or "").strip(),
                published_on=str(row.get("published_on") or "").strip(),
                title=str(row.get("title") or "").strip(),
                url=str(row.get("url") or "").strip(),
                canonical_url=str(row.get("canonical_url") or "").strip(),
                fingerprint=str(row.get("fingerprint") or "").strip(),
                content_hash=str(row.get("content_hash") or "").strip(),
                decision=decision,
                reason=str(row.get("reason") or "").strip(),
                source_type=str(row.get("source_type") or "").strip(),
                model=str(row.get("model") or "").strip(),
                criteria_version=str(row.get("criteria_version") or "").strip(),
            )
            for key in (
                record.fingerprint,
                record.canonical_url,
                record.url,
                record.content_hash,
            ):
                if key:
                    cache[key] = record
        return cache

    def append_decisions(self, decisions: list[DecisionRecord]) -> int:
        if not decisions:
            return 0
        ws = self._book.worksheet(self.decisions_sheet_name)
        rows = [
            [
                item.decided_at.replace(tzinfo=timezone.utc).isoformat(),
                item.company,
                item.published_on,
                item.title,
                item.url,
                item.canonical_url,
                item.fingerprint,
                item.content_hash,
                item.decision,
                item.reason,
                item.source_type,
                item.model,
                item.criteria_version,
            ]
            for item in decisions
        ]
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        return len(rows)

    def append_run_metrics(self, metrics: RunMetrics) -> None:
        ws = self._book.worksheet(self.metrics_sheet_name)
        row = [
            metrics.started_at.replace(tzinfo=timezone.utc).isoformat(),
            metrics.candidates_seen,
            metrics.candidates_new,
            metrics.cache_hits,
            metrics.kept,
            metrics.discarded,
            metrics.hard_discards,
            metrics.heuristic_discards,
            metrics.duplicates_skipped,
            metrics.fetch_errors,
            metrics.classify_calls,
            metrics.editorial_calls,
            metrics.prompt_tokens,
            metrics.completion_tokens,
            f"{metrics.estimated_cost_usd:.6f}",
            metrics.site_only,
            metrics.tdnet_only,
            metrics.matched_site_tdnet,
            json.dumps(metrics.source_stats, ensure_ascii=False),
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")

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
        _, existing_fingerprints = self.existing_release_keys()
        rows_to_append = []
        written = 0
        for item in releases:
            fingerprint = release_fingerprint(
                item.company,
                item.published_on,
                item.original_title or item.title,
            )
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
                existing_fingerprints.add(fingerprint)
                written += 1
            elif fingerprint in existing_fingerprints:
                continue
            else:
                rows_to_append.append(row)
                existing_fingerprints.add(fingerprint)
                existing_rows[item.url] = -1
                written += 1
        if rows_to_append:
            ws.append_rows(rows_to_append, value_input_option="USER_ENTERED")
        self.sort_releases_by_date()
        return written

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

    def append_releases(self, releases: list[CuratedRelease]) -> int:
        return self.upsert_releases(releases)
