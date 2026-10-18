# P9 の監査の指摘の仕分け（2026-10-19）

- 監査: [`p9-audit-report.md`](p9-audit-report.md) — **判定: 合格（条件つき）**。
  条件は **C-1〜C-3**、ほかに **D-1〜D-10**・**G-1〜G-6**。
- 直した人: DeepSeek（dsh）。**監査の推奨はすべて採用**（見送った物は §5 に理由を書いた）。
- **正とした文書**: 監査の「直し方（推奨）」・`docs/design.md` §12.1 / §12.2 / §16.7・
  `docs/frontend-design.md` §6・`p8-4-audit-triage.md` の B-1 / G-1。
- **触っていない物**: **実データ `.data/`（`mode=ro` と `os.stat` の読みだけ。画像は 1 枚も動かしていない）**・
  **`.backup/`（利用者の日次 3 件はそのまま。§4）**・**8790（一度も止めていない。打ったのは GET だけ）**・
  `ComfyUI`・`schemas/`（契約は変えていない）・`pyproject.toml` / `uv.lock`。**コミットはしていない**。
- **同じ作業ツリーで「ワーディング監査」の担当が `apps/gui/index.html`・`app.js`・`pending.js`・
  `docs/frontend-design.md` を同時に直している。** 下の「行数」は**私の変更の物**で、
  `app.js` / `pending.js` / `frontend-design.md` の差分にはその担当の分が混ざる
  （**私の検証は混ざったツリーで回した**。§3）。

## 1. 指摘ごとの 1 行

