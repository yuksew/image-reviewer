# P5-3 実装の監査報告

- 監査した版: 2026-10-15 の作業ツリー（コミット無し）。読んだもの: `src/image_reviewer/{compare,thumbs,store,db,app}.py`、`api/{__init__,compare}.py`、`review.py:270-330`、`apps/gui/{compare.js,index.html,styles.css}`、`tools/{gui_smoke.mjs,probe_p5.py}`、`tests/{test_p5_3,test_compare,test_db,conftest}.py`、`pyproject.toml`、`uv.lock`（先頭 320 行）、`README.md`、`docs/{p5-3-audit-brief,p5-design,comparison,p5-review-report,p5-audit-report,p5-2-audit-report}.md`。
- **実行できたかどうか: 何も実行できていない。** `PowerShell`・`Bash`・`Glob` / `Grep`（`rg`）のすべてが `EPERM: operation not permitted, uv_spawn` で拒否された（過去 2 回と同じ）。したがって **`pytest`・サーバの起動・実データ（`.data/db.sqlite3` は二進ファイルで `Read` では読めない）・`node tools/gui_smoke.mjs`・ブラウザ・計測・`tests/.tmp` の個数はいずれも「実行していない」**。`tests/.tmp` は `Read` が `EISDIR` を返したので**フォルダとして存在する**ことだけ分かった（中身の個数は不明）。以下はすべてコードを読んで推論した結果で、§H に依頼者がそのまま打てる確認手順を置いた。
- テスト件数は**ソースを読んで数えた 163 件**（`test_p5_3.py` 23 ＋ README の 140）。指示書の「163 件が通るはず」と一致する。通るかどうかは確かめていない。
- 総合判定: **条件つきで使える。** pHash / dHash がサムネイルの復号に同居する形、`comparison_cache` の点検 D1、錠の下の読み、`force` の経路、`object-fit: contain`、依存の増分は設計どおり。ただし **(1) 比較画面のヒートマップの包みとタイルを隠す仕組み（`hidden`）が CSS に打ち消されていて、空の帯が常に出る／タイルが隠れない。しかも意図どおり隠れたら今度は「強制して出す」がマウスで届かない**、**(2) 位置合わせの「峰が弱い＝別の絵」の判定が実質死んでいて、`force` した無関係な 2 枚に「合わせた」と言って無意味な絵を返す**、**(3) 比較の文書はサムネイルより先に作られるので、既存 263 枚では画面を開いただけでは似ている順もヒートマップの自動有効も出ない**（依頼者の実測どおり）の 3 点は使う前に直す必要がある。

---

## A. 設計の主張が成り立たない（必ず直す）

| # | 場所 | 問題 | 利用者の側で何が起きるか | 再現手順 / 確認手順 | 提案 |
| --- | --- | --- | --- | --- | --- |
| **A1** | `apps/gui/styles.css:259-262`（`.cmp-heatwrap { display: flex; … }`）、`:209-212`（`.cmp-stage { display: flex; … }`）、`styles.css` 全体に **`[hidden]` の規則が無い**、`apps/gui/index.html:76`（`<div class="cmp-heatwrap" id="cmp-heatwrap" hidden>`）、`apps/gui/compare.js:503`（`wrap.hidden = !state.heat`）、`:533-539`（`renderHeat`: `wrap.hidden` / `stage.hidden = true`「ヒートマップを見ている間はタイルを隠す」）、`:487-493`（`heatLine`: 出せない組では `#cmp-heat` を `disabled`、`#cmp-heatforce` の `hidden` を外す）、`:559-572`（`openHeat`: 出せない組では置き場の `state.heat` を作って包みを開く）、`:739`（`openHeat` へ入る経路は **`d` キーの `toggleHeat()` だけ**）、`:790-793`（`#cmp-heat` の click は `showHeat(false)`。`disabled` なら発火しない） | **2 段の問題。(a) `hidden` 属性は UA の `[hidden] { display: none }` で効くが、作者の `display: flex` が同じ要素にあると打ち消される**（作者の宣言が UA の宣言に勝つ。詳細度は関係ない）。`.cmp-heatwrap` と `.cmp-stage` は両方 `display: flex` なので、`compare.js` が `hidden` を立てても**包みは隠れず、タイルも隠れない**。結果、比較画面には**常に**ヒートマップの帯（「—」・空の指標・「閉じる」）と空の絵の領域が出て、`.cmp-stage` と `.cmp-heatwrap` が `flex: 1 1 auto` を分け合うのでタイルの高さが半分になる。ヒートマップを出してもタイルは隠れず、下に並ぶ。`#cmp-heatforce`（`<button>`。作者の `display` 無し）だけは `hidden` が効くので、出せない組では**常に見えている帯の中に**「強制して出す」が現れ、押せる。**(b) 意図どおりに `hidden` を効かせると（`[hidden]` の規則を足すと）、今度は出せない組で「強制して出す」にマウスだけでは到達できない。** ボタンは `disabled`、強制の口は `state.heat` が無いと隠れる包みの中、包みを開くのは `d` キーだけ。設計 §0.5 G6「条件の外でも利用者が押せば出す」と `comparison.md` §6「キーが無いとできない操作は作らない」に反する | (a) 今: 比較画面の下半分が空の帯で埋まり、「閉じる」を押しても消えない。ヒートマップを出すとタイルの下に絵が足される。(b) 直した後: 遠い組（実データでは pHash 未計算の組がほぼ全部。B1）で差分を見たい人は、ヘルプの `d` を読まない限り何もできない | **実行していない。** §H-3（ブラウザで開いて、初回に空の帯が出ているかを見る。出ていなければ `d` を押さずに「強制して出す」が見えるかを見る）。`tools/gui_smoke.mjs` は CSS を持たないので (a) を見られず、`:284-290` は `dispatchKey('d')` の**後**に `cmp-heatforce.hidden === false` を見るだけなので (b) も通る | (a) `styles.css` に `[hidden] { display: none !important; }` を足す（または `hidden` を使わずクラスで切り替える）。(b) 同時に、`#cmp-heat` を `disabled` にせず（見た目は `aria-disabled`）click を `toggleHeat()` に結ぶか、`#cmp-heatforce` を `#cmp-heatwhy`（`index.html:87`）の隣へ出して出せない組では常に見せる。`gui_smoke.mjs` に「`d` を押さずに `cmp-heat.dispatch('click')` → `cmp-heatwrap.hidden === false`」を足す |
| **A2** | `src/image_reviewer/compare.py:92`（`ALIGN_MIN_PEAK_RATIO = 1.5`）、`:1209`（`ratio = corr.max() / abs(corr).mean()`）、`:1214-1216`（この比で「別の絵の可能性が高い」を返す） | **「峰が弱い」の判定が実質働かない。** 位相相関は正規化した相互パワースペクトル（全周波数で振幅 1）の逆 FFT なので、全体のエネルギーは 1 に固定される。**無関係な 2 枚**では `corr` が約 N（256×192 ≒ 5 万）点に散ったノイズになり、`max / mean(|corr|)` は**ガウス雑音の最大値 / 平均絶対値 ≒ 4〜6** に落ち着く（推論。実測していない）。同じ絵なら比は数百〜数万（`gui_smoke.mjs:178` の fixture が `peak_ratio: 120.5` を置いているのと整合）。**1.5 はノイズの比より下**なので、ほぼ一様な絵（`cross` が 0 に潰れる）以外では決して発火しない。残る守りは `ALIGN_MAX_SHIFT`（`:1210`）だけ | `force=True` で無関係な 2 枚（seed も絵も別）を出すと、ノイズの最大点が ±64px に入れば `aligned: true`・`dx/dy` にでたらめな値・全面が赤の絵が返る。`comparison.md` §2.3「ずれが大きいときは『位置が合いません』と出す（黙って誤魔化さない）」の主張が、**ずれが大きくない「別の絵」で**崩れる。画面は `ずれ dx×dy px` をそのまま出す（`compare.js:525`） | **実行していない。** §H-4 の読み取り専用スクリプト（実データの無関係な 30 組と同じ seed の組で `_phase_shift` の `peak_ratio` を印字）。無関係な組の最小値が 1.5 を超えていれば再現。コード上の再現: `test_a_forced_far_pair_with_a_large_shift…`（`tests/test_p5_3.py:500-522`）は**ずらした写し**（峰が強い）で `ALIGN_MAX_SHIFT` の枝だけを通す。**無関係な 2 枚**（独立な乱数の絵）で `build_heatmap` を呼ぶテストが無い | §H-4 の分布から閾値を決め（同じ seed の組の最小値と無関係な組の最大値の間。余裕を見て 10〜50 のどこか）、`p5-design.md` §0.7 に実測として書く。「無関係な 2 枚 → `available: False` かつ理由に『手がかりが弱い』」のテストを足す（今の 1.5 では落ちる＝この指摘の証明になる） |

