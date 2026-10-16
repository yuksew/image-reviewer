# P6-1a（要求の API）の監査報告

- 監査した版: 2026-10-16 の作業ツリー（`review_requests.py` / `api/requests.py` / `tests/test_requests.py` 04:40、`tools/check_contract_p6.py` 04:44、`tools/probe_p6_1a.py` 04:45、`db.py` / 契約 04:48。`review.py` / `export.py` / `app.py` / `api/groups.py` は P6-1a の変更込み）。設計は `p6-design.md`（04:16）、実装の記録は `p6-1a-implementation.md`（04:47）。
- **実行できたかどうか: 全部実行できた**（コマンド約 15。ソースは編集せず、実データは `mode=ro`、一時物は `.tmp-audit-redo/p6/`。サーバは `data-p52` で 8791、性能はその複製 `data-perf` で 8792）:
  - `uv run pytest -q` ×2 → **203 passed, 1 warning**（9.3 / 9.0 s）、`tests/.tmp` 0 → 0 → 0。`node tools/gui_smoke.mjs` → **51 ok**。
  - 実装者の道具: `tools/check_contract_p6.py`（本物の `jsonschema` 4.26.0）→ **すべて OK**（12 項目）。`tools/probe_p6_1a.py` → **すべて OK**（一覧 p95 3.0 / `count_only` 1.0 / 取得 1.1 / `POST` 3.0 ms、403 ×2）。**`.tmp-p6-1a`（93 MB）が残る**（実装者は「消した」と書くが、走らせるたびに作り直される。§D）。
  - **自前の HTTP 検査**（`p61a_api.py`、`http.client`）: 検査順序（順序違いの再送・`decide` 後の再送・`decided` への新規・`actor` ヘッダ `robot` / `human`・中身違い・差し替えられた要求の再送）、`group_id` 経路と `decline` が `groups/<id>.json` の `requests[]` に届くか、「判断が 1 つも無い」の範囲、`closed_request_ids` の近似の再現（同じ秒に `reopen` → 再 `decide`）、同じ秒に 6 件入れたキーセット、**別接続 × 8 スレッドの HTTP 同時投入**、`decline` の 403 / 422 / 200 / 200 / 409、`Host` / `Content-Type` / `decline` の 403、`GET` 4 本の後で `review.json` と `groups/` の一覧が不変、判断の後に `annotation` を直接挿して `response.annotations` に出るか、決定性。
  - **契約**: サーバの `scope=all`（要求 24 件: open 10 / done 3 / declined 2 / superseded 9）/ `group:` / `asset:` を本物の `jsonschema` で検証 → **3 文書とも OK**。`annotations` は id の配列、`superseded` は `closed_at` 無し・`superseded_by` あり。
  - **性能の測り直し**（`p61a_perf.py`。`data-p52` の複製に 1,000 件の要求を作ってから、**keep-alive と毎回接続の両方**で各 30 回）。
- 総合判定: **条件つきで使える。** 設計の核（投げてすぐ返る、`decide` と同一取引で閉じる、`reopen` で `response` 不変、注記は読むとき導出、差し替えの一意性と同時投入、キーセット、`GET` は書かない、契約）は**実行で裏が取れた**。検査順序の逸脱は**妥当**（§E）。残るのは **(1) `X-Image-Reviewer-Actor` に `human` / `agent` 以外を入れると 500**（`CHECK` に当たる。エージェントの綴り 1 つで要求が落ちる）、**(2) `group_id` で受けた要求が `groups/<id>.json` の `requests[]` に出ない**（書き出しの印を付けていない）、**(3) 「判断が 1 つも無い」の判定が広すぎて、P5 の判断がある画像を含む古いまとまりは差し替えても閉じない**（点検 A3 の問題が実データでは残る）、の 3 点。

---

## A. 直っていない（必ず直す）

