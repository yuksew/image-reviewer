# P4-0（v5 の表と契約）監査報告 — 実行込み

- 日付: 2026-10-16（09:25〜10:05）。監査者: Fable（Claude Code）
- 指示書: `docs/p4-audit-brief-p4-0.md`（09:20）。対象: `src/image_reviewer/db.py`（09:14、`SCHEMA_VERSION = 5` / `V5_TAG_DDL` / `_migrate_v5`）、`schemas/review-export.schema.json`（09:16）、`src/image_reviewer/export.py`（09:17、`_tag_docs`）、`tests/test_db.py`（09:16）、`tests/test_export.py`（09:17）
- 設計: `docs/p4-design.md` は **09:12 版の後、09:23 に 952 行版**になった（点検の反映）。P4-0 の実装（09:14〜17）は **09:23 版より前**。§A-1 はこの時間差から出ている。
- 環境: 実データ `.data/` は `mode=ro` と **`sqlite3.Connection.backup()`** だけ（WAL 込みの複製。`db.sqlite3` だけ `cp` すると判断 3 件が抜けることも確認）。一時物は `.tmp-audit-redo/p40/`（移行の 4 経路の DB と `srv`＝タグを入れたサーバ用複製）と `.tmp-audit-redo/p4/p40_*.py`（`p40_migrate.py` / `p40_contract.py` と各 `.out.txt`）。サーバはポート 8791（停止済み）。ソースと既存の文書は編集していない。
- 実装者の記録（「自分で決めた 3 点・申し送り 5 件」）は **`docs/` に無かった**ので、指示書 §2-5 / §2-6 の列挙を記録として扱った（§H）。

---

## 判定: **P4-0 は合格（P4-1 へ進んでよい）。ただし v5 の DDL を 952 行版の設計に揃えてから。**

移行（4 経路・3 回呼び）・制約・契約の 3 欄・既定で `tags` 無し・決定性・`GET` が書かない・回帰（pytest 231 / gui_smoke 91 / gui_layout 4 画面）は**すべて実行で通った**。
残るのは **設計 §2.1（952 行版）と実装の DDL の差 2 列**（`known` の `CHECK` と `asset_tag.actor`）で、`.data` が v3 のままのいまなら v5 を直せば済む（§A-1）。

**最も重大な 3 件**
1. **v5 の DDL が 952 行版の設計 §2.1 と 2 列ずれている**（`known … CHECK (known IN (0, 1))` と `asset_tag.actor TEXT` が無い）。**実データが v3 のままの今のうちに `V5_TAG_DDL` を揃える**（v6 の `ALTER TABLE` を増やさない）。実装者の複製 `data-p40` は作り直し（§A-1）。
2. **`tags[]` の並びが設計 §0.10（カテゴリ → スコア降順 → 名前）でなく `name → source`**。決定的ではあるが規則が違う。P4-1 で API の並びと揃えるときに契約の並びも決め直す（§E-1）。§8.1-19 は `ORDER BY` を外しても落ちない（§F-1）。
3. **`INSERT OR IGNORE` の申し送りは 952 行版で `INSERT … ON CONFLICT(name) DO UPDATE` に変わった**（`tag.known` が古くなる経路。点検 §I）。テストの docstring（`test_asset_tag_keeps_the_three_sources_apart`）も「`INSERT OR IGNORE` / `REPLACE`」と書いており、**P4-1 がそのまま読むと `known` が狂う**（§B-1）。

---

## A. 直っていない／設計と食い違う（必ず直す）

