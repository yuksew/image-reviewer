# P6-2（注記と切り出し）の実装の記録

- 実装: 2026-10-16（DeepSeek 側）。設計は [`p6-design.md`](p6-design.md)（**§0 が拘束力のある差分**）
- 位置づけ: **P6 の最後の段**（R11）。これで P6 の合格の線 1〜3 がそろう

## 1. 作ったもの

| ファイル | 行 | 中身 |
| --- | --- | --- |
| `src/image_reviewer/annotations.py` | 新規 約 430 | `AnnotationService`（作る・一覧・メモの変更・削除・座標 JSON・切り出し・起動時の `*.tmp` 掃除）、`crop_box()`（純関数） |
| `src/image_reviewer/api/annotations.py` | 新規 約 90 | `GET/POST /api/assets/{id}/annotations`、`PATCH/DELETE /api/annotations/{id}`、`GET .../export?format=json`（書かない）、`POST .../export {format:'crops'}`（書く）、`GET /api/annotations/{id}/crop`（その場で返す） |
| `apps/gui/annotations.js` | 新規 約 300 | 拡大（`#/asset/<id>`）の注記: ドラッグで矩形・Shift で楕円、**4 px 未満は作らない**、メモ（画像 1 枚へのメモも）、一覧（人 / エージェント・切り出し・消す）、座標 JSON と切り出しの書き出し |
| `apps/gui/app.js` / `styles.css` | 変更 | `select()` から `mountAnnotations()` を呼ぶ（**注記の入口**。点検 C5 / C13）、注記の見た目 |
| `tests/test_annotations.py` | 新規 14 件 | §8.1 の 11〜19・28〜30 |
| `tools/probe_p6_2.py` | 新規 | 実機（サーバ）で合格の線 3 を通す |
| `tools/gui_smoke.mjs` | 変更 | §8.2-6（4 px 未満では作らない／以上で 1 回だけ POST）＋ 作り物の DOM に `getBoundingClientRect` / `replaceWith` / `insertAdjacentHTML` / `created` を追加 |

## 2. 実行した確認（すべて緑）

| 何 | 結果 |
| --- | --- |
| `uv run pytest -q` | **222 passed**（P6-1b までの 208 ＋ 新規 14） |
| `node tools/gui_smoke.mjs` | **すべて ok**（注記の 4 件を追加） |
| `uv run python tools/probe_p6_2.py --base http://127.0.0.1:8791` | **すべて ok**。実データのコピーで **1024² → 256×256 / 2048² → 512×512 / 1536² → 384×384** の切り出し、座標の丸めなし往復、`GET` が `crops: null`、その場の切り出しも PNG |
| 画面写真 | `.tmp-audit-redo/shot-p6-2-annotations.png`（印が絵の上に出る）／`shot-p6-2-list.png`（一覧・メモ・書き出しのボタン） |
| 実データ `.data/` | **未変更**（触ったのは `.tmp-audit-redo/data-p52` のコピーだけ） |

## 3. 自分で決めた所（設計が黙っていた）

1. **`GET .../export?format=json` の `image` は DB の実寸**（`asset.width/height`。P5 が実体から写した値）を使う。
   無ければ復号して実体から取る。理由: 座標だけの書き出しが**実体を要求しない**ようにするため
   （実体が無いときに 409 にしない）。
2. **`POST .../export` の応答は契約（`annotation-export`）の文書そのもの**にした（設計 §3.6 の
   スケッチは `{"files": [...]}` だが、契約 §6.2 は `crops` を持つ文書。**契約を正**とした）。
3. **切り出しを書くときに領域なしの注記が混ざっていたら 422**（全体を書かない）。§3.6 の 1 行どおり。
4. **`annotation_ids` を渡したときは、その画像の注記だけを許す**（他の画像のは 422 `details.extra`）。
5. **`PATCH` は `body` だけ**、`DELETE` は行を消してから PNG を消す（消せなくても警告なしで続ける。
   §6.3 の「害は小さい」）。
6. **`actor` の検査はサービス層**（`PATCH` / `DELETE`）。表の `CHECK` は `human` / `agent` だけを見る。
7. **注記の追加は `#detail` の中**（設計の「右の列」は、いまの詳細ペインが右の列そのもの）。

## 4. 未実装・次の段に残したもの

- **`tools/gui_layout.mjs` の §8.3-2 / -3**（注記 20 個で右の列が外に出ない・印が画像の外に出ない）は
  **未着手**。`MEASURE` に「カードの `right`」「注記の一覧の `bottom`」「印の箱」を足す設計（点検 F13）までは
  決まっているが、実装は次の段（P6-2 の監査の後か、監査で指摘されたとき）に回す。
