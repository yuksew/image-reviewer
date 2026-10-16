# P5-2 実装の監査報告

- 監査した版: 2026-10-15 の作業ツリー（コミット無し）。読んだもの: `src/image_reviewer/{compare,png_meta,store,review,export,db,app,cli,scan,capture,reasons}.py`、`api/{__init__,compare,groups}.py`、`apps/gui/{compare.js,app.js,index.html,styles.css}`、`tests/` の 6 ファイルと `conftest.py`、`pyproject.toml`、`README.md`、`docs/{p5-design,comparison,p5-audit-brief,p5-review-report,p5-review-triage,p5-audit-report}.md`。
- **実行できたかどうか: 何も実行できていない。** `Bash`（サンドボックス有り・無しの 2 回）、`PowerShell`、`Glob` / `Grep` が使う `rg` のすべてが `EPERM: operation not permitted, uv_spawn` で拒否された（前回の監査と同じ制限）。したがって **`pytest`・サーバの起動・実データ（`.data/db.sqlite3` は二進ファイルで `Read` では読めない）・性能の計測・ブラウザでの確認はいずれも「実行していない」**。以下はすべてコードを読んで推論した結果で、§H に**依頼者がそのまま打てる確認手順**を置いた。
- テスト件数は**ソースを読んで数えた 127 件**（`test_review.py` 35 / `test_compare.py` 24 / `test_prototype.py` 21（parametrize 3 を含む）/ `test_store_sqlite.py` 12 / `test_db.py` 14 / `test_export.py` 21）で、指示書の「127 件が通るはず」と一致する。通るかどうかは確かめていない。
- 総合判定: **条件つきで使える。** 合格の線（8 枚を来歴つきで比べ、違う行だけが既定で見える）はコード上は満たしている。差分の鍵・2 段の正規化・`moved`・実寸・`tags: null`・`base`・まとまり無しの比較・403・前回の 5 件は、いずれも設計どおり。ただし **(1) 語の union（`_union_tokens`）が基準の語数 × 画像数だけ LCS を回し直すので、普通の長さのプロンプトで §8 の 30ms を超える見込み**、**(2) 英訳を捕獲していない画像の `final_prompt` に前置語だけを入れるため、差分表が「同じ」「違う」を取り違える**、**(3) 画面に基準（`base`）を変える口が無い**（点検 C10 が予言したとおり）の 3 点は使う前に直す必要がある。

---

## A. 合格の線を満たしていない（必ず直す）

**無し。** 「8 枚を来歴つきで比べ、違う行だけが既定で見える」は、コード上は満たしている:

- サーバは `changed`（`state != "same"` の行。`changed` / `reweighted` / `only_in_some`）と `same` を分けて返す（`compare.py:712-714, 722-729`）。
- 画面は既定 `showSame: false` で `diff.changed` だけを描き、`same` は「同じ N 行は畳んであります」の 1 行に畳む（`compare.js:28, 201, 220-223`）。`m` キーと「同じ行」ボタンで開く（`compare.js:405, 429-434`）。
- 8 枚は `layoutFor(8)` が 4×2（`compare.js:53-58`。`comparison.md` §2.1 の表どおり）。

ただし **8 枚で文書を組み立てるテストが 1 つも無い**（最大は 3 枚。§F-1）。合格の線そのものが自動では守られていない。下の B1・B2 は「違う行」の**中身**を間違える問題で、線を越えているかどうかではなく、越えた先の表の信頼性に効く。

---

## B. 重大（静かに間違える）

| # | 場所 | 問題 | 利用者の側で何が起きるか | 再現手順 / 確認手順 | 提案 |
| --- | --- | --- | --- | --- | --- |
| **B1** | `src/image_reviewer/compare.py:613-657`（`_union_tokens`）。とくに **`:629-636`**: `for word in base_words:` の中で、`for index in range(len(items)):` ごとに **`diff_sequence(base_keys, [...])` を呼び直している**。同じ結果は `build_prompt_diff()` が `:581-582` で画像ごとに 1 回ずつ既に計算していて、捨てている | **基準の語数 B × 他の画像数 (N−1) 回**、`difflib.SequenceMatcher(autojunk=False)` を回す。1 回の LCS は O(B × I) なので全体は **O(B² × I × N)**。語数の上限は無い（`MAX_CHAR_DIFF` は `ja_text` の文字差分だけ。`compare.py:43, 686`）。§8「差分表（8 枚）30ms 以内」の見込みが立たない。私は計測していないが、品質語を含む普通のプロンプト（40〜80 語）で 8 枚なら数百回の LCS になり、200 語なら 1,400 回になる。**遅いだけで値は誤らない**が、§8 の数値目標の違反としてここ（B）に置く | 比較の応答が遅くなる。プロンプトが長い組（アニメ系は 100 語を超えることがある）で秒単位になりうる | **実行していない。** §H-3 の計測スクリプト（8 枚 × 20 / 60 / 200 語で `build_document` の時間を出す）を打つ。`_union_tokens` を `build_prompt_diff` の `item_states` を受け取る形に直すと同じスクリプトで桁が変わるはず | `build_prompt_diff()` が画像ごとに計算した `item_states` を `_union_tokens()` に渡し、`word` のループの中で LCS を呼ばない（`moved` の判定は画像ごとに 1 回で足りる）。あわせて語数の上限（例: 1 画像 2,000 語を超えたら語の差分を省く）を `MAX_CHAR_DIFF` と同じ形で置く |
| **B2** | `src/image_reviewer/compare.py:329-342`（`_effective_final_prompt`）と `:372`。`png_meta.py:272-280` は、正側が `StringConcatenate` で英訳が捕獲されていない画像では **`final_prompt=None`、`final_prompt_source="reconstructed"`、`concat_prefix="(masterpiece, …), safe,"`** を返す。`compare.py` はこのとき**前置語を `final_prompt` の値にする** | 「最終プロンプト」の行に、**実際には翻訳文が続いていた**のに前置語だけが入る。帰結が 2 つ。(a) **捕獲していない 2 枚**（日本語原文が違っても）は `final_prompt` が「同じ」と出る。(b) **捕獲した 1 枚と捕獲していない 1 枚**を比べると行は `changed` になり、訳文の語が**基準がどちらかで `added` か `removed`** になる。基準が捕獲側（`test_real_assets…` の並び）なら、相手の画像ごとの行は前置語だけで全部 `same`、訳文は union の行にだけ `removed` で出る（C6）。基準が捕獲していない側なら、捕獲側の行で訳文がまるごと `added`。どちらも「最終プロンプトは不明」が正しい答えで、`final_prompt_source` の行（`reconstructed` / `None`）を見ないと気づけない | 実データ（263 枚中、英訳を持つのは 1 枚。前回の監査の指示書）では、**ほぼすべての比較でこの行が「同じ」**と出る。利用者は「プロンプトは同じで seed だけ違う」と読むが、実際には翻訳文が毎回違った可能性がある（`textgen_params` の `sampling_mode.seed` が違えば訳も違う） | **実行していない。** §H-4 のスクリプトで実データの 8 枚を組み立て、`final_prompt` の `state` と `values`、`final_prompt_source` を並べて見る。`values` が全部 `(masterpiece, …), safe,` のような前置語だけで `state == "same"` なら再現。`tests/test_compare.py:476-520` の実データテストは**この行を見ていない**（§F-5） | `final_prompt` は**捕獲できたときだけ**入れ、捕獲していないときは `None`（`only_in_some` に落ちる）。前置語は別の鍵（例 `prompt_prefix`。`concat_prefix` は `analyze_graph` が返す値で「発明」にならない）で比べる。画面は `final_prompt_source == "reconstructed"` で値が無い枚に「訳は未捕獲」と 1 行出す |

