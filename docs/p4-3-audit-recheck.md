# P4-3 監査の再確認（指摘の直しを実行で確かめた）

- 日付: 2026-10-16（12:15〜12:40）。監査者: Fable（Claude Code）
- 元の監査: `docs/p4-3-audit-report.md`。仕分け: `docs/p4-3-audit-triage.md`（12:12）
- 対象（直した版）: `src/image_reviewer/jobs.py`（11:57）/ `tags.py`（11:57）、`apps/gui/jobs.js`（11:58）/ `badge.js`（12:00）/ `app.js`（12:01）/ `taglist.js`（12:08）、`tools/gui_smoke.mjs`（12:04）/ `gui_layout.mjs`（12:05）、`tests/test_tags.py`（12:03）、`docs/frontend-design.md`（12:10）/ `p4-design.md`（12:11）
- 環境: 前回と同じ（`uv run --no-sync`、実データは `mode=ro` のみで mtime 不変、複製 `.tmp-audit-redo/p43/srv` を 8791 で、Chrome headless で `fetch` を数える。本物の ComfyUI でタグ付けと訳）。一時物は `.tmp-audit-redo/p43/page_re_*.js` と画面写真 `shot-re-*.png`。ソースと既存の文書は編集していない。監査のサーバは停止済み。

---

## 判定: **直した 6 点はすべて実物で通った。C-3・C-5 も通った。P4 を閉じてよい。ただし C-2 の「次の 200 語」が見せた API の頁送りの欠陥（B-1）を P4 の残件として記録する。**

| # | 指摘 | 直し | 実物での結果 | 判定 |
| --- | --- | --- | --- | --- |
| A-1 | `#/jobs` に失敗した項目と「もう一度」が出ない | `JobService.list()` を `failed_limit=20` に。`counts` の行は `failed` だけでも出す | 失敗の行に **`失敗 1 件`・`01AUDITNOFILE… FileNotFoundError: … gone43.png`・「もう一度」・`付いた 0 ・ 飛ばした 0 ・ 失敗 1`**。「もう一度」を押すと `POST /api/assets/tag {"asset_ids":["01AUDITNOFILE…"],"engine":"auto"}` → **新しい行が 1 つ増え**、それも `失敗 1 件`＋「もう一度」つき | **直った** |
| A-2 | `#/tags` の詳細の「訳す」が 422 | `items` に `tag_id`、画面は `item.tag_id`（`translateIds`） | `GET /api/assets/{id}/tags` の `items` 全 61 行に整数の `tag_id`（契約の `review.json` は変えていない）。詳細の「訳す」→ **`{"tag_ids":[343],"limit":20}`（`human`）→ 200**、`outdoors → 外で` が一覧に出る | **直った** |
| B-1 | 完了ジョブの「1 枚 X 秒」が増える | `finished_at` で計算 | 完了の行 `1 枚 0.4 秒` が 4.6 秒後も **`1 枚 0.4 秒`** | **直った** |
| B-2 | 「保存しました」「N 語を訳しました」が消える | `load()` の後に知らせる | 「1 語を訳しました。」「保存しました（人が直した語釈になります）。」「20 語を訳しました。」が **2.5 秒後も出たまま** | **直った** |
| C-1 | タグ欄が来歴の下 1,635 px | 画像のすぐ下へ | `#tg-panel` は `#detail` の先頭から **575 px**（画像の下 327 → 注記の箱 341 → タグ欄 575 → 来歴）、**スクロール無しで見える**。`gui_layout --screen asset` が `tgTop=575px tgVisible=true` を毎回出す | **直った** |
| C-2 | `#/tags` が 200 語で打ち切り | 「次の 200 語を読む」（`next_cursor`） | 押すと `GET /api/tags?known=all&limit=200&cursor=bare_legs` → 行は **200 → 400**。**しかし 400 行のうち 183 行が重複**で、頭の表示が `200 / 630 語` → `400 / 593 語` に変わる（§B-1） | 画面は直ったが **API の頁送りが壊れている** |
| C-3 | 5 秒未満のジョブの「終わりました」が出ない | 前回の周期以降に `finished_at` が入った `done` も知らせる。初回は「いま」を基準 | 清い状態で開くとバーは**隠れたまま**（古い完了で鳴らない）。2 枚のジョブ（1.3 秒で完了）→ **2.2 秒後に `タグ付けが終わりました（2 枚）`** | **直った** |
| C-4 | 「その他」の見出し | `frontend-design.md` §4.13 に 1 行 | 文書の変更（読んで確認） | 妥当 |
| C-5 | `queued` の印が「待ち」 | `待っています` | `STATE_LABEL.queued` は `待っています`（`gui_smoke` が固定）。実機では job が即 `running` になるので `queued` の行は見えなかった（`実行中` → `完了`） | 直った（コードと smoke で） |
| §8.3-3 | 行の高さの検査が折り返しで NG | 折り返した `.ja` を除く | 画像 B（247 行）は `高さの差=2px 折り返し=0` で ok。画像 A はまだ **NG（差 20px）**: 原因は **長い語名 `she_is_holding_a_syringe_in_one_hand` が `.en` の行で折り返す**（`.en` 42 px）。除外は `.ja` だけ | **検査の作りがまだ足りない**（§C-1） |

