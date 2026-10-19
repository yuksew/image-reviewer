# 引継書 — image-reviewer / **P10 まで完了**（2026-10-19 時点）

このセッション（dsh・ワークツリー `dsh`）で進めた内容と、**次のセッションがそのまま続けられる形**の引継ぎです。
読む順: **§0 危険な操作 → §1 いまの状態 → §2 Fable との往復 → §3 次の手順**。細部は §4 以降。

> **2026-10-19 の追記（最新。P9 の監査の反映 → 文言の監査 2 つと適用 → P10）**:
> - **P9（仕上げ）の監査の指摘も全部反映した**（判定「合格（条件つき）」。[`p9-audit-triage.md`](p9-audit-triage.md)）——
>   **C-1**（走ったまま壊れた DB の入口を、**書き込んだ接続のページキャッシュ**越しに見ていた →
>   **新しい読み取り専用の接続**で `quick_check`）・**C-2**（画面の「枚」が 262 と 455 で食い違っていた →
>   **生きた枚**に統一）・**C-3**（「同時 8 本」は実装に無い見込みだった・`state=kept` は 0 件への絞り込みだった）。
> - **文言の監査を 2 つ受け、どちらも適用した**:
>   **ワーディング監査**（[`wording-audit-report.md`](wording-audit-report.md) → [`wording-fix.md`](wording-fix.md)。
>   判定「自然」。原因は中国語ではなく**癖 3 つ**・直した 141 件・食い違い 24 行の裁定）と、
>   **日本語 UI の監査**（[`japanese-ui-audit-report.md`](japanese-ui-audit-report.md) →
>   [`japanese-ui-fix.md`](japanese-ui-fix.md)。判定「一部に不揃い」。**`frontend-design.md` §6.1 を
>   規約 A〜F＝通し番号 1〜6 に振り直した**・違反 A16/B11/C30/D17/E11/F9・用語 27 語・質問 G-1〜G-10 は
>   **推奨を全部採用**）。**`design.md` §17 に「画面の語」の列ができた**——「実体」→**ファイル**・
>   「語釈」→**日本語訳**・「控え」→**バックアップ**・「捕獲」→**取り込む**・「入れ物」→**絞り込み**。
> - **P10（段 1 の行を後から進める・実体が無い行を片付ける）が通った**（2026-10-19）。
>   利用者の要望（**一度カタログから外した物をゴミ箱へ／実体が無い物を片付ける**）で、
>   **段 1 が行き止まりだった**のを塞いだ（口 4 つ。**人だけ**・**1 回 200 件**・**段 3 への直行は作らない**・
>   **ファイルは 1 つも消さない/動かさない**）。記録は [`deletions-advance.md`](deletions-advance.md)、
>   決定は [`design.md`](design.md) §16.7、画面の文言は `frontend-design.md` §4.6・§6。
>   **数（私が回して実測）**: `pytest` **547 件**（547 passed・0 failed・40.3 秒）・
>   `gui_smoke` **395 検査（NG 0）**・`gui_layout` **10 画面 × 4 幅＋`pending --ids`**（複製 8797 で。
>   **`--screen tags` は語を植えた複製で 4 幅 ok**。**`--screen pending --ids` の「段 2 の結果の 1 行」だけ
>   4 幅 NG**＝`gui_layout.mjs` の `WANT_STAGE[2]` が「2 枚をゴミ箱へ移しました。」のまま。
>   画面は「2 枚をアプリのゴミ箱へ移しました。」で `frontend-design.md` §6 が正。**検査の 1 行の残件**）。
> - **実データ `.data/`（`mode=ro` で読んだだけ。1 バイトも書いていない）**: **461 行・生きた 267 枚・
>   段 1 の生きた行 194・うち実体が在るのは 7 行**（**187 行が実体なし**。実体が在る 7 行のうち **6 行**は
>   台帳の `asset_id` が古い形＝§6 の罠）。`deletion_log.closed_at` / `close_reason` の**列は
>   2026-10-19 16:48:56 に、トレイの自己検査の穴（監査 A-1）で足されていた**（**控え無し**。
>   行の中身の変化は 0＝194 行・`closed_at` は全部 NULL・461 枚・判断 3 件）。
>   **この列を足したのは利用者の起動ではない**ので、「利用者が立ち上げ直して『まとめて片付ける』を押す番」
>   という案内は**もう当てはまらない**（`pre-topup-<日時>/` の控えは付かない。詳細は
>   [`tray.md`](tray.md) §6 と [`tray-audit-triage.md`](tray-audit-triage.md) A-1）。
>   **押すと 187 件が閉じ、7 件は 409 `file_found` で断られる**（意図どおり。
>   残る 7 行は「アプリのゴミ箱へ移す」で進められる）。
>   **この作業の時点では 8790 は動いていなかった**（`Get-NetTCPConnection` に 8790 が無い。**止めてはいない**）。
> - **P8-5 の監査の条件 3 件（C-1〜C-3）は 2026-10-18 の仕分けで直っていた**
>   （[`p8-5-audit-triage.md`](p8-5-audit-triage.md)。印のボタンの二度押し・読み取り専用の DB で書き込むボタンを
>   置かない・`--screen asset` の段の期待値を API から組む）。**README と `design.md` の「未反映」は古い事実
>   だったので直した**（**段 3 の許可が無い置き場の枚で 4 幅とも ok** を 2026-10-19 に実測）。

