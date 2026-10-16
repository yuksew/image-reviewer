# 1 回目の点検（DeepSeek）の仕分け ― 未仕分けだった指摘

[`review-report-deepseek.md`](review-report-deepseek.md)（A10 / B16 / C21 / D15 / E8 / F11 / G12 / H）のうち、
[`review-triage.md`](review-triage.md) が仕分けていない指摘を **1 件ずつ**振った記録。
2 回目の点検（[`review-report.md`](review-report.md) の C1）が「約 40 件が採用も却下もされていない」と指摘した穴を閉じる。
**この文書は指摘の再掲ではなく、状態・直す場所・直す内容の一覧である。**

- 確認した版: 2026-10-15 10:13〜10:16 時点の作業ツリー
  （`design.md` 10:16 / `frontend-design.md` 10:14 / `duplicates-deletion-backup.md` 10:14 /
  `workflow-reproduction.md` 10:13 / `schemas/review-export.schema.json` 10:13 / `comparison.md` 06:39）。
  **この仕分けと並行して 2 回目の反映が進んでいた**ため、行番号はずれうる。節で引く。
- 対象: A9・A10・**B5・B6**・B9〜B16・C1〜C21・D1〜D15・E1〜E8・F1〜F11・G1〜G12・H。
  - **1 回目の E は E8 までしかない**（E9・E10 は 2 回目の点検の番号）。同じ `E9` でも別の指摘なので注意。
  - **B5・B6 は `review-triage.md` に載っていない**（2 回目 C1 の指摘どおり）。この文書で仕分ける。
- 状態の意味:
  - **採用** = 今の文書をまだ直す必要がある。**2 回目の点検も引き取っていない**もの。→ §5 の作業リスト。
  - **却下** = 指摘が誤っている。理由を書く。
  - **対応済み** = 既に反映済み、**または** 2 回目の点検（クライアント承認済み）が同件を引き取ったもの。
    どちらで閉じたかを「何をするか／何で直ったか」に書く。

---

## 1. 仕分け

### A. 決定との矛盾

| id | 主題 | 状態 | 場所 | 何をするか／何で直ったか |
| --- | --- | --- | --- | --- |
| A9 | 「外へ出るのは ComfyUI だけ」が URL 取り込みと矛盾 | 対応済み | `design.md` §3・§4・§5.1 | `design.md` は「ComfyUI と、利用者が明示した URL の取得だけ」＋ URL 取得の上限表に**反映済み**。`frontend-design.md` §2.3 の「ネットワークを使わずに動く」は未修正で、**2 回目 A1 が同件を引き取る** |
| A10 | 通知の音の理由が「常駐していないため」 | 対応済み | `frontend-design.md` §11 | 「使わない（**決定による**）。件数・タブのタイトル・トレイのアイコンで示す」に**反映済み** |

### B. 重大な問題（B5・B6 は 1 回目の仕分け表に無かったもの）

| id | 主題 | 状態 | 場所 | 何をするか／何で直ったか |
| --- | --- | --- | --- | --- |
| B5 | 印を `filename_prefix` に入れる前提（リテラル・保存ノード）が無い | 対応済み | `workflow-reproduction.md` §4.7・§4.7.1 | **2 回目 B9** が前提の表（リンク入力なら印を付けない／複数保存ノードは同じ印）を要求（反映中） |
| B6 | seed 違いで全 `KSampler` を書き換える／印が `seed-<seed>` で一意でない | 対応済み | `workflow-reproduction.md` §4.7.2 | **2 回目 B9** が「保存ノードから遡って最初の 1 つだけ」を要求（反映中） |
| B9 | 契約 `runs[]` に seed / attempt_id / marker / matched_by が無い | 対応済み（一部未確認） | `schemas/review-export.schema.json` `Reproduction.runs` | `attempt_id` / `seed` / `marker` / `matched_by` / `result_asset_id` / 指標は**追加済み**。「どの書き出しの結果か」は満たす。`export_id` と `result_hash` は無い（`runs[].id` が書き出しを指すのかは **未確認**。§6） |
| B10 | 決定性テストが `generated_at` のせいで必ず落ちる | 対応済み | `design.md` §6.2・§14 テスト方針・schema `description` | 「`generated_at` を除いて決定的」に**反映済み**（提案 (a)(c) を採用。`content_hash` は足していない） |
| B11 | Host / Origin の検査が無く、外部から段 3 の削除に到達しうる | 対応済み | `design.md` §6.3.1 | 検査を**新設済み**（認証は入れない＝`review-triage.md` §2.3）。残る矛盾（multipart・独自ヘッダ・ポート）は **2 回目 C6 が引き取る** |
| B12 | 取り消しの `os.replace` が元パスの別ファイルを無警告で上書き | 対応済み | `duplicates-deletion-backup.md` §3.4 | 「事前に存在を確かめ、埋まっていれば戻さず**別名で戻すか尋ねる**。決して上書きしない」に**反映済み** |
| B13 | 一括削除のスコープを受け取る口が無い | 対応済み | `design.md` §6.1 `POST /api/locations/bulk-delete` | スコープ付きの口を**追加済み**（`review-triage.md` §2.2）。確認と実行のずれは **2 回目 A6**（preview / preview_id）が引き取る。※`review-triage.md` §2.2 の B13 / C8 は番号が入れ替わっている（2 回目 E10） |
| B14 | `asset_meta` に CLIP / TE の列が無い | 対応済み | `design.md` §5.2・schema `Provenance` | `asset_meta.clip` は**追加済み**（`clip2` は無い）。契約側の `Provenance.clip` / `llm` は **2 回目 C8(5) が引き取る** |
| B15 | `changed_fraction` の定義が 2 文書で違う | 対応済み | `comparison.md` §4・`workflow-reproduction.md` §4.8 | 定義を `comparison.md` §4 の**1 か所**に固定済み（閾値 8 は増幅前、3 倍増幅は表示だけ） |
| B16 | 完了条件が確かめられない段がある | 対応済み | `design.md` §14 | (a) P2 は 3,999 枚での実測＋換算、(c) P4 は実測、(d) P3 は既存 `/history` で、(e) P9 は「目標」行の実測、に**反映済み**。残る (b) P1 の 60fps の測定条件は **2 回目 C14 が引き取る** |

