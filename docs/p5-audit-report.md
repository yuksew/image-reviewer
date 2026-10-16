# P5 実装の監査報告

- 監査した版: 2026-10-15 の作業ツリー（コミット無し）。**ファイルの更新時刻は取れなかった**（下記の理由でシェルが起動できず、`Read` はファイルの中身しか返さない）。テスト件数は**ソースを読んで数えた 88 件**（`test_review.py` 29 / `test_export.py` 13 / `test_prototype.py` 21（parametrize 3 を含む）/ `test_db.py` 14 / `test_store_sqlite.py` 11）で、指示書の 88 件と一致する。
- 読んだもの: `src/image_reviewer/{app,cli,db,store,review,reasons,export,scan,capture}.py`、`api/{__init__,reviews,groups,export}.py`、`png_meta.py` の先頭、`tests/` の 5 ファイルと `conftest.py`、`pyproject.toml`、`schemas/review-export.schema.json`、`apps/gui/app.js`、`docs/{p5-design,p5-review-report,p5-review-triage,review-report,README,prototype-notes}.md`、`design.md` §13 末尾〜§14。
- **実行したコマンドと結果**: **何も実行できていない。** `Bash` / `PowerShell` / `Monitor`（および `Glob` / `Grep` が使う `rg`）の起動がすべて `EPERM: operation not permitted, uv_spawn` で拒否された（サンドボックスを外す指定でも同じ。報告を書く前後で計 9 回試した）。したがって **`pytest`・サーバの起動・実データの読み取り（`.data/db.sqlite3` は二進ファイルで `Read` では読めない）・スキーマ検証・計測・`diff` はいずれも「実行していない」**。指示書 §2 の 1〜7 は**コードから推論した結果**と、**依頼者がそのまま打てる確認手順**を書くにとどめた。「実行して初めて分かったこと」を最重大 3 件に 1 件含めよ、という要求は**満たせない**。代わりに「実行で白黒を付けるべき筆頭」を指名した（末尾）。
- 総合判定: **条件つきで使える。** 骨格（追記のみの台帳・`seq` 順・`human` 以外 403・1 取引での N＋1 行・`open` も書き出す契約）はコード上は設計どおり。ただし **(1) 1 枚の判断が `review_group.changed_at` を動かさないため、遅延中に落ちる／普通に終了するだけで書き出しが永久に漏れる**（設計 B1 の主張が成り立たない）、**(2) 「結論が変わるときだけ open に戻す」の判定が `all_rejected`＋keep と `selected`＋clear を取りこぼし、契約ファイルが矛盾した結論を出す**、**(3) `migrate-from-json` が台帳無しで `review_state` を写すので、起動時の `reconcile()` が取り込んだ判断を消す** の 3 点は使う前に直す必要がある。

---

## A. 設計の主張が成り立たない（必ず直す）

| # | 場所 | 問題 | 利用者の側で何が起きるか | 再現手順 / 確認手順 | 提案 |
| --- | --- | --- | --- | --- | --- |
| **A1** | `src/image_reviewer/review.py:71-96`（`apply_asset` の取引の中に `UPDATE review_group` が**無い**）、`review.py:764-766`（`_notify` はメモリ上の `mark()` だけ）、`review.py:378-381`（`_decide_group` は**自分のまとまりだけ** `changed_at` を更新し、同じ画像を含む他のまとまりは更新しない）、`export.py:170-175`（起動時の回収は `exported_at IS NULL OR changed_at > exported_at` **だけ**を見る）、`export.py:177-183`（`close()` は書かずに捨てる）、`app.py`（shutdown フックが無く、Timer は daemon なので終了で消える） | 設計 §0.3 B1 は「判断・reopen・メンバー変更と**同じトランザクションで `changed_at` を更新する**」と言うが、**1 枚の判断（`POST /api/reviews`）はどのまとまりの `changed_at` も動かさない**。書き出しの印は `ExportService._pending`（プロセスのメモリ）にしか無い。`export.py:17` の「COMMIT 直後に落ちても次回の起動で追い付く」は、**一度も書き出されていないまとまり（`exported_at IS NULL`）に限って**正しい | 既に 1 回書き出されたまとまり（普通の状態）に属する画像を 1 枚キープし、2 秒以内にプロセスが落ちる／`taskkill` される／`Ctrl+C` で普通に止める、のいずれかで `export/groups/<id>.json` は**古いまま**になり、次の起動でも、次の日次でも直らない（`write_all` は印を触らない）。他ツールは「未判断」のままの契約ファイルを読み続ける。同じ画像を含む別のまとまり B も、まとまり A の `decide` では DB 上の印が付かないので同じ | **実行していない。** 手順: (1) `uv run image-reviewer serve --port 8791`。(2) `POST /api/groups {asset_ids:[a]}` → 2 秒待つ → `export/groups/<g>.json` ができ `SELECT exported_at FROM review_group` が非 NULL になるのを確かめる。(3) `POST /api/reviews {subject_id:a, verdict:'keep'}`（ヘッダ `X-Image-Reviewer-Actor: human`）→ **即座に** `taskkill /F /PID <pid>`。(4) 再起動し、`export/groups/<g>.json` の `assets[0].review_state` を見る。**期待は `kept`、コード上の予測は `unreviewed`**。(5) `SELECT changed_at, exported_at FROM review_group` で `changed_at <= exported_at` のままであることを確かめる | `apply_asset` の取引の中で `_affected_groups()` の全 `group_id` に `UPDATE review_group SET changed_at = ?` を入れる（`_decide_group` も同様に、影響した他のまとまりへ）。あわせて `create_app()` に shutdown で `exporter.flush()` を呼ぶフックを足す。テストは「**既に書き出し済みの**まとまりで落ちて、起動時に出る」に書き直す（F1） |
| **A2** | `review.py:633-640`（`_contradicts`。`selected`＋`reject` と `pick_one` の `not_selected`＋`keep` の 2 条件だけ）、`review.py:656-672`（`_inherit_slot` は矛盾と判定されなかった行に前の `group_decision` を**そのまま引き継ぐ**）、`export.py:282-303`（`items[].group_decision` と `selected_asset_ids` はその引き継いだ値から作る） | 「結論が変わるときだけ `open` に戻す」（§0.4 B4/G9）の「結論が変わる」が 2 条件に固定されていて、次の 2 つを取りこぼす。(a) **`all_rejected` のまとまりの 1 枚を `keep`** → 矛盾と判定されず、`keep` 行に `group_decision='all_rejected'` が引き継がれ、まとまりは `decided / all_rejected` のまま。(b) **`selected` の枚を `clear`** → `_contradicts('clear', 'selected')` は偽。`clear` 行に `group_decision='selected'` が引き継がれ、まとまりは `decided / selected`、`selected_asset_ids=[a]` のまま | (a) 「全部ボツ」と決めたまとまりの 1 枚を後からキープすると、契約ファイルは `groups[].decision: "all_rejected"`、`items[a].verdict: "keep"`、`items[a].group_decision: "all_rejected"`、`assets[a].review_state: "kept"` という**矛盾した 1 文書**になる。(b) 選んだ 1 枚の判断を取り消すと、`selected_asset_ids: [a]` のまま `assets[a].review_state: "unreviewed"` になる。要求（P6）を読むエージェントは「全部ボツ」「a に決まった」を信じる | **実行していない。** (a) `POST /api/groups` で 2 枚（policy `pick_one`）→ `decide` で両方 `reject`＋`group_reason_code_id` → `POST /api/reviews {a, keep}` → 応答の `reopened_group_ids` が `[]`、`GET /api/groups/{id}` が `decided` のまま。(b) `decide` で a を `keep` → `POST /api/reviews {a, clear}` → `GET /api/groups/{id}` の `selected_asset_ids` が `[a]` のまま、`items[a].review_state` は `unreviewed` | `_contradicts` に「`slot == 'all_rejected' and verdict == 'keep'`」「`slot == 'selected' and verdict == 'clear'`」を足す（`pick_many` の `selected`＋`clear` で選ばれた枚が 0 になる場合も含む）。設計 §0.4 の文言も「結果と食い違う」の列挙を 4 つに直す |

