# P5 実装の監査報告（実行込みのやり直し）

- 監査した版: 2026-10-15 の作業ツリー（git 管理外）。更新時刻は実行して取った: `src/image_reviewer/compare.py` 19:52、`app.py` 19:10、`store.py` / `db.py` 19:08、`export.py` / `cli.py` 18:49、`review.py` 16:24、`apps/gui/styles.css` 20:18、`README.md` 20:16。環境: uv 0.12.19 / Python 3.14.7 / SQLite 3.53.1 / numpy 2.5.4 / Pillow 12.3.0 / Node 24.19.0。
- **実行できたかどうか: 今回は全部実行できた。** `Bash` / `PowerShell` / `uv run` / `node` / ブラウザ（Chrome headless）のいずれも拒否されなかった。実行したもの（コマンドの数 **約 60**。一時ファイルは `.tmp-audit-redo/` に置いた。ソースは編集していない。実データ `.data/` は `mode=ro` で読み、書く試験はすべて `.tmp-audit-redo/data-*` のコピーで行った）:
  - `uv run pytest -q` を **2 回連続**: **169 passed, 1 warning**（17.3 s / 17.7 s）。`tests/.tmp` の個数は **0 → 0 → 0**（増えない）。warning 1 件は `.venv\Lib\site-packages\fastapi\testclient.py:1` の `StarletteDeprecationWarning`（`httpx` + `starlette.testclient` の非推奨。**アプリの外**。`httpx2` を dev 依存にすれば消える）。
  - 実データ（読み取り専用）: `user_version=3`、asset **263**、来歴あり **183**、`decision` **3 行**（すべて同じ 1 枚: clear → reject → keep）、`kept` **1**、`review_group` **0**、`reason_code` 12、英訳あり **1**、`phash IS NULL` **263 / 263**、`comparison_cache` **1 行**、参照切れ 0。**台帳の無い写し（前回 B1 の SQL）は 0 行**。
  - サーバを `IMAGE_REVIEWER_DATA=<コピー>` で 8791〜8794 に上げ、API を叩く Python（`.tmp-audit-redo/p5_api.py`）: 403 ×7、入力検査 ×3、A2 の 2 経路、C7、C6、同じ `client_token` の **8 本同時**、C9、D2、C8、決定性、B2（ファイルを掴んだまま判断）、**100ms の実測**（30 件 ×2 条件）。
  - 落とす / 止める / 組み直す（`p5_crash.py`、`p5_stop.py`）: **書き出し済みのまとまりへ 1 枚の判断 → 73 ms 後に `taskkill /F`** → 再起動。Ctrl+Break による終了（python.exe 直起動 / `uv run` 経由）。壊した写しからの起動。
  - `migrate-from-json`（`p5_migrate.py`）: 3 枚の JSON（kept 1 / rejected 1）を取り込み → 2 回目の取り込み → `ReviewService()`。
  - 別プロセスの `scan` をサーバ稼働中に実行（`.tmp-audit-redo/scanroot` の 2 枚）。CLI が `create_app()` を走らせるかの確認。
  - **本物の `jsonschema`**（`uv run --no-project --with jsonschema`）で `scope=all` / `all + paths/tags/prompts` / `group:` / `asset:` の 4 文書を検証。
  - ComfyUI（**8188 で稼働中。0.39.2**）に対して `POST /api/userdata`（指示書 §3-5）。
- 総合判定: **使える。** 前回の A1 / A2 / B1 / B2 / B3 は**実行で**直っていることを確かめた。新たに分かったのは、(1) 書き出しが失敗するたびに **`.tmp` が `export/groups/` に溜まる**（再試行のたびに 1 つ。実行でしか分からない）、(2) 前回の C1 / C6 / C8 / C9 / D2 / D3 / D12 は**そのまま**（§R）、(3) 100ms は**余裕で満たす**（中央値 3 ms）。使う前に直すべきものは (1) と C9 だけで、どちらも小さい。

---

## A. 設計の主張が成り立たない（必ず直す）

**無し。** 前回の A1（1 枚の判断が `changed_at` を動かさない）と A2（`all_rejected`＋keep / `selected`＋clear の取りこぼし）は、**実行で直っていることを確かめた**（§R-A1、§R-A2）。