> **2026-10-16 12:50 の追記**: **利用者の了解で `onnxruntime`（CPU 版）を入れ、P4 の線 8 を測って達成**しました
> （実画像 4 枚で**語の集合が完全一致**。詳しくは [`p4-line8-note.md`](p4-line8-note.md)）。
> **`git` 管理にして GitHub に push 済み**（`https://github.com/yuksew/image-reviewer`・main・初回コミット）。
> **利用者のアプリはいま止めてあります**（`onnxruntime` の導入で止めた）。**次に起動すると `.data` が v3 → v5** に上がります
> （控えは `.backup/pre-p4-20261016-093705`）。
>
> **2026-10-16 13:00 の追記（その後の状態）**: **アプリは起動済みで、`.data` は v5 に上がりました**（263 枚・判断 3 件は無傷）。
> **利用者の決定でタガーは ComfyUI を優先**します（`settings` の `tagger.engine=comfyui`・`tagger.node=illust`＝`IllustTagger`。
> 内蔵は CPU 版しか入っておらず 1.30 秒/枚、IllustTagger は 0.27 秒/枚のため）。`tagger.comfyui_temp` も入れて
> **投げた複製を消す**ようにしました。**`onnxruntime-gpu` ＋ CUDA の DLL** を入れれば内蔵が最速（0.063 秒/枚）になるので、
> そのときは `tagger.engine=auto` に戻します。
>
> **2026-10-17 02:40 の追記（P7 完了）**: **P7（条件の記録。R12）の P7-0〜P7-4 が全部通り、4 段の監査も受けました**
> （**合格の門は線 6**＝印つきの出力から結果の画像が紐付き、人が合否を記録できる。`probe_p7.py --watch` で通過）。
> - **数（実測）**: `pytest` **403 件**（P7 開始時 285 → +118）・`gui_smoke` **164 検査**・`gui_layout` **8 画面**
>   （比較・要求・まとまり・注記とタグ・語の一覧・ジョブ・**条件の記録**・**記録の一覧**）。
> - **実データ `.data/`**: **v6**（`recipe_record` / `watcher_state` は 0 行・263 枚・判断 3 件は無傷）。**利用者のアプリは 8790 で新コードで稼働中**。
> - **利用者が決めたこと（Q1〜Q6・G-1〜G-7 はすべて推奨どおり）**: 監視の最小形も P7 に入れる／印ありの認定は前方一致＋PNG の `prompt` の保険／
>   `userdata` への設置は P7 では作らない（P3 で）／モデルのフルハッシュは取らない／合否は 1 枚ずつ／手作業の後処理も結果として受け取る。
> - **設計の期待値を 1 つ直した**: 線 2 は **`exact` 182 / `approx` 1 / `impossible` 80**（点検の「183 / 0 / 80」は誤り。
>   1 枚は ja2en で**英訳が PNG に残らない**ため。**監視で英訳を捕まえて `exact` に上がる**のがこの機能の存在理由）。
> - **次の段は P8（重複・削除・5 分の取り消し・バックアップ）**。そのあと P9（仕上げ）。
>
> **P7 で踏んだ罠（§6 に足すべき物）**:
> ① **`/api/jobs` の一覧に `workflow` は無い**（`/api/jobs/{id}` が要る＝2 段。**タグ付けの job も並ぶ**ので `outputs_count: 0` で弾く）／
> ② **`execution_cached` は全部の job に出て `nodes` が空**（「保存ノードが `cached` にあるか」で見分ける）／
> ③ **`subfolder` は Windows でバックスラッシュ**で来る／
> ④ **`/object_info` の一括は 2.39 MB・0.41〜0.91 秒**（**`/object_info/{class_type}` は 0.7〜3 KB・0 ms**。使ったノードだけ引く）／
> ⑤ **`COMFY_DYNAMICCOMBO_V3` の入れ子**（`sampling_mode.temperature` など）を展開しないと**入力キーの検査が誤判定**する／
> ⑥ **SQLite は `ALTER TABLE` で `CHECK` を足せず、外部キーの `ON DELETE` も変えられない**（**表が空のうちに決める**。P7-0 の C-1）／
> ⑦ **`seed` が NULL だと UNIQUE が効かない**（`COALESCE(seed,'')` の式の索引）／
> ⑧ **`asset_location.path` は正規化した鍵**（生の `str(path)` では Windows のドライブの大小文字で当たらない）／
> ⑨ **ComfyUI に繋がらないときは `system_stats` で打ち切る**（全 `class_type` を引き続けると 1 枚 20〜32 秒かけて全部 `impossible` になる）。
>
> **2026-10-17 03:40 の追記（P7 の廃止）**: **利用者の判断で P7（条件の記録。R12）を削除しました**
> （理由: ①「前に作った絵をもう一回作る」ときは PNG を ComfyUI にドラッグすればワークフローが戻るので記録は重複 ②ja2en の英訳ももう一度実行すれば取れる。
> 何を作って何を消したかは [`p7-decision.md`](p7-decision.md)）。
> - **消した物**: サーバ（`recipe.py` / `recipe_export.py` / `watcher.py` / `api/recipes.py` / `api/watcher.py`）・画面（`recipe.js` / `recipelist.js` と
>   `app.js` / `jobs.js` / `index.html` / `styles.css` の配線＝`#/jobs` の監視 1 行も）・道具（`probe_p7.py` / `check_contract_p7.py`、`gui_smoke` / `gui_layout` の P7 の検査）・
>   テスト 5 本と `test_db.py` の v6・契約 `recipe-manifest.schema.json`。**`SCHEMA_VERSION` は 5** に戻した（`db.py` の「v6 はもう無い」の注記は**未追加**）。
> - **数（実測）**: `pytest` **285 件**（403 → 285）・`gui_smoke` **129 検査**（164 → 129）・`gui_layout` **6 画面**（比較・要求・まとまり・注記とタグ・語の一覧・ジョブ）。
>   複製のサーバで `/api/recipes`・`/api/watcher`・`/api/assets/{id}/recipe` は **404**、他の口は 200。
> - **控え**: `.backup/pre-p7-removal-20261017-030324/db.sqlite3`（v6 のまま。`recipe_record` 4 行）。
> - **実データ `.data/` はこの追記の時点（03:55）では `user_version` 6・25 表のまま**（v6 の 6 表は残っていて行は 0。`comfyui.*` の設定だけ消えている。
>   `mode=ro` で確認）。**6 表の DROP と `user_version` 5 への戻しは実装者が再実行する**（`SCHEMA_VERSION = 5` のコードは v6 の DB でも起動する）。
> - **次の段は P8** のまま。上の罠のカタログ（①〜⑨）は P7 以外でも効く（`/object_info/{class_type}`・`ALTER` で `CHECK` は足せない など）ので残す。
>
> **2026-10-18 の追記（P9 完了。仕上げ＝性能の目標を実測で埋めた）**: **`docs/design.md` §12.1 の
> 「目標」の行は全部実測で埋まった**（**未計測 0**）。記録は [`p9-implementation.md`](p9-implementation.md)
> （**測り方・生の値・届かない物・見送った物・exe 化の推奨**）。
> - **届かなかったのは 1 行だけ**: **一覧 API の p95 は 244.7 ms**（目標 20 ms。**目標は下げていない**）。
>   理由は **§12.2 の「一覧」（キーセット改ページ・概算の件数・最小の列）が実装に入っていない**こと。
>   **必要な条件を §12.1 に書いた**（`total` の意味と絞り込みが変わるので、テストと画面の前提を
>   一緒に直す段として立てる）。**実データ 262 枚なら p95 14.3 ms** なので**いまは困らない**。
> - **計測の途中で不具合を 2 つ見つけて直した**: ①**`PRAGMA temp_store = MEMORY` が実装に無く、
>   1 万枚の `GET /api/assets` が 500 になっていた**（`%TEMP%` に書けない置場で一時ファイルを作れない。
>   §12.2 と §6 の罠には最初から書いてあったのに実装に無かった）②**`sqlite_error_handler` が
>   壊れていない DB に「バックアップから戻してください」と言っていた**（P8-6 の監査 **D-8**。語彙を分けた）。
> - **`PRAGMA cache_size = -65536` は入れなかった**（§12.2 の 4 行のうち 1 行だけ採らなかった）。
>   64 MB のページキャッシュに DB 全体が載ると、**走ったまま壊れた DB を live の `quick_check` が
>   見落とす**（実測 `ok: True`）。**P8-4 の監査 G-1 の保証**（壊れた DB に書き続けない）が壊れるので、
>   **速さより安全を取った**（既存のテストがこれを守っている）。
> - **画面を 1 行直した**: 一覧は `limit=2000` で引くので**1 万枚では 2000 枚で切れる**のに、
>   上部が「10000 枚」と言っていた。**「10000 枚（先頭 2000 枚を表示）」**と出すようにした
>   （**数を黙って捨てない**。文言の正は `frontend-design.md` §6）。
> - **数（実測。2026-10-18 に私が回した）**: `pytest` **518 件**（**5 回**回して 5 回とも緑。
>   2〜5 回目は 37.5〜38.2 秒。1 回目は 66.1 秒＝サーバと Chrome が同時に走っていた）・
>   `gui_smoke` **322 検査（NG 0）**・`gui_layout` **11 本すべて ok**（複製 8795）。
> - **exe 化の推奨は「今は作らない」**。**作れることは実測した**（PyInstaller 6.22.3 が Python 3.14 で動き、
>   `--onedir` が **23.7 秒・131.9 MB**。起動は **0.53 秒**で、`uv` 経由の 1.05 秒より速い）が、
>   **`apps/gui` の解決が 1 か所足りず画面が出ない**（`gui_present: false`）。**配布しないなら要らない**。
>   必要な作業の一覧は `p9-implementation.md` §6-4。
> - **見送った物**: **768px の上部バー**（**溢れは 0** なので実害なし。直すには
>   `gui_layout` の `VIEWPORTS` に狭い窓を足すのが先）・**一覧の仮想グリッドとページ送り**・
>   **`--no-hash` の走査**（実装に無い）。
> - **実データは無傷**: **455 枚・段 1 の 193 行・判断 3 件・`missing_at` 0 件**のまま
>   （画像の署名 `d9604560e494c510` と `.data` の署名 `ae60041b0b0b5365` が**前後で同じ**）。
>   **（2026-10-19 の注記）この「無傷」はこの時点（2026-10-18）の話。** そのあと **2026-10-19 16:48:56 に、
>   トレイの自己検査の穴で実データの `deletion_log` に 2 列が足された**（行の中身の変化は 0・控え無し。
>   [`tray.md`](tray.md) §6）。**画像と行は今も動いていない。**
>   **§14 の段はこれで全部済み**——次にやるのは**利用者の判断待ち**（再リンクの画面・
>   一覧 API の改ページ・`--include-library` を日次に載せるか・exe 化）。**トレイは 2026-10-19 に作った**。
>
> **P8 の追記（2026-10-18。重複・削除・バックアップ）**: **P8 の小段（P8-0〜P8-5）が全部通りました**
> （P8-0 = v6 の表と `backup-manifest` の契約／P8-1 = 重複の検出と整理／P8-2 = 削除の 3 段階と 5 分の取り消し／
> P8-3 = 重複と削除の画面／P8-4 = バックアップと復元／P8-5 = 設定と文言の仕上げ）。
> **合格の線に数えるのは P8-1〜P8-4**（**P8-0 は機能を足さない段・P8-5 は画面の仕上げなので数えない**。P5-3 と同じ扱い）。
> 点検 1 回（[`p8-review-report.md`](p8-review-report.md) ＋ [`p8-review-triage.md`](p8-review-triage.md)）と
> **6 本の監査＋3 本の再確認**（[`p8-0-audit-report.md`](p8-0-audit-report.md) / [`p8-1-audit-report.md`](p8-1-audit-report.md) /
> [`p8-2-audit-report.md`](p8-2-audit-report.md) ＋ [`p8-2-audit-recheck.md`](p8-2-audit-recheck.md) /
> [`p8-3-audit-report.md`](p8-3-audit-report.md) ＋ [`p8-3-audit-recheck.md`](p8-3-audit-recheck.md) /
> [`p8-4-audit-report.md`](p8-4-audit-report.md) ＋ [`p8-4-audit-recheck.md`](p8-4-audit-recheck.md) /
> [`p8-5-audit-report.md`](p8-5-audit-report.md)）を受け、
> 判定はどれも「合格（条件つき）」→ **指摘は全部反映**（P8-3 の再確認は**合格（条件なし）**。
> **P8-5 の条件 3 件だけは未反映**——文書化の後に出たため。→ §3 の 0）。
> **（2026-10-19 の注記）この 3 件は 2026-10-18 の仕分け（[`p8-5-audit-triage.md`](p8-5-audit-triage.md)）で
> 反映済み。上の最新の追記を見よ。**
> - **数（実測。2026-10-18 に私が回した）**: `pytest` **477 件**・`gui_smoke` **291 検査**（すべて ok）・
>   `gui_layout` **10 画面＋`pending --ids` の 11 本**（比較 / 要求 / まとまり / 注記とタグ / 語の一覧 / ジョブ /
>   重複の整理 / 最近の削除 / 削除の確認つき / ライブラリの下部バー / 設定。**11 本とも ok**）。
> - **実データ `.data/`**: **v6・263 枚・判断 3 件・削除 0 件**（`deletion_log` も `delete_request` も 0 行）。
>   **利用者が実際に押した 2 件**が残っている——「**別物として確定**」1 件（`duplicate_exclusion`）と、
>   「**まとまりにする**」1 件（`review_group` の `kind='duplicates'` / `policy='pick_one'`、2026-10-17T20:19:02Z）。
>   `root.allow_stage3` は `illust-authoring` の置き場（262 / 263 枚）にだけ 1（Q8）。pHash は 263 / 263 枚に入っている。
> - **P8 の決定は [`design.md`](design.md) §16.6 に反映済み**（Q1〜Q8・3 段階と 5 分の窓・`os.rename`・凍結した一覧だけを消す・
>   最後の 1 つは 409・別ボリュームは 409・`allow_stage3`・重複は pHash ≤ 6・帯の保証は距離 15・バックアップの 5 つ・
>   `restore` の sha256 照合・読み取り専用で起動する道・`import` で `create_app()` を走らせない）。`README.md` も直した。
> - **⚠ 実機のバックアップはまだ取れていない。** 8790（利用者のアプリ）は **dsh の sandbox の子プロセス**として
>   立っているので、**既定の `%USERPROFILE%\image-reviewer-backups` に書けない**（`GET /api/backup` の
>   `last_error` に `WinError 5`・`count 0`・`ticks` は進む。P8-4 の再確認 B-1'）。
>   **利用者が自分の端末（sandbox の外）で 8790 を立て直す**必要がある（「取っていない（不安）」への答えは、
>   コードではなく**この 1 操作**で完成する）。P8-5 で**上部バーと `#/settings` に失敗の全文を出す**ようにしたので、
>   いまは画面で見える。
>   **（P9 の監査 D-4。この段落は古くなっていた）** 実際には 8790 は **Explorer → `start-image-reviewer.cmd`** の
>   系譜で立っていて（sandbox の子ではない）、**利用者が置き場を `.backup/daily` に変えた**ので**日次は取れている**:
>   `20261018`（263 枚・17:12 JST）・`20261018-171143`（「いま取る」）・**`20261019`（455 枚・00:00:15 JST）**。
>   **`%USERPROFILE%\image-reviewer-backups` は無い**（既定の置き場が実機で使えない謎は未解決のまま）。
> - **再リンク（合格の線 9）は P8-6 として作った（2026-10-18）。** P8-3 が指示書の段で「重複と削除の画面」に
>   置き換わって残っていた物で、口は `POST /api/locations/relink`（**人だけ**。`exact` / `nearby`）と
>   `GET /api/locations/missing`（**読むだけ**）の 2 つ。**中身の `sha256` が一致したときだけ繋ぎ、pHash は使わない**。
>   **ファイルは 1 つも動かさない**（`asset_location` の 1 行を `UPDATE` し、`location_history` に 1 行残す）。
>   **画面は無い（口だけ）**。実装の記録は [`p8-6-relink.md`](p8-6-relink.md)（**事故 3 件目**と `create_app()` の硬化もそこ）。
>   `design.md` の §5.1・§5.8・§6.1・§14・§15・§16.6 に反映した。**この時点ではトレイ（常駐）も無かった**（`design.md` §16.6。**2026-10-19 に作った**＝§16.8）。
> - **次の段は P9（仕上げ）**。未計測の性能（1024px サムネ・一覧 API・表示速度・**`--include-library` の 292 MB**）の
>   実測、テストの締め、**exe 化の判断**（[`design.md`](design.md) §14 の P9 の行）。
>
> **P9 で踏んだ罠**

- **`PRAGMA temp_store = MEMORY` が実装に無いと、1 万枚で一覧が 500 になる**（`ORDER BY` が一時ファイルを作り、
  `%TEMP%` に書けない置き場で `unable to open database file`）。**455 枚では起きない**ので、
  **1 万枚を開くまで誰も気づかない**（§12.2 にも §6 にも「`temp_store = MEMORY` で回避」と書いてあったのに、
  **実装に落ちていなかった**）。直した（`db.py`）。
- **`PRAGMA cache_size` を大きくすると、走ったまま壊れた DB の検知が壊れる**（64 MB に DB 全体が載ると
  live の接続の `quick_check` が `ok: True` を返す）。**既存のテスト
  （`test_a_broken_source_does_not_replace_the_seven_healthy_snapshots`）が落ちて分かった**——
  **性能の pragma は安全の保証とぶつかることがある**。
- **`uv run` を止めても python が生き残る**ので、**起動時間の計測で前のサーバの 200 を拾う**
  （「17 ms で上がった」と出た）。**回ごとに別のポート**を使い、**`taskkill /T` で木ごと**止める。
- **前の計測が残したサムネイルがあると「初回生成」を測れない**（`ensure_thumb()` が「在る」を返し、
  **測っている物が「配信」に変わる**。実測で「初回生成 2 ms」と出た）。**消してから測る**。
- **測る道具の「増えなくなった時刻」を毎フレーム上書きしない**（読み取った時刻を測ってしまう。
  グリッドの計測で「全部そろうまで 1.8 秒」という**嘘の値**が出た。未設定のときだけ書くように直した）。
- **`gui_layout --screen pending --ids` には生きている枚を渡す**（外した枚だと画面がパスを引けず、
  段 3 の 1 行が「確かめられない」になり**必ず NG**。**あれが正しい動作**）。
- **PyInstaller は `%USERPROFILE%\AppData\Local\pyinstaller` にキャッシュを掘る**（sandbox の外に出たくなければ
  `PYINSTALLER_CONFIG_DIR` を内向きに）。**`--add-data` の相対パスは spec の場所から解決されて失敗する**（絶対パスにする）。

**P8 で踏んだ罠（§6 に足した）**: ① `os.replace` は既存を**黙って上書きする**（取り消し・移動は `os.rename`。WinError 183）／
> ② **索引名は DB 全体で一意**（`IF NOT EXISTS` が黙って何もしない）／③ `quick_check` は**例外を投げることもある**／
> ④ **先頭 4 KB を潰すと開けない**（2 ページ目を潰すと「開けるが壊れている」）／⑤ **8bit × 8 本の帯は距離 7 までしか保証できない**／
> ⑥ `import image_reviewer.app` で `create_app()` が走ると**実データに書く**／⑦ **sandbox の子プロセスは `%USERPROFILE%` に書けない**／
> ⑧ **版を上げずに表を変えるときも控えを取る**（`stuck_reason` の事故）／⑨ **長い会話の fork は文脈が尽きる**（重い段は素の `subagent`）／
> ⑩ **画面の検査の前提は実装が変わると古くなる**（`--screen asset` が印なしで必ず NG＝P8-5 の監査 C-2）／
> ⑪ **`busy` を付け忘れたボタンは二度押しで 2 回 POST**（P8-5 の監査 C-1）。
> ⑫ **`create_app()` を env 無しで呼ぶと実データを書き込み可で開く**（P8-6 の事故 3 件目。`import` で走る・
>   検証スクリプトが呼ぶ・検証サーバに env を付け忘れる、の 3 つの型はどれも同じ形。**開く前に `RuntimeError`** にして塞いだ）。

---

## 0. 最初に読む: 触ってはいけないもの・危ない操作