---

## B. 重大（静かに間違える・遅い）

| # | 場所 | 問題 | 利用者の側で何が起きるか | 再現手順 / 確認手順 | 提案 |
| --- | --- | --- | --- | --- | --- |
| **B1** | `compare.py:1415-1425`（`compare_assets` は `store.asset()` の列を写すだけで復号しない）、`:455-456`（`asset_item` は `asset.phash` をそのまま）、`:872-874`（`nearest` と `pairs` はこの時点の値で決まる）、`app.py:201-222`（ハッシュが埋まるのは **`/thumb` の要求のとき**だけ）、`compare.js:108`（画面は先に `/api/compare` を取り、`<img src=thumb>` はその描画の後） | **既存の 263 枚では、比較の文書が pHash 無しで組まれる。** `/api/compare` の応答が先、サムネイルの要求（＝ハッシュの計算）はその後なので、`nearest.distances` は全部 `null`、同じ seed でない組の `pairs[].heatmap` は全部「pHash もまだ計算されていません（サムネイルを開くと計算されます）」になる。サムネイルは画面に見えているのにこの文言が出る。**再読み込みすると直る**（2 回目は列に入っている）。指示書 §2-2 の「画面を開いただけでは正しく出ない」が**そのとおり起きる**。遅延で埋める設計自体は妥当（背景ジョブは要らない。1 枚 14 ms）だが、**埋める場所がサムネイルだけ**なのが足りない | 「似ている順」に切り替えても入力順のまま、距離も出ない。ヒートマップは同じ seed の組以外すべて無効。利用者は再読み込みを知らない | **実行していない。** §H-2: 未計算の枚を SQL で選び、起動直後に `GET /api/compare?ids=a,b` → `nearest.distances` が `null` → `GET /api/assets/{a,b}/thumb?size=256` → もう一度 `GET /api/compare` → 距離が入る | `compare_assets()` で、`phash` が無く実体がある枚について **錠の外で** `ensure_hashes()` を呼んでから文書を組む（最大 8 枚 × 約 14 ms。1 枚につき生涯 1 回）。起動時の全件（263 枚で 3.7 秒、1 万枚で 2.3 分）は `serve` を止めるので採らない。`cli` の 1 回限りの口は任意 |
| **B2** | `compare.py:1000-1008`（`reduced_gray` は **`_primary_path` ＝原本** を `Image.open` する）、`:1295-1300`（`pair_report` は 1 組につき原本を 2 枚復号）、`:1104-1108`（指標だけの要求も原本）、`comparison.md:236`（「比較のために**原本を開かない**」）、`:231`（「差分ヒートマップ 50ms 以内 — 256px に縮小して numpy」） | **ヒートマップと指標が、毎回 2 枚の原本を復号している。** 指示書 §2-7 の実測（1024² 26 ms / 2048² 83 ms）は numpy ではなく **PNG の復号**で、原本の画素数に比例する（約 20 ms/MP/枚 × 2 枚）。`comparison.md` §7 の「原本を開かない」に反し、50ms の目標は 1024² でも 2 枚で届かない。256 のサムネイル（`thumbs.thumb_path(data_dir, sha256, 256)`）は**既に長辺 256 の縮小**（`thumbs.py:61` と `compare.py:1007` は同じ `thumbnail((256,256), LANCZOS)`）なので、それを読めば 1 枚 1 ms 程度で済む | ヒートマップを押すたび（保存しないので毎回）に 50〜170 ms。2048² の絵では目標の 3 倍 | **実行していない。** §H-5 の計測（`reduced_gray` を原本と 256 サムネで 10 回ずつ）。指示書の実測で既に判明している | `pair_report` / `cached_pair_metrics` の入力を「256 のサムネイル（無ければ `ensure_thumb` で作る＝同じ復号でハッシュも入る）」にする。WebP（q82）は非可逆なので指標がわずかに変わる → `ALGO_VERSION` を上げる（そのための版）。原本を正とするなら、§7 を「復号を除いて 50ms。復号込みは原本の画素数に比例」に書き直す（§E の 7） |

---

## C. 中程度