| # | 指摘（監査） | どうした | どこ |
| --- | --- | --- | --- |
| **C-1** | `_refuse_if_broken` が**書き込んだ接続のページキャッシュ**越しに `quick_check` するので、外から潰したページを見落とし、**壊れた DB に書き続ける**（0.65 MB の DB・既定の `cache_size` でも起きる） | **採用（推奨どおり）**。`quick_check` を**新しい読み取り専用の接続**（`quick_check_on_disk()`＝`check_db_file` が `file:...?mode=ro` を 1 本開く）に変えた。**「混んでいる」（`database is locked`）だけは `read_only` に切り替えない**（一時的な錠で永久に書き込みを止めない）。試験を 1 件足した（`test_a_page_in_the_writers_cache_is_still_noticed`。**既定の `cache_size=-2000` のまま**・250 行・0.65 MB）。**`cache_size` は入れないまま**（実利なし）——**理由を「速さだけ」に書き直した**（`db.py` のコメント・§12.2・§16.7-2・`p9-implementation.md` §3-2・`tests/test_db.py` の docstring）。※ 監査が「P8-4 の記録にも `shrink_memory`＋`cache_size=1` で捨てる、が残っていた（当時から知り得た）」と書いているので、**P8-4 の記録は歴史として残し**、この triage と §12.2 に「当時から知り得た」ことを書き残した | `backup.py` `quick_check_on_disk` / `_refuse_if_broken` / `_looks_busy`、`db.py`、`tests/test_backup.py`、`docs/design.md` §12.2・§16.7-2、`docs/p9-implementation.md` §3-2、`tests/test_db.py` |
| **C-2** | 上部バーは**生きた枚**（262）・「すべて」(`#c-all`) と下部バーは `/api/stats` の `assets`（455）で、**同じ画面に 2 つの数** | **採用（推奨: 生きた枚に統一）**。規則を `apps/gui/counts.js` の**1 か所**（純粋関数 `liveTotal` / `briefText` / `provenanceCounts`）に置き、上部バー・「すべて」・下部バーの枚数・来歴あり／なしを**生きた枚**に統一。`gui_smoke` の `/api/assets` stub に `total` を持たせ、**実データの 455 と 262 が混ざらない**検査を 5 件足した。`frontend-design.md` §6 の例を **455 → 262** に直した。**本物の Chrome で実データの複製（455 行・生きた 262 枚）を開いて実測**（§3） | `apps/gui/counts.js`（新規）、`apps/gui/app.js` `renderStats`、`tools/gui_smoke.mjs`、`docs/frontend-design.md` §6 |
| **C-3①** | 「同時 8 本なら 22 ms/枚」は `probe_p9.py` が**自分で回した**見込みで、**実装にスレッドプールは無い**（未申告） | **採用（推奨: 書き分け）**。§12.1 の 2 行を「**1 スレッド（実測）／並列は未実装（見込み）**」に書き分け、§12.2 のサムネイルの項と §16.7-5 に「**未実装**」と明記した。`p9-implementation.md` §2 の #3/#4 も同じ | `docs/design.md` §12.1・§12.2・§16.7-5、`docs/p9-implementation.md` §2 |
| **C-3②** | `state=kept` の計測は**0 件への絞り込み**（`make_synthetic_db.py` の直接 `UPDATE` を起動時の `reconcile()` が全部戻す） | **採用（推奨: 正しい条件で測り直す）**。`seed_rows()` を **`ReviewService.apply_asset()` で台帳に入れる**形に直した（再生成で **`decision` 2,209 件・`kept` 1,429 枚**）。`probe_p9.py` は**返った件数を出し、0 件なら落とす**ようにした。1 万枚で **1,429 件・p95 289.9 ms** を実測 | `tools/make_synthetic_db.py` `seed_rows`、`tools/probe_p9.py` `probe_list`、`docs/design.md` §16.7-11 |
| **D-1** | `disk i/o error` を「壊れ」に数えている（復元を勧める）。この語には試験が無い（壊し試験 M7 が生き残る） | **採用**。`CORRUPTION_WORDS` から外し、**503 `io_error` ＋ `Retry-After: 5`** で「**もう一度**。復元は要らない」にした。**試験 1 件**（`disk I/O error` → 503 `io_error`・「戻してください」を出さない）を足した（**M7 が落ちる**）。上部バーも `code` で見分ける（`badge.js` の `isReadOnlyStatus()`） | `src/image_reviewer/api/__init__.py`、`apps/gui/badge.js`、`tests/test_backup.py`、`docs/design.md` §6.1・§16.7-3 |
| **D-2** | `database is locked` が **500 `sqlite_error`** | **採用**。**503 `busy` ＋ `Retry-After: 1`** にした（「混んでいる」は内部エラーではない）。試験 1 件（`database is locked` → 503 `busy`）。**既存の「500 の 3 通り」の 1 つ（`database is locked`）はこの試験から外した**（意図した変更。§6） | 同上 |
| **D-3** | `probe_p9.py` の `--out` に相対パスを渡すと `--library` が落ち、**日次も黙って 5 回失敗**（stderr だけ） | **採用**。`--out` / `--synth` / `--replica` を `Path(...).resolve()` に通した。**相対パスで `--list --decide --real --library` を実際に回して通した**（§3）。直す前の落ち方は `check_backup_dir()` が相対パスを **422 `bad_backup_dir`** で断る物（実測） | `tools/probe_p9.py` `main`、`docs/design.md` §16.7-12 |
| **D-4** | 文書が実機より古い（「日次 0 個」） | **採用**。実機は **8790 = Explorer → `start-image-reviewer.cmd`** の系譜で、利用者が置き場を `.backup/daily` に変え、**日次は `20261018`（263 枚）・`20261019`（455 枚・00:00:15 JST）**、手動 `20261018-171143` がある。`handoff.md` §7-1・§0 と `p9-implementation.md` §8-9 を直した | `docs/handoff.md`、`docs/p9-implementation.md` |
| **D-5** | `--include-library` は OS のファイルキャッシュで 2.40 秒／0.63 秒 | **採用（両方書く）**。§12.1・§12.3・§16.7-6 に **0.63〜2.40 秒**（実装者 132 MB/s・監査 516 MB/s・**再測 0.68 秒＝427 MB/s**）を書き、「**冷えた状態／温まった状態の両方**」を書く規則を足した | `docs/design.md` §12.1・§12.3、`docs/p9-implementation.md` §2 |
| **D-6** | `/api/stats` が §12.1 に無い（画面は一覧と一緒に毎回呼ぶ） | **採用**。§12.1 に 1 行足した（**p95 134.6 ms**（合成 1 万枚・自分の再測）／**6.1〜7.1 ms**（実データ 455 枚））。`probe_p9.py` も `/api/stats` を測るようにした | `docs/design.md` §12.1、`tools/probe_p9.py` |
| **D-7** | exe の数の単位（MiB と MB）と冷えた起動 | **採用**。**138.3 MB（= 131.9 MiB）** と書き、**冷えた 1 回目 1.71 秒**を書き分けた | `docs/design.md` §16.7-8、`docs/p9-implementation.md` §6-2 / §6-3 |
| **D-8** | `_failed()` がもう一度 `_record_error()` を呼び、`read_only` の DB に書けずトレースバック（二重記録） | **採用**。`code == 'read_only'` の断りは記録しない（`_switched_read_only()`）。**実測で再現してから直した**（直す前は `バックアップの失敗を記録できませんでした` のトレースバックが出た）。試験は C-1 の試験の中で「そのログが出ない」ことを見る | `backup.py`、`tests/test_backup.py`、`docs/design.md` §16.7-14 |
| **D-9** | `probe_p9.py --decide` の表示が `state=None / 掃き出し待ち None`（応答に無い鍵） | **採用**。応答の実在の鍵（`asset.review_state`・`affected_group_ids`）を出す。実測で `review_state=kept` と出る | `tools/probe_p9.py` `probe_decide` |
| **D-10** | 壊し試験 M1 / M2 は pragma の値だけを見ていて**振る舞いの試験が無い**（`temp_store` を外すと 1 万枚の一覧が 500） | **見送り（理由つき。§5）**。`TMP` / `TEMP` を書けない所へ向けても SQLite は**カレント（`.`）に落ちる**ので、pytest の中で決定的に作れない（実測）。**代わりに** D-6 と C-3② で実測を厚くし、`tests/test_db.py` の docstring に「なぜ振る舞いの試験を足していないか」を残した | `tests/test_db.py` の docstring、§5 |
| **G-1** | `quick_check` を新しい読み取り専用の接続にするか → **する** | **採用**（C-1）。250 行の試験も足した | 同上 |
| **G-2** | 上部バーの「枚」は何を数えるか → **生きた枚（262）に統一、`c-all` も同じ数、§6 の例も 262** | **採用**（C-2） | 同上 |
| **G-3** | 一覧 API の段をいつ立てるか → **1 万枚が現実になる前に、`/api/stats` と一緒に** | **持ち越し（コードは変えない）**。§12.1 の「必要な条件」に `/api/stats` を足し、§16.7-7 に「2 つ一緒に」と書いた。段を立てるのは利用者の判断（`handoff.md` §7-2） | `docs/design.md` §12.1・§16.7-7 |
| **G-4** | スレッドプールを実装するか、§12.1 を「見込み」と書くか → **今は書き分けだけ** | **採用**（C-3①） | 同上 |
| **G-5** | 日中に外した枚をその日の控えに入れる道 → **段 1 / 段 3 の直後に「いま取る」を促す 1 行** | **採用**。削除の実行後（**段 1・3 だけ**）に「控えは日付が変わったときに取ります。**設定**の「いま取る」で今すぐ取れます。」を出す（**自動では取らない**。段 2 では出さない）。`gui_smoke` に 3 件、`frontend-design.md` §6 に 1 行 | `apps/gui/pending.js` `backupHintHtml`、`tools/gui_smoke.mjs`、`docs/frontend-design.md` §6、`docs/design.md` §16.7-13 |
| **G-6** | `disk i/o error` の扱い → **復元を勧めない** | **採用**（D-1） | 同上 |

