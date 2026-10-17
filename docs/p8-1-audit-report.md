# P8-1 監査報告（重複の検出と整理。合格の線 1〜3）— 実行込み

- 日付: 2026-10-17（JST 22:30〜23:00）
- 指示書: `docs/p8-audit-brief-p8-1.md`。実装の記録: `docs/p8-1-implementation.md`（81 行）。P8-0 の仕分け: `docs/p8-0-audit-triage.md`（13 行）。
- 対象（コミット `fe343fb`、22:27:08。12 ファイル +1492/-4）: `src/image_reviewer/duplicates.py`（445 行。新規）、`src/image_reviewer/api/duplicates.py`（70 行。新規）、
  `src/image_reviewer/api/__init__.py`（+13。`duplicates_of` / `require_human`）、`src/image_reviewer/app.py`（+7）、`src/image_reviewer/store.py`（+5。`set_hashes` が帯も書く）、
  `src/image_reviewer/db.py`（+9/-4。`_top_up_v6` の先頭で `V6_DELETE_DDL`）、`tests/test_db.py`（+132/-4。F-1 の書き直し＋ F-2 / C-1 の 2 件）、`tests/test_duplicates.py`（336 行・16 件。新規）、`tools/probe_p8.py`（179 行。新規）。
  監査中に対象の `git status` は空のまま（本報告だけが untracked）。
- 設計の版: `docs/p8-design.md` 837 行（`35bfc44` のまま。P8-1 で変更なし）。
- 環境: `uv run --no-sync`。SQLite 3.53.1・Python 3.14.7。実データ `.data` は `mode=ro` と `backup()` の複製だけ。
  複製は `.tmp-audit-redo/p8-1-audit/`（`data/`・`gui/`・`synth/`・`synth10k/`・スクリプト 7 本・出力 7 本）と、`probe_p8.py --keep` が残した `.tmp-audit-redo/p8probe/data/`。
  サーバは複製 `gui/` で **8791**（`IMAGE_REVIEWER_DATA` を付けて起動。PID 28600。終了後に `netstat` で 0 本を確認）。**8790 は止めていない**（監査の前後で `health` 200）。ComfyUI は触っていない。
- 触っていないもの: `src/`・`tools/`・`tests/`・`schemas/`・`docs/`（本報告以外）・`.backup/`・`.data/`（`db.sqlite3` 1,265,664 B・03:24:06、`-wal` 251,352 B・21:33:46 のまま。
  監査の最後に `mode=ro` で読み直して **v6・263 枚・判断 3 件・pHash 91・帯 0・除外 0・job 0**）。コミットしていない。
- 回帰: **pytest 314 passed × 3 回**（13.94 / 13.84 / 13.76 s。揺れなし）、**gui_smoke 129 ok / NG 0**、**gui_layout 6 画面すべて ok**（比較・要求・まとまり・注記＋タグ・語の一覧・ジョブ。各 3 窓）。

## 判定: **合格（条件つき）**

線 1〜3 は**私の手で通った**。`probe_p8.py` を複製で回し、**202・263 枚・pHash 91 → 263・帯 2104 行・≤3 が 17 群 / 39 枚・≤6 が 21 群 / 57 枚・≤10 が 28 群 / 87 枚・完全重複 0 群・除外 21 → 20 → 21・`GET` の前後で帯と pHash が不変**、
すべて実装者の記録と一致し、点検（`p8-review-report.md`）の総当たりの数とも一致する。帯は全 263 枚で `bands_of(phash)` と同じ、帯 0 と帯 7 だけ一致する組も候補に入る（境界は落ちない）。
本物のサーバで 403 / 422 / 405 の表どおりに守られ、`POST /api/groups` の `kind='duplicates'` で群からまとまりが作れる（線 3 は既存の口で通る）。P8-0 の条件 3 件は**前回緑だった壊し方 11 通りが全部落ちる**ようになった（C-0）。

条件は 3 つ。(1) **帯索引の取りこぼし 0 が成り立つのは距離 7 まで**で、API は 0〜64 を受け、Q3 は ≤10 を画面の選択肢にしている（B-1）。
(2) **ハッシュの背景ジョブは HTTP から中断できない**（`POST /api/jobs/{id}/cancel` は別のサービスの印を立てる。C-1）。
(3) **設計 §7 が P8-1 に課した「辞書の帯で 1 万枚を測る」が未実施**で、いまの SQL の自己結合は 1 万枚で総当たりと同じ速さ（C-2）。

