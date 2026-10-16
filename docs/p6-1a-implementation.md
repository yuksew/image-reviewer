# P6-1a 実装報告（要求の API。画面なし）

対象: `docs/p6-design.md` §0.2・§0.3・§0.4・§0.9・§3.1〜§3.5・§3.7・§4.1・§6.1・§8.1（1〜10・20・21・24〜27・31）・§1.2 の 1
点検: `docs/p6-review-report.md`（A2/A3/B3/B4/B5/C1/C2/C8/C9）・`docs/p6-review-triage.md`（全部採用）
監査に渡すもの: この文書＋下の「実行したコマンドと結果」＋ `tools/probe_p6_1a.py` / `tools/check_contract_p6.py`

---

## 1. 作ったもの（行数は Python で数えた実数）

| ファイル | 行 | 何 |
| --- | --- | --- |
| `src/image_reviewer/review_requests.py` | 508 | **新規**。`ReviewRequestService`（受付・差し替え・一覧・取得・断る）＋ `decide` と**同じ取引**で呼ぶ `close_open_requests()` ＋ `request_docs()`（書き出し） |
| `src/image_reviewer/api/requests.py` | 60 | **新規**。`POST/GET /api/review-requests`、`GET /{id}`、`POST /{id}/decline`（作成は 201、再送は 200） |
| `tests/test_requests.py` | 552 | **新規**。21 件（§8.1 の 1〜10・24〜27・31 と、その周り）。各 docstring に「何を壊すと落ちるか」 |
| `tools/probe_p6_1a.py` | 276 | **新規**。HTTP の計測（uvicorn を別プロセスで立てる。§1.2 の 1 と §7 の表） |
| `tools/check_contract_p6.py` | 147 | **新規**。本物の `jsonschema` での契約検証（§8.1 の 20。P5 F7 の教訓） |
| `src/image_reviewer/review.py` | 946（+55） | `_insert_group()` を切り出し（要求と共有）／`_decide_group()` が**同じ取引**で要求を `done` に／`_group_result()` に `closed_request_ids`／`_group_state()`・`list_groups()` に `superseded_by` と `include_superseded`／`notify_export()` |
| `src/image_reviewer/export.py` | 554（+2） | `requests[]` を `scope` に応じて埋める／`groups[]` に `superseded_by` |
| `src/image_reviewer/app.py` | 284（+7） | `ReviewRequestService` を作り `app.state.requests` に置き、router を載せる |
| `src/image_reviewer/api/__init__.py` | 54（+6） | `requests_of()` |
| `src/image_reviewer/api/groups.py` | 60（+3） | `GET /api/groups?include_superseded=1` |

契約（`schemas/review-export.schema.json`）は **P6-0 で既に足りていた**（`ReviewRequest.target_key` / `actor`、
`Group.superseded_by`、`response.annotations` の但し書き）ので、P6-1a では触っていない。

---

## 2. 実行したコマンドと結果

```
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
uv run pytest -q                       -> 203 passed（P6-0 の 182 + 新規 21）
node tools/gui_smoke.mjs               -> すべて ok（画面は P6-1b なので、この段では無変更）
uv run python tools/probe_p6_1a.py     -> すべて OK（下の表。keep-alive で測る）
uv run --no-project --with jsonschema python tools/check_contract_p6.py
                                       -> jsonschema 4.26.0 / すべて OK
```

計測（`tools/probe_p6_1a.py`。uvicorn を 8797 で立て、`httpx` の keep-alive で 30 回）:

| 測ったもの | min | p50 | p95 | max | 線 | 判定 |
| --- | --- | --- | --- | --- | --- | --- |
| `GET /api/review-requests?state=open`（open **1,000 件**、既定 `limit=50`） | 2.3 | 2.4 | **2.8** | 3.2 | 20 ms | OK |
| `GET /api/review-requests?count_only=1`（1,000 件） | 0.8 | 0.9 | 1.1 | 1.2 | 20 ms | OK |
| `GET /api/review-requests/{id}` | 0.7 | 0.8 | 1.2 | 1.2 | 20 ms | OK |
| `POST /api/review-requests`（8 枚 × 30 回） | 1.1 | 1.1 | **1.5** | 9.4 | 150 ms | OK |