## 2. 作った物・触った物（行数）

行数は `read_bytes().count(b"\n")`（最終形）。**「+」は私の追加行**（`git diff --numstat` の追加。
同じファイルを他の担当も触っているので、`app.js` / `pending.js` / `frontend-design.md` は**混ざった数**）。

| ファイル | 行数 | + | 何をしたか |
| --- | --- | --- | --- |
| `src/image_reviewer/backup.py` | 1578 → **1646** | 74 | **C-1** `quick_check_on_disk()`（新しい ro 接続）・`_refuse_if_broken` の差し替え・`_looks_busy()`（混んでいるだけなら `read_only` にしない）・**D-8** `_switched_read_only()`（二重記録しない）・module docstring の 12 |
| `src/image_reviewer/db.py` | 886 → **891** | 11 | **C-1** `cache_size` の**理由の書き直し**（前の理由は誤りだったと明記） |
| `src/image_reviewer/api/__init__.py` | 186 → **233** | 53 | **D-1 / D-2** `disk i/o error` → 503 `io_error`、`database is locked` → 503 `busy`（どちらも `Retry-After`。**復元を勧めない**）。`CORRUPTION_WORDS` から `disk i/o error` を外した |
| `apps/gui/counts.js` | **新規 52** | 52 | **C-2** 画面の「枚」の規則（`liveTotal` / `briefText` / `provenanceCounts`。純粋関数） |
| `apps/gui/app.js` | 548 → **617** | 100 | **C-2** `renderStats()` が `counts.js` を使う（*他の担当のワーディングの分を含む*） |
| `apps/gui/badge.js` | 275 → **289** | 17 | **D-1 / D-2** `isReadOnlyStatus()`（503 でも一時的な物を「読み取り専用」と言わない） |
| `apps/gui/pending.js` | 725 → **752** | 37 | **G-5** `backupHintHtml()`（段 1・3 の直後に控えの道） |
| `tools/probe_p9.py` | 770 → **800** | 38 | **D-3** パスの `resolve()`・**D-6** `/api/stats` の計測・**D-9** 判断の応答の名札・**C-3②** `state=kept` の件数（0 件なら落とす） |
| `tools/make_synthetic_db.py` | 250 → **273** | 33 | **C-3②** `seed_rows()` が判断を `ReviewService.apply_asset()` で**台帳に**入れる。できた物に `kept` / `decision` を出す |
| `tools/gui_smoke.mjs` | 1925 → **1976** | 54 | **C-2** 5 件（455 と 262 を混ぜない・切れているときの文言・古いサーバ）・**G-5** 3 件・**D-1/D-2** 3 件。`/api/assets` の stub に `total` |
| `tests/test_backup.py` | 2042 → **2155** | 114 | **C-1** 1 件（`test_a_page_in_the_writers_cache_is_still_noticed`）、**D-1/D-2** 2 件（parametrize）、`small_store()`。`database is locked` を 500 の試験から外した |
| `tests/test_db.py` | 909 → **920** | 15 | docstring の書き直し（`cache_size` の理由・D-10 で振る舞いの試験を足さない理由） |
| `docs/design.md` | 2074 → **2118** | 66 | §12.1（C-3 の書き分け・`/api/stats`・`--include-library` の両方の値）・§12.2（`cache_size` の理由の書き直し・スレッドプール未実装）・§6.1（例外の語彙の表）・§12.3（D-5）・§16.7（2・3・4b・5・6・7・8 の直しと 10〜14 の追加） |
| `docs/frontend-design.md` | 1020 → **1049** | 80 | §6 の「上部バー: 枚数」を **262** に・削除の実行後の控えの案内（G-5）・上部バーの読み取り専用の条件（D-1/D-2）。*他の担当の分を含む* |
| `docs/handoff.md` | 618 → **625** | 10 | **D-4** 実機の日次（§0・§7-1） |
| `docs/p9-implementation.md` | 427 → **446** | 39 | §2（`/api/stats` の行・C-3 の書き分け・D-5）・§3-2（**理由の書き直し**）・§3-4（C-2）・§6（D-7）・§8-9（D-4） |
| `README.md` | 295 → **301** | 10 | 数を実測へ（**520 件・333 検査・11 本**）・`--screen tags` と `--screen pending` の前提 |
| `docs/p9-audit-triage.md` | **新規（この文書）** | — | 指摘ごとの 1 行 |
| **合計（私の分）** | — | **約 700 行**（うち文書 240 行） | |