### C. 中程度

| id | 主題 | 状態 | 場所 | 何をするか／何で直ったか |
| --- | --- | --- | --- | --- |
| C1 | `recipe_*` 等が §5 に無い／§13 に置き場が無い | **採用**（残りは §13 だけ） | `design.md` §5.7・§13 | §5.7（専門文書が定義する表）は**追加済み**。§13 に `<data>/exports/<recipe_id>/`（`workflow-reproduction.md` §4.7 の書き出し先）が無く、`export\`（`design.md` §13）と `exports`（workflow）で**綴りが揺れている**。`src/image_reviewer/_gui`（`frontend-design.md` §10 が正）も §13 に無い |
| C2 | `GET /api/assets/{id}/graph?format=ui` の振る舞いが未定義 | 対応済み | `design.md` §6.1 | 実装は 404 を選んだ。**2 回目 I8** が「§6.1 に 404 と理由を書く」を引き取る |
| C3 | `reviews{subject_type:'group'}` と `decide` が重複／reopen が未定義 | 対応済み | `design.md` §6.1 | `POST /api/reviews` は**画像 1 枚専用に修正済み**。reopen の意味論は **2 回目 C5 が引き取る** |
| C4 | コメント `-- kind='url' のときの出所` が誤り | 対応済み | `design.md` §5.1 | 未修正のまま。**2 回目 D16** が `source='url'` に直す |
| C5 | 並び順の語彙が 3 か所で違う | **採用** | `design.md` §6.1 `GET /api/assets`・§10.3・`frontend-design.md` §11 | API の `sort` を `added\|seen\|name\|decided\|seed` に広げ、§10.3（「判断日時」）と frontend §11（「`疎` では seed 順」）をその語彙で書き直す |
| C6 | `POST /api/scan` に `mirror_folders` が無い | **採用** | `design.md` §6.1・§10.1 | 引数に `mirror_folders:false` を足し、既定と「2 回目以降の走査で増えた階層だけ足すか」を書く（§10.1 は既に前提にしている） |
| C7 | `--no-hash` の「一覧の表示だけ」を担う表と API が無い | **採用** | `design.md` §5.1・§6.1 | `POST /api/scan {dry_run:true}` の応答を**メモリ上（または一時ファイル）の一覧**として定義し、CLI の `--no-hash` はそれを表に出すだけ、と決める（`asset` を作らない＝判断はできない、を守る） |
| C8 | 設定の表と `system_prompt` の置き場が無い | **採用** | `design.md` §5.6・§6.1・§7.3.2 | `GET/PATCH /api/settings` と「設定は DB に持つ」は**追加済み**。`settings` 表が §5.6 に無く、`system_prompt`（設定ファイルで持つ）の実体も未定義。表を起こして `system_prompt` をその値にする（データ置き場の変更に再起動が要る旨も文言へ） |
| C9 | クリップボードをサーバが読むのか画面が送るのか未定 | **採用** | `design.md` §6.1 `from-clipboard`・§16.2-10b | 「画面の `paste` で受けて `POST /api/assets/from-clipboard {data_url \| text}` に送る」に確定し、§6.1 に引数を書く（サーバ側は補助。`pyperclip` を必須にしない） |
| C10 | `duplicate_exclusion` を解除する口が無い／PK の順序 | **採用** | `design.md` §6.1・`duplicates-deletion-backup.md` §2.4 | 組を**解除する口**を足し、PK を `(min(a,b), max(a,b))` に正規化して保存・読み出しする（押し間違えが永続し、準重複が二度と出なくなるのを防ぐ） |
| C11 | `DELETE /api/folders/{id}` が下位を無警告で消す | **採用** | `design.md` §6.1・§5.3 | `?dry_run=true`（消える下位フォルダと枚数を返す）と `?confirm=<名前>` を要求する、または `folder.deleted_at` の論理削除にする。`duplicates-deletion-backup.md` §5.1 の「カタログ構造は必ず守る」と釣り合わせる |
| C12 | `folder_member.position` の並べ替え口が無い | **採用** | `design.md` §6.1・§5.3 | `PATCH /api/folders/{id}/members {asset_ids:[…]}`（順序を渡す）を足す。`count_cache` を数え直す口の方は **2 回目 D19**（当面は数える）が引き取る |
| C13 | 台帳・記録・プリセットの画面が無い | 対応済み | `frontend-design.md` §3 | **2 回目 B7** が `#/asset/<id>/recipe` と `#/recipes` を追加（反映済み） |
| C14 | 語釈の有無を画面が判定できない／`gloss/pending` の役割が曖昧 | **採用** | `design.md` §6.1・`frontend-design.md` §11「訳の取得」 | タグの応答に **`gloss` の有無**を含めると書き、`GET /api/tags/gloss/pending` は**一括訳（タグ画面）**用と役割を書き分ける（使わないなら削る）。※「呼ぶ画面が無い」は言い過ぎ（§2 参照） |
| C15 | `review_request` の上書きの意味論が未定義 | 対応済み | `design.md` §9.6・§5.6 | **2 回目 B6**（任意の `target_key` で `superseded`、旧まとまりは一覧と件数から外す）が引き取る |
| C16 | 64bit の `phash` / `seed` が SQLite の `INTEGER` に入らない | 対応済み | `design.md` §5.1 | TEXT（16 進 16 文字 / 10 進）に**反映済み**。`seed_sort` の要否は **2 回目 D1** が引き取る |
| C17 | `path_map` と `Asset.locations[]` の二重持ち | **採用** | `schemas/review-export.schema.json`・`design.md` §6.2 | `path_map` を削り、`include_paths=true` のときだけ `locations[]` にする（`primary` で代表が分かる）。残すなら「`locations` の `primary` を写したもの」と `description` に固定する |
| C18 | 契約が「全枚に理由」「`all_rejected` なら理由」を強制していない | **採用** | `schemas/review-export.schema.json` `Group` / `GroupItem` | `allOf`＋`if/then` で「`state='decided'` なら `items` 必須」「`decision='all_rejected'` なら `reason_code_id` 必須」「decided なら `items[].reason_code_id` 必須」を足す（**2 回目 C5・C8** と重なる部分はそちらで） |
| C19 | `decided_at` が `$defs/Timestamp` を使っていない | 対応済み | schema `Asset.decided_at`・`Group.decided_at` | `anyOf:[Timestamp, null]` に**反映済み** |
| C20 | `.cmd` でコンソールを消す方法と pystray / uvicorn の主スレッドが未定 | **採用** | `design.md` §4.1 | 「`.cmd`（ショートカットで最小化）＋ `uv run`」か「`.vbs` → `pythonw`」のどちらかに**確定**し、`tray.py` が主スレッド／uvicorn は `Server.serve()` を別スレッド／停止は `should_exit` 経由、を 3 行で書く（**2 回目 F1** が同じ場所を未検証として指す） |
| C21 | 「ポートが使えれば既存」で別アプリを誤認 | **採用** | `design.md` §4.1・§6.1 `/api/health` | `/api/health` に自分の識別子（`{"app":"image-reviewer","pid":…}`）を含め、**それで**判定する。別人なら「8790 は別のアプリが使っています」と出して終了する |

