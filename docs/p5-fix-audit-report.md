# 9 件の修正の再監査報告（実行込み）

- 監査した版: 2026-10-16 の作業ツリー（git 管理外）。今回の修正で変わったファイルと更新時刻: `src/image_reviewer/{api/export.py 01:56, export.py 01:56, compare.py 01:57, review.py 01:58}`、`apps/gui/{styles.css 02:01, compare.js 02:04}`、`tests/{test_review.py 01:59, test_export.py 02:01, test_compare.py 02:08}`、`tools/gui_smoke.mjs 02:06`、`docs/{frontend-design.md 02:12, comparison.md / design.md / p5-design.md 02:15}`、`README.md 02:14`。
- **実行できたかどうか: 全部実行できた**（コマンド約 20。ソースは編集せず、実データは `mode=ro`、サーバは `IMAGE_REVIEWER_DATA=.tmp-audit-redo\data-p52` で 8791、一時物は `.tmp-audit-redo/`）:
  - `uv run pytest -q` ×2 → **175 passed, 1 warning**（8.2 s）。`tests/.tmp` **0 → 0 → 0**。warning は前回と同じ `starlette.testclient` の非推奨（アプリ外）。
  - `node tools/gui_smoke.mjs` → **51 ok / 0 NG**（前回 47）。
  - HTTP（`fix_api.py` / `fix_api2.py`）: #7 の mtime、#8 の再送 10 本、#4 の改名（参照する 2 まとまり・参照しないまとまり・過去の判断だけの参照・`position` / `active`）、#1 のロック 9.5 秒、#9 の鍵。
  - in-process（`data-fix1` のコピー）: #1 の起動時の掃除（残骸 1 つ＋**別プロセスが開いている**模擬 1 つ＋本体 1 つ）、300 ファイルでの費用。
  - ブラウザ（Chrome headless + CDP、`page_fix.js` / `page_width.js`）: **1400×900 / 1200×800 / 1920×1080** の 3 つで 2〜8 枚の初回描画、`resize` / `r` / `m` / `b` / `d` の後、`num` セルの幅と書体、入力順・seed 順・似ている順の `1`〜`8` キーと語の差分の番号、同じ seed の文言と「強制して出す」。画面写真 `.tmp-audit-redo/shot-fix-{1400,1200,1920}.png`。
  - 新規テスト 6 件と `gui_smoke.mjs` の変更箇所は読んで「何を守っているか」を判定した（§F）。
- 総合判定: **使える。** 9 件のうち **7 件は直っている。2 件（#3・#4）は直っているが別の問題が残る。直っていないものは無い。** #3（初回描画）は 1400×900 では直っているが、**タイルの幅が枠ではなく見出しで決まる**という別の原因が残り、1200×800 では 8 枚が今も 3 行に溢れる（§B-1）。#4 は参照するまとまりのファイルは直るが、全ファイルに載るマスタ `reason_codes[]` は参照しないファイルで旧名のまま（§C-1）。回帰（新しく壊した所）は**見つからなかった**。

---

## A. 直っていない（必ず直す）

**無し。**

---

## B. 直っているが別の問題が残る（重大）

