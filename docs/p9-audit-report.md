# P9（仕上げ）の監査報告 — 実行込み

- 日付: 2026-10-18〜19（JST）。監査: Fable。実装: DeepSeek（dsh）。対象のコミット: `c98b25e`（P9）。
- 根拠: `docs/design.md` §12.1（P9 の合格の線）・§12.2・§12.3・§14・§16.7、`docs/p9-implementation.md`、`docs/p9-implementation-brief.md`、`docs/handoff.md` §5〜§7・§10。
- 触っていない物: **既存のファイル（書き換え 0）**・**実データ `.data/`（`mode=ro` と `os.stat` の読みだけ。画像は 1 枚も動かしていない。§F）**・**8790（PID 7324。一度も止めていない）**・ComfyUI・`%USERPROFILE%`（フォルダを作っていない）。**コミットもしていない**。私のサーバは 8793 / 8794 と、起動時間の計測で 8796〜8798・8784〜8786 を一瞬だけ（全部 `data_dir` を確かめてから止めた）。
- 一時物: `.tmp-audit-redo/p9-audit/`（108 MB。脚本・生のログ・合成 1 万枚・複製。消して構わない）。

## 判定: **合格（条件つき）**

§12.1 の実測は**私の手で再現した**（合成 1 万枚を自分で作り、`probe_p9.py --all` と自前の計測で同じ桁・同じ結論）。「一覧 API だけ届かない」の結論は正しく、むしろ控えめである（画面が実際に引く `limit=2000` は p95 278〜306 ms、画面が一緒に呼ぶ `/api/stats` が 1 万枚で p95 130 ms）。計測中に直した 2 件は壊すと落ち、exe 化の根拠は 3 点とも再現した。回帰は pytest 518 × 3・gui_smoke 322・gui_layout 11 本が緑で、実データは無傷（段 1 の 193 行は中身の sha256 まで同じ）。

条件は下の 3 件。**C-1 は段をまたぐ穴**（P8-4 の G-1 の保証が、出荷の形では小さい DB に効いていない。P9 の `cache_size` の判断の根拠がこれで、結論は合っているが理由が違う）。**C-2** は P9 が上部バーの枚数の出どころを変え、実データでは「455 枚」が「262 枚」になった（同じ画面の「すべて」は 455 のまま）。**C-3** は §12.1 の表の 2 つの数が「実装の値」ではない（存在しない並列プールの見込みと、0 件への絞り込み）。

## 最も重大な 3 件

1. **C-1（P8-4 ↔ P9）走ったまま壊れた DB の入口（G-1）は、ページキャッシュに載っているページの壊れを見ない。** 出荷の既定（2 MB）でも、アプリ自身が書いた 0.65 MB の DB を外から潰すと `tick()` は控えを取り、`read_only` にならず書き続ける（実測。4 つの pragma の組み合わせ全部）。P8-4 当時の実データは 1.0 MB だった。実装者の「`cache_size=-65536` を入れると見落とす」は正しい観察だが、既定なら見落とさないという前提が誤り。**新しい読み取り専用の接続で `quick_check` すれば 28/28 で見つかる。**
2. **C-2（P8-2 ↔ P9）上部バーの枚数が「全部」から「生きた枚」に変わった。** 直す前は `/api/stats` の `assets`（削除済みを含む）、直した後は `/api/assets` の `total`（段 1 で外した枚を含まない）。実データでは **455 枚 → 262 枚**。同じ画面の「すべて」の数（`c-all`）は 455 のまま。`p9-implementation.md` §3-4 の「実データでは文言が変わらない」と `frontend-design.md` §6 の例「455 枚」は実データと合わない。
3. **C-3 §12.1 の表に「実装の値」でない数が 2 つ入っている。** ①「同時 8 本なら 22 ms/枚 → 3.7 分」は `ThreadPoolExecutor` を計測の道具が自分で回した見込みで、実装にスレッドプールは無い（`thumbs.py` / `app.py` に `ThreadPool` / `Semaphore` が無い。§12.2 の「min(8, cpu)」は未実装）。②「`state=kept`（絞り込み）」は、`make_synthetic_db.py` が入れた判断をアプリ起動時の `reconcile()` が全部 `unreviewed` に戻すため（stderr に「2209 行」）、**0 件への絞り込み**を測っている。数の桁は変わらないが、表の名札が違う。

