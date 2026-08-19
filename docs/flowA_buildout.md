# フロー A 本番化 段階手順（疎通テストからの拡張）

作成日: 2026-08-19
前提: [flowA_smoke_test.md](flowA_smoke_test.md) の疎通テストが完了していること
設計の正本: [power_automate_prtimes.md](power_automate_prtimes.md)

## 進め方の原則

**1ステップ足すごとに実行して検証する。** まとめて作ると失敗の切り分けができない。
各ステップに「検証」を書いてあるので、そこを満たしてから次へ進む。

## 全ステップ共通の注意

**① 式は必ず `fx` エディタから入れる**

テキスト欄に直接打つとリテラル文字列になる。疎通テストで実際に踏んだ。

**② 貼り付けると引用符が化ける**

`'`（ASCII）が `'`（カーリークォート）に変わると式として解釈されない。手入力か入力補完を使う。

**③ 式の中のアクション名は実際の名前に合わせる**

表示名の**半角スペースはアンダースコアに置き換わる**。「JSON の解析」→ `JSON_の解析`。
同名アクションを追加すると「選択 2」のように連番が付き、式では `選択_2` になる。
**このドキュメントのアクション名は想定値なので、実際の名前を確認して読み替えること。**

**④ 「それぞれに適用する」の同時実行は必ず 1 にする**

「設定 → 同時実行制御: オン、次の値まで = 1」。理由は2つある。

- PR TIMES へ18本同時アクセスしないため（元コードの `HttpClient` は同期 httpx で逐次）
- ループ内の「変数の設定」が並列実行で壊れるため

**既定は並列20。放置すると両方壊れる。**

## 開始時点のフロー

```
Recurrence
  → HTTP
  → JSON の解析
  → 作成
  → 表に行を追加
  → (Copilotプロンプト ※テスト用)
```

## 到達点

```
Recurrence
  → 変数を初期化する ×6
  → 表内に存在する行を一覧表示（tbl_sources）
  → アレイのフィルター処理（enabled）
  → それぞれに適用する（18社／同時実行1）
       → HTTP
       → JSON の解析
       → アレイのフィルター処理（キーワード）
       → アレイのフィルター処理 2（遡及窓）
       → 選択
       → 変数の設定（candidates に union）
  → 表内に存在する行を一覧表示 2（tbl_candidates）
  → アレイのフィルター処理 3（空白行の除外）
  → 選択 2（既存キーの配列化）
  → アレイのフィルター処理 4（新規のみ）
  → それぞれに適用する 2（新規候補／同時実行1）
       → HTTP 2（記事ページ）
       → 作成（Compose_seg / Compose_json / Compose_pr / Compose_body）
       → 表に行を追加
  → 表に行を追加 2（tbl_run_log）
```

---

# ステップ1: sources を読んでループする

まだ1社1件のままにして、**ループと動的 company_id だけ**を検証する。

## 1-1. Recurrence の直後に「変数を初期化する」を2つ追加

| 名前 | 種類 | 値 |
|---|---|---|
| `run_id` | 文字列 | `guid()` |
| `lookback_days` | 整数 | `90` |

トリガーが Recurrence で入力パラメータを持てないため、`lookback_days` は変数で持つ。
テスト中は 90、本運用では 14 にする。

## 1-2.「表内に存在する行を一覧表示」を追加

- ファイル: `data/pa_prtimes_test.xlsx`
- テーブル: **`tbl_sources`**

## 1-3.「アレイのフィルター処理」を追加

- 開始: `body('表内に存在する行を一覧表示')?['value']`
- **詳細モード**:

```
@equals(toLower(string(item()?['enabled'])), 'true')
```

Excel はブール値を `TRUE` / `true` と揺れた表記で返すため `toLower(string(...))` で正規化する。

## 1-4.「それぞれに適用する」を追加し、既存4アクションを中へ移す

- 開始: `body('アレイのフィルター処理')`
- **設定 → 同時実行制御: オン、次の値まで = 1**
- 中に入れる: `HTTP` / `JSON の解析` / `作成` / `表に行を追加`

## 1-5. HTTP の URI を動的にする

```
https://prtimes.jp/api/company_content.php/companies/@{items('それぞれに適用する')?['company_id']}/press_releases?limit=90
```

`limit` を 10 から **90** に変更する。

## 1-6.「表に行を追加」の3列を差し替える

| 列 | 変更後 |
|---|---|
| `run_id` | `variables('run_id')` |
| `source_name` | `items('それぞれに適用する')?['source_name']` |
| `status` | `pending` |