---

## B. 重大（静かに間違える・遅い）

**無し。** 前回の B1 / B2 / B3 は直っている（§R）。

---

## C. 中程度（実行で新たに分かったこと）

| # | 場所 | 問題 | 利用者の側で何が起きるか | 実行したコマンド / 再現手順 | 提案 |
| --- | --- | --- | --- | --- | --- |
| **C1** | `src/image_reviewer/export.py:126-132`（`_atomic_write`: `tmp.write_text` → `os.replace`。**失敗時に `tmp` を消さない**）、`:183-206`（`flush` は失敗を `_pending` に戻して**2 秒ごとに再試行**する。監査 B2 の修正そのもの）、`:129`（一時名に `threading.get_ident()` を含むので**再試行のたびに別名**） | 書き出し先の `groups/<id>.json` を他のプロセスが掴んでいる間（Windows では閲覧ソフトやウイルス対策で起きる。監査 B2 の想定どおり）、`os.replace` が `PermissionError` で落ちる。中身を書いた **`<id>.json.<pid>.<tid>.tmp` はそのまま残り**、2 秒後の再試行が**別名**でもう 1 つ作る。掴まれている限り **2 秒に 1 ファイル**増え、解除後に本体は書き直されるが `.tmp` は**誰も消さない** | `export/groups/` に `.tmp` が溜まる。3 分掴まれていれば 90 個。他ツールが `groups/*.json` を glob する分には混ざらない（拡張子が `.tmp`）が、フォルダは汚れ続け、起動時にも掃除されない | **再現した（実行）。** 8791 のサーバで、まとまりのファイルを `open(path, "rb")` で掴んだまま `POST /api/reviews` → **9.5 秒で `.tmp` が +4**（2 秒ごと）、解除 3 秒後に本体は書き直されたが `.tmp` は 5 個のまま。サーバのログには `WinError 5` の WARNING が **5 行**（再試行の回数と一致） | `_atomic_write` で `os.replace` を `try` で囲み、失敗したら `tmp.unlink(missing_ok=True)` してから投げる。加えて起動時（`flush_dirty` の前）に `export/groups/*.tmp` を掃除する。テスト: `os.replace` を `monkeypatch` で `PermissionError` にし、呼んだ後に `*.tmp` が 0 個であることを見る（`test_a_failing_group_does_not_stop_the_others_and_is_retried` は `write_group` ごと差し替えているので `.tmp` の経路を通らない） |
| **C2** | `src/image_reviewer/export.py:199`（`log.warning(...)`）、`src/image_reviewer/review.py:222`（`log.warning(...)`）、`cli.py:93`（`uvicorn.run(..., log_level="info")`）。**アプリ側の `logging` を設定している所が無い** | `image_reviewer.*` のロガーには handler が無く、WARNING 以上は Python の `lastResort`（stderr）に**素の文**で出る。INFO（`reconcile` の「0 行」など）は**どこにも出ない**。uvicorn の `INFO:` の行と形が違い、時刻も無い | 監査 B2 の「理由を `log.warning` に出す」は**出てはいる**が、`INFO:     ...` の中に時刻無しの日本語 1 行が混ざる形。「いつ失敗したか」が分からない。INFO の `reconcile` は `serve` では見えない | **実行で確認。** `server-p5-A.log` に `WinError 5` の行が 5 行（レベル名・時刻・ロガー名無し）。`server-crash-s3.log` の 1 行目に `現在値の写しを台帳から組み直しました: 1 行（監査 B1）…`（同じく素の文） | `cmd_serve` で `logging.basicConfig(level=INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")` を `uvicorn.run` の前に 1 回呼ぶ（uvicorn は `disable_existing_loggers=False` なので共存する）。CLI の `scan` / `migrate-from-json` でも同じ |
| **C3** | `src/image_reviewer/app.py:277`（`app = create_app()` が**モジュール読み込み時**に走る）、`cli.py:37`（`_store()` が `from .app import data_dir`）、`cli.py:292`（`cmd_migrate_from_json` も同じ） | 前回 C1 の**半分だけ**直っている。`_store()` は自前で `flush_dirty()` を呼ぶようになった（順序依存は消えた）が、`from .app import data_dir` の 1 行で **`create_app()` が走り、CLI プロセスの中に 2 本目の `Store`・`ExportService`・`ReviewService`（`reconcile()`）ができる**。`scan` を打つたびに、サーバと**別のプロセス**が `reconcile()` と `flush_dirty()` を走らせる（前回 C1 の「2 つのプロセスが同じ `export/groups/*.json` を `os.replace` し合う」はそのまま） | `scan` が余計な接続を 1 本開き、台帳を全件なめる（263 枚で 0.5 秒。1 万枚なら数秒）。印の付いたまとまりがあれば**サーバと同時に**同じファイルを書く | **再現した（実行）。** `uv run python -c "import image_reviewer.cli as cli; cli._store(flush=False)"` の前後で `'image_reviewer.app' in sys.modules` が **False → True**、`sys.modules['image_reviewer.app'].app.state.store is not st` が **True**、CLI の標準出力に `image_reviewer.review INFO 現在値の写しを台帳から組み直しました: 0 行` が出る（サーバではなく CLI が出した行） | `data_dir()` を `app.py` から `config.py`（または `store.py`）へ移し、`cli.py` は `app` を import しない。`app.py:277` は `uvicorn.run("image_reviewer.app:create_app", factory=True)` にして消す（前回 C1 の提案どおり）。`conftest.py` の `_close_prototype_app()` も不要になる |