## 3. 実行したコマンドと結果

`$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"`、`cd C:\work\image-reviwer`。
**`uv run` は全部 `--no-sync`**（利用者のサーバが `.venv` を握っているため）。

| 何 | コマンド | 結果 |
| --- | --- | --- |
| **C-1 の再現と直し** | `uv run --no-sync python -X utf8 .tmp-audit-redo/p9fix/probe_c1.py` | 直す前: 250 行（0.65 MB）で **`tick()` が控えを取り `read_only=False`**（書いた接続の `quick_check` は `ok`）。直した後: **`taken` なし・`read_only=True`**。2.28 MB は前から断る（テストが見ていたのは境界） |
| **C-1 の「壊すと落ちる」** | `uv run --no-sync python -X utf8 .tmp-audit-redo/p9fix/mutate_c1.py` | `src/` を写して `_refuse_if_broken` を**直す前の形**に戻すと **新試験が FAILED**（`test_a_page_in_the_writers_cache_is_still_noticed`）。旧 `test_a_broken_source_…` は**通るまま**（＝あの試験は保証ではない、という監査の指摘どおり） |
| **pytest** | `uv run --no-sync pytest -q` × **4** | **520 passed** × 4（40.0 / 38.9 / 38.8 / 41.8 秒）。**518 → 520**（C-1 1 件・D-1/D-2 2 件 ＝ +3、`database is locked` を 500 の試験から外して −1） |
| **gui_smoke** | `node tools/gui_smoke.mjs` | **333 ok / NG 0**「すべて ok」（**322 → 333**＝C-2 5・G-5 3・D-1/D-2 3）。**私の変更を入れた時点の数**。※ その後に**並行して入ったワーディング監査の差分**（`compare.js` / `pending.js` / `settings.js` / `duplicates.js` の文言）で、**その担当がまだ検査の期待値を更新していない**ため、いま打つと 26 件 NG になる（**私の 9 件の新しい検査は全部 ok**。§5-6） |
| **gui_layout（11 本）** | 複製（8791）で `--count 8` / requests / group / asset / tags / jobs / duplicates / pending / pending --ids / library / settings | **11 本とも「すべて ok」**（3 窓）。※ 2 つの前提と 2 か所の追従が要った（§5-6）: ①**`--screen tags` は語が 0 件だと 3 窓とも NG**（実データの `tag` は 0 件）ので `tools/gui_layout_seed.py --data <複製> --tags` を当てた ②`--screen pending` は**本物の走査を 1 回打つ**（複製の DB に行が増える） ③並行のワーディング監査（W-20: 段 3 の呼び方を 1 つに）で `gui_layout` の期待値 2 か所が古くなったので、**新しい語と古い語の両方を受ける**ように直した（`3 実削除` → `3 実体を消す`、`印あり` → `許可あり|印あり`、`段 3 の印がありません` → `段 3 の(印|許可)がありません`） |
| **C-2 の実データ実測（本物の Chrome）** | `node .tmp-audit-redo/p9fix/gui_counts.mjs --base http://127.0.0.1:8791` | `{brief:"262 枚", all:"262", with:"182", without:"80", bar:"262 枚 来歴あり 182 来歴なし 80", stage:262}` で **6 件すべて ok**。`/api/stats` は 455 のまま（**455 を画面に出していない**） |
| **§12.1 の再測（C-3 / D-6）** | `uv run --no-sync python -X utf8 tools/probe_p9.py --out .tmp-audit-redo/p9fix --synth .tmp-audit-redo/p9fix/synth10k --replica .tmp-audit-redo/p9fix/real --list --decide --real --runs 30` | **`/api/stats` p95 134.6 ms**（1 万枚）・**`?state=kept` は 1,429 件で p95 289.9 ms**・一覧 p95 260.6 ms・1024px **130 ms/枚 → 21.7 分**・256px **29 ms/枚 → 4.9 分**・同時 8 本（道具の中）21 / 4 ms・比較 p95 7.5 ms・判断 p95 1.5 ms（`review_state=kept`）。**相対パスの `--out` で通った**（D-3） |
| **`--include-library` の再測（D-5）** | 同 `--library --replica .tmp-audit-redo/p9fix/real` | **0.68 秒 / 262 枚・291.1 MB（427 MB/s）**。画像なしの日次 **72.7 ms** |
| **複製の `/api/stats`（D-6）** | `.tmp-audit-redo/p9fix/stats_real.py`（keep-alive・30 回） | **p95 7.1 ms**（実データ 455 枚）・`/api/assets?limit=2000` p95 24.9 ms |
| **合成 1 万枚の作り直し（C-3②）** | `uv run --no-sync python -X utf8 tools/make_synthetic_db.py --out .tmp-audit-redo/p9fix/synth10k --count 10000 --force` | 画像 5.8 秒・初回走査 **41.2 秒**・判断 **`kept` 1,429 / `rejected` 780 / `decision` 2,209**・DB 30.8 MB（**判断が台帳に載った**） |
| **D-3 の証拠** | `.tmp-audit-redo/p9fix/d3_evidence.py` | 相対パス → **422 `bad_backup_dir`「絶対パスで指定してください」**、絶対パス → OK |
| **D-10 の検討** | `.tmp-audit-redo/p9fix/probe_temp_store.py`（＋ 新しいプロセスで `TMP`/`TEMP` を**ファイル**へ） | 1 万行の `ORDER BY` は**素の接続でも通った**（SQLite が `.` に落ちる）。**決定的な振る舞いの試験は作れない** → §5 |