## 検証

**18行入ること。** 各社の最新1件が1行ずつ入る。

- `source_name` が18社ぶん異なること（`グローバル・ブレイン` 固定になっていたら 1-6 の差し替え漏れ）
- `run_id` が18行すべて同じ GUID であること
- `company_id` が18社ぶん異なること

実行後、この18行は削除してよい。

---

# ステップ2: キーワードフィルタと遡及窓を入れる

**ここが最も変更量が大きい。** 1社1件から「条件に合う複数件」に変わるため、
配列に溜めて後でまとめて書く形に組み替える。

## 2-1.「変数を初期化する」を4つ追加（ステップ1のものに続けて）

| 名前 | 種類 | 値 |
|---|---|---|
| `cutoff` | 文字列 | `addDays(convertFromUtc(utcNow(),'Tokyo Standard Time'), mul(variables('lookback_days'), -1), 'yyyy-MM-dd')` |
| `candidates` | アレイ | （空欄のまま） |
| `fetched_total` | 整数 | `0` |
| `error_count` | 整数 | `0` |

`cutoff` は `lookback_days` を参照するので、**必ず `lookback_days` より後**に置く。

## 2-2. ループ内の「作成」と「表に行を追加」をループの外に出す／削除する

- **「作成」は削除する**（`first()` で1件に絞る役目が終わる）
- **「表に行を追加」はループの外に移す**（後で新しいループの中に入れる）

## 2-3. ループ内、「JSON の解析」の後に「アレイのフィルター処理 2」を追加（キーワード）

- 開始: `body('JSON_の解析')?['data']?['data']`
- **詳細モード**:

```
@or(contains(item()?['title'], '出資'), contains(item()?['title'], '資本参加'), contains(item()?['title'], 'リード投資'), contains(item()?['title'], '引受'), contains(item()?['title'], 'ファンド'), contains(item()?['title'], '投資事業有限責任組合'))
```

6語の **OR**、**部分一致**。元コード `src/extractors/prtimes.py:158` と同じ挙動。

## 2-4.「アレイのフィルター処理 3」を追加（遡及窓）

- 開始: `body('アレイのフィルター処理_2')`
- **詳細モード**:

```
@greaterOrEquals(substring(coalesce(item()?['release_comple_date'], item()?['updated_at']?['time_iso_8601']), 0, 10), variables('cutoff'))
```

## 2-5.「選択」を追加

- 開始: `body('アレイのフィルター処理_3')`
- マップ（**キー／値モード**）:

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

## 2-6.「変数の設定」を追加（ループ内の最後）

- 名前: `candidates`
- 値: `union(variables('candidates'), body('選択'))`

**「配列変数に追加」は使わない。** 配列を1要素として入れ子にしてしまう。`union()` で平坦に連結する。

## 2-7.「変数の設定 2」を追加（件数カウント、任意）

- 名前: `fetched_total`
- 値: `add(variables('fetched_total'), body('JSON_の解析')?['data']?['total'])`

## 2-8. ループの外に「それぞれに適用する 2」を追加し、「表に行を追加」を中へ

- 開始: `variables('candidates')`
- **同時実行: 1**

「表に行を追加」の列を、`item()` 参照に差し替える。

| 列 | 値 |
|---|---|
| `release_key` | `item()?['release_key']` |
| `run_id` | `variables('run_id')` |
| `fetched_at` | `convertFromUtc(utcNow(),'Tokyo Standard Time','yyyy-MM-dd HH:mm:ss')` |
| `source_name` | `item()?['source_name']` |
| `company_id` | `item()?['company_id']` |
| `release_id` | `item()?['release_id']` |
| `title` | `item()?['title']` |
| `url` | `item()?['url']` |
| `published_on` | `item()?['published_on']` |
| `status` | `pending` |

`company_name` はこの段階では入らない（詳細ページから取るのでステップ4で追加）。

## 検証

`lookback_days` の値によって件数が変わる。**2026-08-18 の実測値**が基準になる。

| `lookback_days` | 期待件数 |
|---|---|
| 14 | 3（すべてグローバル・ブレイン） |
| 90 | **22** |
| 365 | 97 |

`lookback_days = 90` で **22行**入れば正しい。内訳は
[prtimes_expected_90d.md](prtimes_expected_90d.md) の一覧と一致するはず。

日数が経つと件数は変わる。数が合わないときは `variables('cutoff')` の値を実行履歴で
確認する（`2026-05-21` のような日付になっているか）。