**確かめた結果、問題なし（実行）**:

- **403（§2.3-11）**: `Host: evil.example` / `Origin: http://evil.example` / `Content-Type: text/plain` / ヘッダ無し（`{"detail": "判断は人が付けます", "details": {"actor": "agent"}}`）/ 本文の `actor: "human"`（無視されて 403）の 5 つすべて **403**。`PATCH /api/reason-codes` のミドルウェアも効く。
- **入力検査**: `source: "x"` → 422、`asset_ids: []` → 422、`asset_ids: "abc"` → 422（`asset_ids は配列です`）。前回 C5 / D8 / D9 は直っている。
- **決定性（§2.2-7）**: `scope=all` を 1.1 秒おきに 2 回取り、`generated_at` を落として **完全一致**（263 枚・4 まとまり）。
- **契約（§2.2-6）**: 本物の `jsonschema`（Draft 2020-12）で **4 文書とも 0 errors**。`scope` は `{"kind": "asset", "id": …}` まで出る（前回 G5 / G11 は契約側も直っている）。
- **再送（§2.1-4）**: 同じ `client_token` の `POST /api/reviews` を **8 本同時** → 全部 200、`decision_id` は **1 種類**、台帳は **1 行**。
- **100ms（§2.1-3）**: 8 枚の `pick_many` を作って書き出した後、`client_token` を変えつつ 0.5 秒おきに 30 件（2 秒のタイマーを何度も跨ぐ）: **中央値 3.0 ms / p90 22.3 / 最大 26.5**。`GET /api/export/review.json?scope=all` を裏で連打（813 回、中央値 11.3 ms）しながらでも **中央値 5.3 / 最大 26.2**。前回 C2（`mark()` が書き出しの錠を待つ）は**実測では見えない**（§R-C2）。
- **別プロセスの走査（§2.1-1）**: 8791 を上げたまま `uv run image-reviewer scan --root .tmp-audit-redo\scanroot`（既知 2 枚）→ 台帳 **86 行 → 86 行**、`review_state` 不変。`scan` 自体は 0.57 秒。
- **`reconcile()`（§2.1-5）**: サーバを止めて `UPDATE asset SET review_state='kept', reviewed_by='agent'` で壊し → 起動 → `GET /api/assets/{id}` は **rejected / human**、ログに WARNING（直す前 / 直した後の値つき。監査 B1 の修正どおり）。
- **C7**: reopen → 再 decide の 2 本目のまとまりの行が 1 本目を `supersedes` で指す（**True**）。`GET /api/reviews` に `client_token` は出ない（前回 D6 直っている）。

---

## D. 軽微

