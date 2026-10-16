# P7 設計の点検の仕分け（Fable の点検 → どう直したか）

- 点検報告: [`p7-review-report.md`](p7-review-report.md)（**判定: 直してから実装**。A 3 / B 6 / C 9 / D 12 / E 11 / F / G 7 / H / I）
- 立場: **すべての指摘と G-1〜G-7 の推奨を採用**した（G は「待たずに推奨で進めてよい」とされた）。
  反映先: [`p7-design.md`](p7-design.md)。**利用者に新しく聞くことは無い**（§0.14 に「G-1〜G-7 も推奨どおりで確定」と 1 行足した）。

## A. 設計の主張が成り立たない（必ず直す）

| # | 指摘（要約） | どう直したか |
| --- | --- | --- |
| **A-1** | 検査③が**動的コンボの入れ子名**（`TextGenerate.sampling_mode.temperature` など 7 つ）を「宣言に無いキー」と誤判定し、実データで唯一 `TextGenerate` を持つ 1 枚（ja2en の経路）を `unresolved` で止める。**ComfyUI はそのグラフを実行しているので検査の方が間違い** | **§0.8 を直した**: `COMFY_DYNAMICCOMBO_V3` を**展開**（`inputs[<name>]` の値に対応する `options[].key` の `required` / `optional` を `<name>.<key>` として足す）。**`COMFY_DYNAMIC` で始まる型で展開できないものは検査の対象外にして `notes` に出す**（黙って `unresolved` にしない）。**§0.6 で `unresolved` の重さを確定**（モデルが combo に無い → `impossible`／キーの差 → `approx` ＋ キー名。G-7-(a)）。**§8.1-31 に「展開を外すと落ちる」テスト**を足した |
| **A-2** | §2.1 の DDL が §3.3 の約束と**3 点で矛盾**（実測で確認） | **(a)** `recipe_export.marker` を **NULL 可**にし `CHECK ((marker IS NULL) <> (marker_skip_reason IS NULL))`。**(b)** **束の表 `recipe_export_attempt`** を足した（`attempt_id` 主キー・`client_token` UNIQUE・`checked_json`・`manifest_path`・`export_dir`・**`seed_node`**・`created_at`）。`recipe_export` は**その中の 1 ファイル**（`attempt_id` 参照）。**(c)** `ux_export_attempt_seed` を **`COALESCE(seed,'')` の式の索引**にして **seed NULL でも一意**（前の版は NULL で 2 行入った） |
| **A-3** | **記録時の判定と書き出し時の判定が混ざり**、線 2・線 4・§8.1-1 が設計のままでは評価できない | **§0.6 に表を足して分けた**: 記録時は **7 語**（`missing` / `text_not_captured` / `node_missing` / `unresolved` / `version_differs` / `hash_mismatch` / `gpu_differs`）、書き出し時は **`text_pinned` / `llm_nondeterministic` / `manual_step`**（`checked_json` と束の表）。**`text_not_captured` は「到達部分グラフに `CLIPTextEncode` があるのに文字列が分からないとき」だけ**。**線 2 を数で書き直した**（この環境・この版で **`exact` 183 / `approx` 0 / `impossible` 80**。環境が変わったら「`impossible` ≥ 80、超えた分は `node_missing` / `unresolved`」）。**線 4 を mode 明記に**（`rerun_graph` で鍵が記録と一致／`pin_text` で変わるのは `TextGenerate` を持つ 1/183 だけ）。**§0.5 を「鍵はグラフだけの純関数」に直した**（`(size, mtime)` は `env_snapshot` と `hash_mismatch` の材料に留める）。**§8.1-32・33** を足した |

## B. 重大（すべて §0.9 / §0.8 / §0.7 / §6.1 / §7 に反映）