## 4. 実データが無傷であること

`.tmp-audit-redo/p9fix/sig.py`（`mode=ro` と `os.stat` の読みだけ）を**作業の前と最後**に取った。

| 見た物 | 前（`sig-before.txt`） | 後 |
| --- | --- | --- |
| `asset` / `asset.deleted_at` | **455 / 193** | **455 / 193** |
| `asset_location`（`missing_at`） | **455（0）** | **455（0）** |
| `deletion_log` / `decision` | **193 / 3** | **193 / 3** |
| `user_version` / `quick_check` | **6 / ok** | **6 / ok** |
| 段 1 の 193 行の sha / 隠した 193 枚の sha / 判断 3 件の sha | `1f5991aaacd93e0a` / `e848d1c2ce5d70eb` / `3b784a039c7b49b6` | **同じ**（※下の注記） |
| 画像の署名（455 パスの `(size, mtime_ns)`） | `0183d290a5f9cbd3`（**生きた 299 場所・357.8 MB**） | **同じ** |
| `.data` の全ファイルの署名 | `faa4a9912cf02eab`（501 ファイル） | **同じ** |
| **`.backup/daily`** | `20261018` / `20261018-171143` / `20261019`（**3 件**） | **3 件とも消していない** |

**注記（署名の数え方）**: 「生きた 262 枚」は**資産**の数、「生きた 299」は**場所**（`asset_location`）の数
（1 つの資産が 2 か所にある物がある）。`sig.py` は**場所**で数えている。

