# P6-2（注記と切り出し）監査報告 — 実行込み

- 日付: 2026-10-16（05:36〜06:05）
- 監査者: Fable（Claude Code）
- 指示書: `docs/p6-audit-brief-p6-2.md`　実装の記録: `docs/p6-2-implementation.md`
- 対象: `src/image_reviewer/annotations.py`（05:20 版）、`src/image_reviewer/api/annotations.py`（05:20）、`apps/gui/annotations.js` / `app.js` / `group.js` / `styles.css`（**05:41〜05:42 版**）、`tests/test_annotations.py`（05:24）、`tools/gui_smoke.mjs`（05:45）、`tools/probe_p6_2.py`（05:32）、`schemas/annotation-export.schema.json`（04:48）
- 環境: `IMAGE_REVIEWER_DATA=.tmp-audit-redo/data-p52`（v4 の写し）をポート 8791 で。実データ `.data/` は `mode=ro` だけで触った（`db.sqlite3` の mtime は 10-15 14:29 のまま）。画面は Chrome headless（CDP、1400×900 と 1920×1080）。一時物は `.tmp-audit-redo/p6/`（`p62_api.py` / `p62_inproc.py` / `page_anno.js` / `page_g2z.js` / `page_num.js` / `page_pos.js` と出力・画面写真）
- ソースと既存の文書は編集していない。

> **注意（監査中にソースが変わった）**: 指示書（05:35）と実装の記録（05:34）より後、監査の最中に `annotations.js` / `app.js` / `group.js` / `styles.css`（05:41〜42）と `gui_smoke.mjs`（05:45）が書き換えられた。この報告の画面の結果は **05:42 版**で取ったもの。実装の記録が「穴」としている group_id の引き継ぎは、この版で**すでに塞がれている**（§F-3）。サーバ側（`annotations.py` など）は監査の間ずっと 05:20 版。

---

## A. 判定

**合格の線 3 は通った。切り出しの式・GET が書かない・原子性・actor と 404/403・領域なし・契約も実行で確認した。**
ただし、**実装者の申告に無いバグが 3 件**見つかった（下の上位 3）。いずれも直し方は小さい。

| # | 内容 | 重さ |
|---|---|---|
| 1 | **右端・下端ぴったりの注記で切り出しが 500**。`x=1-1e-12, w=1e-12`（`x+w=1`）は作成 201 だが `GET /crop` と `POST export` が `ValueError: cannot write empty image` で 500。`crop_box` の `left == width` のときクランプが潰れる（§C-2） | 高（500 を出す） |
| 2 | **領域なしが混ざる 422 の `details.annotation_id` が id でなく文言**（`annotations.py` 287-288 行と 331-332 行）。画面の「切り出しを書き出す」は `annotation_ids` を送らないので、**メモが 1 件あるだけで画像全体の書き出しが「切る範囲がありません」で止まり、どれが原因か分からない**。`tools/probe_p6_2.py` が 422 で落ちたのもこれ（§C-6） | 高（導線が止まる） |
| 3 | **画像の上の番号と一覧の番号がずれる**（メモが間にあると）。一覧は全件の index、画像の印は `shape` 付きだけの index。一覧「3: 楕円」に画像の印は「2」（§C-8）。実装者が申告した穴 2 より悪い | 中 |

合格の線（指示書 §1）の自分の手での確認は §B。実装者の判断 7 点への意見は §D、未実装 2 点と穴 3 件は §F。

---

## B. 合格の線（自分の手で）

### 線 3（1024×1024 と 2048×1536、`{x:0.25,y:0.5,w:0.25,h:0.25}`）

実データには **2048×1536 が無い**（263 枚すべて正方形）ので、HTTP は 1024² と 2048²、2048×1536 は `crop_box` と合成画像で通した。

| 画像 | 作成 | GET json の座標 | `image` | POST crops | 実ファイル | 期待 |
|---|---|---|---|---|---|---|
| 1024² `…9ZXHHW` | 201 | `(0.25, 0.5, 0.25, 0.25)` そのまま | 1024×1024 | 256×256 left=256 top=512 | PNG 256×256 | 256×256 ✔ |
| 2048² `…TKSM75` | 201 | 同上 | 2048×2048 | 512×512 left=512 top=1024 | PNG 512×512 | 512×512 ✔ |
| 2048×1536（合成） | — | — | — | `crop_box` → (512, 768, 1024, 1152) | Pillow で切って 512×384 | 512×384 ✔ |
| 1536×2048（合成） | — | — | — | (384, 1024, 768, 1536) | 384×512 | ✔ |

