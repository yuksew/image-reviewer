# 設計点検の報告（DeepSeek による独立点検・2 本目）

- 点検した版: 2026-10-15 02:03 時点の作業ツリー（`design.md` 01:52 / `frontend-design.md` 02:03 /
  `workflow-reproduction.md` 01:40 / `duplicates-deletion-backup.md` 01:36 / `comparison.md` 01:40 /
  `metadata-findings.md` 01:40 / `schemas/review-export.schema.json`（変更時刻は `docs` 外）/ 
  `review-export.example.json` 01:53 / `comfyui-reproduction-findings.md` 10-14 22:41）
- 点検の手段: `read` / `glob` / `grep` のみ。設計文書は一切変更していない（`docs/review-report-deepseek.md` の新規作成のみ）
- 数値の検算と JSON の突き合わせは実際に実行して確かめた（鳩の巣原理の反例、スキーマ定義と例の突き合わせ、割り算）
- 総合判定: **修正してから進む**。設計の骨格（内容を正体にする・出所を分ける・生成を実行しない）は維持できる。
  ただし §B3/B4（英訳の捕獲と L1）と §B2（走査時の UNIQUE 衝突）は**設計の一部を差し替えないと実装が止まる**。

前提として、`docs/review-brief.md` §3 の決定一覧を唯一の正とした。決定と食い違う記述は §A に置いた。

---

## A. 決定との矛盾（必ず直す）

| # | 場所 | 矛盾の内容 | なぜ困るか | 提案 |
| --- | --- | --- | --- | --- |
| A1 | `workflow-reproduction.md` §1（24-27 行）・§6-1（515-516 行） ↔ `design.md` §3（92 行）・§6.1（449, 456, 459 行）・§7.3.2（638 行）・§8.2（694 行） | 「このツールは ComfyUI に **`POST /prompt` を投げない**」と断定しているが、`design.md` は `/prompt` を**訳し直し・語釈・ComfyUI 経由のタガー**に使うと書いている | 「生成を実行しない」という決定は**画像生成の話**なのに、絶対表現にしてしまったため、実装者が §6-1 を字義どおり読むと `POST /api/assets/{id}/retranslate`・`POST /api/tags/gloss`・`POST /api/assets/tag {engine:'comfyui'}` を実装しない。R4b・R3・R7 が丸ごと落ちる | `workflow-reproduction.md` §1 と §6-1 を「**生成（画像を作る実行）の投入はしない。訳し直し・語釈・タガーのための `POST /prompt` は使う**」に書き換え、`design.md` §3 の図と一致させる。用語集（§17）にも 1 行足す |
| A2 | `design.md` §7.3.1（630 行） ↔ 同 §6.1（533 行）・§13（1037 行） | 同じ機能が `POST /api/integrations/comfyui/rescue-history` と `POST /api/comfyui/rescue-history` の 2 つのパスで書かれている。ルーター一覧（§13）にも `integrations` ルーターは無い | どちらを実装するか決まらない。起動時の救済走査（実装側の呼び出し）と手動 API の URL が食い違うと、テストが書けない | §7.3.1 を `/api/comfyui/rescue-history` に統一する（§6.1・§13 が正） |
| A3 | `design.md` §6.2（545, 560 行）・§9.4（793 行） ↔ 同 §6.1（423-537 行） | 外部参照の口（`GET /api/export/review.json`、`POST /api/export/...`）が**§6.1 の API 一覧に無い**。R5c の唯一の口なので、一覧から漏っている | 「API の一覧が正」として実装すると、外部契約を出す口が実装されない。§14 P5 の完了条件（他ツールが読める）が満たせない | §6.1 に `GET /api/export/review.json ?scope=&include_paths=&include_library=`、`POST /api/export/review`（手動書き出し）、`GET /api/export/review.schema.json`（契約ファイルの配信）を明記 |
| A4 | `duplicates-deletion-backup.md` §1.3（43-55 行） ↔ `design.md` §5.1（157-173 行） | 同じ `asset` 表の**改訂版**が別の列構成になっている。改訂版には `kind`（生成物/参考資料/写真）・`source_url`・`ref_tags` が**無く**、`source` の値集合も `'scan'\|'import'\|'comfyui-watch'` に変わっている（`design.md` は `'scan'\|'drop'\|'clipboard'\|'url'\|'watch'`）。どちらが正か書かれていない | 決定「種別は自動判定し人が直せる」「参考資料には出所 URL・種別・何の参考かを持たせる」が改訂版から落ちている。実装者が改訂版を採ると R1b の中核列が消える | `design.md` §5.1 の列を正とし、`duplicates` §1.3 は「`asset` の**同一性の部分**（`sha256` UNIQUE と `asset_location`）のみを改訂する」と明記して、`kind`/`source_url`/`ref_tags` は §5.1 を参照させる。`source` の enum も §5.1 に一本化 |
| A5 | `workflow-reproduction.md` §7 の 3-3（540 行）・`schemas/review-export.schema.json` `Prompts.en_source` ↔ `design.md` §16.1（1191 行）・§7.3.2（644-645 行） | 工程表に「再翻訳（`TextGenerate` 再実行 / **Ollama**）」と残っている。契約の enum にも `ollama` がある | 決定「Ollama は今回使わない」と食い違う。P3 の作業項目に存在しないエンジンが入っていると、実装者が使わない経路を作る | 3-3 の文言から Ollama を外す。enum の `ollama` は「将来用に予約（実装しない）」と schema の `description` に明記（現状は `en_source` の説明にその旨があるが、`Prompts.en_source` の enum 直近には無い） |
| A6 | `design.md` §12.1（943 行） ↔ `duplicates-deletion-backup.md` §6（361-362 行） | `--no-hash` の初回走査目標が **30 秒**（design）と **60 秒**（duplicates）。しかも duplicates は「`design.md` §12.1 の『初回走査 60 秒』は…90 秒に改める」と書くが、§12.1 に「初回走査 60 秒」という行は無い（あるのは「内容ハッシュ 60 秒」） | 受け入れ基準が 1 つに決まらない。P9「全目標値を満たす」が判定できない。引用が存在しない行を指しているので、どちらかを直しても他方が残る | `duplicates` §6 の引用を「§12.1 の『内容ハッシュ 60 秒』」に直し、`--no-hash` の目標を **30 秒**（design §12.1 が正）に一本化する |
| A7 | `duplicates-deletion-backup.md` §3.4（250-252 行） ↔ `design.md` §4.1（133 行）・`frontend-design.md` §3（242-253 行）・§2.4（131-148 行）・§4.5（325 行） | 「『最近の削除』（残り時間つき）は**目に入る場所に常設**する」「**トレイから開ける**ようにする」と決めているが、トレイのメニューは両文書とも「ブラウザで開く」「停止」の 2 つだけで、画面一覧 10 個にもレイアウト図にも常設領域が無い | 5 分の取り消しが「削除直後に出るトースト」だけになる。別の画面へ移る・再読込する・ウィンドウを閉じると取り消せない。決定「確認 1 回＋5 分取り消せる」の安全網が成立しない | 画面一覧に「最近の削除」（`#/pending-deletes`）を足し、上部バーに残り時間つきの常設の入口を置く。トレイのメニューに「最近の削除を開く」を足す（§4.1 のメニューを 3 項目に） |
| A8 | `frontend-design.md` §6（363 行） ↔ `duplicates-deletion-backup.md` §3.1（160 行）・§3.4（229-233 行） | 削除確認の文言が「3 枚を**完全に消します。8.4 MB 空きます**」。実際は同一ボリュームの保留領域へ `os.replace` するだけで、**5 分間は容量が空かない**（消えるのは `purge_at` を過ぎてから） | 利用者が「8.4 MB 空く」を信じて実行し、空き容量が変わらないので「消えていない」と誤解する。逆に「完全に消します」と読み、戻せることを軽く見る | 「3 枚を消す用意をします。あと 5 分なら取り消せます。**5 分後に 8.4 MB 空きます**」に直す。§6 の「削除の取り消し」も「3 枚を消す用意をしました。あと 4:58 は取り消せます」に揃える |
| A9 | `design.md` §3（99 行）・§4（117, 119 行） ↔ `review-brief.md` §3（54 行）・`design.md` §1 R1b（25 行） | 「**外へ出るのは ComfyUI だけ**」「httpx は ComfyUI の呼び出し（それ以外の接続先は無い）」と書くが、決定は「画像 URL を貼る」「クリップボードの中身が URL なら取り込みを試みる」なので、任意の外部ホストへ HTTP で出る | 「接続先は ComfyUI だけ」を実装の制約として読むと、URL 取り込みが実装されない。逆に実装すると §3・§4 の記述が嘘になる | §3・§4 を「**自分から出るのは ComfyUI と、利用者が明示的に指定した URL の取得だけ**。他ツールの API は呼ばない」に直す。あわせて URL 取得の制限（タイムアウト、最大バイト数、`Content-Type` とマジックナンバーの確認、リダイレクト回数の上限）を §5.1 に書く |
| A10 | `frontend-design.md` §11（459 行） ↔ `review-brief.md` §3（44 行）・`design.md` §4（122-134 行） | 「通知の音を使わない（**常駐していないため**）」とあるが、決定は「タスクトレイに常駐」。理由が決定と食い違う | 「常駐していない」を前提に読むと、トレイ常駐・ウィンドウを閉じても通知・A7 の取り消しの設計が崩れる | 理由を「決定により音は使わない。件数とタブのタイトルで示す」に直す |

