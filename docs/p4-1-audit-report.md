# P4-1（タガーと背景ジョブ）監査報告 — 実行込み

- 日付: 2026-10-16（09:40〜10:35）。監査者: Fable（Claude Code）
- 指示書: `docs/p4-audit-brief-p4-1.md`（09:36）。対象: `src/image_reviewer/tagger.py`（09:27、531 行）/ `jobs.py`（09:34）/ `tags.py`（09:24）/ `api/tags.py`（09:34）/ `db.py`（09:33）/ `app.py`（09:25）、`tests/test_tags.py`（9 件）/ `tests/test_jobs.py`（11 件）、`tools/probe_p4.py`（09:30）
- 設計: `docs/p4-design.md` 952 行版（09:23）。実装者の記録（「自分で決めた 6 点・設計の穴 5 件」）は `docs/` に無く、指示書 §2-11 / §2-12 の列挙を記録として扱った。
- 環境: 利用者のサーバ（8790、PID 14616）が `.venv` を握っているので **`uv run --no-sync` と `.venv\Scripts\python.exe`** を使った。実データ `.data/` は `mode=ro` と **`backup()`** だけ（mtime は 10-15 のまま）。ComfyUI 0.39.2（8188）に**タグ付けだけ**投げた（生成はしない）。一時物は `.tmp-audit-redo/p41/`（`p41_jobs.py` / `p41_http.py` / `resize_check.py` と各 `.out.txt`、`srv/`＝実データの複製 v5 済み、`old-v5/` `race/` `block/` `targets/`）。`tools/probe_p4.py` は自分で `.tmp-audit-redo/p4/data` を作って消す。監査のサーバは 8791（停止済み）。ソースと既存の文書は編集していない。

---

## 判定: **線 1・2・7 は私の手で通った。線 8 は `onnxruntime` 無しで 409 を正直に返す。ただし「ワーカー 1 本」と「1 枚 1 取引」に実証した欠陥があり、古い v5 の DB ではジョブが二度と動かなくなる。3 点を直してから P4-2 へ。**

**最も重大な 3 件**
1. **P4-0 の形の v5（`actor` / `note` の無い DB）でジョブを流すと、全件 `no column named actor` で落ち、さらに `_finish` 自身が `no such column: note` で落ちて job が `running` のまま残る**（§A-1）。以後の `POST /api/assets/tag` は再起動まで 409。`_migrate_v5` が `IF NOT EXISTS` だけで**列を見て足す手当てが無い**（v4 の `superseded_by` にはある）。指示書が「P4-1 の検証にも使える」と言う `data-p40` がまさにこの形。
2. **錠を握ったまま模型を待つ**（§B-1）。`_one()` は `store.transaction()` の中で `engine_obj.tag()`（ComfyUI の往復）を呼ぶ。`Store` は**接続 1 本を RLock で直列化**しているので、ジョブが走る間は**全部の API（読みも）が 1 枚ごとに模型の時間だけ待つ**（実測: 1.0 s の模型で `locked()` の待ち 801〜901 ms、別接続の書き込み 2.7 s）。
3. **`queued` が「忙しい」に入っていない**（§B-2）ので、スレッド起動から最初の `UPDATE` までの窓で 2 つ目の `POST` が通り、**2 本同時に走る**（実測: `['running', 'running']`、模型の呼び出し 4 回）。加えて**縮小の丸めがノードと違い**（`round` 対 `int`）、縦長の画像で語が 1〜2 語ずれる（§B-3）。`onnxruntime` を入れた日に線 8 が落ちる。

---

## A. 直っていない／設計の約束が成り立たない（必ず直す）