**確かめた結果、問題なし（コード上。実行はしていない）**: `apply_group` は `store.transaction()`（`BEGIN IMMEDIATE`）1 つの中で N 件の枚の行＋1 件のまとまりの行＋写し＋`review_group` の更新を書き、例外は `ROLLBACK` される（`store.py:86-103`、`review.py:107-127`、`review.py:355-388`）。`seq` は取引の中で `MAX(seq)+1`（`db.py:294-297`）なので別プロセスとも衝突しない。`human` 以外は `ReviewService` が最後の砦として 403（`review.py:392-395`）。`reopen` は台帳に行を書かず `clear` も書かない（`review.py:674-679`）。

---

## B. 重大（データを失う・静かに壊れる）

| # | 場所 | 問題 | 利用者の側で何が起きるか | 確認手順 | 提案 |
| --- | --- | --- | --- | --- | --- |
| **B1** | `src/image_reviewer/cli.py:92-104`（`migrate_from_json` が JSON の `review_state` / `reviewed_at` / `reviewed_by` を `asset` に**直接**書き、`decision` に行を書かない）、`review.py:57-59`（`ReviewService.__init__` は毎回 `reconcile()`）、`review.py:612-616`（台帳に行が無ければ `('unreviewed', None, None, None)`） | **台帳が無い写し**を作る唯一の経路。次に `ReviewService` が作られた瞬間（`serve`、そして後述 C1 のとおり**どの CLI コマンドでも**）、`reconcile()` が「台帳が正」として写しを `unreviewed` に戻し、INFO ログに「組み直しました: N 行」とだけ出す。`store.json` 側に `kept` があればそれは**黙って消える** | 指示書は「いま `kept` が 1 枚」と言う。その 1 枚が **API で付けたもの**（台帳に行がある）なら残るが、**`store.json` から取り込んだもの**なら、P5-1 のコードで最初にサーバを上げた時点で消えている（消えたこと自体は INFO ログの 1 行でしか分からない） | **実行していない。** `.data/db.sqlite3` の**コピー**で: `SELECT a.id, a.review_state FROM asset a WHERE a.review_state <> 'unreviewed' AND NOT EXISTS (SELECT 1 FROM decision d WHERE d.subject_type='asset' AND d.subject_id=a.id);` — 1 行でも返れば、次の起動で消える。`SELECT count(*) FROM decision;` が 0 で `kept` が 1 枚なら、それは取り込み由来で、既に消えているか次で消える | `migrate_from_json` で `review_state` が `unreviewed` 以外の枚には `decision` を 1 行（`actor='human'`、`created_at=reviewed_at`、`note='store.json から取り込み'`）を書く。`reconcile()` は直した行数が 0 でないとき **WARNING** にし、直す前の値を併記する |
| **B2** | `export.py:163-168`（`flush` は `_pending` を**先に空にして**から順に書く）、`export.py:201-216`（`write_group` の `os.replace` / `UPDATE` の例外を受けない）、`export.py:185-188`（Timer スレッドの中で例外は標準エラーに印字されるだけ） | 1 つのまとまりの書き込みが失敗すると（Windows では、他ツールやウイルス対策がその `.json` を開いている瞬間に `os.replace` が `PermissionError` になる）、**残りの対象は書かれず、`_pending` は既に空**。A1 のとおり DB に印が無いので、以後どの起動でも拾われない | 同じ画像を含む 3 つのまとまりのうち 1 つで書き込みが失敗すると、残り 2 つの契約ファイルも古いまま止まり、画面には何も出ない | **実行していない。** `export/groups/<g1>.json` を別プロセスで開いたまま（例: PowerShell で `[IO.File]::Open(..., 'Open', 'Read', 'None')`）、g1 と g2 を汚す判断を入れ、2 秒後に g2 のファイルが更新されるか見る | `flush` は対象ごとに `try` で囲み、失敗した ID を `_pending` に戻して次のタイマーで再試行、`log.warning` で理由を出す。A1 を直せば起動時の回収も効く |
| **B3** | `export.py:172,194,204,228-254,278,317,392-418`（`self.store.con` を**`Store._lock` を取らずに**読む）、`store.py:86-103`（錠は `transaction()` の中でだけ握る）、`db.py:62-69`（`check_same_thread=False` の 1 本を共有） | 書き出しは Timer スレッド、判断は FastAPI のスレッドプールで、**同じ `sqlite3` 接続**を同時に使う。要求側が `BEGIN IMMEDIATE` の途中（枚の行は入ったが写しはまだ）のとき、書き出し側の `SELECT` は同じ接続なので**未コミットの行を見る**。その取引が `ROLLBACK` されれば、存在しない判断が契約ファイルに残る。1 接続の複数スレッド同時利用は `sqlite3` モジュールが直列化するので落ちないが、**文の割り込み位置は不定** | 起きる確率は低いが、起きたときは「誰も付けていない判断」が他ツールに読まれる。再現性が無いので追えない | **実行していない。** 確かめ方: `write_group` の `build` を monkeypatch して「中で別スレッドが `apply_group` を途中で失敗させる」を作る（`test_a_change_during_the_export_stays_dirty` と同じ手口） | `ExportService` の読み出しをすべて `with self.store.transaction() as con:`（または `with self.store._lock`）の中に入れる。長期的には書き出し専用の**別接続**（WAL なら読みは競合しない）を持ち、コミット済みだけを見る |

