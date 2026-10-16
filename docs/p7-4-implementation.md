> **廃止（2026-10-17。利用者の判断）**: この段は**削除しました**。理由と控えは [`p7-decision.md`](p7-decision.md) を見てください（①PNG を ComfyUI にドラッグすればワークフローが戻るので記録は重複 ②ja2en の英訳も実行すれば取り直せる）。**記録として残しています。**

# P7-4（画面）の実装の記録

- 日付: 2026-10-17。設計: `docs/p7-design.md` §0.13・§5.1〜§5.4・§3・§4・**§0.18（この段で決めたこと）**、
  `docs/frontend-design.md` §4.7〜§4.12・**§6（文言）・§11.9（細部）**
- 指示書: `docs/p7-4-implementation-brief.md`。**実装したのは親（DeepSeek）**（深度の都合で委任できなかった）
- **`git` のコミットはしていない**（親の指示どおり。まとめてコミットする）

## 作ったもの

| ファイル | 行 | 何 |
| --- | --- | --- |
| **`apps/gui/recipe.js`** | **286（新規）** | 1 枚の条件の記録（`#/asset/<id>/recipe`）。判定と理由・記録・検査・書き出し・束とファイル・結果と合否・手で紐付け・esc |
| **`apps/gui/recipelist.js`** | **121（新規）** | 記録の一覧（`#/recipes`）。要約・判定で絞る・続きを読む |
| `apps/gui/index.html` | +30 | `#recipe` と `#recipes` の器（既存の `#tags` / `#jobs` と同じ形） |
| `apps/gui/styles.css` | +63 | 出し分け（`body.recipe` / `body.recipelist`）と `.rc-*` / `.rl-*` |
| `apps/gui/app.js` | +26/-4 | 経路（**`#/asset/<id>/recipe` を `#/asset/<id>` より先に**判定）・`#/recipes`・**来歴の下に「条件の記録」1 行**・`wireRecipe` / `wireRecipes` |
| `src/image_reviewer/db.py` | +27/-3 | **`recipe_export_result.fetched`** を v6 の DDL に足し、**`_top_up_v6`**（`PRAGMA table_info` を見てから `ALTER TABLE`。既に v6 の DB にも入る） |
| `src/image_reviewer/watcher.py` | +6/-2 | `/view` で取り込んだら **`fetched=1`**。`results()` が `fetched` を返す |
| `src/image_reviewer/recipe_export.py` | +4 | `_result_doc` が `fetched` を返す（画面が「取り込み / 参照」を出す） |
| `src/image_reviewer/recipe.py` | +18/-6 | **`GET /api/recipes` に `status` の絞り込み**（語彙外は 422）・**`_doc_of` が `graph_source` を返す**（前は `POST` の応答にしか無く、画面の「出所」が `—` だった） |
| `src/image_reviewer/api/recipes.py` | +4/-2 | `list_recipes` に `status` を通す |
| `tests/test_db.py` | +46 | **v6 の DB に `fetched` が入る**（列を落とした v6 を手で作って `migrate()`） |
| `tools/gui_smoke.mjs` | +77 | **13 件**（判定・理由・束・印なし・合否の 4 ボタン・`fetched`・esc・**記録時の 7 語と書き出し時の 3 語が混ざらない**・一覧・`status` の読み・**画面を開くだけで書かない**） |
| `tools/gui_layout.mjs` | +110 | **`--screen recipe`（`--ids` が要る）と `--screen recipes`**（`MEASURE_RECIPE` / `MEASURE_RECIPES`） |

## 実行した結果

