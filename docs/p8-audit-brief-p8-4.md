# 監査の指示書（P8-4: バックアップと復元）

あなたは**実装の監査者**です。**P8-4** を監査してください。**利用者が「バックアップを取っていない（不安）」と言っている段**です。

- 対象: `C:\work\image-reviwer` ／ 出力: **`docs/p8-4-audit-report.md` を新規に書くだけ** ／ 言語: 日本語 ／ **実行してよい**
- **形式は前の段と同じ**（`docs/p8-audit-brief-p8-3.md` の §0〜§4 を踏襲。**A/B/C/D/E/F/G/H** と「最も重大な 3 件」）。

## 0. 環境（**利用者のアプリが 8790 で動いています。止めないでください**）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"      # 必須
uv run --no-sync pytest -q                                  # ★ --no-sync。いま 453 件
node tools/gui_smoke.mjs                                    # 207 件
uv run --no-sync python tools/probe_p8.py --all              # すべて OK のはず
uv run --no-sync --with jsonschema python tools/check_contract_p8.py
```

- **実データ `.data/` は `mode=ro` のみ**（**v6・23 表・263 枚・判断 3 件・削除 0 件・台帳 0 行**）。**画像を 1 枚も動かさない**。
  壊す試験は**必ず複製で**（DB と画像の両方）。**複製にサーバを立てるときは必ず `IMAGE_REVIEWER_DATA=<複製>`**。
  **`.backup/` は消さない**。**バックアップの置き場は実データの外**（`%USERPROFILE%` の下）にし、**実データの隣に作らない**。
- 一時物は `.tmp-audit-redo/`。**ソースは編集しない**。**`git` のコミットもしない**。**ComfyUI は使わない段**。
- **P8-3 の修正が並行で走っています**（`apps/gui/` と `api/deletions.py`）。**あなたの対象は P8-4 のファイル**（`backup.py`・`api/backup.py`・`api/roots.py`・`cli.py`・`db.py`・`store.py`）。

## 1. P8-4 で入ったもの

- 設計: `docs/p8-design.md`（**§0.12 / §0.1 / §0.3 / §0.6 / §0.13 / §0.14 の Q3・Q6 / §2.1 / §3.3 / §6 / §7 / §8.1 / §8.4 の F7 / §9 の P8-4 の行**）
- 実装の記録: [`p8-4-implementation.md`](p8-4-implementation.md)（**自分で決めた点 9・設計の穴 7・申告 1**）
- **新規**: `backup.py`（1276 行）・`api/backup.py`（130）・`api/roots.py`（50）・`tests/test_backup.py`（1366 行・**45 件**）
- **変更**: `app.py`・`cli.py`（`backup` / `restore` / `rebuild-metadata`）・`db.py`・`store.py`・`review.py`・`compare.py`・`deletions.py`・`api/__init__.py`・`tests/conftest.py`・`tools/probe_p8.py`・`tools/check_contract_p8.py`

## 2. 確かめてほしいこと（**データが失われないかが最優先**）

1. **`backup()` が WAL を畳むか**（**写しに 263 枚と判断 3 件が入る**。**素の `copy2` では判断 0 件**になることを**自分で**確かめる）。
   **`manifest` が契約（`schemas/backup-manifest.schema.json`）を通る**か（**本物の `jsonschema`**）。
2. **日次**: **起動直後＋30 秒周期で「今日まだなら取る」**か。**同じ日に 2 回取らない**か。**「いま取る」は必ず新しく取る**か。
   **失敗が `last_error` に残り `GET /api/backup` に出る**か。
3. **増分**（`os.link` の共有と写しの数）・**保持 7 世代**（**人が置いた物を消さない**か）・**置き場**（既定 `%USERPROFILE%\image-reviewer-backups\`・**`<data>` の中は 422**）。
4. **壊れた DB の 3 つの形**を**自分で作って**確かめる（**先頭 4KB**・**2 ページ目**・**300 ページ目**）。
   **`quick_check` が例外を投げたら「壊れている」に数える**か。**読み取り専用で起動**して**読みは生かし書き込みは 503** か。
   **健康の口以外が 503**（先頭 4KB）か。**版が新しい DB を拒否しない**か。**版を上げる前の控えが取れなければ上げない**か。
5. **`restore`**: **元の DB を退避**してから・**戻す前に `quick_check`**・**戻した後に `integrity_check`**（**通らなければ元に戻す**）。
   **壊れた写しは 409 で断る**（`--force` でも `integrity` は外さない）。
   **複製の `<data>` を丸ごと消して restore** → **263 枚・判断 3 件・sidecar** が戻るか。
6. **`rebuild-metadata`**: **sidecar と PNG の `prompt` から**来歴が戻るか。**DB にある値は上書きしない**か。
7. **口**: `POST /api/backup`（**人だけ**）・`GET /api/backup`・`GET /api/health/db`・`GET/PATCH /api/settings`・`GET /api/roots`・
   **`POST /api/roots/{id}/allow-stage3`**。**`GET` は 1 バイトも書かない**（**全ファイルと全表**）。**403 / 422**。
8. **「壊すと落ちる」テストが本当に落ちるか**（§8.1 の P8-4 の担当＋§8.4 の F7）。**自分で壊して**確かめる。
9. **回帰**: `pytest` **453**（**複数回**）・`gui_smoke` **207**・`gui_layout`（**8 画面**）。
   **実データが無傷**（263 枚・判断 3 件・**画像の署名**・`.backup/` の 7 フォルダ・**`%USERPROFILE%\image-reviewer-backups` が作られていない**こと）。
10. **実装者が自分で決めた 9 点**と**設計の穴 7 件**を判定する（とくに **`settings.json` を契約の外で足した**・**増分に `os.link`**・
    **写しの DB を `journal_mode=DELETE` に戻す**・**`health/db` は読み取り専用なら 503**）。
11. **申告 1 件**（画面検査の下ごしらえが複製の外の画像を `shutil.move` しようとして **WinError 5**。**元ファイルは無傷**と申告）を、
    **実データの画像が本当に無傷**であることで裏取りする。
12. **設計とのずれ**（`docs/p8-design.md` と違う所・**設計が黙っているのに実装が決めた**所）。

## 3. 報告の形式

`docs/p8-4-audit-report.md` に A/B/C/D/E/F/G/H と**最も重大な 3 件**。各項目に**場所**と**実行したコマンド / 再現手順**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p8-4-audit-done --body (Get-Content -Raw $env:TEMP\p8-4-audit.txt) --json
```

- subject は `p8-4-audit-start` / `-mid` / `-done`。待たずに続けて `G` に推奨つきで書いてください。