---

## C. 中程度

| # | 場所 | 問題 | 利用者の側で何が起きるか | 提案 |
| --- | --- | --- | --- | --- |
| **C1** | `app.py:237`（`app = create_app()` を**モジュール読み込み時**に実行）、`cli.py:22` と `cli.py:220`（`from .app import data_dir` が `_store()` / `migrate-from-json` の中で走る） | **`scan` / `capture` / `migrate-from-json` のどのコマンドでも** `create_app()` が走り、CLI プロセスの中に**もう 1 組**の `Store` / `ExportService`（起動時 `flush_dirty()`）/ `ReviewService`（`reconcile()`）と daemon Timer ができる。指示書 §2.1-1 の「サーバを上げたまま `scan`」は、走査が判断を消すかではなく、**2 つのプロセスが同じ `export/groups/*.json` を同時に `os.replace` し、`exported_at` を取り合う**問題として現れる。`migrate-from-json` は取り込み**前**の DB に `reconcile()` を当て、取り込み後はサーバ起動時に B1 が起きる | `scan` を打つたびに書き出しと組み直しが裏で走る（遅い・ログが二重）。同時書き込みで `PermissionError` になれば `scan` 自体が `create_app()` の中で落ちる | `data_dir()` を `app.py` から `config.py` 等へ出し、`create_app()` は `serve` だけが呼ぶ（モジュール頂上の `app = create_app()` は `uvicorn.run("...:create_app", factory=True)` に変える） |
| **C2** | `export.py:132,153-161,163-168,203`（`mark` も `flush` も `write_group` も同じ `RLock`）、`review.py:96,127,140,226`（`_notify` → `mark`） | 判断の応答は取引の**外**で `mark()` を呼ぶが、`mark()` は exporter の錠を待つ。Timer が `flush()` で複数まとまりを書いている間（まとまり 1 つにつき `build` が枚数 × 4〜5 クエリ＋ファイル書き）、**`POST /api/reviews` の応答はその完了まで待たされる**。「書き込みの速さを書き出しの重さから切り離す」（§4）は錠の取り方で半分戻っている | 連続して判断するほど、2 秒ごとに応答が詰まる。100ms の目標（§8）に乗るかは**未計測** | `mark()` は `_pending` 用の小さな錠だけを取り、`write_group` は錠の外でファイルを書く（`_pending` から取り出す瞬間だけ錠）。100ms は依頼者側で計る（H の手順） |
| **C3** | `app.py:46-48`（`ExportService(store)` が `flush_dirty()` を**先に**走らせ、その後で `ReviewService(store)` が `reconcile()`）、`review.py:163-185`（`reconcile` は `asset` だけ直し、`review_group.changed_at` を動かさない） | 写しが壊れていた場合、起動時の書き出しは**壊れた写し**から `assets[].review_state`（`export.py:324` は `asset.review_state` を読む）を書き、直後の `reconcile` は `asset` を直すが印を付けないので、ファイルは次に誰かがそのまとまりに触るまで古いまま | 「起動時に組み直す」の価値が書き出しに届かない | 順序を `ReviewService` → `ExportService` に入れ替え、`reconcile()` が直した枚の `group_item` から `changed_at` を更新する |
| **C4** | `store.py:358-386`（`set_review_state` が台帳無しで `asset.review_state` を書く。docstring は「唯一の口」）、`tests/test_prototype.py:292`、`tests/test_store_sqlite.py:200-220,369` が使う | 指示書 §2.3-8 の答え: **`ReviewService` 以外で `review_state` を書くのは `Store.set_review_state`（休眠）と `cli.migrate_from_json`（B1）の 2 か所**。`review_group` / `decision` を書くのは `ReviewService` と `ExportService.write_group`（`exported_at` だけ）のみ。`set_review_state` はアプリから呼ばれていないが、残っている限り「次の `reconcile()` で消える写し」を作れる。docstring の「唯一の口」は P5-1 で嘘になった | 将来の誰かが使うと B1 と同じ静かな消失が起きる | 削除するか、`ReviewService.apply_asset` を呼ぶ薄い互換にする。使っているテストは `ReviewService` 経由に書き直す |
| **C5** | `review.py:189-191`（`create_group` は `kind` / `policy` / `title` を検査するが **`source` を検査しない**）、`api/groups.py:26`（本文の `source` をそのまま渡す）、`db.py:118`（CHECK 無し）、`schemas/review-export.schema.json:387-391`（`source` の enum は `manual / comfyui / watcher / request`） | `POST /api/groups {"source":"x"}` が通り、そのまとまりの契約ファイルは**スキーマ検証に落ちる**。§0.7 C2 の「`source='manual'` と書く」は既定値だけで、入力の検査が無い | 他ツールの読み取りが 1 まとまりのために丸ごと失敗する | `source` を enum で検査（422）し、DB にも CHECK を足す |
| **C6** | `review.py:494-497, 508-516`（同じ `client_token` でも、その行が**その対象の最新でない**／まとまりが `decided` でないと 409） | 設計 §3.1・§3.2 は「同じ `client_token` で再送 → **200**（既存を返す）」。実装は、再送の前に同じ枚へ別の判断（まとまりの `decide` 等）が入っていると 409 `client_token_conflict` を返す。画面の楽観的更新の後始末が「競合」扱いになる。なお §0.8 D3 の「一意制約違反は既存行を返す」は無いが、`_token_row` は `BEGIN IMMEDIATE` の中で走る（`store.py:97`）ので、別プロセスでも 2 本目は 1 本目の COMMIT を待ってから行を見つけて再生する。**今の錠の取り方では実際上到達しない守りの穴**で、優先度は低い | 遅れて届いた再送が、成功していた判断に対して赤い帯を出す | 同じ token で**中身が同じ**なら、最新かどうかに関わらず 200 で既存を返す。`IntegrityError` の変換は将来の多接続化のときに |
| **C7** | `review.py:372-376`（`subject_type='group'` の行は `supersedes=None`） | 指示書 §2.3-10: **枚の行の `supersedes` は正しい**（`_latest_asset_decision` の `seq` 降順の直前行を指す。`review.py:88-93, 365-370`）。**まとまりの行は鎖がつながらない**。`reopen` → 再 `decide` の 2 本目の行は前の行を指さない。§0.8 C11「同じ subject の直前の行」の半分 | まとまりの判断の履歴を辿る側（P6 の要求）が、どれが差し替えか分からない | `_decide_group` でまとまりの直前行（`subject_type='group' AND subject_id=?` の `seq` 降順）を `supersedes` に入れる |
| **C8** | `api/export.py:37-38`（`scope=all` は **GET でもファイルを書く**） | GET に副作用。他ツールが読むだけのつもりで `GET /api/export/review.json` を叩くたびに `<data>/export/review.json` が書き直される（設計 §3.4 は GET と POST の両方を「書く口」として並べているので、設計どおりではある） | 読み取りが書き込みを伴い、A1 とは逆に「古いファイルが読まれる」ことは無いが、同時に GET されると `os.replace` を取り合う | GET は返すだけ、POST だけが書く、に分ける（設計 §3.4 の修正提案として） |
| **C9** | `review.py:315-351`（理由の `label` / `active` を変えても、どのまとまりの `changed_at` も動かない） | `reason_label` は「書き出し時点のマスタ」（G8）だが、改名しても**次に判断が入るまで**契約ファイルは古い label のまま。点検 B1-(d) が「reopen と label 変更は `created_at` では検出できない」と指摘した後半が未対応 | 改名したのに他ツールが古い語を使い続ける | `patch_reason_code` でその理由を参照する `decision.group_id` と `group_item` から影響したまとまりを引き、`changed_at` を更新する（A1 と同じ関数） |