---

## C. 中程度

| # | 場所 | 問題 | 利用者の側で何が起きるか | 再現手順 | 提案 |
| --- | --- | --- | --- | --- | --- |
| **C1** | `apps/gui/compare.js:394-420`（`installKeys`）、`:74-101`（`showCompare`）、`apps/gui/app.js:308-312`（`openCompare`） | **画面に基準（`base`）を変える口が無い。** `b` キー（`comparison.md` §6 の表 `:202`）も、タイルを押して基準にする経路も、ボタンも無い。`?base=` を URL に手で書く以外に無い。API 側は `?base=` に追従する（`compare.py:705-711`、`test_compare.py:200-221`）ので、**点検 C10（`p5-review-report.md:46`）が「実装者が 1 番目を基準に決め打ちし、`b` キーが効かない」と予言した状況が画面側で起きている** | 8 枚から 1 枚を選ぶとき、「3 番を基準に他を見たい」ができない。`prompt_diff` の `per_asset` は常に 1 番目からの差で固定される | §H-2 の (7)。`#/compare?ids=a,b,c` を開き、`b` を押す・2 番のタイルを押す → 上の 1 行が「基準 1 番」のまま。URL に `&base=<b の id>` を足して開き直すと「基準 2 番」になる | タイルの番号（`.no`）クリックか `b` キーで `location.hash` の `base=` を書き換える（`showCompare` が再取得する。サーバの再計算は既定どおり）。`comparison.md` §6 に「`b` は選択中のタイルを基準にする」とあるので、`select()` した枚を `b` で基準にするのが素直 |
| **C2** | `compare.py:465-466, 474-475`（`_signature` / `_word_signature` が**語順つきのタプル**） | **語順だけの違いが、表の行では `changed`**（太字・「違い」のバッジ）になる。`moved` は `prompt_diff` の語にだけ付く。`p5-design.md` §6.1 `:374` と `comparison.md` §3.2 `:115` は「順序だけの違いは追加・削除と区別する」と言い、設計は行レベルの話として書いている。`test_compare.py:168-183` は `per_asset` の `moved` だけを固定していて、行の `state` を見ていない（§F-4） | 語を入れ替えただけの 2 枚が、表では「最終プロンプトが違う」と出る。利用者は語の差分を開いて「移動 3 語」を読むまで分からない。`reweighted` を行に出したのと同じ理由で、行にも区別が要る | `test_compare.py:170-171` と同じ 2 枚（`"1girl, solo, chibi"` / `"chibi, 1girl, solo"`）で `compare.compare_assets(store, [a, b])` → `row_of(doc, "final_prompt")["state"] == "changed"`、`cells == ["same", "changed"]`。`prompt_diff.per_asset[b]` は `["moved", "same", "same"]` | `_word_signature` を**順不同**（`sorted` か `Counter`）にし、順序つきでは違うが順不同で同じなら `state: "moved"`（または `reordered`）を行に出す。画面は `stateLabel` に 1 行足すだけ（`compare.js:236-238`） |
| **C3** | `compare.py:462, 486-487, 532-538`（`node_types`）と `compare.js:206-218`（`renderDiff`） | (a) `_signature` が **`frozenset(raw.keys())`** なので、**同じ型の個数の差**（`KSampler` 1 と 2。hires-fix の 2 段目や refiner）は「同じ」になる。`_display` も型名だけを並べ、個数を落とす。(b) 点検 C5 が求めた「集合の差」は `row["only_in"]` に計算してあるが、**画面はこれを読まず**、各セルに**全部の型名**を並べる。差を取るのは利用者の目 | 2 段サンプリングの有無が差分表に出ない。ControlNet の有無は出るが、8 列の長い型名の列を見比べる必要がある | (a) `make_meta(node_types={"KSampler": 2, "SaveImage": 1})` と `{"KSampler": 1, "SaveImage": 1}` の 2 枚 → `row_of(doc, "node_types")["state"] == "same"`。(b) `test_the_c5_keys_are_diffed`（`test_compare.py:251-260`）の 2 枚を `#/compare?ids=` で開く → 「ノード」の行の両セルに `KSampler, SaveImage, TextGenerate` / `KSampler, SaveImage` と全部が並び、`TextGenerate` だけが強調されることはない | `_signature` を `tuple(sorted(raw.items()))`（型と個数）にし、`values` は「共通部分に無い型だけ」（`only_in`）を出す。共通部分は `title` か畳んだ行に回す |
| **C4** | `compare.py:66-90`（`COMPARE_KEYS`）↔ `png_meta.py:305-309, 304`（`analyze_graph` が返す **`textgen_system_prompt`**、**`ja_source`**）、`capture.py:150`（**`en_source`**） | 指示書 §2-2 の「逆向き」: `analyze_graph` が返すのに差分に無い鍵は **`textgen_system_prompt`**（翻訳 LLM への指示。訳を変える）、**`ja_source` / `en_source`**（点検 C5 `p5-review-report.md:41` は「同じ文でも捕獲と訳し直しは別物」と `en_source` を挙げた）、`loras[].loader`、`clip_all`。設計 §0.6 `:78-82` は C5 の列挙から 5 つだけ採り、`textgen_system_prompt` と `en_source` を**黙って落とした**（仕分け `p5-review-triage.md:23` は「5 鍵を追加」とだけ書く）。実装は設計どおりで、**責任は設計側**。それ以外（`positive_literal` は `final_prompt` に畳まれる、`seed_raw`、`has_textgen`、`primary_ksampler`、`unresolved`、`concat_prefix` / `concat_delimiter`）は差分に出さなくてよい | system prompt を変えて訳の傾向を変えた 2 枚が「翻訳の設定は同じ」と出る。`textgen_params` に `system_prompt` が入るのは**リテラルで渡したときだけ**（`png_meta.py:306`。結線なら落ちる。実物のグラフ `test_prototype.py:65-68` は結線） | `make_meta(textgen_system_prompt="A")` と `"B"` の 2 枚 → `"textgen_system_prompt" not in doc["diff"]["keys"]`、`changed` にも `same` にも無い | `textgen_system_prompt`（kind `text`）と `en_source`（kind `text`）を `COMPARE_KEYS` に足す。`clip_all` は P5-3 以降 |
| **C5** | `apps/gui/compare.js:124-127`（`render` の「同一 seed / seed が違うので画素は別物」） | `seed` の行が **`same`** のときに「同一 seed」と出すが、`_row` は**全枚に seed が無いときも `same`** を返す（`compare.py:499-500`）。来歴の無い 2 枚を比べると「同一 seed」と出る。また `comparison.md` §3.3 `:122-127` の「seed が同じ**組**にバッジ」は、8 枚のうち 2 枚だけ同じ seed のときに何も出ない（全部同じか全部違うかの 2 値） | 来歴の無い写真 2 枚で「同一 seed」。seed が 2 枚ずつ対になった 8 枚で、どの組が同じ seed かが分からない | 一覧で「来歴なし」の 2 枚を Ctrl+クリックで選び「比較を開く」→ 上の 1 行が「2 枚 / 基準 1 番 / 同一 seed」。API では `row_of(doc, "seed")` が `state == "same"` かつ `values == [None, None]` | `values` が全部 `null` なら出さない。組のバッジは、サーバが `seed` の `values` を返しているので画面で同値のセルに同じ色を当てれば足りる（計算の再実装にはならない） |
| **C6** | `compare.py:581-597`（`build_prompt_diff` が `_base_states` を捨てる）、`compare.js:245-253`（`promptBlock` の画像ごとの行） | 画像ごとの行は**その画像の語**だけを並べるので、**基準にあってその画像に無い語（削除）は、その行に出ない**。`tokens`（union の行）には `removed` が出るが、「どの画像で消えたか」は `assets` を読まないと分からず、画面は `assets` を描かない。`comparison.md` §3.1 `:105` の「2 枚は左右 2 列の diff（片側に −、片側に +）」はこの形では作れない。`test_compare.py:186-194` は名前が「removed word is removed」なのに `removed` を 1 つも assert していない（§F-3） | 「基準にあった `chibi` を 3 番が落とした」が、3 番の行に出ない | `a="1girl, solo, chibi"`、`b="1girl, solo"` で `compare.compare_assets(store, [a, b])` → `per_asset[b]` の `state` が `["same", "same"]`（`removed` が無い）、`tokens` に `{"t": "chibi", "state": "removed"}` | `per_asset[id]` に基準側の `removed` を（位置を保って）混ぜるか、`removed: [...]` を別に持たせる。画面は `line-through` の CSS（`styles.css:285`）が既にある |
| **C7** | `src/image_reviewer/api/compare.py:37-39`、`compare.py:760-766` | `GET /api/groups/{id}/compare` は `ids=` 無しだと全員を渡すので、**9 枚以上のまとまりは既定で 422**（「8 枚まで」）、**1 枚のまとまりも 422**（「2 枚以上」）になる。docstring（`:33-36`）はそう書いてあるが、設計 §3.2 `:248` の「比較に要るものを 1 回で返す」からは遠い。画面は `#/compare?group=` の経路を持つ（`compare.js:80`）が、`app.js` はそこへ入る道を作っていない | まとまりの画面（P5 では未実装）から比較へ入れるようになったとき、9 枚以上のまとまりで最初の 1 回が必ず 422 になる | `POST /api/groups` に 9 枚の `asset_ids` → `GET /api/groups/{id}/compare` → 422「一度に並べられるのは 8 枚までです」。1 枚のまとまり → 422「比較には 2 枚以上が要ります」 | 既定を「`position` 順の先頭 8 枚」にし、`group.item_count > 8` のとき応答に `truncated: true` を付ける。1 枚は 422 のままでよい |
| **C8** | `compare.py:770-780`（`check_ids` が先、`store.asset()` が後）、`api/compare.py:25`（`ids: str \| None`）、`api/compare.py:40-43` | **指示書 §2-8（未知の id は 404 か 422 か）の判断**: `/api/compare` は未知の id を **404** で返し（`compare.py:777-778`）、テストが固定している（`test_compare.py:376-381, 451`）。**仕様（404）のとおりで正しい。** 依頼者が実測した 422 は次の 3 つのどれかで出る。(a) **形の検査が存在の検査より先**なので、`ids=nope`（1 枚）・`ids=nope,nope`（重複）・9 枚以上は 404 に届かず 422。(b) FastAPI は `ids: str` に対して `?ids=a&ids=nope` のような**繰り返しの query を最後の 1 つだけ**採るので 1 枚になり 422。(c) **`/api/groups/{id}/compare` は「まとまりに無い id」を 422** で返す（`api/compare.py:40-43`）。未知の id は必ず「まとまりに無い」ので、この口では未知でも 422 になる。(c) は「所属の検証」として妥当だが、**設計 §3.2 にも docstring にも書かれていない** | 2 つの口で同じ入力の番号が違う。他ツールが「404 なら消えた画像」と判断すると、まとまりの口では判断できない | §H-5 の 5 本の `curl`（`/api/compare` で 404 / 422 / 422、まとまりの口で 422 と `details.extra`） | `/api/compare` は現状のまま（404）。`/api/groups/{id}/compare` は「所属しない → 422、`details.extra` に id」を設計 §3.2 に書き、**未知の id の場合は `details.unknown` を分けて**返す（`store.asset()` を 1 回引けば分かる） |

