# P5 の設計（判断と比較）

- 版: 0.2（**Fable の点検を反映**。実装前）
- 対象: 工程 P5「判断と比較」（[`design.md`](design.md) §14）。**最初に実装する段**（点検 G11）
- 前提: [`design.md`](design.md) §5.4・§9・§6.2・§6.3、[`comparison.md`](comparison.md)、
  [`review-triage-fable.md`](review-triage-fable.md)（決まった 11 件）、
  [`review-triage-review1.md`](review-triage-review1.md)（未仕分けだった 80 件の仕分け）、
  [`p5-review-report.md`](p5-review-report.md)（**この段の点検**。A2 / B5 / C16 / D / E / F）
- **この文書はレビューの対象**。点検してほしい点は §11 に列挙した（点検は完了。§0 が結論）。
- 使い方: 点検 → 修正 → 実装 → 監査（Claude Code の Fable）

---

## 0. 点検の反映（**本文と食い違うときはこちらが正**）

点検の判定は **「修正してから進む」**。指摘は [`p5-review-report.md`](p5-review-report.md)、
仕分けは [`p5-review-triage.md`](p5-review-triage.md)。下表が**拘束力のある差分**で、
本文（§1〜§11）はこの差分で読み替える。

### 0.1 段の分け方（点検 G1・G2・G10）

P5 を **4 つに分ける**。**合格の線は P5-2 まで**。

| 段 | 中身 | 完了条件 |
| --- | --- | --- |
| **P5-0** | **SQLite 化（機能を足さない）。** 表の作成、`store.json` からの取り込み、`asset.id` の ULID 化、`review_group.changed_at` / `exported_at` の追加、**サーバ経由の走査**（別プロセスの `save()` をやめる） | 既存の 21 件のテストが緑。`store.json` から取り込んだ 263 枚が同じ来歴で引ける。**`cli scan` がサーバの判断を消さない**ことをテストで示す |
| **P5-1** | **判断と書き出し。** 台帳、現在値の写し、1 枚の判断、まとまりの決定、`review.json` の書き出し（影響したまとまりだけ） | §1 の合格の線 1〜7（比較を除く） |
| **P5-2** | **比較の基本。** 並べる、来歴の差分表、同期ズーム | 8 枚を来歴つきで比べ、**違う行だけ**が既定で見える |
| **P5-3** | **比較の重い見方。** 差分ヒートマップ、似ている順、`comparison_cache`、pHash/dHash の背景ジョブ | 近い組でヒートマップが出る／pHash の実測を記録する |

- **P0 の DB とマイグレーション、P1 の最小のジョブ実行と起動時フックは P5-0 に含める**（点検 G1）。
- **`numpy` をこの段で入れる**（点検 G3。SSIM と位置合わせに要る。P4 の前倒し）。
- **P5-3 は合格の線に数えない。** 判断と差分表が主目的（点検 §I-11）。

**P5-0 / P5-1 / P5-2 で作らないもの（先に断っておく）:**

- **SSE（`GET /api/events`）は無い**（点検 C16。監査でも「未反映」と確認）。
  プロトタイプにジョブも SSE も無いので、**画面は判断の応答（`reopened_group_ids` など）を
  使って自分で組み直す**（§4 の 6 の「SSE で流す」は行わない）。入れるのは P1 のジョブ基盤と一緒にする。
- **日次の全件書き出しは未着手**（点検 C14-(4)）。`<data>/export/review.json` と
  件数索引の `index.json` を**起動時に 1 日 1 回**書く形はまだ無い。いま全件が出るのは
  **手動の `POST /api/export/review.json`**だけで、判断のたびに出るのは
  影響したまとまりのファイルだけ（§3.4。点検 B4）。**日次は保留のまま**にする。

### 0.2 決定との矛盾の修正（A1・A2）

| # | 直すこと |
| --- | --- |
| **A1** | **`assets[].kind` を必ず出す**（`asset.kind` の写し）。契約では `required` に無いので**落としても検証が通ってしまう**。§3.4 に「必ず出す」と書き、§7 に「`kind` が入っている」を足す |
| **A2** | **`actor` はヘッダ `X-Image-Reviewer-Actor` だけから取る。** 本文の `actor` は**無視する**。**無ければ `agent`** として 403。**画面は全ての状態変更要求に `X-Image-Reviewer-Actor: human` を付ける**（§5 に明記）。`design.md` §6.1 の本文の `actor?` は削る |

> A2 は**実装を間違えると人の判断が全部 403 になる**（画面がヘッダを付け忘れた場合）、
> 逆に「無ければ human」と実装すると**エージェントが素通りする**。どちらも避ける。

### 0.3 書き出しの修正（B1・B2・B3・G11）

