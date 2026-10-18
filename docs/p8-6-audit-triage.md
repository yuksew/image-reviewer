# P8-6 の監査の指摘の仕分け（**2026-10-18。条件 C-1 と中程度 C-2・C-3 を直した＝P8 の最後の直し**）

- 監査: [`p8-6-audit-report.md`](p8-6-audit-report.md)（判定 **合格（条件つき）**。条件 **C-1**、中程度 **C-2・C-3**、
  軽微 **D-1〜D-8**、設計とのずれ **E-1〜E-6**、守れない物 **F**、質問 **G-1〜G-5**）。
  **推奨（G-1〜G-3）は全部採用**（G-4 の試験も足した。G-5 は設計に反映）。
- 実装の記録: [`p8-6-relink.md`](p8-6-relink.md)（この直しの**元**の記録。**§4.1-3 と §7 はこの文書と
  `p8-design.md` §0.22 が上書きする**）。
- 触っていない物: `.data/`（**`mode=ro` と `os.stat` の読みだけ**）・**画像（1 枚も動かしていない）**・
  `README.md`・`docs/design.md`・`apps/gui/`・`schemas/`・`docs/p8-6-relink.md`（歴史）・
  `docs/p8-6-audit-report.md`（監査の物）・ComfyUI。**コミットしていない**。**8790 は止めていない**。

## 触ったファイルと行数

`git diff --numstat`（前 = HEAD `4aadd9e`）と、`read_bytes().count(b"\n")` の行数。

| ファイル | 前 → 後 | 増減 | 何をした |
| --- | --- | --- | --- |
| `src/image_reviewer/scan.py` | 150 → **157** | +8/−1 | **C-1**: 早道（`size` と `mtime_ns` が同じ）で `missing_at` が立っていれば `store.mark_seen(path)` を呼ぶ。docstring に「戻ってきたら印を戻す」 |
| `src/image_reviewer/store.py` | 586 → **619** | +33/−0 | **C-1**: `Store.mark_seen(path)`（印が立っている行だけ `missing_at = NULL` と `last_seen_at` を書く。**取引の中で見直す**。`asset.deleted_at` は触らない） |
| `src/image_reviewer/relink.py` | 485 → **588** | +150/−47 | **C-2**: `_search_nearby` を 2 段（その参照切れを含む置き場 → 残り）にし、`folders` / `folders_skipped` / `found_in` / `scope` を返す。**候補の上限は段ごと**（上限に達しても次の段は歩く）。`missing()` の `hint` にも範囲。**C-3**: 取引の中で `SELECT asset_id FROM asset_location WHERE path = ?` を見直し、規則を `_conflict_of` の 1 か所に |
| `src/image_reviewer/api/relink.py` | 61 → **61** | +2/−2 | docstring（`nearby` の 2 段） |
| `tests/test_relink.py` | 741 → **961** | +225/−5 | **26 → 32 件**。C-1 の生き返り（＋印が無ければ書かない）・C-2 の 2 段（置き場の中で見つかる／残りで見つかる／**上限に達しても残りを歩く**）・C-3 の窓の中（`path_taken` と `already_registered`）・G-4 の `_sync_hidden` |
| `tools/probe_p8.py` | 1242 → **1264** | +22/−0 | `--relink` に「**動かして戻して走査 → 参照切れ 0**」（C-1。複製で 17 行に増えた） |
| `docs/p8-design.md` | 1154 → **1181** | +31/−4 | **§0.22**（P8-6 の監査で確定したこと）・§0.11・§1.2 の線 9・§3.2 の `relink` の行・**§8.1 の 68〜72** |
| `docs/duplicates-deletion-backup.md` | 608 → **612** | +7/−3 | §4 の表に「**走査で見つかった（戻ってきた）→ `missing_at` を外す**」と、近くを探すの 2 段 |
| `docs/p8-6-audit-triage.md` | **この文書（新規。161 行）** | — | 指摘ごとに 1 行 |

## 実行した確認と結果