| # | 場所 | 問題 | 提案 |
| --- | --- | --- | --- |
| D1 | `tests/test_export.py:10-15`（docstring「本物の `jsonschema` での検証は `uv run --no-project --with jsonschema` で別に行う（作業報告を参照）」） | 作業報告は前回も今回も見つからない。今回私が走らせた（§C の「契約」）ので、**この報告がその記録**になる。`jsonschema` を dev 依存に足さない方針なら、せめて `tools/validate_export.py` に今回の 10 行を置く | `.tmp-audit-redo/validate.py` を `tools/` へ（コピー可） |
| D2 | `README.md:121`（「Python 3.12」）、`:127`（「前面の TypeScript + Vite」「5273」） | 実行環境は **3.14.7**（`pyproject.toml` は `>=3.12`）。前面は素の JS でビルド無し。前回 E.2 のまま | 更新 |
| D3 | `cli.py:93`（`uvicorn.run(... log_level="info")`）と `uv run` の組み合わせ | **`uv run image-reviewer serve` を Ctrl+Break で止めると、`uv` が先に終わり python（uvicorn）が後から終わる。** 画面はプロンプトに戻るが `lifespan` の `flush()` はその後に走る（実測: `uv` の終了後も `Application shutdown complete` まで進む。`uv` を `taskkill /F` しても子は生きていて `GET /api/health` が 200）。終了後すぐに `export/groups/*.json` を読む他ツールは**数十 ms 古い**ものを読むことがある | 害は小さい。README に「止めたあと 1 秒待つ」か、`serve` を `python -m image_reviewer.cli serve` で案内する |

---

## E. 設計・ドキュメントとのずれ

前回（`p5-audit-report.md` §E）の表のうち、**実行で状態が変わったもの**だけ:

| 項目 | 前回 | 今回（実行で確認） |
| --- | --- | --- |
| **B1 / B2** `changed_at` を同じ取引で、和集合 | 半分 | **反映**（§R-A1。hard kill 後の再起動で拾う） |
| **B4 / G9** 4 経路 | 半分 | **反映**（§R-A2） |
| **C2** `source` の検査 | 半分 | **反映**（422） |
| **C11** まとまりの `supersedes` | 半分 | **反映** |
| **C14-(6)** `path_map` | 契約に残る | **契約から消えている**（`export-all-full.json` が `locations[]` だけで検証を通る） |
| **G11 / G5** `scope.kind` に `asset` | 未反映 | **反映**（契約に `asset` があり検証を通る） |
| **G4** `locations` は `null`、`tags` は鍵ごと省く | 作法が別 | **そのまま**（`include_paths=false` で `"locations": null`、`tags` は無い）。実行で確認 |
| **D4** `cursor` はキーセット | 未反映 | **未反映**（`review.py:308, 340` は `OFFSET`） |
| **§8 100ms** | 未計測 | **達成**（中央値 3 ms） |
| **`README.md:23`** テスト件数 | 古い | **169 件で正しい**（実行で一致） |

---

## F. テストが守っていないもの

前回の F1〜F8 の再判定は §R。**今回、実行して初めて「守られていない」と分かったもの**:

| # | テスト | 何を主張しているか | 実際に守っているか | 直し方 |
| --- | --- | --- | --- | --- |
| **F1** | `tests/test_export.py:309` `test_a_failing_group_does_not_stop_the_others_and_is_retried` | 「1 つの失敗で残りを落とさない・再試行する」 | 守っている。ただし **`write_group` ごと差し替えて失敗させる**ので、`_atomic_write` の `os.replace` が落ちる本物の経路（C1 の `.tmp` 残り）を通らない | `os.replace` を `monkeypatch` で落とし、`*.tmp` が残らないことを足す |
| **F2** | `tests/test_export.py:667` `test_shutdown_flushes_what_is_still_pending` | 「終了時に書き出す」 | `TestClient` の lifespan（同一プロセス）で守っている。**実プロセスでも効く**ことを今回確かめた（§R-H 2.1-2）。十分 | — |
| **F3** | （無い） | ログの形（C2） | `caplog` のテストは `reconcile` の WARNING を見ているが、**`serve` で handler が無い**ことは誰も見ない | `cmd_serve` に `basicConfig` を入れたら、`caplog` ではなく `logging.getLogger().handlers` を見る |