| # | 直すこと |
| --- | --- |
| **B1** | **ファイルの mtime で「書き出し済み」を判定しない。** `review_group` に **`changed_at`** と **`exported_at`** の 2 列を足し、**判断・reopen・メンバー変更と同じトランザクション**で `changed_at` を更新する。書き出しの対象は `exported_at IS NULL OR changed_at > exported_at`。ファイルを置いた後、`exported_at` に**書き出し開始時に読んだ `changed_at` の値**を入れる（開始後に入った変更は次回に残る） |
| **B2** | **「影響したまとまり」を定義する**: その判断で `decision` を書いた**全画像**について `group_item` を引いた `group_id` の**和集合**。1 枚の判断でも N 個のファイルを書く（P5 の規模では小さい）。**まとまりに属さない画像は日次と手動だけ**に出る（§3.4 に明記） |
| **B3** | **`open` なまとまりも書き出す**（判断のたびに書くため）。契約を直した（`GroupItem.verdict` を **null 可**、`Group.decision` は `open` なら `null`、`selected_asset_ids` は `[]`）。**実装済み**（実例に `open` なまとまりを足して検証） |
| **G11** | `GET /api/export/review.json?scope=asset:{id}` を足す（**読むだけ。ファイルは書かない**）。まとまりに属さない画像の判断を、他ツールが日次を待たずに読める |
| **C1（追記）** | **書き出しの失敗で一時ファイルを残さない。** `_atomic_write` の `os.replace` を `try` で囲み、失敗したら `<id>.json.<pid>.<tid>.tmp` を消してから投げ直す。あわせて**起動時**（`flush_dirty()` の先頭）に `export/groups/*.tmp` を掃除する。実行での再現: ファイルを掴んだまま 9.5 秒で `.tmp` が **+4**（2 秒ごとの再試行のたびに別名で増え、誰も消さなかった） |
| **C9（追記）** | **理由の改名も印にする。** `PATCH /api/reason-codes/{id}` で `label` を変えたら、その理由を参照しているまとまり（**まとまりの結論**と**属する枚の現在値**の両方）に `_touch_groups` して書き出しを予約する。契約ファイルの `reason_label` は「書き出し時点のマスタ」（点検 G8）なので、印がないと次に誰かが触るまで**旧名**が残る |

### 0.4 まとまりの決定の修正（B4・G7・G9）

- **`decided` を `open` に戻すのは「結論が変わるときだけ」。**
  1 枚の判断が入ったとき、その画像が属する `decided` なまとまりのうち
  **verdict が結果と食い違う**もの（`selected` の枚が `reject`、`pick_one` で `not_selected` の枚が
  `keep`、`all_rejected` のまとまりで 1 枚が `keep`、`selected` の枚が `clear`。
  `pick_many` で選ばれた枚が 0 になる場合も `clear` に含む）
  だけを `open` に戻し、`changed_at` を更新する。
- **理由・メモだけの変更（verdict が同じ）は `decided` のまま。** `supersedes` で繋ぎ、
  `group_decision` を前の行から引き継ぐ。
- §3.1 の応答に **`reopened_group_ids`** を返し、画面が「この判断でまとまりが未決定に戻った」と知らせられるようにする。
- **`reopen` は枚ごとの判断を消さない**（`clear` を書き足さない。点検 G7）。
- §7 に「理由だけ直しても `decided` のまま」「選ばれた枚をボツにすると `open` に戻る」を足す。

### 0.5 その他の確定（点検 G4・G5・G6・G8）

| # | 決定 |
| --- | --- |
| **G4** | 「全部ボツ」用の**既定の理由を builtin として用意しない**（語彙は利用者のもの）。ボツの初期値は `design.md` §9.2 の 8 つ＋「その他」（利用者の指定どおり） |
| **G5** | プロンプトの**重みの違いは「重み変更」として出す**（`comparison.md` §3.2 の正規化から「重みの表記を同一視する」を外す）。重みは絵を変えるので「同じ」ではない |
| **G6** | 差分ヒートマップは、**条件の外でも利用者が押せば出す**（`force`）。「派生関係」の条件は P7 まで外す |
| **G8** | 理由の表示は**マスタを引く**（改名すると過去の表示も変わる）。契約の `reason_label` は「**書き出し時点の** label」と `description` に書く |
| **G9** | 「結論が変わるときだけ reopen」で確定 |

### 0.6 差分表の鍵の追加（点検 C5）

§6.1 の鍵に次を足す: **`negative_literal` / `init_image` / `textgen_params` / `node_types` /
`final_prompt_source`**。`clip_skip` は**プロトタイプが読んでいない**ので、要るなら
`png_meta.py` の変更を P5-2 に含める（今は入れない）。

**追記（監査 G4・実行込みのやり直し）**: **`textgen_system_prompt`**（翻訳 LLM への指示。訳を
変える）と **`en_source`**（その英訳が捕獲か訳し直しか）も足す。前回の点検 C5 が挙げていたのに
ここで黙って落ちていた 2 つで、`analyze_graph()` / `capture.py` が既に返している値なので
「発明」にはならない。実測でも `compare_assets` の `diff.keys` に両方が入り、差が出ることを
確かめている（`tests/test_compare.py` の `test_the_g4_keys_are_diffed`）。

### 0.7 実装の前の実測（`tools/probe_p5.py`。2026-10-15 実測）

未確認のまま進めないとした 3 件を実測した。**結果が 2 つの前提を変えた。**