**回帰**: `uv run --no-sync pytest -q` → **283 passed**。`node tools/gui_smoke.mjs` → **129 ok**（122 → +7）。`gui_layout`: タグ一覧・ジョブ（13 件）・比較・要求・まとまり・注記（画像 B）**ok**。画像 A の注記/タグは上の検査の作りの件で NG。実データ `.data/` の mtime は 10-15 のまま。

---

## B. 重大（新しく見えた）

### B-1. `GET /api/tags` の `cursor` が「名前」なのに並びが「使用数」で、頁送りが壊れている（`src/image_reviewer/tags.py` `list_tags`。P4-1 の実装）
- 実測（`p43` の複製、API を直接）:

| `known` | 1 頁 | `next_cursor` | 2 頁 | 1 頁と 2 頁の重複 | 1+2 頁で届かない語 | 2 頁の先頭の `uses` |
| --- | --- | --- | --- | --- | --- | --- |
| `all` | 200 語 / total 630 | `bare_legs` | 200 語 / total **593** | **183 語** | **413 / 630** | 38, 33, 32（1 頁の末尾は 2, 2, 2） |
| `1` | 200 語 / total 576 | `buttoned_cuffs` | 200 語 / total **465** | **147 語** | **323 / 576** | 33, 32, 28 |

- 原因: `WHERE t.name > ?`（名前のキーセット）を `ORDER BY uses DESC, t.name` の一覧に当てている。2 頁は「名前が `bare_legs` より後の語を使用数順に 200 語」になるので、1 頁と重なり、`total` も `name > cursor` の数になる。
- 画面への影響: 「次の 200 語を読む」で **同じ語が二重に並び**、本当に続きの語には届かない。C-2 の直し自体は正しく、**API の欠陥がそこで露わになった**。
- 直し方（どちらか）: (a) **キーセットを並びと揃える**（`(uses, name)` の組を cursor にし、`WHERE (uses < ?) OR (uses = ? AND name > ?)`。`uses` は副問合せなので `WITH` でまとめる）。(b) `cursor` を**オフセット**にする（`?offset=200`。語は数百〜1 万なので足りる。`GET /api/assets` と同じ流儀）。**(b) を推奨**（1 行で直り、`total` も変わらない）。
- テスト: 「1 頁と 2 頁に重複が無く、2 頁を合わせると `limit=1000` の一覧と同じ集合」を `tests/test_tags.py` に。

## C. 中程度

### C-1. 「行の高さが揃う」検査は長い語名の折り返しでも NG になる（`tools/gui_layout.mjs` の `MEASURE_ASSET`）
- 画像 A: `she_is_holding_a_syringe_in_one_hand`（PNG の自然文の断片。`語彙外`）が `.en` で 2 行になり、行の高さ 69 px（他は 49 px）。`script` の語釈の行は `.ja` の折り返しで 91 px（これは除外された）。
- 直し方: `.en` の折り返しも除く（`.en` の高さが 1 行分を超える行を除外）か、**「折り返していない行の高さが揃う」**と定義して `.en` と `.ja` の両方を見る。語彙外の長い断片は実データに普通にある（P4 の点検 B-4）ので、実データの複製で ok になる形にする。

