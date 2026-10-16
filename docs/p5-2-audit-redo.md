# P5-2 実装の監査報告（実行込みのやり直し）

- 監査した版: 2026-10-15 の作業ツリー（git 管理外。更新時刻は `p5-audit-redo.md` の冒頭と同じ。`compare.py` 19:52、`compare.js` 19:55、`styles.css` 20:18）。
- **実行できたかどうか: 全部実行できた。** 実行したもの（コマンド約 25。一時ファイルは `.tmp-audit-redo/`。ソースは編集せず、実データは `mode=ro`、サーバは `IMAGE_REVIEWER_DATA=.tmp-audit-redo\data-p52`（`db` + `thumbs` + `export` のコピー）で **8795**）:
  - `uv run pytest -q`: **169 passed**（`p5-audit-redo.md` の冒頭。`test_compare.py` 33 件を含む）。
  - **§H-3 の計測**（`bench_compare.py`）: 8 枚 × 20 / 60 / 200 / 1000 語、語順シャッフルと 1 語追加の 2 形。`diff_sequence` の呼び出し回数も数えた。
  - **§H-4 の実データ**（`probe_compare.py` / `probe_b2.py`、読み取り専用）: 先頭 8 枚の `build_document`、`final_prompt` の行、`final_prompt_source` の分布（183 枚）、捕獲した 1 枚＋他の組（基準の両向き）。
  - **§H-2 / H-5 / H-6**（`p52_api.py`）: `GET /api/compare` 8 枚の時間（初回・2 回目・10 回の中央値）、404 / 422 の 5 本、403 の 3 本、1 枚と 9 枚のまとまりの `compare`、来歴なし 2 枚の `seed` の行。
  - **純関数での再現**（同じスクリプト）: 前回 C2 / C3 / C4 / C6 / D1 / D3 / D5 と F7 の 3 件を `build_document` で 1 件ずつ。
  - **ブラウザ**（Chrome headless を CDP で駆動。`cdp.mjs` + `page_compare.js`、1400×900）: 実データの来歴あり 8 枚を `#/compare?ids=…` で開き、表の行と印、畳みの 1 行、`object-fit`、**「基準にする」ボタンのクリック**と **`b` キー**、ホイールでの同期ズーム、同期を切っての単独ズーム、`m` キー、`#cmp-heatwrap` / `#cmp-stage` の computed `display`、**BIZ UDPGothic での `tabular-nums`**（指示書 §3-5）。画面写真 `.tmp-audit-redo/shot-compare-8.png`。来歴なし 2 枚でも開いた。
- 総合判定: **使える。** 合格の線（8 枚を来歴つきで比べ、違う行だけが既定で見える）は**ブラウザで確かめた**。前回の B1（union の LCS）、B2（前置語だけの `final_prompt`）、C1（基準の切替）は**実行で直っている**。新たに分かったのは、(1) **`tabular-nums` が BIZ UDPGothic で効かず、seed の桁が揃わない**（設計点検 F3 / D10 の未確認が実行で確定。同じ書体一族の等幅版 `BIZ UDGothic` なら揃う）、(2) 前回 B2 の「実データではほぼすべてが再構成」は**事実と違う**（183 枚中 179 枚は `png_literal` で最終プロンプトを持つ。再構成で訳が無い枚は **0**）、(3) 前回 C2〜C8 / D1 / D3 / D5 / D6 / D10 は**そのまま**（§R）。

---

## A. 合格の線を満たしていない（必ず直す）

**無し。** ブラウザ（1400×900）で来歴あり 8 枚を開いた結果: 表は `changed` 15 行＋`only_in_some` 3 行＝**18 行だけ**が出て、各行に「違い」「一部のみ」の印、末尾に「同じ 3 行は畳んであります（m か「同じ行」で開く）」。`m` で **21 行**（`tr.row.same` 3 行）になり、もう一度で戻る。タイルは 8、`.cmp-frame img` の computed `object-fit` はすべて **`contain`**。

---

## B. 重大（静かに間違える）

**無し。** 前回の B1 / B2 は §R（実行で直っている）。

---

## C. 中程度（実行で新たに分かったこと）

