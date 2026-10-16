# P4-2（日本語の語釈）監査報告 — 実行込み

- 日付: 2026-10-16（11:15〜11:50）。監査者: Fable（Claude Code）
- 指示書: `docs/p4-audit-brief-p4-2.md`（10:55）。実装の記録: `docs/p4-2-implementation.md`（11:09）
- 対象: `src/image_reviewer/gloss.py`（11:00、485 行）/ `api/tags.py`（11:01）/ `api/__init__.py`（11:00）/ `app.py`（11:01）/ `tests/test_gloss.py`（11:03、18 件）/ `tools/probe_p4.py`（11:10、`--gloss`）。設計: `docs/p4-design.md` §0.9 / §3.4 / §3.5 / §4.2 / §7 / §8.1
- 環境: 利用者のサーバ（8790）が `.venv` を握っているので **`uv run --no-sync` と `.venv\Scripts\python.exe`**。実データ `.data/` は `mode=ro` と **`backup()`** だけ（mtime は 10-15 のまま、`user_version=3`・判断 3 件）。複製 `.tmp-audit-redo/p42/srv`（起動で v5。IllustTagger で 3 枚にタグ付けして語を作った）をポート 8791 で。ComfyUI 0.39.2 には**訳とタグ付けだけ**投げた（`/free` で模型を 3 回降ろした。生成はしない）。一時物は `.tmp-audit-redo/p42/`（`p42_http.py` / `p42_http2.py` / `parse_edges` と各 `.out.txt`、`srv/`＝語釈 87 行入り）。`tools/probe_p4.py --gloss` は自分の置き場（`.tmp-audit-redo/p4/data`）を作って消す。ソースと既存の文書は編集していない。監査のサーバは停止済み。

---

## 判定: **合格。P4-3 へ進んでよい。**

線 4・5・6 を**本物の `TextGenerate`（`qwen3vl_8b_int8_convrot`）で自分の手で通した**。番号での対応・保存の条件・取引の外で待つこと・`GET` が書かないこと・20 語の単位と 422 / 409 / `skipped`・契約・回帰（pytest 278 / gui_smoke 91 / gui_layout 4 画面）はすべて実行で裏が取れた。
直すべき点は 2 つ（B-1 の 500 と C-1 の設定の読み直し）で、どちらも語釈の正しさは壊さない。設計の矛盾 1 件（E-1）は文面の整理。

**最も重大な 3 件**
1. **冷えた模型の初回に 500**（4 回中 1 回）。ComfyUI が 8.7 GB の模型を読む間 HTTP に応じず、`/history` の接続が Windows の時間切れ（`WinError 10060`）で落ち、**`_wait` が通信の例外を受けずに 500**になる（設計は 502 / 504）。行は 1 つも書かれず、再試行は通る（§B-1）。
2. **`gloss.*` の設定（`llm` / `url` / `system_prompt` / `max_length` / `timeout`）はプロセスで 1 回しか読まれない**（`batch` だけ毎回読む）。設定を変えても再起動まで効かない。`gloss.llm` を無い名前にしても次の訳が古い模型で通った（§C-1）。
3. **設計 §4.2 / §3.5 が「人が直す口は `source='manual'` も立てる」と「自動の訳を直したら `textgenerate` のまま」の両方を言っている**。実装は後者。どちらでも画面は `edited` だけを見るので壊れないが、**設計の文面を 1 つにする**（§E-1）。

---

## A. 直っていない／設計の約束が成り立たない（必ず直す）

無し。

## B. 重大

### B-1. 模型の読み込み中の通信エラーが 500 になる（`gloss.py:214-230` `_wait`、`tagger.py:380` `_http_json`）
- 観測: 複製で最初に `POST /api/tags/gloss`（20 語）を打ったとき（この ComfyUI セッションで語釈の模型を初めて読む回）、**`500 Internal Server Error`**。`server.log`:
  `gloss.py:400 translate → :184 translate → :218 _wait → tagger.py:380 _http_json → urllib.error.URLError: <urlopen error [WinError 10060] 接続済みの呼び出し先が一定の時間を過ぎても正しく応答しなかった…>`。
  `tag_gloss` は 0 行のまま（部分保存なし）。直後の 5 語は 200・1.6 s。
