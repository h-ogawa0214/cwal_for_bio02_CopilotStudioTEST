# フロー A 疎通テスト手順（1社・5アクション）

作成日: 2026-08-14
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

2026-08-14 時点の実測値。**グローバル・ブレインが新しいリリースを出すと先頭が変わる**ので、
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

## 実行後の後片付け

`candidates` シートには**空白のデータ行が1行**入っている（Excel がテーブルに最低1行の
データ行を要求するため）。書き込み後は次のいずれかになる。

- 空白行の下に新しい行が追加される（通常こちら）
- 空白行がそのまま埋まる

**どちらになったかを確認して記録する。** 本番フローの「既存キー照合」で空白行を除外する
処理（設計 A-5 ②）が必要かどうかの判断材料になる。

疎通が確認できたら、`run_id = smoke-test` の行と空白行を Excel 上で削除する。

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
