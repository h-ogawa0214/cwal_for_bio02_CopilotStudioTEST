# PR TIMES 企業別 18社 — Power Automate 移行テスト設計

作成日: 2026-08-14
対象: `config/companies.yaml` の `source_type: prtimes_company`（18社、全社 `crawl_mode: shadow`）
状態: 設計のみ。フロー未実装

## このテストの位置づけ

PR TIMES 企業別 18社**に限って**、収集から判定までを Power Automate だけで完結させる。
Python は使わない。ただし TDnet・各社サイト・PR TIMES キーワード一覧は対象外で、
当面 Python 側（元プロジェクト）が担当し続ける。

対象外にした理由:

| ソース | 除外理由 |
|---|---|
| TDnet（63社） | 開示本文が全て PDF。テキスト抽出に AI Builder 等の追加要素が必要 |
| playwright / eir（6社） | JS 描画。Power Automate に相当機能がない |
| PR TIMES キーワード一覧 | HTML パースが必要 |

PR TIMES 企業別だけは JSON API で完結し、本文も構造化データで取れるため、
Python なしで成立する見込みがある。

## 保存先

`data/pa_prtimes_test.xlsx`（OneDrive for Business 上）

**Power Automate 専用のブックとして新規に作成した。** 既存の `data/releases.xlsx` は使わない。
Python（openpyxl）が保存し直すたびに Excel のテーブル定義（ListObject）が失われる恐れがあり、
Excel Online (Business) コネクタはテーブルを必須とするため。

| シート | テーブル名 | 内容 |
|---|---|---|
| `_README` | — | ブックの説明 |
| `sources` | `tbl_sources` | 巡回対象 18 社（生成済み） |
| `candidates` | `tbl_candidates` | 収集結果＋判定結果 |
| `run_log` | `tbl_run_log` | 実行ログ |

`candidates` と `run_log` には**空白のデータ行が 1 行**入っている。Excel がテーブルに最低 1 行の
データ行を要求するため。フロー側で `release_key` / `run_id` が空の行を除外すること。

### Excel を選んだことによる制約

- **一意制約がない。** Dataverse の代替キーが使えないので、重複排除は「既存 `release_key` を全件読んで照合」で行う。18社・少件数なので問題ないが、件数が増えたら破綻する
- **1 セル 32,767 文字が上限。** `body_text` は切り詰めが必須（後述）
- **同時書き込みに弱い。** Apply to each の同時実行は必ず 1

なお Excel Online コネクタは Graph API 経由なので、**デスクトップ Excel でブックを開いていても
書き込みが失敗しない**。元プロジェクトの「実行中は Excel を閉じておく」制約（README:161）は
この経路では発生しない。

## 確認済みの API 仕様

### 一覧: 企業別プレスリリース API

```
GET https://prtimes.jp/api/company_content.php/companies/{company_id}/press_releases?limit=90
```

実測レスポンス（company_id=118632, 2026-08-14 時点）:

```json
{"data":{"total":5,
  "condition":{"skip":0,"limit":90,"year":null,"search_word":null},
  "data":[{"id":9,
    "title":"Angel Bridge、「地銀DXフォーラム」を開催　～ …",
    "url":"/main/html/rd/p/000000009.000118632.html",
    "company":{"id":118632,"name":"Angel Bridge株式会社"},
    "updated_at":{"time_iso_8601":"2026-06-10T12:10:07+09:00"},
    "release_comple_date":"2026-06-10T09:00:00+09:00"}]}}
```

- `data.total` が全件数。`data.data` が配列
- `url` は**相対パス**。`https://prtimes.jp` を連結する必要がある
- `condition` に `search_word` / `year` / `skip` があり、API 側で絞り込める可能性がある。
  ただし 1 語しか渡せないと思われ、6 語の OR には 6 リクエスト必要。総件数が少ないため
  全件取得＋ローカルフィルタのほうが効率がよい。**使わない**