### D. 軽微

| id | 主題 | 状態 | 場所 | 何をするか／何で直ったか |
| --- | --- | --- | --- | --- |
| D1 | ボツ理由の初期値が 8 つ / 9 つ | 対応済み | `design.md` §16.1・§9.2 | 未修正のまま。**2 回目 D13** が同件（どちらが利用者の指定かは依頼者の確認） |
| D2 | 「1.25 倍の階段」が比になっていない | 対応済み | `frontend-design.md` §2.3 | 「比ではなく、大きさごとに決めた 5 段」に**反映済み** |
| D3 | 本文の行長「80 文字未満」の単位が不明 | **採用** | `frontend-design.md` §2.3 | 「**全角 40 字（半角 80 字）以内**」と単位を書く |
| D4 | seed は 18 桁 → 20 桁 | 対応済み | `frontend-design.md` §2.3 | 20 桁（`num` の幅も 20 桁）に**反映済み** |
| D5 | `frontend` の `/api/export/review.schema.json` というパスが存在しない | 対応済み | `design.md` §6.1 | 契約ファイルの配信口を §6.1 に**追加済み**（A3 / B8 の一環） |
| D6 | 「1024 サムネ 8 枚 ≒ 8MB」が過大 | 対応済み | `comparison.md` §2.1・§7 | 未修正のまま。**2 回目 E6** が実測（1 枚 **126 KB**、8 枚で約 1 MB）を与えた |
| D7 | `en_source` の `ollama` が将来用と書かれていない | **採用** | schema `Prompts.en_source`・`design.md` §16.2-15 | `description` に「`ollama` は**将来用の予約**。今の実装は出さない」を足す（A5 の残り） |
| D8 | タグの並びに `artist` の行き先が無い | 対応済み | `frontend-design.md` §11 | 未修正のまま。**2 回目 D11** が「キャラ → 作品 → **作家** → 一般 → その他」に直す |
| D9 | `postprocess` が `review_group.kind` に無い／`regenerated_from` がどの表にも無い | **採用** | `design.md` §5.4・schema `Group.kind`・`comparison.md` §2.3・§5 | `kind` に `postprocess` を足す（または `variation` に含めると明記）。`regenerated_from` をどの表で表すか決める（使わないなら削る） |
| D10 | `DELETE /api/assets/{id}/tags/{tag_id}` が `source` を取らない | **採用** | `design.md` §6.1 | `?source=manual` を受ける（`asset_tag` の PK は `(asset_id, tag_id, source)`） |
| D11 | 語釈が失敗したときの扱いが無い | **採用** | `design.md` §8.4 | 「失敗したら `tag_gloss` に行を作らない。画面に 1 行で出す。再試行は同じ導線」を足す（粒度・長さの上限も 1 行） |
| D12 | ボツの斜線が画像の内容次第で見えない | 対応済み | `frontend-design.md` §2.2・§4.1 | 未修正のまま。**2 回目 C12(1)** が明度も落とす／「ボツ」の語を置くを提案 |
| D13 | `--ink-muted` を `caption` / `small` に使う矛盾 | **採用** | `frontend-design.md` §8-3・§2.3・§11 | 「`caption` / `small` では `--ink` を使い `--ink-muted` は使わない」と明記するか、`--ink-muted` の用途から caption 相当を外す（語釈は **2 回目 C12(3)** が `body` / `--ink` にする） |
| D14 | 「余裕を 10 倍見ている」が実測（11.8 倍）と合わない | 対応済み | `design.md` §7.1 | 未修正のまま。**2 回目 D18**（C4 と一緒に書き直す）が同件 |
| D15 | `/check` と `/export` の関係が二重 | **採用** | `design.md` §6.1 | `/export` の応答に検査結果（`status` と `reasons`）を含め、`/check` は**プレビュー専用**と注記する（使わないなら削る） |

