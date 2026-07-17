from __future__ import annotations

import json
import unittest
from datetime import date
from unittest.mock import MagicMock

from src.dedupe import canonicalize_url, content_hash, titles_likely_same
from src.extractors.structured import JsonApiExtractor
from src.main import _cluster_candidates
from src.models import RawRelease


class EcoFoundationTests(unittest.TestCase):
    def test_canonicalize_url_strips_tracking_params(self) -> None:
        raw = "https://Example.com/news/a/?utm_source=x&id=1&fbclid=y"
        self.assertEqual(canonicalize_url(raw), "https://example.com/news/a?id=1")

    def test_titles_likely_same_ignores_boilerplate(self) -> None:
        self.assertTrue(
            titles_likely_same(
                "第III相試験開始に関するお知らせ",
                "第III相試験開始",
            )
        )

    def test_content_hash_stable(self) -> None:
        self.assertEqual(content_hash("  hello  "), content_hash("hello"))

    def test_cluster_candidates_merges_site_and_tdnet(self) -> None:
        items = [
            RawRelease(
                company="エーザイ",
                title="新薬の承認申請について",
                url="https://www.eisai.co.jp/news/a.html",
                published_on=date(2026, 7, 16),
                source_type="html_css",
            ),
            RawRelease(
                company="エーザイ",
                title="新薬の承認申請に関するお知らせ",
                url="https://www.release.tdnet.info/a.pdf",
                published_on=date(2026, 7, 16),
                source_type="tdnet",
            ),
        ]
        merged = _cluster_candidates(items)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].source_type, "html_css")
        self.assertTrue(merged[0].reference_url.endswith(".pdf"))

    def test_json_api_extractor_parses_html_fragments(self) -> None:
        from src.models import Company

        payload = {
            "item": [
                {
                    "anndate": "2026/07/01 00:00:00",
                    "contents": (
                        '<li><div class="newsDate">2026年07月01日</div>'
                        '<div class="newsTitle">'
                        '<a href="/news/detail/index_1.html">治験開始のお知らせ</a>'
                        "</div></li>"
                    ),
                }
            ]
        }
        http = MagicMock()
        http.get_text.return_value = json.dumps(payload)
        company = Company(
            name="第一三共",
            list_url="https://www.daiichisankyo.co.jp/news/",
            source_type="json_api",
            config={
                "json_url": "https://www.daiichisankyo.co.jp/data/ann/1855.json",
                "items_path": "item",
                "html_field": "contents",
                "html_link_selector": ".newsTitle a",
                "html_date_selector": ".newsDate",
                "date_field": "anndate",
                "base_url": "https://www.daiichisankyo.co.jp",
            },
        )
        items = JsonApiExtractor(http).fetch(company, limit=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "治験開始のお知らせ")
        self.assertTrue(items[0].url.endswith("/news/detail/index_1.html"))
        self.assertEqual(str(items[0].published_on), "2026-07-01")


if __name__ == "__main__":
    unittest.main()