**確かめた結果、問題なし（コード上。実行はしていない）**:
- §2.3-11 Host / Origin / Content-Type: middleware は `create_app()` の `app` 全体に掛かり（`app.py:53-68`）、ルーターもその `app` に載る（`app.py:70-72`）。`PATCH /api/reason-codes/{id}` も GET/HEAD/OPTIONS 以外なので対象。`tests/test_review.py:516-537` が 5 つの POST で 403 を固定している。**実 HTTP では叩いていない**。`[::1]` が `split(":")[0]` で壊れる点は 2 回目の点検 I7 で既報なので繰り返さない。
- §2.3-12 参照切れ: `app.py:80-87` の `_primary_path` は**`missing_at` を見ている**（P5-0 の申し送りは古い）。`/file` と `/thumb` は `os.path.exists` で 404（`app.py:169,177`）。`/graph` は `png_meta.read_png` が `OSError` を `error` に畳む（`png_meta.py:67-72`）ので 404「グラフが無い」になる（文言は誤解を招くが 500 ではない）。
- §2.1-1 走査: `scan.py` と `store.register` / `mark_missing` / `set_roots` は `asset.review_*` / `decision` / `review_group` に**一切触れない**（`store.py:201-327`）。内容が入れ替わっても古い `asset` の行は残る。別プロセスの走査が判断を消す経路は**コード上は無い**（ただし C1）。
- §2.1-5 `reconcile()`: `asset` の 4 列を台帳の最新行（`seq` 降順）から導き、違う行だけ更新し件数をログに出す（`review.py:163-185`）。`test_review.py:218-262` が壊した写しの復元と時計逆行を固定している。まとまり側を組み直さない理由（reopen を打ち消す）は妥当。
- §2.3-9 境界: 上記 A の末尾。
- `supersedes`（枚）: 上記 C7。

---

## D. 軽微

確認はいずれも引用行を読めば足りる。実行で結果が変わる項目は無い。

| # | 場所 | 問題 | 提案 |
| --- | --- | --- | --- |
| D1 | `export.py:307`（`created_at` が契約の形でなければ **`db.now()` で埋める**） | 決定性（§3.4）に穴。壊れた `created_at` の行があると、2 回の書き出しが `generated_at` 以外でも違う | `None` にして検証に落とす（嘘の時刻を書かない） |
| D2 | `review.py:70,88-93`（`clear` でも `note` を受けて保存）、`export.py:402-411`（`verdict: null` と一緒に `note` を出す） | 「理由は無視して NULL」（§3.1）だが `note` は残る。契約の `assets[].note` に「取り消しのメモ」が出る | `clear` では `note` も捨てるか、仕様として §3.1 に書く |
| D3 | `export.py:345-347`（`include_tags=true` で `tags: []`） | §0.8 D5 は「未計算」と「無い」を区別するために `null` を求めた。契約の `tags` は `array` なので `[]` しか出せず、読む側は「タグが無い」と読む | 契約の `tags` を `["array","null"]` にするか、P4 まで `include_tags=true` を 422 にする |
| D4 | `review.py:234-266`（`cursor` は OFFSET の整数） | §0.8 D11 の「`cursor` は `(created_at, id)` のキーセット」が未反映。一覧の途中で行が増えると重複・欠落する | P5-2 の一覧画面の前にキーセットへ |
| D5 | `review.py:681-689` と `export.py:190-197`（`_affected_groups` / `_affected` が二重） | 「影響したまとまり」の定義が 2 か所にある。A1 を直すときに 1 か所にまとめる | `ReviewService` 側に寄せ、`ExportService.mark` は ID だけ受ける |
| D6 | `review.py:291`（`GET /api/reviews` が `client_token` を返す） | 再送用の鍵が読み出し API に出る。害は小さいが不要 | 省く |
| D7 | `db.py:51-60`（`changed_at` / `exported_at` は壁時計のマイクロ秒） | 点検 B1-(c) の「時計が戻る」経路が残る。NTP 補正で `changed_at < exported_at` になれば、その変更は拾われない | `review_group.changed_seq INTEGER` にして `decision.seq` と同じ発番にする |
| D8 | `review.py:207-223`（`asset_ids=[]` のまとまりを作れる）、`review.py:458-463`（空の `items` は過不足なしで通る） | 0 枚のまとまりを `all_rejected` で決定できる | `asset_ids` が空なら 422 |
| D9 | `api/groups.py:24`（`asset_ids` が文字列だと `list()` で 1 文字ずつに割れる） | 422 にはなるが、`details.missing` に 1 文字ずつ並ぶ | `isinstance(list)` を見る |
| D10 | `db.py:11-12`（「判断の書き手は 1 プロセスに限らない」）↔ `review.py:8`（「`review_state` の書き手はここだけ」） | 2 つの docstring が逆のことを言う。C1 を直せば後者が正 | `db.py` の文を「場所と来歴の書き手は複数プロセス。判断と写しはサーバだけ」に |
| D11 | `export.py:185-188`（Timer スレッドの例外が `logging` を通らない） | B2 の失敗が標準エラーにしか出ない。`uvicorn` のログに残らない | `log.exception` |
| D12 | `review.py:189-227`（`create_group` に `_require_human` が無い）、`api/reviews.py:54-62`（理由マスタの追加・変更も同様） | 設計どおり（403 は `reviews` と `decide` だけ）だが、**エージェントが理由の `label` を改名・`active=0` にできる**。人の語彙が外から変わる | G3 で確認 |