---

## B. 重大な問題（設計を変える必要がある）

| # | 場所 | 問題 | なぜ困るか | 提案 |
| --- | --- | --- | --- | --- |
| B1 | `duplicates-deletion-backup.md` §2.2（117-119 行）・`comparison.md` §4（148 行）・`design.md` §6.1（515 行） | **鳩の巣原理の誤用。** 「64bit を 16bit × 4 の帯に分ければ、ハミング距離 ≤ 6 なら少なくとも 1 つの帯は完全一致する」は**偽**。実際に数え上げると、距離 1〜6 の帯ごとの差の配分 209 通りのうち **15 通り**（例: 帯ごとの差が `(2,2,1,1)`、`(1,1,2,2)`）で一致する帯が 1 つも無い。保証できるのは距離 ≤ **3** まで | 実装すると、距離 2〜6 の準重複が**静かに候補から漏れる**。「しきい値は実データで調整する」と言っても、候補に出ないものは調整できない。テスト（§3.4 相当）を書かないと永遠に気づかない | 帯を **8 帯 × 8bit** に変える（距離 ≤ 7 まで保証できる。64 が 8 で割り切れるので実装も単純）。または帯を 4 のまま閾値を 3 に下げ、SSIM と併用する。どちらでも「保証できる距離」を §2.2 に明記する |
| B2 | `duplicates-deletion-backup.md` §1.3（69 行）・§1.4（86-88 行） ↔ `design.md` §5.1（191 行） | `CREATE UNIQUE INDEX ux_loc_path ON asset_location(path)` があるのに、走査手順は「パスは同じで size/mtime が違う → ハッシュを計算し直し、**ハッシュが既存になければ asset を新規作成して asset_location を足す**」としている。同じパスの旧 `asset_location` 行が残ったままなので **UNIQUE 制約違反で INSERT が失敗する** | 走査の中核で必ず踏む。「中身が変わった」は日常（再保存・上書き生成）なので、初回の実データ走査で止まる。旧 asset の場所を消すのか `missing_at` を立てるのかが決まっていないため、判断も来歴もどちらが正か分からなくなる | §1.4 に一段足す: 「同じパスで中身が変わった場合、旧 `asset_location` を **削除**し（`deletion_log` に `reason='content_replaced'` を残す）、新 `asset` に同じパスを割り当てる」。あわせて `design.md` §5.1 と §15 リスク 4 に、この規則（パスは 1 つの内容にしか属さない）を明記する |
| B3 | `design.md` §7.3.1（621-628 行）・`workflow-reproduction.md` §5（477-478 行） ↔ `comfyui-reproduction-findings.md` §5（500-506 行）・`metadata-findings.md` §2（63 行） | 「`/history` の `PreviewAny.text` を捕まえて `en_text`（`en_source='comfyui_history'`）として保存する」が、実測と合わない。実測では `outputs[node].text` は **リスト**（`{"text": ["Assistant\n- The character's eyes are..."}`）で、内容は**翻訳プロンプトではなく VLM の説明文**。`outputs` に `text` があるのは 419 件中 146 件で、その全部が ja2en の訳とは限らない。さらに ja2en の経路は `TextGenerate` → **`StringConcatenate`（品質語を前置）**→ `CLIPTextEncode` なので、捕獲できるのは「最終プロンプト」でもない | R4b（英訳の表示）と R12（再現）の**唯一の前提**がここにある。翻訳でない文字列を「当時の訳」として保存・表示し、しかも L1 の入力にすると、**別の絵が出る**。実装後に気づくと P3・P7 の作り直しになる | 捕獲した値を `en_text` に入れる前に検証を入れる: (a) `text` がリストなら要素を連結、(b) その実行の `CLIPTextEncode` に到達する経路（`StringConcatenate` の出力）と一致するかを比べる、(c) 一致しなければ `en_source` を付けず「未捕獲」として画面に出す。**捕獲の第一候補を `PreviewAny` ではなく「`CLIPTextEncode` に入る直前の文字列」に変える**（`metadata-findings.md` §2 の経路が分かっているので可能）。§16.2 に「`PreviewAny` は訳以外も出す」を未確認事項として残さず、確定事項として書く |
| B4 | `workflow-reproduction.md` §4.2（172 行）・§4.7（288-289 行）・§4.3（189-197 行） | L1 の手順が「`TextGenerate` ノードを外し、`CLIPTextEncode.text` を捕獲した英文（リテラル）に置き換える」の 1 行だけで、**外したノードの消費者（`StringConcatenate`、`PreviewAny`、その他）の結線をどうするかが書かれていない**。再現キー（§4.3）は「リンクの結線」を**含む**ので、片側だけ書き換えると鍵が変わる | (a) 宙に浮いた `["9", 0]` の参照が残り、`loadApiJson` が解決できない、(b) 品質語の前置が落ちて絵が変わる、(c) 鍵が変わるので §4.3 の「結果の鍵が書き出しの鍵と一致すれば条件は同一」が使えなくなる。§4.7.1 の「印を付けてもキーは変わらない」という主張も、この不整合の前では無意味になる | §4.7 の手順 2 を具体化する: (a) `TextGenerate` と、その出力だけを消費するノード（`PreviewAny`）を**グラフから除去**、(b) `StringConcatenate.string_b`（訳の側）を**捕獲した英文のリテラル**に置き換えて、品質語の前置を**保ったまま**にする（`CLIPTextEncode.text` を直接置き換えない）、(c) 除去後のグラフで再現キーを**再計算**し、記録の鍵と一致することを書き出し前の検査（手順 4）に含める。§4.3 の除外リストに「印のための書き換えで生じる結線の差」も明記する |
| B5 | `workflow-reproduction.md` §4.7.1（312-324 行）・design の問い（`design.md` §19.4 の 12） | 印を `filename_prefix` に入れる根拠が「保存先を決めるだけの**書き込み専用の値**」「再現キーから除外してあるので鍵は変わらない」だが、`filename_prefix` が**リンク入力**（別ノードの出力が繋がっている）場合、リテラルに置き換えると**結線が消える**。§4.3 は結線を鍵に含めているので、この場合だけ鍵が変わる。この前提条件（リテラルであること）がどこにも書かれていない。複数の保存ノードがある場合にどこへ印を入れるかも未定義（§8-2 は「どこまで厳密にするか」を先送りしている） | 「印を付けても条件は同じ」と言い切れなくなる。条件判定・結果の紐付け・合否の記録が同じ土台の上に乗っているので、崩れると P7 全体が疑わしくなる | §4.7.1 に前提を明記: 「`filename_prefix` が**リテラルのときだけ**印を入れる。リンク入力のときは印を入れず、`matched_by='conditions'` の経路に落とす」。複数保存ノードの場合は「`type=='output'` を出す全保存ノードに同じ印を入れる」または「1 つに決めて他は触らない」を決め、**どちらを採るかを §8-2 から §4.7.1 に移して確定させる** |
| B6 | `workflow-reproduction.md` §4.7.2（343-345 行）・§4.7.1（315 行） | seed 違いの書き出しが「`KSampler`（複数あれば**全部**）の `inputs.seed` を書き換える」。印も `seed-<seed>` の 1 種類 | 二段構成（hires fix・2 パス）のワークフローでは、2 つ目の sampler の seed が本来と変わるので「seed だけ違う」が成り立たない（絵が別物になる）。また sampler が 2 つあると `seed-<seed>` が一意でなく、結果の紐付けが曖昧になる | 「書き換えるのは**第 1 の `KSampler`**（`SaveImage` から遡って最初に到達するもの）だけ」を既定にし、それ以外の sampler が同じ seed を持つ場合は「seed を揃えられない」と画面に出す。印は `seed-<seed>` ではなく `seed-<seed>-<sampler_node_id>` などにし、manifest にどちらの sampler かを持たせる |
| B7 | `design.md` §6.1（481 行） ↔ 同 §9.2（761-765 行）・§9.3（778 行）・`schemas/review-export.schema.json` `GroupItem`・`review-export.example.json`（32-54 行） | `POST /api/groups/{id}/decide {selected_asset_ids, reason_code_id, note?}` は理由を**1 つしか受けない**。しかし §9.2・§9.3 は「選ばれなかった枚には**その枚自身の理由**を付ける」と要求し、契約と例は **枚ごとに違う理由**（`rc.reject.body` / `rc.reject.character`）を持っている | この API のままでは、実装が「全員に同じ理由」を書くしかない。契約と例が表現している状態を API が作れないので、外部契約の例が**実在しえない出力**になる。あとで API を変えると契約の意味も変わる | `POST /api/groups/{id}/decide` の入力を `items:[{asset_id, verdict, reason_code_id?, note?}]` に変え、`selected_asset_ids` はその糖衣（または廃止）にする。`all_reject:true` のときだけ単一の `reason_code_id` を許す。「理由を飛ばして決定できない」ことを §14 のテスト方針に足す |
| B8 | `design.md` §16.2 の 9・10（1221-1223 行）・§6.2（541-558 行） ↔ 同 §9.6（832 行） | エージェントは `GET /api/review-requests/{id}` をポーリングして結果を得るのに、**そのレスポンスの形がどこにも定義されていない**。外部契約 `review-export.schema.json` には要求の節が無く、`scope.kind` も `all\|group\|folder` で `request` が無い。`groups[].source_ref` は自由文字列なので、自分の `request_id` と突き合わせる保証が無い。要求の状態（open/done/declined/superseded）・`wants` への応答（`annotations`）・AI の下書き（`ai_pick_asset_id`/`ai_note`）も契約に無い | 依頼者が「契約ファイルだけでエージェントが結果を知れるか」と問うている点そのもの。エージェントは自分の要求が**処理されたのか、断られたのか、まだ開いているのか**を契約から判断できず、結果を他の要求と取り違える。§9.5 の「AI の推しと人の判断を両方並べて出せる」も、外部からは読めない | (a) `GET /api/review-requests/{id}` の**レスポンスを JSON Schema として定義**し（`schemas/review-request.schema.json`）、状態・要求した `wants` への応答・AI の下書き・まとまりの判断を含める。(b) `review-export.schema.json` に `requests[]`（`id` / `state` / `group_id` / `ai_pick_asset_id` / `ai_note` / `decline_note`）を足すか、少なくとも `groups[].source_ref` を「`source='request'` のときは `request_id`」と**意味を固定**する。(c) `scope.kind` に `request` を足す。§16.2 の 9 を「入れない」から「別の契約で出す」に変更する |
| B9 | `schemas/review-export.schema.json` `Reproduction.runs`（278-301 行）↔ `workflow-reproduction.md` §4.9（409-435 行） | 契約の `runs[]` には `seed` / `attempt_id` / `marker` / `matched_by` / `export_id` / `prompt_id` / `result_hash` が**無い**（突き合わせて確認した）。DB 側の `recipe_export_result` は `export_id` と `prompt_id` と `matched_by` を持ち、`seed` は親の `recipe_export` にある | 「どの書き出し（どの seed・どの attempt）の結果か」が契約から分からない。再現の検証を外部ツール（または後日の自分）が集計できない。B8 と同じく、契約を読む側が DB を持っていない前提を裏切る | `runs[]` に `export_id`・`attempt_id`・`seed`・`marker`・`matched_by`・`result_hash` を足す。`seed` は `Recipe_export` から、`matched_by` は `recipe_export_result` から素直に写せる |
| B10 | `design.md` §14 テスト方針（1101 行）・§6.2（553 行） ↔ `review-export.example.json`（4 行） | 「書き出しは**決定性**（2 回出して同一）を確かめる」というテストが、ルートに `generated_at` があるため**必ず落ちる**。§6.2 の「キーも配列も安定した順に出す。他ツールがハッシュで差分を取れる」も同じ理由で成り立たない（毎回ハッシュが変わる） | テストが赤いまま P5 が閉じない。放置すると「決定性」の意味が曖昧なまま実装され、外部ツールが差分を取る前提（契約の説明文そのもの）が嘘になる | (a) テストを「`generated_at` を除いた部分が 2 回で同一」に変える、(b) ルートに `content_hash`（`generated_at` を除いた正規化 JSON の SHA-256）を足す、(c) §6.2 の文言を「`generated_at` を除いて決定的」に直す。契約の `description` も同じ表現に揃える |
| B11 | `design.md` §9.5（800 行）・§3（97-98 行）・`duplicates-deletion-backup.md` §3・`design.md` §6.1（518 行） | 認証なし・同一オリジン配信・**Host / Origin の検査なし**。`DELETE /api/locations {stage:3}` は利用者のファイルを動かす操作で、`POST /api/pending-deletes/{id}/undo`、`POST /api/assets/from-clipboard`、`POST /api/assets/{id}/extract`、`POST /api/groups/{id}/reopen`、`POST /api/comfyui/rescue-history` などは**本文なしで送れる POST** なので、他サイトの `fetch(..., {mode:'no-cors'})` から届く。さらに DNS リバインディングで `Host` を偽装できれば、同一オリジン扱いになり `GET /api/assets/{id}/file`（画像そのもの）や `DELETE /api/locations` まで読める/実行できる | 決定「認証は付けない」は守ったままでも成立する攻撃経路が残る。**利用者のファイルを失う経路**（段 3）に、利用者の操作を介さず到達しうる | 認証を足さずに、**Host と Origin を `127.0.0.1:8790` / `localhost:8790` に限定するミドルウェア**を入れる（起動時に払い出すトークンを URL に含める方式は「認証を付けない」に反するので、まず Host/Origin 検査で足りるかを見る）。`DELETE` に本文を使わない形（`POST /api/deletions`）へ変えるのも併せて検討する |
| B12 | `duplicates-deletion-backup.md` §3.4（239 行）・§3.3（222 行） | 取り消しは `os.replace` で元のパスへ戻すが、**元のパスに別のファイルが出来ている場合の扱いが無い**。Windows の `os.replace` は既存ファイルを**無警告で上書き**する | 利用者が 5 分の間に同じ名前のファイルを置いた（別のツールが書き出した、手で保存した）場合、取り消し操作で**そのファイルが消える**。「戻す」操作が破壊操作になる | 取り消しの直前に `os.path.exists(元のパス)` を確かめ、存在すれば (a) 中断して「元の場所に別のファイルがあります」と出す、(b) 別名（`<名前>.restored.png`）で戻す、のどちらかを決める。**既定は (a) 中断**を勧める。段 2 の復元にも同じ規則を適用する |
| B13 | `review-brief.md` §3（95 行）・`design.md` §16.1（1199 行）↔ 同 §6.1（518 行）・`duplicates-deletion-backup.md` §3.2（211-212 行） | 「一括削除の指定はフォルダ・まとまり単位／検索結果・絞り込み単位／手で選んで一括」と決めているのに、削除の口は `DELETE /api/locations {asset_id, path, stage}` だけ。**範囲（スコープ）を受け取る口が無い** | 検索結果 3,000 枚を消すとき、画面が 3,000 組の (asset_id, path) を組み立てて送ることになる。件数と合計バイト数をサーバ側で確定できず、確認画面の数字（§3.1 の 1 回の確認）と実行対象がずれる。§3.2-6 の「件数と合計バイト数を画面に出してから実行する」が担保できない | `POST /api/deletions {scope:{kind:'folder'\|'group'\|'query', ...}, stage, dry_run:true\|false}` を足す。`dry_run` が「消す対象の一覧・件数・合計バイト数」を返し、それを画面に出したあと同じ条件で実行する（`DELETE /api/locations` は単体操作用に残す） |
| B14 | `design.md` §5.2（210-226 行）・`workflow-reproduction.md` §4.1（151 行）・`schemas/review-export.schema.json` `Provenance`（138-160 行） | `asset_meta` に **CLIP / テキストエンコーダの列が無い**（`model` / `loras` / `vae` はある）。§4.1 は「CLIP・TE は ○（ファイル名）」を再現の必須項目として挙げ、findings も `CLIPLoader.clip_name`（`qwen_3_06b_base.safetensors`）が読めるとしている。契約の `Provenance` にも `clip` / `text_encoder` が無い | テキストエンコーダを差し替えると絵が別物になるのに、記録に入っていないので「完全（条件が同一）」と誤判定する。外部ツールも再現条件を揃えられない | `asset_meta` に `clip TEXT` / `clip2 TEXT`（`CLIPLoader` が 2 つあるワークフローがあるため）を足し、`Provenance` に `clip` / `text_encoder` を足す。§4.1 の表と矛盾しないことを確認する |
| B15 | `comparison.md` §2.3（80-83 行）↔ `workflow-reproduction.md` §4.8（379-380 行）・`schemas/review-export.schema.json`（289-292 行） | `changed_fraction` / `mean_abs` を「このツールの契約として固定する」と書くが、**定義が 2 文書で違う**。comparison は「変化した画素の割合」「絶対差を **3 倍に増幅**」、workflow は「**8 を超えた**画素の割合」。閾値 8 を増幅前/増幅後のどちらに当てるか、`mean_abs` が増幅前/後のどちらか、どこにも書いていない。契約側には `minimum`/`maximum` も定義の説明も無い | 同じ 2 枚を比べても実装者と文書で違う数値が出る。契約に出た値が後から比較できない（再現の検証・重複の確定の両方がこの数値に依存する）。閾値はコードに埋めないと決めているのに、指標の定義自体はコードに埋まる | 「生の差（0〜255）に対して `abs(diff) > 8` の画素の割合を `changed_fraction`（0〜1）、生の差の平均を `mean_abs`（0〜255）。ヒートマップの 3 倍増幅は**表示だけ**」と 1 か所（`comparison.md` §2.3）に確定して書き、他文書はそこを参照する。契約に `minimum`/`maximum` と `description` を足す |
| B16 | `design.md` §14（1073-1084 行） | **完了条件が確かめられない段がある。** (a) P2「走査 1 万枚が 90 秒以内」— 手元の実データは最大 3,999 枚（`metadata-findings.md` の実機環境）で 1 万枚が存在しない。(b) P1「グリッドが 60fps でスクロールする」— 測定条件（ブラウザ・機械・枚数）が無い。(c) P4「GPU で 0.5 秒/枚」— 本文書自身が未再計測と認めている。(d) P3「監視で新しい画像の訳が原文として入る」— ComfyUI での実生成が必要（自動テストで確かめられない）。(e) P9「全目標値を満たす」— (a)〜(d) を含む | 「前の段が緑になってから次へ進む」という工程の規律が働かない。緑にできない条件は、実装者が主観で「たぶん満たした」と判断するか、テストを書かずに進める | (a) は「合成画像 1 万枚を一時ディレクトリに作り、その走査時間で測る」or 「実データ 3,999 枚を 36 秒以内」に置き換える。(b) は「Chromium の Performance パネルで、1,024 枚を 5 秒スクロールして dropped frame が 1% 未満」のように**手順と合否の線**を書く。(c) は「未再計測なので、P4 の完了条件から外して実測後に目標を置く」。(d) は「手動で確かめる手順」として**手動確認**と明記し、自動テストと分ける |