| # | 場所 | 問題 | 利用者の側で何が起きるか | 実行したコマンド / 再現手順 | 提案 |
| --- | --- | --- | --- | --- | --- |
| **B1**（#3） | `apps/gui/styles.css:213`（`.cmp-tile { display: flex; flex-direction: column }`）、`:246-249`（`.cmp-cap { max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }`）、`apps/gui/compare.js:230-243`（`stageHeight`: `byWidth` は**枠の幅＝高さ×縦横比**を前提に 1 行に入る枚数を見積もる）、`:283`（`width` の計算）と `renderStage()` の `tile.innerHTML`（`style="width:…"` を **`.cmp-frame` にだけ**付け、`.cmp-tile` には付けない） | **タイルの幅は枠ではなく見出しの幅で決まっている。** `.cmp-cap` の `max-width: 100%` は、親（タイル）の幅が中身で決まる列 flex の中では上限にならず、`nowrap` の見出し（モデル名・seed・steps・cfg）がそのままタイルを 309〜434 px に広げる。枠は 162 px なのにタイルは 2 倍以上。`stageHeight` の幅の見積もり（`byWidth`）は枠の幅で数えるので当たらず、**1400×900 で 4×2 になるのは見出しの幅がたまたま 4 枚ぶん（1363 px）に収まるから** | **1200×800 では 7〜8 枚が今も 3 行**（1 行 3 枚、舞台の外に 1〜2 枚、スクロール）。**1400×900 でも seed 順にすると 3 行・外に 1 枚**（推定: 434 px の見出しを持つ枚の位置が変わり、その行の 4 枚目が 1400 px に入らない。並び替え後の各行の幅までは測っていない）。1920×1080 は 2 行に収まる（1 行 5〜6 枚になり、§2.1 の「4×2」でもない） | **再現した（ブラウザ）。** `page_width.js`: 1400×900・8 枚で各タイル `(tile, frame, cap.scrollWidth)` = (434, 162, 434), (310, 162, 310), …（**タイル幅＝見出しの scrollWidth**）。`page_fix.js`: 1200×800 で 7 枚 `rows=3 perRow=3 outside=1`、8 枚 `rows=3 perRow=3 outside=2`、`resize` / `r` / `m` / `b` / `d` の後も同じ。1400×900 では 2〜8 枚すべて `outside=0` だが `r`（seed 順）の後に `rows=3 outside=1` | `renderStage()` でタイルにも `tile.style.width = width + 'px'` を付ける（見出しは `max-width: 100%` のまま省略記号で切れる）。これで `byWidth` の前提（タイル幅＝枠幅）が成り立つ。あわせて `comparison.md` §2.1 の追記（「実測: 8 枚で rows=2 / perRow=4」）に **1400×900 の値である**と書き足す。`gui_smoke.mjs` では見えないので、`page_fix.js` 相当を `tools/` に置いて 3 つの窓で回す |

---

## C. 中程度

| # | 場所 | 問題 | 利用者の側で何が起きるか | 実行したコマンド / 再現手順 | 提案 |
| --- | --- | --- | --- | --- | --- |
| **C1**（#4） | `src/image_reviewer/export.py:355`（`build()` が**すべての**文書に `reason_codes: [全理由の id / label / applies_to]` を載せる）、`review.py:424-437`（`_groups_using_reason` は**参照する**まとまりだけを引く） | 改名で直るのは参照するまとまりのファイルだけ。**参照しないまとまりのファイルの `reason_codes[]` は旧名のまま**、`review.json` も次の `POST` まで旧名（#7 で GET が書かなくなったので、手動の POST だけが更新の契機）。契約の `reason_codes` はマスタの写しなので、ファイルごとにマスタの内容が食い違う | 他ツールが「ファイルの `reason_codes[]` から `label` を引く」作りだと、どのファイルを読んだかで同じ id の名前が違う | **再現した（HTTP）。** 理由 R を使う gA・gB と使わない g の 3 つを書き出し → `PATCH label` → 3 秒後: gA の `groups[].reason_label` / `items[].reason_label` / `assets[].reason_label`、gB の `assets[].reason_label` は**新名**。**g の `reason_codes[]` の label は旧名のまま**（`generated_at` 不変＝書き直していない）。誰も使わない理由 R2 を改名 → `review.json` の `reason_codes[]` に R2 は無い（POST 時点のまま） | (a) 改名は**全まとまり**を `_touch_groups` する（まとまり数ぶんの書き出し。263 枚規模なら数十ファイル）か、(b) 契約の `reason_codes[]` を「このファイルで参照する理由だけ」に絞る（契約の `description` を直す）か、(c) `reason_codes[]` は参考情報と割り切り「`reason_label` が正」と契約に書く。推奨は (b)。改名のたびに全ファイルを書き直すより、ファイルが自分の分だけ持つ方が決定性（§3.4）にも合う |
| **C2**（#3） | `apps/gui/compare.js:50`（`state.order`）、`:115-120`（`showCompare()` の `sameIds` 分岐は `views` と `selected` だけを戻し、`order` を戻さない） | 並び順が**比較を開き直しても残る**。seed 順のまま一覧に戻って別の 8 枚を開くと、最初から seed 順で描かれる（ボタンの表示は「並び: seed 順」なので矛盾はしないが、`comparison.md` §2.1 の「既定は入力順」と違う） | 「1 番が基準」と思って `1` を押すと、距離順の 1 番＝基準なのでたまたま合うが、`2` 以降は入力順と違う | **実行で気づいた（ブラウザ）。** `page_fix.js` は 8 枚の操作で `r` を 1 回押して seed 順にした後、`open(all)` で同じ 8 枚を開き直し、そこから `r` を 2 回押した結果が「並び: 入力順」になった（seed 順 → 似ている順 → 入力順）。開き直しで入力順に戻っていれば「似ている順」で止まるはず | `showCompare()` で顔ぶれが変わったら `state.order = 'input'` に戻す（`sameIds` の分岐がすでにある） |