---

## E. 設計と実装のずれ（§2.5）

### E.1 `p5-design.md` §0 の各項目

| 項目 | 状態 | 場所・根拠 |
| --- | --- | --- |
| **A1** `assets[].kind` を必ず出す | **反映** | `export.py:323`。`test_export.py:281` |
| **A2** actor はヘッダだけ・無ければ agent・本文は無視 | **反映（API）／未反映（画面）** | `api/__init__.py:30-32`、`test_review.py:158-181`。ただし **P5 の画面が無い**（`apps/gui/app.js` にキープ／ボツの UI も `X-Image-Reviewer-Actor` を付ける経路も無い）。「画面は全ての状態変更要求にヘッダを付ける」は主語が存在しない |
| **B1** `changed_at` / `exported_at`、同じ取引で更新 | **半分** | 列と判定はある（`db.py:126-130`、`export.py:170-175`）。**1 枚の判断と、影響した他のまとまりで `changed_at` を更新しない**（A1） |
| **B2** 影響したまとまり＝和集合 | **半分** | メモリ上の `mark()` では和集合（`review.py:681-689`）。DB の印は和集合でない（A1） |
| **B3** `open` も書き出す（`decision` null、未判断の `verdict` null） | **反映** | `export.py:284-303`。`test_export.py:264-284` |
| **B4 / G9** 結論が変わるときだけ reopen、理由だけなら decided のまま | **半分** | 2 条件は反映（`review.py:633-640`）。`all_rejected`＋keep と `selected`＋clear が漏れる（A2） |
| **C2** `policy` / `source` の入口、まとまりの理由の列 | **半分** | `policy` は検査あり、列は v2 で追加（`db.py:240-259`）。`source` は検査無し（C5） |
| **C3** `decided` への再 `decide` は 409、reopen は判断を残す | **反映** | `review.py:122-124, 674-679`。`test_review.py:330-338, 408-426` |
| **C5 / C6 / G5 / C7 / G6 / C9 / C10** 差分表・ヒートマップ | **対象外（P5-2 / P5-3）** | `compare.py` は無い |
| **C8 / G3** numpy をこの段で入れる | **未反映** | `pyproject.toml:6-10` に無い。P5-2 まで要らないので実害は無いが、§0.1 は「この段で」と言う |
| **C11** `seq` で最後を決める、`supersedes` を自動で入れる | **半分** | `seq` は反映（`db.py:198,213`、`review.py:605-610`）。`supersedes` は枚の行だけ（C7） |
| **C12** `applies_to` 不一致は 422 | **反映** | `review.py:423-426`。`test_review.py:97-109` |
| **C13** ルーター＋`app.state`、素 JS、ULID | **反映（ルーター・ULID）／該当なし（画面が無い）** | `api/*.py`、`app.py:44-50`、`db.py:32-43` |
| **C14** (1) まとまりを作る画面 (2) 理由マスタは API のみ (3) 保留 (4) 日次 (5) `folder:` / `request:` は 422 (6) `locations[]` に一本化 (7) P7/P8 欄は null (8) 契約に `clip` / `llm` | (1) **未反映**（画面無し） (2) 反映 (3) 未反映 (4) **未反映**（日次の仕組みは無い。`write_all` は手動のみ。起動時に回収するのは `groups/*.json` だけ） (5) 反映（`export.py:50-58`） (6) 反映（`export.py:340-343`。ただし**契約から `path_map` は消えていない** `schema:66-70`） (7) 反映（`export.py:335-336`） (8) **未反映**（契約に `clip` / `llm` は無く、書き出しも出さない。`test_prototype.py:133-135` のとおり `analyze_graph` は `clip` / `llm` を読めている） |
| **C15** 要るテスト 14 件 | 下の F を参照 | 14 件中 11 件相当はある。「同じ秒に 2 件」は無い。「落ちて起動で出る」は空振り |
| **C16** SSE 最小（`GET /api/events`） | **未反映** | ルーターに無い。§4 の 6 も未反映。画面が無いので今は困らない |
| **D3** 一意違反は既存を返す、中身が違えば 409 | **半分** | 409 はある。`IntegrityError` の変換は無い（C6。今の錠では到達しない） |
| **D4** 列名を `decided_*` に | **未反映** | `db.py:144-145` は `reviewed_at` / `reviewed_by` のまま。API と契約は `decided_*`（`review.py:706-707`）。表示上は揃っている |
| **D5** `tags` は既定で鍵ごと省く | **反映（省く）／半分（true のとき `[]`）** | `export.py:345-347`。D3 |
| **D9** builtin の `applies_to` は 422 | **反映** | `review.py:337-339` |
| **D10** ID だけ積んで実行時に読み直す | **反映** | `export.py:148-161` |
| **D11** `cursor` はキーセット、`title` 200 | **半分** | `title` は反映（`review.py:204`）。`cursor` は OFFSET（D4） |
| **G4** 既定の「まとまりごとボツ」理由を作らない、ボツ 8＋その他 | **反映** | `reasons.py:21-34` |
| **G7** reopen は枚の判断を消さない | **反映** | `review.py:674-679` |
| **G8** label はマスタを引く | **反映** | `reasons.py:64-67`、`export.py:328`。ただし C9 |
| **G11** `scope=asset:{id}` は読むだけ | **反映（口）／未反映（契約）** | `api/export.py:36-39`。**契約の `scope.kind` に `asset` が無い**ので `scope` を鍵ごと省く（`export.py:268-273`）。読む側は「何の範囲か」を文書から知れない |
| **§0.1 P5-0「サーバ経由の走査（別プロセスの `save()` をやめる）」** | **別解で反映** | `cli scan` は今も別プロセスで `Store` を開く（`cli.py:27-39`）。「行を書くので消えない」に置き換えた。設計の文言は直っていない。C1 の副作用も残る |
| **§0.7 numpy / `Image.getdata()` の注意** | 対象外（P5-3） | — |
| **§2 `comparison_cache`** | 対象外（P5-3） | — |
| **§3.3 `DELETE /api/reason-codes/{id}` は 405** | **偶然反映** | DELETE の経路自体が無いので FastAPI が 405 を返す |
| **§8 100ms** | **未計測** | H |