| 危ないこと | なぜ | どうする |
| --- | --- | --- |
| **利用者のアプリを止める/干渉する** | `image-reviewer serve --port 8790` が動いていて（`Get-Process image-reviewer` で確かめる。**2026-10-18 08:38 起動の個体**は**画面が P8-5・裏側が P8-4 まで**）、**`.venv` の exe を握っています** | **`uv run …` は `os error 32` で落ちます。必ず `uv run --no-sync …`** か `.venv\Scripts\python.exe` を使ってください。**止めない**（止めてよいかは利用者に確認） |
| **実データ `.data/` を書き換える** | 実データは **v6**（2026-10-18 時点: **263 枚・判断 3 件・削除 0 件**・`duplicate_exclusion` 1・`review_group` 1）。**移行待ちはもう無い**（v6 に上がり、**画面は P8-5・裏側のプロセスは P8-4 まで**で稼働中） | **`mode=ro` でしか開かない**。**壊す試験・検証は必ず複製で**（複製は `sqlite3` の `backup()`。**`cp` だけだと WAL が抜けて判断 3 件が消える**）。使い捨ては `.tmp-audit-redo/` |
| **版を上げずに表を変える**（`ALTER TABLE` のトップアップ） | P8-4 で実データに `deletion_log.stuck_reason` が**控え無しで**足された（事故 2 件目）。**P10 の `closed_at` / `close_reason` も、2026-10-19 16:48:56 にトレイの自己検査の穴で控え無しで足された（事故 4 件目・行の変化 0）** | **変える前に `pre-topup-<日時>/` の控えを取る**（`pre-migrate-*` と同じ）。**足す物の一覧は `db.TOP_UP_COLUMNS` が正**。**控えの置き場が scratch（`.tmp-*`）だと一緒に消える**——実データを開き得る道具の控えは、**消さない場所**へ向ける |
| **`IMAGE_REVIEWER_DATA` を付けずに `create_app()` を呼ぶ** | **P8-6 の事故 3 件目**（検証スクリプトが env を付け忘れ、**実データを書き込み可で開いた**。`location_history` の 3 列と `settings.backup.last_error` が書き換わり、**行の変化は 0**） | **`create_app()` は env が無ければ開く前に `RuntimeError`**（**1 バイトも書かない**）。**既定の `.data` を明示的に指すのは `cli serve`（`serve_data_dir()`）だけ**。**実データを触り得るコマンドには必ず `IMAGE_REVIEWER_DATA=<複製>`**（`mode=ro` も同じ）。控えは `.backup/pre-p8-6-20261018-100443/` |
| **`cli serve` を env 無しで起こす**（事故 4 件目の型） | **`create_app()` の検査は `cli serve` を通す**（`serve_data_dir()` が既定の `.data` を明示するので、`RuntimeError` にならない）。道具（トレイ・自己検査・駆動）が**引き継いだ環境に任せて** `cli serve` を起こすと、**環境が空なら実データを開く** | **道具は子に `IMAGE_REVIEWER_DATA` を必ず明示して渡す**（消して既定に任せない）。**検査・駆動の写し（`-DefineOnly`）は空の置き場と実データを断る**。自己検査は**使うポートが空いていなければ 1 つも起動せず exit 2**（`tray.md` §4.0・§5） |
| **バックアップをエージェントの sandbox の中で取ろうとする** | 既定の置き場 `%USERPROFILE%\image-reviewer-backups` は **sandbox の子プロセスからは書けない**（`WinError 5`。P8-4 の再確認 B-1'）。いまの 8790 もこれで**日次が 0 個** | 検証では `IMAGE_REVIEWER_BACKUP_DIR` か `--out` で**リポジトリの中の `<data>` の外**へ向ける。**実機の日次は利用者が sandbox の外で 8790 を立て直してから**（`GET /api/backup` の `count` が 1 以上になったことを確かめる） |
| `.backup/` を消す | 移行前の控え | `C:\work\image-reviwer\.backup\`（**9 フォルダ**。`pre-p4-*` / `pre-p7-removal*` / `pre-p8-0-*` / `pre-p8-4-20261017-232148` / **`pre-p8-6-20261018-100443`（再リンクの実装の開始）**）。**消さない** |
| 8790 を検証に使う | 利用者のアプリが使用中 | 検証のサーバは **8791〜8799** を使う |

環境: `$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"` が**必須**（無いと `uv` が失敗します）。

---

## 1. いまの状態

### 終わったこと

| 段 | 状態 | 証拠（文書） |
| --- | --- | --- |
| **P5（判断と比較）** | 完了（前セッションまで。実行込みの監査 3 本＋修正の再監査済み） | `docs/p5-*-audit-redo.md`、`docs/p5-fix-audit-report.md` |
| **P6（要求と注記。R10/R11）** | **完了**。設計 → 点検 → **P6-0 / P6-1a / P6-1b / P6-2 を実装** → **各段を Fable が実行込みで監査** → 指摘を全部反映 | `docs/p6-design.md`（944 行）、`docs/p6-review-report.md` ＋ `docs/p6-review-triage.md`、`docs/p6-0-audit-report.md` / `p6-1a-` / `p6-1b-` / `p6-2-audit-report.md` ＋ `docs/p6-*-audit-triage.md`、`docs/p6-1a-implementation.md` / `p6-1b-` / `p6-2-implementation.md` |
| **P6 の朝のまとめ** | 完了。利用者の 6 問の回答を反映済み（`design.md` §16.4 に決定 9 件） | `docs/p6-morning-report.md` |
| **P4（タグと語釈。R3/R7）の設計** | 完了。点検 2 回（本文＋`known` の再点検）を通し「これで実装してよい」 | `docs/p4-design.md`（952 行）、`docs/p4-review-report.md`（§I・§J 含む）、`docs/p4-review-triage.md` |
| **P4-0（v5 の表と契約）** | 実装完了・**監査は「合格」**（ただし §3 の v5 DDL の修正が要る） | `docs/p4-0-audit-report.md` |
| **P4-1（タガーと背景ジョブ）** | 実装完了・**監査は「線 1・2・7 通過」** → 指摘 3 件＋中程度は**反映済み** | `docs/p4-1-audit-report.md` |
| **P4-2（日本語の語釈）** | 実装完了（**278 passed**）・**監査は「合格。P4-3 へ進んでよい」** → 指摘（B-1 / C-1・C-2・C-3 / E）は**反映済み**（**282 passed**） | `docs/p4-2-implementation.md`、`docs/p4-2-audit-report.md` ＋ [`p4-2-audit-triage.md`](p4-2-audit-triage.md) |
| **P4-3（タグの画面）** | **完了**。実装 → 監査「直してから閉じる」→ **指摘 10 件を全部直した** → **再確認で「P4 を閉じてよい」**。再確認で新しく出た 2 件（**`GET /api/tags` の頁送りが壊れていた**・`gui_layout` の行高検査）も**私が直した**。**284 passed**・`gui_smoke` すべて ok・`gui_layout` **6 画面**すべて ok（**247 語の画像**も ok） | 記録 `docs/p4-3-implementation.md`、監査 `docs/p4-3-audit-report.md`、仕分け [`p4-3-audit-triage.md`](p4-3-audit-triage.md)、再確認 `docs/p4-3-audit-recheck.md` |
| **P4-1 の線 8**（内蔵と ComfyUI の語の一致） | **達成**（2026-10-16。`onnxruntime`（CPU 版）を入れて実画像 4 枚で**語の集合が完全一致 4/4**。内蔵 1.30 秒/枚・ComfyUI の WD14 ノード 2.57 秒/枚）。**途中で不具合 1 件を発見して直した**（`BuiltinTagger.tag()` が `name` を受けず、内蔵のときだけ全件 `TypeError` で失敗） | [`p4-line8-note.md`](p4-line8-note.md) |
| **`git` 管理 / GitHub** | **済み**。`https://github.com/yuksew/image-reviewer`（PUBLIC・main）。`.gitignore` は `.data/`・`.backup/`・`.tmp-audit-redo/`・`.venv/`・`.uv-cache/`・`tmp*/`・`.claude/skills/`（ジャンクション）を除外。`.gitattributes` で改行を LF に固定 | `git log` の初回コミット |
| **P7（条件の記録。R12）の設計** | **廃止（2026-10-17。利用者の判断）**。廃止前は **完了**（982 行。点検 → 仕分け → 反映済み。**Q1〜Q6 と G-1〜G-7 は推奨どおりで確定**） | [`p7-design.md`](p7-design.md)、`docs/p7-review-report.md` ＋ [`p7-review-triage.md`](p7-review-triage.md) |
| **P7-0（v6 の表と契約）** | **廃止（2026-10-17。利用者の判断）**。廃止前は **完了 → 監査「合格（条件つき）」→ 条件を反映済み**（**G-1〜G-5**＝`export_id` の CASCADE・`CHECK` 3 本・`noside`…実際は **`noseed`**・`ix_export_attempt` を外す・契約の `required`／**F-1** のテストの穴 5 通りは**壊して 5/5 落ちる**のを確認／**E-1〜E-3** の設計の字） | `docs/p7-0-audit-report.md` ＋ [`p7-0-audit-triage.md`](p7-0-audit-triage.md)、`docs/p7-0-implementation.md` |
| **P7-1（記録と判定）** | **廃止（2026-10-17。利用者の判断）**。廃止前は **完了**（実装 → 監査「直してから次へ」→ **指摘 A-1〜A-4 / B-1〜B-3 / C-1〜C-3 / G-1〜G-6 を反映**）。`probe_p7.py --judge` が **`exact` 182 / `approx` 1 / `impossible` 80**（1 枚は ja2en で英訳が PNG に無い＝**この記録の存在理由**。**監視で英訳を捕まえて `exact` に上がる**） | `docs/p7-1-implementation.md`、`docs/p7-1-audit-report.md` ＋ [`p7-1-audit-triage.md`](p7-1-audit-triage.md) |
| **P7-2（書き出し）** | **廃止（2026-10-17。利用者の判断）**。廃止前は **完了**（`mode` 3 つ・検査・印・seed 違い・manifest・`check`/`export`/`exports` の口）。**監査は P7-4 と一緒に受けた**（A-3 の「口が記録時の語と混ぜている」は P7 を閉じる修正で直した） | `docs/p7-2-implementation.md` |
| **P7-3（監視と結果の紐付け）** | **廃止（2026-10-17。利用者の判断）**。廃止前は **完了 → 監査「直してから次へ」→ A-1〜A-3 を反映 → 再確認で「A-1〜A-3 は直った」**（**25 件 → 25 行**・古い順・上限で基準を上げない・詳細失敗の再試行・**再起動で `GET /api/watcher` が 200**・**英訳を捕まえて `approx` → `exact`**）。**再確認で残り 4 件（sidecar の置き場・根の通知・紐付けの seed・`note` の消失）＋ `_top_up_v6` の `CHECK` ＋ `texts` の二重計上を、P7-4 と一緒に直した** | `docs/p7-3-implementation.md`、`docs/p7-3-audit-report.md`、[`p7-3-audit-triage.md`](p7-3-audit-triage.md)、`docs/p7-3-audit-recheck.md` |
| **P7-4（画面）** | **廃止（2026-10-17。利用者の判断）**。廃止前は **完了 → 監査「直してから次へ」→ A-1〜A-3（押しても動かない・入口が見えない・書き出し時の語が出ない）＋ B-1・C-1/C-2/C-4 を P7 を閉じる修正で反映** | `docs/p7-4-implementation.md`、`docs/p7-4-audit-report.md` |
| **P8-0（v6 の表と契約）** | **完了**。v6 の 5 表（`deletion_log` / `delete_request` / `duplicate_exclusion` / `phash_band` / `pending_delete_preview`）＋列（`asset.deleted_at` / `root.allow_stage3` / `job.cancel_requested`）・`backup-manifest` の契約・`review.json` を変えないテスト。**機能は足さない**（合格の線 1）。**索引名が DB 全体で一意**な罠をここで踏んだ（`ux_delete_token`） | `docs/p8-0-implementation.md`、`docs/p8-0-audit-report.md` ＋ [`p8-0-audit-triage.md`](p8-0-audit-triage.md) |
| **P8-1（重複の検出と整理）** | **完了 → 監査「合格（条件つき）」→ 全部反映**。pHash の背景ジョブ（`POST /api/duplicates/compute`）・**帯を 4bit × 16 本に作り直した**（監査 B-1）・完全重複と準重複・`suggested_id`・除外と解除・まとまり。**実データで 21 群 / 57 枚**（完全重複 0 群） | `docs/p8-1-implementation.md`、`docs/p8-1-audit-report.md` ＋ [`p8-1-audit-triage.md`](p8-1-audit-triage.md) |
| **P8-2（削除の 3 段階と 5 分の取り消し）** | **完了 → 監査「合格（条件つき）」→ 全部反映**（A3 窓の間は `missing_at`・B-1 台帳を先に書く・B-2 失敗したら `purge_at` を NULL・B-3 実削除は錠の下・C-1 人は誰の削除でも戻せる・C-2 `S_IWRITE`・C-3 資産と場所の単位）。再確認の軽微 2 件も反映 | `docs/p8-2-implementation.md`、`docs/p8-2-audit-report.md` ＋ [`p8-2-audit-recheck.md`](p8-2-audit-recheck.md) / [`p8-2-audit-recheck-triage.md`](p8-2-audit-recheck-triage.md) ＋ triage |
| **P8-3（重複と削除の画面）** | **完了 → 監査「合格（条件つき）」→ 反映 → 再確認「合格（条件なし）」**。`#/duplicates`・`#/pending-deletes`・削除の入口 3 つ（拡大・下部バー・まとまり）・`tools/gui_layout_seed.py`（前提の行を複製の中に作る）。**再リンクはこの段に来ず、後の P8-6 で実装した**（下の P8-6 の行） | `docs/p8-3-implementation.md`、`docs/p8-3-audit-report.md` ＋ [`p8-3-audit-recheck.md`](p8-3-audit-recheck.md) ＋ [`p8-3-audit-triage.md`](p8-3-audit-triage.md) |
| **P8-4（バックアップと復元）** | **完了 → 監査「合格（条件つき）」→ 全部反映**（B-1 **壊れた写しを採用しない**・C-1 `restore` は `db_sha256` を照合・C-2 掴まれていれば 409 の 1 行・C-3 読み取り専用でも読める口は読める・D-2 `pre-topup-*` の控え・G-8 `import` で `create_app()` を走らせない）。**実機の日次だけは未達**（sandbox。再確認 B-1'） | `docs/p8-4-implementation.md`、`docs/p8-4-audit-report.md` ＋ [`p8-4-audit-recheck.md`](p8-4-audit-recheck.md) ＋ [`p8-4-audit-triage.md`](p8-4-audit-triage.md) |
| **P8-5（画面の仕上げ。合格の線に数えない）** | **完了 → 監査は「合格（条件つき）」→ 条件 3 件も反映済み（2026-10-18）**。`#/settings` のバックアップ（最後の失敗の全文・7 世代・**取り直す**・置き場）と**置き場ごとの「段 3 を許す」印**・上部バーの「バックアップに失敗しています」と「走査中です」・段 3 の出し分け・文言の追い込み。**トレイは P8-5 では作らなかった**（2026-10-19 に別段で作った＝[`tray.md`](tray.md)）。口は `GET /api/scan` の 1 つだけ足した。**条件 3 件（C-1〜C-3）**: `setAllow` の二度押し・`backupHtml` の `read_only`・`--screen asset` の段の期待値（**2026-10-19 に「許可なしの置き場の枚で 4 幅 ok」を実測**）。**画面の語は「取り直す」に統一した**（下の 0 の D-1） | `docs/p8-5-implementation.md`、[`p8-5-audit-report.md`](p8-5-audit-report.md)、[`p8-5-audit-triage.md`](p8-5-audit-triage.md) |
| **P8-6（参照切れの再リンク。合格の線 9）** | **完了。2026-10-18**（**監査と仕分けも済み**＝[`p8-6-audit-report.md`](p8-6-audit-report.md) ＋ [`p8-6-audit-triage.md`](p8-6-audit-triage.md)）。`POST /api/locations/relink`（**人だけ**。`exact` = 新しいファイル / `nearby` = 探すフォルダ）と `GET /api/locations/missing`（**読むだけ**）・`location_history` に `to_path` / `reason` / `actor`（**版は上げない**＝`pre-topup-*` の控え）・**`create_app()` の硬化**（**`IMAGE_REVIEWER_DATA` が無ければ開かない**）・**事故 3 件目**（実データに 3 列が控え無しで入った。**行の変化は 0**。控え `.backup/pre-p8-6-20261018-100443/`）。**画面は作っていない**（口だけ）。`tools/probe_p8.py --relink` が **16 行すべて OK** | [`p8-6-relink.md`](p8-6-relink.md)、[`p8-6-audit-report.md`](p8-6-audit-report.md) |
| **P8 の合格の線（P8-1〜P8-4）** | **済み。2026-10-18**（**残っていた再リンク＝線 9 も P8-6 で実装済み**）。決定は [`docs/design.md`](design.md) §16.6 に反映済み。**画面の仕上げ（P8-5）の監査の条件 3 件も 2026-10-18 に反映済み** | `docs/design.md` §14・§16.6、[`p8-5-audit-triage.md`](p8-5-audit-triage.md)、[`p8-6-audit-triage.md`](p8-6-audit-triage.md) |
| **P9（仕上げ）** | **完了（2026-10-18）**。**§12.1 の「目標」の行を全部実測で埋めた**（**未計測 0**）。届かなかったのは**一覧 API の 1 行だけ**（p95 **244.7 ms** / 目標 20 ms。**目標は下げていない**。理由と必要な条件は §12.1）。計測の途中で **`PRAGMA temp_store = MEMORY` の欠落**（1 万枚の `GET /api/assets` が 500 になっていた）と **D-8**（壊れていない DB に復元を勧めていた）を直し、**一覧で切った枚数を画面に出した**。道具は `tools/make_synthetic_db.py`（1 万枚の合成 DB）と `tools/probe_p9.py`（**サーバ内**の計測）。**監査の指摘（C-1〜C-3）も 2026-10-19 に全部反映**（[`p9-audit-triage.md`](p9-audit-triage.md)） | [`p9-implementation.md`](p9-implementation.md)、[`design.md`](design.md) §12.1・§12.2・§12.3・§16.7 | [`docs/design.md`](design.md) §14 |
| **P10（段 1 の行を後から進める・実体が無い行を片付ける）** | **完了（2026-10-19）**。利用者の要望（**一度カタログから外した物をゴミ箱へ／実体が無い物を片付ける**）で、**段 1 が行き止まりだった**のを塞いだ。口は 4 つ（`POST /api/deletions/{id}/advance`・`POST /api/deletions/advance`・`POST /api/deletions/{id}/close`・`POST /api/deletions/close`。**人だけ**・**1 回 200 件**・**段 3 への直行は作らない**・**ファイルは 1 つも消さない/動かさない**）。`deletion_log.closed_at` / `close_reason` は**版を上げずに** `TOP_UP_COLUMNS` で足した（**実データの列は 2026-10-19 16:48:56 にトレイの自己検査の穴で足された**＝事故 4 件目。控え無し・行の変化 0。§0 の最新の追記と [`tray.md`](tray.md) §6）。**監査はこれから**（Fable が `docs/p10-audit-report.md`） | [`deletions-advance.md`](deletions-advance.md)、[`design.md`](design.md) §5.8・§6.1・§14・§16.7、`frontend-design.md` §4.6・§6 |
| **トレイ（タスクトレイ常駐。P11 相当）** | **作った（2026-10-19）→ 監査「直してから次へ」→ 全部直した（2026-10-19）→ 再確認「直してから次へ」→ 直した（2026-10-20）**。監査では **A-1（実データに 2 列）・A-2（他人のサーバを止め得た）**、B・C・D・F・G を反映。**再確認**では **A-1（4 ポートの確認が 8795 しか見ておらず、8796 の他人のサーバを止めた）・B-1（駆動 `-DriveScript` に `-DataDir` の断りが効かず既定の `.data` を開く）・C-1（相対パスをトレイの現在地で解く）・C-2（後始末が他人を巻き込む）**と D〜F を反映。**自己検査は 55 → 115 → 133 検査**、壊し試験は 13 通り＋再確認の 8 通りが全部落ちる。**この作業では実データを `mode=ro` でしか開いていない**（1 枚も動かしていない。461 → 463 枚・`.data` の mtime 23:42/00:00 は**利用者の利用と片付け**でこの作業の前） | [`tray.md`](tray.md)、[`tray-audit-report.md`](tray-audit-report.md)、[`tray-audit-triage.md`](tray-audit-triage.md)、[`tray-audit-recheck.md`](tray-audit-recheck.md)、[`tray-recheck-triage.md`](tray-recheck-triage.md) |

