# GitHub Actions 脱却・実行モデル変更 設計方針（ドラフト）

作成日: 2026-08-06
ステータス: **設計方針のみ。実装未着手。**

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

## 未決定事項

1. **コードのバージョン管理の置き場所** — ローカル git のみか、社内の別Git基盤（Azure DevOps等）を使うか。
2. **実装着手のタイミング** — 設計整理を続けるか、`excel_client.py` 実装 / `crawl.yml` 削除 / README更新に進むか。
3. OpenAI→Anthropic移行（[anthropic_migration_plan.md](anthropic_migration_plan.md)）とこの変更を同時に進めるか、別々に進めるか。

## 次のアクション（着手時）

- [ ] バージョン管理方針を確定
- [ ] `excel_client.py` を実装し、`sheets_client.py` と同等のインターフェース（`ensure_schema`/`load_companies`/
      `existing_release_keys`/`load_decision_cache`/`append_decisions`/`append_run_metrics`/`upsert_releases`）を
      維持しつつ Excel 版として作成
- [ ] `.github/workflows/crawl.yml` を削除
- [ ] README・`.env.example` を更新
