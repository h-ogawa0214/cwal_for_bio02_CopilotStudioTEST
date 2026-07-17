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


if __name__ == "__main__":
    unittest.main()
