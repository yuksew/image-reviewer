# 引継書 — image-reviewer / **P9（仕上げ）完了。§14 の段は全部済み**（2026-10-18 時点）

このセッション（dsh・ワークツリー `dsh`）で進めた内容と、**次のセッションがそのまま続けられる形**の引継ぎです。
読む順: **§0 危険な操作 → §1 いまの状態 → §2 Fable との往復 → §3 次の手順**。細部は §4 以降。

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
>   **§14 の段はこれで全部済み**——次にやるのは**利用者の判断待ち**（トレイ・再リンクの画面・
>   一覧 API の改ページ・`--include-library` を日次に載せるか・exe 化）。
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
>   `design.md` の §5.1・§5.8・§6.1・§14・§15・§16.6 に反映した。**トレイ（常駐）も無い**（常駐の実装がリポジトリに無い。`design.md` §16.6）。
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
| **版を上げずに表を変える**（`ALTER TABLE` のトップアップ） | P8-4 で実データに `deletion_log.stuck_reason` が**控え無しで**足された（事故 2 件目） | **変える前に `pre-topup-<日時>/` の控えを取る**（`pre-migrate-*` と同じ）。**足す物の一覧は `db.TOP_UP_COLUMNS` が正** |
| **`IMAGE_REVIEWER_DATA` を付けずに `create_app()` を呼ぶ** | **P8-6 の事故 3 件目**（検証スクリプトが env を付け忘れ、**実データを書き込み可で開いた**。`location_history` の 3 列と `settings.backup.last_error` が書き換わり、**行の変化は 0**） | **`create_app()` は env が無ければ開く前に `RuntimeError`**（**1 バイトも書かない**）。**既定の `.data` を明示的に指すのは `cli serve`（`serve_data_dir()`）だけ**。**実データを触り得るコマンドには必ず `IMAGE_REVIEWER_DATA=<複製>`**（`mode=ro` も同じ）。控えは `.backup/pre-p8-6-20261018-100443/` |
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
| **P8-5（画面の仕上げ。合格の線に数えない）** | **完了 → 監査は「合格（条件つき）」**。`#/settings` のバックアップ（最後の失敗の全文・7 世代・**取り直す**・置き場）と**置き場ごとの「段 3 を許す」印**・上部バーの「バックアップに失敗しています」と「走査中です」・段 3 の出し分け・文言の追い込み。**トレイは作らない**（常駐の実装が無い）。口は `GET /api/scan` の 1 つだけ足した。**条件 3 件（C-1〜C-3）は未反映**（下の「次の手順」の 0）。**画面の語は「取り直す」に統一した**（下の 0 の D-1） | `docs/p8-5-implementation.md`、[`p8-5-audit-report.md`](p8-5-audit-report.md)、[`p8-5-audit-triage.md`](p8-5-audit-triage.md) |
| **P8-6（参照切れの再リンク。合格の線 9）** | **完了。2026-10-18**（**監査はこれから**）。`POST /api/locations/relink`（**人だけ**。`exact` = 新しいファイル / `nearby` = 探すフォルダ）と `GET /api/locations/missing`（**読むだけ**）・`location_history` に `to_path` / `reason` / `actor`（**版は上げない**＝`pre-topup-*` の控え）・**`create_app()` の硬化**（**`IMAGE_REVIEWER_DATA` が無ければ開かない**）・**事故 3 件目**（実データに 3 列が控え無しで入った。**行の変化は 0**。控え `.backup/pre-p8-6-20261018-100443/`）。**画面は作っていない**（口だけ）。`tools/probe_p8.py --relink` が **16 行すべて OK**・`pytest` **507 件** | [`p8-6-relink.md`](p8-6-relink.md) |
| **P8 の合格の線（P8-1〜P8-4）** | **済み。2026-10-18**（**残っていた再リンク＝線 9 も P8-6 で実装済み**）。決定は [`docs/design.md`](design.md) §16.6 に反映済み。**画面の仕上げ（P8-5）は監査の条件 3 件が残っている** | `docs/design.md` §14・§16.6、[`p8-5-audit-report.md`](p8-5-audit-report.md)、[`p8-6-relink.md`](p8-6-relink.md) |
| **P9（仕上げ）** | **完了（2026-10-18）**。**§12.1 の「目標」の行を全部実測で埋めた**（**未計測 0**）。届かなかったのは**一覧 API の 1 行だけ**（p95 **244.7 ms** / 目標 20 ms。**目標は下げていない**。理由と必要な条件は §12.1）。計測の途中で **`PRAGMA temp_store = MEMORY` の欠落**（1 万枚の `GET /api/assets` が 500 になっていた）と **D-8**（壊れていない DB に復元を勧めていた）を直し、**一覧で切った枚数を画面に出した**。道具は `tools/make_synthetic_db.py`（1 万枚の合成 DB）と `tools/probe_p9.py`（**サーバ内**の計測） | [`p9-implementation.md`](p9-implementation.md)、[`design.md`](design.md) §12.1・§12.2・§12.3・§16.7 | [`docs/design.md`](design.md) §14 |