## A. 何を確かめたか（依頼の 9 点との対応）

| # | 依頼 | 結果 | 根拠 |
| --- | --- | --- | --- |
| (1) | §12.1 の実測の追試・計測の正しさ | **再現**（§B）。サーバ内＝`TestClient`、p95 は 30 回の nearest-rank、1 回の温めの後で測っている。本物の HTTP（keep-alive）でも差は 1〜3 ms。**名札の違いが 2 つ**（C-3）、道具の穴が 2 つ（D-3・D-9） | `probe-all.txt` / `probe-rest.txt` / `list_meas.out.txt` |
| (2) | 一覧 API が届かない結論 | **正しい**。limit=100 で p95 252.6 ms、画面の `limit=2000` で 277.6 ms（HTTP 305.7）。内訳は SQL 3 本 47.5 ms ＋ `store.assets()` の dict 組み立て約 150 ms（うち `meta_json` の `json.loads` 1 万回 78〜92 ms）＋ `list_assets` の `_summary`・絞り・並べ替え 80 ms。`cache_size=-65536` を掛けても 43.6 → 42.5 ms（効かない）。実データ 262 枚は p50 13.0 / **p95 29.1 ms**（実装者は 14.3。p50 は一致、p95 は揺れる）＝「20 ms の内側」は余裕があるわけではない | `list_meas.out.txt`（cProfile） |
| (3) | 直した 2 件が壊すと落ちるか | **落ちる**（§E）。`temp_store` を外した写しで 1 万枚の `GET /api/assets` が **500 `sqlite_error`**（`unable to open database file`。D-8 の直しで 503「戻してください」ではなくなっている）、実物は 200。D-8 は語彙の 3 通りで 4 件が落ちる。`disk i/o error` の語だけ試験が無い（D-1） | `mut9.out.txt` / `temp_store_repro.py` |
| (4) | `cache_size` を入れなかった判断 | **結論は妥当・理由は誤り**（C-1）。速さの実利も無い（上） | `cache_exp2.out.txt` / `cache_exp3.py` |
| (5) | exe 化の推奨の根拠 | **3 点とも再現**。PyInstaller 6.22.3 で `--onedir` が 16.4 秒・**138.3 MB（= 131.9 MiB）**・116 ファイル。起動は exe 528 / 537 ms（**冷えた 1 回目は 1706 ms**）、`uv run` は 1055〜1059 ms。`gui_present: false`・`GET /` 404。`gui_dir` が `dist\image-reviewer\apps\gui` を指し、`--add-data` の中身は `_internal\apps\gui` に居る（「1 か所」の指摘どおり）。推奨「今は作らない」に同意 | §B-3 |
| (6) | 見送った 5 件と handoff §7 の 13 件 | **妥当**。ただし §7-1（8790 を sandbox の外で立て直す・日次 0 個）と `p9-implementation.md` §8-9（実機の日次はまだ）は**古い**: 8790 は Explorer → `start-image-reviewer.cmd` から立っていて、利用者が `backup_dir` を `.backup/daily` に変え、**日次は 2026-10-19 00:00:15 JST に 455 枚で取れた**（§D-4） | `GET /api/backup` |
| (7) | 回帰と実データ | pytest **518 × 3**・gui_smoke **322 ok / NG 0**・gui_layout **11 本すべて ok**・画像の署名 `d9604560e494c510`・段 1 の 193 行の sha `c6b9064cfa2972e6` が前後で同じ（§F） | `pytest-3runs.txt` ほか |
| (8) | 設計とのずれ | §D の末尾の表（5 件。うち未申告は 2 件） | — |
| (9) | P8 全体をまたぐ穴 | **C-1・C-2**。P8-6 の C-1〜C-3 の直しは `f7e984f` に入っていて（`test_relink.py` 32 件）pytest で緑。日次の取り方の穴を G-5 に | — |

