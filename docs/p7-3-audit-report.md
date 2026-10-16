# P7-3（監視の最小形と結果の紐付け。合格の門＝線 6）監査報告 — 実行込み

- 日付: 2026-10-17（00:53〜01:20 JST）／指示書: `docs/p7-audit-brief-p7-3.md`（Orca で同じ依頼が 2 回届いた。2 回目の観点 (6) 出力先の推定と登録ルート・(7) 複製の `recipe_record` も含めた）／実装の記録: `docs/p7-3-implementation.md`（00:46）
- 対象（commit **43a8325** ＋ **b6cb78a**）: `src/image_reviewer/watcher.py`（**読んだのは 00:37 の 723 行版**）・`api/watcher.py`（37 行、00:27）・`api/recipes.py`（00:27）・`recipe_export.py`（00:34）・
  `tests/test_watcher.py`（478 行・18 件、00:38）・`tests/test_watcher_api.py`（150 行・5 件、00:39）・`tools/probe_p7.py --watch`（00:42）・設計 `docs/p7-design.md` 1,029 行（00:15）
- **監査中に実装者が P7-4 に着手した**（未コミット。`docs/p7-4-implementation-brief.md`）: `watcher.py` 00:56:37（725 行。差分は `recipe_export_result.fetched` を INSERT と一覧に足しただけ）・`db.py` 01:00:44（`_top_up_v6` で `fetched` 列を後から足す）・`tests/test_db.py` 00:57（+49 行）。
  8793 のサーバ（00:56:22 起動）は**コミット済みの木**で動いた（一覧の結果に `fetched` が無い）。再起動の検査（8797、01:1x）と自前のサービス層の検査は**作業中の木**で動いた。両方で同じ結論になる（下の A は `fetched` と無関係）。pytest 392 × 3 はコミット済みの木。
- 環境: 実データ `.data`（v6・263 枚・判断 3 件・`recipe_record` 0・`watcher_state` 0・`recipe_export_result` 0・根 2 本）は `mode=ro` だけ。複製は `backup()` で `.tmp-audit-redo/p73/{data-http（8793 → 8797）, judge/data（probe --watch）, svc/*（サービス層）}`。
  **ComfyUI（8188・0.39.2）へは GET だけ**（`/api/jobs` 一覧 15 本・詳細 431 本・`/internal/folder_paths`。`POST /prompt` は 0）。利用者のアプリ（8790、PID 48228）は触っていない。
- 触っていないもの: `.data`（`db.sqlite3` 10-15 14:29:51 のまま。**`-wal` は 01:00:59 に動いた**が私ではない——私の接続は全部 `mode=ro` か `IMAGE_REVIEWER_DATA` の複製で、行数と根は上のとおり不変。`db.py` 01:00:44 の作業と同時刻）、`src/`、`.backup/`、利用者の ComfyUI の `output/`（`.result.json` 0 個）。

## 判定: **直してから次へ**

**線 6 そのものは通る**: `probe_p7.py --watch` を複製で回し、印つき 2 枚が `matched_by='marker'`・`same_hash` 1/0・`seed_changed` 0/1・印なし 0 行・タグ付け job の詳細取得 0 回（`watch.out.txt`）。
本物の `/api/jobs` の形（一覧に `workflow` 無し・`create_time` ms・`subfolder` は `ComfyUI\Anima\20261010` のバックスラッシュ・`execution_cached` は `["execution_cached", {"nodes": ["1","2",…]}]`・`outputs` は `{"11": {"text": […]}, "17": {"images": […]}}`）と実装の読み方は一致する。
守り（403 / 422）・合否（human だけ・上書き・`verdict_at` / `verdict_actor`・記録は不変）・`GET` と監視 1 周期の無副作用・pytest 392 × 3・同時投入のテスト × 10・gui_smoke 129・gui_layout 6 画面も緑。

落ちているのは**既読の規律**で、指示書 (2) が名指しした 3 点（**1 周期 20 枚・詳細が取れない job を既読にしない・再起動**）が自分の実行で破れた。設計 §0.9 の「取り込むもの」①〜③（英訳の捕獲）も無い。

### 最も重大な 3 件