---

## C. 中程度（実装前に決めたい）

| # | 場所 | 問題 | なぜ困るか | 提案 |
| --- | --- | --- | --- | --- |
| C1 | `design.md` §14 P7（1082 行）・§5.6（396-415 行） ↔ `workflow-reproduction.md` §4.9（391-446 行） | P7 が前提にする `recipe_record` / `recipe_export` / `recipe_export_result` の 3 表が、**本体のデータモデル（§5）に無い**。同じく `phash_band`（duplicates §2.2）・`deletion_log` / `duplicate_exclusion`（duplicates §3.1）も §5 に無い | 「§5 がデータモデルの正」として実装を始めると、後から表を足すことになり、マイグレーションと API の設計をやり直す | §5 に「専門文書が定義する表」の小節を足し、6 表の所在（どの文書のどの節が正か）と、本体での扱い（マイグレーションの順序）を列挙する。§13 のディレクトリ構成にも `<data>/exports/`、`<data>/pending-delete/`、`settings.json`、`src/image_reviewer/_gui` を足す |
| C2 | `design.md` §6.1（447, 505 行）・`workflow-reproduction.md` §4.7.1（327-328 行） | `GET /api/assets/{id}/graph?format=ui\|api` は、API 形式しか無い画像（実測 83%）に対して `format=ui` を返せない。変換を自前で実装しないと決めている（§7.4）ので、この引数は**実現できない値**を含む。振る舞い（404 / 409 / 400）が未定義 | 画面が「UI 形式で保存」を出して失敗する。エラー処理が場当たりになる | `?format=` を廃止し、`GET /api/assets/{id}/graph` は「ある形式を返す（`graph_kind` をヘッダか本文で示す）」に変える。`format=ui` を残すなら「UI 形式が無いときは 409 と理由」を §6.1 に明記 |
| C3 | `design.md` §6.1（475-477 行）・§5.4（297-309 行）・§5.4 の表（326-331 行） | `POST /api/reviews {subject_type:'group'}` と `POST /api/groups/{id}/decide` が**重複した口**。`decision.subject_type='group'` の `verdict`（`keep`/`reject`/`clear`）と、`group_decision`（`selected`/`not_selected`/`all_rejected`）と契約の `Group.decision`（`selected`/`all_rejected`）の対応が定義されていない。`POST /api/groups/{id}/reopen` の後に、既に書かれた枚ごとの判断をどうするかも未定義 | まとまりの判断が 2 経路で書けるので、台帳と現在値が食い違いうる。reopen の意味が決まらないと、§14 のテスト（「選んだ枚が keep、他が reject」）が書けない | `POST /api/reviews` は `subject_type='asset'` 専用にし、まとまりは `decide` / `reopen` だけにする。reopen は「新しい `decision` を `clear` として全枚に追記し、`review_state` を `unreviewed` に戻す」と定義する（台帳は消さない） |
| C4 | `design.md` §5.1（166 行） | コメントが `source_url TEXT, -- kind='url' のときの出所` だが、`kind` の値は `generated`/`reference`/`photo` で `url` は無い（正しくは `source='url'`） | 実装者がこのコメントを信じると、`kind` に `url` を入れる分岐を作る。決定の「種別は自動判定し人が直せる」と衝突する | `-- source='url' のときの出所（参考資料でも使う）` に直す |
| C5 | `design.md` §6.1（438 行）・§10.3（899 行）・`frontend-design.md` §11（444 行） | 並び順の語彙が 3 か所で違う。API は `sort=added\|seen\|name`、§10.3 は「追加順／撮影・生成順（`mtime`）／名前／判断日時」、frontend は「追加が新しい順。`疎` では **seed 順**も選べる」 | 「判断日時で並べる」「seed 順で並べる」が API に無い。画面に出す選択肢と API が合わない | API の `sort` を `added\|seen\|name\|decided\|seed` に広げ、§10.3 と frontend §11 をその語彙で書き直す |
| C6 | `design.md` §10.1（869 行）↔ 同 §6.1（428 行） | §10.1 は `POST /api/scan {mirror_folders:true}` を前提にするが、§6.1 の引数に `mirror_folders` が無い | ディスク階層の取り込み（決定「独自のフォルダ分け構造を持つ」の実装）を画面から指定できない | §6.1 の `POST /api/scan` に `mirror_folders:false` を足し、既定と「2 回目以降の走査で新しく増えた階層だけ足すか」を書く |
| C7 | `design.md` §5.1（204 行）・§12.1（943 行） | `--no-hash` は「`asset` を作らず**一覧の表示だけ**」とあるが、一覧（`GET /api/assets`）は `asset` 表から引く。`asset` を作らないなら、その一覧はどこから来るのか。表も API も無い | `--no-hash` の下見走査が実装できない、または実装者判断で `asset` を作ってしまい「判断はできない」という制約が消える | `POST /api/scan {dry_run:true}` の結果を**メモリ上（または一時ファイル）の一覧**として返す専用の応答を定義する。CLI の `--no-hash` はその結果を表に出すだけ、と決める |
| C8 | `frontend-design.md` §11（458 行）・`design.md` §7.3.2（641 行） | 設定画面が編集するもの（ComfyUI URL / 取込フォルダ / タガーのモデルと閾値 / **訳のエンジン** / **データ置き場** / バックアップ / テーマ / **`system_prompt`**）に対応する DB 表も API も無い。`settings.json` はバックアップ対象として一度出てくるだけ（duplicates §5.2） | 設定画面がどこへ書くのか決まらない。`system_prompt` を「コードに埋め込まない」と決めているのに、置き場が無い | `settings` 表（または `settings.json` を正とする定義＋`GET/PATCH /api/settings`）を §5.6 と §6.1 に足す。データ置き場の変更は「再起動が要る」ことを画面の文言に含める |
| C9 | `design.md` §6.1（431 行）・`frontend-design.md` §3（250 行）・§11 | `POST /api/assets/from-clipboard` は本文なしの POST で、**サーバが OS のクリップボードを読む**前提に見えるが、どこにも書かれていない。ブラウザの `paste` イベントで送る設計でもない | Windows のサーバプロセスが `OpenClipboard` に失敗する状況（他アプリが掴んでいる、セッション分離）で取り込みが失敗する。失敗時の文言も無い | 「クリップボードはブラウザの `paste` で受け取り、`POST /api/assets/from-clipboard {data_url \| text}` に送る」に決める（サーバ側は受け取った内容だけを見る）。§6.1 の引数を明記する |
| C10 | `duplicates-deletion-backup.md` §2.4（147 行）・§3.1（192-196 行） | `duplicate_exclusion` を**解除する口が無い**（「別物として確定」を押し間違えたら戻せない）。PK が `(a_id, b_id)` なので、順序を入れ替えた組は別行として扱われる | 誤操作が永続する。準重複の候補が二度と出なくなり、見落としに気づけない | `DELETE /api/duplicates/exclude {a_id, b_id}` を足す。PK は `(min(a,b), max(a,b))` に正規化して保存する（読み出し時も同じ正規化をする） |
| C11 | `design.md` §6.1（466 行）・§5.3（252 行） | `DELETE /api/folders/{id}` は `parent_id ... ON DELETE CASCADE` で下位フォルダと `folder_member` を**無警告で**消す。`duplicates-deletion-backup.md` §5.1 は「カタログ構造（`folder` / `folder_member`）は**必ず守る**（人が作った分類。再生成できない）」と位置づけている | 「再生成できない資産」を 1 回の操作で、確認も取り消しもなく失う。ファイル削除には 3 段階と 5 分の窓を置いた設計と釣り合わない | `DELETE /api/folders/{id}` に `?dry_run=true`（消える下位フォルダと枚数を返す）と `?confirm=名前` を要求し、応答に消えた件数を残す。または削除も「論理削除（`folder.deleted_at`）」にする |
| C12 | `design.md` §5.3（267 行）・§10.2（893 行） | `folder_member.position` を持つが並べ替えの口が無い（`PATCH /api/folders/{id}` はフォルダ自身の `position` だけ）。スマートフォルダの `count_cache` を強制的に数え直す口も無い | 手で並べ替えられない。件数のキャッシュが狂ったときに直す手段が無い（走査や判断をすれば無効化されるが、それが起きない原因のとき詰む） | `PATCH /api/folders/{id}/members {asset_ids:[...]}`（順序を渡す）と `POST /api/folders/{id}/recount` を足す |
| C13 | `frontend-design.md` §3（242-253 行）・`design.md` §11（910-921 行）・§6.1（477, 505 行） | `GET /api/reviews`（台帳の履歴）、`GET /api/recipes`（記録の一覧）、プリセットの一覧を表示する画面が、画面一覧 10 個のどこにも無い。§9.5 の「AI の推しと人の判断を両方並べて出せる」の置き場も無い | 実装時に「とりあえず詳細画面の下に出す」ことになり、§9.5 の要求（両方を並べる）が満たされたか誰も確かめられない | 画面一覧に「来歴と判断の記録」（`#/asset/<id>?tab=history` でも独立画面でもよい）を足し、台帳・AI の推し・再現の記録・プリセットをそこに集める |
| C14 | `design.md` §6.1（460 行）・`frontend-design.md` §11（451 行） | `GET /api/tags/gloss/pending` を呼ぶ画面が無い（画面は語ごとに「訳す」）。逆に、詳細の応答が「この語に語釈があるか」を返す設計が無い | 「訳す」を出す条件（語釈の有無）が画面で判定できない。未訳語の一括処理を作るのかどうかも曖昧なまま | §11 の「訳の取得」に「詳細 API のタグに `gloss` の有無を含める」と書き、`/api/tags/gloss/pending` は**一括訳の画面**（タグ画面）のためのものと役割を書き分ける。使わないなら削る |
| C15 | `design.md` §9.6（834 行）・§5.6（375 行） | `review_request` の上書きの意味論が未定義。画像を差し替えると `group_item` の集合が変わるが、(a) 新しい `review_group` を作るのか (b) 既存の `group_item` を差し替えるのか、(c) 旧要求の `group` とそこに既に入った判断をどうするのか、が書かれていない。`superseded_by` には FK も索引も無く、旧要求を引く口も無い。`GET /api/review-requests/{id}` が superseded な要求に対して何を返すかも未定義 | P6 の完了条件（「同じ対象なら上書きされる」）が検証できない。旧 group が `open` のまま残ると、要求の一覧と「未対応の件数」（タブのタイトル）が狂う | (a) と決めて「上書きは**新しい group を作り**、旧 group は `state='decided'` にせず `superseded` として一覧から外す。旧要求の `GET` は `state='superseded'` と `superseded_by` を返し、判断は返さない」と §9.6 に書く。（b）を採るなら `group_item` の差分更新と、外れた枚の判断の扱いを決める |
| C16 | `design.md` §5.1（162-163 行）・§5.2（232-233 行）・`schemas/review-export.schema.json`（148 行）・`comfyui-reproduction-findings.md`（404 行） | `phash` / `dhash` は 64bit、`seed` は ComfyUI の `INPUT_TYPES` で `max = 0xffffffffffffffff`。SQLite の `INTEGER` は**符号付き 64bit** なので、最上位ビットが立つ値や 2^63 以上の seed で `OverflowError: Python int too large to convert to SQLite INTEGER` になる | 走査のたびに一定確率で落ちる（pHash は約 50%）。seed は randomize で 2^63 以上が普通に出る。エラーが出る場所が「たまに落ちる」なので原因究明に時間を食う | `phash` / `dhash` は `BLOB`（8 バイト、ビッグエンディアン）で持つ。`seed` は「符号付きに変換して保存し、読み出しで戻す」または `TEXT`（10 進文字列）にする。契約の `seed` も「0〜2^64-1 の整数」と `description` に明記する |
| C17 | `schemas/review-export.schema.json`（57-61 行, 232-236 行）・`design.md` §6.2（558 行） | 同じ事実（実在するパス）を `path_map`（asset → 単一パス）と `Asset.locations[]`（複数、`primary` と `missing` 付き）の 2 通りで持つ。`path_map` には「どれが代表か」が無く、`locations` と食い違いうる | どちらを読むかで他ツールの挙動が変わる。`include_paths=true` のとき両方が入るので、外部ツールが「代表の 1 つ」を選べない | `path_map` を削り、`include_paths=true` のときだけ `locations[]` を入れる（`primary` で代表が分かる）。残すなら `path_map` は「`locations` の `primary` を写したもの」と契約の `description` に固定する |
| C18 | `schemas/review-export.schema.json` `Group`（317-357 行） | `Group` の必須は `id` / `kind` / `policy` / `state` だけで、`items`・`selected_asset_ids`・`decision` は任意。`reason_code_id` の「`all_rejected` のときは必ず入る」は `description` にあるだけで **JSON Schema で強制されていない**。`GroupItem.reason_code_id` も任意（§9.2 は全枚に理由を必須としている） | 契約を検証しても「全枚に理由がある」「all_rejected なら理由がある」という設計の不変条件を確かめられない。§14 のテスト方針（全員に理由が付く）が契約側で守られない | `allOf` + `if/then` で「`state='decided'` なら `items` 必須」「`decision='all_rejected'` なら `reason_code_id` 必須」「`items[].reason_code_id` は `state='decided'` のとき必須」を足す（draft 2020-12 で書ける）。§5.4 の不変条件を同じ形で DB 側にも書く |
| C19 | `schemas/review-export.schema.json`（212 行, 353-354 行） | `Asset.decided_at` と `Group.decided_at` は `{"type":["string","null"]}` で、`$defs/Timestamp`（RFC 3339 のパターン）を使っていない。同じ文書の中で時刻の型が 2 通りある | 外部ツールが `decided_at` をパースできるか分からない（形式が保証されない）。「決定的に並ぶ」ためには形式の固定が要る | 両方を `$defs/Timestamp` の `oneOf`（`Timestamp` か `null`）にする。`Timestamp` を `["string","null"]` 対応にするか、`oneOf:[{"$ref":"#/$defs/Timestamp"},{"type":"null"}]` を使う |
| C20 | `design.md` §4.1（130-132 行） | `.cmd` のショートカットで「**黒いコンソール画面を出さない**（`pythonw` 相当で起動）」は両立しにくい（`.cmd` はコンソールを伴う。`pythonw` 相当にするなら `.vbs` かショートカットの「最小化」で、完全には消えない）。pystray（メッセージループ）と uvicorn（HTTP ループ）のどちらを主スレッドで動かすか、トレイの「停止」でどう止めるかも書かれていない | P0 の完了条件（ショートカットのダブルクリックでブラウザが開き、トレイにアイコンが出る）で詰まる。コンソールが出ると「黒い画面を出さない」が未達のまま先へ進むことになる | 起動手順を「`.cmd` → `uv run image-reviewer serve`（コンソールは最小化で起動）」または「`.vbs` から `pythonw` で起動」のどちらかに確定する。`tray.py` が主スレッド、uvicorn は `Server.serve()` を別スレッドで、停止は `should_exit` 経由、と §4.1 に 3 行で書く |
| C21 | `design.md` §4.1（132 行） | 「ポートが使えれば既存と見なす」— 別のアプリが 8790 を使っている場合、そのアプリを「自分」と誤認してブラウザで開く | 起動できないのに「起動済み」と表示され、利用者は何が起きているか分からない | `/api/health` の応答に自分の識別子（`{"app":"image-reviewer","pid":...}`）を含め、**それで判定**する。`GET /api/health` が別人なら「8790 は別のアプリが使っています」と出して終了する |