### A-1. 古い形の v5 ではジョブが二度と動かない（`db.py:468-475`、`jobs.py:249-250 / 397-402`）
- 再現（`p41_jobs.py` §1）: `data-p40` を `backup()` で複製 → `Store` で開く（`user_version=5` のまま。`asset_tag` の列は `actor` 無し）→ `start_tag(sources=["png","wd14"])` → `items_failed: OperationalError: table asset_tag has no column named actor` → `_run` の `except` が `_finish(job_id, "failed", …)` を呼ぶ → **`UPDATE job SET … note = ?` が `no such column: note` で落ちる** → スレッドが例外で死に、**job は `running` のまま**。`JobService.wait()` も戻らず、次の `start_tag` は 409 `job_running`。
- 2 層の直し: (1) `_migrate_v5` に `_migrate_v4` と同じ**列の有無を見て `ALTER TABLE ADD COLUMN`**（`asset_tag.actor` と `job.note`。`known` の `CHECK` は `ALTER` で足せないので古い複製では諦めてよい。実データは v3 なので本番は影響なし）。(2) `_finish` は**閉じようとしている行で落ちない**形に（`note` 列が無ければ `note` 抜きで更新する、または `_run` の最後の `except` で `_finish` が落ちたら `state='failed'` だけを別の文で書く）。
- これは P4-0 監査 G-1 で私が「`.data` が v3 のうちに v5 を書き換える」を勧めた帰結。**書き換えた後の v5 と前の v5 が同じ版番号で混在する**ことの手当てを書き忘れた。実装者の `data-p40` と、P4-0 の監査で私が作った複製がその形で残っている。

---

## B. 重大

### B-1. 取引の中で模型を待つ（`jobs.py:257-293`、`store.py:87-104`）
- `Store.transaction()` は **RLock を握って `BEGIN IMMEDIATE`〜`COMMIT`**。`locked()`（全部の `GET`）も同じ RLock。`_one()` は取引の中で `engine_obj.tag(path, …)`（`upload/image` → `/prompt` → `/history` の 0.5 秒ポーリング）を呼ぶ。
- 実測（`p41_jobs.py` §3。模型を 1.0 s の偽物に）: ジョブ中の `store.locked()` の待ち **801 / 901 / 901 / 0 ms**、別接続からの `INSERT` の待ち **2,718 ms**。HTTP では IllustTagger（0.3 s/枚）の間に `GET …/tags` が 60 ms、`/api/health`（store を触らない）が 2 ms だったが、**標本が間に落ちただけで、遮断の否定にはならない**。`WD14Tagger`（2.9 s/枚）なら画面が 1 枚ごとに 3 秒止まる。
- 直し方: **飛ばす判定と模型の呼び出しを取引の外**で行い、語の書き込みだけを短い取引にする（`DELETE` + `INSERT` は数 ms）。「1 枚 1 取引」（点検 C-5）の趣旨は**書き込みを 1 取引にまとめる**ことで、**待ちを取引に入れる**ことではない。

### B-2. `queued` が忙しいに入らず、2 本同時に走る（`jobs.py:28-30 / 124-131 / 145-152`）
- `BUSY_STATES = ("running",)`。`start_tag` は錠の中で検査するが、job の `INSERT`（`queued`）は**錠を離した別の取引**、`running` への更新は**ワーカースレッドの最初の文**。この窓で 2 つ目の `POST` が通る。
- 実測（`p41_jobs.py` §2。`_run` の頭に 0.4 s の遅延を入れて窓を広げた）: 2 つ目の `start_tag` が**通り**、`job.state` が **`['running', 'running']`**、模型の呼び出し 4 回（2 本分）。HTTP では（窓が数 ms なので）2 つ目は 409 だった。
- 直し方: `BUSY_STATES = ("queued", "running")` にし、**検査と `INSERT` を同じ `transaction()` の中**で行う。実装者が `queued` を外した理由（「`queued` が残るのはワーカーが動けないときだけ」）は、`recover_stale()` が起動時に `queued` も `failed` にしている（実測）ので成り立たない。