| # | 何 | 再現と値 | 場所 |
| --- | --- | --- | --- |
| **A-1** | **既読が未処理の job を追い越して、古い job を永久に取り落とす**（20 枚の上限でも、詳細の失敗でも） | (a) 新しい job 25 件 → 1 周期目 20 行、2・3 周期目 0 行、**合計 20（25 が正）**。基準は最新の job に跳ぶ。(b) 古い job の詳細だけ失敗・新しい job は成功 → 次の周期で直しても**古い物は拾われない**（行 1、2 が正）。`watch_checks.out.txt` | `watcher.py:290-293`（`picked` は新しい順）→ `:296` `picked[:MAX_PER_CYCLE]` は**新しい 20 件**→ `:308,:314` `newest = max(...)`。`:303-304` の `continue` は他の job が `newest` を進めるのを止めない。§0.9「失敗の扱い: 次の周期で再試行」に反する |
| **A-2** | **プロセスを立て直すと `GET /api/watcher` が 500**（`watcher_state` の行があれば必ず）。§4.3 の「起動時に `enabled` を 0 に戻す」も無い | 8797 で再起動 → `GET /api/watcher` **500**、ログ `AttributeError: 'ComfyWatcher' object has no attribute '_out_dir_cache'`。行の `enabled` は 1 のまま。`restart.out.txt`。サービス層でも同じ（`watch_checks.out.txt` (c)） | `_out_dir_cache` は `start()`（`:199`）でしか作られず、`status()`（`:175`）と `poll_once()`（`:278`）が読む。`app.py` に `enabled = 0` の 1 行が無い（§4.3「P7-3 で実装」・§8.1 の 21） |
| **A-3** | **§0.9「取り込むもの」①〜③ が無い**（`TextGenerate` の出力＝英訳・`final_prompt` の再構成・環境の写し）。記録は `approx` のまま | job の `outputs["11"]["text"]` に英訳を入れて 1 周期 → 記録は `status=approx`・`final_prompt=None`・`captured_text=None` のまま。`texts` は `bool(prov.get("info"))`（`:506`）＝「グラフがある」の意味で 1 になる。本物の job にも `outputs["11"]["text"]` が出ている（`real_jobs.out.txt`） | `watcher.py` に `capture.py` を使う所が無い。§0.2 で監視を P7 に入れた理由 1（英訳は実行の瞬間にしか無い）、線 2 の注記「監視で英訳を捕まえて `exact` に上がる」が成り立たない。記録は黙っている |

---

## A. 直っていない／設計の約束が成り立たない（必ず直す）

### A-1 既読が未処理の job を追い越す

- 再現: `python .tmp-audit-redo/p73/watch_checks.py` の (a) と (b)。偽の ComfyUI はテストの `FakeComfy`。
- 直し方: `picked` を**古い順**に処理し、`newest` は**途切れなく処理できた所まで**しか進めない（失敗・上限超えの最初の job の `create_time - 1` で止める）。`_seen` はそのまま。
  テスト: 25 件 → 2 周期で 25 行、詳細 1 件失敗 → 次の周期で拾う（§8.1 の 20 の後半「失敗した job は既読にしない」には**テストが無い**）。

### A-2 再起動で 500・`enabled` が 1 のまま

- 再現: `python .tmp-audit-redo/p73/restart_check.py`（複製の行を `enabled=1` にして uvicorn を立て直す）。`POST /api/watcher/start` を 1 回打つと `_out_dir_cache` ができて以後は 200。
- 直し方: `__init__` で `self._out_dir_cache = None`、`status()` は設定か推定を読む。`app.py` の起動時に `UPDATE watcher_state SET enabled = 0`（§4.3）。テスト: 新しい `ComfyWatcher` を同じ `Store` に作って `status()`。

### A-3 英訳の捕獲が無い

- 再現: `watch_checks.py` の (f)。
- §0.9 の表「取り込むもの」は ① `TextGenerate` の出力（**由来を結線で確かめる**。`capture.py`）② `final_prompt` の再構成 ③ 環境の写し ④ sidecar。実装は ④ だけ（しかも B-1 の形）。
  P7-3 の記録にも申し送りにも無い。**この段で入れるか、§9 に「P3 で」と明記して線 2 の注記を直すか**（G-1）。

## B. 重大

### B-1 sidecar を**利用者の ComfyUI の出力フォルダ**に新しい形（`<name>.result.json`）で書く。`<data>/sidecar/<sha256>.json`（既存の形）は書かない