---

## D. 軽微（実装中でよい）

| # | 場所 | 問題 | 提案 |
| --- | --- | --- | --- |
| D1 | `design.md` §16.1（1169 行）↔ §9.2（754-759 行） | 「ボツの理由の初期値は §9.2（利用者が選んだ **8 つ**）」だが、§9.2 のボツ理由は **9 つ**（人数・人物／構図・アングル／意図・場面／雰囲気・絵柄／服装・小物／キャラ／破綻／表情／その他） | 数を「9 つ」に直すか、§9.2 から 1 つ削る（どちらが利用者の指定かは依頼者に確認） |
| D2 | `frontend-design.md` §2.3（111-121 行） | 見出しが「**1.25 倍の階段**」だが、表の値は 11 / 12 / 13 / 15 / 20 で比は 1.09・1.08・1.15・1.33。公比になっていない | 「公比 1.25 の階段」に実際に合わせる（11 / 14 / 17 / 21 / 27 など）か、見出しを「段階的に大きくする（比は一定でない）」に直す |
| D3 | `frontend-design.md` §2.3（122 行） | 「本文の行長は **80 文字未満**」— 半角 80 字（全角 40 字）なのか全角 80 字なのか不明。全角 80 字は日本語の本文として広すぎ、§2.5 の「絵以外を静かにする」とも合わない | 「全角 40 字（半角 80 字）以内」と単位を書く |
| D4 | `frontend-design.md` §2.3（109 行） | 「seed は **18 桁**あり」— ComfyUI の seed の上限は `0xffffffffffffffff` = 20 桁（`comfyui-reproduction-findings.md` 404 行で確認済み） | 20 桁に直し、「20 桁でも桁が揃う幅」を `num` の指定に反映する |
| D5 | `frontend-design.md` §10（431 行） | `/api/export/review.schema.json` という API パスは存在しない（実体は `schemas/review-export.schema.json`）。§6.1 にも配信の口が無い | A3 の提案どおり `GET /api/export/review.schema.json` を §6.1 に足すか、frontend の記述をファイルパスに直す |
| D6 | `comparison.md` §7（209 行） | 「1024 サムネ 8 枚 ≒ 8MB」— WebP quality 82・長辺 1024 なら 1 枚 0.1〜0.3MB 程度。10 倍以上過大 | 「8 枚で 1〜3MB」程度に直す（目標値の根拠として使うなら、実測するか「見込み」と注記する） |
| D7 | `schemas/review-export.schema.json`（175 行） | `en_source` に `ollama` が残る（決定で使わない） | `description` に「`ollama` は将来用の予約。今の実装は出さない」と書く（A5 と同じ） |
| D8 | `frontend-design.md` §11（450 行）・`design.md` §5.2（232 行） | タグの並びが「キャラ → 作品 → 一般 → その他」で、Danbooru の `artist`（1）の行き先が無い。`category` の説明にも 2 が無い（欠番） | 「キャラ → 作品 → 作家 → 一般 → その他」にし、`category=2` は「未使用（Danbooru の欠番）」と注記する |
| D9 | `comparison.md` §5（167 行）・§2.3（70 行） | まとまりの種類に `postprocess` があるが `review_group.kind`（`design.md` §5.4・契約 `Group.kind`）に無い。`regenerated_from` という関係もどの表にも無い | `kind` に `postprocess` を足す（または `variation` に含めると明記）。`regenerated_from` は `decision`/`review_group` のどちらで表すかを決めて書き換える（使わないなら削る） |
| D10 | `design.md` §6.1（455 行） | `DELETE /api/assets/{id}/tags/{tag_id}` は `source` を取らないので、同じ語の PNG 由来と手入力の両方が消える（`asset_tag` の PK は `(asset_id, tag_id, source)`） | `?source=manual` を受けるようにする |
| D11 | `design.md` §5.6（407-414 行）・`frontend-design.md` §11（451 行） | 語釈の取得は語ごとの「訳す」だが、訳の粒度・長さの上限・失敗時の扱い（`tag_gloss` に行を作らない）が書かれていない | §8.4 に「失敗したら行を作らない。画面に 1 行で出す。再試行は同じ導線」を足す |
| D12 | `frontend-design.md` §4.1（278 行）・§2.2（87 行） | ボツの印は「画像の彩度 35% ＋ `--drop` の 1px 斜線」。斜線は**画像の内容の上**に描くので、暗い絵・赤い絵では `#93382C` がほぼ見えない（コントラストが画像依存で保証できない） | 斜線の下に 1px の地色（半透明の `--paper`）を敷く、または斜線の太さを 2px にする。「色だけで意味を伝えない」という §2.2 の方針は**楔と斜線の形の差**で保っているので、色の可視性は別途担保が要る |
| D13 | `frontend-design.md` §8-3（392 行）・§2.2（67 行）・§2.3（115-116 行） | 「`--ink-muted` は `body` 以上の大きさでだけ使う」と決めているが、`caption`（11px）と `small`（12px）の用途に「件数」「状態の語」「来歴の表」があり、`--ink-muted` の用途にも「数値の単位、注記」がある。対応が示されていない | 「`caption` / `small` では `--ink` を使い、`--ink-muted` は使わない」と明記するか、`--ink-muted` の用途から `caption` 相当を外す |
| D14 | `design.md` §7.1（582 行） | 「上限 256 KiB で十分（余裕を 10 倍見ている）」— 実測の最大 22,178 B に対して 11.8 倍 | 「余裕を 10 倍以上見ている」に直す（誤りではないが、数値の対応が合っていない） |
| D15 | `design.md` §6.1（533, 500 行）・`workflow-reproduction.md` §4.7（300 行） | 「検査」（`/check`）と「書き出し」（`/export`）の関係が二重。`/check` 単体を呼ぶ画面が無い | `/export` の応答に検査結果（`status` と `reasons`）を含め、`/check` はプレビュー専用と §6.1 に注記する。使わないなら削る |