## B. 実測の追試（§12.1 の行ごと）

**測り方**: 合成 1 万枚は私が `tools/make_synthetic_db.py` で作り直した（`.tmp-audit-redo/p9-audit/synth10k`。画像 5.7 秒・初回走査 38.5 秒・DB 30.0 MB）。実データの複製は `sqlite3.backup()`（455 枚・判断 3・段 1 の 193 行・`quick_check ok`）。`probe_p9.py --all`（`--runs 30`）と、自前の `list_meas.py`（TestClient・cProfile）、本物の HTTP（`http.client` の keep-alive・uvicorn 8793/8794）、本物の Chrome（実装者の `grid_timing.mjs`）。

| §12.1 の行 | 目標 | 実装者 | **私の実測** | 判定 |
| --- | --- | --- | --- | --- |
| 一覧 API（limit=100・1 万枚） | p95 20 ms | 244.7（ログは 252.7） | **252.6**（TestClient）／ 254.4（HTTP） | 届かない（一致） |
| 同・画面が引く `limit=2000` | — | （未計測） | **277.6**（TestClient・1,020 KB）／ 305.7（HTTP） | 届かない |
| `/api/stats`（画面が毎回呼ぶ） | — | （未計測） | **p95 130.2 ms**（1 万枚）／ 6.1 ms（299 枚） | §12.1 に無い（D-6） |
| 同・実データ 262 枚 `limit=1000` | 参考 | p50 12.6 / p95 14.3 | p50 13.0 / **p95 29.1** | 桁は同じ。p95 は揺れる |
| 詳細 1024px（生成済み） | 200 ms | 2.6 合成 / 2.4 実画像 | **2.6 / 2.2** | OK |
| 1024px 初回生成（実画像 1.15 MB） | 25 分（P9 で決めた） | 128 ms/枚 → 21.3 分 | **131 ms/枚 → 21.9 分**（24 枚の中央値） | OK |
| 256px 初回生成（実画像） | 6 分 | 30 ms/枚 → 4.9 分 | **30 ms/枚 → 4.9 分** | OK |
| 「同時 8 本」 | — | 22 / 4 ms/枚 | 20 / 4.3 ms/枚 | 再現するが**実装の値ではない**（C-3） |
| 比較の 8 枚 | 400 ms | 8.3（最終ログは 7.5） | **7.5**（実データ）／ 3.6（合成） | OK |
| グリッド初回表示 | 300 ms（100 枚） | 87（100 枚）/ 93（299）/ 532（1 万） | **95（299 枚）/ 454（1 万枚 → 2000 枚）**。100 枚ちょうどは取り直していない（299 枚で 95 ms なので上から抑えられる） | OK |
| 2 回目以降の走査（差分なし） | 10 秒 | 2.62〜2.70 | **2.68〜2.70**（3 回） | OK |
| 初回走査（合成。ハッシュほぼ 0） | 90 秒 | 40.6（書いた直後）/ 9.1 | **38.5 / 9.2** | OK（見込み） |
| 判断の記録 | 100 ms | p95 1.5 | **1.4** | OK |
| 日次バックアップ（DB 3.2 MB） | 5 秒 | 201 ms | **66.5 ms** | OK |
| 一括削除の再照合 1,000 件 | 1 秒 | 596 ms（`os.stat` 13.8） | **227 ms**（`os.stat` 11.6） | OK |
| `--include-library`（291.1 MB） | 5 分（P9 で決めた） | 2.40 秒（132 MB/s） | **0.63 秒（516 MB/s）** | OK。差は OS のファイルキャッシュ（D-5） |
| `nearby`（見つからない / 1 段目） | 3 秒（P9 で決めた） | 39.2 / 44.6 ms | **36.4 / 41.9** | OK |
| 土台 `GET /api/health` | — | p95 1.1 | **1.2**（HTTP 1.0） | 枠の費用は 1 ms |