- 丸めなしの往復: `x=0.123456789` を作って GET → `0.123456789` のまま（SQLite の REAL は倍精度）。
- GET の `crops` は `null`、POST は配列。両方を本物の `jsonschema`（Draft 2020-12）で `annotation-export.schema.json` に通して OK（§C-7）。
- 実装者の `tools/probe_p6_2.py` も、**注記が白紙の画像でなら** 1024² / 2048² / 1536² ぜんぶ ok（§C-6 に落ちる条件）。

---

## C. 実行の記録

### C-1. 回帰
- `uv run pytest -q`: **222 passed**（2 回。`tests/.tmp` の残骸 18 個は監査前（05:21〜22、実装者の実行）のもので、私の実行では増えていない）。
- `node tools/gui_smoke.mjs`（05:45 版）: **87 ok**。ただし 1 回だけ `--base http://…` を付けて呼んだ実行が Node の native スタック（V8）を吐いて落ちた。引数なしで 2 回とも通ったので再現せず。記録だけ。
- `tools/gui_layout.mjs --count 8` と `--screen requests`: すべて ok（比較・要求の一覧に退行なし）。
- `tools/check_contract_p6.py`: すべて OK。

### C-2. 切り出しの式（`round(v,6)` → floor / ceil）

| 入力 | 結果 | 備考 |
|---|---|---|
| 1360² `x=0, w=0.275`（HTTP、実画像 `…MZGTFJ`） | **374 px**（crop GET も 374×136） | `0.275*1360 = 374.00000000000006`。`round` 無しなら ceil で 375 |
| `x=0.1, w=0.2`（1000 px） | right=300 | `(0.1+0.2)*1000 = 300.00000000000006` も 300 に |
| `x=0.7, w=0.3`（`x+w=1.0`） | 201、right=1024 | 境界ぴったりは通る |
| `x+w = 1+1e-9` | 201、right=1024 | EPS の内側 |
| `x+w = 1+1e-7` | 422 | EPS の外側 |
| `w=0` / `x=1.0, w=0.001` | 422 / 422 | |
| `x=0.5, w=1e-10`（right ≤ left） | (512, 512, 513, 513) → 1 画素 | クランプが効く |
| **`x=1-1e-12, w=1e-12`（`x+w=1`）** | **(1024, 0, 1024, 1024) → 幅 0** | **作成は 201、crop GET と POST export は 500**（`PIL … cannot write empty image`、`server-p62.log`）。y 軸も同じ |
| 1024² `x=y=0.999, w=h=0.001` | 2×2 | floor(1022.976)=1022、ceil(1024)=1024 |

幅 0 の原因: `left = min(floor(round(x*W,6)), W)` が `W` になると、`right = min(W, left+1) = W` で `right == left` のまま。`left` を `W-1`（`top` を `H-1`）までに抑えるか、作成時に `floor(round(x*W,6)) >= W` を 422 にする。`tests/test_annotations.py` のクランプの試験は `left == W` を踏んでいない。失敗しても `.tmp` は残らなかった（§C-4）。

座標の検証: `shape` 無し＋座標あり 422、`w` だけ欠け 422、`shape=circle` 422、空の POST 422（§A1 の「全部か無しか」）。

### C-3. GET は書かない

- `GET …/annotations/export?format=json`: 200、`crops: null`。`annotations/` 配下のファイル一覧（名前・mtime・size）は前後で**同一**（×3 回）。
- `GET …/export?format=crops`: **422** `{"format": "切り出しの書き出しは POST を使ってください"}`。
- `GET /api/annotations/{id}/crop`: 200 `image/png`（1536² の `w=0.5` → 768×768）、ディスクのファイル一覧は不変（その場で作って返すだけ）。
- GET export の `image` は DB の width/height 由来。実体の無い asset（§C-5）でも GET json は 200。

### C-4. 原子性・起動時の掃除・DELETE
- プロセス内で `os.replace` を `OSError("disk full")` に差し替えて `export_doc(with_crops=True)`: 例外が上がり、`*.tmp` は **0 個**、PNG も作られない。
- 同じ id で POST export を 2 回: ファイル数 8 → 8、名前同じ、mtime は 8 件とも更新（上書きで増えない）。
- 起動時の掃除: `app.py` 66-67 行で `AnnotationService(store).clean_stale_tmp()` を呼んでいる。写しに `annotations/<asset>/zz.png.1.2.tmp` を置いてサーバを再起動 → **消えた**。プロセス内でも 2 階層の `.tmp` が消え、`.tmp` で終わらない `keep.tmp.png` は残る（誤爆なし）。
- `DELETE /api/annotations/{id}`: 200、`annotations/<asset>/<asset>__<id>.png` が消える。2 回目は **404**。