**最も重大な 3 件**

1. **B-1 取りこぼし 0 の保証は距離 7 まで。API は 64 まで受け、Q3 の ≤10 はたまたま通っている。** 8bit × 8 本の帯で「1 本は完全に一致する」のは**距離 ≤ 7** のとき（鳩の巣）。
   実データ（`bands_check.py`）: **≤10 までは 88 / 88 組で取りこぼし 0**（28 群 / 87 枚は正しい）が、**≤12 で 125 組中 3 組・≤16 で 326 組中 72 組を取りこぼす**。
   合成（距離 8 で各帯 1 ビットずつ違う 2 枚）は **≤10 でも候補に入らない**（群に出たのは距離 7 の別の枚が橋になったから）。
   `tools/probe_p8.py:59` の総当たりは **≤6 しか見ない**ので、記録の「取りこぼし 0」は ≤10 では確かめられていない。`duplicates.py:141` の `0〜64` を受ける判断（決定 4）はこの保証と両立しない。
   推奨は G-1（API は 7 までに締める。8 以上が要るなら 263 枚なら総当たりが 20 ms なので Python で総当たり。`probe` の総当たりを 10 まで）。
2. **C-1 ハッシュの背景ジョブは HTTP から中断できない。** `POST /api/jobs/{id}/cancel`（`api/tags.py:190`）は `JobService.cancel` で、`job.message` を「中断しています…」にして **`JobService._cancelled`** に印を立てる。
   `DuplicatesService._run`（`duplicates.py:324`）は**自分の `_cancelled`** しか見ない。`DuplicatesService.cancel`（`:308`）には**口が無い**（死んだコード）。
   実測（`http_check.py`）: `force` で 263 枚を投げて `cancel` → **200・`running`** → 1 秒後 **`done` 263 / 263**（止まらない）。`#/jobs` の中断ボタンを押した利用者には「中断しています…」と出て、そのまま終わる。
3. **C-2 1 万枚の測定が設計の宿題のまま。** 設計 §7 L661「Python で帯を辞書に載せる形にすると…P8-1 で測る」は未実施（記録は「未計測」）。私の合成 1 万枚（`synth10k.py`。実データ 263 の pHash ＋ ビット反転。帯 80,000 行）:
   **`candidate_pairs`（SQL）7.56 s（3 回の中央値）・`near_groups` 8.13 s・辞書の帯 1.13 s・int の総当たり 7.8 s**（3 つとも ≤6 の 67,705 組で一致）。
   **SQL の自己結合は総当たりと同じ速さ**で、帯索引の利得が出ていない（`duplicates.py:145-146` の候補ごとの相関サブクエリ 2 本が重い）。263 枚では 6 ms なので今は困らないが、§7 の記述を「SQL は 1 万枚で 7.6 s（合成）。辞書で 1.1 s」に直して、P8-5 までにどちらかを決める。

---

## A. 直っていない／設計の約束が成り立たない

- 無し。線 1〜3 は通り、P8-0 の条件 3 件は直った（C-0）。

## B. 重大

### B-1 帯索引の取りこぼし 0 は距離 7 までの保証（最も重大の 1）

- 場所: `duplicates.py:8-10`（docstring は「`d < 8`」と正しく書いている）・`:136-158`（`candidate_pairs`。`max_distance` 0〜64 を受ける）・`api/duplicates.py:34`・`tools/probe_p8.py:51-61`（総当たりは ≤6 固定）。設計 §0.14 Q3 L233（≤3 / ≤6 / ≤10）・§1.2 線 2 L349（「帯の候補＝総当たり」）・§0.16 L324（≤10 で 28 群）。
- 再現: `.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-1-audit\bands_check.py`。

| `max_distance` | 総当たり | 帯の候補 | 取りこぼし | 群 / 枚 |
| --- | --- | --- | --- | --- |
| 0 | 9 | 9 | 0 | 5 / 12 |
| 3 | 27 | 27 | 0 | 17 / 39 |
| 6 | 54 | 54 | 0 | 21 / 57 |
| 7 | 54 | 54 | 0 | 21 / 57 |
| 8 | 62 | 62 | 0 | 23 / 64 |
| 10 | 88 | 88 | 0 | 28 / 87 |
| **12** | 125 | 122 | **3** | 29 / 108 |
| **16** | 326 | 254 | **72** | 30 / 162 |