**計測の正しさについて**: サーバ内（ASGI 直叩き）・1 回温めてから・30 回の p95（nearest-rank: 30 回なら 2 番目に遅い値）・別々の入力（サムネイルは 24 枚を順に）は約束どおり。本物の HTTP との差は 1〜30 ms で桁は変わらない。生のログは実装者の `probe-rest2.txt`（生成済み 2.4 ms）と `probe-rest3.txt`（同じ行が 143.6 ms＝当時の脚本が「同時 8 本」の後に測っていた形）で、**報告の 2.4 は rest2 の値**。最終の脚本は順序を直してあり、私の取り直しでも 2.2 ms。

### B-3. exe 化の追試

`uv run --no-sync --with pyinstaller python -m PyInstaller --onedir …`（実装者と同じ引数。`PYINSTALLER_CONFIG_DIR` を内向きにし、`%USERPROFILE%\AppData\Local\pyinstaller` は作られていない）。ビルド **16.4 秒**。`dist/image-reviewer` は **116 ファイル・138,339,023 バイト（= 131.9 MiB）**。うち `onnxruntime` 38 MB・`PIL` 11 MB・`numpy` 6.2 MB（実装者の 26.3 MB と違うのは `numpy.libs` の数え方）。複製（`IMAGE_REVIEWER_DATA=…/real`）を指して `image-reviewer.exe serve`: `/api/health` 200 まで **1706 / 528 / 537 ms**（1 回目は冷えている）、`gui_present: false`、`GET /` は 404、`/api/assets?limit=3` は 262。`uv run --no-sync image-reviewer serve` は **1059 / 1059 / 1055 ms**・`gui_present: true`。`dist` と `build` は消した（数字は上に残した）。

## C. 重大（直してから閉じる）

### C-1. G-1（走ったまま壊れた DB の入口）は「書いた接続のキャッシュに載っているページ」の壊れを見ない

**何が起きるか（出荷の形で実測。`cache_exp3.py`）**: アプリと同じく自分の接続で 250 行（0.65 MB）を書いて `wal_checkpoint(TRUNCATE)` した DB の 100 ページ目を外から 0 で潰す。盤上は `quick_check` が `malformed`。その接続の `BackupService.tick()` は **`taken` あり・`error` 無し・`read_only=False`**（控えを取り、書き続ける）。写しの `integrity_check` は `ok`（写しはキャッシュの健全なページから出来る）。1500 行（2.28 MB）では `tick()` が断って `read_only=True`（テストの形）。

**なぜか（`cache_exp2.py`。16 通り）**: 書いた接続は自分が書いたページをページキャッシュに持ち、外からの書き換えを読み直さない。既定の 2 MB に収まる DB は全部そうなる。

| DB | 接続 | P9（mmap 256 MB・cache 既定） | P9 ＋ cache 64 MB | P8-4 の形（mmap 0） | P8-4 ＋ cache 64 MB | 新しい ro 接続 |
| --- | --- | --- | --- | --- | --- | --- |
| 0.65 MB・page 100 | 書いた接続 | **見落とす** | 見落とす | 見落とす | 見落とす | 見つける |
| 0.65 MB・page 100 | 読んだだけ | 見つける | 見つける | 見落とす | 見落とす | 見つける |
| 2.28 MB・page 300 | 書いた接続 | 見つける | **見落とす**（実装者の観察） | 見つける | 見落とす | 見つける |
| 2.28 MB・page 300 | 読んだだけ | 見つける | 見つける | 見落とす | 見落とす | 見つける |