**ページングは不要**（18社実測済み、詳細は [prtimes_total_survey.md](prtimes_total_survey.md)）。
API は新しい順に返す。`total > 90` の社が 4 社あるが、最も投稿頻度の高いグローバル・ブレイン
（total 584）でも `limit=90` で約 13 ヶ月ぶんを覆う。遡及 14 日の日次運用には大幅に余裕があるため
`skip` は実装しない。

### 詳細: 記事ページの埋め込み JSON

記事ページは Next.js で、`<script id="__NEXT_DATA__">` に構造化データが埋まっている。
**HTML パースは不要。** 実測で以下が取得できることを確認した。

`props.pageProps.pressRelease` のフィールド:

| フィールド | 実測値の例 | 用途 |
|---|---|---|
| `companyName` | `"Angel Bridge株式会社"` | 発表主体（正式名称） |
| `title` | 原題 | |
| `subtitle` / `head` | `""`（この記事では空） | 埋まっていればリード候補として優先 |
| `text` | `"<p>　独立系ベンチャーキャピタル（VC）の…"`（2,737 文字） | **本文。HTML 断片のまま** |
| `releaseCompleDate` | `"2026-06-10 09:00:01"` | 公開日時 |
| `lastUpdatedAt` | `"2026-06-10 12:10:07"` | 更新日時 |
| `releaseTypeName` | `"イベント"` | **カテゴリ。判定の補助シグナル** |
| `referenceUrl` | `"https://angelbridge.jp/"` | 参考 URL |
| `keywords` | 配列 | タグ |

**日付の形式が一覧 API と違う。** 一覧は `2026-06-10T09:00:00+09:00`（ISO 8601、オフセット付き）、
詳細は `2026-06-10 09:00:01`（スペース区切り、オフセットなし）。秒も 1 秒ずれている。
いずれも先頭 10 文字の切り出しで同じ日付になるので、`substring(x, 0, 10)` で統一する。

`formatDateTime()` は使わない。UTC に正規化して日付が 1 日ずれる恐れがあるため
（JST 午前 9 時未満のリリースで発生する）。

**`releaseTypeName` は判定に使えない**（22件で実測）。分布は `その他 ` 19件 / `経営情報` 3件で
識別力がなかった。事前フィルタには使わず、`candidates` に記録して判定プロンプトへの
参考情報として渡すのみとする。

**`その他 ` の末尾に半角スペースが入っている。** `equals()` で比較する実装をすると一致しない。
比較する場合は `trim()` を通すこと。

---

## フロー A: 収集（collect）

### A-1. トリガー

テスト中は「手動でフローをトリガーします」。入力パラメータ `lookback_days`（数値、既定 14）。
本運用では「繰り返し」（毎日 07:00 JST）に差し替える。

### A-2. 変数を初期化する

| 名前 | 種類 | 値 |
|---|---|---|
| `run_id` | 文字列 | `guid()` |
| `cutoff` | 文字列 | `addDays(convertFromUtc(utcNow(),'Tokyo Standard Time'), mul(triggerBody()?['lookback_days'], -1), 'yyyy-MM-dd')` |
| `candidates` | アレイ | `[]` |
| `fetched_total` | 整数 | `0` |
| `matched_keyword` | 整数 | `0` |
| `within_window` | 整数 | `0` |
| `error_count` | 整数 | `0` |

`utcNow()` をそのまま使うと日本時間の日付境界とずれるため `convertFromUtc` で JST に寄せる。

### A-3. 対象社の読み込み

**Excel Online (Business)「表内に存在する行を一覧表示」**
- ファイル: `data/pa_prtimes_test.xlsx`
- テーブル: `tbl_sources`

**「アレイのフィルター処理」（有効な行だけ）**
```
@equals(toLower(string(item()?['enabled'])), 'true')
```
Excel はブール値を `TRUE` / `true` など揺れた表記で返すため、`toLower(string(...))` で正規化する。

### A-4. それぞれに適用する（18社ループ）