**確かめた結果、問題なし（コード上。実行はしていない）**:

- §2-2 **C5 の 5 鍵**: `negative_literal` / `init_image` / `textgen_params` / `node_types` / `final_prompt_source` は `COMPARE_KEYS`（`compare.py:81-87`）にあり、`asset_item` が `analyze_graph` の同名の欄から写す（`:365-367, 373-374`）。`clip_skip` は入れていない（`test_compare.py:285-287`）。
- §2-3 **正規化の 2 段**: `(word:1.2)` と `word` は `_signature`（語＋重み）が違い `_word_signature`（語だけ）が同じなので `reweighted`（`compare.py:503-508`）。`((word))` は 1.1² で同じ経路。`<lora:x:0.8>` と `<lora:x:1.0>` も `parse_weight` が LoRA の重みを `weight` に入れる（`:218-222`）ので `reweighted`。**重みを変えたのに `same` に潰れる経路は見つからなかった**。`loras` 行（kind `list`）の重みの差は `_lora_key` が `strength_model` / `strength_clip` を含む（`:406-411`）ので `changed`（`reweighted` ではないが「違う行」には入る）。`reweighted` の行は `state != "same"` なので `changed` の配列に入る（`:713`）。
- §2-4 **実寸**: `asset_item` は `asset["width"] / ["height"]` を使い（`compare.py:362-363`）、`meta` の `EmptyLatentImage` 由来の値は見ない。`test_compare.py:293-312` が img2img（`meta.width=None`）と食い違い（`meta` 1024 / 実体 768）の両方を固定している。
- §2-5 **`tags: null`**: `compare.py:384`。`test_compare.py:325` が `is None` で固定（`[]` では落ちる）。
- §2-6 **基準**: 既定は入力順の先頭（`compare.py:705-706`）。`?base=` が `ids` に無ければ 422（`:708-711`）。`prompt_diff.base` と `ja_diff.base` が追従する。`ja_diff` は文単位（`split_sentences` → `diff_sequence`）→ 変わった範囲だけ文字単位（`_char_runs`）の 2 段（`:663-693`）。`test_compare.py:200-221, 346-360`。
- §2-7 **まとまり無し**: `GET /api/compare` はまとまりを引かない（`api/compare.py:24-27`）。`GET /api/groups/{id}/compare` は `group_state()` で 404 を出し、所属を検査し、**同じ `compare.compare_assets` の文書に `group_head()` を足すだけ**（`:44-45`）。`test_compare.py:406-443`。
- §2-9 **`object-fit: cover` は使っていない**: `styles.css:104, 219, 249` はすべて `contain`。枠は高さ固定・幅は縦横比（`compare.js:140-147, 161`）。**同期ズームはマウスだけで成立する**: ホイールで拡大（`:342-346`、`passive: false` で `preventDefault`）、ドラッグで移動（`:361-383`）、ダブルクリックで等倍（`:184`）、「同期ズーム」「等倍」「同じ行」のボタン（`index.html:67-69`、`compare.js:437-449`）、「← 一覧」で閉じる（`index.html:63`）。キーは補助（`z` / `m` / `+` / `-` / `0` / `1`〜`8` / `Esc` / 矢印）。**画面で差分を計算し直していない**: 行の `state`、セルの `cells`、語の `state`、`ja_diff` をそのまま描く（`compare.js:201, 207-217, 247-251, 282-287`）。`render()` の `sameSeed` と `promptBlock` の「移動 N 語」はサーバの `state` を数えるだけ（C5 の問題は別）。
- §2-10 **403**: middleware は `create_app()` の `app` 全体（`app.py:75-90`）で、比較のルーターも同じ `app` に載る（`:96`）。`test_compare.py:456-470` が `/api/compare` と `/api/groups/{id}/compare` の両方で Host（GET）・Origin・Content-Type（POST。経路が無くても middleware が先に弾く）の 403 を固定している。
- §2-11 **前回の 5 件を壊していないか**: **A1**（`changed_at` を同じ取引で更新）は `review.py:124, 454-456, 276, 760` にあり、`test_export.py:217-283` が「一度書き出した後」で守る。**A2**（4 経路の `_contradicts`）は `review.py:702-722`、`test_review.py:538-601`。**B1**（取り込みの台帳）は `cli.py:214-235`、`test_store_sqlite.py:379-413`。**B2**（部分失敗）は `export.py:188-204`、`test_export.py:309-335`。**B3**（錠の外の読み）は `export.py:162, 216, 248, 276` が `store.locked()` を取り、**`compare.py:773-779` も `with store.locked():` の下で `store.asset()` を回す**（`Store._lock` は `RLock` なので `_fetchone` の入れ子は壊れない。`store.py:60, 405-407`）。`compare.py` は書き込みをしない。`test_export.py:364-417` が未コミット行を読まないことを守る。
- §2-13 **入力の検査**: 空の `ids` → 422（`compare.py:754-755`）、重複 → 422 と `details.duplicate`（`:756-759`）、9 枚以上 → 422 と理由（`:760-766`）、`a,,b` → 422（`:744-745`）。`test_compare.py:366-400`。空文字・空の入れ物は `_raw_of` が `None` に寄せる（`:394-403`）。

