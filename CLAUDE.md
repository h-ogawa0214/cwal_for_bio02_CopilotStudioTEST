# CLAUDE.md — pr-disclosure-curator 運用指示

創薬・バイオテクノロジー関連企業のプレスリリース／適時開示を巡回し、雑誌サイト掲載に
値するものだけを OneDrive 上の Excel（`data/releases.xlsx`）へ書き出すツール。

全体像は [docs/overview.md](docs/overview.md) を参照。判断基準は
[config/criteria.md](config/criteria.md) と [config/editorial_examples.json](config/editorial_examples.json)。

## 「巡回して」「実行して」等の指示を受けたときの手順

自動スケジューラは無く、LLM APIも呼ばない。**この対話（Claude Code自身）が判定する。**
以下の3段階を順に実行する。

### 1. 巡回・抽出・自動除外

```bash
python -m src.main --dump-for-review .tmp/review_<日付など>.json
```

- 必要なら `--company <企業名>`（複数指定可）、`--since <YYYY-MM-DD>`、`--until <YYYY-MM-DD>` で絞り込む
- 実行前に `.venv` が有効か確認する（無ければ `python -m venv .venv` → `pip install -r requirements.txt` →
  `python -m playwright install chromium`）

### 2. 判定（自分で行う。API呼び出しはしない）

1. 出力されたJSONを読む（`pending` 配列。件数が多い場合はUTF-8のテキストファイルに要約して読むと文字化けを避けられる）
2. `config/criteria.md` の「残す（keep）」「捨てる（discard）」基準、および「タイトル補正」「リード選定」の
   ルールに沿って、各候補を判定する
   - 決算短信・有価証券報告書など定型IR書類のみで新規事実に乏しいものは discard
   - 自己株式取得、人事異動（部長級以下）、社会貢献イベント単体、セミナー・Webinar告知も discard
   - 承認取得・申請・臨床試験・業務提携・共同研究・資金調達・新製品発売・研究成果は keep
   - 決算説明資料等に埋め込まれた臨床試験進捗・パイプライン情報は、定型IRと区別してkeep判断すること
   - VC出資判定は、投資先が創薬・バイオ関連企業かどうかを確認してから判断する（無関係な投資先は discard）
3. 各候補の `review` フィールドに判定結果を書き込む
   - discard: `{"keep": false, "reason": "..."}`
   - keep: `{"keep": true, "reason": "...", "title": "...", "lead": "..."}`
   - タイトルは発表主体を補い、リードは原文の事実を変えず抽出崩れだけ修正する

### 3. 反映

```bash
python -m src.main --apply-review .tmp/review_<日付など>.json
```

- 実行前に、`data/releases.xlsx` がExcelアプリ等で開かれていないか確認する（開いていると書き込み失敗）
- 完了後、書き込み件数と主な記事をユーザーに報告する
- 一時ファイル（`.tmp/` 配下）は完了後に削除してよい（`.gitignore`対象、社外送信・共有はしない）

## 注意

- コード変更を行った場合は、変更内容をコミットし、GitHub（`h-ogawa0214/cwal_for_bio01`）へpushする
- `--reprocess-existing` は課金防止ではなく再確認の重複作業防止のため、`--company` または
  `--since`/`--until` の指定が必須