- 合成: `a5a5…` と `a4a4…`（各帯 1 ビット＝距離 8）は ≤10 でも候補に**入らない**。候補に入るのは距離 7 の `a4a4a4a4a4a4a4a5`（帯 7 が一致）だけ。
- 判定: 実データの ≤10 は**運よく**完全。利用者の画面は P8-5 までこの口に触れないので B に置く。直し方は G-1。

## C. 中程度

### C-0 確かめた結果、問題なし（1 行ずつ。実行したもの）

- **線 1〜3**（`uv run --no-sync python tools/probe_p8.py --keep`）: 263 枚 / pHash 91 / 帯 0 → `start_compute` 202・`total=263`・`done`・**2.3 秒**・pHash 263（+172）・帯 2104 行（+2104）／帯 54 組＝総当たり 54 組（7 ms）／**≤3: 17 群 / 39 枚・≤6: 21 群 / 57 枚・≤10: 28 群 / 87 枚**／完全重複 0 群（1 行の説明つき）／除外 21 → 20 → 21・同じ群か True → False → True／`GET` 前後で帯 2104・pHash 263。**すべて OK**。
- **帯の作り方**: 263 枚すべて `phash_band` の 8 行が `bands_of(phash)` と同一。候補（距離を取る前）2,152 組 ＝ 34,453 組の 6.2 %（点検の実測と同じ）。帯 0 だけ一致・帯 7 だけ一致の合成の組は ≤64 で候補に入る（境界は落ちない）。
- **「帯 0 固定」は本当に落ちる**: `candidate_pairs` の結合を `a.band = 0 AND b.band = 0` にする（N2）→ `test_the_band_index_never_misses_a_near_pair` と `test_the_new_duplicate_endpoints_are_guarded` の 2 件が落ちる。実装者の直し（違う帯のビットを 1 つずつ反転）が効いている。
- **代表の推薦**（§0.9。`bands_check.py` と `tests`）: keep が最優先（size が小さくても）、画素数 → サイズ → `mtime_ns` が新しい方 → `id` 昇順。同点の 2 枚（全部同じ）は `id` 昇順で `a`（決定的）。
- **守り**（本物のサーバ 8791。`http_check.py`）:

| 要求 | 結果 |
| --- | --- |
| エージェント / ヘッダ無しの `GET near` / `exact` / `exclusions` | 200 |
| エージェント / ヘッダ無しの `POST compute` / `exclude` / `exclude/remove` | **403 `human_only`** |
| `actor: robot` の `POST compute` | 422 |
| 人の `exclude` に `Host: evil` / `Content-Type: text/plain`、`compute` に `Origin: http://evil` | 403 |
| `exclude` で `a_id == b_id` / 空の本文 / 配列の本文 | 422 |
| `exclude` / `remove` で知らない id | 404 |
| `?max_distance=99` / `-1` / `abc`、`?limit=abc` | 422 |
| `DELETE /api/duplicates/exclude` | 405（本文は `POST …/remove`。§0.15-1 のとおり） |
| `POST compute` 2 本目（走行中） | **409** |
| `POST compute` 3 本目（計算済み） | 202・`total: 0` |
| `POST /api/groups {kind:'duplicates', policy:'pick_one', asset_ids:[群の 2 枚]}` | **200**・`kind: duplicates`（線 3 は既存の口で通る）。`kind:'duplicate'` は 422 |

- **Q2 との突き合わせ**: 設計 §3.1 L493-500 と §3.4 L544 は **`compute` と `exclude` を人だけ**（エージェントに許すのは削除と自分の `undo`）。実装は `require_human`（`api/duplicates.py:45, 53, 62`）で一致。**`GET` はエージェントにも開いている**（§3.1 のとおり）。
- **`GET` が書かない**（本物のサーバ）: `near`（≤6 と ≤10）/ `exact` / `exclusions` / `jobs` の前後で、複製フォルダの**全ファイルの size と mtime** と **`phash_band` / `duplicate_exclusion` / `job` / `job_item` / `asset` / `decision` の行数・pHash の枚数**が同一。
- **P8-0 の条件 3 件**（前回の plugin `mutate_p8.py` を `tests/test_db.py` に）: **M5**（`band` の `CHECK`）・M1b / M4b / M4c（`delete_request` の `stage` / `actor`・`duplicate_exclusion` と `pending_delete_preview` の `actor`）→ `test_v6_check_constraints_reject_the_wrong_vocabulary` が落ちる／**M14**（FK）・**M19**（主キー）・**M18a〜d**（平の索引 4 本）→ `test_v6_foreign_keys_and_indexes_are_declared` が落ちる／**M22**（`_top_up_v6` から `executescript(V6_DELETE_DDL)` を引く）→ `test_v6_tables_are_added_to_a_p7_style_v6_database` が落ちる。**11 / 11**（前回は全部緑）。
  `.backup/pre-p7-removal2-20261017-032405`（P7 の v6）の複製 → `migrate()` × 3 → **P8 の 5 表と 6 索引が入り**、新規との差は `recipe_*` の残骸 21 件だけ（前回は P8 の物が 16 件 MISSING）。