### C-5. actor・権限・領域なし・他画像・実体なし

| 試み | 結果 |
|---|---|
| actor `robot` で POST | 422 |
| agent が human の注記を PATCH / DELETE | 403 / 403 |
| human 自身の PATCH（body） | 200。`shape` を PATCH しようとすると 422（body だけ） |
| 領域なしのメモ `{"body": …}` | 201、`shape: null`。その `/crop` は 422 |
| 領域なしを含む画像の POST crops（ids 無し） | **422 全体**（決定 3）。`annotation_ids` で印だけ指定すれば 200 |
| 他画像の id を `annotation_ids` に | 422 `details.extra: [その id]` |
| 他のまとまりの `group_id` を付けて作成 | 422 |
| 実体の無い asset（写し DB に行を足した） | 作成 201、GET json 200、POST crops **409** `asset_file_missing`、crop GET 409 |
| client_token の再送 | 200（テスト済み。HTTP でも 2 回目が同じ id） |

### C-6. `tools/probe_p6_2.py` が 422 で落ちた理由
`id_of()` が大きさごとに**最初の 1 枚**を選び、`{"format": "crops"}` を `annotation_ids` 無しで送る。その画像に**領域なしのメモが 1 件でもあると**決定 3 で 422（`{"detail":"切る範囲がありません","details":{"annotation_id":"切る範囲がありません"}}`）。1 回目は data-p52 に実装者が残していた 1024² のメモ（「この 1 枚は構図は良い。手だけ直したい」）、2 回目は私の画面試験が 1536² に残したメモが原因。白紙にすると「すべて ok」。probe は**冪等でない**（自分が作った注記も消さない）ので、同じ写しで 2 回目以降は落ちやすい。

### C-7. 契約
- `annotation-export.schema.json` に GET（`crops: null`）と POST（`crops: [...]`）の 4 文書を `jsonschema` で検証: **すべて OK**。`additionalProperties: false`。
- 否定: `annotations[].x = 2` → 落ちる（`maximum 1`）。`crops[].extra` → 落ちる。
- `$defs.Annotation` は **`review-export.schema.json` の `Annotation` と description 以外で完全一致**（required、座標の `["number","null"]`、`shape` の enum）。
- `crops[]` は `annotation_id / path / left / top / width / height / bytes`。POST export の応答は契約の文書そのもの（決定 2）。

### C-8. 画面（Chrome headless、05:42 版の JS）

**4 px の規則（本物の MouseEvent）**
| ドラッグ | POST |
|---|---|
| 「見るだけ」のまま 90 px | 0（下書きも出ない） |
| 3 px | 0、文言「小さすぎるので作りませんでした（4 px 以上で囲んでください）」 |
| 幅 3.9 px × 高 40 px | 0（片方が 4 未満なら作らない） |
| 4 px | **1**（`{"shape":"rect","x":0.0317…,"w":0.0127…,"group_id":null}`） |
| Shift + 100×60 px | 1（`shape: ellipse`、select も楕円に） |
| 押したまま画像の外へ（mouseleave） | 0、下書きが消える |
| 右下の角を越えてドラッグ | 1、`x+w = 1.0` に収まる（`Math.min(1-x, …)`） |

**20 件の一覧と印**（1536²、矩形/楕円 19 件＋メモ 1 件）
- 一覧 20 行、画像の印 19 個。印は**すべて画像の矩形の内側**（`getBoundingClientRect` で 19/19）。行の横あふれ無し（`white-space: nowrap` の手当てが効いている）。
- 一覧は `#detail`（`overflow-y: auto`、高さ 795 px）の中で縦に伸びる。ページ自体はあふれない（`documentElement.scrollHeight == innerHeight`）。
- **番号のずれ**（`page_num.js`、1024²）: 矩形 → メモ → 楕円 の順に作ると、一覧は `1:矩形 / 2:メモ / 3:楕円`、画像の印は `1 / 2`。**楕円は一覧で 3、画像で 2**。メモの行にも「切り出し」リンクが出て、押すと 422。
- 「切り出しを書き出す」（メモが混ざる）: 画面の文言は「書き出せません: 切る範囲がありません」。19 件の印は 1 枚も書かれない。
- 「消す」: 行が 20 → 19、文言「消しました」。「座標 JSON」: `GET …/export` 1 回だけ（書かない）。別の画像へ移ると舞台・箱・一覧はそれぞれ 1 つ（重複なし）。

