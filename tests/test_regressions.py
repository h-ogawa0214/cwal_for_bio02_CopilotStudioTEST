from __future__ import annotations

import unittest

from src.curator import _is_vague_title
from src.detail import _select_substantive_paragraph
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


if __name__ == "__main__":
    unittest.main()