| # | 場所 | 問題 | 実行したコマンド / 再現手順 | 提案 |
| --- | --- | --- | --- | --- |
| **A1** | `src/image_reviewer/api/requests.py:37`（`actor=actor_of(request)` をそのまま渡す）、`api/__init__.py` `actor_of()`（ヘッダの文字列を**検査せず**返す。無ければ `agent`）、`review_requests.py:285-291`（INSERT に `actor` をそのまま）、`db.py` `review_request.actor CHECK (actor IN ('human','agent'))` | **ヘッダに `human` / `agent` 以外の値があると、`CHECK` に当たって `sqlite3.IntegrityError` → 500。** 設計 §3.1 は「`actor` は自己申告（ヘッダ）」としか書かず、語彙の外の扱いが無い。エージェントが `Agent` / `robot` / `claude` と書いただけで要求が落ち、サーバのログに traceback が出る（P5 の `/api/reviews` は `human` 以外を 403 にするので同じ入口で振る舞いが違う） | **再現した。** `POST /api/review-requests`（`X-Image-Reviewer-Actor: robot`）→ **500 Internal Server Error**、サーバのログに `sqlite3.IntegrityError: CHECK constraint failed: actor IN ('human', 'agent')`（3 回）。`human` → 201・`actor` は `human` で保存 | `actor_of()` の後で `actor not in ("human", "agent")` なら **422**（`details.fields.actor`）にするか、**`agent` に寄せる**（自己申告なので知らない語は `agent`）。設計 §3.1 に 1 行。テスト: `actor="robot"` で 422（または `agent` 扱い）。P6-2 の注記の口も同じ `actor_of()` を使うので、**ここで直せば両方に効く** |

---

## B. 直っているが別の問題が残る（重大）

| # | 場所 | 問題 | 実行したコマンド / 再現手順 | 提案 |
| --- | --- | --- | --- | --- |
| **B1** | `review_requests.py:224, 262-271, 292`（`dirty` に積むのは**新しく作ったまとまり**と**閉じた古いまとまり**だけ。`group_id` を指名した要求では `dirty = []` のまま `notify_export([])`）、`p6-design.md` §6.1（`requests[]` は `groups/<id>.json` にも出る）、`p6-1a-implementation.md` §3「`create` / `decline` / 差し替えで `notify_export()`」 | **既存のまとまりを指名した要求（`group_id` 経路）は、そのまとまりのファイルに出ない。** 要求の行は入り `GET` の `scope=group:` には出るが、判断のたびに書く `export/groups/<id>.json` は書き直されず、`requests: []` のまま。`decline` は `notify_export([group_id])` で届く（確認済み）ので、**受付だけが漏れる**。実装の記録は「`create` で `notify_export()`」と書くが、`group_id` 経路には当てはまらない | **再現した。** `POST /api/groups` で g を作り 3 秒待つ → `POST /api/review-requests {group_id: g}` → **3.5 秒後のファイル**: `requests: []`、`generated_at` 不変（書き直されていない）。`GET ?scope=group:g` は要求を返す。同じ要求を `decline` → 3.5 秒後のファイルに `declined` で出る | `group is not None` の分岐で `dirty.append(gid)` を足す（1 行）。テスト: `group_id` で受けた後に `exporter.flush()` → ファイルの `requests[]` に入る。あわせて、要求の受付は `changed_at` を動かさないので **タイマーが走る前に落ちると起動時の `flush_dirty()` では拾われない**（P5 の A1 と同じ型。`requests[]` は判断ではないので許容するなら §6.1 にそう書く） |
| **B2** | `review_requests.py:444-451` `_no_decisions()`（まとまり自身の判断**または所属する画像の判断**が**どこにあっても**「判断あり」）、`:279`、`p6-design.md` §0.3「古いまとまりに判断が 1 つも無ければ」、`p6-1a-implementation.md` §3「画像だけに判断があるまとまりを閉じると履歴が隠れる」 | **「判断が 1 つも無い」の判定が広すぎる。** 画像が**別の場所**（1 枚の判断 `POST /api/reviews`、別のまとまり）で判断されていると、そのまとまりの中では何も決めていなくても閉じない。その判断はまとまりの履歴ではない（`decision.group_id` が違う／NULL）ので「隠れる」ものは無く、一方で**点検 A3 の問題（差し替えで `open` なまとまりが残る）がそのまま起きる**。P5 の実データは 263 枚中 1 枚しか判断が無いが、使い込むほど判断済みの画像が増え、**差し替えが効かないまとまりが増える** | **再現した。** 画像 d1 を `POST /api/reviews keep`（まとまり外）→ `target_key=orph-1` で `[d1]` の要求 → 同じ鍵で `[d2]` の要求 → 旧まとまり: `superseded_by: None`、`state: open`、**既定の `GET /api/groups` に残る** | 「判断が 1 つも無い」を**そのまとまりの判断**（`decision.group_id = old_group`、または `subject_type='group' AND subject_id = old_group`）に絞る。画像の判断は画像に残るので隠れない。§0.3 に「まとまり**の**判断」と書く。テスト（§8.1-27）に「画像だけに別の場所で判断があっても閉じる」を足す |
| **B3** | `review_requests.py:156-169` `closed_request_ids_for_group()`（再送経路の近似。`closed_at == decided_at`）、`review.py:892-894`、`p6-1a-implementation.md` §3（実装者が自分で「拾いうる」と書いた） | **実際に再現する。** `decide`（token T1）→ `reopen` → 同じまとまりに新しい要求 → `decide`（T2）を**同じ秒**に行い、T1 を再送すると `closed_request_ids` に **2 件**（T1 が閉じた分と T2 が閉じた分の両方）が入る。害: 再送の応答だけが間違う（台帳・要求の状態は正しい）。エージェントが「自分の判断で閉じた要求」を再送の応答から読むと**他人の要求を自分が閉じたと誤解する**。`db.now()` が秒なので、画面の操作でも「決める → 戻す → 決める」を 1 秒以内に打てば起きる | **再現した（HTTP）。** 1 回目の応答 `[rq1]`、2 回目 `[rq2]`、**T1 の再送 `[rq1, rq2]`**（`superseded: true`） | 再送の応答では `closed_request_ids` を**出さない**（`superseded: true` のときは意味が無い）か、`decision.id`（T1 の行）と `review_request` を結ぶ列（`closed_by_decision_id`）を足して正確に引く。前者なら 1 行 |