- **複製は `sqlite3` の `backup()` で作った**（`.tmp-audit-redo/p9fix/real`。WAL を畳む。`cp` では判断が抜ける）。
  サーバは **`IMAGE_REVIEWER_DATA=<複製>`** を付けて **8791** に立て、**止める前に `/api/health` の
  `data_dir` が複製であることを確かめた**。**8790 は一度も止めていない**（打ったのは `GET /api/health` /
  `/api/stats` / `/api/assets` の 3 つだけ）。
- **画像は 1 枚も動かしていない。** `gui_layout --screen pending` は**本物の走査を 1 回打つ**ので、
  複製の DB に**未登録の画像 37 枚**が入る（**ファイルは読むだけ**。行が増えるだけ）。
  実データの画像の署名は変わっていない（上の表）。

## 5. 残した物・見送った物（理由つき）

1. **D-10（`temp_store` の振る舞いの試験）は見送った。** 理由: `TMP` / `TEMP` を「書けない所」に
   向けても SQLite は**カレント（`.`）に落ちる**ので、pytest の中で「一時 b-tree が作れない」を
   決定的に作れない（**実測**。`.tmp-audit-redo/p9fix/probe_temp_store.py` と、新しいプロセスで
   `TMP`/`TEMP` をファイルに向けた追試）。P9 で 500 になったのは**エージェントの sandbox が
   書ける所を全部塞いでいた**ためで、その再現には sandbox が要る。**代わりに** `/api/stats`（D-6）と
   `state=kept`（C-3②）の実測を厚くし、`tests/test_db.py` の docstring に理由を残した。
   **M1 / M2（pragma を外す壊し試験）は今までどおり落ちる。**
