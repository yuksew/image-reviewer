# Fable の点検（2 回目）の仕分けと対応

- 報告: [`review-report.md`](review-report.md)（77 KB、A6 / B9 / C16 / D20 / E10 / F9 / G11 / I19）
- 総合判定: **修正してから進む**（骨格は維持できる）
- この文書: 何を採用し、何を今直し、何を残したか

---

## 1. 最も重大な 3 件への対応

### 1. 削除の規則が自分の用途と衝突している（B1・A4・A6）→ **採用。設計を書き換える**

3 つとも本物だった。とくに `B1` は、規則をそのまま実装すると
**D&D・URL・クリップボード・要求で登録した画像と `<data>/library` の取込実体が「ルート外」として消せなくなる**。
実装者が規則を緩めれば、任意パスを消せる道具になる。危険なのはどちらの分岐も同じ。

直す方針（採用）:

- 規則を「**`asset_location` に登録された実在のパスそのものだけを触る**」に置き換える。
  比較は `normalize_path`（`normcase(realpath)`）の**完全一致**、区切り文字の単位。
  ルート前方一致は `mark_missing` の範囲決定にだけ使う。
- `A4`（「最後の 1 つ以外は段 2 まで」）は**逆向き**。→「最後の 1 つは重い確認、他のコピーは軽い確認で段 3 可」に直す。
- `A6`（`scope.kind='query'`）→ **2 段にする**。`preview` で対象を凍結し、`preview_id` で**その一覧だけ**を消す。
  実行時に `(size, mtime_ns)` を再照合する。

**実装で先に直したもの**: `normalize_path` / `is_under`（境界を区切り文字で見る）を入れ、
登録・照合・`mark_missing` をすべて正規化した鍵に統一した（点検 I1）。
テスト `test_is_under_is_boundary_aware` / `test_path_is_normalized` で固定。

### 2. 唯一復元できない来歴が守られていない（B3・I5）→ **採用。実装で直した**

- `capture` が **sidecar を書いていなかった**。→ **書くようにした**（点検 I5）。
  実データで確認: `79fe0685….json`（7.7 KB）に `en_text` / `final_prompt` / `textgen_params` /
  `textgen_system_prompt` / `llm` / `prompt_id` が入り、`store.json` の値と一致する。
- 設計側の残り（B3）: 日次スナップショットに `sidecar/` と `export/` を含める。
  バックアップ先を `<data>` の**外**に置けるようにする。リスク 11 の本文を
  「**外のバックアップがあれば**組み直せる」に直す。→ **設計の修正として残す**。

### 3. 主画面のサムネイルが判断に要る部分を隠す（B5・I10）→ **採用。実装で直した**

`object-fit: cover` で 768×1360 の上下 44% が切れていた。切れるのは手・足・背景の窓で、
**ボツの理由と要求の条件がまさにそこにある**。題材（ベタ焼き）はコマの縦横比を保つ。

直した: **高さを密度で固定し、幅を絵の縦横比から決める**（幅は 0.5〜2.2 倍に制限、`object-fit: contain`）。
切れなくなった。設計の `frontend-design.md` §4.1 も同じ記述に直す（残す）。

---

## 2. 実装で今直したもの（点検 I と B）