---

## D. 軽微

確認はいずれも引用行を読めば足りる（前回の監査と同じ扱い）。

| # | 場所 | 問題 | 提案 |
| --- | --- | --- | --- |
| D1 | `compare.py:215`（`^(?P<body>.+?):(?P<w>…)$`） | コロンを含む語を重みとして読む。`16:9` → 語 `16` 重み 9、`ratio 1:1` → 語 `ratio 1` 重み 1。逆に `(a : 1.2)`（コロンの前後に空白。ComfyUI は `float()` で読むので有効）は重みにならず `changed` になる | 重みの判定を `_wrapped` の中か `<lora:…>` の中に限る。空白を許す |
| D2 | `compare.py:588-595` | `moved` の語は重みを比べない（`w` は 1.0 以外のときだけ出し、`base_w` は出ない）。語順と重みを同時に変えた語は重みの差が見えない | `same` と同じ分岐を `moved` にも通す |
| D3 | `compare.py:512-521` | 3 枚以上で「基準と語が違う枚」と「基準と重みだけ違う枚」が混ざると、行は `changed` になり、重みだけ違う枚のセルも `changed` になる（`reweighted` は行が `reweighted` のときだけ） | セルの状態は枚ごとに決める（`_word_signature` を基準と比べる） |
| D4 | `compare.py:724`、`test_compare.py:238-240` | `diff.keys` は画面が読まない（`compare.js` に `keys` の参照が無い）。テスト `test_changed_rows_come_first_and_same_rows_are_collapsed` が守っているのは**この死んだ配列の並び**（§F-2） | `keys` を省くか、画面で列の並びに使う |
| D5 | `compare.py:366, 462, 464`（`node_types` / `textgen_params` の型を仮定） | `meta` が `analyze_graph` 以外から来たとき（`migrate-from-json` の旧 `meta`、手で直した JSON）、`node_types` がリストなら `dict()` で、`textgen_params` がリストなら `params[k]` で **500** になる。`asset_item` は `_raw_of` より前に走るので `None` には寄らない | `isinstance(…, dict)` でなければ `None` に寄せる |
| D6 | `src/image_reviewer/review.py:287-290`（`group_state` が `store.transaction()` = `BEGIN IMMEDIATE`）、`api/compare.py:37` | まとまりの比較は**読むだけ**なのに書き込みの錠を取る。別プロセスの `cli scan` が書いている間、`busy_timeout`（15 秒）まで待つ。P5-1 のコードだが新しい口が引き継いだ。指示書 §2-11 の裏返し（錠の**外**ではなく、要らない錠を**中**で取る） | `group_state` を `store.locked()` に変える |
| D7 | `apps/gui/compare.js:158-179`、`p5-design.md` §5.4 `:342` | 比較のタイルに「来歴なし（左下に `--warn` の点）」の印が無い。キープ / ボツの印はある（`:168-169, 177`）。一覧（`app.js:159, 170`）にはある | `.cmp-frame` に `.warn` を足し、`provenance.model` も `seed` も `null` なら出す |
| D8 | `comparison.md` §3.1 `:104-105` | 「数値は増減が分かる形（`steps 10 → 20`）」「2 枚は左右 2 列の diff」は未実装。値はそのまま並ぶ | 2 枚のときは `cells` を使って `−` / `+` の 2 列にする。数値の行は基準との差を `title` に出す |
| D9 | `compare.py:379-380`、`app.py:197-208`、`thumbs.ensure_thumb` | 並べる見方は 1024 のサムネを使う（設計どおり）が、**初回は 8 枚の原本を復号して 1024 と 256 の 2 種類を作る**。`comparison.md` §7 の「400ms 以内（サムネ生成済み）」は生成済みが前提。初回の時間は未計測 | 走査時に 1024 も作るか、初回だけ「作成中」を出す |
| D10 | `api/compare.py:25`（`ids: str \| None`） | `?ids=a&ids=b` の形で来ると最後の 1 つしか読まない（C8-(b)）。画面は `a,b` の形で送るので実害は無いが、他ツールが間違えやすい | `ids: list[str] \| None = Query(None)` で両方を受けて結合する |
| D11 | `compare.js:143-146`（`stageHeight`） | 行に入る幅を**先頭 `perRow` 枚の縦横比の和**で見積もる。2 行目に横長が並ぶと `flex-wrap` で 3 行になり、枠が `stage` から溢れて縦スクロールが要る（ホイールは拡大に取られるので、スクロールはバーを掴むしかない） | 全行の最大の幅の和で見積もる |
| D12 | `cli.py:228-233`（取り込みの台帳の行の `actor` は `"human"` 固定、`created_at` は `reviewed_at or now`）↔ `cli.py:138-139`（`asset.reviewed_by` / `reviewed_at` は JSON の値そのまま） | JSON の `reviewed_by` が `None` や `"user"` なら、次の `reconcile()` が「台帳が正」で `human` に直し、WARNING を出す。**判断は消えない**（B1 は守られている）が、取り込み直後の起動で必ず WARNING が出る | 取り込みで `asset.reviewed_by` も `"human"`、`reviewed_at` も台帳と同じ値にする |