- `POST` は **30/30 が `state:"open"`・201**（判断を待たない。§1.2 の 1 の「1 件でも `done` なら落ち」を満たす）。
- 参考: `limit=200`（200 件を組む）は p50 5.3 / p95 13.5 ms（1 件あたり約 0.1 ms。§1.2 に線は無い）。
- 参考: **書き出しと重なったとき**の一覧は p95 6.1 ms。`ExportService` は `store` の錠を握って
  まとまりのファイルを書くので、混ざれば待たされる（P5 からの性質。P6-1a の欠陥ではない）。
- **測り方の注意**: `--fresh`（毎回つなぎ直す）だと同じ一覧が p50 2.8 / **p95 26.7 ms** になる。
  Windows では 127.0.0.1 でも接続ごとに検査が入るらしく、20 ms 前後の裾が**接続の設立**に載る。
  線（§1.2）は応答に対するものなので、keep-alive の表を記録とする（`--fresh` は線を外して参考値）。
- 守り: `Host: evil.example` → 403、`Content-Type: text/plain` → 403（`include_router` の載せ忘れ検出。§8.1 の 24）。

`tools/check_contract_p6.py` が確かめたこと（**本物の `jsonschema`**。要求 4 件・注記 1 件・差し替え 1 件を作る）:

- `scope=all` / `scope=group:<id>` / `scope=asset:<id>` の文書が契約を通る
- `requests[]` が 4 件（`superseded` も残る）／`response` が**オブジェクト**（文字列のまま出さない。点検 F11）
- 閉じた要求の `response.selected_asset_ids` / `reason_label` が入る／開いた要求は `null`
- `response.annotations` が**読むときに導出**される（判断の**後**に挿した注記が入る。§0.2 / 点検 B3）
- `superseded_by` が要求とまとまりの両方に入り、古いまとまりは `groups[]` の既定から外れる
- `generated_at` を除いて 2 回で同一（鍵の順まで同一）

`.data` は触っていない（`.data/export/review.json` の mtime は作業前の 2026/10/15 14:48 のまま）。
計測の捨て場 `.tmp-p6-1a` は 95 MB になったので消した（スクリプト 1 回で作り直せる）。

---

## 3. 自分で決めた点（設計に書いていない／設計と違う）

**検査の順序（設計 §3.2 の「最初に `client_token`」からの意図的なずれ）**

設計は「照合を最初に行い、一致すれば `target_key` を見ない」だが、実装は
**① 対象を引く（`group_id` の存在・`asset_ids` の解決）→ ② 照合 → ③ 業務の検査（`decided` の 422・
`ai_pick` の 422）→ ④ 差し替え → ⑤ INSERT** にした。理由は 2 つ:

- 再送の中身は**解決した対象の集合**で比べたい（`asset_ids` を id で送った再送とパスで送った再送、
  `group_id` で送った再送を同じものとして扱える）。`group_item` から引くので書き方によらず同じ集合になる。
- `decide` / `decline` の**後**の再送も 200 にしたい。`decided` の 422 を照合より前に置くと、
  応答が届かなかったエージェントの再送が 422 になり、点検 B4 の趣旨（再送で死なせない）に反する。

**書き込みより前**であることは保っている（照合で返れば 1 行も増えない）。§8.1 の 25 はこれで緑。

その他（すべて理由つき。監査で「戻す」判断があれば戻す）:

| 論点 | 決め | 理由 |
| --- | --- | --- |
| 要求のまとまりの `title` | `ask` が 200 文字以内ならそれ、長ければ `NULL` | 設計に無い。切り詰めると嘘の題になるので落とす |
| `wants` の件数上限 | `conditions` と同じ 50 件 | 設計は `conditions` だけ。同じ形の欄は同じ規則に |
| `limit` | 1〜200 に丸める（422 にしない） | 設計に無い。一覧は読むだけなので弾かない |
| `counts` | `{"open": n}` だけ（絞り込みに関係なく open の数） | §3.3 の例のまま。バーとタブが使う |
| `count_only=1` | `{"items": [], "next_cursor": null, "counts": {...}}` | 形が設計に無い。キーは同じに保つ |
| 再送の応答の `state` | **いまの**状態（`done` なら `done`） | 「既存を返す」の意味を素直に。`replayed: true` は付く |
| 再送の `closed_request_ids` | `decided_at` と `closed_at` の一致で引く**近似** | 設計に無い欄。通常の経路は UPDATE の戻り値で正確。`db.now()` は秒までなので、**同じ秒に reopen → 再 decide** すると 1 つ前の判断の分を拾いうる（履歴は壊さない）。コードにも書いた |
| 「判断が 1 つも無い」の範囲 | まとまりの判断**と**所属画像の判断の両方を見る | §4.1 の文言をそのまま。画像だけに判断があるまとまりを閉じると履歴が隠れる |
| 差し替えで古いまとまりを閉じる条件 | 古いまとまり ≠ 新しいまとまり のときだけ | 同じまとまりを指名した要求で、そのまとまり自身を隠さないため |
| `requests[]` の書き出しの印 | `create` / `decline` / 差し替えで `notify_export()`（差し替えは `changed_at` も更新） | `requests[]` は `export/groups/<id>.json` にも出る（§6.1）。判断ではないので `changed_at` が動かない |
| `closed_by` | 判断した人（`human`） | 要求を閉じるのは判断なので |
| `annotations` の形 | **id（文字列）**（契約は実体も許す） | §3.4 の例のまま。API と書き出しで同じ形（§3.3）。実体は P6-2 の `annotation-export` が担う |
| エラー本文 | 「両方／どちらも無い」は `details.fields.asset_ids` だけ | §3.2 の表のとおり |

---

## 4. 見つけた設計の穴（P6-1b / P6-2 で決めるもの）

1. **`GET /api/review-requests` を誰が叩くか**: 画面（P6-1b）が `counts.open` をバーとタブに使う、と
   あるが、その口を叩く間隔（ポーリング 5 秒。§0.10）を画面側の設計に書く欄が無い。
2. **`#/requests` の「開いて決める」の戻り**: `#/group/<id>` で決めた後、一覧に戻る動線（`#/requests` に
   戻るのか、詳細を開いたままか）が §5.1b に無い。
3. **注記の `group_id` の解決**: `POST /api/assets/{id}/annotations` は `group_id` を任意で受けるが、
   「その画像が属さないまとまり」は 422 とある（§3.6）。`group_id` を省いたとき、どのまとまりにも
   入れない（`NULL`）でよいのか、その画像を含むまとまりに自動で入れるのかが書かれていない。
4. **`response.annotations` の絞り込み**: `annotation.group_id = request.group_id` で導出した（§3.4 の
   書き方のまま）。まとまりが違うが画像が同じ印（`group_id` が `NULL` の印）は入らない。これでよいか。
5. **`review_request.policy` が無い**: 「要求のときに指定した `policy`」はまとまりの列にしか残らない。
   `group_id` を指名した要求では、送った `policy` は**捨てられる**（まとまりの設定が正）。仕様として
   明記されていない。
6. **要求の一覧の `total`**: `counts` は `open` の数だけで、絞り込んだ件数（`state=all` の総数）が無い。
   画面が「全部で何件」を出すなら要る。

---

## 5. 未実装（この段の外。次に渡す）

- 画面: `#/requests`（カード・詳細・断る）、`#/group/<id>` の最小形、バーの件数、タブのタイトル（P6-1b。§5.1/§5.1b）
- 注記の口（§3.6）と切り出し、`schemas/annotation-export.schema.json`（P6-2）
- §8.1 の 11〜19・28〜30（座標・切り出し・`GET` が書かない）、§8.2、§8.3（P6-2）
- §8.1 の 24 のうち `.../annotations` と `.../export`（口がまだ無い。P6-2 で足す）
- `README.md` のテスト数（親が最後に直す）