---

## E. 事実・前提の誤り

| # | 場所 | 内容 |
| --- | --- | --- |
| E1 | `duplicates-deletion-backup.md` §1.2（29-31 行）・`design.md` §12.1（936, 941 行）・`README.md`（71-73 行） | 1 万枚の総量が **13.7 GB**（1.37 MB/枚、300 枚 410 MB から）と **11.1 GB**（`ComfyUI\output` 1,028 枚 1.14 GB = 1.11 MB/枚 から）で **24% 食い違う**。`design.md` §12.1 は「実測は `metadata-findings.md` §7 と `duplicates-deletion-backup.md` §1.2 にある（`ComfyUI\output` の 1,028 枚で計測）」と書くが、ハッシュの実測は **300 枚**で、どの 300 枚かがどこにも書かれていない。34 秒という目標の根拠が再現できない。目標値（60 秒）はどちらでも満たすので実害は小さいが、**「実測に基づく」と称する表の土台が揃っていない**。300 枚の内訳（どのディレクトリか）を書くか、1,028 枚の実測に統一する |
| E2 | `design.md` §12.1（935-954 行） | 「**この表の数値は実測に基づく。根拠のない置き数値は置かない**」と書くが、14 行のうち **8 行に実測の出所が無い**: グリッド初回表示 300ms／追加ページ 100ms／一覧 API p95 20ms／詳細表示 200ms／比較 8 枚 400ms／タグ付け 0.5 秒/枚／pHash 全件 2 分／日次バックアップ 5 秒／判断の記録 100ms（うちタグ付けだけは §16.2-8 で「未再計測」と注記されている）。残りは注記すら無い | 
| E3 | `duplicates-deletion-backup.md` §2.2（118 行） | 鳩の巣原理の誤用（B1）。「距離 ≤ 6 なら少なくとも 1 つの帯は完全一致する」は偽で、保証は距離 ≤ 3 まで |
| E4 | `design.md` §7.3.1（621, 627 行）・`workflow-reproduction.md` §5（477 行） | 「`PreviewAny.text` = 英訳」は実測と合わない（B3）。実測例は VLM の説明文で、値はリスト |
| E5 | `design.md` §12.1（945 行）・`metadata-findings.md` §7（220 行） | サムネイル目標の計算は合っている（36 枚/秒 → 10,000/36 = 277.8 秒 = 4.63 分）。ただし、**並列度 1 で目標（6 分）を満たす**（必要なのは 10,000/360 = 27.8 枚/秒）。§12.2 はサムネイルを 2 サイズ（256 / 1024）作ると書くが、実測は **256px だけ**。1024px は 1 枚あたり数倍重く、目標がどちらのサイズを指すのか書かれていない。「並列でさらに短い」も、Pillow の WebP エンコードが線形に伸びる保証は無い（未計測） |
| E6 | `comparison.md` §7（213 行）・`duplicates-deletion-backup.md` §6（358 行）・§5.1（289 行）・`design.md` §12.1（952 行） | pHash 8ms/枚（1 万枚 80 秒）は**どこにも実測が無い**。`comparison.md` と `duplicates` が互いを根拠として参照しているだけ。初回走査の目標（90 秒）は pHash を**入れていない**（§12.2 で別ジョブに回している）ので矛盾はしないが、「実測に基づく」の主張には反する |
| E7 | `frontend-design.md` §2.3（96-97 行） | 「この道具はネットワークを使わずに動く」（書体の同梱の理由として）は、URL 取り込み（決定）と食い違う。書体の話としては正しいが、文が一般化しすぎている |
| E8 | `metadata-findings.md` §2（69 行）・`workflow-reproduction.md` §4.1（156 行） | `TextGenerate` のパラメータ一覧に `temperature` / `top_k` / …を挙げるが、`asset_meta`（§5.2）にこれらの列は無く、`recipe_record.record_json` に入る想定。**どの API がいつ `record_json` を作るのか**（`POST /api/assets/{id}/recipe` か `/check` か）が書かれていない。§4.4 が「L2 では記録に `mtp`/`thinking`/dtype/GPU を含める」と要求しているので、記録の作成時点で ComfyUI を叩く必要がある |