- `watcher.py:568-584`。`watch.out.txt` と `svc/*/output/repro-*/` に `.result.json` が並ぶ。§0.11「sidecar は**形を変えない**」、§2.4「監視が書く欄は既にある（`capture.py` の `write_sidecar`）」。
  実装者の決定 7「sidecar は結果の隣」→ **変更を勧める**（利用者の出力フォルダに書くのは §19.3-10「ルート外を触らない」とも衝突する）。

### B-2 開始時に出力フォルダを**黙って**登録ルートに足す

- 8793 で `POST /api/watcher/start` → 複製の `root` が 2 → 3（`C:\ai\ComfyUI_windows_portable\ComfyUI\output`。729 ファイル）。`watcher.py:211-212,:240-248`。
  §0.9 は「**1 回だけ利用者に確認**」。確認の口も画面も無く、次の走査で 729 枚が取り込まれる。設定 `comfyui.output_dir` があるときはそれを使う（(6)）ことは確認した。

## C. 中程度

- **C-1** 手で紐付ける口は束の**最小の seed の export** に固定で付く（`_export_of` の `ORDER BY COALESCE(seed,'') LIMIT 1`。`:635-643`）。seeds `["5","1"]` で付いたのは seed 1。呼び手が選べない（G-3）。
- **C-2** 合否を `note` 無しで上書きすると前の `note` が消える（`:630-632`。HTTP で `close/近い` → `different/違う` → `same` で `note=None`）。
- **C-3** `_seed_of_graph` は**辞書順で最初の `KSampler`**（`:714-723`）。書き出しは主の `KSampler` だけ seed を書き換える（P7-2）ので、`KSampler` が 2 つのグラフで比べる相手を間違え得る。`analyze_graph` の `primary_ksampler` を使う。
- **C-4** 監視 1 周期は**一覧を 5 本**引く（`completed` ＋ `failed` / `cancelled` / `pending` / `in_progress`。本物で 30.4 ms）。§7 は「一覧 1 回・50 ms」。目標内だが設計と違う（E-4）。
- **C-5** 未完了が終わった次の周期で、基準が**既に処理した job まで進まない**（`clamp_positive.out.txt`: 基準 T+999 のまま。`_seen` にある job は `picked` に入らず `newest` を動かさない）。再起動後に 1 回だけ余分な詳細 GET が出る（行は増えない）。
- **C-6** `GET /api/watcher` の `last_error` は常に `null`（`:165`。`poll_once` は `counters["error"]` を作るが捨てる）。§0.9「`watcher_state` にエラーを残さない」と §3.4 の `last_error` が矛盾。画面は「繋がらない」を知れない。

## D. 軽微

- **D-1** `attach` の `client_token` を**結果 id として**引く（`:600-602`）。再送が 200 になるのは `(export_id, result_asset_id)` の重複判定のおかげ。
- **D-2** 出力先の無い環境で `start` → `GET` は `output_dir: null` だが、`/view` の取り込み先（`<data>/results/`）を画面に知らせる欄が無い（`fetched` は結果側）。
- **D-3** `poll_once` の例外は `_loop` が黙って捨てる（`:263-264`）。ログも `last_error` も無い。
- **D-4** `start {base_url}` は任意の URL を受けて GET する（ローカル道具なので許容。設計どおり）。
- **D-5** 確かめた結果、問題なし: `subfolder` のバックスラッシュ正規化（本物の値で）／`execution_cached` の形と「保存ノードが含まれるか」の判定（本物 429 件で 0 件が該当＝当たる job は無く、偽で 1 件）／タグ付け job は詳細を取らない（本物の一覧 200 件中 198 件が `outputs_count: 0`）／
  `outputs_count > 0` の job だけ詳細（本物 2 件）／繋がらない周期で基準が動かない（X6 で落ちる）／`>` の境界（X2 で落ちる）／`in_progress` が完了より古いとき基準が止まる（`clamp_positive.out.txt`）／
  同じ sha256 の結果は**既存の asset に場所が足される**（asset 1 のまま、`result_asset_id` は元の画像）／`/view` の取り込みは `<data>/results/<sha256>.png` に原子的（`.part` → `replace`）／`ux_result_asset` で二度登録しない／
  `GET /api/watcher` × 4 と `GET …/exports` で複製のファイルと行は不変、監視 6 秒で変わるのは `watcher_state` の行だけ／`start` と `stop` は冪等（200）／死んだ port への `start` は 200 で基準は「いま」／
  `Host: evil`・`text/plain`・`agent`・ヘッダ無しは 403、`robot` は 422（start / stop / results / verdict の 4 口）／`verdict` の語彙外 422・知らない束と結果 404／結果ゼロの束でも一覧は壊れない／
  `infer_output_dir` は本物の `/internal/folder_paths` から `C:\ai\ComfyUI_windows_portable\ComfyUI\output` を当てる／実データの `recipe_record` / `watcher_state` / `recipe_export_result` は 0 行のまま。