- 再現: `POST /free {"unload_models": true}` で模型を降ろしてから訳す、を **3 回**（20 語 10.6 s / 5 語 6.6 s / 5 語 6.9 s）→ **全部 200**。つまり**4 回中 1 回**。最初の 1 回は直前に IllustTagger のジョブが動き、空き RAM が約 10 GB で 8.7 GB の int8 を読む条件だった。
- 原因: `_wait` は ComfyUI の `status_str == "error"` だけを見ていて、**`_http_json` が投げる `URLError` / `TimeoutError` を受けない**。ComfyUI のイベントループが読み込みで長く塞がると、`/history` の接続が OS の時間切れで落ちる。
- 直し方: `_wait` のポーリングで `URLError` / `socket.timeout` / `TimeoutError` を**受けて待ち直す**（`self.timeout` まで）。期限を越えたら **504**。`_submit` の失敗は **502**。`tagger.py` の `_wait` も同じ形なので揃える（タグ付けの `job` はスレッドの `except` で `failed` になるが、口は 500 を返さないように）。

## C. 中程度

### C-1. `GlossService.engine()` が設定を 1 回しか読まない（`gloss.py:354-359`）
- プロセス内（`parse_edges.out.txt`）: `engine_factory` が読んだ設定は **1 回**。`gloss.llm` と `gloss.url` を変えた後の 2 回目も**古い値**（`qwen3vl…` / `:8188`）。`gloss.batch` だけは `translate` のたびに読む（`:395-396`）。
- HTTP（`p42_http2.out.txt`）: `gloss.llm = does-not-exist.safetensors` にした後の訳が **200**、`engine` は `qwen3vl_8b_int8_convrot.safetensors` のまま（読み直していれば `CLIPLoader` が 400 を返す）。**409 の検査は再起動しないと通らなかった**（再起動後は 409 `gloss_engine_unavailable`、`details.url = http://127.0.0.1:1`。2 回目も 409、`GET` は生きている、行は増えない）。
- 設計 §0.9 は `system_prompt` / `llm` を「**設定**」と呼んでいる。利用者が `#/settings`（P4-3 以降）で変えても効かないのは罠。直し方: `translate` のたびに `settings_of(con)` を読んで `self._factory(settings)` を作り直す（`GlossEngine` は軽い）か、設定の指紋が変わったら作り直す。

### C-2. 「日本語か」の判定は「ASCII だけではない」（`gloss.py:94-100`）
- `１. 長髪`（全角の番号）は通る（`\d` が全角に合う。良い）。しかし **`1. ……`** と **`1. 👁️ girl`** も「日本語」として保存される（`parse_edges.out.txt`）。P4 の点検 A-3 で模型が `👁️ = 視聴者を見つめる` を返した実例がある。設計 §0.9-3 の文面どおりだが、**記号だけ・絵文字＋英語**を落とす方が安全（ひらがな／カタカナ／漢字を 1 文字以上含む、など）。P4-3 で画面に出る前に。

### C-3. `POST /api/tags/gloss` はエージェントも押せる（GPU を使う）
- `agent` ヘッダで **200・`calls=1`**（模型が回る）。設計 §3.1 の呼ぶ側は「画面」で `human` の指定は無いので**設計どおり**。ただし語釈は R10 の要求とは別で、エージェントが大量に押せば GPU 時間を使う。許すなら §3.1 に「エージェントも可」と書く。制限するなら `require_human` を 1 行。

## D. 軽微