| # | 確かめたこと | 結果 | 設計への影響 |
| --- | --- | --- | --- |
| **F1** | SQLite の**部分索引**が使えるか | **OK**（`sqlite_version 3.53.1`）。`CREATE UNIQUE INDEX ... WHERE client_token IS NOT NULL` で重複を弾き、`NULL` は何個でも入り、検索でその索引を使う。`journal_mode=wal` も通る | B1・C11・D3 の設計がそのまま成り立つ |
| **F2** | Pillow の **`F` モード**に `GaussianBlur` が効くか | **NG**（`ValueError: image has wrong mode`）。`Image.blend` も同様 | **SSIM は Pillow だけでは書けない。`numpy` が必須**（G3 の判断が正しかった。推測が実測で確定） |
| **F5** | pHash の実費用（**復号込み**） | **11.88 ms/枚**。内訳は **復号＋32×32 縮小が 11.35 ms**、純 Python の DCT が **0.53 ms** | **DCT は無視できる。費用は復号だけ。** 1,000 枚 11.9 秒 / 1 万枚 2.0 分。「背景ジョブが要る」は**誤り**で、**サムネイルを作る時に同じ復号で一緒に計算する**のが正しい（2 回目の点検 C15 の「サムネイルのジョブに同居」が実測で裏付けられた） |
| **実測（P5-3 実装後）** | pHash / dHash の実費用と、1 組の差分の費用 | 復号のみ **11.4 ms/枚** / 復号＋pHash＋dHash **14.1 ms/枚** / **復号済みの画像からハッシュだけ 2.38 ms/枚**。1 組の差分は **1024² で 26 ms / 2048² で 83 ms** で、**復号（原本の画素数に比例）が支配**（256px の FFT・差・合成は数 ms） | F5 の判断は実装後も正しい（ハッシュをサムネイルの復号に同居させれば追加は 1 枚 **約 2.7 ms**。DCT だけの見積り 0.53 ms の **4.5 倍**だが、復号 11.4 ms に比べれば小さい）。**§8 の 50ms は復号を除いた値**である（復号込みでは 1024² でも届かない）。1 組 26〜83 ms は「256 のサムネイル（既に縮小済み）を入力にする」余地として残る |
| **監査 A2** | 位置合わせの判別材料（実データ 263 枚） | **無関係な 200 組**: 峰の比（`max/mean(\|corr\|)`）p50 **5.66** / p90 **7.12** / 最大 **71.8**、一致度（合わせた重なりの正規化相互相関）p90 **0.205** / 最大 **0.758**。**同じ seed の 49 組**: 峰の比 **5.14〜216.3**、一致度 −0.187〜0.983。同じ絵の縮小・再圧縮は一致度 **0.949**、ずらした写しは **1.000** | **峰の比だけでは判別できない**（同じ seed の組の最小 5.14 が無関係の中央 5.66 より低く、範囲が重なる）。前の閾値 **1.5 はノイズの床より下で決して発火しない**（`comparison.md` §2.3 の「別の絵」の判定が死んでいた）。峰の比は**足切り 8.0** にし、判別は**一致度 0.80**（無関係の最大 0.758 と、同じ絵 0.949 の間）で行う。**同じ seed でも絵が違えば「位置が合いません」**になる（実測で 49 組のうち一致度 0.80 を超えるのは 3 組）＝黙って誤魔化さない |
| **監査 B1** | 既存 263 枚のハッシュと、初回の比較文書 | 実データ 263 枚は `phash IS NULL` が **263/263**（ハッシュはサムネイルの復号に同居して入るため）。比較の要求時に足りない枚だけ埋めると、実データ 4 枚で **1 回目に復号 4 回 / 2 回目 0 回**（1 枚 14.1 ms × 最大 8 枚 = 最大約 113 ms を 1 度だけ） | **起動時の全件は要らない**（263 枚で **3.7 秒**、1 万枚で 2.3 分＝規模に比例する）。`compare_assets()` が文書を組む前に**錠の外で**埋めれば、画面を開いただけで似ている順の距離とヒートマップの可否が出る |

- **`asset.phash` はサムネイル生成と同じパスで計算する**（§6.2 を「走査の背景ジョブ」から変更）。
  復号が 2 回にならないので、追加の費用は **0.53 ms/枚**（DCT だけ）。
  **追記（P5-3 の実行込み監査。`probe_p5.py` の 4 番を直接呼んだ実測）**: 復号のみ **11.30 ms** /
  復号＋pHash＋dHash **15.05 ms** / **復号済みからハッシュだけ 2.57 ms**（pHash 1.43 + dHash 1.29）。
  純費用は当初の見積り **0.53 ms の 4.8 倍**（2 回の `convert("L")` と LANCZOS のため）。
  それでも復号 11.3 ms に比べれば小さく、**「サムネイルの復号に同居させる」判断は変わらない**。
- **`tools/probe_p5.py` はこの環境では `%TEMP%` に SQLite を作れず落ちる**（P5-3 の実行込み監査 C3）。
  一時ファイルを `<repo>/.tmp-probe/` などに置くよう直すまで、**実測の記録が残らない**。
- §8 の「pHash 8ms/枚」は**見積り**だった。実測は 11.88 ms/枚（復号込み）／0.53 ms/枚（DCT のみ）。
- 実装の注意: `Image.getdata()` は Pillow 14 で廃止予定（`DeprecationWarning`）。
  `get_flattened_data()`（または numpy 経由）を使う。

---

### 0.8 その他の実装上の注意（点検 C・D）

| # | 内容 |
| --- | --- |
| **C11** | 「最後の `decision`」を `created_at` で決めない。**挿入順（単調な `seq`）**で決める（時計の逆行に耐える） |
| **C16** | SSE はプロトタイプに無い。§4 の 6 は当初 P5-1 で**最小の実装**を入れるとしていたが、**P5-0 / P5-1 / P5-2 では入れていない**（監査で「未反映」）。画面は判断の応答を使って自分で組み直す（§0.1） |
| **D5** | §6.1 の `tags` は `[]` ではなく **`null`**（「未計算」と「無い」を区別する）。P4 で埋まる |
| **D12** | 9 枚以上の送りに**マウスの経路**も書く（ストリップの横スクロール＋クリック） |

