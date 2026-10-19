---
name: image-reviewer-audit
description: >-
  image-reviewer（C:\work\image-reviwer）の設計の点検と実装の監査を「実行して確かめる」やり方。指示書（docs/*-brief.md）の
  読み方、実データの複製（sqlite3 の backup()）、サーバを別ポートで立てる手順、自前の検査スクリプトと Chrome headless、
  報告の形（A/B/C/D/E/F/G/H と最も重大な 3 件）、質問は G に推奨つきで書いて待たずに進む規律、そして
  P5〜P6〜P4 で実際に踏んだ罠のカタログ（GET が書く・部分索引・浮動小数の境界・ヘッダの enum で 500・契約の欄を出さない・
  壊しても落ちないテスト・キャッシュに当たった計測・位置対応の訳・WAL を畳まない複製・申告していない穴・無い画面・
  コードを読んだだけの監査）、P8〜P9 と文言の監査で分かったこと（失敗の道に重大な穴が出る・段をまたぐ穴・実装者の数字を
  測り直す・壊し試験の変異を数える・本物の Chrome で押す（同じ URL への navigate は再読込されない）・文言は 2 つの軸・
  事故を隠さない）。「監査して」「点検して」「audit」「review brief」「docs/p*-audit-brief」「合格の線を通して」
  「実行で確かめて」と言われたとき、または docs/*-brief.md を渡されたときは必ずこのスキルを読む。
  実装側の知識は image-reviewer-dev、Orca の往復は orca-relay を見る。
---

# image-reviewer の監査（実行して確かめる）

監査者は **DeepSeek（実装者）が書いた設計・実装を、自分の手で動かして裏を取る**役。読んだだけの監査は何も守らない
（P5 の最初の 3 回は `Bash` が `EPERM` で起動できず「コード読みだけ」になり、全部やり直した。根拠: `docs/audit-redo-brief.md`、
`docs/p5-audit-run-note.md`）。以下の手順と罠は、すべて実際に踏んだものに根拠を添えてある。

## 1. 段取り

1. **指示書を読む**（`docs/p<N>-review-brief.md` か `docs/p4-audit-brief-p<N>-<k>.md`）。§0 環境、§1 入ったもの、§2 確かめること、
   §3 報告の形、§4 往復。**実装の記録**（`docs/p<N>-<k>-implementation.md`）があれば一緒に読む。無ければ指示書の列挙を
   記録として扱い、報告にそう書く（`docs/p4-0-audit-report.md` 冒頭）。
2. **開始の知らせ**を送る（orca-relay スキル。subject `<段>-audit-start`）。
3. **環境を整える**: `$env:UV_CACHE_DIR`、利用者のサーバが `.venv` を握っていれば `uv run --no-sync` か
   `.venv\Scripts\python.exe`（`docs/p4-audit-brief-p4-1.md` §0）。ComfyUI が要るなら `GET /system_stats` で稼働を確かめる。
4. **実データは読むだけ**（`mode=ro`）。**複製は `sqlite3.Connection.backup()`**（WAL を畳む。`cp` だと判断が抜ける）。
   複製を `IMAGE_REVIEWER_DATA` にして **8791〜のポート**で立てる（8790 は利用者）。起動で移行が当たるので、
   **起動後の `user_version` と件数**をまず記録する（`docs/p4-1-audit-report.md` §D-10）。
5. **回帰の三点セット**を先に回す: `pytest -q`、`node tools/gui_smoke.mjs`、`gui_layout` の 4 画面。件数を指示書の数と比べる。
6. **実装者の道具を自分で回す**（`tools/probe_p<N>*.py`、`tools/check_contract_*.py`）。落ちたら**原因を突き止める**
   （`probe_p6_2.py` の 422 は複製に残っていた領域なしのメモが原因だった。`docs/p6-2-audit-report.md` C-6）。
7. **自前の検査を書く**（`.tmp-audit-redo/p<N>/*.py` / `*.js`）。HTTP は `http.client`、契約は **本物の `jsonschema`**
   （`uv run --no-sync --with jsonschema`）、画面は **Chrome headless を CDP で**（`chrome.exe --headless=new
   --remote-debugging-port=9333 --user-data-dir=<repo 内>` を Node 24 の `WebSocket` で駆動し、ページの中で
   `window.fetch` を差し替えて回数と本文を数える。雛形 `cdp.mjs` は `.tmp-audit-redo/` に置いていたが消されたので、
   監査のたびに作り直す。`docs/p6-1b-audit-report.md`、`docs/p6-2-audit-report.md` §C-8）。
8. **合格の線を自分の手で通す**。設計 §1.2 の表の手順をそのまま打ち、値を報告に写す。
9. **壊すと落ちるか**を見る。テストの docstring と期待値を読み、「壊しても通る」経路を実行で示す（§4 の罠 6）。
   **壊し試験は自分でも回す**（実装者の N 通り＋自分の M 通り。ソースの写しを `PYTHONPATH` で前に置く変異で、`pytest` を
   丸ごと回す）。**落ちない変異が「等価変異」か「テストの穴」かを 1 つずつ判定**して F に書く（`docs/p9-audit-report.md` §E の
   M1〜M9、`docs/p8-2-audit-report.md` F）。
9b. **合格の線の外側＝失敗の道を見る**。取引が落ちる・移動が失敗する・競合する・期限が切れる・DB が壊れている・DB が掴まれている・
   ファイルが読めない——**一番重大な穴はここに出る**（P8-2 の B-1〜B-3 は全部そうだった。`docs/p8-2-audit-report.md` B）。
   **「壊れた DB」「掴まれている DB」「読めないファイル」を実際に作る**（先頭 4 KB／2 ページ目を潰す、別プロセスで `BEGIN IMMEDIATE` を
   持つ、ACL で読めなくする。`docs/p8-4-audit-report.md` B-1、`docs/p9-audit-report.md` D）。
9c. **段をまたぐ穴を見る**。最後の段（P9）で P8-4 の live `quick_check`（書いた接続のページキャッシュの盲点）と P8-2 の枚数の出どころ
   （上部 262・左 455）が見つかった。**最後の段では「P1 から通した穴」を 1 度見る**（`docs/p9-audit-report.md` C-1・C-2）。
9d. **実装者の主張を追試する**。**数字は自分で測り直す**（合成 DB を自分で作り、同じ桁と結論を確かめる。`tools/make_synthetic_db.py`）。
   **「見込み」と「実測」を分ける**（実装に無い並列化を実測のように書いていないか。P9 の「同時 8 本」。`docs/p9-audit-report.md` C-3）。
10. **報告を書く**（§3 の形）→ 実データの mtime と `src/` の mtime を確かめる → サーバを止める（`TaskStop` の後に
    `netstat` で 8791 の PID を確認して `taskkill`）→ **完了の知らせ**（subject `<段>-audit-done`）→ 記憶を更新する。

## 2. 計測の規律

- **別々の入力で測る。** 同じ画像の再投入は ComfyUI が `execution_cached` で返す（0.22 s。実際は 2.8〜3.4 s/枚）。
  `/history` の `status.messages` に `execution_cached` が出たら測り直す（`docs/p4-review-report.md` A-4、`.tmp-audit-redo/p4/comfy_distinct.py`）。
- **測り方を書く**: keep-alive か毎回接続か、何回の中央値か、初回（読み込み込み）と定常を分ける。keep-alive と毎回接続で
  桁が違う（接続の設立 ~20 ms。`docs/p6-1a-audit-report.md` C3）。
- **入力順の並びは証拠にならない**（サーバの順と一致する）。並びの検証は seed 順・似ている順で（P5-2 の監査で advisor に 2 回指摘された）。
- **見積りは実測から比例で出し、「見積り」と書く**（`docs/p4-0-audit-report.md` C-3「10,000 枚で約 4.3 s」）。
- 標本が間に落ちただけの値を「遮断なし」の証拠にしない（`docs/p4-1-audit-report.md` §H）。
- **計測は実装の経路で**。probe が自分でプールを回した値は実装の値ではない。**OS のキャッシュの有無で桁が変わる値は両方書く**
  （`--include-library` 0.63 秒と 2.40 秒。`docs/p9-audit-report.md` D-5、`docs/design.md` §16.7-6）。
- **合成 DB の判断は `ReviewService` で入れる**。`asset.review_state` を直に `UPDATE` すると起動時の `reconcile()` が全部 `unreviewed`
  に戻し、`state=kept` の絞り込みは「0 件への絞り込み」を測る（`docs/p9-audit-report.md` C-3）。
- **計測の道具には絶対パスを渡す**（`probe_p9.py --out` が相対だと `--library` が 422 で落ち、日次も黙って 5 回失敗する。`docs/p9-audit-report.md` D-3）。

## 3. 報告の形（`docs/p<N>-<k>-audit-report.md`。既存のファイルは書き換えない）

```markdown
# <段> 監査報告 — 実行込み
- 日付 / 指示書 / 対象（ファイルと mtime）/ 設計の版（行数と mtime）/ 環境（複製・ポート・一時物）/ 触っていないもの
## 判定: 合格 / 条件つきで使える / 直してから次へ（+ 最も重大な 3 件を冒頭に）
## A. 直っていない／設計の約束が成り立たない（必ず直す）
## B. 重大        ## C. 中程度        ## D. 軽微（「確かめた結果、問題なし」は 1 行）
## E. 設計とのずれ（設計が黙っているのに実装が決めた所も）
## F. テストで守れないもの（表: テスト / 判定 / 根拠と直し方）
## G. 依頼者への質問（表: 論点 / 選択肢 / 推奨）
## H. 確かめられなかったこと（+ 証拠の注記 + 後始末 + 実行したコマンドと結果）
```

- 各項目に**場所（ファイル:行）と再現手順**。実行していないことは「実行していない」と書く
  （`docs/p4-review-brief.md` §2、`docs/p4-audit-brief-p4-1.md` §3）。
- **依頼者は待たない**。決めてもらうことは G に**選択肢と推奨**で書き、推奨どおりで進める（指示書 §4「待たずに続けて」。
  仕分けは慣例として「推奨はすべて採用」。`docs/p6-review-triage.md` 冒頭）。
- 設計の点検では **総合判定: このまま実装してよい / 直してから実装 / 作り直す** と、実装者が自分で決めた点・穴の**判定**も書く。
- 監査の最中に設計やソースが書き換わることがある。**どの版（mtime・行数）を見たか**を冒頭に書き、追記は §I / §J として
  同じ報告に足す（`docs/p6-2-audit-report.md` 冒頭「05:42 版」、`docs/p4-review-report.md` §I / §J）。
- 自分のスクリプトの出力に**紛らわしい行**があれば H に注記する（`known の既定: 1` は自分が 1 を入れた行だった。`docs/p4-0-audit-report.md` H）。

## 4. 実際に踏んだ罠のカタログ（確かめる順）

| # | 罠 | どう確かめるか | 根拠 |
| --- | --- | --- | --- |
| 1 | **`GET` が書く**（`scope=all` の `GET` がファイルを書いていた） | 全部の `GET` の前後で複製フォルダのファイル一覧（名前・mtime・size）を比べる。`format=crops` を `GET` で来たら 422 か | `docs/p5-audit-report.md` C8 / G6、`docs/p6-design.md` §0.6 |
| 2 | **部分 UNIQUE 索引が使われるか・UPDATE → INSERT の順** | `EXPLAIN QUERY PLAN` と、同時 8 本の投入で `open` が 1 つになるか。逆順だと `IntegrityError` | `docs/p6-review-report.md` C4、`docs/p6-0-audit-report.md` F6、`docs/p6-1a-audit-report.md` §2-2 |
| 3 | **浮動小数の境界**（`ceil((x+w)*W)` が幅 1360 で 1 画素はみ出す。`round(v,6)` してから `ceil`。端ぴったり `left == W` で幅 0 → 500） | 1024 / 2048 では起きない。**1360** と `x=1-1e-12, w=1e-12` を打つ | `docs/p6-review-report.md` B1、`docs/p6-2-audit-report.md` 上位 1 |
| 4 | **ヘッダの enum を検査せず DB の `CHECK` に当たって 500** | `X-Image-Reviewer-Actor: robot` を送る。422 が正 | `docs/p6-1a-audit-report.md` A1 |
| 5 | **契約に足した欄を実際に出していない**（`superseded_by` / `gloss`） | 値を 1 件入れてから 3 文書（`all` / `group:` / `asset:`）を本物の `jsonschema` で通し、欄に値があるか。旧契約（欄を知らない読み手）でも通るか | `docs/p6-0-audit-report.md` B1、`docs/p4-review-report.md` B-5、`docs/p4-0-audit-report.md` D-3/D-4 |
| 6 | **壊しても落ちないテスト**（同一プロセスの錠で直列化、`ORDER BY` を外しても同じ順、語釈 0 件で `gloss` の検査が空振り、COMMIT 直後に落ちる試験の空振り） | テストが見ている「壊すもの」を外した状態を再現して通ることを示す | `docs/p5-audit-report.md` F1、`docs/p6-review-report.md` C9、`docs/p4-0-audit-report.md` F |
| 7 | **キャッシュに当たった計測**（`execution_cached` で 0.40 s、別々の画像だと 2.9 s） | §2。`status.messages` を見る | `docs/p4-review-report.md` A-4 |
| 8 | **位置対応の訳**（20 語で 6 回中 2 回しか行数が合わず、合っても `1girl → 男の子`。**番号付きなら 4/4**） | 位置で対応させる設計は番号付き（`1. 1girl`）に変えさせ、`sampling off` で決定的に | `docs/p4-review-report.md` A-3 |
| 9 | **WAL を畳まずに DB をコピーして判断が抜ける** | `backup()` で複製し、`decision` の件数を実データ（`mode=ro`）と比べる | `docs/p4-0-audit-report.md` D-1 |
| 10 | **実装者が申告していない穴**（右端で 500、メモ 1 件で書き出し全体が 422、一覧と印の番号ずれ、`queued` の窓で 2 本走る、取引の中で模型を待つ） | 境界・空・混在・同時・遅い模型（`sleep`）を自分で作る | `docs/p6-2-audit-report.md` 上位 3 件、`docs/p4-1-audit-report.md` B-1 / B-2 |
| 11 | **画面が無いのに「既存」と書いてある**（まとまりレビュー `#/group/<id>` は P5 に無かった） | `apps/gui/index.html` と `app.js` の経路を見て、線が要求する画面が本当にあるか | `docs/p6-review-report.md` A2 |
| 12 | **コードを読んだだけの監査は何も守らない** | 実行できない環境なら「実行していない」と書き、できるようになったらやり直す | `docs/audit-redo-brief.md`、`docs/p5-audit-run-note.md` |
| 13 | **同じ版番号で形が違う DB**（`IF NOT EXISTS` だけの移行は既に作られた表に列や `CHECK` を足さない） | 古い複製を `migrate()` に通し、`PRAGMA table_info` を比べる。ジョブが `running` のまま固まる | `docs/p4-1-audit-report.md` A-1、`docs/p6-0-audit-triage.md` 末尾 |
| 14 | **黙って CPU に落ちる `onnxruntime-gpu`** | `session.get_providers()` の実値。`import torch` を先にすると CUDA に乗る | `docs/p4-review-report.md` B-2 |
| 15 | **括弧とコロンを落とす正規化** | CSV の語を同じ正規化に通して変わる数を数える（1,619 語） | `docs/p4-review-report.md` A-1 |
| 16 | **ノードの前処理との 1 ピクセルの差**（`round` 対 `int`） | 縮小の寸法を式で比べ、非正方形の実画像で語の集合を比べる | `docs/p4-1-audit-report.md` B-3 |
| 17 | **取引の中で外部を待つ**（全 API が止まる） | 偽の模型に `sleep` を入れ、別スレッドの `locked()` の待ちを測る | `docs/p4-1-audit-report.md` B-1 |
| 18 | **ComfyUI へ画像を渡す手順が設計に無い**（`LoadImage` は `input/` の一覧だけ。複製が溜まる） | 絶対パスで 400 を示し、`upload/image` → `[temp]` で通す。`temp/` の枚数を数える | `docs/p4-review-report.md` A-2、`docs/p4-1-audit-report.md` D-14 |
| 19 | **監査中にソースが変わる** | 対象ファイルの mtime を最初と最後に取り、変わっていれば版を報告に書く | `docs/p6-2-audit-report.md` 冒頭、`docs/p4-review-report.md` §J |
| 20 | **複製に残った試験データ**（実体の無い asset・領域なしのメモ）が次の検査を落とす | 複製は作り直す。残した物を報告の後始末に書く | `docs/p6-morning-report.md`「1 つ注意」、`docs/p6-2-audit-report.md` C-6 |
| 21 | **性能の値の出所**（実装者の値は書き出しが落ち着いた後、監査の値は毎回接続で桁が違う） | 両方の測り方で測り直して表に並べる | `docs/p6-1a-audit-report.md` C3 |
| 22 | **失敗の道の穴**（`os.rename` の後・台帳の前で落ちると迷子／`move_failed` の行が窓切れで黙って消える／タイマーの実削除と `undo` の競合） | 取引の途中で例外を注入する（`monkeypatch`）、移動先を埋める、2 スレッドで同時に打つ。**合格の線の表には無い道**を先に回す | `docs/p8-2-audit-report.md` B-1〜B-3、`docs/p8-2-audit-recheck.md` |
| 23 | **`quick_check` を書き込んだ接続で見ると、ページキャッシュに載ったページの壊れを見落とす**（既定の `cache_size` でも。0.65 MB の DB で `tick()` が控えを取って書き続けた） | DB を走らせたまま外から 1 ページ潰し、`BackupService.tick()` が `read_only` になるか。**新しい `mode=ro` の接続なら 28/28 で見つかる**。`cache_size` の有無で結論は変わらない（「入れると見落とす」は誤り） | `docs/p9-audit-report.md` C-1、`.tmp-audit-redo/p9-audit/cache_exp3.py` |
| 24 | **段をまたぐ数の出どころ**（上部バーは `assets.total`、左の列は `stats.assets` で 262 と 455 が並ぶ） | 同じ画面に出る同じ意味の数を全部列挙し、出どころの口を揃える。本物の Chrome の複製で両方の数を読む | `docs/p9-audit-report.md` C-2、`apps/gui/counts.js` |
| 25 | **帯の取りこぼし**（8bit × 8 本は距離 7 まで。4bit × 16 本でも「64bit の一部しか見ない」穴は実データの形では出ない） | 距離 0〜64 の**総当たり**と突き合わせ、**鳩の巣の境界（距離 15・一致する帯が 1 本）**の合成 1 組を置く | `docs/p8-1-audit-report.md` B-1、`docs/p8-3-band-miss.md` |
| 26 | **同じ URL への `Page.navigate` は再読込されない**（押せていないのに ok になる）。`gui_shot` の既定は 8791（8790 に向けると「接続が拒否されました」の写真） | 画面ごとに `about:blank` を挟んでから開くか `Page.reload`。**`run` を飲まず本物の Chrome で押す**。**0 件と N 件の両方**を確かめる（空の状態は壊れやすい） | `docs/duplicates-keep-button.md` §5・§7、`docs/wording-audit-report.md` §6、`docs/japanese-ui-audit-report.md` §3 C |
| 27 | **`ids` 無しの早期 `return` が POST を数え落とす**／**`busy` を付け忘れたボタンの二度押し**を「1 回だけ叩く」検査は見ない | `click()` を 2 連打して POST の回数を数える。空の `ids` でも口を叩く経路を作る | `docs/p8-5-audit-report.md` C-1、`docs/duplicates-keep-button.md` §5 |
| 28 | **文言の監査は軸が 2 つ**: 「中国語の直訳っぽさ」と「日本語のシステムとして初見で通じるか」は別の監査。語彙を数えるだけでは出ない | **癖**を見る（中黒で文を繋ぐ・英語の内部値と記法の露出・「枚」「物」の名詞化・無いボタンへの案内・空の状態の次の一手）。**正（`frontend-design.md` §6）と実装の食い違いを 1 行ずつ数える**。画面の文字列は **grep と本物の Chrome の写し（`innerText`・`title`・`placeholder`）の両方**で拾う | `docs/wording-audit-report.md` §1・§5、`docs/japanese-ui-audit-report.md` §2・§6 |
| 29 | **並行の修正で行番号が動く** | 作業ツリーを**時刻つきで写して**から抽出し、場所は**「ファイル＋引用した文」**で示す。書き終えた直後に全引用を `grep -F` し直して報告に残す（コメント行に当たらないよう、抽出済みのコード行に当てる） | `docs/japanese-ui-audit-report.md` §0・§8.3 |
| 30 | **複製サーバが他の担当に止められる**／自分のスクリプトが人様のサーバを止める | 止める前に `/api/health` の `data_dir` を確かめる。止まっていた・止めてしまったは**隠さず報告に書く** | `docs/japanese-ui-audit-report.md` §8.3、`docs/p8-6-relink.md` §5 |

## 5. 判定の言い方

- **合格 / 条件つきで使える / 直してから次へ** のどれかを冒頭に。「条件つき」は条件を A・B で名指す。
- **最も重大な 3 件**は報告の冒頭と末尾の両方に。理由より先に**再現手順と値**。Orca の知らせも 3 件を先に。
- **事故は隠さず書く**（自分のスクリプトが人様のサーバを止めた、env を付け忘れて実データを開いた、複製に書いた）。何を、いつ、
  どこまで、実データは無傷か（署名の前後比較）を 1 段落で（`docs/p8-6-relink.md` §5、`docs/p9-audit-report.md` H）。
- 指示書が名指しした観点（「ワーカー 1 本」「1 枚 1 取引」）で欠陥が出たら、他が通っていても**合格にしない**
  （`docs/p4-1-audit-report.md` 判定）。
- 実装者の「自分で決めた点」は **妥当 / 条件付き / 変更を勧める** で 1 つずつ。申し送りは **持ち越してよい / 今直す** で。

## 6. 後始末と証跡

- 残した物（複製・一時スクリプト・ComfyUI の `temp` の複製・`tests/.tmp` の残骸）と消した物を H に書く。
- 実データ `.data/` の mtime が変わっていないこと、`src/` に自分の時刻の変更が無いことを確かめて書く。
- 自前のスクリプトは `.tmp-audit-redo/` に置き、**再現手順を報告に写す**（`.tmp-audit-redo/` は消されることがある）。

## 7. 何を足したか（2026-10-19。P8〜P9 と文言の監査から）

- 冒頭の説明: P8〜P9 と文言の監査の項目を足した。
- §1: 9 を「壊し試験は自分でも回し、落ちない変異が等価変異かテストの穴かを判定する」に広げ、9b 失敗の道（壊れた DB・掴まれた DB・読めないファイルを実際に作る）、9c 段をまたぐ穴（最後の段で P1 から通す）、9d 実装者の主張の追試（数字は測り直す・見込みと実測を分ける）を足した。
- §2: 計測は実装の経路で・キャッシュの両方の値・合成 DB の判断は `ReviewService` で・道具には絶対パス。
- §4: 罠 22〜30（失敗の道・`quick_check` のページキャッシュの盲点・段をまたぐ数の出どころ・帯の鳩の巣の境界・同じ URL への navigate と `gui_shot` の 8791 と 0 件/N 件・早期 return と二度押し・文言の 2 つの軸・並行の修正で動く行番号・複製サーバが止められる）。
- §5: 知らせも 3 件を先に。事故を隠さず書く。