**確かめた結果、問題なし（実行）**:

- **#1**: ファイルを掴んだまま判断 → 9.5 秒で `*.tmp` **0 個**（前回は +4）、他のまとまりは書かれ、解除後の次のタイマーで書き直し（`kept`）、サーバのログに `WinError` の WARNING **4 行**（再試行の回数）。起動時の掃除は `ExportService(flush_on_start=True)` の経路で走り（`export.py:161 → 226-233 → 240`）、残骸 1 つを消し、**別プロセスが開いている**一時ファイルは `WinError 32` で消せず WARNING 1 行（本体 `01REAL.json` は無傷）、閉じた後の次の `flush_dirty()` で消える。`app.py:55` の `exporter.flush_dirty()` も同じ関数を通る。300 ファイルのフォルダで **0.43 ms**（`flush_dirty()` は起動時だけなので費用は無視できる）。失敗した ID が `_pending` に戻る経路は `export.py:196-219` のまま。
- **#2**: `num` が付く行は **`steps` / `cfg` / `denoise` / `width` / `height` / `seed`** の 6 行だけ（残り 14 行には無い）。computed `font-family` は `"BIZ UDGothic", "Yu Gothic UI", Consolas, monospace`、`font-size` は文字セルと同じ 12 px。「1111111111」と「9999999999」の幅が **60.0 / 60.0 px**（同じ表の文字セルは 75.6 / 91.2）。`seed` の値 `0` / `0` / `1` のセルに `class="cell changed num"`。「分からない」セルに `num` が付く経路（`compare.js:371-384`）は、数値の 6 行には `unknown` が無い（`unknown` は `final_prompt` だけ。`compare.py:176`）ので実際には到達しない。読みにくさ: 等幅版は字面がやや細いが同じ一族で、12 px のまま。
- **#5**（`page_key.js`。**seed 順と似ている順で**測った。入力順はサーバ順と一致するので証拠にならない）: **seed 順**（並びが入力順から変わったことを確認）で `2` → 表示 2 番のタイル（番号「2」）、`5` → 表示 5 番。**似ている順**（距離 0, 22, 22, 24, 30, 30, 30, 34）で `3` → 表示 3 番（番号「3」。前回は番号 4 が選ばれていた）、`7` → 表示 7 番で「基準 1 番 ⇔ **7 番**」（`compare.js:610` は `order.indexOf`）。表の列番号は両方の順で 1〜8、**語の差分の「N」行の先頭語が表示 N 列目の `final_prompt` セルの先頭と一致**（seed 順・似ている順とも 7 行すべて）。値の添字（`serverIndex`、`:375-376`）はサーバ順のままで、取り違えは見つからなかった。人に見せる番号を出す箇所は `:159, 301, 361, 445, 454, 467, 493, 610` の 8 か所で、すべて表示順（`orderedIds()` / `displayIndex()` / `index` の列挙）。残る違和感は D5（行の並び）。
- **指示書 §2 の `_notify` の形**: `review.py:421` の `{"affected_group_ids": touched}` は `create_group`（`:288` の `{"affected_group_ids": [group_id]}`）と同じ形で、`_notify()`（`:855-857`）は `affected_group_ids` だけを読む。揃っている。
- **#6**: 同じ seed の組: `差分: 同じ seed の組です（合うかは出してみるまで分かりません）`、「強制して出す」は `display: block`、クリック → `差分を出せません: 位置が合いません（…峰の比 6.1 < 8.0）`、強制の口は見えたまま。合う組（距離 0）: 絵が出ると強制の口は **`none`**、閉じると **`block`** に戻る。`comparison.md` §2.3 の「同じ seed は手がかり」と一致。押してはいけない場面: 見つからなかった（1 枚しか選んでいないときは `heatLine()` の `!rule` で隠れる）。代償は、合わない組で強制を押すと**同じ復号（1024² で 38 ms）をもう一度走らせて同じ理由を見る**こと。害は小さい。
- **#7**: `GET ?scope=all` で `export/review.json` の mtime **不変**、`POST` で **更新**、GET と POST の文書は `generated_at` を除いて**同一**、`scope=group:` / `asset:` は GET / POST とも何も書かない（まとまりのファイルの mtime も不変）。GET が書くことに依存する呼び出し元: `apps/gui` / `tools/` / `tests/` に**無し**。
- **#8**: 同じ本文の再送: 直後 **200**（`superseded` 無し、同じ `decision_id`）。別の判断（reject）を入れた後の再送: **200 + `superseded: true`**、応答の `asset.review_state` は **`rejected`**（巻き戻らない）、`GET /api/assets` も `rejected`、台帳 **2 行**のまま。同じ token で**中身が違う** → **409 `client_token_conflict`**、**対象が違う** → 409。まとまり: `decide` → 再送 200 → `reopen` → 再送 **200 + `superseded: true`**、`group.state` は **`open`** のまま、台帳 3 行、中身違いは 409。設計 §3.1 / §3.2（`p5-design.md:236, 263`）と一致。`superseded` は再送のときだけ付き、通常の応答の形は変わらない。
- **#9**: `diff.keys` に `textgen_system_prompt`（16 番目）と `en_source`（17 番目）が入り、23 鍵。置き場は **`provenance`**（`prompts` には無い）。実データで持つのは **1 枚だけ**（676 文字）なので、その枚＋他 1 枚で **`only_in_some`**（`cells: ['same', 'missing']`）、基準を逆にしても `only_in_some`、2 枚とも持たなければ `same` に畳まれる。`/api/groups/{id}/compare` でも出る。文書の大きさは 676 文字 × 2 回（`items[].provenance` と `values`）＝ **+1.3 KB**（18.7 KB → 2 枚の文書）。`prompt_diff` は `final_prompt` のまま。