- **実データ**: `mode=ro` で監査の前後とも v6・263・3・**pHash 91・帯 0・除外 0・job 0**。`.data` の size / mtime 不変。`probe` も `mode=ro` でしか開かない（`tools/probe_p8.py:42`）。
- **`store.set_hashes` が帯を書く**: `compare.py:1010, 1025` の 2 か所は `set_hashes` 経由。上書きで古い帯が残らない（テストと `bands_check` の除外 x2 で確認）。
- **性能（263 枚）**: `near_groups` ≤6 **7 ms**（5 回の中央値）、`exact_groups` 0.1 ms、総当たり 34,453 組 **20 ms**。設計 §7 の「完全重複 100 ms 以内」「準重複 263 枚は未計測」は埋まった（記録は帯の候補 7 ms だけ）。
- **壊すと落ちる**（`mutate_p81.py` を `-p` で。ソースは触らない。29 通り）: **22 通りで狙ったテストが落ちた**（N1 / N2 / N3 / N4 / N5 / N6 / N7 / N8 / N9 / N11 / N12 / N13 / N15 / N18 / N19 / N23 / N24 / N25 / N26 / N28 / N29 ＋ P8-0 の M22）。残りは F。

### C-1 ハッシュの背景ジョブは HTTP から中断できない（最も重大の 2）

- 場所: `api/tags.py:190-192`（唯一の `cancel` の口 → `JobService.cancel`）・`jobs.py:200-211`（`message` を「中断しています…」にして **`JobService._cancelled`** へ）・`duplicates.py:308-322`（`DuplicatesService.cancel` / `_is_cancelled` は**自分の集合**。口が無い）・`:331`（`_run` が見るのはその集合）。
- 再現（`http_check.py` の `[cancel]`）: `POST /api/duplicates/compute {force:true}` → 202 `total 263` → すぐ `POST /api/jobs/{id}/cancel` → **200 `state: running`** → 1 秒後 `GET /api/jobs/{id}` → **`done` 263 / 263**「263 枚の pHash を計算しました」。
- 影響: `#/jobs` の中断は効かず、表示は「中断しています…」→「…計算しました」と嘘を経由する。`force` で 1 万枚を投げたら約 2 分止められない。
- 直し方: `JobService.cancel` が kind を見て `DuplicatesService.cancel` に委ねる（`app.state.duplicates`）か、**中断の印を `job` 表の列（または `message`）に置いて両方のスレッドが DB を見る**（プロセス再起動にも強い）。テストは `cancel` → `_run` が `cancelled` で止まる 1 本。`job_doc` の `counts: tagged/skipped/failed` はタグ付けの語彙で、ハッシュの job では常に 0 / 0 / 0（`failed` だけ意味がある。D-6）。

### C-2 1 万枚の測定（設計 §7 の P8-1 の宿題）が未実施。SQL の自己結合は総当たりと同じ速さ（最も重大の 3）

- 場所: 設計 §7 L661・§10-3 L769。`duplicates.py:143-152`（候補ごとに `phash` を相関サブクエリ 2 本で引く）・`:155`（文字列のまま `hash_distance`。§7 D5「先に `int(hex, 16)`」も未適用）。記録「設計の穴 2」は「未計測のまま」。
- 実測（`synth10k.py`。合成 1 万枚・帯 80,000 行・`PRAGMA temp_store = MEMORY`）:

| 方法 | ≤6 | 組 |
| --- | --- | --- |
| `candidate_pairs`（SQL の自己結合） | **7.56 s**（3 回の中央値） | 67,705 |
| `near_groups`（上＋連結成分） | 8.13 s | 224 群 / 6,162 枚 |
| 辞書の帯（`dict[(band, value)] → ids`。候補 2,440,251 組） | 候補 0.40 s・距離まで **1.13 s** | 67,705（SQL と一致） |
| int の総当たり（49,995,000 組） | 7.8 s | 67,705 |