---

## C. 中程度

| # | 場所 | 問題 | 実行したコマンド / 再現手順 | 提案 |
| --- | --- | --- | --- | --- |
| **C1** | `review_requests.py:424-425`（再送の応答は `request_id` / `group_id` / `state` / `replayed` だけ） | **差し替えられた要求の再送は `state: superseded` を返すが、`superseded_by` が無い。** エージェントは「差し替えられた」ことは分かるが**何に**差し替えられたかは `GET /{id}` を別に叩かないと分からない。§3.2 の応答の例にも無い | **再現した。** 差し替え済みの要求を同じ `client_token` で再送 → 200、鍵は `group_id, replayed, request_id, state` | 再送の応答に `superseded_by`（null 可）を足す。契約の `ReviewRequest` ではなく受付の応答なので `abi` に関係しない |
| **C2** | `tools/probe_p6_1a.py`（`.tmp-p6-1a` を作って消さない） | 走らせるたびに **93 MB**（1,000 件の要求 → 1,000 まとまりのファイル）が残る。実装の記録は「消した」と書くが、道具は消さない | `uv run python tools/probe_p6_1a.py` の後に `du -sh .tmp-p6-1a` → 93M | 終わりに `shutil.rmtree`（`gui_layout.mjs` と同じ扱い）か、`.gitignore` に入れて README に書く |
| **C3**（性能） | `p6-1a-implementation.md` §2 の表（`POST` p95 1.5 ms、一覧 p95 2.8 ms）、`p6-design.md` §1.2 線 1・§7 | **実装者の値は書き出しが落ち着いた後の値で、私の測り直しは桁が違う（線の内側ではある）。** keep-alive で **`POST` p95 16.2 ms**（線 150）、**一覧（open 1,040 件）p95 8.5 ms**（線 20）、`count_only` p95 7.0、`limit=200` p95 10.7。差の理由: 1,000 件の要求は 1,000 のまとまりを作り、**タイマーがそのファイルを書き続ける間は `store` の錠を取り合う**（実装者も「参考」として p95 6.1 を記録）。私は 1,000 件を作った 4 秒後に測ったので、書き出し（887 / 1,000 ファイル）が**まだ走っていた**。**毎回接続**だと一覧 p95 **28.5**、`count_only` **27.1**、`limit=200` **33.4 ms** で線 20 を**超える**（実装者の `--fresh` 26.7 と同じ現象。127.0.0.1 の接続の設立が 20 ms 前後）。線は応答に対するものなので keep-alive の値を記録とするのは**妥当**だが、**画面の 5 秒ポーリングが毎回接続なら 20 ms は守れない**（ブラウザは通常 keep-alive する） | `p61a_perf.py`（`http.client`。keep-alive は 1 本の `HTTPConnection` を使い回し、毎回接続は都度 `connect`）。1,000 件の `POST` は合計 1.2 s（すべて 201 / `open`） | §7 の表に「測り方: keep-alive、書き出しが落ち着いた状態」と書く。**書き出しの最中**の値（p95 16 / 8.5）も「混雑時」として併記する。P6-1b の画面は `fetch` の keep-alive に任せ、`count_only` を使う |