**いまの数（実測。2026-10-18・P9 の最後に回した）**: `pytest` **518 件**（**5 回**回して**5 回とも緑**。
2〜5 回目は 37.5〜38.2 秒。1 回目は 66.1 秒＝計測のサーバと Chrome が同時に走っていた）・
`gui_smoke` **322 検査（NG 0）**・`gui_layout` **10 画面＋`pending --ids` の 11 本**（**11 本とも ok**。
複製 8795 で。**`--screen pending --ids` には生きている枚を渡す**——外した枚を渡すと
「置き場を確かめられないので段 3 は出していません」が出て NG になる。**あれが正しい動作**）。
`SCHEMA_VERSION = 6`。**実データは v6・455 枚（生きた 262 枚）・段 1 の 193 行・判断 3 件・`missing_at` 0 件**。
**P9 の前後で画像の署名 `d9604560e494c510` と `.data` の署名 `ae60041b0b0b5365` が同じ。**

### いま走っているもの

**利用者のアプリが 8790 で動いています**（2026-10-18 08:38 起動の個体。PID 7324）。**止めない・触らない。**
**画面（静的ファイル）は P8-5、裏側のプロセスは P8-4 まで**です（`GET /api/scan` は **404**。P8-5 の監査が実機で確かめた形。
**P8-5 のコードで立て直すと 200 になる**）。**P9 の間も一度も止めていない**（`/api/health` も打っていない）。
**日次バックアップだけは sandbox の中で失敗しています**（§0 の表。`GET /api/backup` の `last_error` に `WinError 5`・`count 0`）。
**P8-5 の監査は出ました**（[`p8-5-audit-report.md`](p8-5-audit-report.md)。**合格（条件つき）**。条件 3 件は下の「次の手順」の 0）。
**P8-6 の監査はまだ受けていない**（`p8-6-audit-triage.md` の指摘は反映済み）。

### 未着手

- **P8-5 の監査の条件 3 件（C-1〜C-3）**: **未反映**（→ **§3 の 0** に直し方つき）。
- **再リンク（P8 の合格の線 9）**: **口は P8-6 で実装済み**（`POST /api/locations/relink` は**人だけ**で
  `exact` / `nearby`、`GET /api/locations/missing` は**読むだけ**。**中身の `sha256` が一致したときだけ繋ぎ、
  `pHash` は使わない**。実装の記録は [`p8-6-relink.md`](p8-6-relink.md)）。**残っているのは画面**（P8 では
  作らないと決めたまま。`design.md` §6.1）。**P8-6 の監査もこれから**。
- **P9（仕上げ）**: **完了**（2026-10-18）。§12.1 の未計測は 0（届かなかったのは一覧 API の 1 行だけ）。
  記録は [`p9-implementation.md`](p9-implementation.md)。**次にやるのは利用者の判断待ち**（下の §7 と
  `p9-implementation.md` §8 の申し送り: **一覧 API のキーセット改ページ**・**一覧の仮想グリッドとページ送り**・
  **768px の上部バー**・**`--no-hash`**・**exe 化**）。
- **トレイ（タスクトレイ常駐）**: **常駐の実装がリポジトリに無い**ので作っていない。作る段で `frontend-design.md` §11 の
  入口 (c)（「最近の削除を開く」）を足す。
- **P2 / P3 の残り**: 仮想フォルダ・スマートフォルダ・取込の 3 経路（D&D / クリップボード / URL）・
  `userdata` への設置・タグの統合と改名・本格的な検索・プリセットの画面。