| # | 場所 | 問題 | 利用者の側で何が起きるか | 再現手順 | 提案 |
| --- | --- | --- | --- | --- | --- |
| **C1** | `db.py:275-286`（`comparison_cache.algo_version`）、`:300-304`（`asset.phash` / `dhash` には版が無い）、`compare.py:72-74`（`ALGO_VERSION` の注記は「縮小のフィルタや指標の式」） | 点検 D1 の「版を上げたら古い値が混ざらない」は **`comparison_cache` だけ**に効く。`asset.phash` / `dhash` は 16 進 16 文字のまま残り、ハッシュの作り方（フィルタ、縮小の段数、入力をサムネイルにする B2 の提案）を変えると**旧版と新版のハッシュが同じ列に混ざり、距離が静かに狂う**。消す口も無い | 作り方を変えた後、以前に埋まった枚と新しく埋まった枚の「似ている順」が意味を失う。気づく手段が無い | `ALGO_VERSION` を上げても `asset.phash` は残る（`test_the_metrics_cache_is_used…` は `comparison_cache` しか見ない） | `asset.hash_version INTEGER` を足して読むときに条件に入れるか、`HASH_VERSION` を上げたマイグレーションで `UPDATE asset SET phash = NULL, dhash = NULL` を行う（再計算は B1 の口が拾う） |
| **C2** | `compare.js:748-751`（`1`〜`8` は `state.doc.items[n-1]` ＝**サーバの順**）、`:266`（タイルの番号は**表示の順**）、`:404, 428, 446`（語の差分・日本語原文の行番号は `state.doc.ids.indexOf` ＝サーバの順）、`:325-327`（表の列は表示の順） | P5-3 で並び順（seed 順 / 似ている順）が入ったので、**番号が 2 系統に割れた。** 似ている順で `3` を押すと「3」と書かれたタイルとは別の枚が選ばれ、語の差分の「2 番」は表の 2 列目と別の枚を指す。入力順ではたまたま一致するので `gui_smoke.mjs:240-243` は通る | 基準から 2 番目に近い枚を `2` で選んだつもりが、入力順の 2 番が選ばれて差分の相手が変わる | `#/compare?ids=a,b,c` で `r` を 2 回（似ている順）→ `3` を押す → 選択の枠が「3」の番号のタイルに付かない組がある（距離順が入力順と違うとき） | 番号を `orderedIds()` の 1 か所に寄せる（キーは `orderedIds()[n-1]`、語の差分の行番号も `orderedIds().indexOf`） |
| **C3** | `compare.py:1011-1015`（指標は `_common_frame` ＝左上の重なり）、`:1158-1172`（ヒートマップは右下を 0 で埋めてマスク）、`:1029`（SSIM は位置合わせ前） | **指標とヒートマップが別の領域・別の位置合わせで計算される。** (a) 縦横比が違う 2 枚では指標は左上の共通部分（縦 145×256 と横 256×145 なら 145×145 の角）だけで数え、絵は全体を出す。数値が何の値か分からない。(b) ずれた組では絵は位置合わせ後（赤が少ない）、横の数値は位置合わせ前（`変化 95%`）。`comparison.md` §2.3 の手順 4「併せて数値を出す」は、画面で**同じ 1 行**に並ぶ | 「赤はほとんど無いのに変化 95%」を見て、どちらを信じるか分からない | 縦横比の違う 2 枚で `POST /api/compare/pair` → `ssim` が返るが、何の領域かは応答に無い。`shifted(pattern(1), 30, 0)` の組で `changed_fraction` と絵を並べる | (a) 縮小後の形が違う組は指標を `null` にして `reason` を返す（「縦横比が違う」）。(b) `build_heatmap` が既に持つ `delta`（マスク内）から `aligned_changed_fraction` / `aligned_mean_abs` を返し、ヒートマップの行には**位置合わせ後**を、表の値には**前**を出す。§6 の答えと一緒に §E の 6 |
| **C4** | `compare.py:919, 928`（`phash_bits` と `dhash_bits` が**それぞれ**全解像度から `convert("L")` ＋ LANCZOS）、`thumbs.py:39`（「費用の 96% は復号」）、`p5-design.md:102`（§0.7 F5: DCT 0.53 ms）、`:29`（§0.1 P5-3 の完了条件「pHash の実測を記録する」） | 依頼者の実測（復号 11.4 / 復号＋両ハッシュ 14.1 / 復号済みから 2.38 ms）と設計の前提（DCT 0.53 ms）が**4.5 倍**ずれている。原因は DCT ではなく、全解像度のグレースケール化と LANCZOS の縮小を**2 回**やり直していること（1 MP → 32×32 の LANCZOS は横の 1 段で 32×H×96 回の積和）。復号の割合は 96% ではなく 81%。そして**この実装後の実測はどの文書にも無い**（§0.7 は実装前の 11.88 / 11.35 / 0.53 のまま）。P5-3 の完了条件が文書上は満たされていない | 263 枚で 0.5 秒の差。費用そのものより、「実測で前提を変えた」と書いた設計が実装後の数字を持っていないこと | `tools/probe_p5.py` の 4 番（`probe_phash_p5_3`）を実行し、§0.7 の表と比べる | `gray = im.convert("L")` を 1 回にし、`gray.thumbnail((256,256))` を経由してから 32×32 と 9×8 を作る（`reduced_gray` と同じ縮小を共有すれば B2 とも揃う。値は変わるので C1 の版と一緒に）。実測を §0.7 に 1 行足す |
| **C5** | `compare.py:1148-1151`（理由の文言「サムネイルを開くと計算されます」） | B1 のとおり、この文言が出るのは**サムネイルが画面に見えているとき**。利用者には意味が通らない | 「開いているのに」で止まる | B1 の再現と同じ | B1 を直せば出番はほぼ消える。残す場合は「再読み込みすると計算されます」 |
| **C6** | `tests/test_p5_3.py:670-697`（v3 の移行テスト）、`:674-675`（`DDL` を流して `user_version = 2` と**書くだけ**）、`db.py:260-268`（v2 の列は `_migrate_v2` が足す） | **「v2 の DB」が v2 ではない。** `DDL` だけの表は `review_group` に `reason_code_id` / `decision` / `note` を持たない（v1 の形）。版を 2 と書いたので `migrate()` は v2 の手当てを飛ばし、v3 だけ当てる。結果の DB は v2 の列を持たないが、テストはそれを見ないので緑。指示書 §2-11「v1 から一気に上げても同じ結果になるか」は、`test_db.py:204-232` が v2 の列まで、このテストが v3 の列までを**別々の DB で**見るだけで、**v1 → v3 を 1 回で上げて両方の列が揃うこと**はどこにも固定されていない。コード（`db.py:238-244`）は正しく続けて当てるはずだが、テストは守っていない | 将来 `migrate()` の順序や `current < 3` の条件を壊しても緑のまま | `test_migration_v3…` の fixture を `DDL` → `_migrate_v2` → `user_version=2` にするか、v1 から上げて `{reason_code_id, decision, note, phash, dhash}` と `comparison_cache` を 1 つのテストで見る | 同左。あわせて「新規作成（`open_db`）と v1 からの更新で `PRAGMA table_info(asset)` の列の並びが同じ」を 1 行足す |

**確かめた結果、問題なし（コード上。実行はしていない）**:

- §2-1 **同じ復号に載っている**: `thumbs.ensure_thumb` は `im.convert("RGB")` の直後・`thumbnail` の前に `on_image(im)` を呼ぶ（`thumbs.py:55-61`）。`app.get_thumb` は `on_image=lambda im: compare.capture_hashes(store, asset_id, im)` を渡し（`app.py:211-213`）、`capture_hashes` は復号しない（`compare.py:965-979`）。**背景ジョブにしない判断は正しい**（1 枚 14 ms で、要求の中で終わる）。
- §2-1 **サムネイルが既にある枚の経路が 1 回で終わる**: `get_thumb` は `asset.phash is None` のとき `ensure_hashes` を呼び（`app.py:218-222`）、`ensure_hashes` は錠の下で列を見て、**あれば復号しない**（`compare.py:988-991`）。サムネイル生成の直後に呼ばれても（`asset` の dict が古い）SELECT 1 回で `None` を返す。復号が増え続ける経路は無い。`on_image` の例外はサムネイルを落とさない（`thumbs.py:57-60`）。
- §2-3 **点検 D1**: `comparison_cache` に `phash_distance` 列は無く、索引は主キーだけ（`db.py:275-286`）。読むときの `WHERE … AND algo_version = ?`（`compare.py:1094-1099`）、書くときの upsert（`:1109-1118`）。`hash_distance` はその場で出す（`:952-962`）。`tests/test_p5_3.py:293-334` が列・索引・版またぎの 3 つを固定している。
- §2-4 **監査 B3**: `pair_report` の `store.asset()` は `store.locked()` の下（`compare.py:1272-1273`）、`cached_pair_metrics` の SELECT は `locked()`、INSERT は `transaction()`（`:1094, 1109`）、復号と SSIM は錠の外（`:1104-1108`）。`capture_hashes` / `ensure_hashes` も同じ（`:971, 988`）。`compare_assets` は P5-2 のまま錠の下（`:1418`）。`api/compare.py` は接続に触らない。**新しい読みが錠の外で接続を触る経路は無い**（ただしそれを守るテストは無い。§F-1）。
- §2-5 **G6 の規則**: `heatmap_enabled` の条件は「同じ seed」と「距離 ≤ 閾値」の 2 つだけ（`compare.py:1146-1153`）。「派生関係」は無い。閾値は `HEATMAP_DISTANCE_THRESHOLD = PHASH_NEAR_THRESHOLD`（`:79-83`）の 1 か所で、理由の文言も画面もこの値を写す（`:1150, 1155`、`compare.js:496-497`。画面に `6` は書かれていない）。`force` は `pair_report` で `enabled or force`（`:1295, 1304`）。`ALIGN_MAX_SHIFT` を超えるずれは画像を返さない（`:1210-1213`、`tests/test_p5_3.py:445-458, 500-522`）。
- §2-5 **位置合わせの符号**: `shifted(+30)` → 峰は `dx = -24`（`tests/test_p5_3.py:441-442`）、`_shift(pb, dy, dx)` は b の中身を `-24` 動かして戻す（`compare.py:1242`）。位相相関の定義どおりで、符号は合っている（ただし戻した結果の差が小さいことは誰も見ていない。§F-4）。
- §2-9 **画面**: `object-fit` は `styles.css:104, 219, 280, 303` のすべてが `contain`（`cover` は無い）。基準の変更（`compare.js:300-312`、ボタン `:267-270, 285-288`）と同期ズーム（`:638-655, 673-714`）は P5-2 のまま。理由は `#cmp-heatwhy` に常に 1 行（`index.html:87`、`compare.js:494-498`）。並び順はボタン `#cmp-order` でも回る（`:788-789`）。
- §2-10 **依存**: `pyproject.toml:13` に増えたのは `numpy>=1.26` だけ。`uv.lock:126-149` の `image-reviewer` は `numpy` を依存に持ち、`requires-dist` も `numpy>=1.26`、`numpy 2.5.4`（`:166-168`）が解決されている。dev 群は変わっていない。整合している。
- §2-11 **移行 v3**: `_migrate_v3` は `PRAGMA table_info(asset)` を見てから列を足す（`db.py:300-304`）。`migrate()` は `current < 2` → `current < 3` と続けて当て、最後に版を書く（`:241-245`）。途中で落ちても再実行で同じ状態になる。実データの v3 は依頼者の確認どおり。
- §2-12 **前回までの修正**: 監査 B1（`item_states` を渡す。`compare.py:724-725, 743-756`）、B2（`final_prompt_unknown` / `known_prefix`。`:388-405, 568-576`）、C1（基準のボタン。`compare.js:267-270, 300-312`）は残っている。`app.py:53-55` は `ReviewService` → `flush_dirty()` の順（監査 C3）、`lifespan` で `flush()`（監査 A1）。`review.py` / `export.py` の本文は今回読んでいない（P5-3 の変更が触っていないため）。`conftest.py:49-63, 80-90` は残骸があれば落とす形のまま。

---

## D. 軽微

確認はいずれも引用行を読めば足りる。