---

## 1. 何を作るか（範囲）

| 作る | 中身 |
| --- | --- |
| **判断の台帳** | `decision`（追記のみ）＋ `reason_code`（理由マスタ）＋ `asset` への現在値の写し |
| **1 枚の判断** | 拡大（`#/asset/<id>`）でキープ / ボツと理由を付ける |
| **まとまりの判断** | `review_group` から 1 枚選ぶ / 全部ボツ。**枚ごとに理由**。枚数の上限なし |
| **比較** | 並べる / 来歴の差分表 / 差分ヒートマップ / 同期ズーム / 似ている順（[`comparison.md`](comparison.md)） |
| **書き出し** | 判断のたびに**影響したまとまりのファイルだけ**、手動と日次で全件（§6.2 of design.md） |
| **人の判断の強制** | `POST /api/reviews` と `decide` は **`human` 以外 403**（点検 A5） |

**作らない（後の段）**: 要求（P6）、注記（P6）、タグと語釈（P4）、条件の記録と書き出し（P7）、
重複と削除（P8）、監視（P3）。**この段では触らない**。

**合格の線**（[`design.md`](design.md) §14 P5 の完了条件を、確かめられる形に落とす）:

1. 1 枚にキープ / ボツと理由を付けられ、**再起動しても残る**
2. まとまりから 1 枚に決めると、**選ばれた枚に `keep`、他の全枚にその枚自身の理由つきの `reject`** が入る
3. **全部ボツ**でも理由が必須で、理由なしでは決定できない
4. **エージェント（`actor` が `human` 以外）は 403** で書けない
5. 8 枚を来歴つきで比べ、**違う行だけ**が既定で見える
6. 他ツールが `review.json` を読んで「どのまとまりの、どの 1 枚に決まったか」が分かる
7. **判断の記録が 100ms 以内**（§12.1）、判断のたびの書き出しが**影響したまとまりのファイルだけ**

---

## 2. データモデル（§5.4 の表を使う。追加はここに書く）

`design.md` §5.4 の `decision` / `reason_code` / `review_group` / `group_item` をそのまま使う。
この段で足すのは次の 2 つだけ。

```sql
-- 同じ判断を二度書かない（楽観的更新の再送に耐える。§4）
ALTER TABLE decision ADD COLUMN client_token TEXT;   -- 画面が作る UUID。任意
CREATE UNIQUE INDEX ux_decision_token ON decision(client_token) WHERE client_token IS NOT NULL;

-- 比較の指標を組ごとに覚える（compute on demand・cache。§6）
CREATE TABLE comparison_cache (
  a_id TEXT NOT NULL, b_id TEXT NOT NULL,          -- a_id < b_id に正規化する
  ssim REAL, changed_fraction REAL, mean_abs REAL, phash_distance INTEGER,
  computed_at TEXT NOT NULL,
  PRIMARY KEY (a_id, b_id)
);
CREATE INDEX ix_comparison_a ON comparison_cache(a_id);
```

### 2.1 現在値の写し（マテリアライズ）の規則

`asset.review_state` / `review_reason_id` / `reviewed_at` / `reviewed_by` は、
**その `asset` を対象にした最後の `decision`**（`created_at` の降順、同時刻なら `id` の降順）から写す。

| 最後の `verdict` | `review_state` |
| --- | --- |
| `keep` | `kept` |
| `reject` | `rejected` |
| `clear` | `unreviewed`（理由と日時も `NULL` に戻す） |
| 判断が 1 つも無い | `unreviewed` |

- **`decision` は消さない・書き換えない。** 取り消しも `clear` の追記で表す。
- 写しは**同じトランザクション**で更新する（台帳と現在値がずれた状態を外に出さない）。
- 起動時に「台帳から写しを組み直す」検査を 1 回行い、ずれていれば直して件数をログに出す
  （写しは**導出できる**ので、壊れても失われない）。

### 2.2 理由マスタの初期値

`design.md` §9.2 のとおり。`builtin=1` で入れる（消せない。`active=0` にはできる）。

```text
keep : 意図どおり / 気に入った / これで仕上げる
reject: 人数・人物が違う / 構図・アングルが違う / 意図・場面と違う /
        雰囲気・絵柄が違う / 服装・小物が違う / キャラが違う（別人化） /
        破綻（体・関節・結合） / 表情が違う / その他
```

**「同じまとまりに良いものがある」は入れない**（利用者が選ばなかった）。
選ばれなかった枚には**その枚自身の理由**を付ける。

---

## 3. API（`design.md` §6.1 の該当行を、ここで確定する）

### 3.1 1 枚の判断

```text
POST /api/reviews
  {subject_type:'asset', subject_id:'<asset_id>', verdict:'keep'|'reject'|'clear',
   reason_code_id?:'<id>', note?:'<自由文>', client_token?:'<UUID>'}
→ 200 {decision_id, asset:{id, review_state, reason_code_id, reason_label, decided_at, decided_by}}
```