| # | どう直したか |
| --- | --- |
| **B-1** | **§0.9 に「結果の画像の実体」の行を足した**（G-1-(a)）: 設定 **`comfyui.output_dir`**（既定は `/internal/folder_paths` から推定し、**実在するときだけ**。この環境では当たる）。**監視の開始時に出力先を登録ルートに足す**（1 回だけ利用者に確認）。当たらなければ **`GET /view` で `<data>/results/<sha256>.png` に取り込む**（画面に 1 行）。**§2.3 に置き場**、**§0.15-13** に本文（§19.3-10）との関係 |
| **B-2** | **§0.8 を逆にした**: **使った `class_type` だけ `/object_info/{class_type}`** で引く（≤ 20 回・0.7〜3.0 KB・0 ms）。**全体（2.39 MB・0.41〜0.91 秒）は引かない**。**§7 を書き直した**（`check` の目標を **p95 50 ms** に。未計測 3 行を実測で埋めた: 一覧 中央 4.5 ms・詳細 1.4 ms・鍵 0.03 ms/グラフ・`json.loads` 12〜17 ms） |
| **B-3** | **§0.9 の表を書き直した**: 既読の基準を **`baseline_create_time`（ms）＋処理済み id の集合**（`last_prompt_id` は表示用）／**`?status=completed`** で引き、`pending` / `in_progress` は**既読にしない**／**`execution_cached` は「保存ノードの id が含まれるとき＝新しい画像は出ていない」**と定義／**一覧の `outputs_count` / `preview_output` で詳細を取る job を絞る**（タグ付けは `outputs_count: 0`）。**§1.3 の 2 行**も実測に直した |
| **B-4** | **§0.7 を直した**: **`subfolder` はバックスラッシュ**で返るので、照合は **`subfolder.replace("\\","/") + "/" + filename` の形に寄せてから前方一致**。`capture.py` の `/` → `\\` と**どちらかに統一**（P7 は比較の直前に `/` へ）。**`<output>/repro-<attempt_id>/` が増える**ことを manifest と画面に書く。**`attempt_id` は 8 文字以上の `[a-z0-9]`**（D-12） |
| **B-5** | **§6.1 の契約を直した**: `notes` を**型つき**（`status` / `reasons` / `inspected` / `instruction` を `required`）にし、**`mode` / `marker_skipped` / `source`（要約）**を足した。`export_hashes` の値は **`sha256:` で縛る**。`seeds` は **`minItems: 1`**（seed 無しは `{"seed": null, …}`）。**§8.1-41** に「でたらめな `status` は落ちる」を足した |
| **B-6** | **§0.12 を直した**: **API でも `seeds` を文字列**（`["1","2"]`）に統一。**`seed + k` は `(seed + k) mod 2^64`**。**§5.3 の文言を実測に合わせた**（読み込み直後は `randomize`・mode は `after` → **「1 ファイルにつき Queue は 1 回。2 回目を押す前に `fixed` にする」**）。**§10-2 を「未確認」から「分かった」に**（E-5） |

## C. 中程度

| # | どう直したか |
| --- | --- |
| **C-0** | 「確かめた結果、問題なし」の 14 項目を**そのまま設計の前提として残した**（`EXPLAIN` の 6 索引は束の表を足したので **§2.2 に 2 本追加**して §8.1-22 で見る） |
| **C-1 / G-5** | **記録は画像 1 枚に 1 つ**。`ux_recipe_source` を **`source_asset_id` だけ**にし、`mode` は「既定（画面の初期値）」と明記（§2.1・§2.2・§0.10） |
| **C-2** | **`seed_node`** を束の表に置いた（§2.1・§3.1） |
| **C-3 / G-3** | `preset.source_asset_id` と `recipe_export_result.result_asset_id` を **`ON DELETE SET NULL`**、`recipe_record.source_asset_id` は **RESTRICT のまま**＋**P8 への申し送り 1 行**（§2.1 の末尾）。**§8.1-42** にテスト |
| **C-4 / G-2** | `verdict_at` / `verdict_actor` を足して**上書き**。「消えない」＝**「再起動・再読込で失われない」**と §4.2 に定義 |
| **C-5 / G-4** | `seeds` / `count` を明示したら **422 `no_sampler`**、無指定なら **seed 無しの 1 ファイル**（印 `…/noseed`）。A-2c の式の索引と組で §0.12・§2.1・§6.1 に反映 |
| **C-6** | 監視の接続先を設定 **`comfyui.url`** に寄せ、`POST /api/watcher/start {base_url?}` でも受ける。**設定は `start` のたびに読む**（§0.9・§3.1） |
| **C-7** | §8.1-37 に「**2 頁の重複ゼロ・合計が `limit=1000` と一致**」を足した（P4-3 の再確認で `GET /api/tags` が踏んだ罠） |
| **C-8** | §0.6 に「**P7 では `graph_source='png'` しか出ない**（`'history'` / `'sidecar'` は語彙に残す）」と書いた |