## D. 確かめた結果、問題なし（1 行ずつ）

- `items` の `tag_id` は契約（`schemas/review-export.schema.json` の `Tag`）に足していない（`_tag_docs` は別の関数）。`review.json` は変わらない。
- 取り付け時の `fetch` は `GET /api/tags?known=all&limit=1000` が残っている（名前→id の地図は `tag_id` が入った今は要らない。消してよい）。
- `#/tags` の 3 経路の知らせ（保存・1 語・20 語）が出たまま。
- `#/jobs` の 13 件が 3 窓で横に溢れない。
- バーは起動直後は隠れ（古い完了で鳴らない）、短いジョブでも 1 周期以内に知らせる。`<audio>` は無い。

## E. 設計とのずれ

- `docs/p4-design.md` §3.6「`GET /api/tags?q=` 側で `LIKE 'q%'`」と「件数の多い順」に、**`cursor` の意味**が書かれていない。B-1 の直しに合わせて「`cursor` はオフセット」か「`(uses, name)` のキーセット」を書く。
- `frontend-design.md` §4.13 の「次の 200 語を読む」の記述を確認（12:10 版に「足す。置き換えない」）。問題なし。

## F. テストで守れないもの

| 観点 | 判定 | 直し方 |
| --- | --- | --- |
| 頁送り（B-1） | **守れない**（`test_the_tag_list_defaults_to_the_vocabulary` は 1 頁だけ） | 2 頁の重複ゼロと合計の一致を固定する |
| 行の高さの検査（C-1） | 検査の作りが実データで NG になる | `.en` の折り返しも除く |
| A-1 / A-2 / B-1 / B-2 / C-3 / C-5 | 落ちる形（`gui_smoke` +7、pytest +1） | — |

## G. 依頼者への質問（推奨つき）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | `GET /api/tags` の `cursor`（B-1） | (a) **オフセットにする**（`?offset=200`、`next_offset` を返す）／(b) `(uses, name)` のキーセット | **(a)**。語は多くて 1 万で、`GET /api/assets` もオフセット。画面は `next_cursor` を `offset` に読み替えるだけ |
| G-2 | 取り付け時の `GET /api/tags?known=all&limit=1000` | (a) **消す**（`tag_id` が `items` に入った）／(b) 残す | **(a)**。1 回分の往復と 1,000 語の上限が消える |
| G-3 | P4 を閉じる判断 | (a) **B-1 を直してから閉じる**／(b) 閉じて B-1 は次の段へ | **(a)**。「次の 200 語を読む」は押せば重複が見える状態なので、出荷の形ではない |

## H. 確かめられなかったこと

- `queued` の行の実物（即 `running` になるため）。コードと `gui_smoke` で確認。
- 「終わりました」が 60 秒で消えること（前回と同じ）。
- 後始末: サーバ 8791 停止。`.tmp-audit-redo/p43/`（複製 `srv/`、`page_re_*.js`、`shot-re-*.png`）を残した。`.data/` の mtime は 10-15。`src/` `apps/` `tools/` の最新は 12:08（実装者）。

### 実行したコマンドと結果（主なもの）

```
uv run --no-sync pytest -q                                   → 283 passed
node tools/gui_smoke.mjs                                     → 129 ok
node cdp.mjs … page_re_asset.js    → tgTop 575 / 見える / items に tag_id
node cdp.mjs … page_re_tags.js     → 次の 200 語 200→400（重複 183）、詳細の訳す tag_ids [343] 200、知らせ 3 種が 2.5 秒後も残る
node cdp.mjs … page_re_jobs.js     → 失敗の理由＋もう一度＋counts、完了の 1 枚 0.4 秒が不変、もう一度で新しい行
node cdp.mjs … page_re_heights.js  → 起動直後のバーは隠れ、2 枚のジョブで 2.2 秒後に終わりました、行の高さの差は長い語名の折り返し
GET /api/tags?…&cursor=            → 1 頁と 2 頁の重複 183 / 147、届かない語 413 / 323
node tools/gui_layout.mjs（7 回）  → タグ一覧・ジョブ・比較・要求・まとまり・注記 B ok、注記 A NG（差 20px、.en の折り返し）
```