**注記の入口の位置**（1024² の普通の画像、`page_pos.js`）
| ビューポート | 画像の表示幅 | 4 px ＝ 元画像の | 注記の箱の位置（#detail の先頭から） | スクロール無しで見える |
|---|---|---|---|---|
| 1400×900 | 315 px | 約 13 px | 2665 px（見出し: 来歴 373 / タグ 793 / ワークフロー 2489 / 注記 2787） | **いいえ** |
| 1920×1080 | 315 px | 約 13 px | 2665 px | **いいえ** |

`#/asset/<id>` は右の列（340 px）の詳細にそのまま注記の箱を**末尾に足す**ので、来歴の長い画像では 2700 px ほど下。「拡大」と呼ぶには画像が小さく（315 px）、4 px の閾値は元画像の 13 px に相当する。

**まとまりレビュー → 拡大 → 印 → 決める**（`page_g2z.js`、新しい要求 `…MVQ10`）
- 「選んだ 1 枚を拡大で開く」→ hash は `#/asset/<id>?group=<gid>`。`pathOf` が `?` 以降を落とすので詳細は正しく開く。
- 拡大で印を付けると POST body に **`group_id` が入る**（`setAnnotationGroup`）。`response.annotations` は決める前は `null`、決めた後は **その印の id を含む**（`containsZoomMark: true`）。
- API 側: `group_id` 付きの注記は `response.annotations` に入り、無しは入らない（`p62_api.py` §6）。

### C-9. 性能（HTTP 込み、keep-alive なし、5 回の中央値、`compress_level=1`）

| 画像 | crop GET 全面 | crop GET 1/4 辺 | POST export 2 枚 | 全面 PNG |
|---|---|---|---|---|
| 1024² | 44 ms | 11 ms | 46 ms | 1288 KB |
| 2048² | 170 ms | 43 ms | 155 ms | 5718 KB |

面積比 4 で時間比 3.9〜4.0。比例していて、P6-1a の接続設立（~20 ms）を引けば 1024² 全面は 25 ms 程度。

---

## D. 実装者の判断（7 点）への意見

| # | 判断 | 意見 |
|---|---|---|
| 1 | export json の `image` は DB の width/height | **賛成**。実体が無くても GET json が 200 で返るのを確認。実体と DB が食い違う（再生成で大きさが変わった）場合は切り出しがずれるが、それは P4 の再走査の責任 |
| 2 | POST export の応答は契約の文書（`{"files":[…]}` でなく） | **賛成**。1 つの形で済む。`docs/p6-design.md` §3.6 のスケッチは `files` のままなので直す（§E-1） |
| 3 | 領域なしが混ざると **全体を 422** | **変えることを勧める**。画面が `annotation_ids` を送らないので、メモ 1 件で書き出しの導線が止まる（§C-8）。しかも `details.annotation_id` が id でない（上位 2）。案: サービス側で `shape` 無しを**黙って飛ばし**、`crops` に出さない（契約は変えずに済む）。全部飛ばして 0 枚なら 422。画面側で印の id だけ送る案は、API を直接叩くエージェントが同じ罠を踏むので弱い |
| 4 | `annotation_ids` は その asset のものだけ、違えば 422 `details.extra` | **賛成**。確認済み |
| 5 | PATCH は body だけ、DELETE は PNG も黙って消す | **賛成**。座標を変えるなら作り直し、が設計の線（§0.7）。DELETE の 2 回目 404 も良い |
| 6 | actor の検査はサービス層 | **賛成**。`_require_own` が PATCH / DELETE 両方で 403。`robot` は 422（P6-1a の直し）が注記でも効いている |
| 7 | 注記の UI は `#detail` の中 | **条件付き**。動くが、**入口が来歴の下 2700 px**（§C-8）。設計 §5.3 の「拡大の画面」は別の画面を想定していた。少なくとも注記の箱を画像の直下（来歴の前）に置く |

---

## E. 設計と実装の差

