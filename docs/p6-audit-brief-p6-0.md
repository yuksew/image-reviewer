# 監査の指示書（P6-0: 表と契約）

あなたは**実装の監査者**です。**P6 の設計**（[`p6-design.md`](p6-design.md)）のうち、
**P6-0（機能を足さない段。表と契約だけ）**の実装を監査してください。

- 対象: `C:\work\image-reviwer`
- あなたの出力: **`docs/p6-0-audit-report.md` を新規に書くだけ**
- 言語: 日本語

## 0. 環境（実行してよい）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"   # 必須
uv run pytest -q                                        # いま 182 件が緑
node tools/gui_smoke.mjs                                # 51 ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8   # 3 窓 × 3 状態
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\data-p52"
uv run image-reviewer serve --port 8791
```

- 実データ `.data/` は **`mode=ro` のみ**。壊す試験はコピーで（`data-p52` は既に v4 に上がっています。
  **v3 のままの DB を作りたいときは `data-p5` などから複製してください**）。
- **ソースは編集しない**。一時物は `.tmp-audit-redo/`（`p6/` の下を使ってよい）。

## 1. P6-0 で入ったもの（設計 §0.1 / §9 の P6-0 の行）

| # | 入ったもの | 場所 |
| --- | --- | --- |
| 1 | **v4 の移行**: `review_request` / `annotation` の表、`review_group.superseded_by` の列 | `src/image_reviewer/db.py`（`SCHEMA_VERSION = 4`、`V4_REQUEST_DDL`、`_migrate_v4`） |
| 2 | 契約の追記: `ReviewRequest` に `target_key` / `actor`、`Group` に `superseded_by`、`ReviewRequestResponse.annotations` の説明（後から増える） | `schemas/review-export.schema.json` |
| 3 | **新しい契約**: `annotation-export`（座標 JSON と切り出しの一覧） | `schemas/annotation-export.schema.json` |
| 4 | `review.json` に **`requests: []`**（P6-0 では空。P6-1 で埋める）、**差し替えで閉じたまとまりを既定で除外**（`include_superseded` で出す。名指しの `scope=group:` では返す） | `src/image_reviewer/export.py`、`src/image_reviewer/api/export.py` |
| 5 | テスト 6 件（v4 の移行・注記の座標の 2 形・`open` の部分索引・`requests: []`・閉じたまとまりの既定除外・2 つの契約の `Annotation` の形の突き合わせ） | `tests/test_db.py`、`tests/test_export.py` |

## 2. 確かめてほしいこと

1. **移行が何度でも安全か。** 新規作成（v0 → v4）と **v1 から 1 回で v4**、**v3 から v4** が同じ結果になるか。
   `migrate()` を 3 回呼んで壊れないか。`ALTER TABLE` を二度当てないか。
   **v3 の実データのコピー**で `user_version` が 4 になり、既存の 12 のまとまり・263 枚・判断が無傷か。
2. **表の制約が設計どおりか。**
   - `annotation`: 座標が「全部 NULL」か「全部あり」の 2 形だけ（片方だけ NULL が落ちる）。
     `shape` の enum、`actor` の enum。
   - `review_request`: `state` の enum、`ux_request_target_open`（**`open` のときだけ**効く部分 UNIQUE）、
     `ux_request_token`、`ix_request_state` / `ix_request_group`。**`target_key` が NULL なら何本でも入る**か。
   - **`EXPLAIN QUERY PLAN`** で `ix_request_state` が使われるか（設計 §8.1-22）。
3. **契約が本物の `jsonschema` で通るか。** `review-export` で `scope=all` / `scope=group:` / `scope=asset:` の
   3 文書、`annotation-export` は `check_schema` と（作れるなら）実例 1 つ。
   **`additionalProperties: false` の契約に `target_key` / `actor` / `superseded_by` を足したことで、
   既存の読み手（P5 の 3 文書）が壊れていないか**（実行で確かめる）。
4. **`requests: []` と閉じたまとまりの除外が設計どおりか。**
   - `scope=all` / `group:` / `asset:` のどれでも `requests` が入るか（P6-0 は空）。
   - `superseded_by` を入れたまとまりが `scope=all` の `groups[]` から外れ、`include_superseded=1` で出るか。
     **`scope=group:<id>` の名指しでは返る**か（設計 §6.1 の但し書き）。
   - `?include_superseded=1` が **GET でも POST でも**効くか（GET は書かないまま）。
5. **壊すと落ちるか**（設計 §8.1 の 20〜23 が P6-0 の担当）:
   - 20（契約の検証）・21（決定性）・22（索引）・23（移行）が**本当に落ちる**形か。**テストを読んで判定**し、
     落ちないならその旨を書く（テストは書き換えない）。
   - **`requests: []` の存在を消したら落ちるか**、**閉じたまとまりの除外を外したら落ちるか**。
6. **回帰。** P6-0 は「機能を足さない」段。**`pytest` 182 件・`gui_smoke` 51・`gui_layout` が緑のまま**か。
   `GET /api/export/review.json` が**書かない**ままか（P5 の監査 C8/G2 が戻っていないか）。
   `scope=group:` のファイル書き出し（`write_group`）が変わっていないか。
7. **設計とのずれ。** 実装が設計（§2.1 の DDL・§6.1・§6.2）と違う所は無いか。**設計が黙っているのに実装が決めた**所は無いか。
8. **「実装者が気づいていない前提」**（P5 の監査で一番役に立った観点）。とくに:
   - 部分 UNIQUE 索引と `UPDATE` → `INSERT` の順（設計 §0.3 / 点検 C4）が、**P6-1 の実装で踏まれる形**で書かれているか
     （P6-0 では表だけなので、**順序を守らないと落ちること**を実行で確かめて記録してほしい）。
   - `annotation` の `CHECK` が **SQLite の式として正しいか**（`(shape IS NULL) = (x IS NULL)` の連鎖）。
     思わぬ行（例: `shape='rect'` で座標が NULL）を通していないか。
   - `review_group.superseded_by` が **`review.json` の `Group` にしか出ておらず、`GET /api/groups` は未対応**
     ではないか（P6-1 の宿題として記録してほしい）。

## 3. 報告の形式

`docs/p6-0-audit-report.md` に:

```markdown
# P6-0（表と契約）の監査報告

- 監査した版 / **実行できたかどうか（実行したコマンドと結果）**
- 総合判定: 使える / 条件つきで使える / 作り直す

## A. 直っていない（必ず直す）
## B. 直っているが別の問題が残る（重大）
## C. 中程度
## D. 軽微
## E. 設計とのずれ
## F. テストが守っていないもの
## G. 依頼者への質問（朝に読むので、推奨つきで）
## H. 確かめられなかったこと
```

- 各項目に**必ず「場所」**と**実行したコマンド / 再現手順**。実行していないことは「実行していない」と明記。
- 問題が無いと確認した観点は 1 行で「確かめた結果、問題なし」。最後に**最も重大な 3 件**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p6-0-audit-done `
  --body (Get-Content -Raw $env:TEMP\p6-0-audit.txt) --json
```

- subject は `p6-0-audit-mid` / `p6-0-audit-done`。**依頼者は寝ている**ので、質問は `G` に書いて待たずに続けてください。