**いまの数（実測。2026-10-19 に私が回した）**: `pytest` **547 件**（**547 passed・0 failed**・40.3 秒。
**並行して実データを読む者がいると `test_data_dir_guard.py` の 1 件が落ちうる**＝§6 の罠。
実際に 2 回目の全体で **546 passed / 1 failed**、単独では 4 passed、3 回目は 547 passed）。
`gui_smoke` **395 検査（NG 0）**。`gui_layout` **10 画面 × 4 幅**（`VIEWPORTS` は 1400・1024・1200・1920）＋
**`pending --ids` の 11 本目**を**複製 8797** で回した（**`--screen tags` は語を植えた複製で 4 幅 ok**。
**`--screen pending --ids` の「段 2 の結果の 1 行」だけ 4 幅 NG**＝`gui_layout.mjs` の `WANT_STAGE[2]` の残件。
下の §6）。**`--screen asset` は段 3 の許可が無い置き場の枚でも 4 幅 ok**（P8-5 の C-2 が直っている証拠）。
`SCHEMA_VERSION = 6`。**実データは v6・461 行（生きた 267 枚）・段 1 の生きた行 194・判断 3 件**。
**うち実体が在るのは 7 行**（187 行が実体なし。実体が在る 7 行のうち 6 行は台帳の `asset_id` が古い形）。
**`deletion_log.closed_at` / `close_reason` の列は、2026-10-19 16:48:56 にトレイの自己検査の穴で
実データに足された**（**事故 4 件目**。控えは無し＝`.tmp-tray\backups` と一緒に消えた。**行の変化は 0**）。
**この列を足したのは利用者の起動ではない**ので、「利用者が立ち上げ直したときに `pre-topup-<日時>/` の
控えが付く」という案内は**もう当てはまらない**（`missing_top_ups()` は空。事後の控えは
`.backup/pre-tray-fix-20261019-204253/`）。原因と直しは [`tray-audit-triage.md`](tray-audit-triage.md) A-1。
**この作業では実データを `mode=ro` でしか開いていない**（画像は 1 枚も動かしていない）。

### いま走っているもの

**利用者のアプリは 2026-10-19 の時点で 8790 に居ません**（`Get-NetTCPConnection` に 8790 が無い。
**こちらから止めたのではなく、もともと動いていなかった**。最後に確認したのは 2026-10-18 08:38 起動の個体 PID 7324）。
**次に利用者が立ち上げ直した時点**で、P10 の 4 つの口が使えるようになる（`closed_at` / `close_reason` の
**列は 2026-10-19 16:48:56 に既に足されている**ので、`pre-topup-<日時>/` の控えは**もう付かない**。
足したのは利用者の起動ではなく**トレイの自己検査の穴**＝事故 4 件目・**行の変化は 0**）。
**日次のバックアップは `.backup/daily` に 3 世代ある**（2026-10-19 の P9 の監査 D-4 で確認。
`%USERPROFILE%\image-reviewer-backups` は作られていないまま＝既定の置き場の謎は未解決）。
**P10 の監査はこれから**（Fable が `docs/p10-audit-report.md` を書く。**私は触らない**）。

### 未着手

- **P10 の監査の結果待ち**（Fable。`docs/p10-audit-report.md`）。出たら仕分けして直す。
- **`tools/gui_layout.mjs` の `WANT_STAGE[2]` の 1 行**（**文言の担当の残件**。段 2 の結果の 1 行が
  「2 枚をゴミ箱へ移しました。」のままで、画面は「2 枚をアプリのゴミ箱へ移しました。」＝
  `frontend-design.md` §6 が正。**直すと `--screen pending --ids` の 4 幅 NG が消える**。
  `deletions-advance.md` §3-4）。
- **再リンク（P8 の合格の線 9）**: **口は P8-6 で実装済み**（`POST /api/locations/relink` は**人だけ**で
  `exact` / `nearby`、`GET /api/locations/missing` は**読むだけ**。**中身の `sha256` が一致したときだけ繋ぎ、
  `pHash` は使わない**。実装の記録は [`p8-6-relink.md`](p8-6-relink.md)、**監査と仕分けも済み**）。
  **残っているのは画面**（P8 では作らないと決めたまま。`design.md` §6.1）。
- **P9（仕上げ）**: **完了**（2026-10-18）。§12.1 の未計測は 0（届かなかったのは一覧 API の 1 行だけ）。
  **監査の指摘も 2026-10-19 に全部反映**。記録は [`p9-implementation.md`](p9-implementation.md)。
  **次にやるのは利用者の判断待ち**（下の §7 と `p9-implementation.md` §8 の申し送り:
  **一覧 API のキーセット改ページ**・**一覧の仮想グリッドとページ送り**・**768px の上部バー**・
  **`--no-hash`**・**exe 化**）。
- **P10（段 1 の行を後から進める・実体が無い行を片付ける）**: **完了**（2026-10-19）。
  記録は [`deletions-advance.md`](deletions-advance.md)。**残っているのは監査だけ**。
  **利用者の再起動 → `#/pending-deletes` で「まとめて片付ける」**が次の 1 操作
  （**187 件が閉じ、7 件は断られる**）。
- **トレイ（タスクトレイ常駐）**: **2026-10-19 に作った**（`tools/tray.ps1`。記録は
  [`tray.md`](tray.md)）。既定の起動は `start-image-reviewer.cmd` → `image-reviewer-tray.cmd`。
  `frontend-design.md` §11 の入口 (c)（「最近の削除を開く」）も入れた。
  **残る判断**: P10 の「ファイルが無いので片付ける」を**トレイからも**使えるようにするか
  （いまは画面だけ。`handoff.md` §3 の 2）。
- **P2 / P3 の残り**: 仮想フォルダ・スマートフォルダ・取込の 3 経路（D&D / クリップボード / URL）・
  `userdata` への設置・タグの統合と改名・本格的な検索・プリセットの画面。
- **実機の日次バックアップ**: **取れている**（`.backup/daily` に 3 世代）。**既定の
  `%USERPROFILE%\image-reviewer-backups` が使えない謎は未解決**（→ §7 の 14・**診断には利用者の許可が要る**）。
- **`README.md` と `docs/design.md` の本体は反映済み**（README は **547 件・395 検査・10 画面 × 4 幅**・
  **P10 の行と `deletions-advance.md` の文書表**・未実装の一覧・**P8-5 の条件 3 件は反映済みに直した**。
  design.md は §5.8・§6.1・§14・§16.7 に **P10**、§16.6 の **P8-5 の条件の「未反映」を直した**）。
  **`docs/p8-*.md` と `docs/p9-*.md`・`docs/deletions-advance.md`・`docs/japanese-ui-fix.md` は履歴として
  そのまま**（**例外は P8-6 の記録 `p8-6-relink.md` と P10 の記録 `deletions-advance.md`**＝
  履歴ではなく**いまの実装の記録**）。

### セッションを切り替えるときの注意

**進行中の作業は無いので、いつ切っても安全です。** ただし次のセッションの最初に**これを回して緑を確かめてください**:
`uv run --no-sync pytest -q`（**547 passed が期待値**）と `node tools/gui_smoke.mjs`（**395 ok / NG 0**）。
**`git` 管理です**（`https://github.com/yuksew/image-reviewer`）。ただし**エージェントはコミットしない**（親が行う）。
控えは `.backup/`（**9 フォルダ**。**消さない**）。**P10 は版を上げない変更なので、増えるのは
`pre-topup-<日時>/`**（利用者の再起動のときに付く）。