---

## G. 依頼者への質問

| # | 論点 | 私の推奨 |
| --- | --- | --- |
| G1 | `.tmp` の後始末（C1）: 失敗時に消す＋起動時に掃除、の両方にするか | 両方。起動時の掃除は 1 行 |
| G2 | `GET /api/export/review.json?scope=all` がファイルを書く（前回 C8 / G6。**再現した**）のを続けるか | GET は返すだけ。前回と同じ推奨 |
| G3 | 古い `client_token` の再送が 409（前回 C6。**再現した**: 同じ枚に新しい判断が入った後の再送 → `409 client_token_conflict`）を仕様にするか。設計 §3.1 は「再送 → 200」 | 中身が同じなら 200 で既存を返す。画面の楽観的更新の後始末が赤くならない |
| G4 | 理由の改名（前回 C9。**再現した**: 改名後 3 秒待っても `changed_at` 不変、`groups/<id>.json` の `reason_label` は旧名のまま）を印にするか | 改名で参照するまとまりを `_touch_groups` する（A1 と同じ関数で 5 行） |
| G5 | `uv run` 経由の `serve` を `python -m image_reviewer.cli serve` に変えるか（D3） | README に 1 行書くだけでよい |

---

## H. 今回も確かめられなかったこと（＋できない理由）

| 項目 | 状態 | 理由 |
| --- | --- | --- |
| **Ctrl+C**（Ctrl+Break ではなく）での終了 | **未確認** | 別コンソールに `GenerateConsoleCtrlEvent(CTRL_C_EVENT)` を送る方法では uvicorn に届かなかった（Ctrl+Break は届き、`lifespan` の `flush()` まで走ることを **python.exe 直起動で確認**した。uvicorn は SIGINT と SIGBREAK を同じ経路で扱うので、Ctrl+C でも同じと見てよい） |
| **B3**（錠の外の読み）の**実 HTTP での競合** | **コードとテストで確認**（`export.py:164, 218, 250, 278` が `store.locked()`、`tests/test_export.py:364` が未コミット行を見ないことを守る） | 実 HTTP で「取引の途中」を狙って読むには `monkeypatch` が要り、プロセス外からは作れない。実測の 100ms（裏で GET を連打）で**壊れなかった**ことは確認 |
| 1 万枚規模の `reconcile()` / `flush_dirty()` の時間 | **未計測** | 実データは 263 枚。263 枚で `scan` 全体が 0.57 秒（CLI 側の `create_app()` を含む） |
| 指示書 §3-5: `control_after_generate` の復元、保留領域の別ボリューム | **できない** | 前者は ComfyUI での実生成が要る（8188 は稼働しているが、生成を走らせる権限は依頼に無い）。後者は P2 / 重複削除（P8）が未実装で、確かめる対象のコードが無い |
| 指示書 §3-5: `tabular-nums` が BIZ UDPGothic で効くか | **P5-2 の報告で扱う**（ブラウザを使う段） | — |

**指示書 §3-5 で実行できたもの**: `POST /api/userdata`（ComfyUI 0.39.2、8188）。`image-reviewer-audit-probe-20261016.json` を `overwrite=false` で書く → **200**（本文はファイル名）、同じ名前でもう一度 → **409 `File already exists`**、`GET` で戻る → 200、`DELETE` → **204**、`GET` → 404（**後始末済み**）。`metadata-findings.md` §6-4 / `workflow-reproduction.md` §3.2 の「既にあると 409」は**実機で正しい**。

---

## R. 前回の指摘の再判定

前回 = `docs/p5-audit-report.md`。行番号は**現物**に直した。

### 前回 A / B