### E.2 `docs/` と実装の食い違い（報告のみ。直していない）

| 場所 | 記述 | 実装 |
| --- | --- | --- |
| `README.md:23` | `uv run pytest -q  # 21 件` | 88 件 |
| `README.md:13` | 「状態: プロトタイプ…点検は 1 回目まで完了」 | 点検 2 回＋P5 設計点検、P5-0 / P5-1 実装済み |
| `README.md:26` | 「キープ / ボツ、比較…は未実装」 | キープ / ボツ・まとまり・書き出しは API として実装済み（画面は無い） |
| `README.md:100` | 「Python 3.12」 | `pyproject.toml:5` は `>=3.12`、指示書は 3.14。**実行環境の版は確かめられなかった** |
| `README.md:100-101` | 「前面は素の TypeScript + Vite」 | `apps/gui/app.js` は素の JS でビルド無し（§0.7 C13 の決定どおり） |
| `README.md:18-24, 109-113` | 動かし方に `migrate-from-json` が無い | `cli.py:260-265` にある |
| `README.md:121` | 「順序は P1 → P2 → P3 → P5」 | `p5-design.md` §0.1 と指示書は P5-0 → P5-1 → P5-2 → P5-3 を最初に |
| `design.md:1353-1372` §14 | P0 に「SQLite とマイグレーション」、P5 は 1 段で比較まで含む、着手は P1 → P2 → P3 → P5 | `p5-design.md` §0.1 は P5-0（SQLite 化）〜P5-3 の 4 段で、合格の線は P5-2。§14 の表と着手順は未更新 |
| `design.md:1315-1339` §13 | `services/review.py`、`services/export.py`、`models.py`、`cli.py` に多数のコマンド | 実装は `src/image_reviewer/review.py` 等の平らな置き方。`models.py` は無い（pydantic を使っていない） |
| `design.md:1301` §13 | `export\index.json` | 無い（P5 の範囲外だが §13 に「P5 で」とは書かれていないので矛盾ではない） |
| `p5-design.md:280-299` §4 | 「`decision.created_at > export の mtime`」「表を増やさない」 | §0.3 で置き換え済み。本文は未修正（§0 が正と冒頭に書いてあるので矛盾扱いにはしない） |
| `p5-design.md:457-470` §9 | `compare.py`、`apps/gui/*.ts` | P5-2 まで無い |
| `cli.py:1-7` docstring | 「プロトタイプでは `scan` と `serve` だけ」 | `capture` と `migrate-from-json` がある |
| `store.py:360` docstring | `set_review_state` が「唯一の口」 | `ReviewService` が書き手。C4 |
| `export.py:17` docstring | 「COMMIT 直後に落ちても、次回の起動で追い付く」 | 一度も書き出していないまとまりだけ。A1 |
| `tests/test_export.py:13-15` docstring | 「本物の `jsonschema` での検証は `uv run --no-project --with jsonschema` で別に行う（作業報告を参照）」 | **作業報告のファイルは見つからなかった**（`docs/p5-work-report.md` ほか 8 通りの名前を試した）。検証したという記録が残っていない |
| `prototype-notes.md:8` | 「テスト: `uv run pytest -q`（9 件）」 | 88 件（プロトタイプ記録としては当時の値） |
| `schemas/review-export.schema.json:66-70` | `path_map` が残っている | 書き出しは出さない（`export.py:339-343`）。C14-(6) の「一本化」の契約側が未了 |
| `schemas/review-export.schema.json:32-45` | `scope.kind` に `asset` が無い | `scope=asset:{id}` の口がある（G11）。書き出しは `scope` を省く |

---

## F. テストが守っていないもの（§2.4）