| 条件 | 応答 |
| --- | --- |
| `actor` が `human` 以外 | **403** `{"detail":"判断は人が付けます"}`（点検 A5） |
| `verdict='reject'` で `reason_code_id` が無い | **422** `{"detail":"ボツには理由が要ります"}` |
| `reason_code_id` が存在しない / `active=0` | **422** |
| `verdict='clear'` | `reason_code_id` は無視して `NULL` にする（未判断に戻す） |
| 同じ `client_token` で再送 | **200**（既存の判断をそのまま返す。二重に書かない）。**その後に同じ枚へ新しい判断が入っていれば `superseded: true` を添える**（監査 C6。以前は 409 にしていたが、設計の約束どおり 200 に戻した） |
| `subject_type` が `asset` 以外 | **422**（まとまりは `decide` を使う） |

- `keep` に理由は**要らない**（付けたければ付く）。
- `note` は自由文。上限 2000 文字（超過は 422）。
- 応答に**現在値をそのまま返す**ので、画面は楽観的更新の後始末に使える。

### 3.2 まとまりの判断

```text
POST /api/groups/{id}/decide
  {items:[{asset_id, verdict:'keep'|'reject', reason_code_id?, note?}],
   group_reason_code_id?:'<id>', note?:'<自由文>', client_token?:'<UUID>'}
→ 200 {group:{id, state, decision, selected_asset_ids, reason_code_id, reason_label, decided_at, decided_by},
       items:[{asset_id, review_state, reason_code_id, reason_label}]}
```

規則（**まとまりの意味を壊さないための検査**）:

| 条件 | 応答 |
| --- | --- |
| `actor` が `human` 以外 | **403** |
| `items` の `asset_id` が、そのまとまりの全枚を**過不足なく**覆っていない | **422**（`details.missing` / `details.extra` を付ける） |
| `verdict='reject'` の項目に `reason_code_id` が無い | **422**（**枚ごとに理由が要る**） |
| 1 枚も `keep` が無い（＝全部ボツ） | `group_reason_code_id` が**必須**。無ければ **422** |
| `keep` が 2 枚以上で `policy='pick_one'` | **422**（「1 枚選ぶ」の意味が壊れる） |
| `policy='all_reject_only'` で `keep` がある | **422** |
| 同じ `client_token` で再送 | **200**（既存の結果を返す）。**その後に新しい判断が入った／`open` に戻った場合は `superseded: true`**（監査 C6） |

- **1 トランザクション**で「枚ごとの `decision`（N 件） → まとまりの `decision`（1 件） →
  現在値の写し → 影響したまとまりの書き出し」まで進める。
- まとまりの `decision` には `group_decision`（`selected` / `not_selected` / `all_rejected`）を入れる。
- `policy='pick_many'` では `keep` が複数でもよい。

```text
GET    /api/groups                ?state=open|decided&cursor=&limit=
POST   /api/groups                {title?, kind, asset_ids:[]}       -- 枚数の上限なし（点検 B6/G8）
GET    /api/groups/{id}           -- まとまり + 項目 + 各枚の現在値
POST   /api/groups/{id}/reopen    -- state を open に戻す（判断は消さない。台帳は残る）
GET    /api/groups/{id}/compare   -- 比較に要るものを 1 回で返す（§6）
```

### 3.3 理由マスタ

```text
GET    /api/reason-codes                     ?applies_to=keep|reject|both&include_inactive=false
POST   /api/reason-codes          {label, applies_to}       -- id は自動。builtin=0
PATCH  /api/reason-codes/{id}     {label?, applies_to?, position?, active?}
```

- `builtin=1` の行は**消せない**（`DELETE` は 405）。`label` と `active` は変えられる。
- 使われている理由（`decision` から参照がある）を `active=0` にしても、**過去の判断の表示は変わらない**
  （表示は `reason_label` を判断時の値として持たないので、`reason_code.label` を引く。
  改名したら過去の表示も変わる。**これを仕様とする**か、`decision` に `reason_label` を焼き込むかは §11 の問い）。

### 3.4 書き出し

```text
GET  /api/export/review.json  ?scope=all|group:{id}|folder:{id}|request:{id}
                              &include_paths=false&include_tags=false&include_prompts=false
POST /api/export/review.json  {scope, include_paths?, include_tags?, include_prompts?}
GET  /api/export/review.schema.json
```

- 判断のたびに書くのは `<data>/export/groups/<group_id>.json` **だけ**（点検 B4）。
- **書くのは `POST` の `scope=all` だけ。`GET` は返すだけ**（監査 C8/G2。読み出しに副作用を
  持たせない——プリフェッチやリンクのプレビューで勝手に書かれない。以前は GET でも書いていた）。
- `scope=all` は手動と日次だけ。`include_tags` / `include_prompts` は**既定 false**。
- **決定性**: `generated_at` を除いて 2 回出して同一（§14 のテスト方針）。

---

## 4. 書き込みの道筋（1 か所に集める）

判断は**すべて `ReviewService.apply()` を通す**。画面も API もここ以外から書かない。

```
apply(actor, subject, verdict, reason_code_id, note, group_id?, group_decision?, client_token?)
 1. actor が human か確かめる（違えば 403）
 2. 理由の妥当性（reject なら必須・存在・active）
 3. client_token の重複を確かめる（あれば既存を返して終わり）
 4. BEGIN
      decision を 1 行 INSERT（追記のみ）
      asset の現在値を写す（§2.1）
      （まとまりなら N 件ぶんを同じトランザクションで）
      export の対象（影響したまとまり）を印だけ付ける
    COMMIT
 5. 書き出しを**遅延**させる（既定 2 秒。同じまとまりへの連続判断をまとめる）
 6. SSE で画面に「変わった」を流す（画面は楽観的更新の後始末に使う）
```