---

## D. 軽微

| # | 場所 | 問題 | 提案 |
| --- | --- | --- | --- |
| D1（#7） | `README.md:161`（「`POST /api/export/review.json`（と `scope=all` の GET）だけ」） | GET は書かなくなったので**古い**。`p5-design.md:301` は直っている | 「（と …の GET）」を削る |
| D2（#9） | `compare.py:163`（`textgen_system_prompt` の `kind` が `prompt`） | 文章の指示文をカンマ・文末で語に割り、大小文字と `_` / 空白を同一視して比べる（`normalize_text`）。「Translate to English.」と「translate to english.」は `same`。LLM への指示として大小文字が意味を持つ場合は差が消える。実データ 1 枚では影響なし | `kind` を `text`（そのまま比べる）にするか、docstring に「大小文字は無視」と書く |
| D3（#2） | `styles.css:347-350`（`td.cell.num` に `text-align` 無し。左寄せ） | 桁は揃うが右寄せではないので、同じ列の `8` と `30` は左端で揃う。桁数が違う値の大小は読み取りにくい | `text-align: right`（`.detail .num` と同じ） |
| D5（#5） | `apps/gui/compare.js:441-454`（`promptBlock` は `Object.keys(detail.per_asset)` ＝**サーバ順**で行を並べ、番号だけ `displayIndex()` にしている）、`:485-493`（`jaBlock` も同じ） | 番号は正しいが、**行の並びがサーバ順のまま**。seed 順では語の差分の行が「6, 3, 1, 7, 4, 5, 2」の順に、似ている順では「2, 3, 5, 6, 4, 7, 8」の順に並ぶ（**実行で確認**。`page_key.js`）。表の列は 1〜8 の順なので、表と差分を上下に見比べるときに目が飛ぶ | `others` を `displayIndex` で `sort` する（1 行） |
| D4（#1） | `export.py:240-258`（`clean_stale_tmp` は `*.tmp` を**無条件に**消す） | 別プロセス（`cli scan` の `create_app()` 経路。`p5-audit-redo.md` C3）が**今まさに書いている**一時ファイルも対象。Windows では開いている間は消せない（実測: WinError 32 で WARNING）が、`write_text` が閉じてから `os.replace` までの数 µs は消せる。消された側は `FileNotFoundError` → 再試行に回る（内容は失われない。指示書の想定どおり） | 自分の pid（`os.getpid()`）を含まない名前は、更新時刻が 1 分以内なら消さない |