---

## F. 未確認のまま危険な箇所

| # | 場所 | 内容 |
| --- | --- | --- |
| F1 | `duplicates-deletion-backup.md` §3.2-8（215 行）・§3.4（231-235 行）・§7-6（377-378 行） | 保留領域を「対象側のボリューム」に置く場合の**命名と場所が未確認**。既定（`<data>/pending-delete/`）のまま `os.replace` すると、別ボリュームで `OSError(EXDEV)` になる。逆に「失敗したらコピーしてから消す」に落とすと、**移動中に落ちたときにデータを失う**（本文書自身が禁じている）。§3.2-1 の「登録ルート外は触らない」とも衝突する（対象側のボリュームに勝手にディレクトリを作る）。実装時にここを間違えると、遡及できない経路になる |
| F2 | `duplicates-deletion-backup.md` §3.4（245-247 行） | 「窓が切れている間にアプリを閉じていたら、起動時にその場で**完全削除**する」。A7（常設の取り消し場所が無い）と組み合わさると、実質「確認 1 回＋戻せない削除」になる。通知は起動後に 1 回だけで、`deletion_log` を見に行かないと何が消えたか分からない。**利用者のファイルが戻らない経路**として最も現実的 |
| F3 | `duplicates-deletion-backup.md` §3.4（239-241 行） | 取り消しとタイマーの競合。同じ行を undo と purge が同時に読んだ場合の排他（トランザクション、ファイルロック）が無い。undo が先に `os.replace` してから purge が走ると、消す対象が無いので実害は小さいが、purge が先だと undo が `FileNotFoundError` で落ち、画面は「取り消せます」と言い続ける（`restored_at` を立てる前に失敗する） |
| F4 | `workflow-reproduction.md` §4.7.2（347-352 行）・`design.md` §16.2-7（1218-1219 行） | 「フロントエンドで読み込んだとき `control_after_generate` がどう復元されるか未確認」。もし `randomize` になると、書いた seed が実行時に変わり、**seed 違いの書き出しが全部無効**になる。§4.7.2 の対策（利用者への注意書き＋結果の seed 照合）は妥当だが、「照合で見つけたらどうするか」（無効として印を付けるだけか、再書き出しを促すか）が無い |
| F5 | `comfyui-reproduction-findings.md` 未検証項目（831 行）・`metadata-findings.md` §6-7（203 行） | R4a の主経路（API 形式 JSON の D&D、Open ボタン）は**ソースコードの確認のみ**で、実ブラウザでの目視は未実施。§14 P3 の完了条件（UI 実行画像のワークフローを開ける）はこの未検証の上に載っている |
| F6 | `metadata-findings.md` §6-4（200 行） | `POST /api/userdata/{file}` への**実際の書き込みは未実施**。`graph.install`（design §7.4）の主経路。fail-soft の設計はあるが、「409 のときに利用者へ何と出すか」は未定（§3.2 に「名前を変えさせる」とだけある） |
| F7 | `design.md` §7.1（586-587 行）・`metadata-findings.md` §6-5（201 行） | JPEG のメタデータは未検証（「グラフは残らない見込み」）。JPEG の EXIF に生成条件がある場合の扱い（読むのか無視するのか）が無い。§7.1 は「取れた範囲だけ出し、グラフは取得できませんと出す」と書くが、**EXIF のどこを見るか**が未定義で、実装者ごとに違う結果になる |
| F8 | `design.md` §8.2（699-704 行） | タガーの前処理（`BGR`/`RGB`、pad、`[0,255]`）と速度（0.5 秒/枚）が未確認。留保は書かれているが、**P4 の完了条件にこれらの数値が入っている**（B16-(c)） |
| F9 | `README.md`（100-101 行）・`design.md` §14 P1（1076 行）・`metadata-findings.md` §5（188-189 行） | P1 の完了条件が「`C:\work\illust-authoring\.store\anima-dev` を走査して一覧が出る」。これは**他プロジェクトのデータ置き場**で、§18 と `metadata-findings.md` §5 は「他ツールのストアは使わない」と書いている。README は「ただの画像フォルダとして」と補っているが、**受け入れ基準が外部の都合に依存する**（移されたら P1 を検証できない）。加えて §14 P2 の「1 万枚」は手元に無い（B16-(a)） |
| F10 | `design.md` §7.3.1（621-628 行）・`comfyui-reproduction-findings.md`（503-505 行） | `outputs[node].text` が**リスト**であること、`PreviewAny` が訳以外も出すこと（B3）を前提にしていない実装になりやすい。`outputs` に `text` があるのは 419 件中 146 件で、「訳が捕まらなかった」場合の件数が実測されていない。捕獲成功率の見積もりが無いまま P3 の完了条件（監視中に生成した画像の英訳が原文として入る）を置いている |
| F11 | `design.md` §12.1（953 行）・`duplicates-deletion-backup.md` §5.2（295-299 行） | 日次バックアップ「5 秒以内」の根拠は online backup API だけ。`asset_tag` は 1 万枚 × 40 語 = 40 万行規模になり、DB は「数 MB〜数十 MB」では済まない可能性がある。`PRAGMA wal_checkpoint(TRUNCATE)` を終了時と日次で行う設計と、稼働中の online backup の同時実行も未検証 |

