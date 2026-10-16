# P7-1 の監査の仕分け（Fable の監査 → どう直したか）

- 監査報告: [`p7-1-audit-report.md`](p7-1-audit-report.md)（**判定: 直してから次へ**。A 4 件 / B 3 件 / C 3 件 / D / E / F / G 7 件）
- 立場: **推奨（G-1〜G-6）はすべて採用**。直したのは**親（DeepSeek）**。設計にも反映済み（§0.6・**§0.17**）。
- **テストは 360 → 369 passed**（9 件追加。`gui_smoke` 129 件も緑）。**`probe_p7.py --judge` は 182 / 1 / 80 のまま**。

| # | 指摘 | どう直したか |
| --- | --- | --- |
| **A-1** | **ComfyUI 不通で全部 `impossible`**（`node_missing` × ノード数）になり、**1 枚 20〜32 秒** | **`system_stats` で打ち切る**（`collect_env` が即 `return env, False`）。**`/object_info` を 1 回も引かない**ことをテストで固定（`probe.calls == []`）。**`declarations` は `None`（未検査）**のまま。**`None`（引けなかった）と `{}`（引いたが無かった）を区別**し、`{}` だけ `node_missing` |
| **A-2** | **選択肢に無いモデルが `approx`**（設計 §0.6 は `impossible`）。テストの名前が嘘だった | **`_reason()` に `fatal` の印**を足し（**7 語は増やさない**）、**`_is_model_input()`**（`*_name` の入力・`Loader` を含む class）で判定。**`judge` が `fatal` を見て `impossible`**。テストは **`status` まで見る**形に直した |
| **A-3** | 同じ画像への同時 `POST` 8 本で **7 本が 500**（`IntegrityError`） | **`INSERT … ON CONFLICT DO NOTHING` → 再 `SELECT` → 負けた側は 200 で既存を返す**。**錠を外部の往復まで広げない**（設計の方針どおり）。**2 本同時のテスト**を足して「1 本が新規・1 本が `replayed`・行は 1」を固定 |
| **A-4** | 消えたグラフを `GET` が**消えたパスのまま**返し、`POST` が作り直さない | **`_existing_path()`** で `graph_path` は**実体があるときだけ**返す（`GET` は書かない）。**`POST` は既存を返す前に `_ensure_graph_file()` で PNG から作り直す**（`os.replace`・原子的） |
| **B-1** | グラフのファイル名が **`recipe_hash`** なので、**同じ鍵で印だけ違う 2 枚目が 1 枚目を書き換える** | **画像の内容ハッシュ**（`_asset_digest()`）に変更（§2.3）。テストで「2 枚目を書いても 1 枚目の中身が変わらない」を固定 |
| **B-2** | `KSampler` が無いと**リテラルでも** `text_not_captured` | **`text_unknown()`** を新設（`resolve_input` が**リテラルか結線先で解決できるなら「分かっている」**）。`judge` はこれを条件にする |
| **B-3** | `inspected` と `notes` が**行に残らない**（201 の応答だけ） | **`record_json` に `inspected` / `notes` を書く**（`_doc_of` が返す）。**グラフ無しの `POST` が「繋がらなかった」と言う**のも直した（グラフの有無と繋がり方は無関係） |
| **C-1** | 1 枚の `POST` が ComfyUI へ **16 本（最大 22 本）の `GET`**、実測 中央 128.7 ms | **目標（p95 300 ms）内**なので**持ち越し**（監査も「持ち越してよい」）。`class_type` ごとの**60 秒のキャッシュ**は P7-2 以降（§0.17 の表に記録） |
| **C-2** | `pin_text` + `text` の再送が **409** | **`pin_text` でも貼られた英文を `final_prompt` に残す**（出所 `manual`）。再送は **200**。テストを追加 |
| **C-3** | `graph_kind` が**常に `api`**（`api+ui` の 1 枚も） | **`record_json.graph_format`** を書く（`CHECK` が生きる）。`prompt` と `workflow` の両方を持つ PNG のテストを追加 |
| **G-5-(b)** | グラフ無しの `recipe_hash` | **空の SHA-256 のまま**（表は触らない）。等価判定は `graph_path IS NOT NULL` を条件にする（設計 §0.5・§5.1 に明記） |
| **G-6-(a)** | `GET /api/recipes` が重い | **要約だけ**返す（`_summary_of()`。`record` / `env` は 1 枚の口）。テストを追加 |

- **確かめたこと**: `uv run --no-sync pytest -q` → **369 passed**（**28 回連続で緑**。下の注記）、
  `node tools/gui_smoke.mjs` → **すべて ok**、`tools/probe_p7.py --judge`（実データの複製 263 枚）→
  **`exact` 182 / `approx` 1 / `impossible` 80**（**変わっていない**）。
- **残り**: C-1 の短命キャッシュだけ（P7-2 以降）。**D / E / F の指摘は設計の文面とテストの見直しで吸収**した。

> **注記（A-4 の直しで本物の不具合を 1 つ踏んだ）**: 最初、`record()` は**錠の中**から
> `_ensure_graph_file()` を呼んでいた。その中で `store.locked()` と `store.transaction()` を取るので
> **錠の入れ子**になり、同時に 2 本入ると片方が `OperationalError` で落ちる（**テストが 4 回に 1 回落ちて発覚**）。
> 錠の外へ出して直し、**28 回連続で緑**を確認した。**「揺れるテスト」は本物の不具合を見つける**という例
> （`docs/p6-1b-audit-report.md` の「壊しても落ちないテスト」の裏返し）。
> あわせて `test_two_posts_at_once_do_not_fail` は **`system_stats` にバリアを入れて「両方が錠の外に居る」**
> ことを保証する形にした（これが無いと、片方が先に書き終えて**衝突の経路を通らないまま**緑になりうる）。
