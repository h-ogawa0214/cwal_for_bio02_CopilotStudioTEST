# フロー A 疎通テスト手順（1社・5アクション）

作成日: 2026-08-18
対象: Power Automate クラウドフロー（新規）
所要: 15〜30分

## 目的

3点だけを検証する。**これ以外は意図的に作らない。**

1. **HTTP アクションで prtimes.jp に出られるか**（DLP ポリシーとライセンスの確認）
2. **JSON の解析がスキーマ通りに通るか**
3. **Excel Online コネクタが `tbl_candidates` に書き込めるか**

意図的に入れないもの: ループ、キーワードフィルタ、日付フィルタ、重複排除、詳細ページ取得、
判定。これらは疎通が確認できてから足す。1つでも混ぜると、失敗したときに
どこが原因か切り分けられない。

## テスト対象

**グローバル・ブレイン（company_id = 47342）** を使う。18社の中で最もリリース件数が多く
（total 584）、必ず結果が返るため。

Angel Bridge（118632）は使わない。全期間で5件しかなく、キーワードにも一致しないため
疎通確認に向かない。

## 事前準備

書き込み先ファイル:

```
OneDrive - 株式会社日経BP/#医療メディア事業推進部/CoPilot Studio/by_yamaji_build/pr-disclosure-curator_CopilotStudio_TEST/data/pa_prtimes_test.xlsx
```

- ブラウザの OneDrive でこのファイルが見えることを先に確認する（同期が終わっていないと
  コネクタのファイルピッカーに出てこない）
- テーブル名は `tbl_candidates`

---

## アクション構成

### 1. トリガー

「**手動でフローをトリガーします**」（Manually trigger a flow）

入力パラメータは無し。

### 2. HTTP

| 項目 | 値 |
|---|---|
| 方法 | `GET` |
| URI | `https://prtimes.jp/api/company_content.php/companies/47342/press_releases?limit=10` |

ヘッダー:

| キー | 値 |
|---|---|
| `User-Agent` | `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36` |
| `Accept-Language` | `ja,en-US;q=0.9,en;q=0.8` |

`limit=10` にしている理由は下の「limit の挙動」を参照。

### 3. JSON の解析

- コンテンツ: `body('HTTP')`
- スキーマ:

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

### 4. 作成（Compose）

先頭1件だけを取り出す。名前は `作成` のまま（下の式が参照する）。

```
first(body('JSON_の解析')?['data']?['data'])
```

### 5. Excel Online (Business)「表に行を追加」

- 場所 / ドキュメントライブラリ: OneDrive
- ファイル: `data/pa_prtimes_test.xlsx`（ピッカーで選択）
- テーブル: `tbl_candidates`

| 列 | 入れる式・値 |
|---|---|
| `release_key` | `concat(string(outputs('作成')?['company']?['id']), '-', string(outputs('作成')?['id']))` |
| `run_id` | `smoke-test` |
| `fetched_at` | `convertFromUtc(utcNow(),'Tokyo Standard Time','yyyy-MM-dd HH:mm:ss')` |
| `source_name` | `グローバル・ブレイン` |
| `company_id` | `string(outputs('作成')?['company']?['id'])` |
| `release_id` | `string(outputs('作成')?['id'])` |
| `company_name` | `outputs('作成')?['company']?['name']` |
| `title` | `outputs('作成')?['title']` |
| `url` | `concat('https://prtimes.jp', outputs('作成')?['url'])` |
| `published_on` | `substring(outputs('作成')?['release_comple_date'], 0, 10)` |
| `status` | `smoke` |

残りの列（`release_type` / `reference_url` / `body_text` / `decision` / `edited_title` /
`lead` / `reason` / `judged_at`）は**空のまま**にする。詳細ページ取得と判定は
このテストの対象外。

`run_id` を `smoke-test`、`status` を `smoke` にしているのは、あとで削除する行を
識別できるようにするため。

---

## 期待結果

2026-08-18 時点の実測値。**グローバル・ブレインが新しいリリースを出すと先頭が変わる**ので、
値そのものではなく「1行が正しい形で入ること」を確認する。

| 列 | 期待値 |
|---|---|
| `release_key` | `47342-611` |
| `company_id` | `47342` |
| `release_id` | `611` |
| `company_name` | `グローバル・ブレイン株式会社` |
| `title` | `ショートドラマ・ショートアニメの制作および配信プラットフォームを提供するFLASH株式会社へ追加出資` |
| `url` | `https://prtimes.jp/main/html/rd/p/000000611.000047342.html` |
| `published_on` | `2026-08-05` |

確認ポイント:

- `published_on` が `2026-08-05` であること（`2026-08-04` になっていたら日付変換が
  UTC に寄っている。`substring` ではなく `formatDateTime` を使ってしまっていないか確認）
- `url` がドメイン付きの絶対 URL になっていること（API は相対パスを返す）
- `release_key` が `47342-611` の形であること（ハイフン区切り）
- `company_name` が文字化けしていないこと

## 実行結果（2026-08-19 実施・完了）

**4項目すべてクリア。Power Automate だけで完結する構成が成立することを実証した。**

| # | 検証項目 | 結果 |
|---|---|---|
| 1 | HTTP で prtimes.jp に出られるか（DLP） | ✅ 通過 |
| 2 | JSON の解析がスキーマ通り通るか | ✅ 通過 |
| 3 | Excel `tbl_candidates` に書き込めるか | ✅ 通過 |
| 4 | 日付が JST で正しく入るか | ✅ `published_on = 2026-08-05` |