| # | 前回の主張 | 再判定 | 根拠（実行） |
| --- | --- | --- | --- |
| **A1** | 1 枚の判断が `changed_at` を動かさず、落ちると漏れる | **直っている（再現しない）** | `review.py:124`（`apply_asset` の取引内で `_touch_groups`）、`:454-456`（`_decide_group`）、`:771-780`。実行: 書き出し済みのまとまり（`exported_at` 非 NULL）の枚を `keep` → **73 ms 後に `taskkill /F`** → ファイルは `unreviewed` のまま、DB は `kept`、`changed_at > exported_at` が **True** → 再起動 → ファイルが **`kept`**、`changed_at <= exported_at`。終了時の `flush()`（`app.py:58-70`）は python.exe 直起動＋Ctrl+Break で **245 ms で完了**し、`decided_at` が新しい値でファイルに出た |
| **A2** | `all_rejected`＋keep と `selected`＋clear を取りこぼす | **直っている（再現しない）** | `review.py:703-722`（4 経路）。実行: (a) 2 枚 `pick_one` を両方 reject で決定 → 1 枚 `keep` → `reopened_group_ids` に入り、`GET` は `open / decision null / selected []`。(b) 1 枚 keep で決定 → その枚を `clear` → reopened、`selected_asset_ids: []`、items は `unreviewed / rejected` |
| **B1** | `migrate-from-json` が台帳を書かず、次の起動で消える | **直っている（再現しない）** | `cli.py:222-243`。実行: kept 1 / rejected 1 を含む JSON → `台帳に写した判断 2 件`、`decision` に `note='store.json から取り込み'` の 2 行、2 回目の取り込みで **増えない**、`ReviewService()` の後も **kept / rejected のまま**。ただし `reviewed_by='user'` は `reconcile()` が `human` に直す（P5-2 監査 D12 のとおり。WARNING 1 行） |
| **B2** | 1 つの失敗で残りが書かれない | **直っている（再現しない）。ただし新たに C1** | `export.py:183-206`。実行: g_A のファイルを掴んだまま共有画像を `keep` → **g_B は書かれ、g_A は書かれず**、`changed_at > exported_at` が True、解除後の次のタイマーで g_A が書かれた。ログに WARNING 5 行 |
| **B3** | 錠の外で読む | **直っている（コード＋テスト。§H）** | `export.py:164, 218, 250, 278`、`tests/test_export.py:364` |

### 前回 C

| # | 再判定 | 根拠 |
| --- | --- | --- |
| **C1** `create_app()` がモジュール読み込み時に走る | **半分。再現した** | 本報告 C3 |
| **C2** `mark()` が書き出しの錠を待つ | **再現しない（実測で無害）** | `export.py:161-171` は今も `self._lock` を取るが、`write_group` の錠も同じ `RLock`（`:249`）。実測: タイマーを跨いで 30 件、最大 26.5 ms。8 枚 × 4〜5 クエリの `build` が速すぎて見えない。1 まとまり 100 枚なら見える可能性はあるが、未計測 |
| **C3** `flush_dirty()` → `reconcile()` の順 | **直っている** | `app.py:53-55`（`ReviewService` → `flush_dirty()`）。実行: 壊した写しで起動 → WARNING → `GET` が正しい値 |
| **C4** `Store.set_review_state` が残る | **残っている（コード）** | `store.py:387`。アプリからは呼ばれない。`tests/test_prototype.py` / `test_store_sqlite.py` が使う |
| **C5** `source` の検査 | **直っている（実行: 422）** | `review.py:250-251` |
| **C6** 古い token の再送が 409 | **再現した（実行）** | `review.py:558-570`。同じ枚に `reject` を入れた後、古い `client_token` で `keep` を再送 → **409 `client_token_conflict`**。同じ token で中身違い → 409（これは正しい）。G3 |
| **C7** まとまりの行の `supersedes` | **直っている（実行: True）** | `review.py:431-438` |
| **C8** GET `scope=all` がファイルを書く | **再現した（実行）** | `api/export.py:37-38`。`GET` 前後で `export/review.json` の mtime が変わる。G2 |
| **C9** 理由の改名が印を付けない | **再現した（実行）** | `review.py:373-409` に `_touch_groups` が無い。改名 → 3 秒後も `changed_at` 不変、ファイルの `reason_label` は旧名 |

### 前回 D