- 判定: 点検 B6 の 2.2 s より悪いのは候補が密な合成だから（取りこぼし 0 は変わらない）。**263 枚では 6 ms で困らない**ので C。§7 の表を実測で埋め、**辞書の形に替えるか「SQL は 1 万枚で 7.6 s」を残すか**を P8-5 までに決める（G-2）。

### C-3 「書き手を 1 つにした」は成り立っていない

- 場所: `duplicates.py:353-355`（`_run` が `UPDATE asset SET phash = ?, dhash = ?` を**直に**書き、`write_bands` を呼ぶ）。`store.set_hashes`（`store.py:369-390`）の**検査（16 進 16 文字の小文字）を通らない**。
- 決定 1 は「`asset.phash` を書く道は必ず `set_hashes` を通る」と言うが、背景ジョブは通らない（書き手は 2 つ）。今は `hash_file` が正しい形を返すので帯は食い違わない。`_run` を `self.store.set_hashes(asset_id, phash, dhash)` に替えれば 1 行で決定 1 が本当になる。

### C-4 段 1（`deleted_at`）の枚が群に出る

- 場所: `duplicates.py:170-174`（`hashed` / `unhashed` は `deleted_at IS NULL` で絞る）と `:143-152`（`candidate_pairs` は絞らない）。
- 再現（`bands_check.py`）: 先頭の群の 1 枚に `deleted_at` を立てる → `hashed` 263 → 262 だが **群 21 → 21、その枚は群に残る**。§8-25（一覧の既定で出さない）は P8-2 だが、**同じ応答の中で数と中身が食い違う**ので今のうちに `candidate_pairs` にも `deleted_at IS NULL` を。

### C-5 `probe` の線 2 は ≤6 しか見ない・「202」は HTTP を通っていない

- `tools/probe_p8.py:59` の総当たりは `<= 6` 固定。≤10 は帯の群の数だけ（B-1 の根拠が無い）。`:84` の「`POST /api/duplicates/compute → 202`」は**サービスを直に呼んだ**表示で、HTTP の 202 は `tests/test_duplicates.py:297` だけが見ている（私は本物のサーバで 202 を確認した）。総当たりを `max(ALLOWED_MAX_DISTANCE)` まで回す。

## D. 軽微

- D-1 「8.6 ms/枚」（記録・コミットの文）は 2.3 s ÷ 263 枚。復号したのは **172 枚**（91 枚は帯を書くだけ）なので **13.4 ms/枚**＝点検の 14.0 ms と同じ桁。§7 の「14.8 ms/枚」と矛盾しない数に直す。
- D-2 `representative` の `reason`（`duplicates.py:123-132`）は**群の中で最初に違う属性**を言い、**決め手の規則ではない**。`A(100px, 10B)・B(100px, 20B)・C(50px, 30B)` → B（サイズで勝った）だが理由は「画素数が最大」。`width` が None の枚は 0 扱いで「画素数が最大」。画面に出す文なので、上位 2 枚を分けた規則を言う形に。
- D-3 `reject` された枚でも画素数が大きければ推薦になる（規則 1 は `keep` だけを見る）。§0.9「人が選んだ物」の読み方次第。`reject` を最下位に落とすか、設計に「reject は見ない」と 1 行。
- D-4 `?limit=-5` は 200 で 1 群（`duplicates.py:202` の `max(1, …)`）。`limit=0` も 1 群。422 にするか「1 以上」を docstring に。
- D-5 `DuplicatesService.cancel`（`:308`）・`wait`（`:394`）は口が無い（`wait` は probe とテストが使う）。C-1 を直すときに `cancel` を生かす。
- D-6 `job_doc` の `counts`（`jobs.py:50`）はタグ付けの語彙。ハッシュの job で `tagged: 0, skipped: 0` が出る。決定 3（成功を `job_item` に書かない）は妥当（`CHECK` は `ALTER` で変えられない）。
- D-7 `hash_distance` を候補ごとに文字列で呼ぶ（正規表現＋ `int` を 2 回）。§7 D5 のとおり先に `int` にすれば 263 枚でも 2,152 組で数 ms、1 万枚で 0.3 s 程度の差（C-2 の表の内訳）。
- D-8 `_asset_rows`（`:85-95`）の `size` / `mtime_ns` / `path` は `is_primary DESC, path` の先頭 1 か所。2 か所に生きている枚（`exact` の対象）では代表の規則 3・4 が主の場所だけで決まる。設計どおりだが注記を。
- D-9 `exclude` は `INSERT OR REPLACE` なので同じ組を 2 回除外すると `reason` / `at` / `actor` が**上書き**される（`bands_check` で確認）。履歴は要らない（§0.10）ので妥当。記録に 1 行。
- D-10 `near_groups` は `within = max(... for a, b, d in pairs if …)` を群ごとに全 pairs で回す（群 × 組）。263 枚では 7 ms なので今は困らない。

