from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.sheets_client import RELEASE_HEADERS, SheetsClient


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


if __name__ == "__main__":
    unittest.main()