- **実機の日次バックアップ**: **利用者が sandbox の外で 8790 を立て直す**（それだけで取れるようになる。
  `count` が 1 以上になったことを 1 度確かめる）。
- **`README.md` と `docs/design.md` の本体は反映済み**（README は 507 件・310 検査・10 画面＋`pending --ids`・
  P8 の文書表（**P8-6 の行**）・未実装の一覧。design.md は §5.1・§5.8・§6.1・§6.2・§9.5・§11・§12.1・§12.3・
  §14・§15・§16.6。**P8-6 の反映は §5.1・§5.8・§6.1・§14・§15・§16.6**）。
  **`docs/p8-*.md` は歴史としてそのまま**（§16.6 に決定を集約した。**例外は P8-6 の記録 `p8-6-relink.md`**＝
  履歴ではなく**いまの実装の記録**）。

### セッションを切り替えるときの注意

**進行中の作業は無いので、いつ切っても安全です。** ただし次のセッションの最初に**これを回して緑を確かめてください**:
`uv run --no-sync pytest -q`（**507 passed が期待値**）と `node tools/gui_smoke.mjs`（**310 ok / NG 0**）。
**`git` 管理です**（`https://github.com/yuksew/image-reviewer`）。ただし**エージェントはコミットしない**（親が行う）。
控えは `.backup/`（**9 フォルダ**。**消さない**）。


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

### 0. P8-5 の監査の条件 3 件（**未反映**。[`p8-5-audit-report.md`](p8-5-audit-report.md)）

**C-1 印のボタンは二度押しで 2 回 POST される**（`apps/gui/settings.js` の `setAllow` だけ `state.busy = true; render();` が無い。
`takeNow` / `saveDir` と同じ形にする。`gui_smoke` に「2 回押しても 1 回」を 1 行）。
**C-2 `gui_layout --screen asset` が「段が 3 つ」を前提にしていて、印の無い置き場の枚では必ず NG**
（`tools/gui_layout.mjs` の `PRESS_ASSET_DELETE`。`.pd-stage` は 2 以上に緩め、「印が無ければ 2・あれば 3」は API と突き合わせる。
**印ありの複製で回す手順だと見えない**——`--no-stage3` でも 11 本を回す手順を記録に足す）。
**C-3 版が新しい DB（`read_only` だが `GET /api/backup` は 200）では設定の「いま取る」「保存する」が押せるまま**
（`backupHtml()` の分岐を `state.status === 503 || got.read_only` にし、`reason` は `GET /api/health/db` から引く）。
軽微（D-1〜D-9）の推奨は監査の §G に 1 行ずつ（D-1「取り直す」→「いま取る」・D-2「今日の分」の文・D-4 走査の印は順番待ちを含む・
D-7 §11 のトレイの 1 行 など）。

### 1. P9（仕上げ）— **済み（2026-10-18）**。未計測は 0 になった

**正**: [`design.md`](design.md) §14 の P9 の行と §12.1 の「目標」の行（**§12.1 の表はもう「未計測」が無い**）。
**記録**: [`p9-implementation.md`](p9-implementation.md)（測り方・生の値・届かない物・見送った物・exe 化の推奨）。
**結果**（P8 の時点で「未計測」と書いてあった物）:

| 測る物 | 結果 |
| --- | --- |
| 1024px サムネイルの生成 | **128 ms/枚（実画像）→ 1 万枚 21.3 分**（同時 8 本で 3.7 分）。**目標を 25 分と決めた** |
| 一覧 API の応答（1 万枚・p95 20ms） | **244.7 ms（届かない）**。理由は §12.2 の「一覧」が未実装。**目標は下げていない**。実データ 262 枚なら 14.3 ms |
| グリッド初回表示 300ms（100 枚・Chrome） | **87 ms**（最初のカード）。299 枚で 93 ms・1 万枚（2000 枚で切れる）で 532 ms |
| 追加ページ読み込み 100ms | **実装が無い**（1 回の `limit=2000` で全部描く。**測る対象が無い**） |
| 2 回目以降の走査（差分なし・10 秒） | **2.62〜2.70 秒** |
| 一括削除の再照合（1,000 件で 1 秒） | **596 ms**（`os.stat` だけなら 13.8 ms） |
| `--include-library`（実データ 291.1 MB） | **2.40 秒**（132 MB/s。1 万枚 11.1 GB なら 1.4 分）。**目標を 5 分と決めた** |
| 再リンクの `nearby`（1 万枚） | **39.2 ms**（全部歩く最悪）／44.6 ms（1 段目で見つかる）。**目標を 3 秒と決めた** |
| タグ付け 0.5 秒/枚（GPU） | **未再計測**（**ComfyUI に触らない**指示のため。いまは `IllustTagger` 0.27 秒/枚） |
| `--no-hash` の初回走査（30 秒） | **実装が無い**（`cli scan` にその口は無い。**測る対象が無い**） |
| 判断の記録（100ms） | **p95 1.5 ms** |
| 日次バックアップ（5 秒） | **201 ms**（DB が 3.2 MB になったので P8-4 の 37 ms より大きい） |