| # | 場所 | 問題 | 利用者の側で何が起きるか | 実行したコマンド / 再現手順 | 提案 |
| --- | --- | --- | --- | --- | --- |
| **C1** | `apps/gui/styles.css:43`（`font-family: "BIZ UDPGothic", "BIZ UDGothic", "Yu Gothic UI", sans-serif`）、`:46`（`font-variant-numeric: tabular-nums`）、`docs/frontend-design.md` §2.3（`tabular-nums`。点検 2 回目 F3 / D10 が「効くか未確認」とした） | **`tabular-nums` が BIZ UDPGothic では効かない。** 書体に `tnum` が無い（`font-feature-settings: "tnum"` でも同じ）。来歴の差分表の `seed`（最大 20 桁）・`steps`・幅・高さの列で、桁数が同じでも幅が揃わない | 「733495470076873」と「3」を見比べる表で、同じ桁数の seed が縦に揃わず、桁を目で数える | **再現した（ブラウザで実測）。** `font-size: 14px` で「1111111111」と「9999999999」の幅: **BIZ UDPGothic + tabular-nums: 88.19 / 106.38 px**（違う）、`font-feature-settings: "tnum"` でも同じ、**BIZ UDGothic（等幅版）: 70 / 70**、Yu Gothic UI + tnum: 75.47 / 75.47、Segoe UI: 75.47 / 75.47（tnum 無しでも同じ）、Consolas: 76.98 / 76.98。`document.fonts.check` はすべて true（環境に入っている） | 数値のセル（`kind` が `num` / `seed`）だけ `font-family: "BIZ UDGothic", "Yu Gothic UI", Consolas, monospace` にする（同じ一族の等幅版で見た目が変わらない）。`frontend-design.md` §2.3 の「効かないときは `ch` 固定幅」を「数値は BIZ UDGothic」に書き換える（点検 D10 のとおり `ch` は代替にならない） |
| **C2** | `src/image_reviewer/compare.py:454`（`dict(meta.get("node_types") or {})`）、`:455, 559`（`textgen_params` を `params[k]` で読む） | 前回 D5。`meta` が `analyze_graph()` 以外の形（旧 JSON・手で直した sidecar）で `node_types` がリストだと `asset_item()` が **`ValueError`**、`textgen_params` がリストだと **`TypeError`** → `/api/compare` は **500** | 1 枚の壊れた来歴で、8 枚の比較が丸ごと開けない。画面は「比較できません: 500 …」 | **再現した（純関数で実行）。** `asset_item({"meta": {"node_types": ["KSampler"]}})` → `ValueError: dictionary update sequence element #0 has length 8`。`build_document([mk(textgen_params=["a"]), mk()])` → `TypeError: list indices must be integers or slices, not str`。実データ 183 枚はすべて `dict` なので今は起きない（`probe_b2.py` で確認） | `isinstance(…, dict)` でなければ `None` に寄せる（2 行） |

**確かめた結果、問題なし（実行）**:

- **§8 差分表 30ms（前回 B1）**: `bench_compare.py` — 8 枚 × 20 語 **2.2 ms** / 60 語 **6.2 ms** / 200 語 **25.2 ms**（語順シャッフル。1 語追加はそれぞれ 2.1 / 5.1 / 21.5）。`diff_sequence` の呼び出しは**どの語数でも 7 回**（画像ごとに 1 回。前回は語数 × 7 回）。1000 語で 256 ms（上限 `MAX_PROMPT_WORDS = 2000` の内側だが 30ms は超える。§E）。実データ 8 枚の `build_document` は **3.7 ms**。
- **`GET /api/compare` 8 枚（§H-2）**: 初回 **152.9 ms**（pHash 8 枚を埋める。P5-3 の修正）、2 回目 **32.5 ms**、以後 10 回の中央値 **23.2 ms**（HTTP 込み）。`nearest.distances` は初回から **8 / 8** 非 null。
- **基準の切替（前回 C1）**: タイルの「基準にする」（`.cmp-base` が 8 個、基準は「基準 ✓」）を 3 番で押す → `location.hash` に `&base=` が付き、上の 1 行が **「基準 3 番」**、`is-base` のタイルが 3 番、語の差分の見出しも「基準 3 番」。`1` → `b` で「基準 1 番」に戻る。マウスとキーの両方が動く。
- **同期ズーム**: 1 番にホイール（`deltaY -300`）→ 8 枚の `transform` がすべて `scale(1.56831)` の **1 種類**、倍率表示 1.57×。「同期ズーム: 切」にして 2 番にホイール → `transform` が **2 種類**（1 枚だけ動く）。
- **404 / 422（前回 C8。§H-5）**: `ids=a,nope` → **404**、`ids=nope` → 422、`ids=a&ids=nope` → 422（最後の 1 つだけ読む。D10 のまま）、`/api/groups/{id}/compare?ids=a,nope` → **422 `details.extra: ["nope"]`**（`api/compare.py:45-48`）。前回の判断どおり。
- **403（§H-6）**: `Host` / `Origin` / `Content-Type` の 3 本とも **403**（`/api/compare` と `/api/compare/pair`）。
- **8 枚のテスト（前回 F1）**: `tests/test_compare.py:662` `test_a_long_prompt_over_eight_images_stays_inside_the_budget` が 8 枚で組む。**入った。**
- **重み（前回 F7 の 3 件。純関数で実行）**: `<lora:x:0.8>` と `<lora:x:1.0>` → **`reweighted`**、`loras` 行の `strength_model` の差 → **`changed`**、語順と重みを同時に変えた `(c:1.3), a, b` → 行は `changed`、`per_asset` は `('(c:1.3)', 'moved', w='1.3')`（`base_w` は無い。前回 D2 のまま）。

