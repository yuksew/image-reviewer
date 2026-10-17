# 監査の指示書（P8-0: v6 の表と契約）

あなたは**実装の監査者**です。**P8-0（機能を足さない段。v6 の表・契約・移行・掃除）**を監査してください。

- 対象: `C:\work\image-reviwer` ／ 出力: **`docs/p8-0-audit-report.md` を新規に書くだけ** ／ 言語: 日本語 ／ **実行してよい**
- **形式は前の段と同じ**（`docs/p7-audit-brief-p7-0.md` の §0〜§4 をそのまま踏襲。**A/B/C/D/E/F/G/H** と「最も重大な 3 件」、各項目に場所と再現手順）。

## 0. 環境（**利用者のアプリが 8790 で動いています。止めないでください**）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"      # 必須
uv run --no-sync pytest -q                                  # ★ --no-sync。いま 296 件
node tools/gui_smoke.mjs                                    # 129 件
uv run --no-sync --with jsonschema python tools/check_contract_p8.py
```

- **実データ `.data/` は `mode=ro` のみ**。**すでに v6（24 表）**・263 枚・判断 3 件。
  壊す試験は複製（**`sqlite3` の `backup()` で WAL を畳む**）。**`.backup/` は消さない**。
  **v3 の控え**（`.backup/pre-p4-20261016-093705`）と **v5 の控え**（`.backup/pre-p8-0-20261017-213346`）で**古い版からの道**も試せる。
- 一時物は `.tmp-audit-redo/`。**ソースは編集しない**。**`git` のコミットもしない**。**ComfyUI は使わない段**。

## 1. P8-0 で入ったもの

- 設計: `docs/p8-design.md`（**837 行**。§0.3 / §2.1 / §2.3 / §3.3 / §6 / §8.1 / §8.4 / §9 の P8-0 の行）
- 実装の記録: [`p8-0-implementation.md`](p8-0-implementation.md)（**自分で決めた 5 点・申し送り**）
- `src/image_reviewer/db.py`: **`SCHEMA_VERSION = 6`**・`V6_DELETE_DDL`（**5 表・6 索引**）・`_migrate_v6`・`_top_up_v6`
- `src/image_reviewer/clock.py`（新規）: `now()` と `monotonic()` を 1 つの口（**点検 C6**）
- `schemas/backup-manifest.schema.json`（新規。**契約はこの 1 つだけ**）・`tools/check_contract_p8.py`
- `tests/test_db.py`（+6）・`tests/test_export.py`（+1）・`tests/test_clock.py`（新規 3）
- **実データの作業**: **P7 の残骸 12 ファイル・30,783 バイトを削除**（控え `.backup/pre-p8-0-20261017-213346/p7-leftovers/`）・
  **`illust-authoring` の置き場に `allow_stage3 = 1`**（**利用者の回答 Q8**。262/263 枚）

## 2. 確かめてほしいこと

1. **移行が何度でも安全か**: 新規・**v1**・**v3 の控え**・**v5 の控え**の 4 つの道が**同じ `sqlite_master`** になるか。**3 回呼び**。
   **263 枚・判断 3 件・`integrity` ok・FK 違反 0**。**`_top_up_v6` が早期 return 側からも呼ばれる**か（**列を `ALTER` で足すので冪等性が要る**）。
2. **表と制約が設計 §2.1 どおりか**（**1 対 1 で突き合わせる**）: **5 表**（`deletion_log` / `delete_request` / `duplicate_exclusion` / `phash_band` / `pending_delete_preview`）・
   **`CHECK`**（`stage` / `actor` / `band` / **`a_id < b_id`** / `allow_stage3`）・**部分索引**（`WHERE ... IS NOT NULL`）・
   **`ux_delete_token` が本当に効くか**（**同じ `client_token` は 2 行入らない・NULL は何行でも**）・
   **索引名が DB 全体で一意**という罠（**P6 の `ux_request_token` と衝突しないか**。**`IF NOT EXISTS` が黙って何もしない**ことに注意）。
3. **`asset.deleted_at` と `root.allow_stage3`**: 列として入っているか。**`deleted_at` に `CHECK` が無い**ことを設計が認めているか（**値の検査はサービス層**）。
   **実データの `allow_stage3` が 1 つの置き場だけ 1** になっているか（**もう 1 つは 0**）。
4. **`review.json` を変えていない**こと（**実データの複製に `deleted_at` を立ててから** `GET /api/export/review.json` を比べる）。
5. **契約**（`schemas/backup-manifest.schema.json`）: **本物の `jsonschema`** で `check_schema` を通り、見本が通り、**壊した物が落ちる**か。
   **`deletion-ledger` の契約が無い**（**契約は 1 つ**）ことも確かめる。
6. **`Clock`**: **テストから注入できる**か。**`now()` と `monotonic()` の両方**が 1 つの口か。**既定は実時計**か。
7. **「壊すと落ちる」テストが本当に落ちるか**（§8.1 の P8-0 の担当＋§8.4 の F の P8-0 の分）。
   **自分で壊して**確かめる（`CHECK` を外す・`ux_delete_token` を外す・`_top_up_v6` を早期 return から外す・`review.json` に `deleted_at` を足す）。
8. **実データの作業が報告どおりか**: 消した **12 ファイル**が**控えにある**か（**バイト数まで**）・`<data>` に `workflows/` と `recipes/` が**残っていない**か・
   **消しすぎていない**か（`sidecar` / `export` / `thumbs` は残っているか。**実データの画像 263 枚は無傷**か）。
9. **回帰**: `pytest` **296**（**複数回**）・`gui_smoke` **129**・`gui_layout`（**6 画面**）。**`GET` が書かない**ままか。**アプリ（8790）が v6 の DB で動いている**か。
10. **実装者が自分で決めた 5 点**と**申し送り**（`phash_band` の埋め方・`asset.deleted_at` の値の検査はサービス層・
    部分索引は `INDEXED BY` に `WHERE` も要る）を判定する。
11. **設計とのずれ**: 実装が `docs/p8-design.md` と違う所（**索引名は設計を直した**＝`ux_delete_token`）。**設計が黙っているのに実装が決めた**所。

## 3. 報告の形式

`docs/p8-0-audit-report.md` に A/B/C/D/E/F/G/H と**最も重大な 3 件**（**`docs/p7-0-audit-report.md` と同じ形**）。
各項目に**場所**と**実行したコマンド / 再現手順**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p8-0-audit-done --body (Get-Content -Raw $env:TEMP\p8-0-audit.txt) --json
```

- subject は `p8-0-audit-start` / `-mid` / `-done`。待たずに続けて `G` に推奨つきで書いてください。