1. **線 4**（`p42_http.out.txt`）: 確かめた結果、問題なし。語釈 0 の画像で `GET …/tags` → `items 60 / glosses 0 / pending_gloss 60 / counts {wd14: 42, png: 19}`。`GET` 5 種 ×3 回で **`tag_gloss` 0 → 0、ComfyUI の `/history` 605 → 605**（模型を回していない）。20 語を `POST` → **200・`translated` 20・`calls` 1・`tag_gloss` 5 → 25・`/history` +1**。例: `syringe → 注射器`、`nurse_cap → 看護帽`、`brown_hair → ブラウンヘア`。`engine` は `qwen3vl_8b_int8_convrot.safetensors`、`source='textgenerate'`、`edited=0`。
2. **2 回目は回さない**: 同じ 20 語で `calls 0`・`skipped 20`（理由「既に語釈があります」）・**`/history` +0・`elapsed_ms 0`**。
3. **線 5**: 確かめた結果、問題なし。`POST /api/tags/{id}/gloss` は `agent` 403・空 422・201 字 422・無い id 404。`human` で 200 → `ja` が入り **`edited: true`**、`source` は `textgenerate` のまま、`engine` もそのまま（E-1）。`GET` が同じ値。`force=true` で訳し直し → **`calls 0`・`skipped`「人が直した語釈は上書きしません」・値はそのまま**。守る語＋普通の語を同時に → `calls 1`、普通の語だけ `translated`。語釈の無い語に人がゼロから書く → **`source='manual'`・`edited=true`・`engine=null`**。`GET …/tags` の `glosses[name].edited` が `true`。
4. **線 6**（`tools/probe_p4.py --gloss`、自分で回した。`probe-gloss.out.txt`）: 確かめた結果、問題なし。**18/18 が日本語**（線 1〜7 も同時に OK）、注入 4 種（番号の無い行・英語のまま・空・番号の重複）で**保存 2 / 保存せず 2、重複は 0**、`tag_gloss` 18 → 20 → 20。注入は in-process の偽の模型で（本物の模型に壊れた応答は出させられないので妥当）。
5. **番号での対応と保存の条件**（`parse_numbered`。`parse_edges.out.txt` と `tests/test_gloss.py`）: 確かめた結果、問題なし。`^(\d+)[.)]\s*(.+)$`、空行は読み飛ばし、`1.長髪`（空白なし）も通る、番号の重複は**3 回目も**捨てる、英語→日本語の順の重複も捨てる、`- 1. 長髪`（箇条書き）と `1: 長髪` は番号が取れず捨てる、CRLF も通る、語数より大きい番号は `mapping.get(index)` で無視。**部分適用**（20 語中 17 語）はテストと実機（20 語で `calls 2` = 1 語を 1 語ずつ）で確認。1 語ずつの成功条件は `again.get(1)`（番号が取れて日本語）。
6. **模型の呼び方**（`_graph`）: 確かめた結果、問題なし。`CLIPLoader(clip_name, type='qwen_image')` → `TextGenerate(max_length=512, sampling_mode='off', thinking=False, use_default_template=True, mtp='auto', system_prompt)` → **`PreviewAny`**。`1. 1girl` の形（`format_prompt`）。`system_prompt` は `DEFAULT_SYSTEM_PROMPT` を初期値に **`settings` の `gloss.system_prompt` で差し替え**（C-1 の読み直しの問題はある）。`_text` は `text` → `string` → … の順で探し、**ノード番号を見ない**。`/history` は 0.05 秒ごと。
7. **取引の外で待つ**: 確かめた結果、問題なし。**HTTP で**、20 語の `force=true` の訳（約 4 秒）の間に `GET /api/tags/gloss/pending` を 12 回 → 待ち **1〜27 ms**。P4-1 の B-1 の直しが HTTP でも確認できた最初の例。テスト `test_the_model_is_called_outside_the_transaction`（偽の模型 0.5 秒、`locked()` 0.25 秒以内）も落ちる形。
8. **20 語の単位・422 / 404**: 確かめた結果、問題なし。空 422 `{"tag_ids": "1 つ以上"}`、本文無し 422、21 語 422 `{"tag_ids": "20 語まで", "count": 21}`、`limit=5` で 6 語 422、文字列 422、無い id 404、重複 id は 1 つに畳む（`skipped 1`）。`gloss.batch=5` で 10 語 → **`calls 2`**（単位は設定で毎回読む）。
9. **`GET /api/assets/{id}/tags` の 3 欄**（P4-1 C-6 の宿題）: 確かめた結果、問題なし。`glosses` は語名を鍵にした辞書（`ja` / `source` / `engine` / `edited`）、`pending_gloss` は **`items` の順の名前の配列**で `items` のうち語釈なしと一致、`counts` は**出所ごと**。
10. **契約**: `review.json`（`asset:` と `all`、`include_tags=true`）が本物の `jsonschema` で OK。`gloss` 61/61、`gloss_edited` に `true` / `false`。
11. **回帰**: `uv run --no-sync pytest -q` → **278 passed**（260 + 18）。`gui_smoke` → **91 ok**。`gui_layout` 4 画面 → すべて ok（複製に要求を 1 つ作って）。P5 / P6 / P4-1 の口（要求・注記・jobs・export）→ 200。実データの mtime 不変。
12. **時間**（§7。測り方: 複製のサーバに HTTP で `POST`、壁時計。`/free` の後が「初回」）:

| 何 | 実測 | 備考 |
| --- | --- | --- |
| 初回（模型の読み込み込み）20 語 | **10.6 s**（`elapsed_ms 10543`） | 実装者 9.7 s（18 語）、設計 10.1 s と同じ程度 |
| 初回 5 語 ×2 | 6.6 / 6.9 s | 読み込み ≈ 5 秒＋語数分 |
| 2 回目以降 20 語 | **4.07 s**（`calls 2`。1 語を 1 語ずつ） | 設計の 4.6〜4.8 s と同じ程度 |
| 2 回目以降 16 語 | 4.92 s | |
| 10 語（`batch=5` で 2 回） | 2.77 s | |
| 5 語 | 1.6 s | |
| 2 回目（全部 `skipped`） | 0 ms | 模型を回さない |

- 見積り: 1,000 語を 20 語ずつ → 50 回 × 約 4〜5 s ≒ **4 分＋初回 5〜10 s**（実装者 §6-4・設計 §7 と一致）。10,000 枚は**見えた語だけ訳す**前提なので語数で決まり、画像数には比例しない。
13. `tests/test_gloss.py` は**偽の engine（`FakeEngine`）だけ**で、本物の模型を呼ばない。`pytest` 既定で走って 12.9 秒。実機は `probe_p4.py --gloss`。
14. `apps/gui/taglist.js` が既にあり `gloss` を参照している（P4-3 の作業が始まっている）。P4-2 の範囲外なので見ていない。
15. ComfyUI の `temp/image-reviewer/` の複製は **101 枚**（P4-1 の監査時 53。タグ付けのたびに増える。P4-1 の D-14 のまま）。

## E. 設計とのずれ

1. **§4.2 と §3.5 の矛盾**（指示 (8)）: §4.2 の箇条書きは「人が直す口は **`edited=1` と `source='manual'` を同時に立てる**（1 回の更新で両方）」、同じ箇条の括弧書きは「自動の訳を人が直したなら **`textgenerate` のまま** `edited=1`」、§3.5 は「人が直す口（`source='manual'`・`edited=1`）」。**実装は括弧書き**（行があれば `source` を保つ、無ければ `manual`）。判定: **妥当**（`source` が由来、`edited` が印、という読みは一貫していて、`engine` が意味を保つ）。ただし設計の 2 文を消して「`source` は由来。人が直す口は `edited=1` だけを立て、行が無ければ `manual` で作る」に揃える。
2. §0.9「`system_prompt` は設定ファイルの文面」: 実装は `settings` 表の `gloss.system_prompt`（初期値はコード）。**設定の変更が再起動まで効かない**（C-1）のは設計の意図と違う。
3. §3.5 の表に「ComfyUI が時間内に応答しない → 504」「通信エラー → 502」が無い（B-1 の帰結）。足す。
4. 設計が黙っていて実装が決めた 8 点（`docs/p4-2-implementation.md` §5）: 404 / 重複を畳む / `limit` 既定 20 上限 20 / `engine` に模型名 / `source` を保つ（E-1）/ 502・504 はそのまま返す（B-1 で 500 になる経路がある）/ `pending` は使用数順 / `gloss.batch` を設定に —— **すべて妥当**。`pending` の使用数順は実機で `1girl, 1boy, …` の順を確認。
5. `GET /api/tags/gloss/pending` の `count` は「表にあって語釈が無い語」（実装者の穴 2）: 実機 **114 語**（画像 3 枚のタグ 60 語より多い）。画面のバーには `pending_gloss` の長さを使う、と §5.4 に 1 行。

## F. テストで守れないもの