- 実装者の観察（64 MB にすると `test_a_broken_source_does_not_replace_the_seven_healthy_snapshots` が落ちる）は本物だが、**`big_store` は 2.28 MB＝既定のキャッシュをぎりぎり超える DB** なので、テストは保証ではなく境界を見ている。P8-4 の実測時の実データは 1.0 MB（`p9-implementation.md` §2 #12）＝**G-1 は初日の実データには効いていなかった**。いまの実データは主ファイル 3.0 MB ＋ WAL 4.2 MB で、ページによる。
- 公平のために: この形では写しは健全（キャッシュから出来る）なので B-1 の「壊れた写しで 7 世代が埋まる」は起きない。壊れるのは「壊れた DB に書き続けない」の方。`mmap_size` は読んだだけの接続の検知を改善している（P9 の功績）。
- **直し方（推奨）**: `_refuse_if_broken()` の `quick_check` を**新しい読み取り専用の接続**（`db.connect(read_only=True)`）で行う（上の表の右端。28/28 で見つける）。小さい DB（250 行・既定のキャッシュに収まる）で `tick()` が断るテストを足す。そのうえで `cache_size` は**速さだけで決める**（1 万枚の SQL 3 本が 43.6 → 42.5 ms で実利なし＝入れないままでよいが、`db.py` のコメント・§12.2・§16.7-2 の「既定の 2 MB なら見落とさない」は書き直す）。P8-4 の監査の記録にも「`shrink_memory`＋`cache_size=1` で捨てる」が残っていた（当時から知り得た）。

### C-2. 上部バーの枚数の出どころが変わり、実データでは「455 枚」が「262 枚」になった（P8-2 ↔ P9）

- `apps/gui/app.js` の `renderStats()`: 直す前は `${s.assets} 枚`（`/api/stats` の `assets`＝`count(*) FROM asset`＝削除済みを含む）。直した後は `state.total || s.assets`（`/api/assets` の `total`＝既定で段 1〜3 の枚を含まない）。実データは `stats.assets` 455・`total` 262。
- 実測: 私の複製（492 枚・段 1 で 193 枚・生きた 299）を本物の Chrome で開くと上部は **「299 枚」**、`/api/stats` は 492。1 万枚は「10000 枚（先頭 2000 枚を表示）」（この文言は正しく出る）。
- 同じ画面の「すべて」の数（`$('c-all')`）は `s.assets` のまま＝実データで **455**。上部 262・絞り込み 455 が並ぶ。
- `p9-implementation.md` §3-4「実データ（299 枚）では文言が変わらない」は実装者の gui 複製（削除行の無い形で 299 ＝ 299）の話で、実データ（193 枚を段 1 で外した）には当てはまらない。`frontend-design.md` §6 の例「455 枚」も実データでは出ない。
- **直し方（推奨）**: 規則を 1 つ決める（推奨: 上部も「すべて」も**生きた枚**＝262。隠した枚は `#/pending-deletes` に出るので数えない）。`c-all` を `total` に合わせ、§6 の例を直し、`gui_smoke` の `/api/assets` stub に `total` を持たせて 1 件固定する。

### C-3. §12.1 の表の 2 つの数が「実装の値」ではない

1. **「同時 8 本なら 22 ms/枚 → 3.7 分」**（1024px）・「4 ms/枚 → 0.7 分」（256px）: `probe_p9.py` の `probe_real()` が `ThreadPoolExecutor(min(8, cpu))` で `ensure_thumb()` を直に回した値。実装にスレッドプールは無い（`thumbs.py` / `app.py` を grep。§12.2 の「スレッドプール min(8, cpu_count)」は未実装）。画面が 2000 枚のサムネイルを要求したときの並列は FastAPI の同期ハンドラのプール次第。§12.1 の行は「1 スレッド 21.9 分（実測）／並列は未実装（見込み 8 本で 3.7 分）」と書き分けるべき。
2. **「`state=kept`（絞り込み）p95 249.6」**: `make_synthetic_db.py` の `seed_rows()` は `asset.review_state` を直接 UPDATE するが、`create_app()` の起動時 `reconcile()`（監査 B1）が台帳と突き合わせて **1 万枚全部を `unreviewed` に戻す**（stderr に「現在値の写しを台帳から組み直しました: 2209 行」。私の合成も実装者の合成も `review_state` は `unreviewed` 10000・`decision` 0）。絞り込みは 0 件で、「一覧の絞り込みが効く形」という道具の説明は成り立っていない。直し方: `seed_rows()` が `ReviewService`（か `POST /api/reviews`）で判断を入れる。
3. **直し方（まとめ）**: §12.1 と `p9-implementation.md` §2 の 2 行の名札を直す。数の桁は変わらない（`store.assets()` が支配的）ので、合否は動かない。