**設定 → 同時実行制御: オン、次の値まで = 1**

理由が 2 つある。PR TIMES へ 18 本同時アクセスしないため（元コードの `HttpClient` は
同期 httpx で逐次アクセス）と、後段の変数更新が並列実行で壊れないため。
**既定の並列 20 のままだと両方が壊れる。**

#### スコープ（Try）

**① HTTP**
```
メソッド: GET
URI: https://prtimes.jp/api/company_content.php/companies/@{items('それぞれに適用する')?['company_id']}/press_releases?limit=90
ヘッダー:
  User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36
  Accept-Language: ja,en-US;q=0.9,en;q=0.8
設定 → 再試行ポリシー: 指数間隔 / 回数 4 / 間隔 PT1S
```

**② JSON の解析** — コンテンツ `body('HTTP')`、スキーマは末尾に記載

**③ 変数の設定** `fetched_total` = `add(variables('fetched_total'), body('JSON_の解析')?['data']?['total'])`

**④ アレイのフィルター処理（キーワード）**
- 開始: `body('JSON_の解析')?['data']?['data']`
- 詳細モード:
```
@or(contains(item()?['title'], '出資'), contains(item()?['title'], '資本参加'), contains(item()?['title'], 'リード投資'), contains(item()?['title'], '引受'), contains(item()?['title'], 'ファンド'), contains(item()?['title'], '投資事業有限責任組合'))
```
6 語の **OR**（AND ではない）、**部分一致**。元コード `src/extractors/prtimes.py:158` の
`any(kw in title for kw in include)` と同じ挙動。

`sources.include_keywords` 列は参考値として持たせているが、テストフローは上の固定式を使う。
Excel から読んだカンマ区切りを OR 条件に展開する式は Filter array の詳細モードでは
`item()` が衝突して書けない。

**⑤ 変数の設定** `matched_keyword` += `length(body('アレイのフィルター処理'))`

**⑥ アレイのフィルター処理 2（遡及窓）**
- 開始: `body('アレイのフィルター処理')`
- 詳細モード:
```
@greaterOrEquals(substring(coalesce(item()?['release_comple_date'], item()?['updated_at']?['time_iso_8601']), 0, 10), variables('cutoff'))
```

**⑦ 変数の設定** `within_window` += `length(body('アレイのフィルター処理_2'))`

**⑧ 選択**
- 開始: `body('アレイのフィルター処理_2')`

| キー | 値 |
|---|---|
| `release_key` | `concat(string(item()?['company']?['id']), '-', string(item()?['id']))` |
| `source_name` | `items('それぞれに適用する')?['source_name']` |
| `company_id` | `string(item()?['company']?['id'])` |
| `release_id` | `string(item()?['id'])` |
| `title` | `item()?['title']` |
| `url` | `concat('https://prtimes.jp', item()?['url'])` |
| `published_on` | `substring(coalesce(item()?['release_comple_date'], item()?['updated_at']?['time_iso_8601']), 0, 10)` |
| `crawl_mode` | `items('それぞれに適用する')?['crawl_mode']` |

`release_key` は `118632-9` の形になる。API が `company.id` と `id` を返すので、
URL を正規化してキーにする必要がない。Excel の行更新キーとしても短くて扱いやすい。

**⑨ 変数の設定** `candidates` = `union(variables('candidates'), body('選択'))`

「配列変数に追加」は配列を 1 要素として入れ子にしてしまうため `union()` で平坦に連結する。

#### スコープ（Catch）

「設定 → 実行条件の構成」で**失敗時／タイムアウト時**にチェック。
中身は `error_count` のインクリメントと、`run_log` の `notes` に残す文字列の組み立て。
1 社が落ちても残り 17 社を止めない。元コードも `try/except` で同じ挙動
（`src/extractors/prtimes.py:147`）。

### A-5. 既存分の除外（ループの外）

**① Excel「表内に存在する行を一覧表示」** — `tbl_candidates`