- **書き出しはトランザクションの外**。書き込みの速さ（100ms）を書き出しの重さから切り離す。
- 遅延中に落ちても、**台帳は確定している**。次回の起動時に「印の付いたまとまり」を書き出す
  （`export_dirty` の表ではなく、`decision.created_at > export の mtime` で判定する。表を増やさない）。

**並行**: 1 ユーザーなので**最後の書き込みが勝つ**。ただし
**`Group.decided_at` 以降に同じまとまりへ別の判断が入ったら、まとまりは `open` に戻す**
（人が見ていない状態で `decided` のままにしない）。

---

## 5. 画面（詳細は [`frontend-design.md`](frontend-design.md)。ここは挙動だけ）

### 5.1 拡大（`#/asset/<id>`）の判断

- 下部に「キープ」「ボツ」と理由の選択。ボツは**理由を選ぶまで確定できない**（押すと選択が開く）。
- 押した瞬間に印が変わる（**楽観的更新**）。`POST /api/reviews` が失敗したら**元に戻して 1 行で知らせる**。
- `Enter` でキープ、`X` でボツ、`A` はまとまりのときだけ。
- 判断の後は**次の未判断へ進む**（設定で切れる。既定 ON）。

### 5.2 まとまりのレビュー（`#/group/<id>`）

- フィルムストリップ＋大きな 1 枚。**枚数の上限なし**。
- `1`〜`8` は**いま見えている 8 枚**に割り当てる。9 枚以上は `←` `→` で送る（点検 B6/G8）。
- 決定は「この 1 枚に決める」または「全部ボツ」。**どちらも理由が要る**。
  - 1 枚に決める: 選んだ枚に `keep`、他は**その枚自身の理由**を選ばせる（既定は未選択）。
  - 全部ボツ: まとまりの理由を 1 つ選ぶ。枚ごとの理由は既定でまとまりの理由を写す（後から直せる）。
- 決定後は、そのまとまりの**次の未判断**へ進む。

### 5.3 比較（`#/compare?ids=a,b,c`）

- 5 つの見方: **並べる / 来歴の差分表 / 差分ヒートマップ / 同期ズーム / 似ている順**。
- **来歴の差分表を既定で出す**（`GET /api/groups/{id}/compare` が計算して返す。画面で再計算しない）。
- 差分ヒートマップは**近い 2 枚のときだけ**有効（同じ seed・派生関係・pHash 距離が閾値以下）。
  使えない組ではボタンを無効にし、**理由を 1 行で出す**。
- 「似ている順」は pHash 距離の昇順。

### 5.4 状態と印

| 状態 | 見た目 |
| --- | --- |
| 未判断 | そのまま |
| キープ | 右上に `--keep` の楔。彩度はそのまま |
| ボツ | 彩度 35% ＋ `--drop` の斜線 |
| 選択中 | 上辺に `--accent` の 2px |
| **来歴なし** | 左下に `--warn` の点（薄くしない。点検 I9） |

---

## 6. 来歴の差分表と比較の指標（サーバ側で計算する）

### 6.1 差分表

`GET /api/groups/{id}/compare` が返す:

```json
{
  "group": {"id": "...", "policy": "pick_one", "state": "open"},
  "items": [
    {"asset_id":"...", "thumb":"/api/assets/.../thumb?size=256",
     "provenance": {"model":"...","loras":[{"name":"...","strength_model":1.0}],"clip":"...","vae":"...",
                    "sampler":"...","scheduler":"...","steps":10,"cfg":1.0,"denoise":1.0,
                    "width":768,"height":1360,"seed":"338134650120909"},
     "prompts": {"ja_text":"...","en_text":"...","final_prompt":"...","final_prompt_source":"reconstructed"},
     "tags": [], "phash":"a1b2...", "review_state":"unreviewed"}
  ],
  "diff": {
    "changed": [{"key":"seed","label":"seed","values":["338...","998...","338...","998..."],"kind":"text"}],
    "same":    [{"key":"steps","label":"steps","values":["10","10","10","10"],"kind":"num"}],
    "prompt_diff": {"normalized_equal": false, "tokens": [{"t":"1girl","state":"same"},{"t":"solo","state":"added"}]}
  }
}
```

- 比較する鍵（固定の列挙）: `model` / `loras`（名前＋重み）/ `clip` / `llm` / `vae` / `sampler` / `scheduler` /
  `steps` / `cfg` / `denoise` / `width`×`height` / `seed` / `ja_text` / `en_text` / `final_prompt`。
- **正規化は 2 段**（[`comparison.md`](comparison.md) §3.2、点検 G5 で修正）:
  **段 1 = 語の同定**（大小文字・`_` と空白・カンマ前後の空白・末尾のカンマ）。
  **段 2 = 値の比較**（重み）。**重みだけが違う語は `reweighted`** として出し、「同じ」に潰さない
  （`(word:1.2)` と `word` は絵を変えるので同じではない。`comparison.md` §3.2 の「重みの表記を同一視する」は
  **この点で誤り**）。`((word))` の段数と `<lora:name:0.8>` も重みとして扱う。
  **語順だけの違いは `moved`**（追加＋削除に割らない。点検 C10）。