### このセッションで終わったこと（2026-10-16 10:25 追記）

- **P4-0 / P4-1 の監査指摘を全部直した**（サブエージェント `4702f8bc`）。
  - **v5 の形**: `db.py` に **`_top_up_v5()`** を新設し、**`migrate()` の早期 return 側でも列を見て補う**
    （`tag.known` / `asset_tag.actor` / `job.note`）。**`SCHEMA_VERSION` は 5 のまま**（v6 の作り直しにしない）。
    古い `data-p40` を開くと列が足され、**263 枚・タグ 3 語は無傷**なのを実測で確認。
  - **模型を取引の外へ**（読む → 模型（錠の外）→ 短い 1 取引で書く。テストで「模型 0.5 秒の間に `locked()` が 0.25 秒以内」）。
  - **`queued` も「忙しい」**に＋検査と `INSERT` を同じ取引に（テストで「`queued` 中の 2 回目は 409」）。
  - **内蔵の縮小を `int()`** に（テストで「768×1360 → 448 の左余白 98 px」）。
  - `job_item.state` の語彙を確定（`tagged` / `skipped` / `failed`）＋ `CHECK`／`/history` を 0.05 秒ごとに（実測 0.72 → **0.51 秒/枚**）／
    対象の既定を `wd14` 軸に／`_balanced()`（語中の括弧は残し、囲む組は外す）／CSV の語は行を作ってから付ける／
    `actor` を落とさない／**ComfyUI の `temp` の複製を 1 枚ごと＋ジョブの終わりに削除**（設定 `tagger.comfyui_temp`）。
  - **検証（私も回した）**: **`pytest` 260 passed**・`gui_smoke` すべて ok・`gui_layout` 4 画面 ok・`probe_p4.py --engine comfyui` OK。
    **実データ `.data` は `user_version 3`・263 枚・判断 3 件のまま**（mtime も不変）。
- **事故 1 件（実装者が申告）**: `tests/test_jobs.py` の文字コードを壊したが、`.pyc` から docstring を戻して書き直し、**いまは緑**（11 → 14 件）。

### ⚠ P4-1 当時の宿題（**歴史**。いまの未着手は上の「未着手」を見る）

- **`pyproject.toml` の `tagger = ["onnxruntime>=1.20"]`** は**未着手**（利用者のサーバが `.venv` の exe を握っていて `uv` が落ちる）。
  **サーバを止めたときに 1 行足す**。**線 8（内蔵と ComfyUI の語の一致）はその時**。
- **`ver. 2` の分割**（`ver` と `2_of_thing` に割れる）: `_balanced()` では扱えない。直すなら「`ver.` の直後は割らない」の 1 行。
- **`GET /api/assets/{id}/tags` の `counts` / `pending_gloss`** は **P4-2（語釈）で形が決まる**ので未着手。
- **`tags[]` の `actor` を契約（`review.json`）に足すか**は**判断待ち**（いまは落とさない形にしてある。API の応答には入る）。

---

## 2. Fable との往復（このプロジェクトの進め方）

**Fable = Orca の別ワークツリーで動く Claude Code**。私（dsh）とは Orca CLI でやり取りします。

```powershell
# 送る（Fable の端末へ。1 行にすると安全。二重引用符 " は使わない＝PowerShell の引数が壊れる）
$h = 'term_a121e64e-0f8d-48a1-aaba-232c9782f863'      # Fable の端末
$msg = @'
【Orca 経由の依頼 / 送信元 dsh セッション(DeepSeek)】…本文…
'@.Trim()
orca terminal wait --terminal $h --for tui-idle --timeout-ms 30000 --json | ConvertFrom-Json | ForEach-Object { $_.result.wait.satisfied }
orca terminal send --terminal $h --text $msg --enter --wait-submit 20 --json | ConvertFrom-Json | ForEach-Object { $_.result.send.accepted }

# 受ける（バックグラウンドで待つとよい）
orca orchestration check --run run_5bdd431bf57b --wait --types "status" --timeout-ms 3600000 --json
# ★ 読んだら必ず ack する（しないと次の check で同じ便が再送される）
orca orchestration check --run run_5bdd431bf57b --ack <deliveryId> --json
```

- **返信先の run id は `run_5bdd431bf57b`**（Fable が `orca orchestration send --to run:run_5bdd431bf57b` で送ってくる）。
- subject の習慣: `<段>-audit-start` / `-mid` / `-done`、`p4-review-done` など。
- **Fable は質問を報告の `G` に推奨つきで書いて待たずに進みます**。私も同じ（利用者に聞くべきことだけ `AskQuestion`）。
- Fable の画面を見る: `orca terminal read --terminal $h --limit 20 --json`。
- Fable は**実行して確かめる**（今回から。`p5-audit-redo.md` の教訓「コードを読んだだけの監査は何も守らない」）。

### 進め方の型（P5・P6 で確立）

1. **設計書を書く**（`docs/<段>-design.md`。§0 拘束力のある差分 → §1 範囲と**実行で確かめられる合格の線** → §2 表 → §3 API → §4 状態 → §5 画面 → §6 契約 → §7 性能 → §8 **何を壊すと落ちるか** → §9 工程 → §10 未確認 → §11 用語 → §12 レビュアー向け）。
2. **Fable に点検させる**（指示書 `docs/<段>-review-brief.md` → 報告 `docs/<段>-review-report.md`）→ **仕分け `docs/<段>-review-triage.md`** を書いて**推奨どおり反映**。
3. **小段ごとに実装**（P6-0 / 1a / 1b / 2 のように割る）。**各段で `pytest`・`gui_smoke`・`gui_layout` を緑に保つ**。
4. **各段を Fable が監査**（指示書 `docs/<段>-audit-brief-<小段>.md` → 報告 `docs/<段>-<小段>-audit-report.md`）→ **仕分け**して反映。
5. 利用者の判断が要る点は**決めずに**記録し、まとめて聞く（`docs/p6-morning-report.md` が手本）。

---

## 3. 次の手順（この順で）

### 0. 監査の結果待ち（**新しい順にここ**）

- **P10 の監査はこれから**（Fable が `docs/p10-audit-report.md` を書く。**こちらの担当は触らない**）。
  出たら**仕分け**（`docs/p10-audit-triage.md` の形）を書いて、指摘を直し、
  **`design.md` §5.8・§6.1・§14・§16.7 と `deletions-advance.md` に書き戻す**（**P10 の記録は
  履歴ではなく「いまの実装の記録」**なので、直したら本文も直す）。
- **P9 の仕分けは済み**（[`p9-audit-triage.md`](p9-audit-triage.md)。C-1〜C-3 は全部反映）だが、
  **再確認はまだ受けていない**（P8 の各段と同じく「直した物が実行で直っているか」）。
  とくに **C-1（新しい読み取り専用の接続で `quick_check`）** は**走ったまま壊れた DB**を作る試験なので、
  再確認では**複製で**回す。
- **P8-5 の監査の条件 3 件（C-1〜C-3）は 2026-10-18 の仕分けで反映済み**——古い「未反映」の記述は
  README と `design.md` §16.6 で直した（**段 3 の許可が無い置き場の枚で `--screen asset` が 4 幅 ok** を実測）。

### 1. 未計測（**1 万枚になったら**測る／入れる）

**`design.md` §12.1 の「目標」の行は全部実測で埋まっている**（未計測 0。**測り方と生の値は §5 と
[`p9-implementation.md`](p9-implementation.md)**）。残っているのは**見込みだけの行**:

- **一覧 API のキーセット改ページ**（p95 **244.7 ms** / 目標 20 ms。**目標は下げていない**）。
  **1 万枚が現実になるまでは困らない**（実データ 267 枚なら p95 14.3 ms）。入れるときは `total` の意味と
  `q` / `tag` の絞り込みが変わるので、**テストと画面の前提を一緒に直す**（§12.1 の「必要な条件」）。
  **入れる段を別に立てる**（利用者の判断）。
- **一覧の仮想グリッドとページ送り**（いまは `limit=2000` で 1 回引いて全部描く。**2000 枚より先を見る道が無い**）。
  入れるなら**狭い窓の検査**（`gui_layout` の `VIEWPORTS` は 1200 以上しか無い）とセットで。
- **`--include-library` を日次に載せるか**（日次が 201 ms → 2.4 秒。1 万枚なら 1.4 分）。
- **`--no-hash` の走査**（実装に無い）。
- **768px の上部バー**（**溢れは 0** なので実害は無く、3 行に折り返す見た目の問題）。

### 2. トレイ（タスクトレイ常駐）

**2026-10-19 に作った**（`tools/tray.ps1` ＋ `image-reviewer-tray.cmd`。記録は [`tray.md`](tray.md)）。
`frontend-design.md` §11 の入口 (c)（「最近の削除を開く」）も入れた。**残る判断**は
**P10 の「ファイルが無いので片付ける」もトレイから使えるようにするか**（いまは画面だけ。§7 の 5 と同じ問い）。

### 3. P2 / P3 の残り

仮想フォルダ・スマートフォルダ・取込の 3 経路（D&D / クリップボード / URL）・`userdata` への設置・
タグの統合と改名・本格的な検索・プリセットの画面・再リンクの画面（**口は P8-6 でできている**）。
**`.data` の版を上げるのはこの段**（上げる前に `pre-migrate-<日時>/` の控えを取り、掃除の対象にしない）。

### 4. `%USERPROFILE%` の権限の診断（**利用者の許可が要る**）

**既定の `%USERPROFILE%\image-reviewer-backups` がアプリのプロセスから作れない謎**は未解決のまま
（`WinError 5`。同じ持ち主のシェルからは作れる。CFA は無効・ACL も正常・系譜は Explorer → cmd → uv → exe）。
**いまは `settings.backup_dir` を `C:\work\image-reviwer\.backup\daily\` にして凌いでいる**（利用者の決定。
**同じドライブなので、ドライブが壊れた場合は両方失う**）。
診断には**利用者の許可が要る**（`icacls` の読み取りと、`%USERPROFILE%` の下に**試験用のフォルダを 1 つ作る**許可。
**エージェントの sandbox の子プロセスからは書けない**ので、**利用者の端末のシェルで**試す必要がある）。

### 5. 利用者に頼む 1 操作（P10。**これが次の 1 手**）

**利用者がアプリを立ち上げ直して `#/pending-deletes` を開き、「全部選ぶ」→「まとめて片付ける」を押す。**
**（2026-10-19 の注記）`closed_at` / `close_reason` の列は既に足されている**ので、この操作で
`pre-topup-<日時>/` の控えは**付かない**（足したのは利用者の起動ではなく、トレイの自己検査の穴＝
事故 4 件目。`missing_top_ups()` は空。`tray-audit-triage.md` A-1）。
**予想される結果**: **「187 件を片付けました。」＋「7 件はファイルがまだあるので片付けませんでした。」**。
**残る 7 行は「アプリのゴミ箱へ移す」**で進められる（移した後も**アプリのゴミ箱に実体が在る間は片付けを断る**＝
ゴミ箱を空にするのは利用者）。**バックアップは `.backup/daily` に 3 世代取れている**（P9 の監査 D-4 で確認済み）。

---

## 4. 検証の三点セットと道具

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
uv run --no-sync pytest -q                      # 547 件（2026-10-19 に実測）
node tools/gui_smoke.mjs                        # 395 ok（軽い DOM。CSS を持たない）
# 本物の Chrome。サーバは実データのコピーで立てる（8791〜）。前提の行は seed が複製の中に作る
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\data-XXXX"
uv run --no-sync python -X utf8 tools/gui_layout_seed.py --data $env:IMAGE_REVIEWER_DATA `
    --tags --exclusion --pending --stage3 --backup-error --backup-dir C:\work\image-reviwer\.tmp-audit-redo\backups
uv run --no-sync image-reviewer serve --port 8791
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8                    # 比較
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests            # 要求の一覧
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>  # まとまりレビュー
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <id>    # 注記とタグ
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags                # 語の一覧
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs                # ジョブ
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen duplicates          # 重複の整理（P8）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending             # 最近の削除（P8）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending --ids <id>,<id>  # 削除の確認つき（P8）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen library             # 下部バーの入口（P8）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen settings            # 設定（P8-5）
node tools/gui_layout.mjs --base http://127.0.0.1:8796 --screen pending             # 段 1 の後始末（P10。**複製で**）
# ★ --screen asset は「段が 3 つ」を前提に**しない**（P8-5 の監査 C-2 で API から期待値を組む形に直した）。
#   段 3 の許可が無い置き場の枚では段 2 までを期待する（2026-10-19 に 4 幅 ok を実測）。
#   **印ありの複製で回す手順だけだと見えない**ので、**印なしの枚でも 1 回は回す**。
# ★ --screen pending --ids には**生きている枚**を渡す（P9 で踏んだ）。外した枚（deleted_at）を渡すと
#   「置き場を確かめられないので段 3 は出していません」が出て、段 3 の検査が 3 窓とも NG になる（**正しい動作**）。
# ★ --screen pending --ids の**段 2 の結果の 1 行だけは 4 幅とも NG**（`WANT_STAGE[2]` が古い 1 行。§6）。
# ★ --screen tags は語が 0 件だと必ず NG。`gui_layout_seed.py --tags` を**複製に**当ててから回す。
# ★ `gui_layout` は**Python の subprocess から呼ばない**（Chrome が `%TEMP%` に書けず EPERM。**PowerShell から直に**。
#   `.ps1` は実行ポリシーで拒まれるので `powershell -NoProfile -ExecutionPolicy Bypass -File …` か、そのまま打つ）。
# 実機の線（合否を出す）
uv run --no-sync python tools/probe_p4.py --engine comfyui   # P4 の線 1・2・7
uv run --no-sync python tools/probe_p6_1a.py                 # P6 の性能（線 150ms / 20ms）
uv run --no-sync python tools/probe_p6_2.py --base http://127.0.0.1:8791   # 切り出しの画素
uv run --no-sync python tools/probe_p8.py --duplicates       # P8 の線 2〜4（帯を総当たりと突き合わせる）
uv run --no-sync python tools/probe_p8.py --delete           # P8 の線 5〜8（3 段階と 5 分の窓）
uv run --no-sync python tools/probe_p8.py --backup           # P8 の線 10・12（日次と健全性）
uv run --no-sync python tools/probe_p8.py --restore          # P8 の線 11（消して戻す・組み直し）
uv run --no-sync python tools/probe_p8.py --all              # 全部（自分の置き場を作り、後始末する）
# P10（段 1 の後始末。**複製を作って 14 件の線を回す**／`--serve` は gui_layout 用に立てるだけ）
.venv\Scripts\python.exe tools\probe_deletions_advance.py --port 8796            # 複製を作って 14 件の線
.venv\Scripts\python.exe tools\probe_deletions_advance.py --serve --port 8796    # 複製サーバ（--keep を含む）
uv run --no-sync --with jsonschema python tools/check_contract_p6.py       # 契約の検証（P6）
uv run --no-sync --with jsonschema python tools/check_contract_p8.py       # 契約の検証（P8 の backup-manifest）
# P9（性能の実測。**合成 1 万枚の DB と実データの複製を作る**。§12.1 の表を作り直せる）
uv run --no-sync python -X utf8 tools/make_synthetic_db.py --out .tmp-audit-redo/p9/synth10k --count 10000
uv run --no-sync python -X utf8 tools/probe_p9.py --all --replica <実データの複製> --runs 30
```

