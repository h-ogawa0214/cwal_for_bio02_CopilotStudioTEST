# pr-disclosure-curator

創薬・バイオテクノロジー関連企業のプレスリリース／適時開示を巡回し、雑誌サイト掲載に値するものだけを Google スプレッドシートへ書き出すツールです。

## できること

- 対象企業一覧をスプレッドシートの `companies` シートで管理（社数増加を想定）
- 1日3回（JST 9:00 / 12:00 / 17:00）GitHub Actions で巡回
- 掲載価値のあるリリースだけを `releases` シートへ追記
- 具体的な原題はそのまま保持し、粗いタイトルだけ本文1段落から40字前後に補正
- 一覧の抜粋ではなく、詳細ページ／PDF本文の最初の実質的な段落を取得

書き込み列:

| published_on | company_name | title | paragraph | url | fetched_at | decision_reason | original_title | reference_url |
|---|---|---|---|---|---|---|---|---|

`reference_url` は、公式URLから本文を取得できず別媒体を参照した場合だけ、その参照元URLを記録します。

## 対象企業（初期10社）

`config/companies.yaml` に定義。初回実行時、スプレッドシートの `companies` が空なら自動でシードします。以後はシート側を編集すれば社数を増やせます。

| company_name | list_url | source_type |
|---|---|---|
| アステラス製薬 | https://jp.newsroom.astellas.com/news | html_css |
| 大塚ホールディングス | https://www.otsuka.com/jp/ir/news/ | playwright |
| 中外製薬 | https://www.chugai-pharm.co.jp/news/ | html_css |
| 協和キリン | https://www.kyowakirin.co.jp/pressroom/news_releases/index.html | playwright |
| 住友ファーマ | https://www.sumitomo-pharma.co.jp/news/ir/ | rss |
| 明治製菓ファルマ | https://www.meiji-seika-pharma.co.jp/pressrelease/ | xlsx |
| 杏林製薬 | https://www.kyorin-pharm.co.jp/news/ | html_css |
| 持田製薬 | https://www.mochida.co.jp/news/ | playwright |
| 科研製薬 | https://www.kaken.co.jp/nr/ | playwright |
| レナサイエンス | https://www.renascience.co.jp/ir/ir_news/ | playwright |

`companies` シート列:

- `company_name`
- `stock_code`（東証コード4桁。上場企業は TDnet 補助取得に使用）
- `list_url`
- `enabled` (`TRUE` / `FALSE`)
- `source_type` (`html_css` / `rss` / `xlsx` / `playwright`)
- `config_json`（抽出用設定の JSON）
- `notes`

各社サイト巡回に加え、`stock_code` がある企業は JPX 公式の適時開示情報閲覧サービス
（`release.tdnet.info`）からも直近数日分を補助取得します（既定: `TDNET_LOOKBACK_DAYS=3`）。
同一内容の重複は会社名・日付・表題の指紋で抑制します。

`config/companies.yaml` で `enabled: false` の企業は、安全停止としてシート側が
`TRUE` でも巡回しません。再開時は両方を `true` / `TRUE` に戻します。

## 選出ロジック

1. キーワードによる一次判定（人事・受賞・採用などは除外、承認・治験・提携などは残す）
2. OpenAI API で最終判定＋タイトル補正（`config/criteria.md` をプロンプトに使用）

`OPENAI_API_KEY` が無い場合はヒューリスティックのみで動きます（判定不能なものはスキップ）。

## セットアップ

### 1. Google サービスアカウント

1. Google Cloud でサービスアカウントを作成し、JSON 鍵を発行
2. 対象スプレッドシートを、そのサービスアカウントのメールアドレスに **編集者** で共有  
   - スプレッドシート: https://docs.google.com/spreadsheets/d/1JlnCTJgC3ZdJ5WrHL9O6yPJsUE8uoVMEdGNSC8xb_6Y/edit
3. JSON 全体を GitHub Secret `GOOGLE_SERVICE_ACCOUNT_JSON` に登録
4. Secret `SPREADSHEET_ID` に `1JlnCTJgC3ZdJ5WrHL9O6yPJsUE8uoVMEdGNSC8xb_6Y`
5. Secret `OPENAI_API_KEY` を登録（推奨）
6. 任意で Secret / Variable `OPENAI_MODEL`（既定: `gpt-4o-mini`）

> 「リンクを知っている全員が編集可」でも、Sheets API 経由の書き込みにはサービスアカウント（または OAuth）が必要です。

### 2. ローカル実行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env   # 値を埋める

python -m src.main --seed-only   # companies / releases シート作成＋企業シード
python -m src.main               # 巡回・選出・書き込み
python -m src.main --reprocess-existing  # 既存URLを再抽出して行を更新
```

### 3. GitHub Actions

`.github/workflows/crawl.yml` が UTC 0:00 / 3:00 / 8:00（= JST 9 / 12 / 17）で実行します。  
Actions タブから `workflow_dispatch` でも手動実行できます。

## 企業の追加方法

1. スプレッドシート `companies` に1行追加
2. `source_type` と `config_json` を設定
3. 次回の Actions 実行から自動で巡回対象になる

例（静的 HTML）:

```json
{
  "item_selector": "li.item",
  "title_selector": "a.title",
  "date_selector": "time",
  "link_selector": "a.title"
}
```

例（RSS）:

```json
{"feed_url": "https://example.com/news/rss.xml"}
```

公式URLが取得できない個別記事に代替ソースを指定する例:

```json
{
  "alternate_urls": {
    "https://example.com/original-release.pdf": "https://prtimes.jp/example"
  }
}
```

この場合も `url` は公式URLのまま維持し、実際に代替ソースを使ったときだけ
`reference_url` に代替ソースのURLを書き込みます。

## 注意

- JS 描画の IR サイトは Playwright を使います。レイアウト変更で抽出が崩れたら `config_json` を更新してください
- PDF 本文は先頭ページから段落抽出します（画像PDFは空になることがあります）
- 同一 URL は通常スキップします。手動実行の `reprocess_existing` では既存行を更新します