**計測の作法**（家風）: サーバ内（`TestClient`）で測る・**別々の入力**で測る・**何回の p95 か**を書く・
**「初回生成」と「生成済み」を分ける**（分けないと「配信」を測ってしまう。**実際に踏んだ**）・
**土台（`/api/health`）の p95 を一緒に出す**。道具は `tools/probe_p9.py`（`--all`）と
`tools/make_synthetic_db.py`（1 万枚の合成 DB）。

### 2. 再リンク（P8 の合格の線 9）— **済み（P8-6。監査待ち）**

`POST /api/locations/relink`（**近くを探す**＝`nearby`・**場所を指定**＝`exact`。**人だけ**。
**`sha256` が一致しなければ 409 `hash_mismatch`**）と `GET /api/locations/missing`（**読むだけ**）。
設計は `p8-design.md` §0.11 と §3.2、元ネタは [`duplicates-deletion-backup.md`](duplicates-deletion-backup.md) §4。
**実装の記録は [`p8-6-relink.md`](p8-6-relink.md)**（**16 行すべて OK**・`pytest` 507 件・**事故 3 件目**と
`create_app()` の硬化もそこ）。**`design.md` の「まだ無い」は §5.1・§5.8・§6.1・§14・§15・§16.6 で直した**。
**残っているのは画面と監査**（**「自動（走査のたびに繋ぐ）」は作らないと決めた**＝`duplicates-deletion-backup.md` §4）。

### 3. 利用者に頼む 1 操作（バックアップ）

**利用者が sandbox の外（自分の端末）で 8790 を立て直す。** それだけで日次が取れるようになる
（`%USERPROFILE%\image-reviewer-backups` が作られ、`GET /api/backup` の `count` が 1 以上になる）。
**置き場を変えて凌ぐ**なら `PATCH /api/settings {"backup_dir": "C:\\work\\image-reviwer\\.backup\\daily"}`
（`.backup/` は既に控えの置き場なので趣旨に合う。**`<data>` の中は 422 で断られる**）。

---