| 確かめたこと | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q` | **393 passed**（392 → +1。`test_the_fetched_column_is_topped_up_on_an_older_v6_database`） |
| `node tools/gui_smoke.mjs` | **すべて ok**（**129 → 142 件**） |
| `node tools/gui_layout.mjs --screen recipe --ids <id>`（**3 窓**） | `badge="完全" rows=1 results=1 verdicts=4 overflow=0 pageOverflow=0 scripts=0 markTop=54` → **すべて ok** |
| `node tools/gui_layout.mjs --screen recipes`（**3 窓**） | `rows=1 empty=false listOverflow=0 pageOverflow=0 brief="すべての判定"` → **すべて ok** |
| 既存 6 画面（比較・要求・まとまり・注記・タグ・ジョブ） | **回帰なし**（緑のまま） |
| **`fetched` 列** | v6 の DDL にあり・既定 0・**列を落とした v6 に `migrate()` で入る**・**その列を足す条件を `if False` にすると、足したテストが落ちる**（`tests/test_db.py:1087`）ことを確認 |

### 実データの複製（`sqlite3` の `backup()`）での往復（**本物の ComfyUI を読むだけ。生成はしていない**）

| # | 手順 | 結果 |
| --- | --- | --- |
| ① | `POST /api/assets/01M4Z0KJR69CW8RA2R5Q9ZXHHW/recipe {mode: pin_text}` | **201**・`status=exact`・`reasons=[]`・`inspected=true`・**グラフを `<data>/workflows/<sha256>.json` に書いた** |
| ② | `POST /api/recipes/<id>/check` | **200**・`marker_ok=true`・保存ノード 1 個・`unresolved=[]` |
| ③ | `POST /api/recipes/<id>/export {seeds:["1","2"], mode: rerun_graph}` | **201**・`attempt_id=s4z0r3zn`・**`seed-1.json` / `seed-2.json` / `manifest.json`**・**印 `repro-s4z0r3zn/seed-1`**・`seed_node=7` |
| ④ | `GET /api/recipes/<id>/exports` | 200・束 1・結果 0 |
| ⑤ | `POST …/{attempt}/results` → `POST …/{result}/verdict {verdict: close}` | **201**（`matched_by=manual`）→ **200**（`verdict_actor=human`・`note` が残る） |
| ⑥ | `GET /api/recipes?status=approx` / `status=nope` | 0 件（記録は `exact`）/ **422** |
| ⑦ | 行数 | `recipe_record=1`・`recipe_export_attempt=1`・`recipe_export=2`・`recipe_export_result=1` |

### `GET` が 1 バイトも書かない（**画面を開くだけでは行が増えない**）

複製の**全ファイルの size と mtime**＋**7 表の行数**の指紋を撮り、**2 画面（recipe / recipes × 3 窓）を開いてから**撮り直した:
**`0751d39fc0e637e5` → `0751d39fc0e637e5`（差 0）**。読みは走っている（対照）。

### エスケープ

`statusHtml` の理由に `<script>alert(1)</script>` を入れて **`&lt;script&gt;` になる**ことを `gui_smoke` で固定。
実物では `MEASURE_RECIPE` が **`scripts=0`** を毎回見る（3 窓）。

### 画面写真

`.tmp-audit-redo/p74/shot-recipe.png`（1400x900）。**判定「完全」・条件は揃っています・書き出しの束（印あり・2 ファイル・`repro-s4z0r3zn/seed-1`）・結果の行（`近い`・手で紐付け・参照・鍵が違う・合否 4 ボタン・人で `人の判断`）**が出ている。

## 自分で決めた点（申し送り）

1. **`GET /api/recipes` に `?status=` を足した**（設計 §5.4 の「判定で絞る」に口が無かった）。語彙外は **422**。
2. **`_doc_of` が `graph_source` を返すようにした**（設計 §0.6 は `record_json` の中と書いており、実際に入っていたが `GET` が出していなかった）。
3. **`#/asset/<id>/recipe` を `#/asset/<id>` より先に判定**（ルータの順序。後ろだと拡大が勝つ）。
4. **`#/recipes` の「次の 50 件」は足す**（置き換えない。P4-3 の監査 C-2 と同じ）。
5. **`recipeLinkHtml(id, null)` は状態を読みに行かない**（来歴の描画で N+1 の `GET` を増やさない。**記録の有無は 1 枚の画面で見る**）。
6. 合否のボタンは**常に 4 つ**出し、押した物を色で示す（**上書き**なので「いまの値」が分かる形）。

## 残した所

- **`#/jobs` に監視の状態を 1 行**（指示書 2 の 3 番目）は**まだ入れていない**（`GET /api/watcher` の表示と開始/停止のボタン）。
  P7-3 の監視は**口がそろっている**ので、次に足すのは小さい。
- **プリセットの画面**（§4.12）は P7 の範囲だが、**口（`POST /api/recipes/{id}/presets`）がまだ無い**ので画面も作っていない（設計 §3 の一覧に載っているが未実装）。
- `comfyui.output_dir` が未設定のときの推定は P7-3 の実装（この環境では実データに設定を入れてある）。