| # | 場所 | 問題 | 提案 |
| --- | --- | --- | --- |
| D1 | `tools/gui_smoke.mjs:211` | `tileHtml[0].includes('is-base') === false \|\| true` は恒真。何も確かめていない行が「ok」と印字される | 削る |
| D2 | `gui_smoke.mjs:58-61, 85-86`（`querySelector` は選択子ごとに作り物を 1 つ返す。`document.querySelector` は `null`）、CSS を持たない | `select()` の枠の付け替え（`compare.js:666-668`）と `applyView` は何も起きない。選択の印・`transform`・**`hidden` が CSS に打ち消されること（A1-(a)）**・親の `hidden` の継承は守られていない | 「見ていないもの」に「選択の印、`hidden` と CSS の関係」を足す |
| D3 | `compare.py:1069-1077` ↔ `app.py:108-115` | `_primary_path` が 2 か所に同じ規則で書かれている | `compare._primary_path` を `app.py` から使う |
| D4 | `compare.py:1269-1276`（`a_id == b_id` を弾かない） | 自分との比較が通り、`comparison_cache(a, a)` に行ができ、ヒートマップは自分自身 | 422 |
| D5 | `compare.py:1296-1298`（実体が無いとき `reason` を入れる）→ `:1302`（直後の `cached_pair_metrics` が 404 を投げる） | `reason` の代入は到達しない（死んだ分岐） | 404 で統一し、代入を消す |
| D6 | `app.py:201-222` ＋ 比較画面（`compare.js:264` の 1024 と `:327` の 256 を**同時に**要求） | 既存の枚では 256 が既にあり 1024 が無いので、256 の要求が `ensure_hashes` で原本を 1 回、1024 の要求が `ensure_thumb` でもう 1 回復号する。1 枚につき 1 度きりの競合（害は無い） | B1 の口で先に埋めれば消える |
| D7 | `compare.py:926-930`（dHash を計算して保存）↔ 使う所が無い（`hash_distance` は pHash だけ、`nearest_order` / `heatmap_enabled` も pHash だけ） | `comparison.md` §4「pHash の補助」の補助先が無い。費用は 0.1 ms なので実害は無い | 使い道（重複 P8）までは「保存だけ」と書く |
| D8 | `compare.py:1005-1007`（`thumbnail` は拡大しない） | 長辺 256 未満の絵は元の大きさのまま。相手が 256 なら `_common_frame` が**別の縮尺**を重ねる。実データは 768 以上なので今は起きない | 縮小後の形が違えば指標を `null`（C3-(a)） |
| D9 | `db.py:275-286`（`CREATE TABLE IF NOT EXISTS comparison_cache`） | 設計 §2（`p5-design.md:160-166`）の形で先に作られた表があれば（`phash_distance` 列・`ix_comparison_a`）そのまま残り、`INSERT` の列指定は通るので気づかない | v3 の手当てで `PRAGMA table_info(comparison_cache)` に `algo_version` が無ければ作り直す |
| D10 | `tests/test_p5_3.py:744, 750` / `test_compare.py:573`（`len(rows) >= 263`、実体 10 枚以上） | 実データの枚数に結びついたテスト。利用者が画像を消すと落ちる | 「1 枚以上」に緩める |
| D11 | `index.html:12`（「比較（並べる / 来歴の差分表 / 同期ズーム）まで」）、`README.md:13, 23`（「P5-2 が動く。テスト 140 件」） | P5-3 を反映していない | 更新 |
| D12 | `compare.py:1283-1290`（`peak_ratio` を応答に出す）↔ `compare.js:516-527`（出さない） | A2 を直す前に、画面で比を見られると調整の助けになる | `metricsLine` に `峰 ×N` を足す（任意） |

---

## E. 設計・`comparison.md` とのずれ

前回までの監査（`p5-audit-report.md` §E、`p5-2-audit-report.md` §E）で挙げたものは繰り返さない。

| 項目 | 状態 | 場所・根拠 |
| --- | --- | --- |
| **§0.1 P5-3 の完了条件**「近い組でヒートマップが出る」 | **反映（API）／半分（画面）** | 近い組（同じ seed か距離 ≤ 6）は `enabled` で画像が返る（`compare.py:1281-1309`）。画面は B1 のとおり初回は距離が無く、A1-(a) のとおり帯が常に出る |
| **§0.1 P5-3 の完了条件**「pHash の実測を記録する」 | **未反映** | §0.7 は実装前の値。実装後の 11.4 / 14.1 / 2.38 はどの文書にも無い（C4） |
| **§0.5 G6**「条件の外でも利用者が押せば出す」 | **反映（API・キー）／偶然（マウス）** | A1。`hidden` が効いていないせいで今は押せるが、意図した形では押せない |
| **§0.5 G6**「派生関係は P7 まで外す」 | **反映** | `compare.py:1140-1141`。ただし `comparison.md:70-73` は 4 条件のまま（「一方が他方から派生」が残っている）。`comparison.md` 側に「P7 まで外す」が無い |
| **§0.7 F5**「サムネイルと同じ復号で計算」 | **反映** | `thumbs.py:56-60`、`app.py:211-213` |
| **§0.8 D1**（`phash_distance` / `ix_comparison_a` を作らない、`algo_version`） | **反映（DB）／未反映（設計本文）** | `db.py:275-286`。`p5-design.md:160-166` の DDL は `phash_distance` と `ix_comparison_a` を持ったまま（§0 が正と冒頭にあるので矛盾扱いにはしないが、§2 の DDL を読んだ人は旧形を作る。D9） |
| **§6.2 の表**「phash / dhash は走査の背景ジョブ（8ms/枚）」 | **本文が古い** | §0.7 で取り消し済み。表は未修正 |
| **§6.2**「`POST /api/groups/{id}/compare/pair {a_id, b_id}`」 | **反映＋別解** | `api/compare.py:65-85`。まとまり無しの `POST /api/compare/pair` も足した（点検 C9 と同じ理由。妥当） |
| **§6.2**「ssim / changed_fraction / mean_abs は**近い組のときだけ**」 | **別解** | `pair_report` は遠い組でも指標を返す（`compare.py:1302`、テスト `:491-492`「無駄に隠さない」）。遠い組でも原本 2 枚を復号する（B2）。設計の「近い組だけ」は費用の話だったので、B2 を直すなら別解でよい |
| **§8**「SSIM（1 組）50ms 以内」 | **出所が誤り（点検 E3 のまま）** | `comparison.md` §7 に SSIM の行は無い。50ms はヒートマップの行 |
| **`comparison.md` §2.3 手順 4 と §4（指示書 §2-6）** | **実装が §4 に従い、§2.3 と食い違う** | §4（`comparison.md:161`）は「§2.3 の手順 **1・3**」と書き、手順 2（位置合わせ）を**意図的に飛ばして**いる。§2.3 の手順 4（`:82`）は手順 2 の後に置かれ、位置合わせ後と読める。**§4 が正**（指示書の言うとおり定義は §4）。理由: 指標は再現の検証と準重複の確定に使う（§4 の表）ので、**ずれは差として数えるべき**（ずれた再現は再現ではない）。また指標は遠い組・位置合わせ不能の組でも返るので、位置合わせに依存させると未定義になる。**直し方（1 行）**: §2.3 手順 4 を「併せて数値を出す。**指標は手順 1 の縮小（位置合わせ前）から計算し、手順 2 は表示の絵だけに掛ける**（定義は §4）」に書き換える。画面の見え方の問題は C3-(b) |
| **`comparison.md` §7「差分ヒートマップ 50ms 以内 — 256px に縮小して numpy」（指示書 §2-7）** | **前提が抜けている** | 50ms は numpy の部分（256px の FFT・差・合成で数 ms）の話で、**復号を含めていない**。実装は原本を開く（B2）ので、復号が 1024² で 26 ms / 2048² で 83 ms と原本の画素数に比例し、目標を外す。**直し方**: 行を「差分ヒートマップ: **縮小済みの 2 枚から** 10 ms 以内（256px の numpy）。**復号は含めない**（256 サムネイルを入力にすれば 1 枚 1 ms 程度。原本を開けば画素数に比例し、1024² で 26 ms / 2048² で 83 ms）」に分けて書く。あわせて `:236` の「原本を開かない」を実装が守るか（B2 の提案）、外すかを決める |
| **`comparison.md` §7 pHash の行**「8ms/枚（未計測）… この値の出所はこの行 1 か所」「登録時に背景で」 | **古い** | 実測は `p5-design.md` §0.7 にあり、出所は 2 か所になった。「背景で」は取り消された。`:238` も同じ |
| **`comparison.md` §4.1 / §6**（`r` で 3 つの順、`d` でヒートマップ） | **反映** | `compare.js:28-32, 739-740` |
| **`comparison.md` §6**「キーが無いとできない操作は作らない」 | **意図した形では未反映（強制して出す）** | A1-(b) |
| **`comparison.md` §2.3**「ずれが大きいときは『位置が合いません』（黙って誤魔化さない）」 | **半分** | 大きいずれは反映。別の絵（峰が弱い）は判定が死んでいる（A2） |
| **`comparison.md` §4** pHash / dHash / SSIM の定義 | **反映** | `compare.py:914-930`（32×32 → DCT → 低周波 8×8 → 中央値、9×8 → 横の増減）、`:1026-1039`（256px → 局所平均・分散・共分散。窓は重なり無しの 8×8 と注記あり）。`changed_fraction` の閾値 8 と `mean_abs` は増幅前（`:1042-1052`、増幅は `:1246` の表示だけ） |
| **`comparison.md` §4「色ヒストグラム距離」** | **未実装（記載なし）** | §4 の表の 4 行目。P5-3 の範囲に含めるとも外すとも書かれていない。P8 で要るなら「後で」と 1 行 |

