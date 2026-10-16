# 監査の指示書（P7-0: 表と契約）

あなたは**実装の監査者**です。**P7-0（機能を足さない段。v6 の表と契約だけ）**を監査してください。

- 対象: `C:\work\image-reviwer`
- あなたの出力: **`docs/p7-0-audit-report.md` を新規に書くだけ**
- 言語: 日本語 ／ **実行してよい**（実行したコマンドと結果を報告に書く）

## 0. 環境（**利用者のアプリが 8790 で動いています**）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"      # 必須
uv run --no-sync pytest -q                                  # ★ --no-sync。いま 309 件
node tools/gui_smoke.mjs                                    # 129 件
uv run --no-sync --with jsonschema python tools/check_contract_p7.py
```

- **実データ `.data/` は `mode=ro` のみ**（**まだ v5**・263 枚・判断 3 件）。壊す試験は複製で
  （**`sqlite3` の `backup()` で WAL を畳む**）。**控え `.backup/pre-p4-20261016-093705` は v3 の控え**（v3 → v6 の道も試せる）。
- 一時物は `.tmp-audit-redo/`。**`.backup/` は消さない**。**ソースは編集しない**。**`git` のコミットもしない**。
- ComfyUI（127.0.0.1:8188）は**読み取りだけ**（`GET`）。**画像は生成しない**。

## 1. P7-0 で入ったもの

| # | 入ったもの | 場所 |
| --- | --- | --- |
| 1 | **v6 の移行**: `recipe_record` / `recipe_export_attempt`（**束の表**）/ `recipe_export` / `recipe_export_result` / `preset` / `watcher_state` の **6 表・10 索引** | `src/image_reviewer/db.py`（`SCHEMA_VERSION = 6`・`V6_RECIPE_DDL`・`_migrate_v6`） |
| 2 | **契約**: `schemas/recipe-manifest.schema.json`（**新規**。設計 §6.1。**点検 B-5 を反映**して `notes` は型つき・`mode` / `marker_skipped` / `source` を足せる） | `schemas/` |
| 3 | **`review.json` は変えない**（`recipes` / `presets` を足さない。**足していないことをテストで固定**） | `tests/test_manifest.py` |
| 4 | テスト: `tests/test_db.py` に v6 の 7 件（v1→v6・v5→v6・3 回呼び・`CHECK`・式の索引・`ON DELETE`）／`tests/test_manifest.py`（17 件）／`tools/check_contract_p7.py` | — |
| 5 | 実装の記録: **`docs/p7-0-implementation.md`**（自分で決めた 4 点・申し送り・設計の穴 5 件） | — |

- 実装者は**壊すと落ちる 12 通り**（`.tmp-audit-redo/mutation_run.py`）を回し、**12/12 で狙ったテストが落ちる**ことを確認しています
  （1 回目は 1 件落ちず・2 件は壊せていなかったのを直した、と申告）。

## 2. 確かめてほしいこと

1. **移行が何度でも安全か**。新規（v0 → v6）・**v1 から 1 回で v6**・**v3 の控えから v6**・**v5 の複製から v6** が同じ結果か。
   `migrate()` を 3 回。**263 枚・判断 3 件・`integrity()`** が無傷か。**v6 は新表だけ**なので `_top_up_v6` が無い判断は妥当か。
2. **表の制約が設計（§2.1）どおりか**（**1 対 1 で突き合わせる**）:
   - **`marker` は NULL 可**＋`CHECK ((marker IS NULL) <> (marker_skip_reason IS NULL))`（**印なし＋理由なしを弾く**）。
   - **`ux_export_attempt_seed` は `ON recipe_export(attempt_id, COALESCE(seed, ''))`** の**式の索引**で、
     **`seed` が NULL でも同じ `attempt_id` に 2 行入らない**（点検 A-2c の穴。**実行で確かめる**）。
   - **`recipe_export_attempt.client_token` の部分 UNIQUE**。
   - **`ON DELETE`**（`preset` / `result` は `SET NULL`・`recipe_record` は `RESTRICT`・束→`recipe_export` は `CASCADE`）が**実際に効くか**。
   - **索引が引かれるか**（`EXPLAIN QUERY PLAN`）。
3. **契約**: `schemas/recipe-manifest.schema.json` が**本物の `jsonschema`** で `check_schema` を通り、**実例が通り**、
   **壊した物が落ちる**か（`tools/check_contract_p7.py` を**自分で回す**）。**`notes` の型**・**`mode` の enum**・
   **`export_hashes` の `^sha256:`**・**`seeds` が文字列**（設計 B-5/§6.1）になっているか。
   **`review.json` に `recipes` / `presets` が入っていない**ことを**実行で**確かめる（`GET /api/export/review.json` を複製のサーバで）。
4. **「壊すと落ちる」テストが本当に落ちるか**（§8.1 の 24〜26・29・34〜36・41〜43）。**実装者の 12 通りを自分で回す**
   （`.tmp-audit-redo/mutation_run.py`。**M7 の直しが効いているか**、**M5/M8 が本当に壊せているか**を見る）。
5. **実装者が自分で決めた 4 点**（`attempt_id` の `^[a-z0-9]{8,}$` を契約に入れた・`notes.reasons` を enum にしない・
   `marker_skip_reason` の字は `'前提1'`・`_top_up_v6` を作らない）が妥当か。
6. **申し送り 5 件**（`recipe_export_result.export_id` に `ON DELETE` が無い・`export_hashes` の seed 無しの鍵・
   `preset` に `client_token` が無い・`graph_kind` 等に `CHECK` が無い・**§0.1/§9 の「5 表」と §2.1 の「6 表」の不一致**）を、
   **P7-1 / P7-2 に持ち越してよいか**を判定する（とくに **§2.1 を正とした**判断）。
7. **回帰**: `pytest` **309**・`gui_smoke` **129**・`gui_layout`（**6 画面**。`--screen tags` は実データに語が無いと NG になるので、
   複製に語を入れてから回す）が緑か。**`GET` が書かない**ままか。**実データ `.data` の mtime が変わっていない**か。
8. **設計とのずれ**: 実装が `docs/p7-design.md` §2.1 / §6.1 と違う所。**設計が黙っているのに実装が決めた**所。

## 3. 報告の形式

`docs/p7-0-audit-report.md` に、これまでと同じ形（A 直っていない / B 重大 / C 中程度 / D 軽微 /
E 設計とのずれ / F テストが守っていないもの / G 依頼者への質問（推奨つき）/ H 確かめられなかったこと）。
各項目に**場所**と**実行したコマンド / 再現手順**。最後に**最も重大な 3 件**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p7-0-audit-done `
  --body (Get-Content -Raw $env:TEMP\p7-0-audit.txt) --json
```

- subject は `p7-0-audit-start` / `-mid` / `-done`。**依頼者は起きている**が、待たずに続けて `G` に書いてください。