---

## E. 設計・`comparison.md` とのずれ

前回の監査（`p5-audit-report.md` §E）で挙げたもの（numpy 未導入、モジュール頂上の `create_app()`、README の古さ、契約の `clip` / `llm` など）は繰り返さない。いずれも未解消で、`cli.py:29-48` は `create_app()` の副作用に頼らない形に直してある（C1 の別解）。

| 項目 | 状態 | 場所・根拠 |
| --- | --- | --- |
| **§0.1 P5-2 の完了条件**（8 枚・違う行だけ） | **反映（コード上）** | §A。8 枚のテストは無い（§F-1） |
| **§0.6 C5 の 5 鍵** | **反映** | `compare.py:81-87`。ただし点検 C5 が挙げた `textgen_system_prompt` / `en_source` は設計が落とした（C4） |
| **§0.5 G5 重みは `reweighted`** | **反映** | `compare.py:505-508`。`comparison.md` §3.2 `:112` の「重みの表記」はまだ正規化の一覧に残っていて、**G5 の修正が `comparison.md` 側に書かれていない**。`p5-design.md` §7 の 20 `:432` も「重み表記の違いを『同じ』にする」のまま（テストは G5 に合わせて逆を固定している） |
| **§0.8 C10 `prompt_diff.base` / `per_asset` / `ja_diff`** | **反映（API）／未反映（画面の基準の切替）** | `compare.py:556-610, 663-693`。画面に `b` が無い（C1） |
| **§0.8 D5 `tags: null`** | **反映** | `compare.py:384` |
| **§0.7 C9 `GET /api/compare?ids=&base=`** | **反映** | `api/compare.py:24-27` |
| **§6.1 `thumb` は `?size=256`** | **別解** | `compare.py:379-380` は `thumb` を 1024（`comparison.md` §2.1 `:51` の「拡大は 1024 サムネ」に従う）、`thumb_small` を 256。設計の例が古い |
| **§6.1 `label` は鍵と同じ文字列** | **別解（妥当）** | `compare.py:51-58` は日本語の表示名。docstring に理由がある |
| **§6.1 「語順だけの違いは移動として区別する」** | **半分** | 語には付く。行には付かない（C2） |
| **§6.1 `changed` を先に・`same` を畳む** | **反映** | `compare.py:722-726`。画面 `compare.js:201` |
| **§5.3 「来歴の差分表を既定で出す」「画面で再計算しない」** | **反映** | `index.html:73`、`compare.js:198-234` |
| **§5.3 ヒートマップは近い組だけ有効・理由を 1 行** | **対象外（P5-3）** | 画面に無効なボタンも理由の行も無い。P5-3 で足す |
| **§5.4 来歴なしの印** | **未反映（比較のタイル）** | D7 |
| **§8 差分表 30ms** | **未計測。コード上は達成の見込みが薄い** | B1 |
| **§9 `apps/gui/compare.ts` / `diff-table.ts`** | **別解（C13 で素 JS）** | `apps/gui/compare.js` 1 本 |
| **`comparison.md` §2.1 各タイルの下に seed / steps / cfg / モデル名（短縮）** | **反映** | `compare.js:162-167, 193-196` |
| **`comparison.md` §2.1 左上に順位 1〜8** | **反映** | `compare.js:176` |
| **`comparison.md` §2.2 0.5x〜8x、`+` / `-` / `0`、`z`、`transform` だけ** | **反映** | `compare.js:14-15, 301-306, 402-405`、`styles.css:220`（`will-change: transform`） |
| **`comparison.md` §2.2 `Space` + ドラッグ** | **別解** | ドラッグだけで動く（`Space` は不要） |
| **`comparison.md` §3.1 増減の形・2 枚は左右 diff** | **未反映** | D8 |
| **`comparison.md` §3.2 正規化前の生の文字列を併記** | **反映** | `values` は生の文字列（`_display` は `str(raw)`）、語は `raw` |
| **`comparison.md` §3.3 seed が同じ組にバッジ** | **半分** | C5（全部同じときだけ。欠損でも出る） |
| **`comparison.md` §6 `b` / `Tab` / `r`** | **未反映 / 未反映 / 対象外（P5-3）** | C1。`Tab` は無くても `1`〜`8` とクリックで選べる |
| **`comparison.md` §6 「キーが無いとできない操作は作らない」** | **反映（ただし基準の切替は URL が要る）** | C1 |
| **`export.py:437-438` の `width` / `height` は `meta` を先に見る** | **`compare.py` と逆** | 点検 C5 は「実寸が正」。契約の書き出しは `meta.width or asset.width`、比較は `asset.width`。同じ画像で 2 つの口が違う値を出しうる（img2img で `meta.width` は `None` なので実害は希） |
| **`README.md:13, 23, 26`** | **古い** | 「テスト 103 件」「比較…は未実装」。127 件、比較は入った（`index.html:12` は更新済み） |
| **`index.html:13`** | **古いまま正しい** | 「キープ / ボツ…はまだ入っていません」は画面の話として正しい（API はある） |