---

## 5. 数字の記録（次のセッションが前提にできる実測）

- **P10（段 1 の行を後から進める・実体が無い行を片付ける。2026-10-19 の実測。正は
  [`deletions-advance.md`](deletions-advance.md) と [`design.md`](design.md) §16.7）**:
  **私（文書の反映の担当）が回した数** — `pytest` **547 passed / 0 failed**（40.3 秒）・
  `gui_smoke` **395 ok / NG 0**・`gui_layout` **10 画面 × 4 幅**（`VIEWPORTS` は 1400・1024・1200・1920）＋
  `pending --ids` の 11 本目（**複製 8797**。`probe_deletions_advance.py --serve` が作った複製）。
  **`--screen tags` は語を植えた複製で 4 幅 ok**・**`--screen asset` は段 3 の許可が無い置き場の枚でも 4 幅 ok**
  （P8-5 の C-2 が直っている証拠）・**`--screen pending --ids` は「段 2 の結果の 1 行」だけ 4 幅 NG**
  （`gui_layout.mjs` の `WANT_STAGE[2]` の残件。§6）。
  **実データ（`mode=ro` で読んだだけ。1 バイトも書いていない）**: `asset` **461 行**・生きた **267 枚**・
  段 1 の生きた行 **194**・**実体が在る 7 行**（うち **6 行**は台帳の `asset_id` が古い形）・実体が無い **187 行**・
  `deletion_log` **194 行**・**`closed_at` / `close_reason` の列は、この読みのあとの 16:48:56 に
  トレイの自己検査の穴で足された**（事故 4 件目。控え無し・行の変化 0。`tray.md` §6）。
  **P10 の実装者が複製で通した線**（`tools/probe_deletions_advance.py` の **14 件**）: 段 1 → アプリのゴミ箱へ移る／
  「戻す」で元に戻る／実体が無ければ 409 `missing_file`／**194 件を 1 回で片付けて 187 件が閉じ 7 件が `file_found`**／
  `asset.deleted_at` はそのまま（187/187 が隠れたまま）／**ファイルの署名が同じ**（536 件が動いていない）／
  二重の片付けは 200 で `replayed`／エージェントは 403 `human_only`。**壊し試験は 13/13 が落ちた**。
- **P9（仕上げ。2026-10-18 の実測。正は [`design.md`](design.md) §12.1 と [`p9-implementation.md`](p9-implementation.md)）**:
  **一覧 API は p95 244.7 ms**（1 万枚・`TestClient`。**目標 20 ms に届かない**。`store.assets()` が 200 ms・
  SQL 3 本が 47.5 ms。実データ 262 枚なら **p95 14.3 ms**）／**1024px サムネイルの生成は 128 ms/枚**
  （実画像 1.15 MB。1 万枚 21.3 分。**同時 8 本なら 22 ms/枚 → 3.7 分**）／**256px は 30 ms/枚**
  （1 万枚 4.9 分。**同時 8 本で 4 ms/枚**）／**生成済みの配信は p95 2.4〜2.6 ms**／
  **比較の 8 枚は p95 8.3 ms**（文書＋8 枚のサムネイルで 22 ms）／
  **グリッドは 100 枚で 87 ms・299 枚で 93 ms**（最初のカードまで。全部そろうまで 104 ms）／
  **1 万枚は 2000 枚で切れて 532 ms**（DOM 12,259 ノード）／**2 回目の走査は 2.6〜2.7 秒**・
  **初回は 9.1 秒（温）／40.6 秒（書いた直後）**／**判断の記録は p95 1.5 ms**／
  **一括削除の再照合は 596 ms / 1,000 件**（`os.stat` だけなら 13.8 ms）／
  **`--include-library` は 2.40 秒 / 262 枚・291.1 MB**（132 MB/s）／**日次は 201 ms**（DB 3.2 MB）／
  **`nearby` は 39〜45 ms**（1 万枚）。
  **土台（`GET /api/health`）の p95 は 1.1〜1.3 ms**。
- **exe 化**（P9 の試し）: **PyInstaller 6.22.3 が Python 3.14.7 で動く**。`--onedir` が **23.7 秒・131.9 MB**
  （`onnxruntime` 37.5 MB ＋ `numpy` 26.3 MB ＋ `PIL` 10.7 MB）で、**起動は 0.53 秒**
  （`uv run --no-sync image-reviewer serve` は **1.05 秒**）。**画面が出ない**（`gui_present: false`。
  `apps/gui` の解決が 1 か所足りない）。`.venv` は 128.4 MB。
- **P6**: 要求の受付 p95 1.5 ms（keep-alive。線 150）／一覧 1,000 件 p95 2.8 ms（線 20）／切り出しは画素数比例（1024² 全面 21 ms・`compress_level=1`）。
- **P4-1**: ComfyUI の `IllustTagger` **0.26〜0.31 s/枚**（スコア付き）／`WD14Tagger` は**キャッシュが当たらないと 2.8〜3.4 s/枚**（設計にあった 0.40 s/枚は `execution_cached` の値）／内蔵 GPU **0.063 s/枚**・CPU 0.75 s/枚（未導入）。
  1 万枚の見積り: **内蔵 GPU 約 11 分 / IllustTagger 約 45 分 / WD14Tagger 約 8 時間**。
- **語釈**: 位置対応は 6 回中 2 回しか行数が合わない／**番号付きなら 4 回とも 20/20**（20 語 4.6〜4.8 秒）。
- **P8（重複・削除・バックアップ。2026-10-18 の実測。正は [`design.md`](design.md) §12.3）**:
  - **pHash の全件計算 14.8 ms/枚**（復号込み。実データの未計算 172 枚が 2.6 秒 → **1 万枚で約 2.5 分**）。
    完全重複の検出 0.1 ms。**準重複（263 枚）は帯の候補づくり 46〜52 ms・総当たり 2〜8 ms**
    （**距離 0〜64 のすべてで総当たりと一致・取りこぼし 0**）。
  - **1 万枚は合成データで SQL の自己結合 7.56 秒・Python の辞書 1.13 秒・int の総当たり 7.8 秒**
    （≤ 6 で 67,705 組が一致）。**いまの実装（帯ごとの照会）での 1 万枚は未計測**（帯の候補が数百万組になる）。
  - **段 3 の移動（`os.rename`）は大きさに依らない**（1 GB の疎ファイルで 0.24 ms・密な 256 MB で 0.19 ms）。
  - **日次バックアップ 37 ms**（実データの複製・温まった状態・5 回の中央値 35〜46。DB 1.0 MB ＋ `sidecar` 1 ＋ `export` 1。
    **写しを開いて `quick_check` → `integrity_check` する分を含む**）／
    **復元 11 ms**（11〜13。`<data>` を丸ごと消した状態から 263 枚・判断 3 件）。
  - **`--include-library`（292 MB）は未計測。**
  - **実データの重複**: **21 群 / 57 枚**（距離 ≤ 6。**完全重複 0 群**）。距離 ≤ 3 で 17 群・≤ 10 で 28 群。
    pHash は **263 / 263 枚**に入っている（帯は 4,208 行＝263 × 16）。
- **P8-6（再リンク。2026-10-18。正は [`p8-6-relink.md`](p8-6-relink.md)）**: `tools/probe_p8.py --relink` が
  **16 行すべて OK**（実データの複製。`TestClient` で本物の HTTP）／`pytest` **507 件**（P8-5 の 477 ＋ 新規 30。
  **私が 2 回回して 35.9 / 40.5 秒**）／`gui_smoke` **310 検査・NG 0**（**P8-5 の条件の直しが並行して入った時点**）／
  `gui_layout` **11 本すべて ok**（**P8-6 の記録**が複製 8791 で。**文書の反映のときには回していない**）。
  **`nearby` の 1 万枚での時間は未計測**（実データは 263 枚）。
- **実データ**: **v6・263 枚・判断 3 件・削除 0 件**（`deletion_log` も `delete_request` も 0 行）。
  `duplicate_exclusion` 1 件・`review_group` 1 件（`kind='duplicates'`）は**利用者が押した物**。WAL は**畳まないと判断が消える**（複製は `sqlite3` の `backup()` で）。
- **語彙**: CSV 10,861 行（general 8,106 / character 2,751）。**キャラ名の 51% が括弧を含む**（`rem_(re:zero)`）。
  PNG の語の採用率は 46%（`.` でも割ると 49%）。実データでは**件数順の上位 4 語が全部 `known=0`** の品質語。

---

## 6. このプロジェクトで実際に踏んだ罠（同じ穴を踏まないために）

**実装側**

- **`GET` に副作用を持たせない**（P5 で `GET` がファイルを書いていた。P6 で `format=crops` を `POST` に限定）。
- 語彙は **DB の `CHECK` でも守る**（サービス層だけにしない）。移行は**足すだけ**・`ALTER TABLE` は**列を見てから**。
- **契約に欄を足したら、実際に出す**（P6-0 の監査 B1: 足したのに一度も出しておらず、隠れるテストだけが緑だった）。
- **浮動小数の境界**: `ceil((x+w)*W)` は**幅 1360 で 1 画素はみ出す**。`round(v, 6)` を挟む。
- **ヘッダの enum を検査しないと DB の `CHECK` に当たって 500**（`actor: robot` で実際に 500 になった）。
- 切り出しの**右端ぴったりで幅 0 の画像**を作って 500 になった（`left <= W-1` に抑える）。
- **キャッシュに当たった計測を実測と思い込まない**（ComfyUI の `execution_cached`）。**別々の入力で測る**。
- 例外を投げる前に**一時ファイルを消す**。起動時に `*.tmp` を掃除する。

**P10 で踏んだ罠**

- **Chrome を起こす道具（`gui_layout` / `gui_shot`）を Python の `subprocess` から呼ぶと `%TEMP%` に書けず
  `EPERM`（`mkdtemp`）で落ちる**——この環境の sandbox の子プロセスは `%TEMP%` にも `%USERPROFILE%` にも書けない。
  **PowerShell から直に回す**。`.ps1` にまとめると**実行ポリシー**で拒まれるので、
  `powershell -NoProfile -ExecutionPolicy Bypass -File …` に渡すか、そのまま打つ
  （**この環境の `pwsh` は 5.1 で、`pwsh` という名前の実行ファイルは無い**）。
- **台帳の `asset_id` は走査で古くなる**（走査が**同じ場所を別の `asset` として登録し直す**ため）。
  `delete()` の `_target(asset_id, path)` は**古い `asset_id` を渡すと 409 `not_registered` で永久に進めない**
  （実データの段 1 で**実体が在る 7 行のうち 6 行**がこの形。**要望の前提「194 行は実体が無い」とも食い違う**）。
  **「いま登録されている行」を引く**道（`_target_for_advance`）を作り、**別のファイルを移さない**守りは
  **`(size, mtime_ns)` の照合**に持たせた。**「その場所がまだその枚の物か」の検査を `asset_id` の一致で代用しない。**
- **`pytest -k` の綴り違いは「1 件も選ばずに終了コード 5」で返る**（**落ちていないのに「落ちた」と数えていた**——
  壊し試験 13 件のうち 2 件がこれだった）。**`-k` で絞ったら「何件選ばれたか」を見る**
  （`1 deselected` / `no tests ran` を見落とさない）。**「落ちた」と数える前に、その試験が本当に走ったかを確かめる。**
