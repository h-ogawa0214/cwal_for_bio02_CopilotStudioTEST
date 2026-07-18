from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock

from src.dedupe import release_fingerprint
from src.sheets_client import COMPANY_HEADERS, RELEASE_HEADERS, SheetsClient


class SheetsClientTests(unittest.TestCase):
    def test_sort_releases_by_date_sorts_data_rows_descending(self) -> None:
        worksheet = MagicMock()
        worksheet.get_all_values.return_value = [
            RELEASE_HEADERS,
            ["2026-07-16"],
            ["2026-07-18"],
            ["2026-07-17"],
        ]
        client = SheetsClient.__new__(SheetsClient)
        client._book = MagicMock()
        client._book.worksheet.return_value = worksheet
        client.releases_sheet_name = "releases"

        client.sort_releases_by_date()

        worksheet.sort.assert_called_once_with((1, "des"), range="A2:I4")

    def test_existing_release_keys_include_fingerprints(self) -> None:
        worksheet = MagicMock()
        worksheet.get_all_records.return_value = [
            {
                "published_on": "2026-07-17",
                "company_name": "レナサイエンス",
                "title": "短い題",
                "url": "https://example.com/a",
                "original_title": "局所進行非小細胞肺がんに対する第二相治験開始のお知らせ",
            }
        ]
        client = SheetsClient.__new__(SheetsClient)
        client._book = MagicMock()
        client._book.worksheet.return_value = worksheet
        client.releases_sheet_name = "releases"

        urls, fingerprints = client.existing_release_keys()

        self.assertIn("https://example.com/a", urls)
        self.assertIn(
            release_fingerprint(
                "レナサイエンス",
                "2026-07-17",
                "局所進行非小細胞肺がんに対する第二相治験開始のお知らせ",
            ),
            fingerprints,
        )

    def test_release_fingerprint_ignores_whitespace(self) -> None:
        left = release_fingerprint("協和キリン", date(2026, 6, 12), "新規診断 AML")
        right = release_fingerprint("協和キリン", "2026-06-12", "新規診断AML")
        self.assertEqual(left, right)

    def test_company_headers_include_crawl_mode(self) -> None:
        self.assertIn("crawl_mode", COMPANY_HEADERS)

    def test_sync_companies_batches_cell_updates(self) -> None:
        from src.models import Company

        worksheet = MagicMock()
        worksheet.get_all_values.return_value = [
            COMPANY_HEADERS,
            ["エーザイ", "4523", "old_url", "TRUE", "tdnet_only", "", "{}", ""],
        ]
        client = SheetsClient.__new__(SheetsClient)
        client._book = MagicMock()
        client._book.worksheet.return_value = worksheet
        client.companies_sheet_name = "companies"
        client.releases_sheet_name = "releases"
        client.decisions_sheet_name = "decisions"
        client.metrics_sheet_name = "metrics"
        client.ensure_schema = lambda: None

        result = client.sync_companies(
            [
                Company(
                    name="エーザイ",
                    list_url="https://www.eisai.co.jp/news/index.html",
                    source_type="html_css",
                    stock_code="4523",
                    crawl_mode="shadow",
                )
            ]
        )

        # All differing authority cells go out in one batch_update call.
        self.assertEqual(worksheet.batch_update.call_count, 1)
        worksheet.update.assert_not_called()
        self.assertGreaterEqual(result["updated_fields"], 3)


if __name__ == "__main__":
    unittest.main()