| # | テスト | 何を主張しているか | 実際に守っているか | 直し方 |
| --- | --- | --- | --- | --- |
| **F1** | `tests/test_export.py:234-258` `test_startup_flush_writes_a_decision_committed_before_a_crash` | 「COMMIT 直後に落ちても次回の起動で書き出しが出る」 | **空振り。** 作ったばかりのまとまり（`exported_at IS NULL`）で試しているので、`changed_at` の更新が無くても `flush_dirty()` が拾う。**一度書き出した後**に 1 枚の判断を入れて落とすと、同じテストは**落ちる**（A1）。設計の中心的な主張が、最も普通の状態で確かめられていない | `exporter.flush_dirty()` を 1 回呼んでから判断を入れ、`close()` → 再起動 → ファイルの `review_state` を見る |
| **F2** | `tests/test_export.py:193-207` `test_a_group_decision_dirties_the_groups_sharing_its_assets` | 「まとまりの決定が、同じ画像を含む他のまとまりも書く」 | メモリ上の `flush()` だけ。DB の `changed_at` を見ていないので、落ちた後は g2 が漏れる（A1） | `flush()` の代わりに `close()` → 新しい `ExportService` の `flush_on_start` で g2 が出ることを見る |
| **F3** | `tests/test_review.py:490-511` `test_decision_survives_a_concurrent_store_scanning`、`tests/test_store_sqlite.py:355-390` | 「別プロセスの走査が判断を消さない」 | 名前は「concurrent」だが**同一プロセスで順番に**走る 2 接続。走査が `review_*` に触らないことの確認としては十分だが、別プロセス・同時・`BEGIN IMMEDIATE` の待ち（`busy_timeout`）は一度も通っていない。後者は `set_review_state` と手書きの `INSERT` で台帳を作っており、`ReviewService` を通していない | `subprocess` で `cli_main(["scan", ...])` を別プロセスで走らせ、その間にサーバ側の `Store` が `apply_asset` を入れる。C1 のとおり CLI 側でも `create_app()` が走ることに注意 |
| **F4** | `tests/test_review.py:187-213`（`client_token` の再送） | 「再送で行が増えない」 | **本当に確かめている**（`len(decisions_for) == 1`、`count(*) WHERE client_token=?`）。ただし**逐次**。並行（§2.1-4）は `Store._lock` で直列化されるので同一プロセスでは同値だが、未確認 | `ThreadPoolExecutor` で同じ要求を 8 本同時に投げ、行数 1・全応答の `decision_id` が同じ、を足す |
| **F5** | `tests/test_export.py:155-176` `test_only_the_affected_group_files_are_written` | 「他のファイルの mtime が変わらない」 | **本当に確かめている**（`st_mtime_ns` と `read_bytes()` の両方）。問題なし |
| **F6** | `tests/test_review.py:385-403` `test_group_decide_is_one_transaction` | 「途中で失敗したら 1 行も入らない」 | 1 枚目の `_materialize_asset` で落とすので、`decision` 1 行の `ROLLBACK` は見ている。まとまりの行や `UPDATE review_group` の**後**で落ちる経路は見ていない | `_conflict_groups` を落とす（まとまりの `UPDATE` の後）版を足す |
| **F7** | `tests/test_export.py:38-116` 自前のスキーマ検査 | 「契約に合う」 | `$ref` / `enum` / `const` / `required` / `additionalProperties` / `pattern` / `type` / `oneOf` / `anyOf` / `items` は見るが、**`minLength` / `maxLength` は見ない**。`jsonschema` での検証は記録が無い（E.2） | `jsonschema` を dev 依存に入れて本物で検証する（`uv run --no-project --with jsonschema` を CI 相当の手順に書く） |
| **F8** | `tests/test_review.py:431-446` | 「理由だけの変更（同じ verdict）では戻らない」 | この 2 枚目の `apply_asset` は**既に `open` に戻ったまとまり**に対して行っているので、「decided のまま」ではなく「open のまま」を見ている。`test_changing_only_the_reason_keeps_the_group_decided` が別に守っているので実害は無い | 2 枚目を削るか、別の decided なまとまりで行う |

**今すぐ要るのに無いテスト**（点検 C15 の 14 件と突き合わせ。C15 の「同じ秒に 2 件」はまだ無い。「落ちて起動で出る」は F1 のとおり空振り）:

1. 既に書き出し済みのまとまりへの 1 枚の判断 → `close()` → 再起動で出る（A1。**最優先**）
2. 同じ秒に 2 件の判断を入れて両方が書き出しに出る（C15-5。`stamp()` のマイクロ秒を固定する）
3. `all_rejected` の 1 枚を `keep` → `reopened_group_ids` に入る（A2-a）
4. `selected` の枚を `clear` → `open` に戻る、`selected_asset_ids` が空（A2-b）
5. `migrate-from-json` で `review_state='kept'` を取り込んだ後に `ReviewService` を作っても `kept` が残る（B1）
6. `write_group` が 1 件失敗しても残りが書かれ、失敗分が次に再試行される（B2）
7. `POST /api/groups {"source":"x"}` が 422、通った文書がスキーマに落ちない（C5）
8. まとまりの行の `supersedes` が前のまとまりの行を指す（C7）
9. `client_token` の並行 8 本で行が 1（F4）
10. `cli scan` を**別プロセス**で走らせても判断が残り、`export/groups/*.json` を取り合わない（F3・C1）
11. 100ms の実測（§8。`pytest` ではなく計測スクリプトとして。H の手順）
12. `GET /api/export/review.json?scope=all` の文書を**本物の `jsonschema`** で検証（F7）

---

## G. 依頼者への質問

| # | 論点 | 私の推奨 |
| --- | --- | --- |
| G1 | `store.json` から取り込んだ `review_state` を、台帳の行として**遡って作る**か（`actor='human'`、`created_at=reviewed_at`、注記つき）、取り込み時に**捨てる**と決めるか（B1）。いま `kept` の 1 枚がどちらの由来かを B1 の SQL で確かめてほしい | 行を作る。「判断は失わない」が設計の第一原則 |
| G2 | `asset_location.kind`（`reference` / `managed`）と `asset.source` の置き場（P5-0 申し送り）。書き出しは `export.py:340` で **`"reference"` を固定**で出し、`source` は `asset_meta.source` に間借りしている | `asset_location.kind TEXT NOT NULL DEFAULT 'reference'` と `asset.source TEXT NOT NULL DEFAULT 'scan'` を v3 で足す（P2 の取込で `managed` が要る前に）。書き出しはその列を写す |
| G3 | `POST /api/groups`・`POST/PATCH /api/reason-codes` を**エージェントにも開けておく**か（D12）。P6 ではエージェントが要求からまとまりを作るので `groups` は開ける必要がある。理由マスタの改名・無効化は人の語彙 | `reason-codes` の変更は `human` だけに |
| G4 | `locations` は `include_paths=false` のとき `null`（契約の現行どおり）か、`tags` と同じく**鍵ごと省く**か（指示書 §2.2-6）。契約の中で `tags`（省く）と `locations`（null）が別の作法 | **省く**に統一し、契約の `description` を「`include_paths=false` のときは鍵ごと省く」に直す。`null` は「値を出す欄が無い」を意味し、「出さない選択をした」と区別できない |
| G5 | `scope=asset:{id}` を契約の `scope.kind` に足すか（G11 の帰結）。今は `scope` を省いて逃げている | 足す（`abi` は上げない。設計段階の方針どおり） |
| G6 | `GET /api/export/review.json?scope=all` が**ファイルを書く**のを続けるか（C8） | GET は返すだけにする |

