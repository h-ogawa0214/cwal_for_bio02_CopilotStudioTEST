# pr-disclosure-curator

創薬・バイオテクノロジー関連企業のプレスリリース／適時開示を巡回し、雑誌サイト掲載に値するものだけを Excel ブック（OneDrive）へ書き出すツールです。

## できること

- 対象企業一覧を Excel ブックの `companies` シートで管理（社数増加を想定）
- 自動スケジューラは使わず、Claude Code への実行指示で都度巡回
- 掲載価値のあるリリースだけを `releases` シートへ追記
- 除外・掲載の判定履歴を `decisions` に保存し、同日の再 LLM を抑制
- run ごとのトークン・概算費用・ソース別件数を `metrics` に記録
- 具体的な原題はそのまま保持し、粗いタイトルだけ本文から補正
- 一覧の抜粋ではなく、詳細ページ／PDF本文の上位段落を取得

書き込み列 (`releases`):

| published_on | company_name | title | paragraph | url | fetched_at | decision_reason | original_title | reference_url |
|---|---|---|---|---|---|---|---|---|

書き込み後は `published_on` の降順に自動整列し、最新のリリースを上に表示します。

## 対象企業

`config/companies.yaml` が `list_url` / `source_type` / 抽出設定の正本です。  
Excel ブックは `enabled` と `crawl_mode`（live / shadow）など運用上書きに使います。

起動時に YAML → Excel ブックへ同期します（未登録社の追記、`list_url` / `source_type` / `config_json` / `stock_code` の更新）。

大手などは各社サイト抽出（`html_css` / `rss` / `xlsx` / `json_api` / `sitemap` / `eir` / `playwright`）を使い、
それ以外の上場企業は当面 `tdnet_only`（公式 TDnet 閲覧サービスのみ）でカバーします。

`prtimes` は PR TIMES のキーワードタグ一覧（医薬・創薬・バイオテクノロジー等）を1行で巡回し、
TDnet に載らない未上場バイオ・研究団体の PR を補完します（各リリースの発表主体は自動判定）。

`prtimes_company` は特定企業の PR TIMES 企業ページを JSON API 経由で取得します。
`config.company_id`（企業ページ URL 末尾）で対象を指定し、`config.include_keywords`
（例: `出資 / 資本参加`）でタイトルを事前フィルタします。VC の「●●に出資」告知のみを
拾う用途に使用。詳細は `config/vc_cohort.md`。

第1陣の公式ソースと VC 陣は `crawl_mode: shadow` で先行運用します（取得・判定はするが `releases` には書かない）。  
詳細は `config/cohort_one.md` / `config/cohort_rollout.md` / `config/vc_cohort.md` を参照。

`companies` シート列:

- `company_name`
- `stock_code`（東証コード。TDnet 補助取得に使用）
- `list_url`
- `enabled` (`TRUE` / `FALSE`)
- `source_type`
- `crawl_mode` (`live` / `shadow`)
- `config_json`
- `notes`

各社サイト巡回に加え、`stock_code` がある企業は JPX 公式の適時開示情報閲覧サービス
（`release.tdnet.info`）からも直近数日分を補助取得します。  
同一内容の重複は URL 正規化に加え、会社名・日付・表題の指紋、本文ハッシュでも抑制します。

## 選出ロジック（API節約）

1. ハード除外タイトル（助成金受領・IR Q&A・払込完了など）
2. タイトルキーワードの安価なヒューリスティック除外
3. 軽量 LLM 一次判定（keep / discard / uncertain）
4. keep / uncertain（およびヒューリスティック keep）だけ媒体向けタイトル・リード編集 LLM
5. few-shot 例は全件ではなく記事種別に近い 2〜4 例だけ送る

`OPENAI_API_KEY` が無い場合はヒューリスティックのみで動きます。

## セットアップ

### 1. 出力先 Excel ファイル

1. `.env` に `EXCEL_FILE_PATH` を設定（既定: `data/releases.xlsx`。このプロジェクトフォルダ自体が OneDrive 配下にあるため、既定のままで OneDrive 同期対象になります）
2. `OPENAI_API_KEY` を登録（推奨。未設定ならヒューリスティックのみで動作）
3. 任意で `OPENAI_MODEL`（既定: `gpt-4o-mini`）

### 2. ローカル実行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env   # 値を埋める

python -m src.main --seed-only   # companies / releases / decisions / metrics シート作成＋企業シード
python -m src.main               # 巡回・選出・書き込み
python -m src.main --company エーザイ --since 2026-07-01
python -m src.main --reprocess-existing --company エーザイ --since 2026-07-01
```

`--reprocess-existing` は課金防止のため `--company` または `--since` / `--until` が必須です。

### 3. 実行タイミング

自動スケジューラは使いません。**Claude Code のチャットで実行を指示した都度**、上記コマンドを実行します。  
`decisions` シートによる同日discardキャッシュは実行頻度に関わらず機能するため、1日に何度実行しても再課金は抑制されます。

## 企業の追加方法

1. **まず** `config/companies.yaml` に追加（正本）
2. 必要なら Excel ブックで `enabled` / `crawl_mode` だけ上書き
3. 次回実行で同期・巡回される

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

例（JSON API）:

```json
{
  "json_url": "https://example.com/data/ann/1.json",
  "items_path": "item",
  "html_field": "contents",
  "html_link_selector": "a",
  "date_field": "anndate",
  "base_url": "https://example.com"
}
```

例（PR TIMES キーワードタグ）:

```json
{
  "keywords": ["創薬", "バイオテクノロジー", "医薬品", "動物用医薬品", "フードテック"],
  "max_per_keyword": 10
}
```

PR TIMES はカテゴリ別 RSS を提供していないため、キーワードタグの一覧ページを巡回します。
増分が確認できるまで `crawl_mode: shadow` で運用してください。

## 注意

- JS 描画の IR サイトは `eir` / `playwright` を使います。レイアウト変更で抽出が崩れたら YAML を更新してください
- 公式ソースが壊れたらその社だけ `tdnet_only` / `enabled: false` に戻し、TDnet は継続します
- PDF 本文は先頭ページから段落抽出します（画像PDFは空になることがあります）
- 同一 URL / 指紋は通常スキップします。再処理は対象を絞って実行してください
- 実行中に `EXCEL_FILE_PATH`（既定 `data/releases.xlsx`）を Excel アプリで開いていると書き込みに失敗します。実行前に閉じてください