- `changed` を先に、`same` を畳んで返す（画面の既定の見え方に合わせる）。
- **行の状態は 4 つではない**（監査 B2 の修正で増えた）: `same` / `changed` / `reweighted` /
  `only_in_some` に加えて **`unknown`**（比べる値がどの枚にも無い）と **`incomplete`**（一部の枚にしか無い）。
  **捕獲していない英訳を前置語だけで埋めてはいけない**（「分からない」を「同じ」に見せない）。
  行に `unknown: [asset_id…]`（どれが分からないか）と `known_prefix: {asset_id: 前置語}` を添え、
  語の差分からは分からない枚を除く。**基準が分からない**ときも相手を「追加」と言わない。
- 語数が `MAX_PROMPT_WORDS`（2000）を超えたら `prompt_diff.too_long=true` にして語の差分を省く
  （行の生の文字列は残す）。**差分の計算は画像ごとに 1 回だけ**行い、語ごとに LCS を回し直さない
  （監査 B1。回数が語数に依らないことをテストで固定する）。
- **`tags` は `null`**（`[]` ではない。点検 D5。「未計算」と「無い」を区別する。P4 で埋まる）。

### 6.2 指標

| 指標 | いつ計算するか | 保存 |
| --- | --- | --- |
| `phash` / `dhash`（64bit、16 進 16 文字） | **サムネイルを作る復号と同じ 1 回**（`thumbs.ensure_thumb(on_image=...)`。実測 F5）。加えて `compare._fill_missing_hashes()` が、**そのときに比べる枚のうちまだ無い枚だけ**を比較の要求時に埋める（1 枚につき生涯 1 回） | `asset.phash` / `asset.dhash` |
| `phash_distance` | 比較の要求時（`hash_distance()` でその場で数える） | **保存しない**（64bit のハミング距離は数えた方が安い。点検 D1） |
| `ssim` / `changed_fraction` / `mean_abs` | 比較の要求時（256px へ縮小した**位置合わせ前**の 2 枚から。**組を要求されたら必ず**。近い／遠いで分けない。規則は [`comparison.md`](comparison.md) §2.3 の手順 4） | `comparison_cache`（`algo_version` を持ち、**引くときも条件に入れる**。点検 D1） |
| 差分ヒートマップの画像 | 要求時（返すだけで保存しない） | — |

- 定義は [`comparison.md`](comparison.md) §4 が正（**ここで再定義しない**）。
- **この表は点検で直した。** 以前は「`phash` / `dhash` は**走査の背景ジョブ**（8ms/枚）」「`phash_distance` は
  `comparison_cache` に保存」「`ssim` などは**近い組のときだけ**」と書いていたが、いずれも**誤り**——
  実測 F5 で背景ジョブは要らないと分かり（サムネイルの復号に同居させる）、点検 D1 で `phash_distance` の列は
  作らないと決め、実装は**遠い組でも指標を返す**。**正は §0.7・§0.8 D1**。
- 近い／遠いの門は**ヒートマップの画像だけ**に掛ける（§0.5 G6。指標には掛けない）。
- 計算は `POST /api/groups/{id}/compare/pair {a_id, b_id}` で単発にも引ける（比較画面のタイル用）。
- pHash の費用の実測は §0.7 にある（復号のみ 11.4 ms/枚 / 復号＋両ハッシュ 14.1 ms/枚 / 復号済みから
  2.38 ms/枚）。**8ms/枚 は未計測の見積り**だったもので、**1,000 枚での全件計算はまだ記録していない**
  （点検 E5）。

---

## 7. テスト（この段で必ず書く）

**台帳と現在値**

1. 追記のみ（`decision` の行が増えるだけ。更新・削除が無い）
2. 最後の判断が現在値に写る（`keep` → `rejected` → `clear` の順に入れて、その都度確かめる）
3. 再起動しても残る（`Store` を作り直して同じ現在値）
4. 写しを壊して起動したら、台帳から組み直される（件数がログに出る）

**理由**

5. ボツで理由が無ければ 422 / 存在しない・`active=0` の理由は 422
6. キープは理由なしで通る
7. `clear` は理由を無視して未判断に戻す

**まとまり**

8. `items` が全枚を覆っていないと 422（`missing` / `extra` が付く）
9. 1 枚に決めると、選ばれた枚が `keep`、他が `reject`、**全員に理由が付く**
10. 全部ボツはまとまりの理由が必須（無ければ 422）。**枚ごとの理由も残る**
11. `pick_one` で `keep` が 2 枚なら 422 / `all_reject_only` で `keep` があれば 422
12. 決定は 1 トランザクション（途中で失敗したら 1 行も入らない）
13. `decided` の後に同じまとまりへ判断が入ると `open` に戻る

**人の判断の強制**

14. `actor='agent'` の `POST /api/reviews` と `decide` が **403**（点検 A5）

**書き出し**

15. 判断のたびに**影響したまとまりのファイルだけ**が更新される（他のファイルの mtime が変わらない）
16. `generated_at` を除いて 2 回出して同一（決定性）
17. `include_tags` / `include_prompts` が既定 false。true で入る
18. スキーマ検証（`schemas/review-export.schema.json`）
19. 他ツールの観点: `groups[].decision` と `items[].group_decision` から
    「どのまとまりの、どの 1 枚に決まったか」が 1 回の読み取りで分かる

**比較**

20. 差分表が**正規化してから**比べる（末尾カンマ・大小文字・重み表記・`_` の違いを「同じ」にする）
21. 語順だけの違いを「移動」として出し、「追加」「削除」と混ぜない
22. `changed` が先、`same` が畳まれて返る
23. pHash は**性質**で固定する（**絶対値は主張しない**。点検 C15——縮小のフィルタを変えると値が動く）。
    同じ画像 → 距離 0、縮小・再圧縮した写し → 近いのしきい値以内、別の絵 → しきい値のずっと外、
    2 回計算しても同じ値、16 進 16 文字の小文字