**② アレイのフィルター処理（空白行を除外）**
```
@not(empty(item()?['release_key']))
```

**③ 選択（既存キーの配列化）** — 開始は ② の出力、マップは**テキストモード**で `item()?['release_key']`

**④ アレイのフィルター処理（新規のみ）**
- 開始: `variables('candidates')`
- 詳細モード:
```
@not(contains(body('選択_既存キー'), item()?['release_key']))
```

### A-6. 本文取得と登録

**それぞれに適用する 2**（開始: A-5 ④ の出力、**同時実行 1**）

**① HTTP 2** — GET `item()?['url']`、ヘッダーと再試行は ① と同じ

**② 条件（構造チェック）**
```
@contains(string(body('HTTP_2')), '__NEXT_DATA__')
```
「いいえ」の場合は `body_text` を空にして `reason` に `no_next_data` を記録し、行だけ追記する。
ページ構造が変わったときに黙って壊れないようにするため。

**③ 作成（Compose_seg）**
```
first(split(last(split(string(body('HTTP_2')), '__NEXT_DATA__"')), '</script>'))
```

**④ 作成（Compose_json）**
```
substring(outputs('Compose_seg'), indexOf(outputs('Compose_seg'), '{'), sub(length(outputs('Compose_seg')), indexOf(outputs('Compose_seg'), '{')))
```
`nonce` 属性が実行ごとに変わるため、タグの終わり `>` を固定文字列で狙えない。
最初の `{` の位置から末尾までを切り出す。

**⑤ 作成（Compose_pr）**
```
json(outputs('Compose_json'))?['props']?['pageProps']?['pressRelease']
```

**⑥ 作成（Compose_body）** — Excel のセル上限対策
```
if(greater(length(coalesce(outputs('Compose_pr')?['text'], '')), 30000), substring(outputs('Compose_pr')?['text'], 0, 30000), coalesce(outputs('Compose_pr')?['text'], ''))
```
Excel の 1 セル上限は 32,767 文字。実測では 2,737 文字だったが、長いリリースで超える可能性がある。

**⑦ Excel「表に行を追加」** — `tbl_candidates`

| 列 | 値 |
|---|---|
| `release_key` | `item()?['release_key']` |
| `run_id` | `variables('run_id')` |
| `fetched_at` | `convertFromUtc(utcNow(),'Tokyo Standard Time','yyyy-MM-dd HH:mm:ss')` |
| `source_name` | `item()?['source_name']` |
| `company_id` | `item()?['company_id']` |
| `release_id` | `item()?['release_id']` |
| `company_name` | `outputs('Compose_pr')?['companyName']` |
| `title` | `item()?['title']` |
| `url` | `item()?['url']` |
| `published_on` | `substring(coalesce(outputs('Compose_pr')?['releaseCompleDate'], item()?['published_on']), 0, 10)` |
| `release_type` | `outputs('Compose_pr')?['releaseTypeName']` |
| `reference_url` | `outputs('Compose_pr')?['referenceUrl']` |
| `body_text` | `outputs('Compose_body')` |
| `status` | `pending` |

`published_on` は詳細側を優先する。元コードも詳細から日付が取れたら上書きする挙動
（`src/main.py:250-251`）。

### A-7. run_log 追記

**Excel「表に行を追加」** — `tbl_run_log`

`run_id` / `phase` = `collect` / `started_at` / `finished_at` / `source_count` /
`fetched_total` / `matched_keyword` / `within_window` / `new_rows` = `length(body('アレイのフィルター処理_新規のみ'))` / `errors`

---

## フロー B: 判定（judge）

収集と分けている理由は、**プロンプトを直して判定だけ再実行できるようにするため**。
`candidates` の `status` を `pending` に戻せば、再取得なしで判定をやり直せる。
元プロジェクトの `--dump-for-review` / `--apply-review` の 2 段構成と同じ狙い。

### B-1. トリガー
手動（テスト中）。将来はフロー A の完了時に呼ぶ。