## D. 中程度（次の段で）

- **D-1 `disk i/o error` を「壊れ」に数えている（D-8 の語彙）。** 一時的な I/O エラー（USB の抜け・ウイルス対策の掴み）にも「バックアップから戻してください」と言う。この語には試験が無い（壊し試験 M7 が生き残る）。推奨: `disk i/o error` は 503 `io_error` で「もう一度」を案内し、復元は勧めない。
- **D-2 `database is locked` が 500 `sqlite_error`。** `busy_timeout` 15 秒の後なので稀だが、内部エラーではなく「混んでいる」。503 ＋ `Retry-After` の方が筋。
- **D-3 `probe_p9.py` は `--out` に相対パスを渡すと壊れる。** `--library` が `check_backup_dir` の「絶対パスで指定してください」で落ち、それ以前の計測でも日次のタイマーが同じ理由で 5 回黙って失敗していた（stderr のみ）。`Path(args.out).resolve()` の 1 行。`--replica` も同じ。
- **D-4 文書が実機の状態より古い。** `handoff.md` §7-1「★ 8790 を sandbox の外で立て直す（日次 0 個）」と `p9-implementation.md` §8-9「実機の日次はまだ取れていない」は、§10 の記録（利用者が `backup_dir` を `.backup/daily` に変えた）と食い違う。実機: 8790 は Explorer → `start-image-reviewer.cmd` → uv → exe の系譜で動き、`.backup/daily/` に `20261018`（263 枚・17:12 JST）・`20261018-171143`（手動）・**`20261019`（455 枚・00:00:15 JST）**。`%USERPROFILE%\image-reviewer-backups` は無い（`default_backup_dir` のまま。§13 の既定が実機では使えない謎は未解決のまま）。`.backup/` は `.gitignore` 済みだが**リポジトリの中・同じドライブ**。
- **D-5 `--include-library` の数は OS のファイルキャッシュに依る。** 実装者 2.40 秒（132 MB/s）、私 0.63 秒（516 MB/s）。§12.1/§12.3 は「冷えた状態」と書くか両方を書く。
- **D-6 `/api/stats` が §12.1 に無い。** 画面は読み込みのたびに `/api/assets?limit=2000` と `/api/stats` を両方呼ぶ。1 万枚で `stats` は p95 130 ms（`meta_json` を 1 万回 `json.loads`）。一覧の段を立てるとき一緒に。
- **D-7 exe の数の単位と冷えた起動。** 131.9 は MiB（バイトなら 138.3 MB）。起動の 1 回目は 1.7 秒（報告は温まった 3 回）。推奨には影響しない。
- **D-8 G-1 で断った後に `_failed()` がもう一度 `_record_error()` を呼び、`read_only` になった DB に書けずトレースバックを吐く**（`cache_exp3` の 1500 行の出力）。`_mark_broken()` が既に記録しているので二重。ログの雑音だけ。
- **D-9 `probe --decide` の表示が `state=None / 掃き出し待ち None`。** `POST /api/reviews` の応答にその鍵が無い（`review_state` / `export_pending`）。道具の名札。
- **D-10 壊し試験の限界。** M1（`temp_store`）と M2（`mmap_size`）を落とすのは pragma の値を見る 1 件だけで、振る舞いの試験は無い（私の `temp_store_repro.py` が振る舞いの根拠）。1 万枚の試験を CI に入れるのは重いので、`temp_store` を外した接続で `ORDER BY` の大きい読みが `%TEMP%` 無しで落ちる最小形（`PRAGMA temp_store_directory` は廃止済みなので、`TMP` 環境変数を書けない所へ向けて 1 万行の一時 b-tree を作る）を 1 件足せるか検討。

