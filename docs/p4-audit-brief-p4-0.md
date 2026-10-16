# 監査の指示書（P4-0: 表と契約）

あなたは**実装の監査者**です。**P4-0（機能を足さない段。v5 の表と契約だけ）**を監査してください。

- 対象: `C:\work\image-reviwer`
- あなたの出力: **`docs/p4-0-audit-report.md` を新規に書くだけ**
- 言語: 日本語。**今回は実行してよい**（実行したコマンドと結果を報告に書く）

## 0. 環境

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"   # 必須
uv run pytest -q                                        # いま 231 件が緑
node tools/gui_smoke.mjs                                # すべて ok
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\data-p40"   # v5 済みのコピー（実装者が残した）
uv run image-reviewer serve --port 8791
```

- **実データ `.data/` は `mode=ro` のみ。** 実装者が気づいた点: **`.data/db.sqlite3-wal` が 0.3 MB あり、`db.sqlite3` だけコピーすると判断 3 件が抜ける**。コピーを作るときは **`sqlite3` の `backup()` API** を使う（実装者の手順）。
- 一時物は `.tmp-audit-redo/`。**ソースは編集しない。**

## 1. P4-0 で入ったもの（設計 §0.1 / §9 の P4-0 の行）

| # | 入ったもの | 場所 |
| --- | --- | --- |
| 1 | **v5 の移行**: `tag`（`known` 込み）/ `asset_tag` / `tag_gloss` / `job` / `job_item` ＋ 索引 | `src/image_reviewer/db.py`（`SCHEMA_VERSION = 5`、`V5_TAG_DDL`、`_migrate_v5`） |
| 2 | 契約: `$defs.Tag` に **`known` / `gloss` / `gloss_edited`** | `schemas/review-export.schema.json` |
| 3 | `review.json` の **`tags[]` を実際に埋める**（`include_tags` が真のときだけ。`asset_tag` → `tag` → `tag_gloss`） | `src/image_reviewer/export.py`（`_tag_docs`） |
| 4 | テスト 7 件（v1→v5・v4→v5・3 回呼び・一意性と括弧の保持・3 出所・`edited`・`job` の CHECK と CASCADE・契約の 2 件） | `tests/test_db.py`、`tests/test_export.py` |

## 2. 確かめてほしいこと

1. **移行が何度でも安全か。** 新規（v0 → v5）・**v1 から 1 回で v5**・**v3 の実データから v5**・**v4（P6）から v5** が同じ結果になるか。
   `migrate()` を 3 回。`ALTER TABLE` を二度当てないか。**v3 のコピーで 263 枚・判断 3 件・`integrity()`** が無傷か
   （**WAL の扱い**に注意。`backup()` を使う）。
2. **表の制約が設計（§2.1）どおりか。** `tag.name` の一意性（**括弧を含む語がそのまま入る**か）／
   `asset_tag` の主キー `(asset_id, tag_id, source)` が**同じ語の複数出所**を許すか／`tag_gloss.edited` の既定／
   `job.state` の `CHECK`／`job_item` の形／`ON DELETE CASCADE` が効くか／`known` の既定。
   **`INSERT` を 2 回して落ちる**ことを実行で確かめ、**P4-1 が `INSERT OR IGNORE` を使うべき**ことを記録する。
3. **契約が本物の `jsonschema` で通るか。** `include_tags=true` の `scope=all` / `group:` / `asset:` の 3 文書。
   **足した 3 欄（`known` / `gloss` / `gloss_edited`）が実際に出ているか**（P6-0 の監査 B1 の型の穴）。
   既定（`include_tags` なし）では `tags` の**鍵ごと出ない**か。`abi` を上げていないか。
   **古い読み手（`known` / `gloss` を知らない側）が壊れないか**。
4. **`tags[]` の決定性**: 2 回出して `generated_at` を除いて一致するか。並びが固定か。
5. **実装者が自分で決めた点**（`p4-0` の報告にある 3 点: `gloss_edited` は語釈が無いとき `null`／`job.kind` に `CHECK` を付けない／
   テストの足場 `_add_tag()`）が妥当か。
6. **申し送り 5 件**（正規化後の形を入れるのは P4-1 の責任／`INSERT OR IGNORE`／`job_item.state` の語彙が未定／
   `_tag_docs` は 1 枚 1 クエリ／実データの WAL）を、**P4-1 に持ち越してよいか**を判定する。
   **1 枚 1 クエリ**は 1 万枚で `include_tags=true` を出すときに問題になるか（見積りを出す）。
7. **テストが本当に落ちるか**（設計 §8.1 の 17・18・19 が P4-0 の担当）。**壊すと落ちる**形か。落ちないならその旨を書く。
8. **回帰**: `pytest` 231・`gui_smoke`・`gui_layout`（比較・要求・まとまり・注記）が緑か。
   **`GET` が書かない**ままか。P5 / P6 の口と契約が変わっていないか。
9. **設計とのずれ**: 実装が `docs/p4-design.md` §2.1 / §6.1 と違う所。**設計が黙っているのに実装が決めた**所。

## 3. 報告の形式

`docs/p4-0-audit-report.md` に、これまでと同じ形（A 直っていない / B 重大 / C 中程度 / D 軽微 /
E 設計とのずれ / F テストが守っていないもの / G 依頼者への質問（推奨つき）/ H 確かめられなかったこと）。
各項目に**場所**と**実行したコマンド / 再現手順**。最後に**最も重大な 3 件**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p4-0-audit-done `
  --body (Get-Content -Raw $env:TEMP\p4-0-audit.txt) --json
```

- subject は `p4-0-audit-start` / `p4-0-audit-mid` / `p4-0-audit-done`。**依頼者は起きている**が、待たずに続けて `G` に書いてください。