| 点検 | 内容 | 直し方 | テスト |
| --- | --- | --- | --- |
| **I1** | パスの正規化が無く、小文字で走査し直すと**全ファイルが再登録**される | `normalize_path`（`normcase(realpath)`）を鍵に。区切り文字の単位で比較 | `test_path_is_normalized` / `test_is_under_is_boundary_aware` |
| **I2** | `KSampler` の seed などが結線のとき `str(["20", 0])` が値になる | `resolve_input` で結線を辿る（`Primitive*` の `value`） | `test_analyze_graph_resolves_linked_sampler_inputs`（64bit 最大値つき） |
| **I3** | `clip` が「最初の `CLIPLoader`」、`llm` 未抽出、正負を「空文字か」で判定 | 正側が参照する `CLIPLoader` を `clip` に、`TextGenerate` が参照するものを `llm` に。正負は**結線の先**で決める | `test_analyze_graph_extracts_ja2en_provenance` |
| **I4** | オフセットで上限を測る、壊れた長さを黙って捨てる、`zTXt`/`iTXt` を読んで捨てる、権限エラーを「PNG ではない」と報告 | 読んだバイト数で上限、`zTXt` は zlib・`iTXt` は UTF-8、理由を `error` に残す | `test_png_chunk_parser_reads_ztxt` / `test_broken_chunk_length_is_reported` / `test_read_png_reports_reason_instead_of_none` |
| **I5** | sidecar を書いていない | `write_sidecar`（原子的）を追加 | 実データで確認 |
| **I6** | 同名ファイルを `basename` だけで照合 | `subfolder` を突き合わせる。複数の実行にまたがるときは**埋めない**（`ambiguous`） | `test_index_outputs_matches_subfolder` |
| **I9** | 来歴なしを `opacity .55` で薄くしていた（設計に無い。ボツの彩度 35% と混ざる） | 薄くするのをやめ、`--warn` の印の意味を「来歴なし」にする | — |
| **I13** | LoRA の重みが入らない、`LoraLoader`（clip 付き）を無視、複数 `KSampler` が上書き | `{name, strength_model, strength_clip, loader}` に。両方の型を読む。主のサンプラは保存ノードから遡った最初の 1 つ | 同上 |
| **I14** | テスト名が「`IDAT` の後の `tEXt`」なのに、Pillow は `IDAT` の**前**に書くので一度も通っていなかった | 手で組んだバイト列（IHDR → IDAT → tEXt → IEND）を足し、名を実態に合わせた | `test_png_chunk_parser_reads_text_that_comes_after_idat` |
| **I15** | 今すぐ要るテストが 7 件無い | 捕獲の 3 手順・守りの 403・64bit 最大値・移動しても判断が切れない・結線の seed・大小文字・他ルートを触らない | 21 件に増えた（9 → 21） |
| **I16** | サムネイルの一時ファイル名が固定で競合する | `mkstemp` + `os.replace` | — |
| **I19** | 1 枚につき `open` が 3 回 | 1 回開いて先頭バイト・ハッシュ・チャンクを同じハンドルから取る | 既存のテスト |
| **B5** | サムネイルが絵の 44% を切る | 縦横比を保つ（上記） | — |
| **B8** | 契約の `Provenance.seed` が `integer`（JS の `JSON.parse` で 2^53 超が丸まる） | `string`（`^[0-9]+$`）に変更。`runs[].seed` と同じ扱い | — |
| **I12/C2** | 種別（`kind`）の自動判定に規則が無い | 規則を決めた: `prompt` あり → `generated`（`auto:prompt`）／PNG で `prompt` 無し → `generated`（`auto:png`。後処理の出力が多いため）／JPEG → `photo`（`auto:jpeg`）。`kind_source` に推定の根拠を残し、人が直せる。**推定が外れる場合（参考資料を PNG で入れた等）は設計に明記する** | `kind_source` を実データで確認 |

**結果**: `uv run pytest -q` → **21 passed**。実データ 263 枚を新しい正規化で作り直し、
`with_provenance 183` / `missing 0` / 日本語 1 / 捕獲 1 / sidecar 1 を確認。

---

## 3. 設計に残した対応（次にやる。優先順）

| 優先 | 点検 | 直す場所 | 内容 |
| --- | --- | --- | --- |
| 1 | A1 | `design.md` §3・§4・§5.1、`frontend-design.md` §2.3 | 「接続先は ComfyUI だけ」を「**自分から出るのは ComfyUI と、利用者が明示した URL の取得だけ**」に直す。URL 取得の上限（タイムアウト・最大バイト・`http(s)` のみ・マジックナンバー・リダイレクト回数）を書く |
| 2 | A5 | `design.md` §5.6・§9.5・§6.1 | エージェントの入口を `review-requests` だけにし、`POST /api/reviews` と `decide` は `human` 以外 403。`decision.actor='agent'` は「今の実装では書かれない」と注記 |
| 3 | A3 | `design.md` §7.3.1、`workflow-reproduction.md` §5 | 起動時の救済は**既に登録済みの画像の `en_text` を埋めるだけ**にする（新規登録しない）。**プロトタイプの `capture_history` は既にこの振る舞い**なので、設計を実装に合わせる |
| 4 | B1・A4・A6 | `duplicates-deletion-backup.md` §3.2・§3.4、`design.md` §6.1 | 削除の規則の置き換え（§1）。`preview` / `preview_id` の 2 段 |
| 5 | B2 | `duplicates-deletion-backup.md` §3.4 | 5 分の窓を**アプリが動いていた時間**で数える（`time.monotonic`、スリープ中は減らさない）。起動時に消さない。取り消しに失敗したら `purge_at` を `NULL` にして自動削除から外す |
| 6 | B3 | `duplicates-deletion-backup.md` §5.2・`design.md` §15 | sidecar/export を日次スナップショットに含める。バックアップ先を `<data>` の外に既定で置く。リスク 11 の本文を直す |
| 7 | B4 | `design.md` §6.2・§9.4 | 判断のたびの自動書き出しは**影響したまとまりのファイルだけ**。全件は手動と日次。`tags`/`prompts` を `include_tags`/`include_prompts`（既定 false）に |
| 8 | B6・G2 | `design.md` §9.3・§9.6 | まとまりの枚数上限を外し、番号キーは**見えている 8 枚**に。要求に任意の `target_key` を足し、「同じ `target_key` の `open` を `superseded` に」と書く |
| 9 | B7 | `frontend-design.md` | **R12（条件の記録・判定・書き出し・合否・プリセット）の画面が 1 つも無い**。画面・部品・文言を足す |
| 10 | B9 | `workflow-reproduction.md` §4.7.1・§4.7.2 | 印の前提（`filename_prefix` がリテラル・保存ノードが 1 つ・`type='output'`）を明記し、外れたときの落とし方を決める。検査は `/object_info/{class_type}` の combo 値と入力キー集合で行う |
| 11 | C・D・E・F | 各文書 | 1 回目から**約 40 件が仕分け表に載っていない**（Fable の C1）。仕分けを埋めてから、残りを順に直す |