### E. 事実・前提の誤り（1 回目は E1〜E8）

| id | 主題 | 状態 | 場所 | 何をするか／何で直ったか |
| --- | --- | --- | --- | --- |
| E1 | 1 万枚の総量が 13.7 GB / 11.1 GB で食い違う | 対応済み | `design.md` §12.1・`duplicates-deletion-backup.md` §1.2 | **11.1 GB に一本化**して理由を明記済み。残る「34 秒」の表記は **2 回目 E1** が引き取る |
| E2 | §12.1 の 14 行中 8 行に出所が無い | 対応済み | `design.md` §12.1 | 「実測」「目標」「未計測」の列に**分離済み** |
| E3 | 鳩の巣原理の誤用（距離 ≤ 6 の保証が偽） | 対応済み | `duplicates-deletion-backup.md` §2.2 | **8bit × 8 本**（距離 ≤ 7）に**反映済み** |
| E4 | 「`PreviewAny.text` = 英訳」が実測と合わない | **却下**（核心が誤り） | `design.md` §7.3.1・`workflow-reproduction.md` §5 | 捕獲値は**翻訳**（`review-triage.md` §1.1 の実機確認。§2 参照）。「リストである」「最終プロンプトではない」の 2 点だけ採用し、**反映済み** |
| E5 | サムネイル実測が 256px のみ／目標のサイズが不明 | 対応済み | `design.md` §12.1 | 256px（実測から導出）と 1024px（未計測・未定）に**分離済み** |
| E6 | pHash 8ms/枚 に出所が無い（2 文書が互いを根拠にする） | 対応済み | `comparison.md` §7・`duplicates-deletion-backup.md` §6 | 「**未計測の見積り**」と明記し、出所を `comparison.md` §7 の 1 か所に**集約済み**（`review-triage.md` に記録が無いまま直っていた例） |
| E7 | 「この道具はネットワークを使わずに動く」が一般化しすぎ | 対応済み | `frontend-design.md` §2.3 | 未修正のまま。**2 回目 A1** が「書体の取得にネットワークを使わない」に限定する |
| E8 | どの API がいつ `record_json` を作るか未定義 | **採用** | `design.md` §6.1・`workflow-reproduction.md` §4.9 | `POST /api/assets/{id}/recipe` が記録を作り、**その時点で**環境の写し（ComfyUI 版・ノード版・GPU・dtype）を取って `env_snapshot` に入れる、と書く。ComfyUI が落ちているときの扱い（記録は作る／`status='approx'`／`env_snapshot` は null）も決める。※2 回目の E8 は**別件**（PNG のチャンク位置） |