### B-3. 内蔵の前処理の縮小が `round()`、ノードは `int()`（`tagger.py:266-270` 対 `wd14tagger.py:63`）
- §0.6 の 9 手順のうち **8 つは実装どおり**（白 255 の正方形・LANCZOS・float32 0〜255・RGB→BGR・CSV の行順で `general_index` / `character_index`・閾値 `>` 0.35 / 0.85・rating を捨てる・`character + general` の順）。**縮小の寸法だけ違う**: ノードは `int(x*ratio)`（切り捨て）、実装は `round(width*scale)`。
- 実測（`p41_jobs.py` §6）: 1216×832 / 832×1216 / 1024×1536 / 1000×700 で**寸法が 1 px 違う**（正方形と 1920×1080 は同じ）。GPU で推論（`resize_check.py`、ComfyUI 同梱の `onnxruntime-gpu`）: 縦長 768×1360 の 4 枚のうち **2 枚で語が変わる**（`highleg` / `pussy` の 2 語、`saliva` の 1 語）。
- 直し方: `int()` に揃える（1 トークン）。**`onnxruntime` が無くても落ちるテスト**: `preprocess(Image.new("RGB", (768, 1360)), 448)` の貼り付け位置か、縮小後の寸法が `(252, 448)` であること。`onnxruntime` を入れれば `BuiltinTagger` は**そのまま線 8 を測れる形**（`tools/probe_p4.py --engine both`）になっている。

### B-4. `--engine both`（線 8）は**正直に 409**（`probe-both.out.txt`）
- `builtin → 409 {"code": "tagger_unavailable", "details": {"builtin": "onnxruntime がありません"}}`。job は作られない（`detect()` → `choose()`）。probe は「NG: 内蔵が使えない（onnxruntime 未導入。§0.4・Q4）」と出す。**未達であることを隠していない**。
- ただし `pyproject.toml` に **`[project.optional-dependencies] tagger = ["onnxruntime"]` が無い**（設計の穴 1 は「入れられない」だが、**書くだけなら入れなくてよい**。§D-5）。

---

## C. 中程度

### C-1. `_wait` の 0.5 秒ポーリングで 1 枚あたり 0.45 秒の空き（`tagger.py:446-462`）
- API 経由の実測: 実データ 8 枚（1024²、IllustTagger、png + wd14）で **0.72 s/枚**（壁時計 5.8 s）。ノード単体は 0.26〜0.31 s/枚（P4 点検 C-1）。差の大半は `/history` を **0.5 秒ごと**にしか見ないこと。10,000 枚で**約 1.2 時間の純粋な待ち**。0.05〜0.1 秒に縮めるか、`/ws` の `executed` を待つ。
- 1 万枚の見積り（IllustTagger）: いまの形で **約 2 時間**、ポーリングを直せば **約 1 時間**。内蔵 GPU なら 10〜15 分（P4 点検）。

### C-2. 既定の対象が `sources` の **AND**（`jobs.py:166-172`）
- `sources=["png","wd14"]`（既定）のとき「png も wd14 も無い画像」だけが対象。設計 §3.2 は「**`wd14` が `sources` にあれば `wd14` の行が無い画像**」。実測（`p41_jobs.py` §4）: `sources=["png"]` で先に付けた画像は、既定の両出所の走行で**対象から外れる**（`wd14` だけなら入る）。`wd14 in sources` なら `wd14` の有無だけで決める。

### C-3. `png_words` が残す語（`tagger.py:100-131`。実データで確認）
- 実データの `GET /api/assets/{id}/tags` に **`(masterpiece`** が `known=0` で出た（`(masterpiece, best quality:1.2)` を `,` で先に割るため、外側の重みの規則に当たらない）。`((foo))` → `((foo))`、`(bar)` → `(bar)` もそのまま語になる。`ver. 2` は `ver` と `2_of_thing` に割れる。
- 直し方: 断片の**先頭の `(` の連なりと末尾の `)` の連なりで数が合わないものを落とす**（`(masterpiece` → `masterpiece`）。重み無しの `(bar)` は `bar` に（Danbooru の語で括弧が**先頭**に来る語は無い）。

### C-4. 手動で付けられるのは `tag` 表にある語だけ（`api/tags.py:35-49`、`tags.py:resolve_tag`）
- `POST /api/assets/{id}/tags {name}` は `tag` 表を引くだけ。**CSV にあってもまだ誰も付けていない語は 404**（実測: `tail` → 404。文言は「その語は語彙にありません」だが、実際は「表に無い」）。設計 §3.1 / §5.1 の「語を足す（候補は `GET /api/tags?q=`）」は表の語だけなら整合するが、**語彙にある語を人が新しく付けられない**のは線 2 の趣旨（`manual` は人が付けた語）に対して狭い。`tag` 表に無ければ **CSV で `known` を引いて `_ensure_tag`** する（1 行）。文言も直す。

