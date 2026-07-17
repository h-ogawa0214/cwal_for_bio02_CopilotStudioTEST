# 段階展開ガイド（cohort rollout）

第1陣の shadow 指標が安定したら、約15社単位で公式ソースを追加する。

## 選定順

1. 直近60〜90日の TDnet 候補数・媒体採用数が多い企業
2. 第1陣で安定したアダプター（`html_css` / `json_api` / `eir` / `rss`）を流用できる企業
3. 保守負担が高い JS依存・PDF一覧・ブロック多発企業は後回し（TDnetのみ残可）

## 判定式

継続可否はおおむね次で見る。

`増分掲載数 ÷ 保守コスト ÷ APIコスト`

- 増分掲載数: `site_only` かつ keep になった件数（週次）
- 保守コスト: セレクター破損・403・Playwright依存の有無
- APIコスト: `est_cost_usd` と `llm_calls`（判定台帳ヒット後の減り方）

## 展開手順

1. YAML に `crawl_mode: shadow` で追加（Sheets の enabled/crawl_mode で運用上書き可）
2. 1〜2週間 shadow。`metrics` / `decisions` を確認
3. 合格なら `crawl_mode: live`
4. 失敗が続くソースは一時 `tdnet_only` に戻し、TDnetは止めない

## 巡回頻度（目標）

| ソース | 頻度 |
|---|---|
| TDnet | 全社 3回/日 |
| 高価値公式ソース | 3回/日 |
| 低頻度・保守的IR | 1回/日 |
| ソース構造の再検査 | 週1 |

## 第2陣の候補プール例

開示頻度の高い上場バイオを、第1陣アダプター再利用可能性で並べ替えて選ぶ。具体社名は直近 `releases` / TDnet 件数を見て更新する。