**設計とのずれ（8）**

| ずれ | 申告 | 判定 |
| --- | --- | --- |
| §12.2 の `cache_size=-65536` を入れない | 申告あり（§12.2・§16.7-2） | 結論は可。理由は C-1 のとおり書き直す |
| §12.1 一覧 API の目標に届かない | 申告あり | 可（目標を下げていない） |
| §12.2 サムネイルの「スレッドプール min(8, cpu)」が未実装 | **未申告**（§12.1 は実装の値のように読める） | C-3 |
| §12.1 グリッドの計測法（開発者ツールのフレーム時間 → CDP の「最初のカード」） | 申告あり（穴 3） | 可 |
| `frontend-design.md` §6 の「455 枚」と実データ | **未申告** | C-2 |

## E. 壊し試験（ソースは触らず `src/image_reviewer` を写して `PYTHONPATH` で影にする）

`tests/test_db.py` ＋ `tests/test_backup.py`（97 件）。全部に出る `test_the_gui_is_served_even_when_the_db_cannot_be_opened` は影の `GUI_DIR` の副作用（P8-6 と同じ）で、数えない。

| 壊し方 | 結果 |
| --- | --- |
| M1 `PRAGMA temp_store = MEMORY` を外す | 落ちる（`test_the_temporary_btree_goes_to_memory`）。**振る舞い**: 合成 1 万枚で `GET /api/assets` と `?limit=2000` が **500 `sqlite_error`**「DB の操作で内部エラーが起きました（DB が壊れているとは限りません）」`unable to open database file`、`health/db` は 200 ok。実物は 200（1,044 KB） |
| M2 `mmap_size` を外す | 落ちる（同上の 1 件） |
| M3 `_is_corruption()` を常に True | 落ちる 3 件（語彙の 3 通り） |
| M4 `CORRUPTION_WORDS = ()` | 落ちる 3 件（潰したページが 503 `read_only` でなくなる） |
| M5 `sqlite_error` の文言に「バックアップから戻してください」を戻す | 落ちる 3 件 |
| M6 `sqlite_error` を 503 に | 落ちる 3 件 |
| M7 `disk i/o error` を語彙から外す | **生き残る**（D-1） |
| M8 `cache_size=-65536` を足す（§12.2 の形） | 落ちる 4 件（pragma の値・`test_a_broken_source_…`・先頭 4 KB を潰した DB で `cache_size` が投げて開けない 2 件） |
| M9 `mmap_size=0` ＋ `cache_size=-65536` | 落ちる 2 件（pragma の値・`test_a_broken_source_…`＝実装者の観察の再現） |

## F. 回帰と実データ