### C-5. 同じ語を 1 行にまとめるときの `score` / `model` / `actor`（`tags.py:tag_docs`）
- 並び（キャラ → 一般 → 他、スコア降順、NULL 最後）で**最初の行**の値だけが残る。`1girl` が `wd14` と `png` にあれば `wd14` の行が先で `score` が残る（意図どおり）。しかし **人が付けた `manual` の `actor`** は、同じ語に `wd14` があると**消える**（`actor` は最初の行の `NULL`）。`sources` に `manual` は残るが、誰が付けたかは落ちる。設計 §3.4（952 行版 560-570 行）は**出所ごとに別の行**の例のまま。契約（`review.json`）は P4-0 のまま**出所ごとに 1 行**。**API と契約で形が違う**ので、設計 §3.4 を実装に合わせて直し、`actor` は `actors` か `manual_actor` で残す。

### C-6. `GET /api/assets/{id}/tags` に設計 §3.4 の `glosses` / `pending_gloss` / `counts` が無い
- 応答は `{asset_id, items}`。`gloss` / `gloss_edited` は `items[]` に入っている（P4-2 で埋まる）。`counts`（出所ごとの数）と `pending_gloss` は P4-2 でも要るので、どちらかに寄せる（§E-3）。

---

## D. 軽微

1. **線 1・2・7（`tools/probe_p4.py --engine comfyui`）**: 確かめた結果、問題なし。合成 8 枚（256²）に `wd14` が **7 / 8 / 9 / 8 / 9 / 10 / 11 / 12 語**、`manual` に `comic` を追加 → `png=0 wd14=7 manual=['comic']`、2 回目 `added=False`、`agent` 403、`manual` の行 1、外す 200、2 回目 404。「すべて OK」。壁時計 7.8 s（サーバ起動込み。**速さの値ではない**）。
2. **実データでの線 2・7**（`p41_http.py`）: 確かめた結果、問題なし。`manual` 追加 200 → 2 回目 `added: False` → `agent` 403 → `DELETE` 200 → 2 回目 404 → `agent` 403 → **`wd14` の行は `DELETE` で消えない**（404）。
3. **正規化**: 確かめた結果、問題なし。`admiral_\(kancolle\)` → `admiral_(kancolle)`、`2b_\(nier:automata\)` → `2b_(nier:automata)`、`:d` → `:d`、`Long Hair` → `long_hair`、`[`/`]` は落ちる（テスト）。`png_words("(three quarter view:1.5)")` → `three_quarter_view`（小数は割れない）、`(red:1.2), (blue :0.8)` → `red` / `blue`、空断片は落ちる、`First girl:` / `Second boy:` の前置きが外れる。**64 字**: `is_acceptable` が 64 で真・65 で偽、長すぎる断片は `note` に「長すぎて落とした断片 N」（テスト）。
4. **`known`**: 確かめた結果、問題なし。`_ensure_tag` は `ON CONFLICT(name) DO UPDATE SET known = max(…)`、`category` は `COALESCE`（テスト）。`_refresh_known` はジョブ開始時に一時表で `UPDATE tag SET known = (name IN …)`（CSV が無ければ飛ばす）。DDL に `CHECK (known IN (0, 1))`（`srv` の `sqlite_master` で確認）。`GET /api/tags` の既定は `known=1`（実データ: 既定 200 語すべて `known`、`known=0` は 64 語で先頭が `best_quality / safe / masterpiece / score_7`、`all` 269、`known=yes` は 422）。`GET /api/assets?tag=<known=0 の語>` は 0 枚、`&known=all` で 8 枚、`known=yes` は 422。
5. **`GET` は書かない**: 確かめた結果、問題なし。`GET` 7 種（tags / tag 一覧 / `?tag=` / jobs / job / items / export）の前後で `srv/` のファイル（名前・mtime・size）が同一。タグ付けは `POST /api/assets/tag` だけ。`require_human` は `tags.py` の 1 か所で、`POST` / `DELETE` の 2 口が呼ぶ。
6. **ジョブ**: 確かめた結果、問題なし（B-1 / B-2 を除く）。走行中の 2 つ目の `POST` は 409 `job_running`（HTTP）。中断: 30 枚を投げて `cancel` → `cancelled`、`progress.done=3`、`wd14` が付いた画像は **3 枚**（= done。付いた語は残る）、2 回目の `cancel` は `cancelled` のまま、無い job は 404。失敗は `job_item` に 1 件ずつ（テスト `test_one_failure…`）。**起動時の後始末**: `running` と `queued` を 1 行ずつ入れて再起動 → **両方 `failed`**（「中断されました」）→ 直後の `POST` が 202。2 回目のジョブは 8 枚とも `skipped`（`model` が同じ）。
7. **ComfyUI の作法**: 確かめた結果、問題なし。複製は `temp/image-reviewer/<asset_id>-<sha8>.png`（実物: `01M511V7Y99GDBNKCVEQKPD3NF-00000000.png`。テストも `names == [f"{asset}-{'a'*8}"]`）。`_parse` は `scores` → `tags` を探し、ノード番号を見ない。既定は `IllustTagger`（`DEFAULT_NODE = "illust"`）。`settings` の `tagger.node=wd14` で 2 枚 → `score` が **全部 `None`**、33 語（設計どおり「スコア無し」）。
8. **契約と決定性**: 確かめた結果、問題なし。`GET …/tags` の `items[]` は 12 鍵、同じ語は 1 行で `sources` に複数（`1girl: ['wd14', 'png']`）、並びは **category 4→0→他 → score 降順（NULL 最後）→ name** の規則どおり（61 語で検証）、2 回同じ。`review.json`（`include_tags=true`、`asset:` と `all`）は本物の `jsonschema` で OK（`all` は 569 行）。
9. **回帰**: `uv run --no-sync pytest -q` → **251 passed**。`gui_smoke` → **91 ok**。`gui_layout` の 4 画面（比較 8 枚・要求・まとまり・注記）→ **すべて ok**。P5 / P6 の口（`/api/review-requests`、注記、export）→ 200。**実データの mtime は 10-15 のまま**（`db.sqlite3` 14:29、`-wal` 19:27、`user_version=3`）。
10. **v3 の実データ → v5 を起動で**: `backup()` の複製を `IMAGE_REVIEWER_DATA` にして起動 → `user_version=5`、263 枚・判断 3 件、`asset_tag.actor` / `job.note` / `known` の `CHECK` あり。
11. `describe()`（`tagger.py:572-579`。点検 B-2 の「実際の provider を出す 1 行」）は**どこからも呼ばれていない**（`app.py` / `cli.py` に `describe` / `doctor` 無し）。
12. `sources=["png"]` だけの job は `engine: "builtin"` と報告する（`jobs.py:138`。内蔵が無くても）。`"none"` か `null` に。
13. `TagCsv.category_of` は 10,861 語の線形走査（66 語で 9 ms → 10,000 枚で約 1.5 分）。`dict` にすれば 0。
14. ComfyUI の `temp/image-reviewer/` に**複製が溜まる**（監査の終わりに **53 枚・19 MB**。実装者の分と私の分）。「再起動で消える」は未確認（設計 §10-21 の「消えなければ開始時に空にする運用」は実装に無い）。
15. `_targets` の `missing` は f 文字列で `source` 名を SQL に埋める（`sources` は検査済みの 2 語なので安全。念のため placeholder に）。