## E. 設計とのずれ（実装が決めた所を含む）

| # | 設計 | 実装 | 判定 |
| --- | --- | --- | --- |
| E-1 | §0.14 Q3 L233「≤3 / ≤6 / ≤10 を切り替え」・§1.2 線 2「帯の候補＝総当たり」 | `max_distance` 0〜64（決定 4） | **B-1**。保証は 7 まで。G-1 |
| E-2 | §0.5 L101-102「帯は `compare.capture_hashes` / `ensure_hashes` の隣に 1 手」 | `store.set_hashes` の中（決定 1） | **妥当**（下に置く方が散らない）。ただし背景ジョブが `set_hashes` を通らない（C-3）。設計の 2 行を「`store.set_hashes` が書く」に |
| E-3 | §7 L661「辞書で P8-1 で測る」 | 未計測のまま | **C-2**。設計の宿題。私の実測で埋められる |
| E-4 | §3.1 L500「`POST /api/groups`（既存の口）で群からまとまり」 | 口は作らず既存のまま（設計の穴 3） | **妥当**。本物のサーバで `kind='duplicates'` が 200（C-0）。`suggested_id` を `policy` に渡す道は P8-5 |
| E-5 | §3.1 L497「`limit`。頁送りは付けない」 | `limit` は群の数・`offset` 無し（設計の穴 4） | 妥当（点検 C7 のとおり）。`limit` の負は D-4 |
| E-6 | §8 L694 の 17「`GET /api/duplicates/near` で計算する → 落ちる」 | `test_the_get_endpoints_do_not_write` | 行はあるが**弱い**（F-1） |
| E-7 | — | `start_compute` が「帯の無い枚」も対象（決定 2） | **妥当で必須**（91 枚が一生群に出ない穴を塞ぐ）。ただしテストが無い（F-2） |
| E-8 | — | `job_item` は失敗だけ（決定 3） | 妥当（D-6） |
| E-9 | — | 除外を `exclude` の中で正規化（決定 5） | 妥当。逆順で渡す試験あり（N8 で落ちる） |
| E-10 | §0.4「完全重複は 2 か所以上の `asset`」 | `asset_location` の `missing_at IS NULL` が 2 以上（決定 6） | 妥当。2 か所目を足すと 1 群になる（`bands_check`） |
| E-11 | §3.1 に `cancel` の記述なし | `DuplicatesService.cancel` はあるが口なし | C-1。設計に「`/api/jobs/{id}/cancel` で止まる」を足してから直す |

## F. テストで守れないもの（`mutate_p81.py`。29 通り、ソースは触らず `-p` で差し替え）