## D. 軽微（12 件すべて反映）

**D-1**（実データは全部 PNG。80 枚は `prompt` チャンク無し）→ 線 1 と §0.7 に明記／**D-2**（`__OUTPUT_PREFIX__` が 172 枚）→ §0.7 と §5.3 の文言／
**D-3**（`graph_kind` に 2 値は入らない）→ §2.1 の注記／**D-4**（グラフが残っていないときは 422）→ §0.12／**D-5**（根は `SaveImage` / `PreviewImage`）→ §0.12／
**D-6**（「**ComfyUI の** `/api/jobs`」と書く）→ §0.9・§1.3／**D-7**（`<data>/recipes/…`）→ §0.10・§2.3・§1.2-3／**D-8**（`watcher_state` は P7 の形が正）→ §0.15-10／
**D-9**（`workflow-reproduction.md` §5 の重複段落）→ §0.15-14（§12-7 へ）／**D-10**（同じ token・別の画像 → 409）→ §0.10／
**D-11**（403 を確かめる `POST` は **7 本**）→ §3.1／**D-12**（`attempt_id` は 8 文字以上・`subfolder` の正確な一致）→ §0.7

## E. `design.md` / 本文とのずれ（§0.15 に 9〜14 を足した）

**E-1**（一覧の欄）→ §1.3 を実測に直した／**E-2**（`POST /api/presets` の形）→ §3.1 に「`design.md` を直す側」／
**E-3**（watcher の 3 口）→ §0.15-9／**E-5**（`loadApiJson` と `control_after_generate` は**確認できた**）→ §10-2 を「分かった」に／
**E-7**（`unresolved` の重さ）→ §0.6・§0.15-11／**E-8**（§7 の未計測 3 行）→ 実測で埋めた／**E-9**（`execution_cached`）→ §0.9・§1.3／
**E-10**（`watcher_state`）→ §0.15-10／**E-11**（登録ルート外）→ §0.15-13。
**E-4 / E-6 は「一致（問題なし）」**としてそのまま。

## F. テストで守れないもの（§8.1 に 31〜43 を足した）

**§8.1-1** に mode を明記（`rerun_graph` で比べる）＋**合成グラフに `TextGenerate` 入りを 1 つ含める**／**§8.1-4** を記録時と書き出し時に分けた／
**§8.1-12** を「動的コンボの入れ子名は宣言に含まれる」に書き直し、**「本当に無いキーは `unresolved`」を別に置いた**（フィクスチャは実物の 5 ノード分）／
**§8.1-16**（束の表で書けるように）／**18**（`outputs_count: 0` で弾く）／**20**（`create_time` 基準＋`in_progress` を混ぜる）／
**24**（v6 の移行。v5 の複製と v3 の控えでも）／**25**（`review.json` に足さない）／**26**（`notes` の型）／**30**（`seed_node`）。

## G. 依頼者への質問（**すべて推奨を採用**）

**G-1**-(a)（`comfyui.output_dir` ＋ 登録ルート）／**G-2**-(a)（上書き＋`verdict_at` / `verdict_actor`）／
**G-3**-(a)（`SET NULL` と RESTRICT）／**G-4**-(a)（`no_sampler` と seed 無し 1 ファイル）／
**G-5**-(a)（画像 1 枚に 1 記録）／**G-6**-(a)（線 9 は任意・門は線 6）／**G-7**-(a)（`unresolved` の重さ）。
**§0.14 の末尾に 1 行足して「確定」とした**（利用者に新しく聞くことは無い）。

## H. 確かめられなかったこと（設計に残した）

- **線 9（利用者の 1 回の生成）は任意**（G-6-(a)）。**利用者が 1 回回したら §J として追記する**。
- **`TextGenerate` の `sampling_mode` 以外の動的コンボ**は実データに無い（展開の実装を一般化しておく）。
- **`system_prompt` を変えたときの訳の崩れ方**（P4-2 からの申し送り）は P7 の対象外。