---

## F. テストが守っていないもの

| # | テスト | 何を主張しているか | 実際に守っているか | 直し方 |
| --- | --- | --- | --- | --- |
| **F1** | `tests/test_p5_3.py:365-402` `test_the_pair_metrics_do_not_read_uncommitted_rows` | 「監査 B3: キャッシュの読みは錠の下（未コミットの行を読まない）」 | **守っていない。** 単一スレッドで、乗っ取った `compute_pair_metrics` の中で未コミット行を作って ROLLBACK するが、**キャッシュの読み（`:1094`）はその前に終わっている**。docstring 自身が「読むのは計算の前なので、取引中に読まない」と認めている。`cached_pair_metrics` から `with store.locked()` を外しても緑。守っているのは「ROLLBACK した行が残らない」だけ | 別スレッドで `store.transaction()` を開いて未コミット行を入れたまま 0.5 秒待ち、主スレッドの `pair_report` が**その間ブロックされ**（`locked()` が錠を待つ）、取引が ROLLBACK された後に `cached: False` で計算することを時間で見る。同一接続なので錠が無ければ未コミット行がそのまま見える |
| **F2** | `tests/test_p5_3.py:670-697` `test_migration_v3_upgrades_a_v2_database_in_place` | 「v2 の DB をその場で v3 に」 | **fixture が v2 ではない**（C6）。v1 → v3 を 1 回で上げて v2・v3 の列が揃うことはどこにも無い | C6 |
| **F3** | （無い） | `comparison.md` §2.3「別の絵では『位置が合いません』」 | **無関係な 2 枚**で `build_heatmap` を呼ぶテストが無い。`:500-522` はずらした写し（峰が強い）。足すと今の 1.5 では落ちる（A2） | 独立な乱数の絵 2 枚で `available is False` かつ `"手がかりが弱い" in reason` |
| **F4** | `tests/test_p5_3.py:427-442` `test_a_near_pair_produces_an_image_and_a_shifted_pair_is_aligned` | 「少しずれた組は**位置合わせしてから**重ねる」 | `dx` の符号と大きさは見るが、**戻した結果の差が小さいこと**は見ない。`_shift` の符号を逆にしても `dx` は同じ値で緑（絵は全面が赤になる） | `build_heatmap` が位置合わせ後の `mean_abs`（マスク内）を返すようにし（C3-(b)）、ずらした写しで小さいことを固定する |
| **F5** | `tests/test_p5_3.py:461-497`（`same_seed` の組） | 「同じ seed で条件が開く」 | 守っている。ただし `near` は 240×180 の JPEG で、256×192 の相手と**縮尺が違う**（D8）のに `available is True` が通る。これは A2 の「峰が弱くても通る」の副産物で、このテストは縮尺の違いを「合った」と言っている | D8 を直せばこの組は `available False` になるので、`near` を同じ大きさの再圧縮に変える |
| **F6** | （無い） | §0.1「近い組でヒートマップが出る」を**画面を開いただけで** | 初回の `/api/compare` でハッシュが入っていること（B1）を見るテストが無い。足すと落ちる | `app_client` で登録 → サムネイルを取らずに `GET /api/compare` → `items[].phash` が入り `nearest.distances` が `null` でない |
| **F7** | `tools/gui_smoke.mjs:272-311` | 「出せない組で強制の口が残る」「ヒートマップを見ている間はタイルを隠す」 | **CSS を持たない**ので、`hidden` が `display: flex` に打ち消されること（A1-(a)）は見えない。「強制の口」は `d` の後だけ見るので、意図した形での未到達（A1-(b)）も通る。`:211` は恒真（D1）。`node` 依存で `pytest` からは走らない | A1 の 1 行を足す。`hidden` の検査は「`display` を持つ要素に `hidden` を使わない」の静的な検査（`styles.css` に `[hidden]` があるか）に置き換える。`pytest` から `subprocess` で呼ぶか、走らせ方を README に書く |
| **F8** | `tests/test_p5_3.py:748-751`（`1`〜`8` の割り当て） | — | 並び順を変えた後のキー → タイル（C2）を見るテストは無い（smoke も入力順だけ） | 似ている順にしてから `3` → 選ばれる id が `orderedIds()[2]` |

**守っているもの（指示書 §2-8 の 3 件と C15）**:

- 「復号 1 回でハッシュ」: `tests/test_p5_3.py:188-220` は `PIL.Image.open` を数え、`thumbs.py` と `compare.py` は `from PIL import Image` 経由で呼ぶので差し替えが効く。`capture_hashes` を `hash_file(src)` に変えると 2 回になって落ちる。`:223-245` はサムネイルがある枚の 1 回だけの復号と、2 回目の 0 回を固定する。**守っている。**
- 「縮小が画像ごとに 1 回」: `:337-362` は `compare.reduced_gray` を数え、`pair_report` → `build_heatmap(gray=…)` の共有を外すと 4 回になって落ちる。**守っている。**
- 「未コミット行を読まない」: **守っていない**（F1）。
- pHash の**絶対値**（C15）: 実画像のハッシュ値を書いたテストは無い。`:154-163` は性質（写しは ≤ 6、別の絵は > 18）、`:473-475, 535-536, 584-586` は手で入れた値で順序と規則だけを見る。**守っている。**
- `algo_version` を引くときも条件に入れる: `:316-321` は `ALGO_VERSION` を上げて再計算されることを見る。SELECT から `AND algo_version = ?` を外すと落ちる。**守っている。**

**今すぐ要るのに無いテスト**: F1 の作り直し、F2、F3、F4、F6、F8。