---

## G. 依頼者への質問（判断が要るもの）

1. **外部契約に要求（`review_request`）を入れるか。** 入れない場合、エージェントは契約ファイルだけで「自分の要求が処理されたか、断られたか」を知れない（B8）。`GET /api/review-requests/{id}` の応答を別スキーマで定義する案は許容できるか。
2. **段 3 の取り消しで、元のパスに別のファイルがあったらどうするか**（中断／別名で戻す／上書き）。既定は「中断」を勧める（B12）。
3. **`changed_fraction` の閾値（8）と増幅（×3）の正はどちらか。** `mean_abs` は増幅前か後か（B15）。
4. **帯索引は、閾値 6 を保ったまま 8 帯にするか、閾値を 3 に下げるか**（B1）。
5. **一括削除の確認（件数と合計バイト数）は誰が数えるか。** サーバにスコープを受け取る口を作るか（B13）。
6. **1 万枚の目標をどう確かめるか。** 合成画像を 1 万枚作って測るか、実データの規模（3,999 枚）で目標を置き直すか（B16-(a)）。
7. **クリップボード取り込みはサーバ側か、ブラウザ側か**（C9）。
8. **設定（タガーの閾値・訳のエンジン・`system_prompt`・データ置き場）をどこに保存し、どの API で編集するか**（C8）。
9. **「最近の削除」をどこに常設するか**（画面 or トレイのメニュー項目。A7）。
10. **L1 で品質語（`StringConcatenate` の前置）をどう扱うか。** 捕獲する文字列を `PreviewAny` ではなく「`CLIPTextEncode` に入る直前」にできないか（B3/B4）。
11. **`--no-hash` の「一覧の表示だけ」を担う表と API を作るか、`--no-hash` 自体をやめるか**（C7）。
12. **Host / Origin の検査を入れてよいか。** 「認証は付けない」決定を変えずに、ローカル前提の穴を塞ぐ手段として（B11）。