2. **G-3（一覧 API のキーセット改ページ）は持ち越した。** 段を立てるのは利用者の判断で、
   §12.1 に「必要な条件」と「`/api/stats` も一緒に」を書いた（コードは変えていない）。
3. **`cache_size` は入れないまま**（C-1 の推奨どおり）。**理由は「速さの実利が無い」だけ**に直した。
4. **`gui_layout --screen tags` の前提（語を入れる）はコードでは直していない**——実データに語が
   0 件なのは仕様なので、回す前に `tools/gui_layout_seed.py --tags` を当てる（README に書いた）。
5. **`.tmp-audit-redo/p9fix/`（使い捨て）を残した**（複製・合成 1 万枚・計測の生ログ・脚本。
   監査が `probe_p9.py` を回し直せるように）。**`backups-library`（284.2 MB）は測った後に消した**
   （残り 89.1 MB）。**`%USERPROFILE%` の下には何も作っていない**（`gui_layout` の Chrome プロファイルは
   `%TEMP%`、私の Chrome 計測は `.tmp-audit-redo` の中）。**8791 のサーバは止めた**
   （止める前に `/api/health` の `data_dir` が複製であることを確かめた）。
6. **並行して入った「ワーディング監査」の差分で、`gui_smoke` の期待値がまだ追いついていない。**
   私の変更を入れた時点（03:0x）は **333 ok / NG 0**。その後に `compare.js`（「一部不明」→
   「一部が分からない」など）・`pending.js`（「3 実削除」→「3 実体を消す」、「印」→「許可」）・
   `settings.js`・`duplicates.js` の文言が変わり、**その担当が検査の期待値を更新する前の状態**では
   **26 件 NG** になる（**私の 9 件の新しい検査は全部 ok**。NG は全部その担当の差分の語を見ている物）。
   **私はその 26 件の期待値を書き換えていない**（その担当の仕事で、同時に触ると衝突する）。
   `gui_layout` の側は、**私の検証を通すために 2 か所だけ両方の語を受ける形にした**（§3 の表）。
   **この文書の「333 ok」は私の変更を入れた時点の実測**である。

## 6. 設計とのずれ（この直しで新しく出た物）

| ずれ | 判断 |
| --- | --- |
| 既存の試験 `test_an_error_that_is_not_corruption_is_not_reported_as_a_broken_db` の `database is locked`（500 を期待）を**外した** | **意図した変更**（D-2。503 `busy` にするのが監査の推奨）。**同じ試験の `unable to open database file` と `IntegrityError` はそのまま**（500 のまま） |
| `disk i/o error` を `CORRUPTION_WORDS` から外したので、**「壊れている」の語彙が 1 つ減った** | 意図した変更（D-1 / G-6）。**復元を勧める語を減らす方向**なので安全側 |
| 上部バーが `code` で読み取り専用を判定するようになった（前は 503 なら全部） | **D-1 / D-2 の副作用**を直した物。`frontend-design.md` §6 に書いた |
| `probe_p9.py` の `?state=kept` は**0 件なら落ちる**ようにした | 計測の空振りを防ぐ（監査 C-3② の再発防止）。**目標に届かない 4 行は今までどおり落ちる**（一覧の 3 変種と `tag`） |