### B-2. 対象の抽出

**Excel「表内に存在する行を一覧表示」** — `tbl_candidates`

**「アレイのフィルター処理」**
```
@and(not(empty(item()?['release_key'])), equals(item()?['status'], 'pending'))
```

### B-3. それぞれに適用する（同時実行 1〜3）

**① プロンプト**（AI Builder のプロンプト、または Copilot Studio のプロンプト）

指示文には `config/criteria.md` の内容をそのまま落とし込む。入力は以下。

- `company_name`
- `title`
- `release_type`（PR TIMES のカテゴリ。判断の参考。これ単独で結論を出さないよう明記する）
- `body_text`（HTML 断片のまま。タグは無視するよう指示する）

出力形式:
```json
{"decision":"keep|discard","edited_title":"","lead":"","reason":""}
```

`criteria.md` の「タイトル補正」「リード選定」の節をそのまま指示に含める。特に
「原文の事実・数値・固有名詞・試験相を変更しない」「推測や評価を加えない」は必須。

**領域限定を必ず明示する。** キーワード 6 語のフィルタは「投資ニュースかどうか」しか
見ておらず、**領域を絞っていない**。18社の実測では、キーワード一致 97 件（直近 365 日）の
大半がショートドラマ配信・量子技術・セールス AI・太陽電池・自動運転・宇宙輸送など、
創薬・バイオと無関係な出資案件だった。

`criteria.md` の keep 条件「資金調達」は領域の限定を明文化していないため、プロンプト側で
「創薬・バイオテクノロジー領域に限る」旨を明示する必要がある。**これを落とすと無関係な
出資リリースが大量に keep される。** このコホートにおける判定プロンプトの主たる仕事は、
`criteria.md` のカテゴリ判定よりむしろ領域判定である。

**② JSON の解析** — ① の出力

**③ Excel「行の更新」** — `tbl_candidates`
- キー列: `release_key`、キー値: `item()?['release_key']`
- 更新: `status` = `reviewed`、`decision` / `edited_title` / `lead` / `reason`、
  `judged_at` = `convertFromUtc(utcNow(),'Tokyo Standard Time','yyyy-MM-dd HH:mm:ss')`

### B-4. 掲載反映はしない

18社すべて `crawl_mode: shadow` のため、`releases` に相当する出力は**行わない**。
判定履歴だけを残して精度を検証する。

live 化する段では、`crawl_mode = 'live'` かつ `decision = 'keep'` の行に対して
**承認アクションを挟む**。`CLAUDE.md` の「掲載可否・最終承認は人が担当する」に沿わせるため、
AI の判定は一次判断として扱い、掲載前に人の承認を必須とする。

### B-5. run_log 追記
`phase` = `judge`、keep / discard の内訳を `notes` に記録。

---

## JSON の解析スキーマ（一覧 API 用）

`thumbs` などの未使用プロパティは定義しなくてよい。解析時に無視される。

```json
{
  "type": "object",
  "properties": {
    "data": {
      "type": "object",
      "properties": {
        "total": { "type": "integer" },
        "data": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "id": { "type": "integer" },
              "title": { "type": "string" },
              "url": { "type": "string" },
              "company": {
                "type": "object",
                "properties": {
                  "id": { "type": "integer" },
                  "name": { "type": "string" }
                }
              },
              "updated_at": {
                "type": "object",
                "properties": {
                  "time_iso_8601": { "type": ["string", "null"] }
                }
              },
              "release_comple_date": { "type": ["string", "null"] }
            },
            "required": ["title", "url"]
          }
        }
      }
    }
  }
}
```

日付系を `["string", "null"]` にし、`required` から外しているのは、null が返る企業が
あった場合に解析全体が失敗しないようにするため。

---

## テスト時の注意

### 「0 件」は正常な結果

実測した Angel Bridge の唯一のリリース（2026-06-10、「地銀DXフォーラム」開催）は、
キーワード 6 語のいずれにも一致せず、かつ遡及窓 14 日の外にある。
**この社からの候補は 0 件になるのが正しい。** フローの故障と誤認しないこと。