- `frontend-design.md` §4.3 は**既存の記述のままで足りた**（新しい画面・部品を発明していない）。
- 要求の一覧（`#/requests`）やまとまりレビュー（`#/group/<id>`）は P6-1b の担当（実装済み）。

## 5. 気づいた設計の穴（監査で判断してほしい）

1. **`GET /api/annotations/{id}/crop` は「その場で作る」ので、大きい囲み（2048² 全面で約 93 ms）を
   何度も要求できる**。§7 の目標は「画素数に比例」なので外れていないが、**連打の抑制**（画面側の
   間引き）は設計に無い。いまの画面は 1 件ずつリンクなので実害は小さい。
2. **注記の一覧に「どの注記がどの印か」の対応**が番号だけ（印の番号と一覧の番号）。設計 §4.3 は
   「押すとその領域へ寄る」と書くが、**寄せる（スクロール・ズーム）は未実装**（印が小さい絵では
   番号で足りるため）。やるなら P6-2 の後続。
3. **`response.annotations` に入るのは `group_id` が一致する注記だけ**（§0.2）。まとまりのレビュー中に
   付けた印（`group_id` 付き）は入るが、`#/asset/<id>` から直接付けた印は入らない。設計の
   想定どおりだが、**画面の導線（まとまりレビュー → 拡大）で `group_id` を引き継ぐ**必要がある
   （P6-1b の「選んだ 1 枚を拡大で開く」は `#/asset/<id>` に移るだけなので、いまは `group_id` が付かない）。

---

## 6. 監査（`p6-2-audit-report.md`）の後の追記 — 2026-10-16

**この節は監査の指摘を直した後の記録。** 上の §3-3・§4-1・§5-3 の記述は**この節が上書きする**。

| 直した所 | 何をしたか |
| --- | --- |
| 監査 上位 1（右端・下端で 500） | `crop_box()` の `left` / `top` を **`W - 1` / `H - 1` まで**に抑え、`right = left + 1` で**必ず 1 画素**残す（`x = 1 - 1e-12, w = 1e-12` で幅 0 → `PIL cannot write empty image` → 500 になっていた）。`tests/test_annotations.py` に境界のテストを追加 |
| 監査 上位 2（領域なしで全体が止まる） | **§3-3 の判断を変更**（監査 §D-3 の推奨）。`annotation_ids` を**指定しない**画像全体の書き出しでは**メモを黙って飛ばす**（`crops` は書けた分だけ。422 にしない）。**名指し**なら 422 で `details.annotation_id` に**その id**（以前は文言が入っていた。`crop_png` も同じく id に直した）。`tools/probe_p6_2.py` は**すべて ok** になった（メモが混ざると 422 で落ちていた） |
| 監査 上位 3（一覧と印の番号のずれ） | `annotations.js` の番号を**一覧の並び（古い順）で全件**に振り、**印も同じ番号**にした（メモを飛ばして別々に数えていた）。メモの行には「切り出し」リンクを出さない（押すと 422）。`tools/gui_smoke.mjs` に「メモが間にあっても一覧の N と印の N が一致する」検査を追加 |
| 監査 §F-1（`gui_layout.mjs` の §8.3-2 / -3 が無い） | **`--screen asset --ids <1 枚>` を追加**。3 窓で「印が画像の中（`outside=0`）」「一覧が横に溢れない」「**印の番号が一覧の番号と同じ**」「入口がスクロール無しで見える」を見る。実測: 20 件で `marks=19 rows=20 outside=0 listOverflow=0 boxTop=341px visible=true`、番号は `markNos=[1,3,…]` / `rowNos=[1,2,3,…]` |
| 監査 §D-7（入口が来歴の下 2665 px） | 注記の箱を **`#detail` の末尾から画像のすぐ下**へ移した（`stage.parentNode.insertBefore(box, stage.nextSibling)`）。実測 **2665 px → 341 px**、3 窓とも**スクロール無しで見える** |
| 監査 §E-1（設計の `{"files": ...}`） | `docs/p6-design.md` §3.6 を**契約の文書を返す形**に直した（`crops` の配列） |
| 監査 §E-4（穴 3 の記述が古い） | **§5-3 は 05:42 版の JS で塞がっている**（`group.js` が `?group=` を付け、`app.js` が `setAnnotationGroup` を呼び、`annotations.js` が POST の `group_id` に入れる。監査 §C-8 で確認済み）。**上の §5-3 の「いまは `group_id` が付かない」は誤り** |

- 実行の結果（直した後）: `pytest` **224 passed**、`gui_smoke` **すべて ok**、`gui_layout` は
  比較・要求・まとまり・**注記（新）**の 4 画面すべて ok、`probe_p6_2.py` **すべて ok**。