| 壊し方 | 判定 | 根拠と直し方 |
| --- | --- | --- |
| **N10b** `near` の中で `asset.dhash` を上書きし `job` を 1 行足す（`GET` が書く） | **落ちない**（16 passed） | **F-1**。`tests/test_duplicates.py:255-269` は `phash_band` と `asset` の**行数**だけを比べる。全表の行数（と複製のファイルの size / mtime）を比べる形に（私の `http_check.py` の `snap()`） |
| **N17** `start_compute` の対象から「帯の無い枚」を外す（決定 2 を外す） | 落ちない | **F-2**。pHash ありで帯なしの枚を 1 枚作り、`total` が 1 になることを固定する（実データの 91 枚の道） |
| **N27** 1 枚の失敗で job 全体を `failed` にする | 落ちない | 実体の無い枚（`missing_at` 無しでパスが無い）を混ぜ、`done`・`failed 1` で続くことを固定（記録「1 枚の失敗で全体を止めない」の約束） |
| N14 `recover_stale` を無効に | 落ちない | `running` の hash job を入れてから `DuplicatesService(store)` → `failed` になる 1 本 |
| N20 `limit` を無視 | 落ちない | 群 2 つで `limit=1` → 1 |
| N21 同じ組の 2 回目の除外で落ちる（`INSERT` に替える） | 落ちない | 2 回除外して 200 を固定（D-9） |
| N30 除外の `actor` を記録しない（常に `agent`） | 落ちない | `exclusions()` の `actor` が `human` であることを見る |
| N10 `INSERT OR IGNORE` で既にある帯を足す | 落ちない | **等価変異**（何も変わらない）。数えない |
| N1 / N24（`BANDS=4`・小文字に揃えない） | 落ちる | `test_bands_split…`（N1 は 8 件） |
| **N2**（帯 0 固定） | 落ちる | `test_the_band_index_never_misses…`（本当に落ちる。実装者の直しが効いている） |
| N3 / N9 / N11 / N29（規則 1 を最下位・規則 4 を古い方・規則 2 を外す・`reason` 固定） | 落ちる | 代表の 4 テスト |
| N4 / N23（`set_hashes` が帯を書かない・古い帯を消さない） | 落ちる | `test_the_store_writes_bands…`（N4 は 5 件） |
| N5 / N13 / N26（並びを大きい群から・`unhashed` 0・`max_distance_within` 0） | 落ちる | `test_near_groups_orders_by_certainty…` |
| N6 / N28（`require_human` を外す・202 を 200 に） | 落ちる | `test_the_compute_endpoint_is_202_and_human_only` |
| N7 / N8 / N25（除外を外さない・正規化しない・解除の 404 を返さない） | 落ちる | `test_an_exclusion_hides_a_pair…` |
| N12 / N18 / N19 / N15（`max_distance` 無視・語彙外を通す・`exact` が 1 か所でも数える・409 を外す） | 落ちる | 期待どおり |
| M5 / M1b / M4b / M4c / M14 / M18a〜d / M19 / M22（P8-0 の条件） | **全部落ちる** | C-0 |

## G. 依頼者への質問（推奨つき。待たずに推奨で進めてよい）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | B-1 の直し方 | (a) API の `max_distance` を **0〜7** に締める（Q3 の ≤10 は帯で保証できないので ≤7 に改める） / (b) 8 以上は Python の総当たり（263 枚で 20 ms。1 万枚は 8 s） / (c) 帯を 4bit × 16 本に作り直す（保証 ≤15。`phash_band` の `CHECK (band BETWEEN 0 AND 7)` は `ALTER` で変えられないので表の作り直し。**実データは帯 0 行なのでいまなら安い**） | **(b) を短期、(c) を本命**。Q3 の ≤10 を活かすなら (c)。実データの帯が 0 行のうちに決める（P8-2 の前）。どれでも `probe` の総当たりを 10 まで回す |
| G-2 | C-2 の候補づくり | (a) 辞書の帯（1 万枚 1.1 s）に替える / (b) SQL のまま §7 に「1 万枚で 7.6 s（合成）」と書く | **(b) をいま、(a) は 1 万枚が現実になったら**。263 枚では 6 ms。設計 §7 の表は実測で埋める |
| G-3 | C-1 の中断 | (a) `JobService.cancel` が kind を見て委ねる / (b) 中断の印を `job` 表に置いて両サービスが DB を見る | **(b)**。再起動をまたいでも印が残り、`recover_stale` と同じ流儀 |
| G-4 | D-3 `reject` の枚の推薦 | (a) `reject` を最下位 / (b) 今のまま | **(a)**。人が「要らない」と言った物を「おすすめ」に出さない |
| G-5 | `_run` の書き手（C-3） | (a) `store.set_hashes` 経由 / (b) 今のまま | **(a)**。1 行で決定 1 が本当になる |

## H. 確かめられなかったこと・注記・後始末

**確かめていない**

- ComfyUI は触っていない（P8-1 に要素が無い）。
- 1 万枚は**合成**（実データ 263 の pHash にビット反転）。実データでの 1 万枚は無い。
- `force` の 263 枚が 1 秒で終わった理由（2 回目は OS のファイルキャッシュで復号が速い、と見ている）は測っていない。
- `#/jobs` の画面での中断ボタンの挙動（C-1）は API で再現しただけで、Chrome では押していない（P8-5 の画面）。
- `cancel` を正しく効かせた場合に `_run` が `cancelled` で止まるかは、口が無いので HTTP では試せない（`DuplicatesService.cancel` を直に呼ぶテストも無い）。