---

## F. テストが守っていないもの

| # | テスト | 何を主張しているか | 実際に守っているか | 直し方 |
| --- | --- | --- | --- | --- |
| **F1** | （無い） | 合格の線「**8 枚**を来歴つきで比べ、違う行だけが既定で見える」 | **8 枚で `build_document` を組むテストが無い。** 最大は `test_size_comes_from_the_asset…` の 3 枚。`test_more_than_eight_ids…` は `check_ids` の 8 / 9 の境だけ | 来歴つき 8 枚（seed だけ違う 4 枚＋steps が違う 2 枚＋来歴なし 2 枚）で、`changed` が `seed` / `steps` と `only_in_some` の鍵だけ、`same` に残りが入ることを見る。`items` が 8 個、`per_asset` が 8 鍵、`cells` の長さが 8 |
| **F2** | `tests/test_compare.py:230-242` `test_changed_rows_come_first_and_same_rows_are_collapsed` | 「`changed` が先、`same` が畳まれる」 | **「先」を確かめていない。** `changed` と `same` は別の配列なので順序の主張が無く、代わりに `diff.keys` の中で `steps` が `cfg` より前かを見ている。`keys` は画面が読まない（D4）。`changed == ["steps"]` と `"steps" not in same` の 2 行だけが本体 | 画面が描く順（`changed.concat(same)`）に相当する「`changed` の全行が `same` の全行より前」を、両配列を連結して鍵の位置で確かめる。`keys` の assert は削る |
| **F3** | `tests/test_compare.py:186-194` `test_an_added_word_is_added_and_a_removed_word_is_removed` | 「追加は `added`、削除は `removed`」 | **`removed` を 1 つも assert していない**（名前と docstring だけ）。削除の表現（C6: 画像ごとの行には出ない、union には出る）が固定されていないので、直すとき何が正しいか分からない | `a="1girl, solo, chibi"`、`b="1girl, solo"` で `tokens["chibi"] == "removed"` と、`per_asset[b]` に削除がどう出るかを決めて固定する |
| **F4** | `tests/test_compare.py:168-183`（語順） | 「語順だけの違いは `moved`」 | `per_asset` と `tokens` の `moved` は守る。**行の `state` を見ていない**（今は `changed`。C2）。行で `moved` を出すように直しても、逆に `changed` のままでも、このテストは緑 | `row_of(document, "final_prompt")["state"]` を固定する（設計で行の状態を決めてから） |
| **F5** | `tests/test_compare.py:476-520` `test_real_assets_show_the_captured_translation_as_a_difference` | 「実データで英訳の差が出る」 | `en_text` の行だけ見る。**同じ 2 枚の `final_prompt` の行**（B2 が起きる組そのもの）を見ていない。基準が捕獲した枚なので、今は行が `changed`、`per_asset[other]` は前置語だけで全部 `same`、訳文は `tokens` の `removed` にだけ出る | `final_prompt` の `state` と `values[1]` を assert に足す。B2 を直せば `only_in_some` と `None` になる |
| **F6** | （無い） | §8「差分表 30ms」 | 計測が無い。`tests/` には性能のテストが 1 つも無い（設計 §7 は「計測スクリプトとして」でよい） | §H-3 のスクリプトを `tools/` に置き、結果を `p5-design.md` §0.7 の表に書く |
| **F7** | `tests/test_compare.py:137-163`（重み） | 「重みだけ違えば `reweighted`」 | `(solo:1.2)` と `((solo))` は守る。**`<lora:x:0.8>` と `<lora:x:1.0>`**（`parse_weight` の LoRA の分岐 `compare.py:218-222`）、**`loras` 行の `strength_model` の差**（`_lora_key`）、**語順と重みを同時に変えた場合が `changed`** は守っていない | 3 件を足す |
| **F8** | （無い） | `node_types` の「集合の差」 | `test_the_c5_keys_are_diffed` は `only_in` を 1 組だけ見る。**同じ型の個数が違う**（`KSampler` 1 と 2）とき「同じ」になること（C3）を誰も固定していないので、直しても壊しても緑 | `node_types={"KSampler": 2}` と `{"KSampler": 1}` で `state` を決めて固定する |
| **F9** | `tests/test_compare.py:124-135`（正規化）、`:318-328`（`tags: null`）、`:200-221`（`base`） | 指示書が「何も守っていないテストになりやすい」と挙げた 3 件 | **守っている。** 正規化は 4 種の違いを 1 つの文字列に詰めて `same` と `normalized_equal` を見るので、どの正規化を外しても落ちる。`tags` は `is None`。`base` は `?base=` の有無で `prompt_diff.base` / `per_asset` / `cells` が入れ替わることを両向きで見る | — |
| **F10** | `tests/test_compare.py:456-470`（403） | 「新しい口にも効く」 | 守っている。`/api/groups/{a}/compare` の `a` は asset の id（存在しないまとまり）だが、middleware は経路より先に走るので検査としては成り立つ | — |