- **道具が `cli serve` を起こすときは、置き場を必ず明示する**（**事故 4 件目**。2026-10-19、
  トレイの自己検査の §10 が `IMAGE_REVIEWER_DATA` を付けずに `cli serve` を起こし、§2 が `attach` に
  なっていたので環境変数が無いまま**既定の `.data` を開き、`deletion_log` に 2 列が控え無しで入った**）。
  **`create_app()` の env 検査は `cli serve` を通す**（`serve_data_dir()` が既定を明示する）ので、
  **ここは道具側の規律で塞ぐしかない**。直しは `tools/tray.ps1` `Start-OwnServer`（`$env:IMAGE_REVIEWER_DATA`
  を必ず立てる）・`tools/tray_selftest.ps1`（4 ポートの空きを先に見て、`own` でなければ exit 2）。
- **`deletion_log` に `closed_at` を書く SQL を、列の無い DB に打つと `no such column` で落ちる**
  （読み取り専用の点検スクリプトでも同じ。**列の有無を `PRAGMA table_info` で見てから**書く。
  §0 の「版を上げずに表を変える」と同じ規律）。
- **実データの署名（`rglob` の size と `mtime_ns`）は、他のプロセスが `mode=ro` で開くだけで揺れる**——
  **`db.sqlite3-shm` の `mtime_ns` が動く**（2026-10-19 に実測: 675 ファイルのうち `-shm` だけが変わる）。
  `tests/test_data_dir_guard.py` の「実データが変わった」の比較は**この形**なので、
  **並行して誰かが実データを読んでいると（監査・複製づくり・利用者のアプリ）1 件だけ落ちうる**。
  **落ちたら中身の変化ではなく `-shm` を見る**（**本当に変わったのかを `mode=ro` の問い合わせで確かめる**）。
  2026-10-19 の実例: 1 回目 **547 passed** → 2 回目 **546 passed / 1 failed**（この検査。**単独では 4 passed**、
  3 回目の全体は **547 passed**）。**並行作業中の「1 件だけ落ちた」を、実装の不具合と早合点しない。**

**P8 で踏んだ罠**

- **`os.replace` は既存のファイルを黙って上書きする**（実測: 置いた別のファイルが消えた）。**「上書きしない」を作るのは `os.rename`**
  ——Windows では `MoveFileExW` を `MOVEFILE_REPLACE_EXISTING` 無しで呼ぶので、**検査と置き換えの間の競合が無い**。
  埋まっていれば **`FileExistsError`（WinError 183）** → **409 `target_exists` で止めて尋ねる**。`exists` の事前検査は要らない（P8 の点検 B4）。
- **索引名は DB 全体で一意**。`CREATE UNIQUE INDEX IF NOT EXISTS ux_request_token ON delete_request(...)` は
  **エラーも出さずに何もしない**（P6 の `review_request` が同じ名前を使っていた）。**`PRAGMA index_list` を見るまで気づかない**
  ——同じ token が 2 行入って初めて分かる（P8-0 の監査 C-0。`ux_delete_token` に変えた）。
- **`PRAGMA quick_check` は例外を投げることもある**（2 ページ目を 0 で潰した DB は `database disk image is malformed`）。
  **`fetchall()` の中身で判定すると、壊れた DB ほど 500 になる**——`try/except sqlite3.DatabaseError` で受け、
  **例外も「`ok` 1 行でない」も「壊れている」に数える**（P8-4 の B-1）。
- **DB の先頭 4 KB を潰すと開けない**（接続はできるが最初の SQL で `DatabaseError`）。**2 ページ目（4096〜8191）を潰すと
  「開けるが壊れている」**（`quick_check` は例外・`asset` の `SELECT` は通る）。**報告はこの 2 つの形を分けて書く**。
- **8bit × 8 本の帯では距離 7 までしか保証できない**（鳩の巣の当てはめ違い）。実測で **≤ 12 で 3 組・≤ 16 で 72 組を取りこぼした**。
  **4bit × 16 本なら距離 15 まで保証**でき、**16 以上は帯で絞らず総当たり**に落とす（P8-1 の B-1）。
- **`import image_reviewer.app` で `create_app()` が走ると実データに書く**（P8-4 の事故。`ALTER` が控え無しで走った）。
  **`app` を PEP 562 の `__getattr__` で遅延**し、`serve` は `--factory`、**pytest は収集の前に `IMAGE_REVIEWER_DATA` をテストへ向ける**。
- **版を上げずに表を変えるときも、変える前に控えを取る**（`pre-topup-<日時>/`）。**足す物の一覧は `db.TOP_UP_COLUMNS` に 1 か所**で書き、
  `_top_up_v6` と `missing_top_ups()` が同じ物を見る（P8-4 の D-2・G-5）。
  **控えの置き場が scratch（`.tmp-*`）だと、掃除で控えごと消える**（事故 4 件目。`IMAGE_REVIEWER_BACKUP_DIR` を
  `.tmp-tray\backups` に向けていたので、控えは `.data` に残らなかった）。**実データを開き得る道具の控えは消さない場所へ。**
- **`sandbox` の子プロセスは `%USERPROFILE%` の下に書けない**（直下・`Documents`・`AppData\Local`・`Downloads`・`C:\work` 直下の
  7 か所で `WinError 5`）。**既定の `%USERPROFILE%\image-reviewer-backups` は作れない**——**実機の日次が 0 個なのはこれ**
  （P8-4 の再確認 B-1'）。検証では `IMAGE_REVIEWER_BACKUP_DIR` / `--out` で**リポジトリの中の `<data>` の外**へ向ける。
- **`%TEMP%` にも書けない**ので、SQLite の一時 b-tree で `unable to open database file` になる（`PRAGMA temp_store = MEMORY` で回避）。
- **長い会話の `fork`（`subagent_fork`）は文脈が尽きる。** 会話が長いセッションでは子が最初から文脈を読み直して上限に当たる
  ——**重い段は素の `subagent` に、必要な前提を本文に書いて渡す**。
- **画面の検査の前提は、実装が変わると古くなる。** P8-5 が「印の無い置き場では段 3 を出さない」を入れたのに、
  `gui_layout --screen asset` は「段が 3 つ」を期待したままだった——**印を立てた複製で回す手順だと見えない**
  （P8-5 の監査 C-2）。**前提を変える変更をしたら、その前提を見ている検査を grep して直す**（`--no-stage3` でも回す）。
- **`busy` を付け忘れたボタンは二度押しで 2 回 POST する。** `settings.js` の `setAllow` だけ
  `state.busy = true; render();` が無く、`click()` 2 連打で `allow-stage3` が 2 回飛んだ（P8-5 の監査 C-1。
  **`gui_smoke` の「1 回だけ叩く」は 1 回押ししか見ていない**）。**行を増やす口を押すボタンには同じ形を写す。**

**P7 で踏んだ罠（§1 の追記からここへ移した）**

- **`/api/jobs` の一覧に `workflow` は無い**（`/api/jobs/{id}` が要る＝2 段。タグ付けの job も並ぶので `outputs_count: 0` で弾く）。
- **`execution_cached` は全部の job に出て `nodes` が空**（「保存ノードが `cached` にあるか」で見分ける）。
- **`subfolder` は Windows でバックスラッシュ**で来る。
- **`/object_info` の一括は 2.39 MB・0.41〜0.91 秒**（`/object_info/{class_type}` は 0.7〜3 KB・0 ms。使ったノードだけ引く）。
- **`COMFY_DYNAMICCOMBO_V3` の入れ子**（`sampling_mode.temperature` など）を展開しないと**入力キーの検査が誤判定**する。
- **SQLite は `ALTER TABLE` で `CHECK` を足せず、外部キーの `ON DELETE` も変えられない**（**表が空のうちに決める**）。
- **`seed` が NULL だと UNIQUE が効かない**（`COALESCE(seed,'')` の式の索引）。
- **`asset_location.path` は正規化した鍵**（生の `str(path)` では Windows のドライブの大小文字で当たらない）。
- **ComfyUI に繋がらないときは `system_stats` で打ち切る**（全 `class_type` を引き続けると 1 枚 20〜32 秒かけて全部 `impossible` になる）。

**進め方**

- **コードを読んだだけの監査は何も守らない**（P5 の「実行込みのやり直し」で判明）。監査は**実行**させる。
- **「既存の画面」があると思い込まない**（P6 A2: 設計が「既存のまとまりレビュー」と書いていたが、P5 は作っていなかった）。
- **テストは「壊すと落ちるか」を言える形**にする（何も守っていないテストが見つかった）。
- 利用者の判断が要る点は**勝手に決めずに記録して聞く**（推奨つきで）。決定は**仕分け文書と設計本体の両方**に書く。

---

## 7. 利用者（人間）の判断待ち・確認待ち

**P10 まで終わったので、ここにある物が次にやることの全部**です。
**新しく足した物（2026-10-19）を先に**、そのあとに P9 までの持ち越しを並べます。

**新しく足した物（2026-10-19）**

1. **★ P10 の監査の結果待ち**（Fable が `docs/p10-audit-report.md`）。**利用者に聞くことは無い**（こちらで仕分ける）。
2. **★ P9 の監査の再確認待ち**（[`p9-audit-triage.md`](p9-audit-triage.md) の直しが**実行で直っているか**）。
   とくに **C-1**（新しい読み取り専用の接続で `quick_check`）は**走ったまま壊れた DB**を作るので**複製で**回す。
3. **★ 利用者の 1 操作: アプリを立ち上げ直して「まとめて片付ける」を押す**（P10 の仕上げ）。
   **（2026-10-19 の注記）`closed_at` / `close_reason` の列は既に足されている**（トレイの自己検査の穴＝
   事故 4 件目。**控えは付かない**）。押す意味は「187 行を終わりにする」ことで、列を足すことではない。
   **予想: 「187 件を片付けました。」＋「7 件はファイルがまだあるので片付けませんでした。」**。
   **残る 7 行は「アプリのゴミ箱へ移す」**で進められる（**ゴミ箱を空にするのは利用者**）。
4. **`tools/gui_layout.mjs` の `WANT_STAGE[2]` の 1 行**（**文言の担当の残件**。段 2 の結果の 1 行だけが
   4 幅とも NG。**画面の語が正**＝`frontend-design.md` §6。`deletions-advance.md` §3-4）。
   **誰が直すかは利用者の判断**（私は `tools/` を触らない指示だった）。
5. **`%USERPROFILE%` の権限の診断**（**利用者の許可が要る**。§3 の 4。`icacls` の読み取りと、
   **利用者の端末のシェルから `%USERPROFILE%` の下に試験用のフォルダを 1 つ作る**許可）。
   **既定のバックアップの置き場が使えない謎**は未解決のまま（**いまは `.backup/daily` で凌いでいる**）。
6. **`--include-library` を日次に載せるか**（判断待ちのまま。日次が 201 ms → 2.4 秒。1 万枚なら 1.4 分）。
7. **`?source=` の複数指定が AND か OR か**（P4 からの持ち越し。設計に無く、実装は AND）。

**P9 までの持ち越し**

1. ~~**★ 8790 を sandbox の外（自分の端末）で立て直す**（**バックアップのため**）~~ → **済み（P9 の監査 D-4 で確認）**。
   **8790 は Explorer → `start-image-reviewer.cmd` の系譜で動いていて（PID 7324）、利用者が置き場を
   `.backup/daily` に変え、日次は取れている**（`GET /api/backup` の実測）:
   **`20261018`（263 枚・17:12 JST）・`20261018-171143`（「いま取る」）・`20261019`（455 枚・00:00:15 JST）**。
   `%USERPROFILE%\image-reviewer-backups` は無い（既定のままでは使えない、という §13 の謎は未解決のまま）。
   **`.backup/` はリポジトリの中・同じドライブ**なので、別のドライブに置くかは利用者の判断。
   **（2026-10-19 の追記）その 8790 は、この作業の時点では動いていない**（`Get-NetTCPConnection` に 8790 が無い）。
2. **★ 一覧 API のキーセット改ページを入れるか、いつ入れるか**（**P9 で唯一目標に届かなかった行**）。
   p95 **244.7 ms** / 目標 20 ms。**1 万枚が現実になるまでは困らない**（実データ 267 枚で p95 14.3 ms）ので、
   P9 では入れずに**段を別に立てる**ことにした。入れるときは `total` の意味と `q` / `tag` の絞り込みが
   変わるので、**テストと画面の前提を一緒に直す**（`design.md` §12.1 の「必要な条件」）。
3. **一覧の仮想グリッドとページ送りを入れるか。** いまは `limit=2000` で 1 回引いて全部描くので、
   **1 万枚では 2000 枚で切れる**（P9 で「先頭 2000 枚を表示」と出すようにした）。**2000 枚より先を見る道が無い**。
   入れるなら**狭い窓の検査**（`gui_layout` の `VIEWPORTS` は 1200 以上しか無い）とセットで。
4. **再リンクの画面を作るか、いつ作るか。** **口は P8-6 で作った**（`POST /api/locations/relink` は**人だけ**・
   `GET /api/locations/missing` は読むだけ。**画面は無い**＝対象の枚を一覧で見て「近くを探す」「場所を指定」を
   押す画面。`docs/frontend-design.md` に項目が無いので、作るなら画面設計から）。
5. ~~**トレイ（タスクトレイ常駐）を作るか。**~~ **済み（2026-10-19 に作った）**。`tools/tray.ps1` ＋
   `image-reviewer-tray.cmd`。**残る問い**は「**P10 の『ファイルが無いので片付ける』をトレイからも使えるようにするか**」
   （いまは画面だけ）。`frontend-design.md` §3・§4.5・§4.6・§11 と `design.md` §4.1・§16.8 を直した。
6. **768px の上部バーを詰めるか**（P9 で見送った。**溢れは 0** なので実害は無く、**3 行に折り返す**見た目の問題。
   直すには `gui_layout` の `VIEWPORTS` に狭い窓を足すのが先）。