### テスト用の遡及期間

18社の実測（2026-08-14 時点）でのキーワード一致件数:

| 遡及 | 件数 | 用途 |
|---|---|---|
| 14 日（既定） | 3 | 疎通確認。全てグローバル・ブレイン |
| 90 日 | 22 | **判定プロンプトの検証に手頃** |
| 365 日 | 97 | トークン消費の実測 |

疎通確認は既定の 14 日で行い（3 件入るので行が入ることは確認できる）、判定プロンプトの
検証は `lookback_days = 90` で行う。

### 必ず確認する設定

- **Apply to each の同時実行を 1 にする。** 既定の並列 20 では、PR TIMES への同時アクセスと
  `candidates` 変数の競合が同時に起きる
- **HTTP アクションはプレミアムコネクタ。** DLP ポリシーで任意の外部 URL への
  アクセスが許可されているかを最初に確認する。ここが通らないとこの構成は成立しない

---

## 未確認事項

1. **DLP ポリシー** — HTTP アクションで prtimes.jp に出られるか。未確認。**最初に確認すべき項目**
2. **ライセンス** — HTTP はプレミアムコネクタ。AI Builder クレジットまたは
   Copilot Studio メッセージの消費見積もりも未実施
3. ~~`limit` の上限と 18 社の `total`~~ → **実測済み**。
   [prtimes_total_survey.md](prtimes_total_survey.md) 参照。取得エラー 0 社、
   ページング不要、18社合計 total 1,423 件。`limit` を 90 より大きくしたときの挙動は未確認だが、
   90 で足りるため確認不要と判断した。
   なお **`limit` に 10 未満を指定しても 10 に切り上げられる**（`limit=5` で10件返り、
   `condition.limit` も `10` に書き換わる）。少数件だけ取る用途では使えないため、
   フロー側で `first()` / `take()` により絞ること
4. ~~`releaseTypeName` の取り得る値~~ → **実測済み**。22件で `その他 ` 19 / `経営情報` 3。
   識別力がなく事前フィルタには使えない
5. **`__NEXT_DATA__` 構造の安定性** — PR TIMES 側の実装詳細であり、予告なく変わりうる。
   A-6 ② の条件で検知できるようにしてある。なお **22ページで抽出成功 22/22**
   （A-6 ③④の式と同じ手順で検証済み）。`body_text` の実測長は 1,577〜3,401 文字で、
   切り詰め（30,000）は実質発生しない
8. **判定プロンプトの精度** — [judge_prompt_draft.md](judge_prompt_draft.md) は未実行。
   [prtimes_expected_90d.md](prtimes_expected_90d.md) の想定判定（keep 1 / discard 21）と
   突き合わせて測る
9. ~~掲載領域の定義~~ → **解決**。2026-08-14 にフードテック・バイオ生産を含める判断を得て、
   `config/criteria.md` に「対象領域」節として明文化した。
   なお `criteria_version`（`settings.py:31`）は criteria.md の SHA256 を含むため、
   この追記で版が変わる。Python 側の判定履歴との突き合わせでは版差に注意する
6. **API の利用規約上の位置づけ** — `company_content.php` は公開ドキュメントのない内部 API。
   Microsoft のクラウド IP からの定期アクセスに変わるため、レート制限やブロックの扱いは要確認
7. **`prtimes.jp` へのアクセス頻度** — 一覧 18 本＋詳細（候補件数分）。日次で問題ない規模だが、
   同時実行 1 の逐次アクセスを崩さないこと

## 関連ドキュメント

- [config/criteria.md](../config/criteria.md) — 掲載可否の判断基準（判定プロンプトの原文）
- [config/vc_cohort.md](../config/vc_cohort.md) — VC 陣の運用方針
- [docs/overview.md](overview.md) — 元プロジェクト（Python）全体の処理の流れ