24. 差分ヒートマップは**近い組のときだけ**有効（遠い組では 422 と理由）

**画面（ヘッドレス）**

25. 楽観的更新: 押した瞬間に印が変わり、失敗したら戻る
26. 9 枚以上のまとまりで、番号キーが見えている 8 枚に割り当たり、`←` `→` で送れる

---

## 8. 性能（この段で守る数値）

| 項目 | 目標 | 根拠 |
| --- | --- | --- |
| 判断の記録（台帳＋現在値。書き出しを除く） | **100ms 以内** | `design.md` §12.1 |
| 判断のたびの書き出し | **影響したまとまりのファイルだけ**（遅延 2 秒でまとめる） | 点検 B4 |
| 差分表（8 枚） | 30ms 以内 | `comparison.md` §7 |
| pHash の全件計算 | 1,000 枚で計測して記録（8ms/枚 は見積り） | 点検 E5 |
| SSIM（1 組） | 50ms 以内（256px） | `comparison.md` §7 |

---

## 9. 実装の形（ファイル）

```
src/image_reviewer/
  review.py       # ReviewService.apply / まとまりの決定 / 現在値の写し（P5 の中心）
  reasons.py      # 理由マスタの初期値と検証
  compare.py      # 差分表・pHash/dHash・SSIM・changed_fraction・mean_abs・ヒートマップ
  export.py       # review.json の組み立てと原子的な書き出し・遅延
  api/reviews.py  # POST /api/reviews, GET /api/reviews, /api/reason-codes
  api/groups.py   # /api/groups, decide, reopen, compare
  api/export.py   # /api/export/review.json
apps/gui/
  decisions.ts    # 判断の部品（キープ / ボツ / 理由の選択。楽観的更新）
  group.ts        # まとまりレビュー
  compare.ts      # 比較（5 つの見方）
  diff-table.ts   # 来歴の差分表
```

---

## 10. やらないと決めること

1. **点数（星）を入れない**（利用者の回答。`reason_code` の拡張として後から足せる形にはしておく）。
2. **判断を自動で付けない**（タガーや AI の推しで `keep` にしない。点検 A5）。
3. **まとまりの枚数を制限しない**（点検 B6/G8）。
4. **画面で差分を計算し直さない**（サーバが返したものを描くだけ。定義を 2 か所に持たない）。
5. **全件の書き出しを判断のたびにやらない**（点検 B4）。
6. **`decision` を消さない・書き換えない**（取り消しも追記）。

---

## 11. 確かめてほしい点（レビュアー向け）

1. **§2.1 の写しの規則**（最後の `decision` から導出・`clear` で未判断に戻す・起動時に組み直す）に、
   ずれが生まれる経路が残っていないか。
2. **§3.2 の規則が過不足ないか。** 特に「全部ボツでまとまりの理由が必須」「枚ごとの理由」で、
   利用者が詰まないか（理由を選ぶ手間が 8 枚ぶん発生しないか）。
3. **§3.1 の「ボツには理由が必須」**は厳しすぎないか（1 枚だけ素早く落としたいときに邪魔にならないか）。
   逆に、理由を必須にしないと §9.2 の「理由を必ず付ける」と矛盾しないか。
4. **§4 の書き込みの道筋。** 「書き出しの遅延」「SSE」「`decided` の `open` 戻し」の 3 つが
   互いに矛盾しないか。とくに**遅延中に落ちたとき**に書き出しが漏れないか
   （`decision.created_at > export の mtime` という判定で足りるか）。
5. **§3.4 の書き出しの範囲。** 「影響したまとまり」の定義が曖昧でないか
   （1 枚の判断でも、その画像が属する全まとまりを書く必要があるか）。
6. **§6.1 の差分表**の鍵の列挙に漏れがないか（`llm` / `init_image` / 制御入力の有無は要るか）。
   正規化の規則（[`comparison.md`](comparison.md) §3.2 に委ねている）で足りるか。
7. **§7 のテスト**で、**今すぐ要るのに無いもの**はどれか。逆に、この段では要らないものはどれか。
8. **§8 の性能目標**が、この段の作りで達成できる見込みがあるか（とくに 100ms と書き出しの遅延）。
9. **手動タグ（`manual`）をこの段で扱わない**判断（P4 に回す）は妥当か。
   §6.1 の `tags: []` が、P4 まで「タグが無い」と読まれて困らないか。
10. **§5 の画面の挙動**で、`design.md` §9.3 の「1 枚選ぶ / 全部ボツ」と食い違う点はないか。
11. **範囲（§1）**に、P5 に含めるべきなのに落としているものはないか。
    逆に、P5 に要らないものを含めていないか（とくに比較の 5 つの見方を全部この段で作る是非）。
12. **実装の形（§9）**が、既にある `src/image_reviewer/`（`png_meta.py` / `capture.py` / `scan.py` /
    `store.py` / `app.py` / `thumbs.py`）と噛み合うか。**JSON ストア（プロトタイプ）から
    SQLite へ移す作業**をこの段で一緒にやるべきか、判断してほしい。
    現状は `store.json` 1 ファイルで、台帳を載せると毎回 600 KB を書き直すことになる。