**今すぐ要るのに無いテスト**（上の表の F1・F3・F5・F7・F8 に加えて）:

1. B2 の形: `final_prompt=None, final_prompt_source="reconstructed", concat_prefix="p"` の 2 枚で `final_prompt` の行がどうなるべきかを決めて固定する（今は `same`）。
2. B1 の形: `_union_tokens` が `diff_sequence` を画像ごとに 1 回しか呼ばないこと（`monkeypatch` で呼び回数を数える）。
3. C5 の形: 来歴の無い 2 枚で `seed` の行が `same` でも `values` が全部 `None` であること（画面のバッジの条件）。
4. C8 の形: `/api/groups/{id}/compare?ids=<member>,<unknown>` の応答の番号と `details`（今は 422 `extra`）。
5. 画面（任意。設計 §7 の 25・26 と同じく合格の線に数えない）: `#/compare?ids=a,b` で `cmp-diff` に `tr.row.changed` が描かれ、`tr.row.same` が無いこと。

---

## G. 依頼者への質問

| # | 論点 | 私の推奨 |
| --- | --- | --- |
| G1 | 未知の id の番号（指示書 §2-8）。`/api/compare` は 404 で仕様どおり。`/api/groups/{id}/compare` の「まとまりに無い id → 422」をそのまま仕様にするか、未知の id だけ 404 に分けるか（C8） | **422 のまま**で、`details.extra`（所属しない）と `details.unknown`（存在しない）を分けて返す。設計 §3.2 に 1 行書く |
| G2 | 捕獲していない画像の `final_prompt` を「前置語だけ」にするか、`None` にして前置語を別の鍵で出すか（B2） | **`None`＋別の鍵**。「分からない」を「同じ」に見せない |
| G3 | 語順だけの違いを**行**でも `moved` にするか（C2）。`comparison.md` §3.2 は語の話とも行の話とも読める | 行にも出す（`reweighted` と同じ扱い） |
| G4 | `textgen_system_prompt` と `en_source` を鍵に足すか（C4）。設計 §0.6 は 5 つに絞った | 足す。`analyze_graph` が既に返していて「発明」にならない |
| G5 | 基準の切替の操作（C1）。`b` キーだけか、タイルの番号クリックも付けるか | 両方。マウスだけで完結させる決定（`comparison.md` §6 `:192`）に合わせる |
| G6 | 9 枚以上のまとまりの `GET /api/groups/{id}/compare` の既定（C7）。422 のままか、先頭 8 枚か | 先頭 8 枚＋`truncated` |

---

## H. 私が確かめられなかったこと

**実行はゼロ。** 以下を依頼者側で打てば白黒が付く。番号は指示書 §2 の番号ではなく本文の参照用。すべて `cd C:\work\image-reviwer` と `$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"` の後に打つ。

### H-1 テスト（127 件）

```powershell
uv run pytest -q
uv run pytest -q tests/test_compare.py -v
```

期待: 127 passed（`test_real_assets_…` は `.data/db.sqlite3` が無ければ skip）。

### H-2 サーバと画面

```powershell
uv run image-reviewer serve --port 8792
```

別の窓で:

```powershell
$base = "http://127.0.0.1:8792"
$ids = ((Invoke-RestMethod "$base/api/assets?provenance=with&limit=8").items | ForEach-Object id) -join ','
Measure-Command { Invoke-RestMethod "$base/api/compare?ids=$ids" } | ForEach-Object TotalMilliseconds
Start-Process "$base/#/compare?ids=$ids"
```

画面で見ること: (1) 下の表に「違い」「重み」「一部のみ」のバッジの行だけが出て、「同じ N 行は畳んであります」がある。(2) ホイールで 1 枚を拡大すると 8 枚が追従し、ドラッグで全部が動く。(3) 「同期ズーム」を押して切ると 1 枚だけ動く。(4) `m` と「同じ行」で畳んだ行が開く。(5) DevTools で `.cmp-frame img` の computed `object-fit` が `contain`。(6) 上の 1 行が「同一 seed」か「seed が違うので画素は別物」か。(7) **基準を変える操作が無い**こと（C1）。`#/compare?ids=…&base=<3 番目の id>` を手で開くと「基準 3 番」になる。

### H-3 差分表の時間（B1。§8 の 30ms）

次を `C:\work\bench_compare.py`（**リポジトリの外**）に保存して `uv run python C:\work\bench_compare.py`:

```python
import random, time
from image_reviewer import compare

def item(i, words):
    meta = {"model": "m", "seed": str(i), "steps": 10, "cfg": 1.0,
            "final_prompt": ", ".join(words), "final_prompt_source": "png_literal",
            "node_types": {"KSampler": 1, "SaveImage": 1}}
    return compare.asset_item({"id": f"{i:026d}", "meta": meta, "width": 1024,
                               "height": 1024, "review_state": "unreviewed"})

for n_words in (20, 60, 200):
    base = [f"tag{k}" for k in range(n_words)]
    shuffled = []
    appended = []
    for i in range(8):
        w = base[:]
        random.Random(i).shuffle(w)
        shuffled.append(item(i, w))
        appended.append(item(i, base + [f"extra{i}"]))
    for name, items in (("語順をシャッフル", shuffled), ("1 語ずつ追加", appended)):
        t = time.perf_counter()
        compare.build_document(items)
        print(f"8 枚 × {n_words} 語（{name}）: {(time.perf_counter() - t) * 1000:.1f} ms")
```

判定: 60 語で 30ms を超えれば B1 の再現。`_union_tokens` を直した後に同じスクリプトで桁が落ちることを見る。

### H-4 実データで `final_prompt` の行（B2）と 8 枚の組み立て

同じく `C:\work\probe_compare.py` に保存して `uv run python C:\work\probe_compare.py`（**読み取り専用**で開く。DB は書かない）:

```python
import json, sqlite3, time
from image_reviewer import compare

con = sqlite3.connect("file:C:/work/image-reviwer/.data/db.sqlite3?mode=ro", uri=True)
con.row_factory = sqlite3.Row
rows = con.execute(
    "SELECT a.id, a.width, a.height, a.review_state, m.meta_json FROM asset a"
    " JOIN asset_meta m ON m.asset_id = a.id WHERE m.meta_json <> 'null' LIMIT 8").fetchall()
items = [compare.asset_item({"id": r["id"], "meta": json.loads(r["meta_json"]),
                             "width": r["width"], "height": r["height"],
                             "review_state": r["review_state"]}) for r in rows]
t = time.perf_counter()
doc = compare.build_document(items)
print(f"{len(items)} 枚: {(time.perf_counter() - t) * 1000:.1f} ms")
print("changed:", [r["key"] for r in doc["diff"]["changed"]])
print("same   :", [r["key"] for r in doc["diff"]["same"]])
fp = next(r for r in doc["diff"]["changed"] + doc["diff"]["same"] if r["key"] == "final_prompt")
print("final_prompt:", fp["state"], [(v or "")[:40] for v in fp["values"]])
print("final_prompt_source:", [i["prompts"]["final_prompt_source"] for i in items])
print("ja_text が違う枚数:", len({i["prompts"]["ja_text"] for i in items}))
```

判定: `final_prompt_source` が `reconstructed` なのに `values` が前置語だけで `state == "same"`、かつ `ja_text` が違う枚数が 2 以上なら B2 の再現。

### H-5 404 と 422（C8）

```powershell
$base = "http://127.0.0.1:8792"
$a = (Invoke-RestMethod "$base/api/assets?limit=2").items[0].id
curl.exe -s -o NUL -w "%{http_code}`n" "$base/api/compare?ids=$a,nope"       # 期待 404
curl.exe -s -o NUL -w "%{http_code}`n" "$base/api/compare?ids=nope"          # 422（1 枚）
curl.exe -s -o NUL -w "%{http_code}`n" "$base/api/compare?ids=$a&ids=nope"   # 422（最後の 1 つしか読まない）
$g = (Invoke-RestMethod -Method Post "$base/api/groups" -ContentType "application/json" -Body (@{asset_ids=@($a)} | ConvertTo-Json)).id
curl.exe -s -w "`n%{http_code}`n" "$base/api/groups/$g/compare?ids=$a,nope"  # 422 と details.extra
```

### H-6 403

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" -H "Host: evil.example" "$base/api/compare?ids=$a,$a"            # 403
curl.exe -s -o NUL -w "%{http_code}`n" -H "Origin: http://evil.example" -X POST "$base/api/compare"      # 403
curl.exe -s -o NUL -w "%{http_code}`n" -H "Content-Type: text/plain" -X POST -d "{}" "$base/api/compare" # 403
```

### H-7 読んでいないもの

`docs/frontend-design.md`、`docs/design.md`、`src/image_reviewer/thumbs.py`、`src/image_reviewer/api/{reviews,export}.py`、`schemas/review-export.schema.json`、`tools/probe_p5.py`。P5-2 の範囲に直接は関係しない。

---

## 最も重大な 3 件

### 1. 語の union が、基準の語数 × 画像数だけ LCS を回し直す（B1。**実装者が気づいていない**）

`_union_tokens` は基準の語ごとに全画像との `diff_sequence` を呼び直すが、同じ結果は 10 行上の `build_prompt_diff` が画像ごとに 1 回計算して捨てている。計算量は語数の 3 乗に近く語数の上限も無いので、§8「30ms」はプロンプトが 60 語を超えたあたりで守れなくなる見込みで、テストは 2〜3 語しか使わないので緑のまま。直し方は `item_states` を渡すだけで、§H-3 のスクリプトで前後の桁が分かる。

### 2. 捕獲していない画像の「最終プロンプト」に前置語だけを入れる（B2。**実装者が気づいていない**）

`analyze_graph` は英訳を捕獲していない再構成の画像で `final_prompt=None` を返すが、`compare.py` はそれを前置語（品質語）で埋める。実データ（英訳を持つのは 263 枚中 1 枚）の比較では `final_prompt` の行がほぼ常に「同じ」と出て、日本語原文が違っても最終プロンプトが同じに見える。「分からない」を「同じ」に見せているので差分表を既定にした意味が最初の行で崩れ、実データのテストは隣の `en_text` の行しか見ていない。

### 3. 画面に基準を変える口が無い（C1。点検 C10 の予言どおり）

API は `?base=` に追従しテストもそれを守るが、画面には `b` キーもタイルのクリックもボタンも無く、URL を手で書くしかない。点検 C10 は「実装者が 1 番目を基準に決め打ちし、`b` キーが効かない」と書き、設計はそれを API の形で引き取ったが画面の操作は誰も引き取らなかった。8 枚から 1 枚を選ぶ作業で「3 番から見た差」が出せないのは、`comparison.md` §6 の「キーが無いとできない操作は作らない」より手前の「操作そのものが無い」状態である。