## E. 設計とのずれ

| # | 何 | 設計 | 実装 | 判定 |
| --- | --- | --- | --- | --- |
| E-1 | sidecar | §0.11 / §2.4: `<data>/sidecar/<sha256>.json`（形を変えない） | 出力の隣に `<name>.result.json` | 変更を勧める（B-1） |
| E-2 | 登録ルートへの追加 | §0.9: 1 回だけ利用者に確認 | 黙って足す | 今直す（B-2。確認の口が無いなら、少なくとも `start` の応答と画面に出す） |
| E-3 | 起動時に `enabled` を 0 | §4.3 | 無い | 今直す（A-2） |
| E-4 | 1 周期の一覧 | §7: 1 回 | 5 回 | 設計を実装に合わせる（§0.9 自身が `failed` / `cancelled` / 未完了を別に引けと言っている） |
| E-5 | 英訳の捕獲 | §0.9「取り込むもの」①〜③ | 無い | A-3 / G-1 |
| E-6 | 記録が引く §3.6〜§3.8 | **設計に §3.6 以降は無い**（§3.5 まで。手で紐付ける口は §0.15 の 5 行目と §3.1 の表だけ） | — | 設計に §3.6（手で紐付け・合否の口の形と応答）を足す |
| E-7 | `last_error` | §3.4 にある、§0.9 は残さない | 常に `null` | §3.4 を直すか、プロセス内の値を返す（C-6） |

実装者が自分で決めた 8 点:

| # | 決めたこと | 判定 | 根拠 |
| --- | --- | --- | --- |
| 1 | `create_time` は `>`、同じ ms は `_seen` | 妥当 | X2（`>=`）で落ちる。ただし再起動後の同じ ms の 2 件目は A-2 で試せなかった（H） |
| 2 | `start(run=False)` | 条件付き | テストと道具のためだけに本番の経路と違う形を置くと、**周期（スレッド）を回すテストが 1 つも無い**（X15 の二重起動が緑）。`run=True` で `interval=0.01` の 1 本は置く |
| 3 | 一覧が空なら基準は「いま」 | 妥当 | 死んだ port でも同じ（8793 で確認） |
| 4 | `_touch(None)` は基準を動かさない | 妥当 | X6 で落ちる |
| 5 | 結果の登録は同じ束・同じ画像を弾く | 妥当 | 同じ sha256 で 1 行 |
| 6 | 指標が取れなくても登録 | 条件付き | 妥当だが、X9（指標を全部捨てる）が緑＝指標の値を見るテストが無い |
| 7 | sidecar は結果の隣 | **変更を勧める** | B-1 |
| 8 | `marker_skip_reason` は設計のまま | 妥当 | P7-2 の値 |

申し送り 5 件: (1) 8790 の再起動は利用者の判断（A-2 を直してから）。(2) 設定の値は読まれている（`output_dir_inferred=false`）。(3) 再起動で止まる方針は**実装されていない**（A-2）。(4) `fetched` は作業中の木で**既に足されている**（下の G-5）。(5) `/object_info` を引かないことは中継ログ相当で確認（監視の GET は `/api/jobs*` だけ）。

設計の穴 3 件: (1) ファイル名だけに印: **実害なし**（本家の `SaveImage` は `a/b` を必ず `subfolder=a` に分ける。当たらないのは独自の保存ノードだけで、その場合の PNG の保険には**テストが無い**（X12 が緑））。(2) `fetched` 列: 方針は**よい**。ただし `_top_up_v6` の `ALTER TABLE … ADD COLUMN fetched INTEGER NOT NULL DEFAULT 0`（`db.py:544`）には新規 DDL（`:644`）の `CHECK (fetched IN (0, 1))` が無く、**同じ v6 で形が 2 つ**になる（罠 13）。`ADD COLUMN` は `CHECK` を持てるので付ける。(3) §8.1 に `/view` の行を足す: 同意。