### A-1. `V5_TAG_DDL`（`db.py:403-457`）に 952 行版 §2.1 の 2 列が無い
- 設計（`p4-design.md` 389 行）: `known INTEGER NOT NULL DEFAULT 0 CHECK (known IN (0, 1))`。実装: `CHECK` 無し（`db.py:409`）。
- 設計（409 行）: `asset_tag.actor TEXT`（手動で付けた人。後でエージェントにも許すときの移行を避けるため**今**足す。点検 §I-4）。実装: 列が無い（`db.py:411-419`。列は `asset_id, tag_id, score, source, model, tagged_at`）。
- 残りの表・索引は**一致**（`job` / `job_item` / `tag_gloss` / 索引 5 本を文面で突き合わせた。差は改行だけ）。
- **直し方**: `V5_TAG_DDL` に 2 列を足し、`test_migrate_v5_creates_the_tag_and_job_tables` に `actor` 列と `known` の `CHECK` を足す。**`.data/db.sqlite3` は `user_version=3` のまま**（`mode=ro` で確認）なので、v5 を書き換えても本番の DB に二度当てる問題は起きない。**ただし設計 §0.2 のとおり「サーバを次に `.data` で起動したとき」に v5 が当たる**ので、**次の起動より前に**直す。間に合わなければ v6（`actor` は `ALTER`、`CHECK` は表の作り直し）。ただし **`.tmp-audit-redo/data-p40`（v5 済み）は `IF NOT EXISTS` で素通りして列が足りないまま**になる → 作り直す。もし v5 を「出荷済み」と見るなら v6 で `ALTER TABLE asset_tag ADD COLUMN actor TEXT`（`CHECK` は `ALTER` で足せないので表の作り直しになる）。**今直す方が安い**。

---

## B. 重大

### B-1. 申し送り「サービス層は `INSERT OR IGNORE`」は設計の改訂で**無効**
- `tests/test_db.py:452-460` の docstring と、指示書 §2-6 の申し送り 2 は `INSERT OR IGNORE` / `REPLACE` を勧める。952 行版 §2.1（392-396 行）は **`INSERT … ON CONFLICT(name) DO UPDATE SET known = max(known, excluded.known)`** と**ジョブ開始時の引き直し**を要求する（`INSERT OR IGNORE` だと `known=0`・`category=NULL` が残る。点検 §I-1 で実行再現）。
- `asset_tag` 側の主キー衝突は `INSERT OR IGNORE` で正しい（出所ごとの行は 1 つ。実行で 2 回目が `IntegrityError`、`OR IGNORE` で通ることを確認）。**`tag` と `asset_tag` で使う形が違う**ことを申し送りに書き直す。

### B-2. `job.kind` に `CHECK` が無い／`job_item.state` の語彙が未定（実装者の決定 2・申し送り 3）
- 実行: `INSERT INTO job(kind='bogus')` → **通る**。`job_item(state='whatever')` → **通る**。
- 設計 §2.1 は `job.kind` を `-- 'scan' | 'thumbnail' | 'tag' | 'extract' | 'hash' | 'export'` のコメントで示すだけで `CHECK` を書いていないので、**実装は設計どおり**。ただし `job.state` と `asset_tag.source` には `CHECK` を付けた方針（§0.10「語彙は DB でも守る」）と**不揃い**。`kind` は将来増える語なので `CHECK` 無しでよいが、**`job_item.state` は P4-1 で語彙を決めたら `CHECK` を v6 で足す**か、今 `('queued','done','failed','skipped')` で縛る。**P4-1 に持ち越してよい**（表が空のうちは `ALTER` 不要で作り直せる）。

---

## C. 中程度

### C-1. `gloss_edited` は語釈が無いとき `null`（実装者の決定 1）
- 実行: 語釈の無い語は `gloss: null, gloss_edited: null`、自動の語釈は `false`、人が直した語は `true`（`p40_contract.out.txt`）。契約は `["boolean", "null"]`。**妥当**（「語釈が無い」と「自動」を区別できる）。

### C-2. テストの足場 `_add_tag()`（実装者の決定 3）
- `tests/test_export.py:913-924`。P4-1 でサービスが入ったら**そちらに置き換える**前提なら妥当。ただし足場は `INSERT INTO tag` を素で打つので、**P4-1 の正規化（`\(` のエスケープ外し・小文字化）を通らない**。`test_tags_carry_gloss_known_and_the_official_spelling` は `rem_\(re:zero\)`（エスケープ形）を入れて**そのまま出ること**を確かめているが、P4-1 以降は**正規形 `rem_(re:zero)` で入る**ので、このテストの期待値は P4-1 で変わる。今は「DB は文字列をいじらない」の確認として意味がある。