---

## E. 設計とのずれ

1. **§3.4 の応答の形**: 設計は出所ごとに別の行（560-570 行）、実装は 1 語 1 行＋`sources`（指示書 §2-8 の言い方と同じ）。実装の形で設計を直す。`actor` の扱い（C-5）もそこで。
2. **§3.2 の既定の対象**（C-2）: 実装は AND。
3. **§3.4 の `glosses` / `pending_gloss` / `counts`** が応答に無い（C-6）。P4-2 で入れるなら設計に「P4-2」と書く。
4. **`job.note`**（実装者の決定 3）: 設計 §2.1 / §3.3 に無い。**足してよい**（§0.8-5「採った数と語彙外の数を job の結果に残す」の置き場）。§2.1 の DDL と §3.3 の例に `note` を足す。
5. **`GET /api/jobs/{id}/items`**（決定 4）: 設計 §3.3 に「全部は `GET /api/jobs/{id}/items?state=failed`」と**既にある**。ずれではない。
6. **`job_item` に時刻が無い**（穴 3）: `job_item` は空の表なので**今 `at TEXT` を足す**（v5 の DDL を直すだけ。古い v5 の複製は A-1 の手当てで列を足す）。
7. **`pyproject.toml` の `tagger` extra**（穴 1）: 書くだけなら利用者のサーバは関係ない。`[project.optional-dependencies] tagger = ["onnxruntime>=1.17"]` を**今**書く（`uv sync --extra tagger` は後で）。
8. **`?tag=` がメモリ上の一覧**（穴 4）: `asset_id` の集合を SQL で引いてから Python で絞る形（`app.py:182-212`）。設計 §3.6 のとおりで、**P4 ではこのまま**でよい（263 枚で 1 ms 台。1 万枚でも集合は `ix_asset_tag_tag` で引ける）。
9. **`force` の消し方**（穴 5）: `DELETE … source='wd14'` → `INSERT`。同じ取引の中なので途中で落ちても消えない（実装どおり）。**問題なし**。
10. 設計 §0.4 の「`doctor` 相当の 1 行」が未配線（D-11）。