---

## D. 軽微

| # | 場所 | 問題 | 提案 |
| --- | --- | --- | --- |
| D1 | `apps/gui/index.html`（`<link rel="icon">` が無い） | 画面を開くたびに `GET /favicon.ico` が **404**（サーバのログに毎回 1 行。ブラウザの console にも赤い 1 行）。実行で見えた | `<link rel="icon" href="data:,">` の 1 行 |
| D2 | `compare.py:72`（`MAX_PROMPT_WORDS = 2000`） | 1000 語で 256 ms（8 枚）。上限 2000 語は「秒に近づく」手前で切る値で、30ms の線（§8）は 200 語あたり。実データの最長は 40 語なので今は困らない | §8 に「30ms は 200 語まで。2000 語で語の差分を省く」と書く |
| D3 | `apps/gui/compare.js:157-160`（`sameSeed = seed.state === 'same'`） | 前回 C5。**ブラウザで再現**: 来歴なし 2 枚を開くと上の 1 行が「2 枚 / 基準 1 番 / **同一 seed**」。API の `seed` の行は `same`・`values: [null, null]` | `values` が全部 `null` なら出さない |

---

## E. 設計・`comparison.md` とのずれ

前回（`p5-2-audit-report.md` §E）のうち、実行で状態が変わったもの・事実が違ったもの:

| 項目 | 前回 | 今回（実行で確認） |
| --- | --- | --- |
| **§8 差分表 30ms** | 未計測・達成の見込み薄 | **達成**（200 語まで。上記） |
| **§0.8 C10 画面の基準の切替** | 未反映 | **反映**（ボタン + `b`。ブラウザで確認） |
| **前回 B2「実データでは 263 枚中、英訳を持つのは 1 枚なので、ほぼすべての比較で `final_prompt` が同じと出る」** | 前提 | **前提が違う。** `final_prompt_source` の分布（183 枚）: **`png_literal` で最終プロンプトあり 179**、来歴に無い 3、`reconstructed` で**訳あり** 1（捕獲した 1 枚）。**再構成で訳が無い枚は 0**。実データの 8 枚は `final_prompt` が**本当に違う**（`cells` が `changed` × 7）。B2 の修正（`unknown` / `incomplete`）は正しいが、現在の実データでは経路に入らない（`probe_b2.py`。ただし `test_compare.py:707-805` が作り物で守っている） |
| **`comparison.md` §6 `b` / `Tab`** | 未反映 | `b` は**反映**。`Tab` は無し（`1`〜`8` とクリックで足りる） |
| **`comparison.md` §3.1 「2 枚は左右 2 列の diff」「数値は増減が分かる形」** | 未反映 | **未反映**（表は値をそのまま並べる。画面写真のとおり） |
| **`index.html:12`** | — | 「比較（並べる / 来歴の差分表 / 同期ズーム）まで」のまま（P5-3 未反映。前回 P5-3 D11） |

---

## F. テストが守っていないもの

| # | テスト | 何を主張しているか | 実際に守っているか | 直し方 |
| --- | --- | --- | --- | --- |
| **F1** | `tests/test_compare.py:561` `test_real_assets_do_not_report_a_missing_final_prompt_as_same` | 「実データで、訳が無い枚を `same` と言わない」 | 実データに**その枚が無い**（再構成で訳が無い枚 0）。中身を読んでいないので、skip しているか作り物で代用しているかは不明。**名前が実データを指しているのに、実データでは起きない形** | 名前を直すか、作り物の方（`:707`）に一本化 |
| **F2** | `tests/test_compare.py:188` | 「削除は `removed`」 | **`removed` を 1 つも assert していない**（前回 F3 のまま。`grep removed` は `:181` のコメントにしか当たらない） | `tokens` の `removed` と `per_asset[b]` の形を固定 |
| **F3** | （無い） | 数値の桁揃え（C1） | 画面のテスト自体が無い（`gui_smoke.mjs` は CSS を持たない） | `styles.css` に `tnum` を頼らない書体指定があるかの静的検査でよい |