---

## H. 私が見落としている観点

- **実機での確認ができない。** D&D の実挙動、`POST /api/userdata` の実書き込み、`control_after_generate` の復元、ComfyUI の実行を伴う監視・訳し直し・タガーは、この点検では一切検証していない（環境も権限も無い）。§F に「未確認」として挙げたが、**未確認の一覧そのものが完全かは保証できない**。
- **画面の見た目。** 描画していないので、§2.6 の自己点検（「フレームが接する」構造が罫線だらけの紙面に見えないか）、`--seam` の 1px の見え方、暗幕での絵の見え方は判断できない。色のコントラストだけは計算した（`--ink-muted` は表 4.77:1 / 暗幕 6.21:1、`--accent` は 5.32:1 / 7.77:1、`--warn` 表 4.67:1、`--drop` 表 6.43:1、`--keep` 表 5.46:1）。**本文の下限 4.5:1 は満たす**が、`--seam`（表 `#C6C7CA` / 暗幕 `#0C0D0E`）と画像上の 1px 斜線は画像内容に依存し、保証できない（D12）。
- **書体の実物。** BIZ UDPGothic の 400/700 と UDPMincho の 500 という制約が、字の尺度（D2）と両立するかは実際に組んでみないと分からない。`font-variant-numeric: tabular-nums` が BIZ UDPGothic で効くかも未確認（文書も「効かない環境では」と留保している）。
- **DB の運用。** `user_version` による前方のみのマイグレーション（duplicates §5.4）と、WAL のチェックポイント、online backup の同時実行、`mmap_size` の効果は検証していない。7 表を後から足す（C1）ことになるので、マイグレーションの初版に何を含めるかは早めに決めたほうがよい。
- **依存とライセンス。** `onnxruntime-gpu` と ComfyUI の CUDA / cuDNN の共存、`pystray` の Windows での挙動、`uv` の `UV_CACHE_DIR` 制約は未検証（§4 と README に留保はある）。
- **私はこの設計を書いたのと同じ系統のモデルである。** 語彙（キープ / ボツ）と §18 の「連携しない」の解釈、そして「実測に基づく」という自己申告については、判断が甘くなっている可能性がある。特に **§12.1 の「根拠のない置き数値は置かない」という宣言を、私は一度も疑わずに読んでいた**（E2 は後から数えて気づいた）。同じ理由で、`comparison.md` と `duplicates` が互いを根拠として参照している箇所（E6）も、両方を書いた側の癖である可能性が高い。**別系統の点検（Fable）の指摘と突き合わせるときは、この 2 文書の相互参照を優先して見てほしい。**

見た結果、問題なしと判断した観点:

- 語彙（`kept` / `rejected` / `unreviewed`、`keep` / `reject` / `clear`、画面の「キープ / ボツ」）は、`design.md` §9.1・§17、契約の enum、`review-export.example.json` で統一されている。
- しきい値の値そのもの（pHash ≤ 6 / SSIM ≥ 0.95）は `comparison.md` §4・`duplicates` §2.4・`design.md` §6.1（`max_distance=6`）・§16.2-3 で一致している（単位と定義の記述は B15）。
- `GET /api/jobs/{prompt_id}`（`job id == prompt_id`）、`/history` の `prompt[3].extra_pnginfo.workflow`、`POST /api/userdata/{file}`（body は生バイト、`overwrite=false` で 409）は、`design.md` §7.4・`workflow-reproduction.md` §2・`comfyui-reproduction-findings.md` §4・§5 で一致している。
- 割り算の検算: 24,719 枚/秒 → 1 万枚 0.4 秒（✓）、399 MB/s → 13.7 GB で 34.4 秒（✓）、36 枚/秒 → 4.63 分（✓）、1,028 枚中 175 枚 = 17%（✓）、419 件中 150 件 = 36%（✓）、`1,204` = 未判断 812 + キープ 96 + ボツ 296（✓）。
- `review-export.example.json` は `review-export.schema.json` の構造（必須・列挙・`additionalProperties: false`）に**適合している**（突き合わせて確認）。食い違いは「契約に入っていない情報」（B8/B9）と「型の揃え方」（D3/C19）であって、検証エラーではない。

---

## 最も重大な 3 件

### 1. 英訳の捕獲と L1 の書き換え手順（B3・B4・E4）

この設計の要は「生成の瞬間を監視して英訳を捕まえる」（`design.md` §7.3.1・`workflow-reproduction.md` §5）に置かれている。
しかし実測（`comfyui-reproduction-findings.md` 503-505 行）では `outputs[node].text` は**リスト**で、中身は翻訳ではなく
VLM の説明文であり、ja2en の経路は `TextGenerate` → **`StringConcatenate`（品質語を前置）** → `CLIPTextEncode` なので、
捕獲した訳は最終プロンプトでもない。さらに L1 の手順（`TextGenerate` を外して `CLIPTextEncode.text` を置き換える）は、
宙に浮く結線と品質語の脱落を招き、再現キー（結線を含む）まで変える。**R4b と R12 の中核が同時に崩れる**ので、
実装が進んでから気づくと P3・P7 のやり直しになる。ここだけは実装前に、実機で `PreviewAny` の中身と
`CLIPTextEncode` に入る文字列を突き合わせて確定させるべきである。

### 2. 5 分の取り消しが「戻せない削除」になりうる（B12・B11・F1・F2・A7・A8）

決定は「確認は 1 回だけ。その代わり削除後 5 分間は取り消せる」である。ところが (a) 取り消しの `os.replace` は
元パスの別ファイルを**無警告で上書き**し、(b) 常設の「最近の削除」が画面にもトレイにも無く（`duplicates` §3.4 の要求と
`design.md` §4.1・`frontend-design.md` §3 が食い違う）、(c) アプリを閉じている間に窓が切れると起動時に**完全削除**され、
(d) 保留領域が別ボリュームのときの置き場所が未確認で、間違えると移動中の失敗がデータ喪失になる。
さらに認証も Host/Origin 検査も無いので、外部サイトから `DELETE /api/locations`（段 3）に到達しうる。
**利用者のファイルが失われる経路が 4 つ残っている**ので、安全網の設計を先に固めるべきである。

### 3. 走査の `UNIQUE(path)` 衝突と、準重複の帯索引の誤り（B2・B1・E3）

`asset_location` に `UNIQUE(path)` を張ったまま「中身が変わったら新しい `asset` を作って同じパスに場所を足す」と、
**走査の初回で必ず制約違反になる**（再保存・上書き生成は日常）。同時に、準重複の候補生成は
「16bit × 4 帯なら距離 ≤ 6 で一致帯が必ずある」という**偽の鳩の巣原理**に乗っており、実際には距離 2〜6 の
準重複を静かに取りこぼす（数え上げで 209 通り中 15 通りが該当）。どちらも「動いているように見えて結果が欠ける」
種類の誤りで、テストを書かない限り気づけない。**内容を正体にするという設計の土台**に関わるので、優先して直してほしい。

（次点: B7 の `decide` API が枚ごとの理由を表現できない点。契約と実例が表現している状態を API が作れないため、
外部契約の例が実在しえない出力になる。）
