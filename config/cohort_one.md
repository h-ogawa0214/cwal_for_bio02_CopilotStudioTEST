# 第1陣公式ソース調査メモ（cohort one）

対象: 武田薬品工業、第一三共、エーザイ、小野薬品工業、塩野義製薬、参天製薬、日本新薬、JCRファーマ、ペプチドリーム、ネクセラファーマ

方針: RSS → JSON/サイトマップ → EIR → 静的HTML → Playwright。TDnetは全社で安全網として維持。

| 企業 | 採用方式 | crawl_mode | 結果 |
|---|---|---|---|
| 第一三共 | `json_api` (`/data/ann/1855.json`) | shadow | 一覧JSONが安定。本番化候補 |
| エーザイ | `html_css` | shadow | 静的リスト取得可 |
| 小野薬品工業 | `html_css` | shadow | 静的リスト取得可 |
| 塩野義製薬 | `html_css` | shadow | 静的リスト取得可 |
| 参天製薬 | `html_css` | shadow | 静的リスト取得可（IRにEIR痕跡あり） |
| JCRファーマ | `html_css` | shadow | 取得可。IR資料混在のため選別必須 |
| ネクセラファーマ | `eir` | shadow | EIRウィジェット。共有アダプター＋Playwrightフォールバック |
| 武田薬品工業 | `tdnet_only` | live | 安定な日本語一覧URL未確定 |
| 日本新薬 | `tdnet_only` | live | 公式ニュースが403 |
| ペプチドリーム | `tdnet_only` | live | 公式ニュースが403 |

## シャドー運用の合格条件（計画どおり）

- TDnetにない有用候補が確認できる
- 取得成功率 ≥ 99%
- 日付抽出 ≥ 95%
- releases への重複追加ゼロ
- 1〜2週間の shadow 後に `crawl_mode: live` へ昇格

## 観測指標

`metrics` シートの `site_only` / `matched_site_tdnet` / `llm_calls` / `est_cost_usd` を週次で比較する。