**確かめた結果、問題なし（実行）**:

- **検査順序**（§2-1）: 順序違いの `asset_ids`（`[b,a]`）の再送 → **200 `replayed`、同じ `request_id`、行は 1**。`decide` の**後**の再送 → **200 `replayed` `state: done`**（設計どおり「いまの状態」）。`decided` なまとまりへの**新規** → 422（点検 C2）。同じ token で中身違い → 409 `client_token_conflict`。**書き込みより前**で照合が済む（`:241-244` が `:254` の `db.ulid()` より前）。順序の妥当性は §E。
- **差し替え**（§2-2）: 古い `open` の UPDATE（`:275`）→ INSERT（`:285`）の順。**HTTP で別接続 × 8 スレッド**同時投入 → 8 本とも 201、**`open` 1・`superseded` 7**。`done` / `declined` は触られない（`tests/test_requests.py:107` と同じ経路を HTTP でも: §1 の `decide` 後の同じ鍵の再送は 200 で行を増やさない）。`superseded` に `closed_at` 無し・`superseded_by` あり（契約の文書で全件確認）。
- **判断で閉じる**（§2-3）: `decide` の応答 `closed_request_ids == [req]`、要求は `done`、`response.selected_asset_ids` が選んだ枚。`review.py:510-516` が `_decide_group` の**同じ取引**の中で `close_open_requests()` を呼ぶ。`reopen` 後も `done` のまま（`tests:220`。HTTP では `reopen` → 同じまとまりに新しい要求 → `decide` が**新しい要求だけ**を閉じることを確認）。**判断の後に `annotation` を直接挿す** → `GET /{id}` の `response.annotations` に **その id が入る**（読むとき導出。`:62-72, 87`）。
- **断る**（§2-4）: `agent` → 403、空 → 422、理由つき → 200、同じ理由 → 200、違う理由 → 409 `request_not_open` `details.state: declined`。`client_token` は取らない（`:346-371`）。
- **一覧**（§2-5）: **同じ秒に 6 件**を `limit=2` で 5 ページ → **重複 0・取りこぼし 0**（`created_at < ? OR (created_at = ? AND id < ?)`。`:317-319`）。`target_key=` の絞り込み、`count_only=1` の形 `{items: [], next_cursor: null, counts}`。**`GET` 4 本の後で `review.json` の mtime と `groups/` の一覧が不変**。
- **契約**（§2-6）: 3 文書とも本物の `jsonschema` で OK。`response` はオブジェクト、`annotations` は id の配列、`scope=group:` は 1 件、`scope=asset:` はその画像を含むまとまりの分。決定性: `generated_at` を除いて同一（注記を足した要求を除く）。
- **守り**（§2-7）: `Host: evil` → 403、`Content-Type: text/plain` → 403、`decline` の `Host: evil` → 403。`app.py:107` で router を載せている。
- **回帰**（§2-12）: 203 / 51 緑。P5 の `POST /api/reviews`（1 枚の判断）と `decide` / `reopen` は今までどおり動く（本監査の手順で使った）。`GET /api/export/review.json` は書かない。`GET /api/groups` は `superseded_by` を返し、既定で閉じたまとまりを外す（P6-0 の C1 が直った）。