---

## G. 依頼者への質問

| # | 論点 | 私の推奨 |
| --- | --- | --- |
| G1 | 数値の書体（C1）: `BIZ UDGothic`（等幅版。同じ一族）か `Yu Gothic UI`（tnum が効く）か | `BIZ UDGothic`。見た目が変わらず、数字以外の記号も揃う |
| G2 | 前回 G2〜G6（`final_prompt` の `None`、行の `moved`、`textgen_system_prompt` / `en_source` の鍵、9 枚以上の既定）はいずれも**未着手のまま**（§R）。この段で入れるか P6 以降か | `textgen_system_prompt` / `en_source`（C4）と行の `moved`（C2）は 10 行で済むので今 |

---

## H. 今回も確かめられなかったこと（＋できない理由）

| 項目 | 状態 | 理由 |
| --- | --- | --- |
| 前回 D11（横長が 2 行目に並ぶと `flex-wrap` で 3 行になり溢れる） | **未確認** | 実データの 8 枚は 1024² と 1360² で縦横比が揃っている。混ぜた組は P5-3 の画面確認で見る |
| 前回 C7 の「9 枚以上のまとまりの画面」 | 画面の入口が無い（`app.js` に `group=` へ入る道が無い）ので API だけ | **API は再現**（§R） |
| 指示書 §3-5 の `control_after_generate` / 別ボリューム | **できない**（`p5-audit-redo.md` §H） | 同左 |

---

## R. 前回の指摘の再判定

前回 = `docs/p5-2-audit-report.md`。行番号は現物。

### 前回 B

| # | 前回の主張 | 再判定 | 根拠（実行） |
| --- | --- | --- | --- |
| **B1** | `_union_tokens` が語ごとに LCS を回し直す | **直っている（再現しない）** | `compare.py:768-826`（`item_states` を受ける）。計測: `diff_sequence` は語数に依らず **7 回**、8 枚 × 200 語 **25 ms** |
| **B2** | 捕獲していない `final_prompt` に前置語だけを入れる | **直っている（再現しない）。ただし実データの前提が違う** | `compare.py:413-430`（`(None, True)`）、`:594-654`（`unknown` / `incomplete` / `known_prefix`）、`compare.js:332-347`（「分からない」のセル）。実行: 来歴なし 2 枚で `final_prompt` の行が **`unknown`**（ブラウザの表に `final_prompt:unknown`）。実データに再構成で訳無しの枚は 0（§E） |

### 前回 C

| # | 再判定 | 根拠 |
| --- | --- | --- |
| **C1** 基準を変える口が無い | **直っている** | `compare.js:269-272, 283-290, 302-314, 765`。ブラウザで両方確認 |
| **C2** 語順だけの違いが行では `changed` | **再現した（純関数）** | `compare.py:549-564, 567-571`（署名は順序つき）。`"1girl, solo, chibi"` / `"chibi, 1girl, solo"` → 行 `changed`、`cells ['same','changed']`、`per_asset` は `['moved','same','same']` |
| **C3** `node_types` の個数の差が `same`、画面は `only_in` を使わない | **再現した（純関数＋画面写真）** | `compare.py:557`（`frozenset(raw.keys())`）。`{"KSampler": 2}` と `{"KSampler": 1}` → **`same`**、`only_in` は両方 `[]`。画面写真: 「ノード」の行は各セルに全部の型名が並ぶ |
| **C4** `textgen_system_prompt` / `en_source` が鍵に無い | **再現した** | `compare.py:143-167`。`"textgen_system_prompt" in doc["diff"]["keys"]` → **False**、`en_source` も False |
| **C5** 来歴なしで「同一 seed」 | **再現した（ブラウザ）** | 本報告 D3 |
| **C6** 基準にあって無い語が `per_asset` に出ない | **再現した（純関数）** | `"1girl, solo, chibi"` / `"1girl, solo"` → `per_asset[b]` は `['same','same']`、`tokens` に `('chibi','removed')` だけ |
| **C7** 1 枚・9 枚のまとまりの既定 | **再現した（HTTP）** | 1 枚 → 422「比較には 2 枚以上が要ります」、9 枚 → 422「一度に並べられるのは 8 枚までです」 |
| **C8** 404 / 422 の番号 | **仕様どおり（HTTP で確認）** | 上記 |