D1（`created_at` の `db.now()` 埋め: `export.py:362` **残る**）、D2（`clear` の `note`: **再現した**。`POST clear note="取り消しのメモ"` → 応答と `scope=asset:` の両方に `note` が出る。`export.py:384`）、D3（`include_tags=true` で `[]`: **再現した**。`export.py:402`）、D4（`cursor` OFFSET: **残る**。`review.py:308, 340`）、D5（二重定義: **直っている**。`review.py:42-53` の `affected_group_ids` 1 か所）、D6（**直っている**。実行で `client_token` が出ない）、D7（壁時計: **残る**。`db.py:58`）、D8 / D9（**直っている**。実行で 422）、D10（docstring: **直っている**。`db.py:11-14`）、D11（`log.exception`: **直っている**。`export.py:238`）、D12（`PATCH /api/reason-codes` に actor 不要: **再現した**。ヘッダ無しで **200**）。

### 前回 F

F1（**直っている**。`test_export.py:217` が書き出し済みのまとまりで試す）、F2（**直っている**。`:254`）、F3（`test_review.py:606` は今も同一プロセス。**残る**。実 HTTP＋別プロセスの走査は今回私が実行した）、F4（並行 8 本のテストは**無い**。今回私が実行して 1 行）、F5（問題なし）、F6（**残る**）、F7（`jsonschema` 本物: テストは無い。**今回私が実行して 4 文書 OK**）、F8（**残る**。実害無し）。「今すぐ要る 12 件」のうち 1・3・4・5・6・7・8 は入った（`test_export.py:217, 286, 309`、`test_review.py:313, 371, 538, 562, 586`、`test_store_sqlite.py`）。9（並行）・10（別プロセス）・11（100ms）・12（jsonschema）は無く、今回の実行がその代わり。

### 前回 §H

| § | 再判定 |
| --- | --- |
| 2.1-1 | **消えない**（86 → 86）。CLI 側にも `reconcile` の行が出る（C3） |
| 2.1-2 | **漏れない**（hard kill → 再起動で出る） |
| 2.1-3 | **中央値 3.0 ms / 最大 26.5 ms** |
| 2.1-4 | **1 行**（8 本同時） |
| 2.1-5 | **直る**（WARNING つき） |
| 2.2-6 | **4 文書 OK**（本物の `jsonschema`） |
| 2.2-7 | **一致** |
| 2.3-11 | **403 ×5** |
| 実データの件数 | 263 / 183 / 英訳 1 / kept 1 / decision 3 / group 0 |
| Python の版 / sqlite | **3.14.7 / 3.53.1** |
| 更新時刻 | 冒頭 |

---

## 最も重大な 3 件

### 1. 書き出しの再試行が `.tmp` を 2 秒に 1 つ残す（C1。**実行して初めて分かった。実装者は気づいていない**）

監査 B2 の修正（失敗した ID を `_pending` に戻して再試行）は正しく動く。しかし `_atomic_write` は `os.replace` が落ちたときに一時ファイルを消さず、一時名にスレッド ID が入るので再試行のたびに別の `.tmp` が増える。ファイルを掴んだまま 9.5 秒待っただけで 4 個増えた。閲覧ソフトやウイルス対策が数分掴めば数十個になり、起動時にも掃除されない。直し方は `try` と `unlink` の 3 行。

### 2. 理由の改名が契約ファイルに届かない（前回 C9。**実行で再現**）

`PATCH /api/reason-codes/{id}` で `label` を変えても、その理由を使っているまとまりの `changed_at` は動かず、`groups/<id>.json` の `reason_label` は旧名のまま残る（3 秒待っても、再起動しても出ない）。`reason_label` は「書き出し時点のマスタ」（G8）だが、「書き出す契機」が無いので他ツールは次に誰かがそのまとまりに触るまで旧名を読む。A1 で入った `_touch_groups` を改名でも呼べばよい（5 行）。

### 3. CLI が今も `create_app()` を走らせる（前回 C1 の半分。**実行で再現**）

`_store()` の `from .app import data_dir` が `app.py:277` の `app = create_app()` を引き、`scan` / `migrate-from-json` のたびに 2 本目の `Store`・`ExportService`・`ReviewService` ができる（CLI の標準出力に `reconcile` の行が出た）。`_store()` が自前で `flush_dirty()` を呼ぶようになった分、順序依存は消えたが、「別プロセスがサーバと同じファイルを `os.replace` し合う」経路はそのまま。`data_dir()` を `app.py` の外へ出すだけで消える。