### F. 未確認のまま危険な箇所

| id | 主題 | 状態 | 場所 | 何をするか／何で直ったか |
| --- | --- | --- | --- | --- |
| F1 | 保留領域を対象側のボリュームに置くときの命名・場所が未確認 | 対応済み | `duplicates-deletion-backup.md` §3.4・§7-6・`design.md` §16.2-4 | 「対象と同じボリュームに置く／別ボリュームに置いてはならない」は**明記済み**。実機確認は **2 回目 F4** が引き取る |
| F2 | 窓が切れている間に閉じていると起動時に完全削除 | 対応済み | `duplicates-deletion-backup.md` §3.4 | **2 回目 B2** が「起動時は消さず残り時間を引き継ぐ」に変更（反映中） |
| F3 | 取り消しとタイマーの排他が無い | 対応済み | `duplicates-deletion-backup.md` §3.4 | **2 回目 F6** が同件（1 つのロックで直列化） |
| F4 | `control_after_generate` の復元が未確認／食い違ったときの扱い | 対応済み | `workflow-reproduction.md` §4.7.2 | 「seed の欄は触らず `fixed` のまま」＋「結果の seed が違えば**同じ条件の結果として記録しない**」で扱いを**決定済み**。実機で 1 回確かめる手順は **2 回目 F2** |
| F5 | R4a の主経路がソース確認のみ（実ブラウザ未検証） | 対応済み | `metadata-findings.md` §6-7・`workflow-reproduction.md` §2-1 | 未検証として**記録済み**。利用者に出る「実機で確認済み」の文言は **2 回目 E4** が引き取る |
| F6 | `POST /api/userdata` の実書き込みが未実施／409 の文言 | 対応済み | `workflow-reproduction.md` §3.2・`metadata-findings.md` §6-4 | 「既にあると伝えて名前を変えさせる（409）」を**明記済み**。実書き込みの確認は未確認として残る（設計の判断は済み） |
| F7 | JPEG で読む EXIF の項目が未定義 | **採用** | `design.md` §7.1 | 読む項目を決めて 1 行で書く（例: 種別判定に `Make` / `Model` だけを使い、`UserComment` / XMP は見ない）。未検証であることも残し、**2 回目 C2** の JPEG の種別規則と整合させる |
| F8 | タガーの前処理と速度が未確認で P4 の完了条件に入っている | 対応済み | `design.md` §8.2・§14 P4 | 「前処理は実測で確定」「GPU の実測時間を計って記録する」に**反映済み** |
| F9 | P1 の完了条件が他プロジェクトの置き場に依存 | **採用** | `design.md` §14 P1 | 完了条件を「任意の画像フォルダ（合成でも実データでもよい）」に変えるか、`.store\anima-dev` は**一例**にすぎないと注記する（移されたら P1 を検証できない）。「1 万枚が手元に無い」は §14 P2 で対応済み |
| F10 | 捕獲成功率の見積りが無く、未捕獲が見えない | **採用** | `design.md` §7.3.1・`workflow-reproduction.md` §5 | `outputs` に `text` がある割合（実測 **146 / 419 件**）を書き、**訳を捕獲できなかった件数**を画面とジョブに出す設計を足す |
| F11 | 日次バックアップ 5 秒の根拠が無い（`asset_tag` 40 万行） | 対応済み | `design.md` §12.1・`duplicates-deletion-backup.md` §5.2 | **2 回目 F7** が同件（未計測として扱い、DB の大きさを実測する） |

### G. 依頼者への質問（1〜12）