---

## E. 設計文書とのずれ

| 項目 | 状態 | 場所・根拠 |
| --- | --- | --- |
| `comparison.md` §2.1 の追記「実測: 8 枚で `rows=2 / perRow=4 / outside=0`。`resize` の後も同じ」 | **1400×900 だけの値**。1200×800 では成り立たない（B1）。窓の大きさを書くべき | `docs/comparison.md:49-53` |
| `comparison.md` §2.3「同じ seed は手がかり」 | **一致**（文言・強制の口。#6） | `compare.js:548, 555` |
| `p5-design.md` §3.1 / §3.2 の `superseded` | **一致**（#8） | `:236, 263` |
| `p5-design.md:301`「書くのは POST の scope=all だけ」 | **一致**（#7） | — |
| `README.md:161` | **古い**（D1） | — |
| `frontend-design.md:110`「数値のセルだけ BIZ UDGothic」 | **一致**（#2） | `styles.css:347` |
| `p5-design.md:96` 追記（監査 G4 の鍵） | **一致**（#9） | `compare.py:163-164` |
| 契約 `schemas/review-export.schema.json` の `reason_codes` | **今回触っていない**。C1 の (b) を採るなら `description` を直す | — |

---

## F. テストが守っていないもの

新規 6 件と `gui_smoke.mjs` の変更箇所を読んで判定した（「実装を戻して落ちるか」は読んだだけ）。