---

## D. 軽微

| # | 場所 | 問題 | 提案 |
| --- | --- | --- | --- |
| D1 | `review_requests.py:467-483` `_text_list` | `conditions` / `wants` の**各要素の長さ**に上限が無い（件数は 50 まで）。1 要素 1 MB でも通る | 要素も `MAX_ASK`（2000）で切る |
| D2 | `review_requests.py:216-219` | `asset_ids: []` と `group_id: null` の「どちらも無い」が `details.fields.asset_ids` だけなのは設計どおりだが、`group_id` を書いた側には `asset_ids` の欄名で返るので分かりにくい | `details.fields` に `group_id` も |
| D3 | `review_requests.py:416`（`client_token` は**全要求で一意**。`ux_request_token`） | 別のエージェントが偶然同じ token を使うと、他人の要求の 200 / 409 になる（P5 の判断と同じ設計）。`client_token` に名前空間が無い | 設計の注記で「token は UUID 相当を使う」と書く |
| D4 | `p6-1a-implementation.md` §2「`.tmp-p6-1a` は消した」 | 道具は消さない（C2）。記録と道具が食い違う | 道具を直す |

---

## E. 設計とのずれ（検査順序の逸脱の妥当性を含む）

| 項目 | 状態 | 判断 |
| --- | --- | --- |
| **§3.2「`client_token` の照合を最初に行い、一致すれば `target_key` を見ない」** vs 実装「①対象の解決 → ②照合 → ③業務検査 → ④差し替え → ⑤INSERT」 | **逸脱は妥当。ただし設計の文を実装に合わせて直す。** 理由: (a) 再送の比較に**解決した対象の集合**を使うには①が②より前に要る（id・パス・`group_id` のどの書き方でも同じ集合になる。実行で順序違いの `asset_ids` が 200 になることを確認）。(b) 点検 B4 の核心「照合が**差し替えより前**」は保たれている（②が④より前。同じ token・同じ鍵の再送で行が増えないことを `tests:351` と HTTP で確認）。(c) ③（`decided` の 422、`ai_pick` の 422）が②より**後**なので、`decide` 後の再送が 422 にならず 200 になる（確認済み）。**穴になりうる点は 2 つ**: ①の 404（`group_id` が無い）/ 422（未知の id・パス）は照合より前なので、**最初の要求の後に対象が消えた再送は 200 ではなく 404 / 422**になる（P8 の削除が入るまでは起きない）。長さ・語彙の 422（`:197-214`）も照合より前だが、最初に通った中身の再送は同じ検査を通るので実害は無い | §3.2 の順序の文を「対象の解決 → `client_token` の照合（**差し替えより前**） → 業務検査 → 差し替え → INSERT」に書き換え、「対象が消えた再送は 404 / 422」を 1 行 |
| §0.3「古いまとまりに判断が 1 つも無ければ」 | 実装は**画像の判断がどこにあっても**「あり」と読む（B2） | 「そのまとまりの判断」に絞る |
| §6.1「`requests[]` は `groups/<id>.json` にも出る」 | `group_id` 経路で出ない（B1） | 直す |
| §3.1「`actor` は自己申告」 | 語彙の外が 500（A1） | 422 か `agent` 寄せ |
| §3.3 `counts` / `count_only` / `limit` の丸め | 実装者の決め（§3）のとおり。**妥当**（読むだけの口で 422 にしない） | — |
| §3.4 `response.annotations` は id の配列、再送は「いまの状態」 | **妥当**（契約は両方を許す。実体は P6-2 の `annotation-export` が担う） | — |
| まとまりの `title` を `ask` から（200 文字以内なら） | **妥当**（切り詰めない判断もよい）。`frontend-design.md` §4.1 の見出し「同じ指示で出した候補（8 枚）」は `title` から来るので、`ask` が長いと見出しが空になる。P6-1b で `ask` を見出しに使うなら `title` は要らない | P6-1b で決める |
| `wants` の件数上限 50 | 妥当 | — |
| `closed_by` = 判断した人 | 妥当 | — |
| 差し替えで古いまとまりを閉じるのは「古い ≠ 新しい」のとき | 妥当（同じまとまりを指名した差し替えでそのまとまりを隠さない） | — |
| `GET /api/groups?include_superseded=1`（設計 §0.3） | **一致**（P6-0 の C1 が直った） | — |
| **実装者が挙げた設計の穴 6 件（§4）** | 1（ポーリングの間隔を画面側に書く）・2（決めた後の戻り）・6（`total`）は **P6-1b で決めてよい**（画面の話）。3（注記の `group_id` の既定）・4（`response.annotations` の絞り込み）は **P6-2 で決めてよい**が、4 は B3 と同根なので「`group_id` が NULL の注記は入らない」を §3.4 に今書いておく。5（`policy` が要求に残らない）は **今決めるべき**: `group_id` 指名の要求で送った `policy` は黙って捨てられる（`:240`）。422 にするか、契約の `ReviewRequest` に `policy` を出すかのどちらか。推奨は「まとまりの `policy` と違えば 422」（黙って捨てない） | G2 |