実測された行（3回実行ぶん）:

```
release_key  47342-611
company_id   47342
release_id   611
company_name グローバル・ブレイン株式会社
published_on 2026-08-05
```

### 判明した5点

**① `#` を含むパスは問題なかった**

`#医療メディア事業推進部` を含むパスでも、Excel Online コネクタのファイルピッカーで
解決できた。事前に懸念していたが対処不要。

**② openpyxl で作ったテーブル定義は Graph API 側から読める**

`tbl_candidates` がテーブル選択のドロップダウンに正しく出た。ブックの作り方はこのままでよい。

**③ 空白行は再利用されず、下に追記される**

3回実行して3行が追記され、先頭の空白行は残ったまま。
**本番フローの空白行フィルタ（設計 A-5 ②）は必須**と確定した。

**④ 重複排除がないと同じ記事が何度でも入る**

3回実行で `47342-611` が3行できた。**既存キー照合（設計 A-5）は必須**と確定した。

**⑤ `fetched_at` が Excel 側で日付型に変換される**

`2026-08-19 11:54:00` として書き込んだ値が `2026/8/19 11:54` の日付値になり、右寄せ表示に
なった。読み戻すとシリアル値または別書式の文字列になる可能性がある。

`published_on` も同じ変換を受けている可能性がある。**日付フィルタで `published_on` を
文字列比較に使う場合は注意が必要**（設計 A-4 ⑥は API のレスポンスに対して比較しているので
影響しないが、Excel から読み戻して比較する実装にすると壊れる）。

### 日付変換の設計が裏付けられた

このテスト対象の記事は予約投稿で、2つのタイムスタンプが1日ずれていた。

| フィールド | 値 |
|---|---|
| `release_comple_date` | `2026-08-05T11:00:00+09:00` |
| `updated_at.time_iso_8601` | `2026-08-04T09:55:54+09:00` |

**更新日時のほうが公開日時より前**である。`updated_at` は「最終編集時刻」であり、
公開日より前になり得る。`release_comple_date` を第一優先にした設計（A-4 ⑥⑧）が
正しかったことになる。フォールバック側を参照していれば1日ずれていた。

また `formatDateTime()` を使っていれば UTC 正規化で `2026-08-04` になっていた。
`substring(x, 0, 10)` を選んだ判断も実測で裏付けられた。

### つまずいた点（次回のための記録）

**式は必ず `fx` エディタから入れる。** テキスト欄に直接打つとリテラル文字列として扱われ、
`作成` の出力が `first(body('JSON_の解析')?['data']?['data'])` という文字列そのものになった。

**貼り付けると引用符が化ける。** ドキュメントからコピーすると `'`（ASCII）が
`'`（カーリークォート）に変換され、式として解釈されない。手入力するか、入力補完を使う。

**ヘッダーは1行1ヘッダー。** 左の箱にヘッダー名、右の箱に値。値だけを2つ並べると
「適切な JSON を入力してください」になる。

### 後片付け

`run_id = smoke-test` の3行と、先頭の空白行を Excel 上で削除する。

---

## 失敗パターンと切り分け

| 症状 | 意味 | 対処 |
|---|---|---|
| HTTP アクションにプレミアムのバッジが付いて追加できない | ライセンス不足 | Power Automate Premium が必要 |
| 実行時に `FlowActionBlockedByPolicy` / 「DLP ポリシーによりブロック」 | **DLP でブロック。この構成の可否を決める最重要点** | 管理者に HTTP コネクタの許可を依頼。許可されない場合は Power Automate 案そのものを見直す |
| HTTP が 403 / 503 を返す | PR TIMES 側で弾かれた | `User-Agent` ヘッダが入っているか確認 |
| HTTP が 200 だが「JSON の解析」で失敗 | 本文が文字列として渡っていない | コンテンツを `string(body('HTTP'))` にする |
| スキーマ検証エラー（`release_comple_date` 等） | null が返っている | スキーマの `["string","null"]` が消えていないか確認 |
| Excel で「テーブルが見つかりません」 | テーブル名の指定ミス | `tbl_candidates`。ピッカーからファイルを選び直す |
| Excel で「ファイルが見つかりません」 | OneDrive の同期未完了 | ブラウザの OneDrive でファイルが見えるか確認 |
| 書き込めたが列がずれる／空になる | 列名の不一致 | ヘッダー名と式の参照名を突き合わせる |

## 疎通が通ったら次に足す順序

1 つずつ足して、都度実行する。

1. `sources` シートの読み込み＋「それぞれに適用する」（**同時実行を 1 に設定**）
2. キーワードフィルタ
3. 日付フィルタ（`cutoff` 変数）
4. 既存キー照合による重複排除
5. 詳細ページ取得（`__NEXT_DATA__` からの本文抽出）
6. `run_log` 追記

詳細は [power_automate_prtimes.md](power_automate_prtimes.md) を参照。

---

## limit の挙動（実測で判明）

**`limit` に 10 未満を指定しても 10 に切り上げられる。**

`limit=5` で照会したところ、レスポンスは10件返り、`condition.limit` も `10` に
書き換わっていた。

```
GET .../companies/47342/press_releases?limit=5
→ {"data":{"total":584,"condition":{"skip":0,"limit":10,...},"data":[ ...10件... ]}}
```

`limit=90` は honored される（実測済み）。疎通テストで「1件だけ取る」ことは
API 側ではできないため、**取得は10件で、フロー側の `first()` で1件に絞る**構成にしている。