## 4. 検証の三点セットと道具

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
uv run --no-sync pytest -q                      # 507 件
node tools/gui_smoke.mjs                        # 322 ok（軽い DOM。CSS を持たない）
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
# ★ --screen asset は「段が 3 つ」を前提にしている（P8-5 の監査 C-2）。**印の無い置き場の枚では必ず NG**になるので、
#   段 3 の印を立てた複製で回す（上の seed の --stage3）。印なしの形は --no-stage3 で別に回す（未修正）。
# ★ --screen pending --ids には**生きている枚**を渡す（P9 で踏んだ）。外した枚（deleted_at）を渡すと
#   「置き場を確かめられないので段 3 は出していません」が出て、段 3 の検査が 3 窓とも NG になる（**正しい動作**）。
# 実機の線（合否を出す）
uv run --no-sync python tools/probe_p4.py --engine comfyui   # P4 の線 1・2・7
uv run --no-sync python tools/probe_p6_1a.py                 # P6 の性能（線 150ms / 20ms）
uv run --no-sync python tools/probe_p6_2.py --base http://127.0.0.1:8791   # 切り出しの画素
uv run --no-sync python tools/probe_p8.py --duplicates       # P8 の線 2〜4（帯を総当たりと突き合わせる）
uv run --no-sync python tools/probe_p8.py --delete           # P8 の線 5〜8（3 段階と 5 分の窓）
uv run --no-sync python tools/probe_p8.py --backup           # P8 の線 10・12（日次と健全性）
uv run --no-sync python tools/probe_p8.py --restore          # P8 の線 11（消して戻す・組み直し）
uv run --no-sync python tools/probe_p8.py --all              # 全部（自分の置き場を作り、後始末する）
uv run --no-sync --with jsonschema python tools/check_contract_p6.py       # 契約の検証（P6）
uv run --no-sync --with jsonschema python tools/check_contract_p8.py       # 契約の検証（P8 の backup-manifest）
# P9（性能の実測。**合成 1 万枚の DB と実データの複製を作る**。§12.1 の表を作り直せる）
uv run --no-sync python -X utf8 tools/make_synthetic_db.py --out .tmp-audit-redo/p9/synth10k --count 10000
uv run --no-sync python -X utf8 tools/probe_p9.py --all --replica <実データの複製> --runs 30
```

---

## 5. 数字の記録（次のセッションが前提にできる実測）

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

**P9 で「段」は全部終わったので、ここにある物が次にやることの全部**です。
**P9 の申し送り（`p9-implementation.md` §8）も同じ内容**です。

1. ~~**★ 8790 を sandbox の外（自分の端末）で立て直す**（**バックアップのため**）~~ → **済み（P9 の監査 D-4 で確認）**。
   **8790 は Explorer → `start-image-reviewer.cmd` の系譜で動いていて（PID 7324）、利用者が置き場を
   `.backup/daily` に変え、日次は取れている**（`GET /api/backup` の実測）:
   **`20261018`（263 枚・17:12 JST）・`20261018-171143`（「いま取る」）・`20261019`（455 枚・00:00:15 JST）**。
   `%USERPROFILE%\image-reviewer-backups` は無い（既定のままでは使えない、という §13 の謎は未解決のまま）。
   **`.backup/` はリポジトリの中・同じドライブ**なので、別のドライブに置くかは利用者の判断。
2. **★ 一覧 API のキーセット改ページを入れるか、いつ入れるか**（**P9 で唯一目標に届かなかった行**）。
   p95 **244.7 ms** / 目標 20 ms。**1 万枚が現実になるまでは困らない**（実データ 262 枚で p95 14.3 ms）ので、
   P9 では入れずに**段を別に立てる**ことにした。入れるときは `total` の意味と `q` / `tag` の絞り込みが
   変わるので、**テストと画面の前提を一緒に直す**（`design.md` §12.1 の「必要な条件」）。
3. **一覧の仮想グリッドとページ送りを入れるか。** いまは `limit=2000` で 1 回引いて全部描くので、
   **1 万枚では 2000 枚で切れる**（P9 で「先頭 2000 枚を表示」と出すようにした）。**2000 枚より先を見る道が無い**。
   入れるなら**狭い窓の検査**（`gui_layout` の `VIEWPORTS` は 1200 以上しか無い）とセットで。
4. **再リンクの画面を作るか、いつ作るか。** **口は P8-6 で作った**（`POST /api/locations/relink` は**人だけ**・
   `GET /api/locations/missing` は読むだけ。**画面は無い**＝対象の枚を一覧で見て「近くを探す」「場所を指定」を
   押す画面。`docs/frontend-design.md` に項目が無いので、作るなら画面設計から）。
5. **トレイ（タスクトレイ常駐）を作るか。** いまは**常駐の実装がリポジトリに無い**ので、画面の一覧と入口から外してある
   （`frontend-design.md` §3・§4.5・§4.6・§11）。**利用者の当初の回答は「トレイに出す」**なので、作る段を決める。
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
| 全体の設計（正） | [`design.md`](design.md)（**P8 の決定は §16.6**。表は §5.8・口は §6.1・性能は §12.3・段は §14。**P8-6 の再リンクは §5.1・§5.8・§6.1・§14・§15・§16.6**） |
| フロントの設計 | [`frontend-design.md`](frontend-design.md)（画面一覧は §3。**削除と重複は §4.6**・文言は §6・細部は §11） |
| 段ごとの設計 | [`p8-design.md`](p8-design.md)（**§0 が拘束力のある差分**） / `p5-design.md` / `p6-design.md` / `p4-design.md` |
| **P9（仕上げ）の実装の記録** | [`p9-implementation.md`](p9-implementation.md)（**§12.1 の実測値の表**・測り方・届かない物・**exe 化の推奨**・見送った物・申し送り・設計の穴） |
| P8 の点検と仕分け | [`p8-review-report.md`](p8-review-report.md) ＋ [`p8-review-triage.md`](p8-review-triage.md) |
| P8 の監査と仕分け | [`p8-0-audit-report.md`](p8-0-audit-report.md) / [`p8-1-audit-report.md`](p8-1-audit-report.md) / [`p8-2-audit-report.md`](p8-2-audit-report.md) ＋ [`p8-2-audit-recheck.md`](p8-2-audit-recheck.md) / [`p8-3-audit-report.md`](p8-3-audit-report.md) ＋ [`p8-3-audit-recheck.md`](p8-3-audit-recheck.md) / [`p8-4-audit-report.md`](p8-4-audit-report.md) ＋ [`p8-4-audit-recheck.md`](p8-4-audit-recheck.md)（＋各 `p8-*-audit-triage.md`） |
| P8 の実装の記録（自分で決めた点・穴） | `docs/p8-{0,1,2,3,4,5}-implementation.md` |
| **P8-6（参照切れの再リンク）の実装の記録** | [`p8-6-relink.md`](p8-6-relink.md)（**履歴ではなく、いまの実装の記録**。`POST /api/locations/relink` と `GET /api/locations/missing`・`location_history` の 3 列・`create_app()` の硬化・**事故 3 件目**・**設計の穴 6 件**・申し送り） |
| 帯の取りこぼしの調査 | [`p8-3-band-miss.md`](p8-3-band-miss.md)（8bit × 8 本 → 4bit × 16 本） |
| 前の段の記録（歴史） | `docs/p4-*` / `docs/p5-*` / `docs/p6-*` / `docs/p7-*`（P7 は廃止。[`p7-decision.md`](p7-decision.md)） |
| 朝のまとめ（利用者向け） | [`p6-morning-report.md`](p6-morning-report.md)（P8 は利用者への問いを §0.14 で先に済ませた） |
| 控え | `.backup\`（**9 フォルダ**。`pre-p4-*` / `pre-p7-removal*` / `pre-p8-0-*` / `pre-p8-1-restart-*` / `pre-p8-2-restart-*` / `pre-p8-4-20261017-232148` / `pre-p8-6-20261018-100443`） |
| 検証の道具 | `tools/gui_smoke.mjs` / `tools/gui_layout.mjs` / **`tools/gui_layout_seed.py`** / `tools/probe_p4.py` / `tools/probe_p6_1a.py` / `tools/probe_p6_2.py` / **`tools/probe_p8.py`** / **`tools/probe_p9.py`（P9 の性能）** / **`tools/make_synthetic_db.py`（1 万枚の合成 DB）** / `tools/gui_shot.mjs` / `tools/check_contract_p6.py` / **`tools/check_contract_p8.py`** |

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
- **未解決（2026-10-18）**: **アプリのプロセスから %USERPROFILE% に書けない**（C:\Users\yukse\image-reviewer-backups を WinError 5 で作れない。**同じ持ち主のシェルからは作れる**。CFA は無効・ACL も正常・系譜は Explorer → cmd → uv → exe）。**回避策として settings.backup_dir を C:\work\image-reviwer\.backup\daily\ にした**（利用者の決定）。**別ドライブにしたい場合はこの謎を先に解く**（#/settings から戻せる）。
- **利用者の判断（2026-10-18 夜）**: **193 枚を削除した（意図どおり）**。内訳: ファイルは **20:01 にエクスプローラでゴミ箱へ**（元は `C:\ai\...\ComfyUI\Anima\20261010`）→ **20:04〜20:12 にアプリで段 1 の印**（`deletion_log` 193 行・`delete_request` 30 回・`actor='human'`）。**アプリはファイルを 1 枚も動かしていない**（段 2/3 の記録 0・`trash` / `pending-delete` は空・`missing_at` 0）。**そのあと ComfyUI が同じフォルダに同じ名前で生成中**（20:27 時点 37 枚・**台帳の size と一致しない**＝別の絵）。**利用者は「そのまま」を選択**（**戻さない**）。**`#/pending-deletes` の「戻す」は `stuck` で止まる**（元の場所に別のファイルがあるため）＝**正しい動作**。`asset` 455（うち 193 が `deleted_at` で隠れている）