---

## F. テストが守っていないもの

| # | テスト | 何を主張しているか | 実際に守っているか | 直し方 |
| --- | --- | --- | --- | --- |
| **F1** | `tests/test_requests.py:123` `test_eight_concurrent_requests_leave_exactly_one_open` | 判定と更新を別の取引に分けると落ちる（点検 C9） | **守っている。** スレッドごとに `Store`（別接続）を作るので `Store._lock` で隠れない。判定（SELECT）と更新（UPDATE → INSERT）を別の取引にすると、2 本が「古い `open` 無し」と判定してから INSERT し、2 本目が `UNIQUE` で落ちて `errors` が非空になる。鎖の検査もある | — |
| **F2** | `:351` `test_the_same_token_and_target_key_twice_writes_one_row` | 照合を差し替えの後ろに回すと落ちる（§8.1-25） | **守っている。** 順序を逆にすると 2 回目が自分を `superseded` にして行が 2 になる | — |
| **F3** | `:454` `test_superseding_hides_the_old_group_only_when_it_has_no_decisions` | 判断が無いときだけ閉じる（§8.1-27） | **半分。** 「まとまりの中で決めた」場合しか見ていないので、**B2（別の場所の画像の判断で閉じなくなる）は緑のまま** | 「画像を `apply_asset` で先に判断してから差し替え → 閉じる」を足す |
| **F4** | `:196` `test_the_stored_response_survives_decide_and_reopen` | 写しが不変、`annotations` は導出 | **守っている**（改名と `reopen` の両方で不変、`annotations` は除外） | 判断の後に `annotation` を直接挿して `annotations` に入ることも 1 行（今回私が HTTP で確認） |
| **F5** | `:175` `test_decide_closes_the_open_request_and_reports_it` | 同じ取引で閉じる | 守っている。ただし「**同じ取引**」は、`close_open_requests` を取引の外に出しても落ちない（結果は同じ） | `_insert` を途中で落とす `monkeypatch`（`test_group_decide_is_one_transaction` と同じ手口）で、要求が `open` のままであることを見る |
| **F6** | （無い） | `actor` の語彙の外（A1） | 無い | `actor="robot"` で 422 |
| **F7** | （無い） | `group_id` 経路の `requests[]` がファイルに出る（B1） | 無い（`:484` は `build()` を直接呼ぶので、タイマーの印は見ない） | `group_id` で受けた後に `exporter.flush()` → ファイル |
| **F8** | （無い） | 再送経路の `closed_request_ids`（B3） | 無い（実装者が「拾いうる」と書いた経路） | B3 の直し方に合わせて |
| **F9** | `:438` `test_reading_requests_writes_no_files` | `GET` が書かない | **守っている**（ファイル一覧の前後比較） | — |
| **F10** | `:517` `test_the_new_endpoints_are_guarded_and_create_is_201` | router の載せ忘れ、201 / 200 | **守っている** | — |
| **F11** | `:389` キーセット | 同じ秒の重複・抜け | 3 件が同じ秒に入るとは限らない（`db.now()` 次第）が、通常は同じ秒になる。今回 HTTP で 6 件同じ秒を確認 | `created_at` を `monkeypatch` で固定して確実に同じ秒に |