| id | 主題 | 状態 | 場所 | 何をするか／何で直ったか |
| --- | --- | --- | --- | --- |
| G1 | 外部契約に要求を入れるか | 対応済み | schema `requests`・`design.md` §6.2・§16.2-9 | 「**入れる**」で**反映済み**（任意の `requests` 配列） |
| G2 | 取り消しで元パスに別ファイルがあったら | 対応済み | `duplicates-deletion-backup.md` §3.4 | 「上書きしない・**別名で戻すか尋ねる**」に**確定**（B12） |
| G3 | `changed_fraction` の閾値 / 増幅の正、`mean_abs` の前後 | 対応済み | `comparison.md` §4 | 定義を**固定済み**（B15） |
| G4 | 帯索引を 8 帯にするか閾値を 3 に下げるか | 対応済み | `duplicates-deletion-backup.md` §2.2 | **8bit × 8 本・閾値 6** に**確定** |
| G5 | 一括削除の件数とバイト数を誰が数えるか | 対応済み | `design.md` §6.1 | スコープを受ける口を**追加済み**（B13）。凍結は **2 回目 A6** |
| G6 | 1 万枚の目標をどう確かめるか | 対応済み | `design.md` §14 P2 | 「3,999 枚で実測し 1 万枚換算の見込みを示す」に**変更済み** |
| G7 | クリップボードはサーバ側か画面側か | **採用** | `design.md` §16.2-10b・§6.1 | C9 と同じ（画面の `paste` に確定する） |
| G8 | 設定をどこに保存し、どの API で編集するか | **採用** | `design.md` §5.6・§6.1・§7.3.2 | C8 と同じ（`settings` 表と `system_prompt` の置き場） |
| G9 | 「最近の削除」をどこに常設するか | 対応済み | `design.md` §4.1・§11・`frontend-design.md` §3・§4.6 | 画面 `#/pending-deletes` ＋ 上部バーの常設の入口 ＋ トレイ 3 項目に**反映済み** |
| G10 | L1 で品質語をどう扱うか／捕獲点を変えられるか | 対応済み | `workflow-reproduction.md` §4.2・§5 | `StringConcatenate.string_b` を捕獲値のリテラルに置き換え、品質語を残して `final_prompt` を**再構成**する形に確定済み |
| G11 | `--no-hash` の一覧を担う表と API を作るか、やめるか | **採用** | `design.md` §5.1・§6.1 | C7 と同じ |
| G12 | Host / Origin の検査を入れてよいか | 対応済み | `design.md` §6.3.1 | **入れた**（B11。認証は入れない） |

### H. 見落とし観点（指摘ではなく限界の申告）

| id | 主題 | 状態 | 場所 | 何をするか／何で直ったか |
| --- | --- | --- | --- | --- |
| H-1 | 実機で確かめられず、未確認の一覧が完全とは限らない | 対応済み（限界として記録） | `metadata-findings.md` §6・`review-triage.md` §4 | 未確認は §6 に集約済み。次は**実行して確かめてよい条件**で 3 回目を行う（`review-triage-fable.md` §5） |
| H-2 | 画面の見た目を描画していない | 対応済み（視覚の指摘は 2 回目が引き取り） | `frontend-design.md` §2.6・§12 | 描画での確認は未了。`cover` の欠陥は **2 回目 B5 / I10 / I11**、ボツの見え方は **2 回目 C12** が引き取る |
| H-3 | 書体の実物（`tabular-nums` が効くか）が未確認 | 対応済み | `frontend-design.md` §2.3 | **2 回目 F3・D10** が同件（`ch` 固定幅の代替が効かないので別書体へ） |
| H-4 | DB の運用（マイグレーションの初版・WAL・online backup・表を後から足す） | 対応済み | `design.md` §5.7・`duplicates-deletion-backup.md` §5.4 | 表の所在は §5.7 に**集約済み**。日次スナップショットの段と復元の口は **2 回目 C11** が引き取る |
| H-5 | 依存とライセンス（`onnxruntime-gpu` と CUDA、`pystray`、`UV_CACHE_DIR`） | 対応済み | `design.md` §4・README | 留保は記載済み。`pystray` の起動は **2 回目 F1**（C20 / C21 と同じ場所） |
| H-6 | 点検者自身が同じ系統のモデルで、相互参照と自己申告に甘い | 対応済み | `comparison.md` §7・`duplicates-deletion-backup.md` §6 | 相互参照は `comparison.md` §7 の 1 か所に**集約して解消**（2 回目 H も確認）。同種の誤りは E1 / E6 / 2 回目 E1 で拾った |
| H-7 | 末尾の「問題なしと判断した観点」（語彙・しきい値・API の形・割り算・例の適合） | 対応済み | 2 回目 H | 2 回目は**目視で追認**しただけで再検証していない。契約の検証は実装時に行う（`design.md` §14 テスト方針） |

---

## 2. 1 回目の点検が誤っていたもの

1. **E4（＝B3 の核心）「`outputs[].text` は翻訳ではなく VLM の説明文なので捕獲は使えない」→ 誤り。**
   実機で確かめた結果、捕獲値は**そのときの訳そのもの**（`review-triage.md` §1.1）。
   日本語原文が情景説明なので、その訳である英文も説明文の形になるだけである。
   実データでも再現できている（`prototype-notes.md` §3.3 の 2,478 文字、§3.4 の 392 文字と、
   `"(masterpiece, best quality, good quality, score_9), safe," + "\n\n" + 捕獲値` の再構成）。
   正しかったのは「**リスト**である」「**最終プロンプトではない**」の 2 点で、どちらも反映済み。