**紛らわしい出力の注記**

- `mutations.out.txt` の N8 の行頭に `IntegrityError: CHECK constraint failed` が混ざるのは `grep` の拾いすぎ。判定は末尾の `1 failed`。
- `synth10k` の総当たりは Python の `bin().count` で、numpy なら点検の 4.0 s。比べるのは同じ Python の辞書（1.13 s）と SQL（7.56 s）。
- サーバ 8791 は `taskkill` で止めたので `server.log` の末尾は途切れているが、クラッシュではない。

**実行したコマンドと結果（再現手順）**

```powershell
cd C:\work\image-reviwer; $env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"; $env:PYTHONUTF8 = "1"
uv run --no-sync pytest -q                                               # 314 passed × 3（13.94 / 13.84 / 13.76 s）
node tools/gui_smoke.mjs                                                 # すべて ok（ok の行 129）
uv run --no-sync python tools/probe_p8.py --keep                         # 線 1〜3 すべて OK（上の C-0）。複製は .tmp-audit-redo\p8probe\data
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-1-audit\bands_check.py   # 帯 vs 総当たり ≤0/3/6/7/8/10/12/16・境界・合成の距離 8・代表の同点・deleted_at・性能・exact・除外 x2（B-1 / C-4 / D）
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-1-audit\synth10k.py      # 1 万枚: SQL 7.56 s / 辞書 1.13 s / 総当たり 7.8 s（C-2）
bash .tmp-audit-redo\p8-1-audit\mut_run.sh                                   # 29 通り（PYTHONPATH=.tmp-audit-redo\p8-1-audit、-p mutate_p81、P8X=N1..N30）→ 22 落ちる（F）
# P8-0 の条件: PYTHONPATH=.tmp-audit-redo\p8-0-audit、-p mutate_p8、P8X=M5/M1b/M4b/M4c/M14/M19/M18a-d/M22 を tests\test_db.py に → 11/11 落ちる
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-0-audit\paths.py         # P7 の v6 の控え → P8 の 5 表が入る（差は recipe_* の 21 件だけ）
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-1-audit\gui_setup.py     # 複製 gui/（backup() + sidecar/export/thumbs）＋ まとまり 1 ＋ 語 4
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\p8-1-audit\gui"; uv run --no-sync image-reviewer serve --port 8791
.venv\Scripts\python.exe -X utf8 .tmp-audit-redo\p8-1-audit\http_check.py    # 守り 24 通り・GET 不変・compute 202→409→done 2.3 s・≤3/≤10・除外・POST /api/groups・cancel（C-1）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8 / --screen requests / group --group 01M5513SYP9DTB749HNFQ2F733 / asset --ids 01M4Z0KJS58V2SAJBGTG1TRFK5 / tags / jobs   # 6 画面すべて ok
taskkill /PID 28600 /F /T                                                # netstat で 8791 の LISTENING 0 本。8790 は health 200 のまま
```

**後始末**

- 残した物: `.tmp-audit-redo/p8-1-audit/`（複製 `data/`・`gui/`・`synth/`・`synth10k/`（約 20 MB）・スクリプト 7 本・出力 7 本）と `.tmp-audit-redo/p8probe/data/`（`probe --keep`）。消してよい。
- 消した物: 無し。サーバ 8791 は停止。
- `.data/` の size と mtime は不変。`src/` / `tests/` / `tools/` / `docs/` に監査中の変更は無い（`git status` は本報告だけ）。

---

## 最も重大な 3 件（再掲）

1. **B-1** 帯索引の取りこぼし 0 は距離 7 までの保証。API は 64 まで受け、Q3 の ≤10 は実データでたまたま完全（≤12 で 3 組・≤16 で 72 組を取りこぼす）。G-1 で決める。`probe` の総当たりを 10 まで。
2. **C-1** ハッシュの背景ジョブは `POST /api/jobs/{id}/cancel` で止まらない（別サービスの印）。印を `job` 表に置いて両方が見る（G-3）。
3. **C-2** 設計 §7 が P8-1 に課した 1 万枚の測定が未実施。合成 1 万枚で SQL 7.56 s＝総当たり 7.8 s と同じ、辞書なら 1.13 s。§7 を実測で埋める（G-2）。