実行後、この22行は削除してよい。

---

# ステップ3: 重複排除を入れる

疎通テストで同じ記事が3行できた問題への対処。**この処理がないと実行ごとに行が増え続ける。**

「それぞれに適用する 2」の**前**に4つ追加する。

## 3-1.「表内に存在する行を一覧表示 2」

- テーブル: **`tbl_candidates`**

## 3-2.「アレイのフィルター処理 4」（空白行の除外）

- 開始: `body('表内に存在する行を一覧表示_2')?['value']`
- **詳細モード**:

```
@not(empty(item()?['release_key']))
```

疎通テストで、空白行は再利用されず残ることが確認できている。この除外は必須。

## 3-3.「選択 2」（既存キーの配列化）

- 開始: `body('アレイのフィルター処理_4')`
- **テキストモード**（キー／値ではなく単一値のモードに切り替える）:

```
item()?['release_key']
```

これで `["47342-611", "47342-610", ...]` という文字列配列になる。

## 3-4.「アレイのフィルター処理 5」（新規のみ）

- 開始: `variables('candidates')`
- **詳細モード**:

```
@not(contains(body('選択_2'), item()?['release_key']))
```

## 3-5.「それぞれに適用する 2」の開始を差し替える

`variables('candidates')` → `body('アレイのフィルター処理_5')`

## 検証

**2回連続で実行する。**

| 回 | 期待 |
|---|---|
| 1回目 | 22行追加される |
| 2回目 | **0行追加される**（すべて既存キーに一致するため） |

2回目で22行増えたら、`選択 2` がテキストモードになっていないか、`アレイのフィルター処理 5`
の開始が差し替わっていないかを確認する。

---

# ステップ4: 詳細ページから本文を取得する

「それぞれに適用する 2」の中、「表に行を追加」の**前**に追加する。

## 4-1.「HTTP 2」