| # | テスト | 何を主張しているか | 実際に守っているか | 直し方 |
| --- | --- | --- | --- | --- |
| **F1** | `tests/test_export.py:343` `test_a_failed_replace_does_not_leave_a_tmp_file` | `os.replace` が落ちても `.tmp` を残さず、`_pending` に戻し、解除後に書ける | **守っている。** `os.replace` を `monkeypatch` で落とし、`glob("*.tmp") == []` と `pending_ids()` を見る。`_atomic_write` の `unlink` を消せば落ちる |
| **F2** | `tests/test_export.py:366` `test_stale_tmp_files_are_cleaned_at_startup` | 「起動時に残骸を片づける」 | **半分。** `clean_stale_tmp()` を**直接**呼んでいる。`flush_dirty()` の先頭の呼び出し（`export.py:233`）を消しても**緑のまま**＝名前の「at startup」を守っていない | `ExportService(store, flush_on_start=True)` を作り直して消えることを見る（今回私が in-process で実行した形） |
| **F3** | `tests/test_export.py:384` `test_renaming_a_reason_code_touches_the_groups_that_use_it` | 改名で印が付き、`flush()` で新名になる | **守っている**（枚の現在値の参照）。まとまりの結論の理由（`review_group.reason_code_id`）の参照は見ていないが、同じ SQL の UNION なので実害は小さい。C1（参照しないファイルの `reason_codes[]`）は**誰も守っていない**（主張自体が無い） | まとまりの理由の参照を 1 行足す。C1 の方針を決めてからその主張を足す |
| **F4** | `tests/test_review.py:216, 243` | 再送 200 + `superseded`、行が増えない、中身違いは 409 | **守っている。** `_replay_asset` の `superseded` を常に `False` にすれば落ち、409 を消しても落ちる |
| **F5** | `tests/test_compare.py:293` `test_the_g4_keys_are_diffed` | 2 鍵が `keys` と `changed` に入り、値が出る | **守っている。** 置き場（`provenance`）は `row_of` 経由なので見ていないが、`asset_item()` の置き場を変えても `_raw_of` が引けなくなって落ちる |
| **F6** | `tests/test_export.py:786-800`（GET が書かない） | GET は書かず POST が書く、文書は同じ | **守っている。** `write=` を GET で `True` に戻せば落ちる |
| **F7** | `tools/gui_smoke.mjs:303-307`（`num`） | seed のセルに `num`、数値でない行には無い | **半分。** 後半は `diffHtml.split('row incomplete')[1]` ＝ `final_prompt` の行**以降**だけを見るので、それより前の文字行（`model` など）に `num` が付いても通る。`class="cell [a-z]* num"` は `cell unknown num` も `[a-z]*` で拾うので意図は合う | 行ごとに `tr.row` を割って、`kind` が `num` でも `seed` でもない行に `num` が無いことを見る |
| **F8** | `tools/gui_smoke.mjs:354-365`（強制の口を常に出す）、`:357-362`（同じ seed の文言） | 設計変更（#6）に合わせた**反転** | **緩めではない。** 元の主張「規則の外で、キーを押さずに強制の口が見える」は `:369-382` に**残っている**。新しい主張（出せる組でも見える、絵が出たら隠れる）は前半だけで、「絵が出たら隠れる」は smoke に無い（ブラウザで確認した） | 「絵が出たら `cmp-heatforce.hidden === true`」を 1 行足す |

**新しく守るべきもの**: B1（タイルの幅＝枠の幅。3 つの窓で `outside=0`）、C2（開き直したら入力順）。どちらも `gui_smoke.mjs` では見えない（CSS とレイアウトが無い）。

---

## G. 依頼者への質問

| # | 論点 | 私の推奨 |
| --- | --- | --- |
| G1 | C1 の方針: 改名で全まとまりを書き直す (a) / `reason_codes[]` を参照分だけにする (b) / `reason_label` が正と契約に書く (c) | (b)。ファイルが自分の分だけを持てば、改名の影響範囲も「参照するまとまり」で閉じる |
| G2 | B1 の直し方: タイルに幅を付ける（枠と同じ）か、見出しを `position: absolute` で枠の下に重ねるか | 前者。1 行で済み、`byWidth` の前提がそのまま成り立つ |
| G3 | #9 の `textgen_system_prompt` を `prompt` のままにするか `text` にするか（D2） | `text`。指示文は語の集合ではなく文 |

---

## H. 今回も確かめられなかったこと（＋できない理由）

| 項目 | 状態 | 理由 |
| --- | --- | --- |
| 「実装を戻すと新規テストが落ちるか」 | **読んだだけ**（§F） | ソースを編集しない約束 |
| 別プロセスが**書いている最中**の一時ファイルを `clean_stale_tmp()` が消す瞬間（D4） | **部分的**（開いている間は消せないことは実行で確認。閉じてから `os.replace` までの隙は作れなかった） | µs の競合を外から再現する手段が無い |
| 1200×800 より小さい窓・DPI 150% での見え方 | **未確認** | B1 が直ってから見る方がよい |

---

## R. 9 件それぞれの判定

