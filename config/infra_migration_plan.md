# GitHub Actions 脱却・実行モデル変更 設計方針

作成日: 2026-08-06
ステータス: **実装済み。** リポジトリはご自身のGitHubアカウント
（`h-ogawa0214/cwal_for_bio01`）へ移行し、`excel_client.py`・`crawl.yml`削除・
README更新まで完了。掲載可否判定もOpenAIではなくClaude Codeが直接行う方式
（[anthropic_migration_plan.md](anthropic_migration_plan.md) の案Bを採用）で実装済み。

## 背景・決定事項

- 社内ポリシーにより GitHub は非推奨。GitHub Actions によるスケジュール実行を廃止する。
- 定期実行の代替として Windows タスクスケジューラ等の自動化は使わず、
  **ユーザーが Claude Code に実行を指示した都度、この環境から `python -m src.main` を実行する**方式に変更。
  - 理由: 実行対象PCの常時電源ON・ログイン状態を維持する必要がなくなり、運用負荷が下がるため。
- 書き込み先を Google Sheets から **OneDrive 上の Excel（.xlsx）** に変更する。

## 変更が必要な箇所

| ファイル | 変更内容 |
|---|---|
| `.github/workflows/crawl.yml` | 削除（GitHub Actions を使わないため） |
| `src/sheets_client.py` | 廃止し、`src/excel_client.py`（仮）を新設。`openpyxl` で `.xlsx` を直接読み書き。companies/releases/decisions/metrics の4シート構成は維持 |
| `src/settings.py` | `SPREADSHEET_ID`/`GOOGLE_SERVICE_ACCOUNT_JSON` を廃止。Excelファイルパス設定（例: `EXCEL_FILE_PATH`）を追加 |
| `requirements.txt` | `gspread`/`google-auth` を削除（不要になる） |
| `README.md` | 「1日3回自動巡回」の記述を「Claude Codeへの指示による都度実行」に書き換え。セットアップ手順からGoogle関連を削除 |

## 影響を受けない部分（確認済み）

- **`decisions` シートによる同日discardキャッシュ**（`load_decision_cache`）は日付ベースの判定のため、
  実行が不定期になっても同じ日の再課金抑制は引き続き機能する。
- 抽出（`extractors/*`）、重複排除（`dedupe.py`）、選別ロジック（`curator.py`）は書き込み先と無関係のため無変更。

## 運用上のリスク・注意点

1. **Excelファイルの排他制御** — 実行中に本人がExcelで同じファイルを開いていると書き込み失敗の可能性。
   一時ファイルへの書き込み→置き換え方式などの対策が必要。
2. **OneDrive同期タイミング** — ローカル更新直後は他端末からの参照が古い内容になる可能性（同期完了待ち）。
3. **実行頻度がユーザー任せになる** — 自動での「1日3回」保証がなくなるため、記事の取得漏れ・遅延は
   ユーザーが指示するタイミングに依存する。

## 決定事項（更新）

1. **コードのバージョン管理の置き場所** — GitHub継続。ただし山地さん（Licca-07）のリポジトリとは
   独立させ、ご自身のアカウント（`h-ogawa0214/cwal_for_bio01`）に新規作成して全履歴を移行。
   山地さん側にのみ存在した直近8コミット分（PR TIMES企業別抽出器等）は今回未反映。
2. 掲載可否判定・タイトル/リード編集はOpenAI/Anthropic APIのどちらも使わず、
   Claude Codeが `--dump-for-review` / `--apply-review` の間で直接判定する方式を採用。

## 完了済みアクション

- [x] `excel_client.py` を実装（`sheets_client.py` と同等インターフェース）
- [x] `.github/workflows/crawl.yml` を削除
- [x] README・`.env.example` を更新
- [x] OpenAI連携を廃止し、Claude Codeレビュー方式に置き換え（`curator.py`の`evaluate()`/`finalize_reviewed()`、
      `main.py`の`--dump-for-review`/`--apply-review`）