### C-3. `_tag_docs` は 1 枚 1 クエリ（申し送り 4）— **P4-1 に持ち越してよい**
| 何 | 実測 |
| --- | --- |
| クエリ単体（263 枚・17,625 行） | 22 ms（1 枚 0.08 ms） |
| HTTP `GET …?scope=all`（`include_tags` 無し / あり） | 9 ms / 123 ms（差 114 ms = 1 枚 0.43 ms。JSON 2.8 MB） |
| 10,000 枚の見積り（66 行/枚） | クエリ 0.8 s、組み立て込みで **約 4.3 s**。JSON は **約 110 MB**（設計 §10-14 の「100 MB 規模」と一致） |
| `scope=asset:` 1 枚 | 2 ms |

- 計画は `asset_tag` の主キー索引 → `tag` の rowid → `ORDER BY` の一時 B 木。1 万枚でも**数秒**で、問題は時間ではなく**ファイルの大きさ**（`include_tags` の既定 `false` で守られている）。**1 枚 1 クエリのままでよい**。JOIN を 1 本にするのはカタログの段で。

### C-4. 実装者の複製 `data-p40` の WAL（申し送り 5）
- `.data/` は `db.sqlite3`（1.0 MB）＋ `-wal`（0.26 MB）。**`cp` だけだと判断 0 件**、`backup()` なら 3 件（実行で確認）。`data-p40` も `-wal` 0.33 MB を持つので、**複製するときは毎回 `backup()`**。監査の手順（記憶）に入れた。**持ち越しは不要**（手順の問題）。

---

## D. 軽微

1. **移行**: 確かめた結果、問題なし。v0（`open_db` 新規）/ v1（`DDL` + `user_version=1`）/ **v3（実データの `backup()` 複製）**/ v4（v3 複製に `_migrate_v4` を当てて `user_version=4`）の **4 経路の `sqlite_master`（表・索引・SQL 文面）が完全一致**。各 3 回呼んで `5`。`superseded_by` 列は 1 つ（`ALTER` を二度当てない）。v3 複製は移行後も **263 枚・判断 3 件**、`integrity()` = `quick_check ok / foreign_key_violations 0 / schema_version 5 / wal`。`open_db`（起動の経路）でも v5。
2. **制約**: 確かめた結果、問題なし。`tag.name` は `rem_(re:zero)` と `rem_\(re:zero\)` が**別の語として入り**、同名 2 回目は `UNIQUE` で落ちる。`known` の既定は **0**。`asset_tag` は `png` / `wd14` / `manual` の 3 行が入り、同じ組の 2 回目は落ちる。`source='x'` は `CHECK`、無い `asset` は FK。`tag_gloss.edited` の既定 0、同じ `tag_id` 2 回目は落ちる、`source='dict'` は `CHECK`（テスト）。`job.state='paused'` は `CHECK`。`job` 削除で `job_item` が消え、`tag` 削除で `tag_gloss` が消え、参照のある `tag` は FK で消せない。
3. **契約**: 確かめた結果、問題なし。`include_tags=true` の **`all` / `group:` / `asset:` の 3 文書**と既定の文書が**本物の `jsonschema`（Draft 2020-12）で通る**。`Tag` の鍵は `name / category / category_name / score / source / known / gloss / gloss_edited` の 8 つで、**`known` は true/false の両方、`gloss` は 259 行、`gloss_edited` は null/false/true の 3 値が実際に出た**。括弧の語 `2b_(nier:automata)` / `star_(symbol)` と `:d` がそのまま出る。既定では **`tags` の鍵ごと無い**（`prompts` も）。`abi` は `0.1` のまま。
4. **古い読み手**: `known` / `gloss` を知らない `Tag`（`additionalProperties: false`）で検証すると **`include_tags=true` の文書は落ちる**（"Additional properties are not allowed"）。`additionalProperties` を見ない読み手なら通る。既定の文書は厳密な旧読み手でも通る。設計 §0.12 の「足すだけなので壊れない」は**厳密な読み手には当てはまらない**。`abi` を上げないなら、契約の `description` に「0.1 の読み手は `Tag` の未知の鍵を無視すること」を 1 行足す（§E-2）。
5. **決定性**: 確かめた結果、問題なし。`GET` 2 回（`generated_at` 除く）一致、`POST all` 2 回のファイルも一致。
6. **`GET` は書かない**: 確かめた結果、問題なし。`GET /api/export/review.json`（4 種）の前後で `srv/` のファイル（名前・mtime・size）が同一、`export/` は作られない。`POST group:` もファイルを書かない。`POST all` だけが `export/review.json`（4.7 MB、tags 込み）を書く。
7. **回帰**: `uv run pytest -q` → **231 passed**（`tests/.tmp` の残骸 18 個は前からのもの）。`node tools/gui_smoke.mjs` → **91 ok**。`gui_layout --count 8` / `--screen requests` / `--screen group` / `--screen asset` → **すべて ok**（`srv` 複製、要求を 1 つ作って）。P5 / P6 の口（`/api/assets` / `/api/review-requests` / 注記）は触れておらず、既定の文書の鍵は `abi / generated_at / scope / assets / groups / requests / reason_codes / schema` のまま。
8. `tests/test_export.py` の `check_contract` は自前の検査だが、**余計な鍵・型違い・enum 外・`gloss_edited` の数**の 4 つを本物の `jsonschema` と同じく落とした（実行で確認）。