## F. テストで守れないもの

壊し方 15 通り（`.tmp-audit-redo/p73/mutate_watch.py`、`mutations.out.txt`）:

| 壊し方 | 落ちたテスト | 判定 |
| --- | --- | --- |
| X1 `_seen` を無くす | **0** | 同じ ms の 2 件目を守るテストが無い（基準が `>` なので通る） |
| X2 `>` を `>=` に | 1 | 守れている |
| X3 `outputs_count` の絞りを外す | 1 | 守れている |
| X4 未完了の clamp を外す | **0** | `test_an_unfinished_older_job_holds_the_baseline` は**未完了が完了より新しい**ので clamp が効かなくても通る（空振り）。私の `clamp_positive` の形（未完了が古い）に直す |
| X5 cached を常に偽 | 1 | 守れている |
| X6 不通で基準を進める | 1 | 守れている |
| X7 照合が seed を見ない | **0** | 束に seed 1 つのテストしか無い |
| X8 バックスラッシュを直さない | 1 | 守れている |
| X9 指標を全部捨てる | **0** | `ssim` などの値を見るテストが無い |
| X10 `seed_changed` を常に偽 | 1 | 守れている |
| X11 `same_hash` を常に 0 | 2 | 守れている |
| X12 PNG の `prompt` の保険を外す | **0** | 保険の経路にテストが無い（指示書 (4)） |
| X13 `/view` の取り込みを外す | 1 | 守れている |
| X14 合否を上書きしない | 2 | 守れている |
| X15 二重起動で周期が 2 本 | **0** | `run=False` しか使わないのでスレッドが走らない |

テストの無い経路: A-1 の 2 つ（上限超え・詳細の失敗）／A-2（再起動の `status()`・`enabled` を 0 に）／A-3／B-2（根の追加）／C-2（`note` の消失）。
§8.1 の対応: 18 ✓・19 ✓・20 前半 ✓ 後半 ✗・21 ✗（実装も無い）・38 ✓・39 **空振り**・40 ✓（probe）・`/view` ✓（表に行を足す）。
揺れ: pytest 392 を 3 回、`test_two_posts_at_once_do_not_fail` を 10 回、すべて緑（`pytest3.out.txt`・`conc10.out.txt`）。

## G. 依頼者への質問（推奨つき。待たずに推奨で進める）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | 英訳の捕獲（§0.9 ①〜③） | (a) P7-3 の直しで入れる（`capture.py` の由来判定を job の `outputs[*].text` に当て、`captured_text` / `final_prompt` を埋めて記録を `exact` に上げる） (b) P3 に送り、§9 と線 2 の注記を直す | **(a)**。材料は `capture.py` にあり、本物の job に `text` が出ている。これが無いと ja2en の記録は永久に `approx` |
| G-2 | sidecar の置き場 | (a) `<data>/sidecar/<sha256>.json` を `capture.write_sidecar` で（結果の欄を `extra` に足す） (b) 今の `.result.json` を `<data>/results/` 側だけに (c) 今のまま | **(a)** |
| G-3 | 手で紐付ける口の seed | (a) 本文に `seed?` を受け、無ければ束に export が 1 つのときだけ通す（複数なら 422） (b) 今のまま最小の seed | **(a)** |
| G-4 | 根の追加の確認 | (a) `start` の応答に `root_added` を返し、画面で 1 行出す（P7-4）。設定 `comfyui.add_root=0` で止められる (b) 根に足さず `/view` の取り込みに統一 | **(a)**。(b) だと 729 枚の複製が `<data>/results/` に増える |
| G-5 | `fetched` 列（穴 2） | (a) 作業中の `_top_up_v6` で行く。`ADD COLUMN` に `CHECK (fetched IN (0,1))` を付け、`test_db.py` に「古い v6 に列が足される・新規と `PRAGMA table_info` が一致」を 1 件 (b) v7 に上げる | **(a)** |
| G-6 | 既読の進め方（A-1） | (a) 古い順に処理し、途切れた所で止める（上限も失敗も同じ規則） (b) 上限は撤廃 | **(a)** |
| G-7 | P7-4 に着手済みだが A-1〜A-3 を先に入れるか | (a) A-1〜A-3 と B-1 / B-2 を P7-3 の直しとして先に入れ、再確認してから P7-4 | **(a)**。画面（P7-4）は `GET /api/watcher` を使うので A-2 を先に |