---

## G. 依頼者への質問

| # | 論点 | 私の推奨 |
| --- | --- | --- |
| G1 | ヒートマップと指標の入力を **256 のサムネイル（WebP q82・非可逆）** にするか、原本のままにして §7 の目標を「復号を除く」に書き直すか（B2） | サムネイルにする。「原本を開かない」の方針どおりで、復号が 1 ms に落ちる。`ALGO_VERSION` を 2 にする |
| G2 | 既存 263 枚のハッシュをどこで埋めるか（B1）。比較の要求時（≤ 8 枚）／起動時の全件（3.7 秒）／`cli` の 1 回限り | 比較の要求時。起動時は `serve` を止め、規模に比例する |
| G3 | `asset.phash` / `dhash` に版を持つか、版を上げたときに `NULL` に戻すか（C1） | `NULL` に戻す（列を増やさない。再計算は B1 の口が拾う） |
| G4 | 位置合わせの「峰が弱い」閾値（A2）。実データで分布を取ってから決めるか、`peak_ratio` を応答に残すだけにして P7 まで待つか | 分布を取って決め、§0.7 に書く。`force` が無意味な絵を返すのは G6 の意味を損なう |
| G5 | 指標の位置合わせ（§2-6）。§4（位置合わせ前）を正とし §2.3 を直すか、§2.3 を正とし指標を位置合わせ後にするか | §4 を正。画面のヒートマップの行だけ位置合わせ後の値を別に出す（C3-(b)） |
| G6 | 「強制して出す」の置き場（A1-(b)）。`#cmp-heat` を無効にしないか、強制の口を `#cmp-heatwhy` の隣に常に出すか | 後者。理由の 1 行の隣に「それでも出す」があるのが素直。`hidden` の打ち消し（A1-(a)）は `[hidden] { display: none !important }` の 1 行で先に直す |

---

## H. 私が確かめられなかったこと（＋依頼者が打てる確認手順）

**実行はゼロ。** すべて `cd C:\work\image-reviwer` と `$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"` の後に打つ。サーバを上げたまま `uv sync` を打たない（`os error 32`）。実データは**読み取り専用**で開く。

### H-1 テスト（163 件）と `tests/.tmp`

```powershell
(Get-ChildItem tests\.tmp -ErrorAction SilentlyContinue | Measure-Object).Count   # 前の残骸
uv run pytest -q
(Get-ChildItem tests\.tmp | Measure-Object).Count
uv run pytest -q
(Get-ChildItem tests\.tmp | Measure-Object).Count
uv run pytest -q tests/test_p5_3.py -v -s | Select-String "実測"
```

期待: 2 回とも `163 passed`、`.tmp` の個数が 2 回の前後で増えない。最後の行は `test_real_assets…` の実測（復号込み / ハッシュだけ）。

### H-2 初回の比較文書に pHash が無い（B1）

P5-3 を入れてから 256 のサムネイルを 1 度でも要求した枚は既にハッシュを持つので、**先に未計算の枚を SQL で選ぶ**（seed が違う 2 枚）:

```powershell
uv run python -c "import sqlite3,json;c=sqlite3.connect('file:.data/db.sqlite3?mode=ro',uri=True);print(c.execute('select count(*) from asset where phash is null').fetchone());[print(r) for r in c.execute(\"select a.id, json_extract(m.meta_json,'$.seed') from asset a join asset_meta m on m.asset_id=a.id where a.phash is null and m.meta_json<>'null' limit 6\")]"
uv run image-reviewer serve --port 8794
```

別の窓で（`$a` / `$b` に上の 2 つの id を入れる）:

```powershell
$base = "http://127.0.0.1:8794"
(Invoke-RestMethod "$base/api/compare?ids=$a,$b").nearest.distances          # 期待（今のコード）: b が null
(Invoke-RestMethod "$base/api/compare?ids=$a,$b").pairs[0].heatmap            # reason に「pHash もまだ計算されていません」
Invoke-WebRequest "$base/api/assets/$a/thumb?size=256" -OutFile $env:TEMP\a.webp
Invoke-WebRequest "$base/api/assets/$b/thumb?size=256" -OutFile $env:TEMP\b.webp
(Invoke-RestMethod "$base/api/compare?ids=$a,$b").nearest.distances          # 距離が入る
```

### H-3 ヒートマップの包みと「強制して出す」（A1）

`$base/#/compare?ids=$a,$b` を開く（H-2 の `a`・`b`。同じ seed でない組）。**キーボードに触らずに**:

1. 初回の画面に、タイルの下に**空のヒートマップの帯**（「—」・「閉じる」）と空の領域が出ていて、タイルの高さがその分縮んでいるか。**コード上の予測: 出ている可能性が高い**（`hidden` が `display: flex` に打ち消される）。出ていれば A1-(a) の再現。DevTools で `#cmp-heatwrap` の computed `display` が `flex` なら確定。
2. 帯が出ていれば、その中に「強制して出す」が見えて押せるはず（偶然の経路）。押して差分が出るか。
3. 帯が出ていなければ（`[hidden]` が効いている環境）、「差分ヒートマップ」ボタンが押せず、「強制して出す」がどこにも無いこと（A1-(b)）。`d` を押すと現れる。
4. ついでに `r` を 2 回押して「似ている順」にし、`3` を押す → 枠が付くタイルの番号が「3」か（C2）。

### H-4 位相相関の峰の比（A2）

`C:\work\probe_peak.py`（**リポジトリの外**）に保存して `uv run python C:\work\probe_peak.py`:

```python
import itertools, json, random, sqlite3
from pathlib import Path
from image_reviewer import compare

con = sqlite3.connect("file:C:/work/image-reviwer/.data/db.sqlite3?mode=ro", uri=True)
con.row_factory = sqlite3.Row
rows = [r for r in con.execute(
    "SELECT a.id, l.display_path, m.meta_json FROM asset a"
    " JOIN asset_location l ON l.asset_id = a.id AND l.missing_at IS NULL"
    " LEFT JOIN asset_meta m ON m.asset_id = a.id ORDER BY l.is_primary DESC, a.id")
    if Path(r["display_path"]).exists()]
seen, assets = set(), []
for r in rows:
    if r["id"] in seen:
        continue
    seen.add(r["id"])
    meta = json.loads(r["meta_json"]) if r["meta_json"] else {}
    assets.append((r["id"], r["display_path"], (meta or {}).get("seed")))
gray = {}
def g(a):
    if a[0] not in gray:
        gray[a[0]] = compare.reduced_gray(a[1])
    return gray[a[0]]
def ratio(a, b):
    pa, pb, _, _ = compare._pad_pair(g(a), g(b))
    return compare._phase_shift(pa, pb)

random.seed(0)
unrelated = [ratio(a, b) for a, b in (random.sample(assets, 2) for _ in range(30))]
by_seed = {}
for a in assets:
    if a[2]:
        by_seed.setdefault(a[2], []).append(a)
same = [ratio(x, y) for group in by_seed.values() if len(group) > 1
        for x, y in itertools.combinations(group[:3], 2)]
print("無関係 30 組: peak_ratio 最小 %.2f / 中央 %.2f / 最大 %.2f, ok(=合わせた扱い) %d 組" % (
    min(r["peak_ratio"] for r in unrelated),
    sorted(r["peak_ratio"] for r in unrelated)[len(unrelated) // 2],
    max(r["peak_ratio"] for r in unrelated), sum(r["ok"] for r in unrelated)))
print("無関係で ok になった組の dx,dy:", [(r["dx"], r["dy"]) for r in unrelated if r["ok"]][:10])
if same:
    print("同じ seed %d 組: peak_ratio 最小 %.2f / 最大 %.2f" % (
        len(same), min(r["peak_ratio"] for r in same), max(r["peak_ratio"] for r in same)))
print("閾値 ALIGN_MIN_PEAK_RATIO =", compare.ALIGN_MIN_PEAK_RATIO)
```