---

## E. 設計とのずれ

1. **`tags[]` の並び**: 実装は `ORDER BY t.name, a.source`（`export.py:513`）。設計 §0.10（176 行、952 行版では 266 行付近）は「カテゴリ（4 → 0 → その他）→ スコア降順 → 名前」。契約の `description` には並びの規則が無い。実装者は `name → source` を「決定性」のために選んだと `_tag_docs` の docstring に書いている（設計が黙っていた所を決めた）。**契約の並びは `name → source` で良い**（読む側が辞書順で見つけやすい）が、**設計 §6.1 にそう書き、§0.10 の規則は API の応答（画面の並び）に限る**と明記する。
2. **古い読み手**（D-4）: §0.12 / §6.2「足すだけなので壊れない」は、`Tag` の `additionalProperties: false` を使う厳密な読み手には当てはまらない。契約の `description` に 1 行。
3. **DDL の 2 列**（A-1）。
4. `_tag_docs` の `gloss_edited` を `null` にする規則（C-1）は設計 §6.1 に無い（契約の description にはある）。設計にも 1 行。
5. 契約の `known` は `["boolean", "null"]` だが、設計 §6.1 は「真偽」、`_tag_docs` は `bool(...)` しか出さない。`null` を許す意味（語彙の判定がまだ無い？）が無いなら `boolean` だけにする。P4-1 が `null` を出し始めないように 1 行。

---

## F. テストで守れないもの

| テスト | 判定 | 根拠 |
| --- | --- | --- |
| §8.1-17（`test_migrate_v5_creates_the_tag_and_job_tables`） | **落ちる形** | `_migrate_v5` を外せば `tag` が無く落ちる。v1 → v5 と v4 → v5 の両方。ただし **v3 の実データの形**（`backup()` の複製）は見ていない。CI で実データは使えないので、代わりに「v3 の DDL 相当（`_migrate_v2` + `_v3` まで）から」を足すとよい |
| §8.1-18（`test_tags_carry_gloss_known_and_the_official_spelling`） | **落ちる形** | `_tag_docs` から `gloss` / `known` / `gloss_edited` のどれを外しても `assert` で落ちる。語釈を 1 語入れてから見ている（P6-0 の B1 の型は塞がっている） |
| §8.1-19（`test_tags_are_absent_by_default_and_deterministic`） | **並びは守れない** | `ORDER BY` を外しても SQLite は同じ DB から同じ順で返すので 2 回の比較は一致する（実行で確認: `ORDER BY` 無しで 2 回同じ、名前順ではない）。**「`name → source` の並びそのもの**」を期待値で固定する（18 番のテストが `[(long_hair,png),(long_hair,wd14),…]` で既に固定しているので、合わせて 1 本にできる） |
| `test_tag_name_is_unique_and_keeps_the_official_spelling` | 落ちる形 | `UNIQUE` を外せば落ちる。`Long_Hair` が別の語として入ることも固定（小文字化はサービス層） |
| `test_asset_tag_keeps_the_three_sources_apart` | 落ちる形 | 主キー・`CHECK`・CASCADE を見ている。docstring の `INSERT OR IGNORE` は B-1 |
| `test_tag_gloss_keeps_the_edited_flag` | 落ちる形 | 既定 0 と `source` の `CHECK` |
| `test_job_state_is_constrained_and_items_cascade` | 落ちる形。**`kind` と `job_item.state` は見ていない**（B-2） | |
| 契約の検証 | 自前の `_check` だが 4 種の壊し方で落ちた（D-8） | 本物の `jsonschema` は `tools/check_contract_p6.py` 相当で別途 |