## H. 確かめられなかったこと・証拠の注記・後始末

確かめていないこと:
- **本物の印つき job**（生成が禁止なので合成のみ）。本物で確かめたのは一覧・詳細・`execution_cached`・`subfolder`・`outputs` の形と、タグ付け job の比率。
- `execution_cached` に保存ノードが入る**本物の job は 429 件中 0 件**（形は本物、判定の正例は偽で）。
- 再起動後の「同じ ms の 2 件目」（A-2 の `AttributeError` で実行できず）。
- 周期スレッド（`run=True`）の長時間運転（8793 で 6 秒だけ）。
- `recipe_export.py` の P7-3 差分（`exports` に `results`）は HTTP で結果が出ることだけ確認。

紛らわしい出力:
- `watch_checks.out.txt` の (d) 1 回目は元画像を偽の sha で登録していたので `assets=2`。本物の sha で取り直した (d) が正（`watch_checks2.out.txt` 末尾）。(h) 1 回目は出力フォルダが無かったので根が足されなかった。取り直しで足される。
- `watch_checks2.out.txt` の前半は `import` で (a)〜(i) が再実行された写し。
- `http_checks.out.txt` の「files/rows changed by ~6 s of polling」の `root (2,3)` は B-2、`watcher_state (0,1)` は開始の行。
- `.data/db.sqlite3-wal` の 01:00:59 は実装者の作業（上の環境欄）。

回帰: pytest **392 × 3**・同時投入 × 10・gui_smoke **129**・gui_layout **6 画面**（8793。`GET` の無副作用の後に、複製へまとまり 1 つと語 4 つを入れて実行）すべて ok。

後始末: 止めた: 8793（PID 38732）・8797（restart_check が自分で止めた）。残した: `.tmp-audit-redo/p73/`（複製 `data-http`・`judge/`・`svc/` 11 個・スクリプト・`*.out.txt`・`jobs_*.json`・`server*.log`）。利用者の ComfyUI の `output/` には何も書いていない（`.result.json` 0）。

実行したコマンド（`cd C:\work\image-reviwer`、`$env:UV_CACHE_DIR`、`PYTHONUTF8=1`）:

```
uv run --no-sync pytest -q（× 3）／ uv run --no-sync pytest -q tests/test_recipe.py::test_two_posts_at_once_do_not_fail（× 10）／ node tools/gui_smoke.mjs
uv run --no-sync python tools/probe_p7.py --watch --keep --data .tmp-audit-redo/p73/judge/data        # 線 6
python .tmp-audit-redo/p73/real_jobs.py 相当（real_jobs.out.txt / cached_scan.out.txt）                   # 本物の形（GET だけ）
python .tmp-audit-redo/p73/watch_checks.py                                                             # (a)〜(i)
python .tmp-audit-redo/p73/clamp_positive.py 相当（clamp_positive.out.txt）
PYTHONPATH=.tmp-audit-redo/p73 P73_MUTATION=X1_no_seen_set python -m pytest -q -p mutate_watch tests/test_watcher.py tests/test_watcher_api.py   # X1〜X15
IMAGE_REVIEWER_DATA=.tmp-audit-redo/p73/data-http uv run --no-sync image-reviewer serve --port 8793 → python .tmp-audit-redo/p73/http_checks.py 8793
MSYS_NO_PATHCONV=1 node tools/gui_layout.mjs --base http://127.0.0.1:8793 --count 8 / --screen requests / --screen group --group 01M52Q39968RFSQRGCG2XNSKES / --screen asset --ids 01M4Z0KJS58V2SAJBGTG1TRFK5 / --screen tags / --screen jobs
python .tmp-audit-redo/p73/restart_check.py                                                            # 8797 で再起動
```

## 最も重大な 3 件（再掲）

1. **A-1** 既読が未処理の job を追い越す: 25 件で 20 件しか登録されず、詳細が 1 回失敗した job は永久に拾われない。`watcher.py:290-314`。古い順に処理し、途切れた所で基準を止める。
2. **A-2** 再起動で `GET /api/watcher` が 500（`_out_dir_cache` 未初期化）、`enabled` が 1 のまま（§4.3 の 1 行が無い）。
3. **A-3** §0.9「取り込むもの」①〜③（英訳の捕獲・`final_prompt`・環境）が無く、ja2en の記録は `approx` のまま。`texts` は「グラフがある」を数えている。
