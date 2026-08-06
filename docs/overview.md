# pr-disclosure-curator 全体の処理の流れ

作成日: 2026-08-06

創薬・バイオテクノロジー関連企業のプレスリリース／適時開示を巡回し、雑誌サイト掲載に
値するものだけを選び、OneDrive上のExcelへ書き出すツールの全体像。

## システム構成（3つの場所）

| 場所 | 役割 | 補足 |
|---|---|---|
| **GitHub**（`h-ogawa0214/cwal_for_bio01`、非公開） | ソースコードのバージョン管理のみ | 実行データ・記事本文は一切含まない |
| **このPC** | コードの実行場所 | GitHubの作業コピーそのもの。Claude Codeへの指示で都度実行 |
| **OneDrive上のExcel**（`data/releases.xlsx`） | 実行結果（記事データ）の保存場所 | GitHubには含まれない（`.gitignore`対象） |

自動スケジューラ（GitHub Actions等）は使わない。**都度、あなたがClaude Codeに実行を指示する**運用。

## 処理の流れ（3段階）

### 1. 巡回・抽出・自動除外 — `python -m src.main --dump-for-review <path>`

1. `config/companies.yaml`（正本）とExcelの`companies`シートを同期
2. 対象企業のサイト（html_css/rss/xlsx/json_api/sitemap/eir/playwright）＋ TDnet（全社共通の適時開示閲覧サービス）＋ PR TIMES（キーワード一覧・企業別）を巡回
3. 同一記事の重複をクラスタリングで排除（同一URL・タイトル類似・会社名+日付一致）
4. 詳細ページ／PDFから本文段落を抽出
5. 既存Excel記載分・同日discardキャッシュ・重複指紋はスキップ
6. **ハード除外タイトル**（助成金受領・IR Q&A・払込完了等）と**明確なヒューリスティック除外**（採用・イベント告知・自己株式等のキーワード）はここで自動的にdiscard確定
7. 上記で決着しない候補を、判定待ちとしてレビューキュー（JSON）に書き出す

### 2. Claude Codeによる判定（この対話の中で実施）

- レビューキューJSONを読み、`config/criteria.md`（掲載可否の判断基準）と
  `config/editorial_examples.json`（編集お手本）に沿って、各候補を **keep / discard** 判定
- keepの場合は、媒体向けにタイトル・リード文を編集（原題の重要事実は保持し、主語や
  発表主体を補うなど）
- 判定結果をJSON内の`pending[].review`に書き込む

**LLM APIは呼ばない。** 判定は実行を指示されたClaude Code自身が対話の中で行う。

### 3. 判定結果の反映 — `python -m src.main --apply-review <path>`

1. レビュー結果を取り込み、最終的な記事データを構築
2. 企業ごとの`crawl_mode`（live / shadow）に応じて振り分け
   - **live**: `releases`シートへ実際に書き込み
   - **shadow**: 判定・記録はするが`releases`には書かない（新規ソースの精度検証用）
3. 同一記事の重複（URL・指紋）を最終チェック
4. `decisions`シート（判定履歴・同日再判定抑制のキャッシュ元）、`metrics`シート
   （候補数・keep/discard内訳・ソース別件数）に記録
5. `releases`シートを`published_on`の降順に整列

## 次回実行時、既存データはどうなるか

- 既存の`releases`行は**そのままキープ**される（同じURLの記事は既知として自動スキップされ、
  私の判定対象にすら上がらない）
- 新しく見つかった記事だけが追加される
- `--reprocess-existing`を対象を絞って明示的に指定した場合のみ、既存行が上書き更新される

## バージョン管理

- コード変更は都度コミットし、GitHub（`h-ogawa0214/cwal_for_bio01`）へpush
- 山地さん（Licca-07）の元リポジトリとは完全に独立（自動同期なし）。直近8コミット分
  （詳細未確認）は本リポジトリに未反映

## 運用上の注意

- 実行中は`data/releases.xlsx`をExcelアプリで開いたままにしない（書き込み失敗の原因）
- レビューキューJSON（一時ファイル、`.gitignore`対象）には掲載可否未決定の記事本文が
  そのまま含まれるため、社外送信・共有はしない
- keep/discard判定は私（Claude Code）の一次判断。境界的な案件は`decisions`シートの
  `reason`列で判断根拠を確認できる

## 関連ドキュメント

- [config/criteria.md](../config/criteria.md) — 掲載可否の判断基準
- [config/anthropic_migration_plan.md](../config/anthropic_migration_plan.md) — LLM判定方式の検討経緯（不採用案の記録）
- [config/infra_migration_plan.md](../config/infra_migration_plan.md) — GitHub移行・Excel化の設計経緯
- [README.md](../README.md) — セットアップ手順