7. **exe 化するか**（**P9 の推奨は「今は作らない」**。作れることは実測済み＝`p9-implementation.md` §6）。
8. **`--include-library` を日次に載せるか**（日次が 201 ms → 2.4 秒になる。1 万枚なら 1.4 分）。
9. **`--no-hash` の走査を作るか**（§12.1 の行。いまは実装に無い）。
10. **`onnxruntime-gpu`（CUDA の DLL）を入れるか。** 入ると内蔵タガーが **0.063 秒/枚**（いまは ComfyUI の
    `IllustTagger` が 0.27 秒/枚）。**入れるにはサーバを止める**許可が要る（`pyproject.toml` の `tagger` の extra）。
11. **`PATCH /api/settings` をどこまで開けるか。** いま受け取るのは **`backup_dir` だけ**。ComfyUI・タガー・閾値・
    テーマなどは **DB の `settings` にあるが、変える口が無い**（画面も読むだけ）。要るなら次の段で。
12. **`?source=` の複数指定が AND か OR か**（P4 からの持ち越し。設計に無く、実装は AND）。
13. **`.data` の版**: いま **v6**。**次に上げるのは P2 / P3 の段**（上げる前に `pre-migrate-<日時>/` の控えを取り、
    `pre-topup-*` と同じく掃除の対象にしない）。

**決着済み**: 語釈の模型（`qwen3vl_8b_int8_convrot`）／タガーは ComfyUI を優先（`settings` の `tagger.engine=comfyui`）／
**skill の置き場**（原本は `.agents/skills/` の 1 か所、`.claude/skills/` はジャンクション。**リポジトリは git 管理になった**ので
`skills-layout.md` の G-1 は解決。G-2（利用者レベルへ `orca-relay` を置くか）は**置かない**のまま。§9）。

---

## 8. 主要ファイルの地図

| 何 | どこ |
| --- | --- |
| 全体の設計（正） | [`design.md`](design.md)（**P8 の決定は §16.6・P9 と P10 の決定は §16.7**。表は §5.8・口は §6.1・性能は §12.3・段は §14。**P8-6 の再リンクは §5.1・§5.8・§6.1・§14・§15・§16.6**、**P10 は §5.8・§6.1・§14・§16.7**） |
| フロントの設計 | [`frontend-design.md`](frontend-design.md)（画面一覧は §3。**削除と重複は §4.6**・文言は §6・細部は §11） |
| 段ごとの設計 | [`p8-design.md`](p8-design.md)（**§0 が拘束力のある差分**） / `p5-design.md` / `p6-design.md` / `p4-design.md` |
| **P9（仕上げ）の実装の記録** | [`p9-implementation.md`](p9-implementation.md)（**§12.1 の実測値の表**・測り方・届かない物・**exe 化の推奨**・見送った物・申し送り・設計の穴） |
| **P9 の監査と仕分け** | [`p9-audit-report.md`](p9-audit-report.md)（判定「合格（条件つき）」・C-1〜C-3・D 10 件・G 6 件）＋ [`p9-audit-triage.md`](p9-audit-triage.md)（指摘ごとに 1 行。**再確認はこれから**） |
| **P10（段 1 の行を後から進める・実体が無い行を片付ける）の実装の記録** | [`deletions-advance.md`](deletions-advance.md)（**履歴ではなく、いまの実装の記録**。口 4 つ・決めた 8 点・**設計の穴 4 件**・複製で通した線 **14 件**・壊し試験 **13/13**・申し送り） |
| P8 の点検と仕分け | [`p8-review-report.md`](p8-review-report.md) ＋ [`p8-review-triage.md`](p8-review-triage.md) |
| P8 の監査と仕分け | [`p8-0-audit-report.md`](p8-0-audit-report.md) / [`p8-1-audit-report.md`](p8-1-audit-report.md) / [`p8-2-audit-report.md`](p8-2-audit-report.md) ＋ [`p8-2-audit-recheck.md`](p8-2-audit-recheck.md) / [`p8-3-audit-report.md`](p8-3-audit-report.md) ＋ [`p8-3-audit-recheck.md`](p8-3-audit-recheck.md) / [`p8-4-audit-report.md`](p8-4-audit-report.md) ＋ [`p8-4-audit-recheck.md`](p8-4-audit-recheck.md)（＋各 `p8-*-audit-triage.md`） |
| P8 の実装の記録（自分で決めた点・穴） | `docs/p8-{0,1,2,3,4,5}-implementation.md` |
| **P8-6（参照切れの再リンク）の実装の記録** | [`p8-6-relink.md`](p8-6-relink.md)（**履歴ではなく、いまの実装の記録**。`POST /api/locations/relink` と `GET /api/locations/missing`・`location_history` の 3 列・`create_app()` の硬化・**事故 3 件目**・**設計の穴 6 件**・申し送り） |
| 帯の取りこぼしの調査 | [`p8-3-band-miss.md`](p8-3-band-miss.md)（8bit × 8 本 → 4bit × 16 本） |
| 前の段の記録（歴史） | `docs/p4-*` / `docs/p5-*` / `docs/p6-*` / `docs/p7-*`（P7 は廃止。[`p7-decision.md`](p7-decision.md)） |
| 朝のまとめ（利用者向け） | [`p6-morning-report.md`](p6-morning-report.md)（P8 は利用者への問いを §0.14 で先に済ませた） |
| 控え | `.backup\`（**9 フォルダ**。`pre-p4-*` / `pre-p7-removal*` / `pre-p8-0-*` / `pre-p8-1-restart-*` / `pre-p8-2-restart-*` / `pre-p8-4-20261017-232148` / `pre-p8-6-20261018-100443`） |
| 検証の道具 | `tools/gui_smoke.mjs` / `tools/gui_layout.mjs` / **`tools/gui_layout_seed.py`** / `tools/probe_p4.py` / `tools/probe_p6_1a.py` / `tools/probe_p6_2.py` / **`tools/probe_p8.py`** / **`tools/probe_p9.py`（P9 の性能）** / **`tools/make_synthetic_db.py`（1 万枚の合成 DB）** / **`tools/probe_deletions_advance.py`（P10。複製を作って 14 件の線・`--serve` で gui_layout 用のサーバ）** / `tools/gui_shot.mjs` / `tools/check_contract_p6.py` / **`tools/check_contract_p8.py`** |

---

## 9. Agent skills（このセッションで Fable が作成）

**実装者（DeepSeek / dsh）と監査者（Fable）が同じ知識から始められるように**、Fable が 3 つ作りました。
`origin: Fable が作成（2026-10-16）。各規則に根拠の文書が添えてある`。

| skill | 誰のため | 何が書いてあるか |
| --- | --- | --- |
| **`image-reviewer-dev`** | **実装する側（DeepSeek / dsh）** | 段の流れ（設計→点検→仕分け→小段実装→監査）、**正になる文書の優先順位**、検証の三点セット、道具、**データの安全**（`backup()` で WAL を畳む）、**環境の罠 8 件**（`UV_CACHE_DIR`・`os error 32`・`execution_cached`・`LoadImage` の制約・CUDA の黙った CPU 落ち・cp932…）、**家風の表 16 行**（`GET` は書かない・`CHECK`・移行は足すだけ・`client_token`・actor の検査は 1 か所・取引の中で外部を待たない・括弧を落とさない…）、合格の線の書き方 |
| **`image-reviewer-audit`** | **点検・監査する側（Fable。私が監査するときも）** | 実行して確かめるやり方、指示書の読み方、複製の作り方、**報告の形（A〜H と最も重大な 3 件）**、質問は `G` に推奨つきで書いて待たずに進む規律、**実際に踏んだ罠のカタログ**（`GET` が書く・部分索引・浮動小数の境界・ヘッダの enum で 500・契約の欄を出さない・壊しても落ちないテスト・キャッシュに当たった計測・位置対応の訳・WAL を畳まない複製・申告していない穴・無い画面・コードを読んだだけの監査） |
| **`orca-relay`** | 両方（Orca の往復） | `orchestration send` の本文の作り方（**二重引用符と山括弧を入れない**・UTF-8 のファイルから）、`check --ack` / `--wait`、`terminal send`、subject の付け方、返信先の run id、依頼への答え方 |

**置き場（2026-10-16 に Fable が確かめ直して決めた。詳細と根拠は [`skills-layout.md`](skills-layout.md)）**

- **原本は `C:\work\image-reviwer\.agents\skills\<name>\SKILL.md` の 1 か所。** DSH はここを `project-agents`（rank 200）として読む
  （`@deepseek-ai/dsh-skill-filesystem/lib/index.js` の `roots()`。rank は小さい方が勝つ）。
- **Claude Code が読む `.claude\skills\<name>` は、原本への Windows ジャンクション**（Claude Code は `.agents/skills` を直接は読まない。
  実行で確認）。張り直しは `powershell -ExecutionPolicy Bypass -File .agents\link-skills.ps1`（何度打っても同じ）。
- **利用者レベル（`~/.claude/skills`・`~/.agents/skills`）と `docs/skills/` の写しは撤去した。** Claude Code は同名なら
  **利用者 > プロジェクト**なので、写しを残すと古い方が勝つ。**直すのは `.agents/skills/` だけ**。
- **注意**: DSH はプロジェクトの根を `.git` で探し、無ければ起動した `cwd` を根にする。このリポジトリは git 管理外なので、
  **DSH は `C:\work\image-reviwer` で起動する**（下のフォルダで起動すると `.agents/skills` が読まれない）。
- `skills` CLI（vercel-labs）はこれと同じ形（原本 `.agents/skills` ＋ 各エージェントへのジャンクション）を自分で作る。
  CLI が手置きを消すのは**同名を入れ直したときだけ**。
---

## 10. この引継書の更新

次のセッションが作業を進めたら、**このファイルを更新**してください（§1 の状態・§3 の次の手順・§7 の判断待ち）。
`docs/p6-morning-report.md` は「利用者に読ませる」用途、**この引継書は「次のエージェントに読ませる」用途**です。
- **未解決（2026-10-18。2026-10-19 も未解決）**: **アプリのプロセスから %USERPROFILE% に書けない**（C:\Users\yukse\image-reviewer-backups を WinError 5 で作れない。**同じ持ち主のシェルからは作れる**。CFA は無効・ACL も正常・系譜は Explorer → cmd → uv → exe）。**回避策として settings.backup_dir を C:\work\image-reviwer\.backup\daily\ にした**（利用者の決定）。**別ドライブにしたい場合はこの謎を先に解く**（#/settings から戻せる）。**診断には利用者の許可が要る**（§3 の 4・§7 の新 5）。
- **利用者の判断（2026-10-18 夜）**: **193 枚を削除した（意図どおり）**。内訳: ファイルは **20:01 にエクスプローラでゴミ箱へ**（元は `C:\ai\...\ComfyUI\Anima\20261010`）→ **20:04〜20:12 にアプリで段 1 の印**（`deletion_log` 193 行・`delete_request` 30 回・`actor='human'`）。**アプリはファイルを 1 枚も動かしていない**（段 2/3 の記録 0・`trash` / `pending-delete` は空・`missing_at` 0）。**そのあと ComfyUI が同じフォルダに同じ名前で生成中**（20:27 時点 37 枚・**台帳の size と一致しない**＝別の絵）。**利用者は「そのまま」を選択**（**戻さない**）。**`#/pending-deletes` の「戻す」は `stuck` で止まる**（元の場所に別のファイルがあるため）＝**正しい動作**。`asset` 455（うち 193 が `deleted_at` で隠れている）
- **2026-10-19 の実データ（P10 の文書反映のときに `mode=ro` で読んだだけ。1 バイトも書いていない）**:
  **`asset` 461 行・生きた 267 枚・`deletion_log` 194 行（全部が段 1 で生きたまま）**。
  **段 1 の 194 行のうち、実体が在るのは 7 行・実体が無いのは 187 行**（実体が在る 7 行のうち **6 行**は
  台帳の `asset_id` が古い形＝§6 の罠）。**`closed_at` / `close_reason` の列は、この読みのあとの
  16:48:56 にトレイの自己検査の穴で足された**（事故 4 件目。控え無し・行の変化 0・
  [`tray.md`](tray.md) §6）。
  **次の 1 操作は利用者の再起動 → 「まとめて片付ける」**（→ §3 の 5・§7 の新 3）。
- **★重要（2026-10-19 に確定）★ アプリのプロセスは「ワークスペースの外」に書けないことがある**。実測: 同じ持ち主（DIANA\yukse）・拒否の項目 0・ロック無し・所有者も同じなのに、**トレイ経由で起動したアプリは C:\work\image-reviwer の外へ書けない**（%USERPROFILE%\image-reviewer-backups を作れない・C:\work\illust-authoring\... のファイルをゴミ箱へ移せない＝WinError 5）。**私のシェル（DSH）は同じ場所に書ける**。**スタートメニューから開いた新しい cmd は書けた**（`mkdir C:\work\test-probe` が通った）＝**セッション全体の制限ではなく、アプリの起動の系譜（親プロセス）の問題**。PATCH /api/settings で `backup_dir` を外にしても **500 で書けない**（last_error も残らない）。**回避策**: ①**アプリを「制限の無い窓」から起動する**（新しい cmd で `start-image-reviewer-console.cmd`）②外のファイルを動かしたいときは**利用者がエクスプローラで消してから「ファイルが無いので片付ける」**（**アプリは元のファイルに触らないので必ず通る**）③バックアップは `.backup\daily`（ワークスペースの中）に置く。**設計の「<data> の外に置く」はこの環境では満たせない**（`design.md` に注記が要る）