## 4. 依頼者に判断してほしいこと（Fable の G）

Fable の推奨に私も同意する。**「全部推奨でよい」で構わない**なら、そう指示してください。

| # | 論点 | 推奨 |
| --- | --- | --- |
| G1 | 画像への手動タグ付け（`manual`）を残すか | **残す**（決定は「語の統合・改名を作らない」であって、画像への付け外しは否定していない）。`design.md` §16.1 の文言を直す |
| G2 | 要求の「同じ対象」を何で決めるか | **エージェントが付ける任意の `target_key`**。無ければ上書きしない |
| G3 | 契約に画像の種別（`kind`）を入れるか | **入れる**。後から足すと `abi` を上げる理由になる |
| G4 | 5 分の窓を「アプリが動いていた時間」で数えてよいか | **よい** |
| G5 | 「最後の 1 つ以外は段 2 まで」の意図 | **「最後の 1 つは重い確認、他は軽い確認で段 3 可」に書き換える** |
| G6 | サムネイルの形 | **行の高さ固定・幅可変（縦横比を保つ）** ← 実装で先に直した |
| G7 | 判断のたびの書き出しの範囲 | **まとまり単位のファイルだけ自動**、全件は手動と日次 |
| G8 | 要求の画像が 8 枚を超えたとき | **上限を外し、番号キーは見えている 8 枚に割り当てる** |
| G9 | エージェントが `POST /api/reviews` で判断を書けるか | **書けない**。入口は要求の `ai_pick` だけ |
| G10 | プロトタイプを P1 の土台にするか、設計どおり作り直すか | **土台にする**。ただしパスの正規化と結線の解決は**先に直す**（今回直した） |
| G11 | 本実装の順序（P4 → P5 か P1 → P5 か） | **P5（判断と比較）を先に**。判断が主目的で、来歴はプロトタイプで足りた |

## 5. Fable 自身が挙げた限界（次の点検で補うこと）

- **実行していない**（`pytest`・スキーマ検証・性能の再計測・ブラウザ描画・ComfyUI 接続のいずれも）。
  この環境で `rg` が起動できず `Glob` / `Grep` が使えなかったため、ファイルは個別に読んだ。
- **Windows の挙動**（`os.walk` とジャンクション、`os.replace` と使用中のファイル、`realpath` の大文字小文字）は
  記憶に基づく。F5・C7 は実機で確かめてから設計に入れる。
- **画面の見た目は描画していない。** 構造について言えるのは「3 列＋上下バーという**外枠はどんな題材でも出る管理画面の形**」で、
  題材（ベタ焼き）が効いているのは一覧の中だけ、という点。
- **1 回目の申し送り（`design.md` §12.1 の自己申告）はまだ未達**。表は「実測」と「目標」に分かれたが、
  E1 の残りと E3（計測条件）があり、「実測に基づく」の土台は揃っていない。

→ 次の点検（3 回目）を頼むときは、**実装が動く状態で**「実行して確かめてよい」と伝える
（`--allowedTools` に `Bash` を足す）。今回は読み取りだけだった。