| # | 判定 | 根拠（実行したコマンド） |
| --- | --- | --- |
| **1** `.tmp` | **直っている** | `fix_api2.py`: ロック 9.5 秒で `.tmp` 0、B は書かれ、解除後に A が再試行、WARNING 4 行。in-process: `flush_on_start` 経路で残骸 1 つを削除、開いている 1 つは WARNING で残す、本体は無傷、300 ファイルで 0.43 ms |
| **2** `num` | **直っている** | ブラウザ: 6 行だけに `num`、`BIZ UDGothic`、60.0 / 60.0 px（文字セル 75.6 / 91.2）。軽微: 左寄せ（D3） |
| **3** 初回描画 | **直っているが別の問題が残る** | ブラウザ: 1400×900 は 2〜8 枚すべて `outside=0`（8 枚 4×2）。**1200×800 は 7〜8 枚が 3 行・外に 1〜2 枚**、1400×900 でも seed 順で 3 行。原因はタイル幅＝見出し幅（B1） |
| **4** 改名 | **直っているが別の問題が残る** | `fix_api.py`: 参照する gA（結論・枚）と gB（枚の現在値）は 3 秒で新名、`position` / `active` は `changed_at` 不変、過去の判断だけの参照は不変、応答の形は不変。**参照しないファイルの `reason_codes[]` は旧名のまま**（C1） |
| **5** 番号 | **直っている** | ブラウザ（`page_key.js`、seed 順と似ている順）: seed 順で `2` / `5`、似ている順で `3` / `7` が表示の番号のタイルを選ぶ、語の差分の N 行目と表示 N 列目の一致（両方の順で 7 行すべて）、ヒートマップの「⇔ 7 番」。`+ 1` の 8 か所すべて表示順。軽微: 差分の行の並びがサーバ順（D5） |
| **6** 文言・強制 | **直っている** | ブラウザ: 文言、常時表示、絵が出たら隠れる、閉じると戻る、合わない組の強制は理由を返す。代償は 38 ms の二重の復号 |
| **7** GET | **直っている** | `fix_api.py`: GET で mtime 不変、POST で更新、文書同一、group / asset 不変。依存する呼び出し元なし。`README.md:161` が古い（D1） |
| **8** 再送 | **直っている** | `fix_api.py`: 枚とまとまりで 200 / `superseded` / 巻き戻らない / 行数不変 / 中身違い・対象違い 409 |
| **9** 鍵 | **直っている** | `fix_api2.py`: `keys` 16・17 番目、`provenance`、`only_in_some`、まとまりの口でも出る、+1.3 KB。軽微: `kind` が `prompt`（D2） |

---

## 最も重大な 3 件

### 1. タイルの幅は枠ではなく見出しで決まっていて、1200×800 では 8 枚が今も 3 行に溢れる（B1。**新しく見つけた**）

#3 の修正（描画の順と見出しの高さ）は正しいが、1400×900 で 4×2 になったのは見出しの幅（309〜434 px）がたまたま 4 枚ぶんに収まるからで、枠（162 px）とは関係が無い。`stageHeight` の幅の見積もりは枠の幅で数えるので、窓が狭いと当たらず、同じ窓でも並び順を変えると 3 行になる。タイルに枠と同じ幅を付ける 1 行で、見積もりの前提が成り立つ。

### 2. 改名が届くのは参照するまとまりのファイルだけで、全ファイルに載るマスタ `reason_codes[]` は食い違う（C1。**新しく見つけた**）

#4 の修正は「書き出し時点のマスタ」を参照する行には届いた。しかし `build()` は毎回すべての理由をマスタとして各ファイルに書くので、参照しないまとまりのファイルと `review.json` は改名前の名前を持ち続ける。どのファイルを読んだかで同じ id の名前が違う。マスタを参照分に絞るか、改名で全部を書き直すか、契約で「`reason_label` が正」と言い切るかを決める必要がある。

### 3. 起動時の掃除のテストが、起動の経路を通っていない（F2）

`test_stale_tmp_files_are_cleaned_at_startup` は `clean_stale_tmp()` を直接呼ぶので、`flush_dirty()` の先頭の 1 行を消しても緑のまま。今回は私が `ExportService(flush_on_start=True)` の経路を実行して確かめたが、テストにはその主張が無い。名前が約束していることをテストに書き直すだけで済む。