1. `docs/p6-design.md` §3.6 の POST export の応答スケッチ `{"files": [...]}` が実装（契約の文書）と違う。文書を直す。
2. §0.7 は `floor(round(x*W,6))` / `ceil(round((x+w)*W,6))` に更新済みで実装と一致。**ただし `left == W` のときの幅 0 は設計にも実装にも手当てがない**（上位 1）。
3. 契約の `details` の約束: 領域なしの 422 は「どの注記か」を `details.annotation_id` で返すつもりの形だが、文言が入っている（上位 2）。
4. 実装の記録の穴 3（group_id の引き継ぎ）は 05:42 版で塞がれているが、記録はまだ「いまは付かない」のまま。記録を更新する。

---

## F. 未実装 2 点と穴 3 件

### F-1. `gui_layout.mjs` §8.3-2 / -3（注記の画面の計測）が無い
いま無いのは Chrome での**自動**計測だけで、手動では上の §C-8 で測った。足すべき検査（今回の値を基準に）:
- 印が画像の矩形に収まる（`.anno-mark` の rect ⊂ `img.preview` の rect。19/19）
- **一覧の番号と画像の番号の対応**（メモを間に挟んだ 3 件で `3:楕円 ↔ 印 2` を検出できる。上位 3 をこれで捕まえられた）
- 4 px の規則を本物の MouseEvent で（3 px → POST 0、4 px → 1）
- 一覧 20 行で行の横あふれ無し（`scrollWidth ≤ clientWidth`）と、`#detail` の外にはみ出さない
- 注記の箱が**スクロール無しで見える**か（いまは 1400×900 / 1920×1080 とも否）
- 画像の表示幅と「4 px が元画像の何画素か」

### F-2. 穴 1: GET crop はその場で作り、絞りが無い
2048² 全面で 170 ms・5.7 MB。一覧の「切り出し」リンクは `download` なので連打の害は小さい。ブラウザの同時要求は 6 本までで自然に絞られる。**いまは直さなくてよい**。将来の懸念はエージェントが 20 件を並列で取る場合（2048² なら 3 s 強）。

### F-3. 穴 2: 一覧と印の対応は番号だけ、「寄せる」は無い
番号だけでも足りる、は**メモが無い前提**でしか成り立たない（上位 3）。番号の付け方を揃える（一覧も `shape` 付きだけに番号を振り、メモは「—」）のが最小の直し。「寄せる」（行をホバーで印を強調）は後回しでよい。

### F-4. 穴 3: まとまりレビュー → 拡大で `group_id` が引き継がれない
**05:42 版で塞がれている**（§C-8 の g2z）。`group.js` が `?group=` を付け、`app.js` が `setAnnotationGroup` を呼び、`annotations.js` が POST body に入れる。残る点:
- `groupId` は `resetAnnotations()` で消さないが、`app.js` の経路切替（363 行）が毎回 `setAnnotationGroup(null)` を呼んでから `?group=` を読むので、`#/asset/<id>` を直接開けば `null` に戻る（画面の試験でも `group_id: null` を確認）。前のまとまりの id が残る経路は無い。gui_smoke に「`?group=` 無しで開いたら `group_id: null`」の 1 行を足すと今後も守れる。
- group_id が合わない asset に付けると 422（確認済み）。まとまりの外の画像へ `?group=` 付きで移ることは画面からは起きない。

---

## G. 質問（待たずに続けた）

1. 右端ぴったり（`x+w = 1` で `x` が `1-ε`）の注記は**作らせない**（422）か、**1 画素に丸める**か。私は後者（`left` を `W-1` に抑える）を勧める。作成を 422 にすると画面の右端ドラッグ（`Math.min(1-x, …)`）で起きうる。
2. 決定 3 を変えるなら、飛ばしたメモを契約の `crops` の外で知らせたいか（例: 応答の `details.skipped`）。契約の `additionalProperties: false` なので足すなら schema も変わる。
3. 「拡大の画面」は右の列の詳細のままでよいか（画像 315 px）。設計 §5.3 の読み方の確認。

---

## H. 残件の上位 3 と後始末

1. **右端・下端の幅 0 で 500**（`crop_box` のクランプ、`left == W`）。
2. **領域なしが混ざると全体 422 ＋ `details.annotation_id` が文言**。画面の書き出しがメモ 1 件で止まる。
3. **一覧と画像の番号のずれ**（メモが間にあるとき）。

後始末: サーバ 8791 は停止。`.tmp-audit-redo/data-p52` に監査の注記・切り出し（52 KB）と、実体の無い試験用 asset（`01AUDITNOFILE00000000000000`、一覧の先頭に黒いタイルで出る）が残っている。`.data/` と `src/`、`docs/` の既存ファイルは触っていない。