`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`cd C:\work\image-reviwer`。

| 何 | コマンド | 結果 |
| --- | --- | --- |
| **pytest** | `uv run --no-sync pytest -q -p no:cacheprovider` ×**6**（**最終形が 2 回**、試験を 1 件足す前の版が 4 回） | **513 passed**（最終形。途中の版は 512。36.5〜36.9 秒）が**全部緑**（**507 ＋ 新規 6**） |
| **gui_smoke** | `node tools/gui_smoke.mjs` | **322 ok / NG 0**（「すべて ok」） |
| **gui_layout** | 複製（**8791**）で **11 本**（**10 画面 ＋ `pending --ids`**） | **11 本とも「すべて ok」**（**39 の ok 行・NG 0**。各 3 窓） |
| **契約** | `uv run --no-sync --with jsonschema python -X utf8 tools/check_contract_p8.py` | **OK 24 / NG 0**（契約は足していないので前のまま） |
| **壊し試験** | `uv run --no-sync python -X utf8 .tmp-audit-redo/p8-6-fix/mut_c.py` | **6 通り中 6 通りが落ちる**（下表。写しを `PYTHONPATH` で影にして `tests/test_relink.py tests/test_scan_state.py`） |
| **線 9（複製）** | `uv run --no-sync python -X utf8 tools/probe_p8.py --relink` | **17 行すべて OK**（新設の C-1 の行を含む。下の「線 9」） |
| **実データ** | `uv run --no-sync python -X utf8 .tmp-audit-redo/p8-6-fix/real_check.py`（前・後。`mode=ro`） | **署名が同じ**（下の「実データが無傷であること」） |

### 壊し試験（6/6 が落ちる）

| # | 壊した物 | 落ちた試験 |
| --- | --- | --- |
| 1 | **C-1**: 走査の早道で `store.mark_seen()` を呼ばない | `test_a_file_that_came_back_is_revived_by_the_scan` |
| 2 | **C-1**: 印が無くても毎回 `mark_seen()` を呼び、`mark_seen()` も毎回書く | 同上（2 回目の走査で `last_seen_at` が変わる。**時計を進めてから見る**） |
| 3 | **C-2**: 置き場ぜんぶを一度に歩く（2 段をやめる） | `test_nearby_finds_the_file_with_the_same_name_in_a_registered_root` / `test_nearby_walks_the_place_that_holds_the_missing_file_first` / `test_nearby_keeps_walking_the_rest_after_hitting_the_cap` |
| 4 | **C-2**: 候補の上限を**段をまたいで**数える（2 段目を歩かない） | `test_nearby_keeps_walking_the_rest_after_hitting_the_cap` |
| 5 | **C-3**: 取引の中の見直しを外す | `test_a_path_taken_while_hashing_is_refused_by_the_recheck`（503 `db_error` になる）/ `test_a_path_registered_to_the_same_asset_while_hashing_is_refused`（`IntegrityError`） |
| 6 | **G-4**: `DeletionService._sync_hidden()` を呼ばない | `test_relink_redraws_the_catalog_flag_from_the_rules` |

### gui_layout の 11 本（複製は `.tmp-audit-redo/p8-6-fix/gui`。`IMAGE_REVIEWER_DATA` つき）

```text
--count 8                                           比較（8 枚。3 窓 ×3 計測）
--screen requests                                   要求の一覧
--screen group --group audit-group                  まとまりレビュー
--screen asset --ids 01M4Z0KJRT8N9T5PDFTJCVDYQN     注記とタグ
--screen tags                                       語の一覧（5 語）
--screen jobs                                       ジョブ
--screen duplicates                                 重複の整理（20 群 / 55 枚）
--screen pending                                    最近の削除（194 行 = 実データの段 1 の 193 ＋ 種の段 3）
--screen pending --ids …                            最近の削除（削除の確認つき）
--screen library                                    ライブラリ（下部バーの入口）
--screen settings                                   設定（段 3 の印）
```

- 複製は `sqlite3.Connection.backup()`（WAL を畳む）＋**近い群の 13 枚を `gui-lib/` に `copy2`**。
  それ以外の生きた登録は複製の中で参照切れにした（**実データのファイルを複製のサーバに読ませない**保険）。
  種（語・まとまり・除外の理由）は複製の中だけ（`.tmp-audit-redo/p8-6-fix/replica.py`）。
- 止める前に **`GET /api/health` の `data_dir` が複製であることを確かめてから** `Stop-Process` した
  （**8790 は止めていない**。**8791〜8798 で LISTEN していたのは私の 8791 だけ**だった）。
- **注意の 3 行**（NG ではない）: `--screen requests` は open な要求が 0 件、`--screen settings` は
  `last_error` が空（`--backup-error` の前提を入れていない）なので、その 2 つの検査は「見ない」。
  **私の直しは `src/` の Python だけで、画面のコードは 1 行も触っていない**。

### 線 9（実データの複製で通した結果。`tools/probe_p8.py --relink`）

`copy2` した画像 6 枚で、**動かす → 走査 → 参照切れ → 戻す → 走査**まで通した（新設の行）:

```text
[OK] 線 9 の前半（動かして走査 → missing_at が立つ）: scan missing=1 / 一覧 1 件 / missing_at=2026-10-18T12:47:12Z
[OK] 線 9 の後半（人が繋ぎ直せる・同じ asset のまま）: 200 moved=True to=…\relink-moved\renamed.png
[OK] nearby（同じ名前を置き場から探して繋ぐ）: 200 to=…\relink-nearby\sub\01M4Z0KJ-….png searched=1
[OK] 動かして戻して走査 → 参照切れが 0 に戻る（C-1）: 走査1 missing=1 / 一覧 1 件 → 走査2 missing=0 known=4 / missing_at=None
[OK] 実データが無傷（複製だけで試した）: 455 枚 / 判断 3 件 / 参照切れ 156 件
まとめ: すべて OK
```

（**「参照切れ 156 件」は `missing_at` ではなく「実体が無いパス」**の数。実データの `missing_at` は
**0** のまま＝この行は前後で同じ。下の「実データが無傷であること」。）

## 実データが無傷であること（`mode=ro` と `os.stat` だけ）

`.tmp-audit-redo/p8-6-fix/real_check.py` の**前後**（作業の最初と最後）で**同じ**だった:

| 見た物 | 前 | 後 |
| --- | --- | --- |
| `asset` | **455** | **455** |
| `asset_location`（うち `missing_at` が立っている物） | **455（0）** | **455（0）** |
| `deletion_log`（段の内訳） | **193（段 1 が 193）** | **193（段 1 が 193）** |
| `asset.deleted_at` が立っている枚 | **193** | **193** |
| `decision` / `asset_tag` / `location_history`（`reason='relinked'`） | **3 / 0 / 0（0）** | **3 / 0 / 0（0）** |
| 画像の署名（455 パスの `(パス, size, mtime_ns)` の sha256） | **`36be75abaadb2c6c`** | **`36be75abaadb2c6c`** |
| 実体が無いパス（利用者が既に片付けた物） | **156** | **156** |
| 合計バイト | **357,842,538** | **357,842,538** |
| `db.sqlite3` / `-wal` / `-shm` の `(size, mtime_ns)` | 3,055,616 / 4,190,072 / 32,768 | **同じ**（mtime も同じ） |

- **利用者の段 1 の 193 行は 1 行も触っていない**（`missing_at` は 0 のまま・`deleted_at` も 193 のまま。
  **戻してもいないし消してもいない**）。**画像も 1 枚も動かしていない**（署名が同じ）。
- 実データを開いたのは **`mode=ro` の読みだけ**。試験はすべて複製（`backup()` ＋ `copy2`）で、
  サーバは **8791** に **`IMAGE_REVIEWER_DATA=<複製>`** で立てた（**止める前に `/api/health` の
  `data_dir` が複製であることを確かめた**）。**8790 は一度も止めていない**（最後まで PID 7324 で LISTEN。
  `GET /api/locations/missing` も打っていない＝**利用者のアプリには触っていない**）。
- 書き込んだのは複製（`.tmp-audit-redo/p8-6-fix/gui`・`gui-lib`・`backups`・`.tmp-audit-redo/p8probe`）だけ。
  **`%USERPROFILE%` の下には 1 つも作っていない**。

## 指摘ごとに 1 行

| # | 指摘（監査） | どうした | どこ |
| --- | --- | --- | --- |
| **C-1** | **元の場所に戻ってきたファイルを走査が生き返らせない**（`scan.py:75-78` の早道が `register()` の `missing_at = NULL` に届かない。**移動は `mtime_ns` を変えない**ので必ず早道に落ちる。R12a） | **採用（G-1）**。`Store.mark_seen(path)` を足し、早道で `known["missing_at"]` が立っていれば呼ぶ。**印が無い行には 1 バイトも書かない**（走査を重くしない。`last_seen_at` の意味を変えない）。**取引の中で見直す**（C-3 と同じ流儀）。**`asset.deleted_at` は触らない**（段 2・3 の削除の途中の枚を走査で勝手に戻さない。戻す道は「最近の削除」）。**履歴は足さない**（走査は繋ぎ直しではない）。試験は「動かす → 走査 → 参照切れ 1 → **同じパスへ戻す** → 走査 → **参照切れ 0・`known` 1・`last_seen_at` が入る**」＋「2 回目の走査で書かない」 | `scan.py` / `store.py` `mark_seen`、`tests/test_relink.py`、`tools/probe_p8.py --relink`、設計 §0.11・§1.2 の線 9・§8.1 の 68・69 |
| **C-2** | **`nearby` の `path` 省略は登録した置き場ぜんぶを歩く**（実データでは ComfyUI 出力 181 ファイル・306 MB も毎回。`folders` は「歩いた」ではなく「歩く予定の全部」を返していた） | **採用（G-2）**。**2 段**にした: ①**その参照切れを含む置き場**（`missing` の `roots` と同じ `is_under` の規則） ②見つからなければ**残りの置き場**。**見つかった段で止める**ので、306 MB の置き場は**1 段目で見つかったときには歩かない**。応答に **`folders`（歩いた順）・`folders_skipped`・`found_in`（`given`/`home`/`rest`）・`scope`** を足し、**404 / 409 の `details` にも同じ欄**を入れた（**黙って捨てない**）。**候補の上限（200）は段ごと**に掛け、**上限に達しても次の段は歩く**（「見つからなければ残りへ」を守る）。`path` を指定したときは**その 1 つだけ**を歩く（今までどおり）。`hint` にも範囲を書いた（D-2） | `relink.py` `_search_nearby` / `missing`、`tests/test_relink.py`、設計 §0.11・§3.2・§8.1 の 70 |
| **C-3** | **二重登録の検査が取引の外**（`sha256` を読む間に別の要求が同じパスを登録すると主キーに当たり、P8-4 の `sqlite_error_handler` が **503 `db_error`「DB が壊れているので読めません。バックアップから戻してください」**を返す＝**壊れていない DB で復元を勧める**。`mut/M3` の実測） | **採用（G-3）**。取引の中（`UPDATE` の直前）でもう一度 `SELECT asset_id FROM asset_location WHERE path = ?` を見る。**規則は `_conflict_of` の 1 か所**（取引の外と中で同じ答え。**別の `asset` は 409 `path_taken`・同じ `asset` は 409 `already_registered`**）。試験は**窓を決定的に作る**（`relink.sha256_of` を差し替え、**中身を確かめた後**に別の要求がそのパスを登録した形）＋**口から見て 409 で、503 `db_error` でも「バックアップ」の語も出ない**こと | `relink.py` `relink` / `_conflict_of` / `_refuse_if_registered`、`tests/test_relink.py`、設計 §0.22-3・§3.2・§8.1 の 71 |
| **D-1** | 走査の印は錠を取る前に立つ（P8-5 の D-4 と同じ。`relink` は錠を取らないので無関係） | **そのまま**（P8-5 の申し送り 2 と同じ。私の担当は `relink` / `scan` のこの 1 か所で、印の話ではない） | — |
| **D-2** | 一覧の `roots` と `nearby` が実際に歩く範囲が食い違う（`hint` に 1 語） | **採用（C-2 で解消）**。`roots` は「**先に**歩く置き場」、実際に歩いた範囲は `folders` / `folders_skipped`、`hint` にも「その参照切れを含む置き場（この応答の roots）から順に…残りの置き場」と書いた | `relink.py` `missing` / `_search_nearby` |
| **D-3** | `exact` の新しいパスは置き場の外でもよい（設計が黙っている。段 3 は `allow_stage3` で縛るので安全側） | **そのまま**（**置き場の外を許すのは正**＝「まだ走査していない置き場へ動いた」を繋ぐのが `nearby` の目的。**設計 §0.11 に 1 行足した**） | 設計 §0.11 |
| **D-4** | `not_registered` の `code` が削除の語と重なる | **そのまま**（`details.missing` に候補が入るので実害なし。語彙を増やすと契約の話になる） | — |
| **D-5** | 監査の壊し試験の写しが `apps/gui` を持たない | **該当なし**（監査の脚本の副作用。私の `mut_c.py` は `tests/test_relink.py` と `tests/test_scan_state.py` だけを回す） | — |
| **D-6** | 記録 §2 の `gui_smoke` の数が古い | **この文書が正**（**322 ok / NG 0**） | この文書 |
| **D-7** | `cli backup` / `scan` / `rebuild-metadata` は env 無しで実データを開く（README に 1 行） | **触らない**（`README.md` は担当外。**申し送り 3**） | — |
| **D-8** | **`sqlite_error_handler` の守備範囲が広い**（`IntegrityError` / `OperationalError` も「DB が壊れている」に写す） | **この段では触らない**（**C-3 で既知の道は塞いだ**。handler の守備範囲は P8-4 の設計の話で、`malformed` に絞るか番号を分けるのは**次の段の設計事項**。**申し送り 2**） | — |
| **E-1** | §0.11 は「同じルート内」のまま（実装は置き場ぜんぶ） | **C-2 で設計を実装に合わせた**（§0.11 を「①その参照切れを含む置き場 → ②残り」に書き換え） | 設計 §0.11 |
| **E-2** | §0.11 の「自動（走査のたびに繋ぐ）」を作っていない | **設計に「作っていない」と明記**（§0.11。専門 §4 の注記と同じ） | 設計 §0.11 |
| **E-3** | 口の表は 3 つだが実装は `from_path` を足した | **§3.2 の行に `from_path` を書いた** | 設計 §3.2 |
| **E-4** | `location_history` に 3 列を足した（版は上げない） | **そのまま**（P8-6 の実装の決定。`design.md` §5.1 は親の doc pass） | — |
| **E-5** | 線 9 に「戻ってきたら走査で戻る」が無い | **C-1 で線 9 に足した**（合否も「**戻せば走査で戻る**」） | 設計 §1.2 の線 9 |
| **E-6** | 専門 §4 の表に「見つかれば外す」が無い | **足した**（`duplicates-deletion-backup.md` §4 の表に行を 1 つ） | 専門 §4 |
| **F** | C-1・C-3 を見る試験が無い／`_sync_hidden`（M9）が落ちない | **足した**（**6 件**。C-1 の生き返り・C-2 の 2 段 ×3・C-3 の窓 ×2・G-4。**壊すと落ちる**の 6 通りで確認） | `tests/test_relink.py` |
| **G-1** | 早道で `missing_at` を戻す | **採用**（C-1。印が無い行には書かない形にした） | `scan.py` / `store.py` |
| **G-2** | `nearby` を 2 段に／`hint` に範囲 | **採用**（C-2。`folders_skipped` と `found_in` も返す） | `relink.py` |
| **G-3** | 取引の中で再検査 | **採用**（C-3。規則は `_conflict_of` の 1 か所） | `relink.py` |
| **G-4** | `_sync_hidden` の試験 2 件 | **採用**（段 1 の印は残る／印が無ければ戻る） | `tests/test_relink.py`、設計 §8.1 の 72 |
| **G-5** | §0.11 の「同じルート内」と「自動」・§9 の P8-3 の行 | **§0.11 は直した（E-1・E-2）**。**§9 の P8-3 の行と `p8-6-relink.md` の記述は親の doc pass**（申し送り 4） | 設計 §0.11・§0.22 |

## 申し送り（親が決めること）

1. **`docs/design.md` への反映**（担当外）: 「走査で見つかったら `missing_at` を外す」（C-1）、`nearby` の 2 段と
   応答の `folders_skipped` / `found_in` / `scope`（C-2）、`POST /api/locations/relink` の 2 重登録の見直し（C-3）。
   正は `p8-design.md` §0.11・§0.22・§3.2・§8.1 の 68〜72。
2. **D-8（`sqlite_error_handler`）**: `sqlite3.DatabaseError` を全部 503「DB が壊れている」に写す形は
   **C-3 の 1 本を塞いでも残る**（`CHECK` に当たる語彙の穴・`database is locked`）。次の段で
   **`malformed` だけに絞る**か、**`IntegrityError` → 409・`OperationalError` → 503 の別番号**にする設計が要る。
3. **D-7（`cli` の既定）**: `cli backup` / `scan` / `rebuild-metadata` は env 無しで `.data` を開く（**利用者の道具なので正**）。
   README に「複製で試すときは `IMAGE_REVIEWER_DATA` を付ける」の 1 行を足すか。
4. **`p8-6-relink.md` §4.1-3・§7（未計測）と `p8-design.md` §9 の P8-3 の行**は、この直しで**上書きされた**。
   記録は歴史なのでそのままにしてある（親の doc pass で 1 行の注記を足すならここが元）。
5. **実データの段 1 の 193 行**（利用者が消した物）は**この直しで 1 行も触っていない**（`missing_at` は 0 のまま）。
   C-1 の生き返りは**段 2・3 の削除の途中の枚を戻さない**（`asset.deleted_at` を触らない）ので、
   利用者の「消した」意思とは衝突しない。