| 観点 | 判定 | 根拠と直し方 |
| --- | --- | --- |
| §8.1-9（番号で対応・4 種の注入・部分適用） | **落ちる形** | `test_parse_numbered…` / `test_numbered_reply_maps_by_number…`（`calls == 4`、`engine.calls` の中身まで）/ `test_partial_reply…`（17/20）。位置対応に戻すと `2. long hair` と `2. 長髪` の扱いで落ちる |
| §8.1-10（`edited=1` の保護） | 落ちる形 | `force=True` で `("人が直した", 1)` が残り、守る語を模型に送らない（`engine.calls == [["long_hair"]]`） |
| §8.1-11（`GET` が訳さない） | 落ちる形 | 4 つの `GET` の前後で行数不変＋**`engine.calls == []`** |
| §8.1-21（上限） | 落ちる形 | 21 語 422、20 語は通る |
| §8.1-23（2 回目は回さない） | 落ちる形 | `calls == 0`、`len(engine.calls) == 1` |
| 取引の外で待つ | 落ちる形 | 0.5 秒の偽の模型で `locked()` 0.25 秒以内 |
| **通信の例外（B-1）** | **テストが無い** | `FakeEngine.translate` が `URLError` を投げる試験を足し、502 / 504 を固定する |
| **設定の読み直し（C-1）** | **テストが無い** | `settings` を変えて 2 回目の `engine_factory` 呼び出しを見る |
| 線 6 の実機 | 偽の模型（妥当） | 本物に壊れた応答は出させられない。`probe` も in-process の注入 |
| 本物の模型を呼ぶテスト | 無い（既定で走らない） | 妥当。実機は `probe_p4.py --gloss` |

## G. 依頼者への質問（推奨つき）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | `source` の意味（E-1） | (a) **由来**（実装。自動の訳を直しても `textgenerate`）／(b) 人が触ったら `manual` | **(a)**。`engine` と `source` が一致したまま残り、「人が直した」は `edited` だけで判定できる。設計の 2 文を直す |
| G-2 | 設定の読み直し（C-1） | (a) **`translate` のたびに読む**／(b) 再起動を要する仕様と書く | **(a)**。`GlossEngine` は状態を持たず作り直しが軽い |
| G-3 | 「日本語」の判定（C-2） | (a) ASCII だけでない（いま）／(b) **かな・漢字を 1 文字以上含む** | **(b)**。`……` と `👁️ girl` を弾ける。半角カナと記号だけの訳は無い |
| G-4 | エージェントの `POST /api/tags/gloss`（C-3） | (a) **許す**（設計どおり）／(b) `human` だけ | **(a)**。要求の流れで語釈を先に揃えたい場面がある。§3.1 に明記 |
| G-5 | 通信エラーの扱い（B-1） | (a) **`_wait` で受けて待ち直し、期限で 504**／(b) 即 502 | **(a)**。読み込み中の無応答は数秒〜十数秒で、待てば通る（3/3） |

## H. 確かめられなかったこと

- 冷えた模型の 500 は **1 回だけ観測**（再現 3 回は通った）。条件（空き RAM・直前のジョブ）を固定した再現はしていない。コードの経路（通信の例外を受けない）は確定。
- `system_prompt` を利用者が書き換えたときの崩れ方（実装者の穴 1）: 測っていない。
- `max_length=512` が長い語釈で切れるか（実装者の穴 3）: 20 語までで切れなかった。
- 画面（P4-3）: 範囲外。
- 後始末: サーバ 8791 停止。`.tmp-audit-redo/p42/` を残した（`srv/` に語釈 87 行・要求 1 つ）。`.data/` の mtime は 10-15。`src/` の最新は `tools/probe_p4.py` 11:10（実装者）。**利用者の ComfyUI の模型を `/free` で 3 回降ろした**（次に使うとき読み直すだけ。生成はしていない）。ComfyUI の `temp/image-reviewer/` は 101 枚。

### 実行したコマンドと結果（主なもの）

```
uv run --no-sync pytest -q                                   → 278 passed
node tools/gui_smoke.mjs                                     → 91 ok
.venv\Scripts\python.exe tools/probe_p4.py --gloss           → すべて OK（18/18・calls 1・9.7 s・2 回目 calls 0・注入 4 種）
.venv\Scripts\python.exe (parse_numbered の端 13 件 / 設定の読み直し)  → 全角番号 OK、…… と 👁️ girl が通る、設定は 1 回しか読まない
uv run --no-sync --with jsonschema python .tmp-audit-redo/p42/p42_http.py
                                                             → 初回 500（1 回目）→ /free 後 10.6 s で 200、GET は書かない（history 不変）、
                                                               2 回目 calls 0、線 5、422/404、取引の外（待ち ≤27 ms）
uv run --no-sync --with jsonschema python .tmp-audit-redo/p42/p42_http2.py
                                                             → batch=5 で calls 2、agent 200、守り 403、llm 変更が効かない、冷えた模型 6.6/6.9 s、契約 OK
再起動（gloss.url=:1）                                        → 409 gloss_engine_unavailable ×2、GET 200、行は増えない
node tools/gui_layout.mjs --count 8 / --screen requests / group / asset   → すべて ok
```