---

## G. 依頼者への質問（推奨つき。朝に読む）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| **G1**（A1） | `actor` ヘッダが語彙の外のとき | (i) 422 ／ (ii) `agent` に寄せる | **(i)**。黙って `agent` にすると `human` の綴り間違いが「人の判断ではない」扱いになる。`decline` / `decide` の 403 と同じく**はっきり落とす** |
| **G2**（§4-5） | `group_id` 指名の要求で送った `policy` | (i) まとまりと違えば 422 ／ (ii) 黙って捨てる（いま） ／ (iii) 契約に `policy` を出す | **(i)**。`pick_many` のつもりで投げたのに `pick_one` のまとまりに付くと、応答の `selected_asset_ids` が 1 枚しか来ない。黙って捨てない |
| **G3**（B2） | 「判断が 1 つも無い」の範囲 | (i) そのまとまりの判断だけ ／ (ii) 画像の判断も（いま） | **(i)**。画像の判断は画像に残る。(ii) だと使い込むほど差し替えが効かなくなる |
| **G4**（B3） | 再送経路の `closed_request_ids` | (i) 再送では出さない ／ (ii) 判断の id で正確に引く列を足す | **(i)**。再送は「いまの状態」を返すだけでよい。(ii) は v5 の移行が要る |
| **G5**（C3） | §7 の表の測り方 | (i) keep-alive・書き出しが落ち着いた状態（実装者） ／ (ii) 混雑時も併記 | **(ii)**。線は守っているが、画面の 5 秒ポーリングは書き出しと重なる |

---

## H. 確かめられなかったこと

| 項目 | 状態 | 理由 |
| --- | --- | --- |
| 「対象が消えた再送」が 404 / 422 になる経路（§E） | **読んだだけ** | 画像を消す口が無い（P8） |
| 1 要求 200 枚の `POST` の時間（設計 §10-10） | **未計測** | 線は 8 枚。P6-1b の監査で 1 回 |
| 判断の後の注記（実際の `POST /annotations`） | **DB に直接挿して代用** | 注記の口は P6-2 |
| `closed_request_ids` の近似が**違う秒**で `[]` になること | **未確認**（同じ秒の 2 件だけ再現） | 1 秒待つ手順を足せば見える。害の型は同じ |

---

## 最も重大な 3 件

### 1. `actor` ヘッダの綴り 1 つで要求が 500 になる（A1。**実行して分かった**）

ヘッダの値を検査せずに `CHECK (actor IN ('human','agent'))` の列へ入れるので、`robot` でも `Agent` でも `IntegrityError` がそのまま 500 になり、ログに traceback が出る。要求の口は「エージェントが投げる」口で、綴りは相手が決める。`actor_of()` の直後で 422 にするか `agent` に寄せるかの 1 行で済み、P6-2 の注記の口も同じ関数を使うので先に直すと両方に効く。

### 2. 既存のまとまりを指名した要求が、そのまとまりのファイルに出ない（B1。**実行して分かった**）

`dirty` に積むのが新しいまとまりと閉じた古いまとまりだけなので、`group_id` 経路では `notify_export([])` になり、`groups/<id>.json` の `requests[]` は空のまま。`decline` は届くので、受付だけが漏れる。実装の記録「`create` で `notify_export()`」は半分しか当たっていない。`dirty.append(gid)` の 1 行と、`flush()` 後のファイルを見るテストで守れる。

### 3. 「判断が 1 つも無い」が広すぎて、使い込むほど差し替えで古いまとまりが残る（B2。**実行して分かった**）

画像が別の場所で判断されていると、そのまとまりの中では何も決めていなくても閉じない。隠れる履歴は無く（判断は画像とまとまり外の台帳にある）、一方で点検 A3 が指摘した「誰にも紐づかない `open` なまとまり」がそのまま増える。判定を「そのまとまりの判断」に絞り、§0.3 の語を「まとまり**の**判断」にする。
