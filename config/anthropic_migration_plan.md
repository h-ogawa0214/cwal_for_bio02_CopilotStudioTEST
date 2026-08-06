# OpenAI → Anthropic (Claude) 移行設計方針（ドラフト）

作成日: 2026-08-06
ステータス: **設計方針のみ。実装未着手。**

## 目的

`src/curator.py` が OpenAI Chat Completions API（`gpt-4o-mini`）で行っている
以下2段の LLM 呼び出しを、Anthropic API（Claude）に置き換えられるか検討する。

1. `_llm_classify` — 一次判定（keep / discard / uncertain）
2. `_llm_edit` — 媒体向けタイトル・リード編集

## 方針（決定事項）

- **モデル構成**: 一次判定・編集とも**同一モデル**を使う（現行の gpt-4o-mini 運用を踏襲し、
  役割分担による設定・コスト集計の複雑化を避ける）。
  - 候補: `claude-haiku-4-5-20251001`（コスト重視）または `claude-sonnet-5`（品質重視）。
  - **要確認**: どちらを既定にするか。判定精度とコストのトレードオフはコード変更前に
    サンプル記事で比較検証する想定。
- **切替方式**: 未決定（下記オプション参照）。実装着手時に決める。

## 変更が必要な箇所（影響範囲の棚卸し）

| ファイル | 変更内容 | リスク |
|---|---|---|
| `src/curator.py` | `OpenAI` クライアント → `Anthropic` クライアント。`response_format={"type":"json_object"}` は Anthropic に同等機能が無いため、**tool_use（強制ツール呼び出し）**で JSON を取得する形に書き換え | 中（プロンプト構造・パース処理の作り直し） |
| `src/settings.py` | `OPENAI_API_KEY`/`OPENAI_MODEL` → `ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL`（or 両対応） | 低 |
| `src/metrics.py` | `_INPUT_PER_M`/`_OUTPUT_PER_M` が `gpt-4o-mini` 固定単価。Claude モデルの単価に置換。`add_usage()` の usage 属性名が OpenAI 形式（`prompt_tokens`/`completion_tokens`）なので Anthropic 形式（`input_tokens`/`output_tokens`）に対応 | 低〜中（コスト集計の実値がズレるとレポートの信頼性に直結） |
| `requirements.txt` | `openai` → `anthropic`（or 併記） | 低 |
| `.github/workflows/crawl.yml` | Secret名 `OPENAI_API_KEY` → `ANTHROPIC_API_KEY` 等。**Secret登録はユーザー側作業** | — |
| `.env.example` / `README.md` | 環境変数名・セットアップ手順の更新 | 低 |
| `tests/` | OpenAI クライアントをモックしているテストの追随 | 低 |

## 未決定事項（実装着手前に決めること）

1. **切替方式**
   - (a) OpenAI を完全に置き換える
   - (b) 環境変数で OpenAI / Anthropic を選べるようにする（shadow 運用と同じ発想で比較検証しやすい）
   - (c) 一定期間、両方に投げて判定結果を `decisions` シートで突き合わせる（コスト2倍だが最も検証が堅い）
2. **JSON 出力の担保方法の具体化**（tool_use のスキーマ設計）
3. **モデル既定値**（Haiku 4.5 か Sonnet 5 か。criteria.md の判断基準に対する再現性を実データで比較してから決める）
4. **コスト集計の単価更新**（`metrics.py` のハードコード単価は要メンテナンス性の低さも合わせて見直すか検討）

## 影響を受けない範囲（確認済み）

- ヒューリスティック判定（`heuristic_decision`）、ハード除外（`HARD_DISCARD_TITLE_PATTERNS`）は
  LLM 非依存のため無変更。
- 抽出（`extractors/*`）、重複排除（`dedupe.py`）、Sheets 書き込み（`sheets_client.py`）は無関係。
- `OPENAI_API_KEY` 未設定時のヒューリスティックのみ運用モードは、変更後も同様に維持可能。

## 次のアクション（着手時）

- [ ] 切替方式（上記1）をユーザーと確定
- [ ] `curator.py` の tool_use 化プロトタイプを作成し、既存 `config/editorial_examples.json` の
      few-shot 例で出力品質を手動比較
- [ ] `metrics.py` の単価・usage 属性を更新
- [ ] `ANTHROPIC_API_KEY` を GitHub Secret に登録（ユーザー作業）
- [ ] shadow 運用と同様、本番 `releases` に書かない検証期間を挟むか判断