### 前回 D

D1（`16:9` → `('16', 9.0)`、`(a : 1.2)` → `('a : 1.2', 1.1)`、`ratio 1:1` → `('ratio 1', 1.0)`。**再現した**。`compare.py:299`）、D2（`moved` に `base_w` が無い。**再現した**）、D3（3 枚で重みだけ違う枚のセルも `changed`。**再現した**: `[('changed', ['same','changed','changed'])]`）、D4（`diff.keys` は画面が読まない。**残る**。`compare.py:902`、`compare.js` に参照無し）、D5（**本報告 C2**）、D6（`group_state` が `transaction()`。**残る**。`review.py:289`）、D7（比較のタイルに来歴なしの印が無い。**残る**。`styles.css:122-126` は一覧だけ）、D8（**残る**。§E）、D9（初回は 1024 と 256 を作る。**残る**。初回 `GET /api/compare` 153 ms はハッシュの分で、サムネイルは `thumbs/` のコピーがあるので計っていない）、D10（**再現した**。HTTP）、D11（**未確認**。§H）、D12（`reviewed_by` が `user` → `human` に直される。**P5 の取り込み試験で再現**: `p5-audit-redo.md` §R-B1）。

### 前回 F

F1（**直っている**。`:662` が 8 枚）、F2（`diff.keys` の順を見る。**残る**。`:232-248`）、F3（**残る**。本報告 F2）、F4（行の `state` を見ない。**残る**）、F5（`final_prompt` の行を見ない。`:488` は `en_text` だけ。**残る**。ただし `:561` が別に見る）、F6（計測スクリプト: 無い。**今回の `bench_compare.py` がその代わり**）、F7（3 件: **実行で挙動は正しい**。テストは無い）、F8（`node_types` の個数: **無い**。C3 のまま）、F9 / F10（問題なし）。「今すぐ要るテスト」の 1（B2 の形）は `:707-805` で**入った**、2（LCS の回数）は `:635` で**入った**、3（C5）・4（C8）・5（画面）は無い。

### 前回 §H

| § | 再判定 |
| --- | --- |
| H-1 | 169 passed |
| H-2 | 23.2 ms（中央値）。画面の (1)〜(7) すべて確認。(7) は**直っている** |
| H-3 | 20 語 2.2 / 60 語 6.2 / 200 語 25.2 ms。**B1 は直っている** |
| H-4 | 実データ 8 枚 3.7 ms。`final_prompt` の行は `changed`（本当に違う）。**B2 の経路は実データに無い** |
| H-5 | 404 / 422 / 422 / 422（`details.extra`） |
| H-6 | 403 × 3 |

---

## 最も重大な 3 件

### 1. `tabular-nums` が BIZ UDPGothic で効かず、差分表の数値の桁が揃わない（C1。**実行して初めて分かった。実装者も設計の点検も気づいていない**）

設計の点検（2 回目 F3 / D10）が「BIZ UDPGothic が `tnum` を持つかは未確認」と残した件を、ブラウザで実測した。同じ桁数の「1」と「9」の並びで幅が 88 px と 106 px に割れ、`font-feature-settings: "tnum"` でも変わらない。来歴の差分表は seed・steps・幅・高さの数値を縦に見比べる表なので、桁が揃わないと一番見たい列が読みにくい。同じ一族の等幅版 `BIZ UDGothic` が入っていて 70 / 70 px で揃うので、数値のセルだけ書体を変えれば済む。

### 2. `node_types` が型の個数を落とし、画面は集合の差を使わない（前回 C3。**実行で再現**）

`KSampler` が 1 つの絵と 2 つの絵（hires-fix / refiner の有無）が「同じ」になり、画面写真では「ノード」の行の各セルに全部の型名が並んでいて、差を取るのは利用者の目のままである。点検 C5 が求めた「集合の差」はサーバの `only_in` に計算してあるのに、画面がそれを読まない。署名を `tuple(sorted(raw.items()))` にして、セルは `only_in` だけを出す。

### 3. 削除された語が画像ごとの行に出ず、語順だけの違いが行では「違い」になる（前回 C6 / C2。**実行で再現**）

基準にあって 3 番に無い語は、3 番の行には出ず「全」の行にしか出ないので「どの画像で消えたか」が読めない。語を入れ替えただけの 2 枚は表の行で「違い」の印がつき、語の差分を開いて「移動 3 語」を見るまで分からない。どちらも `prompt_diff` と `_row` の 10 行程度で直る。前回 G2〜G6 の問いが未回答のまま残っているので、この段で決めてほしい。