---

## F. テストが守っていないもの

| 観点 | 判定 | 根拠 |
| --- | --- | --- |
| ワーカー 1 本（B-2） | **守れない** | `test_start_rejects_bad_input_and_busy_workers` は `running` の行を手で入れて 409 を見るだけ。`queued` の窓は見ていない。`_run` に遅延を入れた再現（`p41_jobs.py` §2）をテストにする |
| 1 枚 1 取引の**範囲**（B-1） | **守れない** | 取引の長さを見るテストが無い。偽の模型に `sleep` を入れ、別スレッドの `locked()` の待ちが模型の時間より短いことを固定する |
| 内蔵の前処理（B-3） | **守れない** | `preprocess()` のテストが無い。768×1360 → `(252, 448)` の寸法と貼り付け位置を固定する（`onnxruntime` 不要） |
| 古い v5 からの移行（A-1） | **守れない** | `test_migrate_v5…` は v1 と v4 からだけ。「`actor` / `note` の無い v5」からの `migrate()` を足す |
| 中断が 1 枚ごと | テストは**印を立てるだけ** | `test_cancel_marks_the_job…` は `running` の行を手で入れて `message` を見るだけ。1 枚ごとに見ることは私の HTTP の実行（30 枚 → 3 枚で止まる）で確認した。偽の模型で 3 枚目の途中に `cancel` を呼ぶテストにできる |
| 既定の対象の AND（C-2） | **守れない** | `test_targets_default_to_the_untagged` は `sources=["png"]` だけ |
| 正規化・`known`・403/404・飛ばす・失敗 1 件・全滅で `failed`・422・409 `tagger_unavailable`・後始末 | 落ちる形。問題なし | docstring に「壊すと落ちる」が書かれ、期待値が具体 |
| 線 1・8 | `probe_p4.py` が担う | 設計どおり |

---

