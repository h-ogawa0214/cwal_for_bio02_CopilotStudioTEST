from __future__ import annotations

import json
import unittest
from datetime import date
from unittest.mock import MagicMock

from src.dedupe import canonicalize_url, content_hash, titles_likely_same
from src.extractors.prtimes import PrTimesCompanyExtractor, PrTimesKeywordExtractor
from src.extractors.structured import JsonApiExtractor
from src.main import _cluster_candidates
from src.models import Company, RawRelease


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

    def test_prtimes_keyword_extractor_parses_items(self) -> None:
        page = """
        <html><body>
        <article class="item item-ordinary">
          <div class="thumbnail-title-wrap">
            <h3 class="title-item">
              <a class="link-title-item" href="/main/html/rd/p/000000743.000006776.html">
                FRONTEOと参天製薬、共創プロジェクト第2弾を開始
              </a>
            </h3>
          </div>
          <time class="time-release" datetime="2026-07-16T16:00:00+0900">2026年7月16日 16時00分</time>
          <a class="link-name-company name-company" href="/main/html/searchrlp/company_id/6776">株式会社FRONTEO</a>
        </article>
        </body></html>
        """
        http = MagicMock()
        http.get_text.return_value = page
        company = Company(
            name="PR TIMES（医薬・創薬・バイオ）",
            list_url="https://prtimes.jp/topics/keywords/創薬",
            source_type="prtimes",
            crawl_mode="shadow",
            config={"keywords": ["創薬"], "max_per_keyword": 10},
        )
        items = PrTimesKeywordExtractor(http).fetch(company, limit=10)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].company, "株式会社FRONTEO")
        self.assertEqual(items[0].source_type, "prtimes")
        self.assertEqual(items[0].crawl_mode, "shadow")
        self.assertEqual(str(items[0].published_on), "2026-07-16")
        self.assertTrue(items[0].url.endswith("000000743.000006776.html"))

    def test_prtimes_company_extractor_filters_investment_titles(self) -> None:
        payload = {
            "status": 200,
            "data": {
                "total": 3,
                "data": [
                    {
                        "id": 10,
                        "title": "株式会社サンプルへの資本参加に関するお知らせ",
                        "url": "/main/html/rd/p/000000010.000057515.html",
                        "company": {"name_origin": "ジャフコ グループ株式会社"},
                        "release_comple_date": "2026-07-13T12:10:00+09:00",
                    },
                    {
                        "id": 11,
                        "title": "JAFCO SEED 2026 開催のお知らせ",
                        "url": "/main/html/rd/p/000000011.000057515.html",
                        "company": {"name_origin": "ジャフコ グループ株式会社"},
                        "release_comple_date": "2026-07-10T12:10:00+09:00",
                    },
                    {
                        "id": 12,
                        "title": "スタートアップABCに出資しました",
                        "url": "/main/html/rd/p/000000012.000057515.html",
                        "company": {"name_origin": "ジャフコ グループ株式会社"},
                        "release_comple_date": "2026-07-01T12:10:00+09:00",
                    },
                ],
            },
        }
        http = MagicMock()
        http.get_text.return_value = json.dumps(payload)
        company = Company(
            name="ジャフコ グループ",
            list_url="https://prtimes.jp/main/html/searchrlp/company_id/57515",
            source_type="prtimes_company",
            crawl_mode="shadow",
            config={"company_id": 57515, "include_keywords": ["出資", "資本参加"]},
        )
        items = PrTimesCompanyExtractor(http).fetch(company, limit=10)
        # The events post ("JAFCO SEED") is filtered out; investment posts kept.
        self.assertEqual(len(items), 2)
        titles = {i.title for i in items}
        self.assertIn("株式会社サンプルへの資本参加に関するお知らせ", titles)
        self.assertIn("スタートアップABCに出資しました", titles)
        self.assertNotIn("JAFCO SEED 2026 開催のお知らせ", titles)
        first = items[0]
        self.assertEqual(first.company, "ジャフコ グループ")
        self.assertEqual(first.source_type, "prtimes_company")
        self.assertEqual(str(first.published_on), "2026-07-13")
        self.assertTrue(first.url.startswith("https://prtimes.jp/"))

    def test_prtimes_company_extractor_keeps_new_fund_news(self) -> None:
        payload = {
            "status": 200,
            "data": {
                "total": 3,
                "data": [
                    {
                        "id": 20,
                        "title": "ディープテック特化3号ファンドを257億円でファイナルクローズ",
                        "url": "/main/html/rd/p/000000020.000017460.html",
                        "company": {"name_origin": "Beyond Next Ventures株式会社"},
                        "release_comple_date": "2026-07-13T12:10:00+09:00",
                    },
                    {
                        "id": 21,
                        "title": "UMI3号脱炭素東京投資事業有限責任組合の設立について",
                        "url": "/main/html/rd/p/000000021.000017460.html",
                        "company": {"name_origin": "Beyond Next Ventures株式会社"},
                        "release_comple_date": "2026-07-10T12:10:00+09:00",
                    },
                    {
                        "id": 22,
                        "title": "コミュニティ「BRAVE MATE」を設立",
                        "url": "/main/html/rd/p/000000022.000017460.html",
                        "company": {"name_origin": "Beyond Next Ventures株式会社"},
                        "release_comple_date": "2026-07-01T12:10:00+09:00",
                    },
                ],
            },
        }
        http = MagicMock()
        http.get_text.return_value = json.dumps(payload)
        company = Company(
            name="Beyond Next Ventures",
            list_url="https://prtimes.jp/main/html/searchrlp/company_id/17460",
            source_type="prtimes_company",
            crawl_mode="shadow",
            config={
                "company_id": 17460,
                "include_keywords": ["出資", "ファンド", "投資事業有限責任組合"],
            },
        )
        items = PrTimesCompanyExtractor(http).fetch(company, limit=10)
        titles = {i.title for i in items}
        # Fund establishment / close kept (incl. LPS-named fund without ファンド word).
        self.assertIn("ディープテック特化3号ファンドを257億円でファイナルクローズ", titles)
        self.assertIn("UMI3号脱炭素東京投資事業有限責任組合の設立について", titles)
        # Non-fund "設立" (a community) is filtered out.
        self.assertNotIn("コミュニティ「BRAVE MATE」を設立", titles)

    def test_prtimes_company_extractor_requires_company_id(self) -> None:
        http = MagicMock()
        company = Company(
            name="No ID VC",
            list_url="https://prtimes.jp/",
            source_type="prtimes_company",
            crawl_mode="shadow",
            config={},
        )
        self.assertEqual(PrTimesCompanyExtractor(http).fetch(company, limit=10), [])
        http.get_text.assert_not_called()

    def test_cluster_live_wins_over_shadow(self) -> None:
        items = [
            RawRelease(
                company="株式会社FRONTEO",
                title="共創プロジェクト第2弾を開始",
                url="https://prtimes.jp/main/html/rd/p/1.2.html",
                published_on=date(2026, 7, 16),
                source_type="prtimes",
                crawl_mode="shadow",
            ),
            RawRelease(
                company="株式会社FRONTEO",
                title="共創プロジェクト第2弾を開始のお知らせ",
                url="https://www.release.tdnet.info/x.pdf",
                published_on=date(2026, 7, 16),
                source_type="tdnet",
                crawl_mode="live",
            ),
        ]
        merged = _cluster_candidates(items)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].crawl_mode, "live")

    def test_json_api_extractor_parses_html_fragments(self) -> None:
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
        http2 = MagicMock()
        http2.get_text.return_value = json.dumps(payload)
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
        items = JsonApiExtractor(http2).fetch(company, limit=5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "治験開始のお知らせ")
        self.assertTrue(items[0].url.endswith("/news/detail/index_1.html"))
        self.assertEqual(str(items[0].published_on), "2026-07-01")


if __name__ == "__main__":
    unittest.main()