---

## H. 私が確かめられなかったこと

**実行はゼロ。** 以下は依頼者側で打てば白黒が付く。番号は指示書 §2 の番号。

| § | 確かめること | 手順と、何を見れば決まるか |
| --- | --- | --- |
| 2.1-1 | 別プロセスの走査が判断を消さない | サーバを 8791 で上げ、`POST /api/reviews` で 1 枚 `keep` → 別窓で `uv run image-reviewer scan --root <小さいフォルダ>` → `GET /api/assets/{id}` の `review_state` と `SELECT count(*) FROM decision`。**コード上は消えない**。同時に、`scan` の標準出力／サーバのログに「現在値の写しを台帳から組み直しました」が**CLI 側にも**出るか（C1 の証拠） |
| 2.1-2 | 落ちても書き出しが漏れない | A1 の手順。**コード上は漏れる**（既に書き出し済みのまとまりで） |
| 2.1-3 | 100ms | サーバを上げ、1 つのまとまり（8 枚）を作って `flush` させた後、`POST /api/reviews` を 50 回（`client_token` を毎回変える）打ち、応答時間の中央値と最大値を取る。**2 秒のタイマーが発火する瞬間を跨ぐ**よう 3 秒ごとに打つ（C2 の錠の影響を見る）。`scope=all` の `GET` を裏で回した状態でも測る（B3 の共有接続の影響） |
| 2.1-4 | 再送に耐える | 同じ `client_token` の `POST /api/reviews` を 8 本同時（`ThreadPoolExecutor`）→ `SELECT count(*) FROM decision WHERE client_token=?` が 1、全応答が 200 で同じ `decision_id`。**コード上は 1 のはず**（同一プロセスは `Store._lock`、別プロセスでも `BEGIN IMMEDIATE` で直列化され、2 本目は 1 本目の行を見つけて再生する。未確認） |
| 2.1-5 | `reconcile()` | `UPDATE asset SET review_state='rejected' WHERE id=?` で壊して再起動 → ログの件数と `GET /api/assets/{id}`。**コード上は直る**。ただし C3（直しても書き出しの印は付かない） |
| 2.2-6 | スキーマ検証 | `uv run --no-project --with jsonschema python -c "import json,jsonschema,urllib.request as u; s=json.load(open('schemas/review-export.schema.json',encoding='utf-8')); d=json.load(u.urlopen('http://127.0.0.1:8791/api/export/review.json?scope=all')); jsonschema.Draft202012Validator(s).validate(d); print('ok', len(d['assets']), len(d['groups']))"`。`open` なまとまりと `scope=group:<id>` でも。**コード上は通る見込み**（全鍵が契約の `properties` にあり、enum も揃う）。例外は C5（`source` が外から入ったとき）と D1 |
| 2.2-7 | 決定性 | `scope=all` を 2 回取り、`generated_at` を落として `diff`。**コード上は一致**（`ORDER BY id`、`position`、`position, id` で並びが固定） |
| 2.3-11 | 403 | `curl -X POST http://127.0.0.1:8791/api/reviews -H "Host: evil.example" -d "{}"` ほか 3 種。**コード上は 403** |
| — | 実データの件数（263 / 183 / 英訳 1 / kept 1） | 読めていない。B1 の SQL とあわせて `SELECT count(*) FROM asset; SELECT count(*) FROM asset_meta WHERE meta_json <> 'null'; SELECT count(*) FROM decision;` |
| — | Python の版（3.14）と `sqlite3.sqlite_version` | `uv run python -c "import sys,sqlite3;print(sys.version, sqlite3.sqlite_version)"` |
| — | ファイルの更新時刻 | `Get-ChildItem -Recurse src,tests,docs,schemas \| Sort-Object LastWriteTime` |

読んでいないもの: `docs/design.md` の §13 末尾〜§14 以外、`docs/comparison.md`、`docs/frontend-design.md`、`docs/review-triage*.md`、`docs/review-report-deepseek.md`、`thumbs.py`、`png_meta.py` の 80 行目以降、`apps/gui/index.html` / `styles.css`、`tools/probe_p5.py` の 40 行目以降。

---

## 最も重大な 3 件

### 1. 1 枚の判断が DB に「書き出し待ち」の印を残さない（A1。**実行で白黒を付けるべき筆頭**）

設計 B1 は「判断と同じトランザクションで `changed_at` を更新する」ことで「落ちても漏れない」を主張したが、`apply_asset` は `review_group` に触らず、印はプロセスのメモリ（`_pending`）にしか無い。普通に `Ctrl+C` で止めただけでも最後の 2 秒の判断は契約ファイルに出ず、以後どの起動でも拾われない。これを守るはずのテストは「一度も書き出していないまとまり」で試しているので緑になる。私は実行できなかったが、A1 の手順で 5 分あれば確かめられる。

### 2. 「結論が変わるときだけ open に戻す」が、結論が変わる 2 つの経路を見逃す（A2）

`all_rejected` の 1 枚をキープしても、選んだ 1 枚を取り消しても、まとまりは `decided` のまま前の結論を引き継ぐ。契約ファイルには `decision: "all_rejected"` と `review_state: "kept"` が同じ文書に並ぶ。設計 §0.4 の列挙が 2 条件だったのを実装がそのまま固定したもので、「設計では直したのに実装で半分」の典型。他ツールが読む唯一の口の信頼性に直接効く。

### 3. 取り込んだ判断は、次の起動で `reconcile()` に消される（B1）

`migrate-from-json` は `review_state` を写すが台帳を書かない。`ReviewService` は起動のたびに「台帳が正」で写しを組み直すので、`store.json` 由来の `kept` は INFO ログ 1 行を残して `unreviewed` に戻る。しかも C1 のとおり `create_app()` が CLI の読み込みで走るため、「次の起動」は `serve` に限らず `scan` でも起きる。「判断は失わない」が P5-0 の目的だったのに、取り込みそのものが失う経路になっている。実データの `kept` 1 枚が取り込み由来か API 由来かは、B1 の SQL で分かる。