2. **C14「`GET /api/tags/gloss/pending` を呼ぶ画面が無い」→ 言い過ぎ。**
   `frontend-design.md` §3 には「タグ（`#/tags`。語の一覧、件数、訳の確認と修正）」が既にあり、
   未訳語の一括処理の受け皿になりうる。**画面が無い**のではなく、**どの画面がどの口を使うかが書かれていない**
   のが問題で、そちらは §1 の C14 として採用した。
3. **C8「DB 表も API も無い」→ 少なくとも API は疑わしい。**
   2 回目の点検は `design.md` §6.1 に `PATCH /api/settings {data_dir?}` がある前提で引用している（2 回目 C11）。
   1 回目時点の文書は残っていない（このワークスペースに git 履歴が無い）ので**断定しない**。
   残る指摘（`settings` 表と `system_prompt` の置き場）は C8 として採用した。
4. 参考: **D6 の見積り（1 枚 0.1〜0.3 MB）は誤りではない**（実測 126 KB はこの範囲）。
   ただし「8 枚で 1〜3 MB」という置き直しの上限は 3 倍甘い（実測は 8 枚で約 1 MB）。

---

## 3. id は 1 回目と 2 回目で別物を指す（2 回目が引き取ったもの）

同じ番号が両方の報告にあるが、**中身はほぼ別**である（A1〜A6・B1〜B9・C1〜C16・D1〜D20・E1〜E10・F1〜F9・G1〜G11）。
照合は**必ず本文で**行うこと。1 回目の指摘を 2 回目が引き取った組は次のとおり:

| 1 回目 | 内容 | 2 回目 |
| --- | --- | --- |
| A9・E7 | 接続先の記述・「ネットワークを使わずに動く」 | A1 |
| B5・B6 | 印の前提（リンク入力・複数保存ノード）／複数 `KSampler` | B9 |
| B11（残りの矛盾） | multipart・独自ヘッダ・ポート | C6（＝1 回目 C6 の `mirror_folders` とは**別件**） |
| B13（確認と実行のずれ） | `scope.kind='query'` を凍結する | A6 |
| B14（契約側） | `Provenance.clip` / `llm` | C8(5) |
| B16(b) | P1 の 60fps の測定条件 | C14 |
| C2 | `?format=ui` の振る舞い | I8 |
| C3（reopen の意味論） | 全枚に `clear` を追記して戻す | C5 |
| C4 | コメント `kind='url'` | D16 |
| C12（`count_cache`） | キャッシュをやめて数える | D19 |
| C13 | 台帳・記録・プリセットの画面 | B7 |
| C15 | 要求の上書きの意味論 | B6 |
| C16（`seed_sort` の残り） | 並べ替え用の列を削る | D1 |
| D1 | ボツ理由 8 つ / 9 つ | D13（＝1 回目 D13 の `--ink-muted` とは**別件**） |
| D6 | 8 枚で 8MB | E6 |
| D8 | タグの並びに「作家」 | D11（＝1 回目 D11 の語釈の失敗とは**別件**） |
| D12 | ボツの斜線 | C12(1) |
| D14 | 「余裕を 10 倍」 | D18 |
| F1 | 別ボリュームの保留領域 | F4 |
| F2 | 起動時に完全削除 | B2 |
| F3 | `undo` と `purge` の排他 | F6 |
| F4 | `control_after_generate` を実機で 1 回確かめる | F2 |
| F11 | 日次バックアップ 5 秒の根拠 | F7 |
| C20・C21 | 起動・トレイ・ポートの自己判定が未検証 | F1 |

---

## 4. 採用しなかったもの（却下）

- **E4**（核心が誤り。§2）。**これ以外に却下は無い**（残りはすべて採用か対応済み）。

---

## 5. 作業リスト（採用のみ。危険の高い順）

**採用 25 件・却下 1 件・対応済み 54 件**（H を 7 行に分けたので総数は 80 行）。
下から順に片付ければ、この仕分けは閉じる。「対応済み」の行は作業不要（2 回目の反映で閉じる）。