| 項目 | 値 |
|---|---|
| 方法 | `GET` |
| URI | `item()?['url']` |
| ヘッダー | `User-Agent`: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36` |

## 4-2.「作成」（名前を `Compose_seg` に変更）

```
if(contains(string(body('HTTP_2')), '__NEXT_DATA__'), first(split(last(split(string(body('HTTP_2')), '__NEXT_DATA__"')), '</script>')), '{}')
```

`__NEXT_DATA__` が無いページでも落ちないよう `{}` に逃がしている。
設計 A-6 では「条件」で分岐させていたが、この形なら分岐が不要で Excel アクションを
2つに増やさずに済む。**設計より簡潔なのでこちらを採用する。**

## 4-3.「作成 2」（名前を `Compose_json` に変更）

```
if(equals(outputs('Compose_seg'), '{}'), '{}', substring(outputs('Compose_seg'), indexOf(outputs('Compose_seg'), '{'), sub(length(outputs('Compose_seg')), indexOf(outputs('Compose_seg'), '{'))))
```

`nonce` 属性が実行ごとに変わるため、タグの終わり `>` を固定文字列で狙えない。
最初の `{` の位置から末尾までを切り出す。

## 4-4.「作成 3」（名前を `Compose_pr` に変更）

```
json(outputs('Compose_json'))?['props']?['pageProps']?['pressRelease']
```

`{}` だった場合は null になる。`?[]` は null に対して安全なのでエラーにならない。

## 4-5.「作成 4」（名前を `Compose_body` に変更）

```
if(greater(length(coalesce(outputs('Compose_pr')?['text'], '')), 30000), substring(outputs('Compose_pr')?['text'], 0, 30000), coalesce(outputs('Compose_pr')?['text'], ''))
```

Excel の1セル上限は 32,767 文字。実測では 1,577〜3,401 文字なので通常は切り詰めが
発生しないが、長いリリースへの保険。

## 4-6.「表に行を追加」に5列を追加

| 列 | 値 |
|---|---|
| `company_name` | `coalesce(outputs('Compose_pr')?['companyName'], '')` |
| `release_type` | `coalesce(outputs('Compose_pr')?['releaseTypeName'], '')` |
| `reference_url` | `coalesce(outputs('Compose_pr')?['referenceUrl'], '')` |
| `body_text` | `outputs('Compose_body')` |
| `published_on` | `substring(coalesce(outputs('Compose_pr')?['releaseCompleDate'], item()?['published_on']), 0, 10)` |

`published_on` は詳細側を優先するよう**上書きする**。元コードも詳細から日付が取れたら
上書きする挙動（`src/main.py:250-251`）。

## 検証

`lookback_days = 90` で22行入り、かつ以下を満たすこと。

- `body_text` が22行すべて埋まっていること（**1行でも空なら `Compose_seg` の式を確認**）
- `body_text` が `<p>` で始まっていること（HTML断片のまま入る）
- `release_type` が `その他 ` または `経営情報` になっていること（実測分布は 19 / 3）
- `company_name` が `グローバル・ブレイン株式会社` などの正式名称になっていること
- `reference_url` が入っていること（空の記事もある）

`release_type` の **`その他 ` は末尾に半角スペースが入る。** `equals()` で比較する実装を
するなら `trim()` が必要。

## 実行時間の目安

22件×（記事ページ取得 約0.5秒＋Excel書き込み）で、同時実行1なら**1〜2分**程度。
一覧18本ぶんも加わる。タイムアウトはしないが、初回は待つことになる。

---

# ステップ5: run_log を記録する

フローの最後（すべてのループの外）に追加する。

## 5-1.「表に行を追加 2」

- テーブル: **`tbl_run_log`**

| 列 | 値 |
|---|---|
| `run_id` | `variables('run_id')` |
| `phase` | `collect` |
| `started_at` | （下記の注参照） |
| `finished_at` | `convertFromUtc(utcNow(),'Tokyo Standard Time','yyyy-MM-dd HH:mm:ss')` |
| `source_count` | `length(body('アレイのフィルター処理'))` |
| `fetched_total` | `variables('fetched_total')` |
| `matched_keyword` | （下記の注参照） |
| `within_window` | `length(variables('candidates'))` |
| `new_rows` | `length(body('アレイのフィルター処理_5'))` |
| `errors` | `variables('error_count')` |
| `notes` | `lookback_days=@{variables('lookback_days')}` |

**`started_at` について**: トリガー時刻を使う。`convertFromUtc(triggerOutputs()?['startTime'],'Tokyo Standard Time','yyyy-MM-dd HH:mm:ss')`。
取れない場合は、ステップ1で `started_at` 変数を初期化しておく方が確実。

**`matched_keyword` について**: ループ内でカウンタ変数を足す必要がある。省略しても
`within_window` があれば運用上は足りるので、まずは空欄で構わない。

## 検証

`tbl_run_log` に1行入り、`new_rows` が実際の追加件数と一致すること。

---

# ステップ6: エラー処理（任意・後回しでよい）

1社が落ちても残り17社を止めないための処理。**まず動くものを作ってから入れる。**

ループ内の `HTTP` / `JSON の解析` / フィルタ群 / `選択` / `変数の設定` を「**スコープ**」で
囲み、その後ろにもう1つ「スコープ」を置いて「設定 → 実行条件の構成」で
**失敗時／タイムアウト時**にチェックを入れる。中身は `error_count` のインクリメント。

18社実測では取得エラー0社だったので、当面は無くても動く。

---

# 本運用へ切り替えるときの変更点

テストが通ったら以下を変更する。

| 項目 | テスト | 本運用 |
|---|---|---|
| `lookback_days` | `90` | **`14`** |
| Recurrence | 任意 | 毎日 07:00 JST |
| HTTP の再試行ポリシー | 既定 | 指数間隔 / 回数4 / 間隔 PT1S |
| Copilotプロンプトのアクション | テスト用に残置 | **削除**（判定はフロー B へ） |

## 注意: shadow の扱い

18社はすべて `crawl_mode: shadow`。このフローは `candidates` に書くだけで、
掲載相当の出力は行わない。判定は別フロー（フロー B）で行い、`releases` 相当への
反映は live 化するときに承認アクションを挟んで実装する。

`CLAUDE.md` の「掲載可否・最終承認は人が担当する」に沿わせるため、**AI の判定を
そのまま掲載に流す実装にはしない。**

# 未確認事項

1. **Excel の日付型変換** — 疎通テストで `fetched_at` が日付値に変換された。
   `published_on` も同様の可能性がある。ステップ3の `選択 2` は `release_key`（文字列）を
   使うので影響しないが、将来 `published_on` を Excel から読み戻して比較する実装にすると壊れる
2. **22件×記事ページ取得の所要時間** — 概算1〜2分。実測していない
3. **`limit=90` での18社ループの所要時間** — 実測していない
4. **`tbl_candidates` の行数が増えたときの `表内に存在する行を一覧表示 2` の挙動** —
   既定で返る行数に上限がある。件数が増えたらページング設定（`$top` / ページ分割）が必要になる