判定: 無関係な組の `peak_ratio` の最小値が `1.5` を超え、`ok` の組が 0 でなければ A2 の再現（その組は `force` で「合わせた」絵を返す）。同じ seed の組の最小値と無関係な組の最大値の間に閾値を置く。

### H-5 ヒートマップの費用の内訳（B2・§2-7）

```python
# C:\work\probe_heat.py
import time
from pathlib import Path
from image_reviewer import compare, thumbs
import sqlite3
con = sqlite3.connect("file:C:/work/image-reviwer/.data/db.sqlite3?mode=ro", uri=True)
con.row_factory = sqlite3.Row
r = con.execute("SELECT a.sha256, l.display_path FROM asset a JOIN asset_location l ON l.asset_id=a.id"
                " WHERE l.missing_at IS NULL LIMIT 1").fetchone()
orig = Path(r["display_path"]); thumb = thumbs.thumb_path("C:/work/image-reviwer/.data", r["sha256"], 256)
def ms(fn, n=10):
    fn(); t = time.perf_counter(); [fn() for _ in range(n)]; return (time.perf_counter() - t) / n * 1000
print("原本 -> 256 gray :", round(ms(lambda: compare.reduced_gray(orig)), 1), "ms")
if thumb.exists():
    print("256 サムネ -> gray:", round(ms(lambda: compare.reduced_gray(thumb)), 1), "ms")
ga = compare.reduced_gray(orig)
print("numpy だけ（FFT+差+合成）:", round(ms(lambda: compare.build_heatmap(orig, orig, gray=(ga, ga))), 1), "ms")
```

判定: 「原本 → 256」が 20 ms 以上、「サムネ → gray」が数 ms 以下、「numpy だけ」が 10 ms 以下なら、§7 の 50ms を外しているのは復号で、B2 の提案で収まる。

### H-6 ハッシュの実測を記録する（C4・§0.1 の完了条件）

```powershell
uv run python tools/probe_p5.py --images 50 | Select-String -Context 0,8 "P5-3"
```

出た「復号のみ / 復号＋pHash＋dHash / 復号済みから」を `p5-design.md` §0.7 の表に足す。

### H-7 `gui_smoke.mjs`

```powershell
node tools/gui_smoke.mjs
```

期待: 「すべて ok」。ただし A1 / C2 / D1 / D2 はこれでは見えない（§F-7）。

### H-8 読んでいないもの

`src/image_reviewer/{review,export,scan,cli,png_meta,capture}.py` の本文（P5-3 の変更対象外）、`apps/gui/app.js`、`tests/{test_review,test_export,test_store_sqlite,test_prototype}.py`、`uv.lock` の 320 行目以降、`docs/design.md`、`docs/frontend-design.md`。

---

## 最も重大な 3 件

### 1. 比較画面の `hidden` が CSS に打ち消されていて、空のヒートマップの帯が常に出る。直すと今度は「強制して出す」がマウスで届かない（A1。**実装者が気づいていない**）

`.cmp-heatwrap` と `.cmp-stage` は `display: flex` を持ち、`styles.css` に `[hidden]` の規則が無いので、`compare.js` が `hidden` を立てても UA の `display: none` は作者の宣言に負けて効かない。比較画面には初回から空の帯（「—」・「閉じる」）が出てタイルの高さを半分に取り、ヒートマップを出してもタイルは隠れない。「強制して出す」はこの帯の中に偶然見えている。`[hidden] { display: none !important }` の 1 行で意図どおり隠すと、出せない組のボタンは `disabled`、強制の口は `d` キーでしか開かない包みの中になり、G6 と `comparison.md` §6「キーが無いとできない操作は作らない」に反する。両方を同時に直す（`#cmp-heat` の click を `toggleHeat()` に、または強制の口を理由の行の隣へ）。`gui_smoke.mjs` は CSS を持たず `d` を押してから確かめるので、どちらも見えない。§H-3 でブラウザを開くだけで白黒が付く。

### 2. 位置合わせの「別の絵」判定が死んでいて、`force` が無意味な絵を「合わせた」と言って返す（A2。**実装者が気づいていない**）

位相相関の正規化スペクトルはエネルギーが 1 に固定されるので、無関係な 2 枚でも `max / mean(|corr|)` は 4〜6 程度になり、閾値 1.5 は決して割り込まない。残る守りは「ずれが 64px を超える」だけで、ノイズの最大点が ±64px に入れば `aligned: true`・でたらめな `dx/dy`・全面が赤の絵が返る。`comparison.md` §2.3「黙って誤魔化さない」の主張が、まさに `force` の使い所（遠い組）で崩れる。テストはずらした写しで `ALIGN_MAX_SHIFT` の枝だけを通し、無関係な 2 枚のテストは無い。§H-4 のスクリプトで分布を取れば閾値が決まる。

### 3. 比較の文書がサムネイルより先に作られ、既存 263 枚では「似ている順」も自動有効も初回に出ない（B1）

ハッシュをサムネイルの復号に同居させた判断は実測どおり正しいが、埋める口がサムネイルだけなので、`/api/compare` の応答（距離と規則）はサムネイルの要求より先に確定する。依頼者の実測（`items[].phash` が null、理由が「pHash もまだ計算されていません」）はこの順序そのものである。再読み込みで直るのは、裏で 1024 のサムネイルがハッシュを埋めたからで、画面はそれを知らない。`compare_assets()` で足りない枚だけ錠の外で `ensure_hashes()` を呼べば、最大 8 枚 × 14 ms を 1 度払うだけで「画面を開いただけで正しく出る」になる。起動時の全件（3.7 秒）は規模に比例するので採らない。