| 何 | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q` × 3 | **518 passed** × 3（37.3〜37.6 秒。揺れなし） |
| `node tools/gui_smoke.mjs` | **322 ok / NG 0**「すべて ok」 |
| `gui_layout` 11 本（私の複製 8793: `--count 8` / requests / group / asset / tags / jobs / duplicates / pending / pending --ids / library / settings） | **11 本とも「すべて ok」**（3 窓） |
| 実データ（`mode=ro`。前 2026-10-18 23:1x JST → 後 2026-10-19 00:1x JST） | 表の件数 24 表すべて同じ・`asset` 455・`deleted_at` 193・`missing_at` 0・段 1 の 193 行の中身の sha `c6b9064cfa2972e6`・隠した 193 枚の `asset` 行の sha `29022012fc8a9c3d`・判断 3 件の sha `174805d734d5c2e5`・画像の署名 **`d9604560e494c510`**（262 枚・291.1 MB）・455 パス全部の `(size, mtime)` の署名 `5756d7e9cd431324`——**全部同じ**。変わったのは `db.sqlite3-wal` の mtime だけ（8790 の 00:00 JST の日次がチェックポイントした物。中身の署名は同じ） |
| 8790 | PID 7324・`data_dir .data`・一度も止めていない。私が打ったのは `GET /api/health` / `/api/stats` / `/api/backup`（読むだけ） |

複製の注意（H にも）: 実装者の gui 複製には実データの置き場 2 つ（`allow_stage3=1`）と、`gui_layout_seed` が入れた段 3 の行（`seed-1792331644`。`hold_path` は「(削除済み)」、`purge_at` は過去）が残っていた。私の写しでサーバを立てる前に `pending-delete/` を消し、立てた後にその行の元ファイル（ComfyUI の出力 `132800_00001_.png`）が 20:14 JST の mtime のまま在ることを確かめた（動いていない。実データの署名にも含まれ、同じ）。

## G. 質問（推奨つき。待たずに進めてよい）

- **G-1 G-1 の `quick_check` を新しい読み取り専用の接続にするか。** 推奨: **する**（C-1。28/28 で見つける）。合わせて 250 行の試験を足し、`cache_size` は速さだけで判断（入れないままでよい）。
- **G-2 上部バーの「枚」は何を数えるか。** 推奨: 生きた枚（262）に統一し、`c-all` も同じ数に。§6 の例を 262 に。
- **G-3 一覧 API の段をいつ立てるか。** 推奨: 1 万枚が現実になる前に、`/api/stats` の `json.loads` 1 万回（D-6）と一緒に。
- **G-4 §12.2 のサムネイルのスレッドプールを実装するか、§12.1 を「見込み」と書くか。** 推奨: 今は書き分けだけ（C-3）。画面はまず 256px を 2000 枚要求するので、並列の実測は画面の要求の形で取る。
- **G-5 日中の操作をその日の控えに入れる道。** 日次は 00:00 JST の最初の周期で 1 回。利用者の段 1 の 193 行（20:04〜20:12 JST）は 00:00:15 JST まで控えに無かった。推奨: 一括の段 1 / 段 3 の直後に「いま取る」を促す 1 行（`#/pending-deletes` か上部バーの印）。設計の判断。
- **G-6 `disk i/o error` の扱い**（D-1）。推奨: 復元を勧めない。

## H. 作業の記録

- 脚本と生のログ（`.tmp-audit-redo/p9-audit/`）: `sig.py`（署名）・`replica.py`・`probe-all.txt` / `probe-rest.txt`（`probe_p9.py`）・`list_meas.py` / `.out.txt`（内訳）・`cache_exp2.py` / `cache_exp3.py` / `cache_exp2.out.txt`（C-1）・`mut9.py` / `mut9.out.txt`（壊し試験）・`temp_store_repro.py`・`layout11.sh` / `layout-11.txt`・`grid-299.txt` / `grid-10k.txt`・`gui_smoke.txt`・`pytest-3runs.txt`・`sig-before.json` / `sig-after.json`。`cache_exp.py` の「約 2.3 MB」の行は DB が 1.06 MB で 300 ページ目がファイルの外だったので無効（`cache_exp2.py` で作り直した。報告は exp2 / exp3 だけを根拠にしている）。
- 消した物: exe の `dist` / `build` / `picache`（138 MB ＋）・`backups-library`（291 MB × 2）・使い捨ての `w*`・各バックアップの置き場。残り 108 MB（合成 1 万枚・gui と real の複製・脚本）。
- 環境: `uv run --no-sync`・`UV_CACHE_DIR` は repo 内・`%USERPROFILE%` にフォルダを作っていない（PyInstaller は `PYINSTALLER_CONFIG_DIR` で内向き）・ComfyUI に触っていない・コミットしていない（`git status` は `docs/p9-audit-report.md` が untracked なだけ）。
- 事故: **無し**。実データの画像を動かす脚本は書いていない（`probe_p9.py` の `--relink` は合成の中だけ・`--real` は複製の `thumbs/` を消すだけ）。実装者の `grid_timing.mjs` を私のサーバに向けて使った（サーバの中は触らない道具）。
