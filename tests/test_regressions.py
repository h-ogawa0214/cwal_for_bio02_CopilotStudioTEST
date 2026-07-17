from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

from src.curator import (
    Curator,
    _is_hard_discard_title,
    _load_editorial_examples,
    _is_vague_title,
)
from src.detail import _select_substantive_paragraph, extract_release_detail
from src.extractors.tdnet import normalize_tdnet_code, parse_tdnet_list_html
from src.models import Company, RawRelease
from src.textutil import first_paragraph, parse_date


class ExtractionRegressionTests(unittest.TestCase):
    def test_fiscal_year_is_not_parsed_as_publication_date(self) -> None:
        self.assertIsNone(parse_date("2026年3月期連結業績予想修正"))

    def test_explicit_japanese_date_is_parsed(self) -> None:
        self.assertEqual(
            str(parse_date("2026 年 4 月 22 日")),
            "2026-04-22",
        )

    def test_first_paragraph_keeps_all_sentences(self) -> None:
        paragraph = "第一文です。第二文です。\n\n次の段落です。"
        self.assertEqual(first_paragraph(paragraph), "第一文です。第二文です。")

    def test_substantive_company_paragraph_skips_header(self) -> None:
        text = """
        2026 年 4 月 22 日

        Johnson & Johnsonとのライセンス契約に関するお知らせ

        科研製薬株式会社（本社：東京都文京区、以下「科研製薬」）は、
        Johnson & Johnsonとのライセンス契約に基づき、4月1日に
        開発上のマイルストンを達成しましたのでお知らせいたします。
        """
        self.assertTrue(
            _select_substantive_paragraph(text).startswith("科研製薬株式会社")
        )

    def test_specific_original_title_is_not_vague(self) -> None:
        title = (
            "抗体-薬物複合体PADCEV™筋層浸潤性膀胱がんを対象とした"
            "ペムブロリズマブとの併用療法について米国で承認を取得"
        )
        self.assertFalse(_is_vague_title(title))

    def test_ir_qa_and_grant_receipt_titles_are_hard_discarded(self) -> None:
        discarded = [
            "助成金の受領に関するお知らせ",
            "よくあるご質問と回答",
            "決算説明会における質問と回答",
            "2026年4月期通期決算説明会の質疑応答",
        ]
        for title in discarded:
            with self.subTest(title=title):
                self.assertTrue(_is_hard_discard_title(title))

        self.assertFalse(
            _is_hard_discard_title("研究開発助成事業への採択に関するお知らせ")
        )

    def test_kyowa_style_pdf_paragraph(self) -> None:
        text = """
        2026 年 6 月 12 日
        新規診断AML におけるziftomenib／7+3 併用療法の長期追跡試験
        に関する良好な臨床試験データを2026 年EHA 年次総会で口頭発表

        – 単群試験である KOMET-007 試験において、NPM1 変異 AML 患者における
        12 カ月時点の全生存率（OS）は 94％ –

        Kura Oncology, Inc（本社：米国サンディエゴ、以下「Kura」）と協和キリン株式会社（本社：東京、以下「協和キリン」）は、本日、新規診断NPM1変異またはKMT2A再構成を有する急性骨髄性白血病（AML）患者を対象に、ziftomenibと強力化学療法（7+3）の併用療法を評価した第1/2相KOMET-007単群試験における長期追跡結果について、良好な成績が得られたことを発表しました。本データは、欧州血液学会（EHA）2026年次総会にて発表予定です。
        """
        paragraph = _select_substantive_paragraph(text)
        self.assertTrue(paragraph.startswith("Kura Oncology, Inc"))
        self.assertIn("発表しました", paragraph)

    def test_normalize_tdnet_code(self) -> None:
        self.assertEqual(normalize_tdnet_code("4503"), "45030")
        self.assertEqual(normalize_tdnet_code("45030"), "45030")
        self.assertEqual(normalize_tdnet_code("190A"), "190A0")

    def test_parse_tdnet_list_filters_by_stock_code(self) -> None:
        html = (
            Path(__file__).parent / "fixtures" / "tdnet_list_sample.html"
        ).read_text(encoding="utf-8")
        code_map = {
            "45030": Company(
                name="アステラス製薬",
                list_url="https://example.com",
                source_type="html_css",
                stock_code="4503",
            ),
            "41510": Company(
                name="協和キリン",
                list_url="https://example.com",
                source_type="playwright",
                stock_code="4151",
            ),
        }
        items = parse_tdnet_list_html(
            html,
            published_on=date(2026, 7, 17),
            code_map=code_map,
        )
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].company, "アステラス製薬")
        self.assertEqual(items[0].source_type, "tdnet")
        self.assertTrue(items[0].url.endswith("140120260717000001.pdf"))
        self.assertEqual(items[1].company, "協和キリン")
        self.assertEqual(str(items[1].published_on), "2026-07-17")

    def test_editorial_examples_are_loaded(self) -> None:
        examples = _load_editorial_examples()
        self.assertEqual(len(examples), 10)
        self.assertTrue(all(example.get("output_title") for example in examples))
        self.assertTrue(all(example.get("output_lead") for example in examples))

    def test_html_detail_keeps_source_text_for_editorial_selection(self) -> None:
        http = MagicMock()
        http.get_text.return_value = """
        <html><article>
          <p>短いヘッダー</p>
          <p>株式会社テスト（本社：東京）は、新たな第III相試験を開始したことを発表しました。</p>
          <p>試験の詳細を説明する二つ目の段落です。</p>
        </article></html>
        """
        detail = extract_release_detail(
            RawRelease(
                company="テスト",
                title="第III相試験を開始",
                url="https://example.com/release",
            ),
            http,
        )
        self.assertIn("二つ目の段落", detail.source_text)

    def test_curator_uses_editorial_title_and_lead(self) -> None:
        curator = Curator.__new__(Curator)
        curator.client = object()
        curator._llm_decide = MagicMock(
            return_value={
                "keep": True,
                "reason": "editorial fit",
                "title": "親会社、子会社が治験を開始",
                "lead": "子会社は、対象患者における第III相試験を国内の複数施設で開始したことを発表しました。今後、有効性と安全性を評価します。",
            }
        )
        item = curator.curate(
            RawRelease(
                company="親会社",
                title="治験開始のお知らせ",
                url="https://example.com/release",
                published_on=date(2026, 7, 18),
            ),
            "子会社は治験を開始しました。",
            source_text="親会社の子会社は、対象患者における第III相試験を開始しました。",
        )
        self.assertIsNotNone(item)
        assert item is not None
        self.assertEqual(item.title, "親会社、子会社が治験を開始")
        self.assertIn("対象患者", item.paragraph)


if __name__ == "__main__":
    unittest.main()