## G. 依頼者への質問（推奨つき）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | 古い v5 の複製の扱い（A-1） | (a) **`_migrate_v5` に列の手当て**（`actor` / `note` / `job_item.at`）／(b) v6 を切る／(c) 複製は捨てる前提 | **(a)**。本番は v3 なので (c) でも事故は起きないが、`IF NOT EXISTS` だけの移行は「同じ版番号で形が違う DB」を黙って受け入れる。v4 と同じ流儀に揃える |
| G-2 | 取引の範囲（B-1） | (a) **模型の呼び出しを取引の外**／(b) `Store` に接続をもう 1 本（ワーカー専用） | **(a)**。(b) は WAL なら読みは並ぶが、書きは結局 `busy_timeout` 待ちになり、Store の「接続 1 本」の設計を崩す |
| G-3 | `GET …/tags` の形（C-5 / E-1） | (a) **1 語 1 行＋`sources`**（実装）／(b) 出所ごとの行（設計・契約） | **(a)** を設計に反映。`actor` は `actors: {manual: "human"}` のように出所ごとに残す |
| G-4 | 手動で付けられる語（C-4） | (a) **CSV にある語なら表に無くても付けられる**／(b) 表の語だけ | **(a)**。`known` を CSV で引いて `_ensure_tag`。語彙外の自由な語は P4 では作らない（§1.3） |
| G-5 | ポーリング（C-1） | (a) **0.1 秒**／(b) `/ws` を使う | **(a)**。1 行の変更で 10,000 枚あたり 1 時間縮む |
| G-6 | ComfyUI の複製の後始末（D-14） | (a) **ジョブの終わりに `temp/image-reviewer/<名前>.png` を自分で消す**（ComfyUI の `temp` は同じマシンなので `os.remove` できる）／(b) 再起動任せ | **(a)**。既に 53 枚・19 MB が残っている |

---

## H. 確かめられなかったこと

- **線 8**（内蔵と ComfyUI の一致）: `onnxruntime` が `.venv` に無い。コードを読んだ判定（B-3）と、ComfyUI 同梱の `python_embeded` で**縮小の丸めだけ**を実機で比べた。入れればそのまま `probe_p4.py --engine both` で測れる形。
- **HTTP での遮断の時間**（B-1）: IllustTagger（0.3 s/枚）の間に取った標本は 60 ms と 2 ms（`/api/health` は store を触らない）で、**標本が少なく遮断の有無の証拠にならない**。証拠はプロセス内の実測（801〜901 ms / 2,718 ms）。
- ComfyUI の `temp` が再起動で消えるか（利用者の ComfyUI を再起動していない）。
- 実装者の「決めた 6 点・穴 5 件」の原文。
- `category_of` の 10,000 枚は見積り（9 ms × 10,000）。
- ワーカーの終了（`lifespan` の `shutdown` でスレッドを待つか）。daemon スレッドなので**プロセス終了時に途中の取引は `ROLLBACK` される**（1 枚単位なので失うのは 1 枚）。
- 後始末: `.tmp-audit-redo/p41/`（`srv/` は実データの複製 v5＋タグ 569 行＋job 6 行、`old-v5/` ほか）を残した。`.tmp-audit-redo/p4/data` は probe が自分で消した。サーバ 8791 は停止。`.data/` の mtime は 10-15。`src/` の最新は `jobs.py` 09:34（実装者）。ComfyUI の `temp/image-reviewer/` に 53 枚（私の分は 40 枚前後）。

### 実行したコマンドと結果（主なもの）

```
uv run --no-sync pytest -q                                      → 251 passed
node tools/gui_smoke.mjs                                        → 91 ok
.venv\Scripts\python.exe tools/probe_p4.py --engine comfyui     → 線 1（7〜12 語 / 8 枚）・線 2・線 7 すべて OK
.venv\Scripts\python.exe tools/probe_p4.py --engine both        → builtin 409 tagger_unavailable（onnxruntime がありません）
.venv\Scripts\python.exe .tmp-audit-redo/p41/p41_jobs.py        → 古い v5: running のまま（actor / note）、queued の窓: running 2 本、
                                                                  locked() の待ち 801〜901 ms、既定の対象 AND、category_of 9 ms、丸め 4/6 違う
python_embeded\python.exe .tmp-audit-redo/p41/resize_check.py … → 768×1360 の 4 枚中 2 枚で語が変わる（int 対 round）
uv run --no-sync --with jsonschema python .tmp-audit-redo/p41/p41_http.py
                                                                → v3→v5 起動、8 枚 0.72 s/枚、409、契約の形・並び・決定性、known の既定、
                                                                  GET は書かない、review.json OK、中断 3/30、WD14 ノードは score NULL
再起動（running + queued を植えて）                             → 両方 failed、直後の POST 202
node tools/gui_layout.mjs --count 8 / --screen requests / group / asset → すべて ok
```