---

## G. 依頼者への質問（推奨つき）

| # | 論点 | 選択肢 | 推奨 |
| --- | --- | --- | --- |
| G-1 | DDL の 2 列をどう入れるか | (a) **v5 を書き換える**（`.data` は v3 のまま。複製は作り直し）／(b) v6 で `ALTER`（`CHECK` は付けられない） | **(a)**。v5 を使った本番 DB はまだ無い |
| G-2 | `tags[]` の契約の並び | (a) **`name → source`**（実装）／(b) §0.10 の規則（カテゴリ → スコア → 名前） | **(a)**。契約は突き合わせやすい辞書順、画面は §0.10。設計 §6.1 に書き分ける |
| G-3 | `job_item.state` の語彙 | (a) P4-1 で決めてから `CHECK`／(b) 今 `('queued','done','failed','skipped')` で縛る | **(b)**。表は空なので今なら `CREATE` を直すだけ。設計 §4.1 の `counts.skipped` に合う |
| G-4 | 厳密な旧読み手への手当て | (a) 契約の `description` に「未知の鍵は無視」／(b) `abi` を `0.2` に | **(a)**。`abi` の description に「実装までの変更では版を上げない」とある |

---

## H. 確かめられなかったこと

- 実装者の「自分で決めた 3 点・申し送り 5 件」の**原文**（`docs/` に無い）。指示書の列挙を正として判定した。
- `job` の**動き**（P4-0 では表だけ。ワーカー・409・中断は P4-1）。
- P4-1 の正規化を通した後の `rem_\(re:zero\)` の扱い（C-2）。
- 10,000 枚の `include_tags` は**見積り**（263 枚の実測から比例）。
- 複製 `data-p40` を実装者がどう作ったか（`backup()` と言っているが確かめていない。`-wal` が 0.33 MB あるので複製後に書いている）。
- 証拠の注記: `p40_migrate.out.txt` の「known の既定: 1」は**私のスクリプトが `known=1` を明示して入れた行**の値で、既定の証拠ではない。既定 0 の証拠は `p40_known_default.out.txt`（`INSERT INTO tag(name)` だけで入れて `known=0`）と pytest の `test_tag_name_is_unique_and_keeps_the_official_spelling`。
- 後始末: `.tmp-audit-redo/p40/` に移行の 4 経路の DB（`v0` / `v1` / `v3` / `v3-open` / `v4` / `v3-cp-only`）と `srv/`（タグ 17,625 行、`export/review.json` 4.7 MB）が残っている。サーバ 8791 は停止。`.data` の mtime は 10-15 のまま。`src/` に私の時刻の変更は無い（`db.py` 09:14 は実装者）。`uv run` は実装者のサーバが `.venv` の `image-reviewer.exe` を掴んでいる間は `--no-sync` が要る（監査の最後に 1 回ぶつかった）。

### 実行したコマンドと結果（主なもの）

```
uv run pytest -q                                           → 231 passed
node tools/gui_smoke.mjs                                   → 91 ok
uv run python .tmp-audit-redo/p4/p40_migrate.py            → v0/v1/v3(backup)/v4 → 5、sqlite_master 完全一致、263 枚・判断 3 件・integrity ok、制約 24 項目
uv run --with jsonschema python .tmp-audit-redo/p4/p40_contract.py
                                                           → 既定に tags 無し、3 文書が契約 OK、8 鍵、known/gloss/gloss_edited が実際に出る、
                                                             旧 Tag（厳密）では落ちる、GET ×2 一致、GET は書かない、all 9/123 ms、asset 2 ms
POST /api/export/review.json {scope:all, include_tags:true} ×2 → ファイル 4.7 MB、generated_at 以外一致、契約 OK
node tools/gui_layout.mjs --count 8 / --screen requests / --screen group --group … / --screen asset --ids …  → すべて ok
sqlite3 (mode=ro) .data/db.sqlite3                         → user_version 3、asset 263、decision 3（cp だけの複製では decision 0）
```