| 順 | id | 直す場所 | 何をするか |
| --- | --- | --- | --- |
| 1 | C20 | `design.md` §4.1 | 起動方式を「`.cmd`（最小化）」か「`.vbs` → `pythonw`」に確定し、`tray.py` 主スレッド／uvicorn 別スレッド／停止は `should_exit` を書く。**P0 の完了条件がここに乗っている** |
| 2 | C21 | `design.md` §4.1・§6.1 | `/api/health` に自分の識別子を含め、ポート占有時は「別のアプリが使っています」で終了する |
| 3 | C11 | `design.md` §6.1・§5.3 | `DELETE /api/folders/{id}` に `dry_run` と `confirm=<名前>` を要求する（または `folder.deleted_at` の論理削除）。**再生成できない分類を無警告で消さない** |
| 4 | C10 | `design.md` §6.1・`duplicates` §2.4 | `duplicate_exclusion` を解除する口を足し、PK を `(min,max)` に正規化する |
| 5 | C7・G11 | `design.md` §5.1・§6.1 | `POST /api/scan {dry_run:true}` の応答（メモリ上の一覧）を定義し、`--no-hash` はそれを出すだけにする |
| 6 | C8・G8 | `design.md` §5.6・§6.1・§7.3.2 | `settings` 表を起こし、`system_prompt` の実体をそこに置く（データ置き場の変更は再起動が要る旨も） |
| 7 | C9・G7 | `design.md` §6.1・§16.2-10b | クリップボードは画面の `paste` で受けて送る、に確定し、`from-clipboard` の引数を書く |
| 8 | E8 | `design.md` §6.1・`workflow` §4.9 | `POST /api/assets/{id}/recipe` が記録と `env_snapshot` を作る、と書き、ComfyUI が落ちているときの扱いを決める |
| 9 | C18 | `schemas/review-export.schema.json` | `allOf`＋`if/then` で「decided なら `items` と各 `reason_code_id` 必須」「`all_rejected` なら `reason_code_id` 必須」を強制する |
| 10 | C17 | schema・`design.md` §6.2 | `path_map` を削って `locations[]` に一本化する（残すなら「`primary` の写し」と固定） |
| 11 | F7 | `design.md` §7.1 | JPEG で読む EXIF の項目を決めて書く（種別判定は `Make`/`Model` だけ、など）。2 回目 C2 と整合 |
| 12 | C6 | `design.md` §6.1・§10.1 | `POST /api/scan` に `mirror_folders` を足し、既定と増分の扱いを書く |
| 13 | C5 | `design.md` §6.1・§10.3、`frontend` §11 | `sort` の語彙を `added\|seen\|name\|decided\|seed` に広げ、3 文書を揃える |
| 14 | C14 | `design.md` §6.1、`frontend` §11 | タグの応答に `gloss` の有無を含め、`gloss/pending` を一括訳（タグ画面）用と書き分ける |
| 15 | C12 | `design.md` §6.1 | `PATCH /api/folders/{id}/members {asset_ids:[…]}` を足す（`count_cache` は 2 回目 D19 の方向に従う） |
| 16 | C1 | `design.md` §13 | `<data>/exports/<recipe_id>/` を足し、`export\` との綴りを `workflow` と揃える。`src/image_reviewer/_gui` も足す |
| 17 | F10 | `design.md` §7.3.1・`workflow` §5 | `outputs` に `text` がある割合（146 / 419）を書き、捕獲できなかった件数を画面とジョブに出す |
| 18 | F9 | `design.md` §14 P1 | 完了条件を任意の画像フォルダに変えるか、`.store\anima-dev` は一例だと注記する |
| 19 | D9 | `design.md` §5.4・schema・`comparison` §2.3・§5 | `postprocess` を `kind` に足す（または `variation` に含めると明記）。`regenerated_from` の持ち方を決める |
| 20 | D15 | `design.md` §6.1 | `/export` の応答に検査結果を含め、`/check` はプレビュー専用と注記する（使わないなら削る） |
| 21 | D11 | `design.md` §8.4 | 語釈が失敗したら行を作らない・1 行で出す・再試行は同じ導線、を足す |
| 22 | D10 | `design.md` §6.1 | `DELETE /api/assets/{id}/tags/{tag_id}` に `?source=` を受ける |
| 23 | D7 | schema・`design.md` §16.2-15 | `ollama` は将来用の予約で今は出さない、と `description` に書く |
| 24 | D13 | `frontend` §8-3・§2.3・§11 | `caption` / `small` では `--ink` を使う（`--ink-muted` を使わない）と明記するか、用途から caption 相当を外す |
| 25 | D3 | `frontend` §2.3 | 行長を「全角 40 字（半角 80 字）以内」と単位つきで書く |

---

## 6. 未確認（推測で埋めなかったもの）

1. **B9 の `runs[].id` の意味。** 契約に説明が無く、`recipe_export.id`（書き出し）なのか
   `recipe_export_result.id`（結果）なのか決められない。`export_id` を別に足すべきかは、これが決まらないと判断できない。
2. **C8 の前提（1 回目時点で `PATCH /api/settings` があったか）。** ワークスペースに git 履歴が無いため確かめられない（§2-3）。
3. **H-1 の「未確認の一覧そのものが完全か」。** 検証の性質上、確かめる手段が無い（未確認のまま残す）。
4. 参考（数の食い違い、仕分けには影響しない）: 1 回目 C1 は「§5 に無い表は 6」と数えたが、現在の `design.md` §5.7 は 8 表を挙げる
   （`location_history` はその後 B2 の修正で足され、`preset` は §5.6 に元からあった）。
