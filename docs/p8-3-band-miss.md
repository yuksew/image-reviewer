# P8-3 重複の「取り落とし」の調査と直し（**帯の取りこぼしではなかった**）

- 日付: 2026-10-18（JST 05:50〜07:05）
- 立場: **実装者**（P8-3 の実装と P8-1 の監査 B-1 の直しを書いた側）
- 対象: `GET /api/duplicates/near?max_distance=6` が実データで **20 群 / 55 枚**を返し、
  総当たりの **21 群 / 57 枚**と食い違った件
- 正: [`p8-design.md`](p8-design.md) §0.5（帯索引）・§0.10（除外と解除）・§3.1（口）、
  [`p8-1-audit-report.md`](p8-1-audit-report.md) B-1、[`p8-1-audit-triage.md`](p8-1-audit-triage.md) B-1
- 鉄則: **実データ `.data/` は `mode=ro` でしか開いていない**。**画像を 1 枚も動かしていない**。
  `git` のコミットはしていない。**`README.md` と `docs/design.md` は触っていない**。
  **利用者のアプリ（8790）を止めていない**（読んだだけ）。`uv run` は使わず `.venv\Scripts\python.exe` 直呼び。

---

## 1. 結論（先に 5 行）

1. **落ちていたのは 1 組**: `01M4Z0KJR893495T88VC0V90E5` ↔ `01M4Z0KJS89CAB2T0QNT1WAVPF`（**距離 4**）。
2. **原因は帯ではない。** `duplicate_exclusion` の**1 行**（「別物として確定」）がその組を隠していた。
   **帯は 1 組も落としていない。**
3. 帯は健全: **4208 行 = 263 × 16**、`asset.phash` と**行ごとに一致**（食い違い 0 枚）、
   **0〜64 の全 65 距離**で「帯の候補 = 総当たり − 除外」。
4. つまり **API の 20 群 / 55 枚は正しかった**（人の「別物」が効いている）。
   21 群 / 57 枚は**除外を引かずに数えた数**。
5. **穴は「見分けが付かないこと」だった**（API も画面も「除外で隠れている」と言わない）。
   `total_pairs` / `excluded_pairs` と画面の 1 行を足し、`probe` の突き合わせから除外を引く形に直した。

**「P8-1 の B-1 の直しが実データで取りこぼした」のではない。** B-1 の直し（4bit × 16 本＋16 以上は総当たり）は
効いている。実データで起きたのは**別の機能（人の除外）が数を変えた**ことで、それを
**帯の取りこぼしと読み違える形**になっていた。

---

## 2. 診断（すべて実行した値）

### 2.1 総当たり・帯・API の突き合わせ（実データ `.data`・v6・263 枚）

台本: `.tmp-audit-redo/p8-3-band-miss/diag.py`（`mode=ro`。1 バイトも書かない）。

| 距離 | 総当たり（`asset.phash`） | `candidate_pairs`（帯） | 差 | API（`near_groups`） |
| --- | --- | --- | --- | --- |
| ≤0 | 9 組 | 9 組 | **0** | 5 群 / 12 枚 |
| ≤3 | 27 組 | 27 組 | **0** | 17 群 / 39 枚 |
| ≤6 | 54 組 | **53 組** | **1** | 20 群 / 55 枚 |
| ≤10 | 88 組 | **87 組** | **1** | 28 群 / 86 枚 |
| ≤15 | 190 組 | **189 組** | **1** | 33 群 / 142 枚 |

- **帯の行は健全**: `phash_band` **4208 行**（263 × 16 ちょうど）・`asset.phash` と
  **食い違う枚 0 / 帯が 1 行も無い枚 0**（全 263 枚を `bands_of(phash)` と行ごとに突き合わせ）。
- **帯の候補そのものは 0〜15 で取りこぼし 0**: 帯だけの SQL（`ba.band = bb.band AND bb.value = ba.value`）を
  診断側で組み直すと、≤0 / ≤3 / ≤6 / ≤10 / ≤15 の**どれも総当たりと一致**する（差 0）。
  ≤32 / ≤64 で「取りこぼし」に見えるのは**帯の保証（≤15）の外**で、
  実装は 16 以上を総当たりに落とすので問題にならない（≤16 の実装値 325 = 総当たり 326 − 1）。
- **落ちている 1 組の正体**: `duplicate_exclusion` の 1 行だけが原因（2.3）。

### 2.2 除外を消した複製では期待どおり（決定打）

台本: `.tmp-audit-redo/p8-3-band-miss/proof_copy.py`（複製は `sqlite3` の `backup()`）。
**複製から `duplicate_exclusion` の 1 行を消しただけ**で:

| 距離 | 除外あり（いまの実データ） | 除外を消した複製 | 親が期待した数 |
| --- | --- | --- | --- |
| ≤0 | 5 群 / 12 枚 | **5 群 / 12 枚** | 5 / 12 ✔ |
| ≤3 | 17 群 / 39 枚 | **17 群 / 39 枚** | 17 / 39 ✔ |
| ≤6 | 20 群 / 55 枚 | **21 群 / 57 枚** | 21 / 57 ✔ |
| ≤10 | 28 群 / 86 枚 | **28 群 / 87 枚** | 28 / 87 ✔ |

**差はこの 1 行だけ**（他の表・他の行は 1 つも変えていない）。取りこぼしは 0 組になる。

### 2.3 隠していた 1 行と、その 2 枚

```
duplicate_exclusion: a_id=01M4Z0KJR893495T88VC0V90E5
                     b_id=01M4Z0KJS89CAB2T0QNT1WAVPF
                     reason=NULL / actor='human' / at='2026-10-17T20:19:38Z'（JST 2026-10-18 05:19:38）
```

| | pHash | 距離 | 違う帯 | 一致する帯 |
| --- | --- | --- | --- | --- |
| `01M4Z0KJR893495T88VC0V90E5` | `ce3949e3a487d392` | **4** | 3 / 5 / 6 / 9（各 1 bit） | 12 本 |
| `01M4Z0KJS89CAB2T0QNT1WAVPF` | `ce3841f3a687d392` | | | |

- この 2 枚は**同じ絵の作り直し**（片方の `asset_meta` の `init_image` が**もう片方のファイル名**
  `e75f5f753acf478f.png`）。1024 × 1024。**距離 4** なので帯では必ず候補になる（実際なっている）。
- 除外は `candidate_pairs` の中で外れる（§0.10 の仕様どおり）。群は**連結成分**なので、
  **2 枚だけの群は辺が 1 本消えると群ごと消える**（20 群 / 55 枚 = 21 群 / 57 枚 − この 1 組）。

### 2.4 いつ・誰が書いた形か（分かる範囲）

- 2026-10-17T20:19:02Z に `POST /api/groups`（題名 `重複の候補（距離 0・2 枚）` = **`duplicates.js:274` の文言そのもの**）
  → `export/groups/01M55R95PD89SR1EVB0JT480G2.json` が 20:19:05Z に書かれている。
- 20:19:06Z / 20:19:08Z に `thumbs/` が書かれている（画面がサムネイルを読んだ）。
- 20:19:38Z にこの除外（`reason` なし＝画面の `excludePair` が送る形と同じ）。
- **同じ時刻に動いていた他の書き込みは無い**（`decision` / `job` / `delete_request` / `deletion_log` /
  `pending_delete_preview` の全部で 0 行）。リポジトリのファイルも 04:43 から 05:56 まで 1 つも変わっていない。
- `%TEMP%` に**新しい `gui-layout-*`（Chrome のプロファイル）は無い**（最後は 04:39:57）→
  **`gui_layout.mjs` の実行ではない**（あれは毎回プロファイルを作る）。
- 8790 のサーバは **05:21:35 に起動**し直している（いまの PID 35136）。
- → **画面（GUI）から押された形**。人が押したのか、誰かが HTTP で同じ形を叩いたのかは**DB からは決まらない**。
  `reason` が無いので**私の probe の除外テスト（`reason="probe"`）ではない**。

---

## 3. 原因（なぜ「帯の取りこぼし」に見えたか）

| 層 | 起きていたこと | 直し方 |
| --- | --- | --- |
| 実装（`duplicates.py`） | 除外を外すのは**仕様どおり**（§0.10）。ただし**外した数をどこにも出していない** | `excluded_pair_count` を足し、`near` が `total_pairs` / `excluded_pairs` を返す |
| 道具（`probe_p8.py`） | 総当たり（`asset` を読むだけ）は**除外を知らない**ので、`candidate_pairs` と比べると**除外 1 組が「取りこぼし 1 組」に見える**。しかも既定は 8 段の距離だけ | 総当たりから**除外を引いて**比べる。既定を **0〜64 の全部**に。群の数も**総当たりから出した数**と比べる |
| 画面（`duplicates.js`） | 見出しが「候補 20 群 ・ 55 枚」としか言わない | 「**別物として確定で 1 組を隠しています**」を足す（0 のときは出さない） |
| 試験 | **実データと同じ形**（263 枚・同じ pHash）で「帯 = 総当たり」を見る試験が無かった | `tests/test_duplicates_real_shape.py` を足した |

**「帯の候補 = 総当たり」を API でも確かめられる**ようにしたのが要点:
`total_pairs + excluded_pairs` が**その距離の総当たりの組数**になる（`excluded_pairs` は
「その距離でなら候補に入っていたのに、除外で隠れている組」だけを数える。遠い除外は数えない）。

---

## 4. 直した物（ファイルと行数）

```
$ git diff --stat
 apps/gui/duplicates.js           |  10 +++-
 docs/frontend-design.md          |   1 +
 src/image_reviewer/duplicates.py |  31 ++++++++++
 tools/gui_smoke.mjs              |  11 ++++
 tools/probe_p8.py                | 120 +++++++++++++++++++++++++++++++--------
 5 files changed, 149 insertions(+), 24 deletions(-)
 （新規: tests/test_duplicates_real_shape.py 367 行。`docs/p8-3-band-miss.md` がこの文書）
```

| ファイル | 何をしたか |
| --- | --- |
| `src/image_reviewer/duplicates.py` | **`excluded_pair_count(con, max_distance)`** を新設（除外のうち、その距離でなら候補に入っていた組の数）。`near_groups` が **`total_pairs` / `excluded_pairs`** を返す（`近い順` などの既存の欄はそのまま） |
| `tools/probe_p8.py` | 総当たりから**除外を引いて**比べる（`excluded_edges`）・**既定を 0〜64 の全部**に（`--distances` で絞れる）・群の数を `groups_of`（総当たり側の連結成分）と比べる・`total_pairs + excluded_pairs` の辻褄も見る・復号 0 枚のときの「−263 枚で 116 ms/枚」という**嘘の数字**を直した |
| `tests/test_duplicates_real_shape.py`（新規） | **実データと同じ 263 個の pHash**を埋め込んだ合成 DB。5 本（§5） |
| `apps/gui/duplicates.js` | 見出しに「別物として確定で N 組を隠しています」（`excluded_pairs` が 0 なら出さない） |
| `tools/gui_smoke.mjs` | 検査 2 本（隠れている組の数を出す／0 なら出さない）。**205 → 207 件** |
| `docs/frontend-design.md` | §6 に 1 行（文言を先に書く家風） |

**触っていない物**: `README.md`・`docs/design.md`・`schemas/`・`db.py`（**帯の DDL も移行も変えていない**）。

`near` の応答に**欄を足しただけ**（消した欄は無い）。`docs/p8-design.md` §3.1 と `docs/design.md` §16.x への
1 行は**触っていない**（約束の外なので、次の段か親で）。

---

## 5. 壊すと落ちる（自分で壊して確かめた）

台本: `.tmp-audit-redo/p8-3-band-miss/mutants.py`（実物の `duplicates.py` を 1 か所ずつ壊し、
`tests/test_duplicates_real_shape.py` を回して戻す。前後で sha256 一致＝`3eb8a141e532d58b`。
毎回 `duplicates.*.pyc` を消す）。

| 壊し方 | 落ちた試験 |
| --- | --- |
| 帯の切り出しが **64bit の前半 8 文字しか見ない**（`bands_of`） | `test_the_bands_look_at_all_sixty_four_bits` |
| 帯を **1 本書かない**（`write_bands` が最後の 1 本を落とす） | `test_the_band_candidates_equal_the_brute_force_at_every_distance`・`test_the_bands_look_at_all_sixty_four_bits` |
| 除外を**距離を見ずに**数える | `test_the_excluded_count_only_counts_pairs_within_the_distance` |
| 応答から `total_pairs` / `excluded_pairs` を落とす | 3 本（API の群・実データの除外・数の辻褄） |
| **帯の窓を 1 つ回す**（`(i+1) % 16`） | **落ちない（等価変異。それが正しい）** |

- **等価変異の話**: 帯の窓を 1 つ回すのは**帯の名前に数を付け替えるだけ**で、
  「同じ桁で一致する組」は同じだけ候補になる（最初これを「穴」と読みかけた）。**落ちないのが正しい。**
- **実データの形だけでは「64bit の一部しか見ない」穴は捕まらない**（実行値: 実データの
  距離 ≤15 の **190 組は全部が前半 8 文字のどれかでも一致する**ので、前半だけ見ても取りこぼし 0。
  取りこぼすのは距離 16 の 1 組だけだが、16 以上は総当たりに落ちる）。
  だから**鳩の巣の境界**を 1 組置いた: `0000000000000000` と `8888888888888880`
  （**距離 15・一致する帯は 15 本目だけ**）。これで初めて落ちる。
- **データ側の変異**（`.tmp-audit-redo/p8-3-band-miss/missing_row.py`）:
  - **実データの形では、帯を 1 行消しても取りこぼしが出ない**。距離 14/15/16 の組数は **65 / 0 / 136** で、
    **距離 15 の組が 1 組も無い**（＝「一致する帯が 1 本だけ」の組が無い。≤14 は一致する帯が 2 本以上あるので
    1 行消しても当たる）。実行値: 距離 0 の組の帯 0 を 1 行消しても **≤6 の候補は 54 → 54 組**。
  - 境界の組（距離 15）で**その 1 行を消すと取りこぼし 1 組**が出る（`test_..._at_every_distance` が落ちる形）。
  - そのあと**開き直すと `rebuild_stale_bands` が「16 本でない枚」を数え直して直す**
    （帯 4239 → 4240 行・取りこぼし 0 に戻る）。**1 行の欠けは起動で自己修復する。**

---

## 6. 検証（三点セット）

```
.venv\Scripts\python.exe -X utf8 -m pytest -q -p no:cacheprovider   → 408 passed（24.25 s。**403 + 5**）
node tools/gui_smoke.mjs                                            → ok 207 / NG 0（**205 + 2**）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen duplicates   → 3 窓すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending      → 3 窓すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags         → 3 窓すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <1 枚>  → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>  → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8             → すべて ok（3 窓）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests     → すべて ok
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs         → すべて ok
```

- **既存の 403 件は 1 件も落ちていない**（足したのは 5 件）。
- **`gui_layout` の注意（前から）**: **素の実データの複製だと 3 画面が NG になる**（私の変更とは無関係の**データ依存**）。
  - `--screen duplicates` は**除外の理由が `<script>alert(1)</script>`** であることを見る（道具の作り物。
    実データの除外は理由なし）。
  - `--screen pending` は**段 3 の保留が 1 件**要る（実データには 0 件）。
  - `--screen tags` は **`known=1`（語彙の語）の行**が要る（`tags.py` の既定。実データの `tag` は 0 行）。
  - 複製にこの 3 つを用意して（`setup_srv.py` / `make_copy_show.py`。**保留の実体は複製**）8 画面とも ok。
    素の複製のログは `.tmp-audit-redo/p8-3-band-miss/layout.log`、整えた後のログは `layout2.log`。
- `probe_p8.py --duplicates`（**0〜64 の 65 段**）: **すべて OK**（帯 47〜54 ms / 総当たり 2〜13 ms。
  ≤4 から除外 1 が効き、どの距離でも「帯 = 総当たり − 除外」）。

### 実データで確かめた数（**読むだけ**）

| 距離 | 実データ（`mode=ro`・除外 1 行あり） | 除外なしの複製 | 総当たり |
| --- | --- | --- | --- |
| ≤0 | 5 群 / 12 枚（組 9 + 除外 0） | 5 / 12 | 9 組 |
| ≤3 | 17 群 / 39 枚（組 27 + 除外 0） | 17 / 39 | 27 組 |
| ≤6 | **20 群 / 55 枚（組 53 + 除外 1）** | **21 / 57** | 54 組 |
| ≤10 | 28 群 / 86 枚（組 87 + 除外 1） | 28 / 87 | 88 組 |

- **8790（利用者のアプリ）は変更前のコードで動いている**ので、`GET /api/duplicates/near?max_distance=6` は
  いまも **20 群 / 55 枚**を返し、`total_pairs` は出ない（再起動すると出る）。**私は止めていない。**
- 実データの署名（調査の前後で同じ）: `db.sqlite3` 1,544,192 バイト / 2026-10-18 00:07:26、
  `db.sqlite3-wal` 4,190,072 / 05:19:38、`db.sqlite3-shm` 32,768 / 05:21:35。**画像は 1 枚も動かしていない。**

---

## 7. 実データに手を入れる必要があるか

**帯の埋め直しは要らない。**（4208 行 = 263 × 16・`asset.phash` と行ごとに一致・全距離で取りこぼし 0。
帯は `asset.phash` からいつでも引き直せるうえ、**1 行欠けても起動時の `rebuild_stale_bands` が直す**。）

**親に相談すべき点は 1 つだけ**: `duplicate_exclusion` の **1 行**（2026-10-17T20:19:38Z）をどう扱うか。
**私は消していない**（実データは `mode=ro` のみ）。

| 判断 | すると | 根拠 |
| --- | --- | --- |
| **(a) 利用者の「別物として確定」なら、何もしない** | API は **20 群 / 55 枚**のまま（これが正しい）。画面にも「別物として確定で 1 組を隠しています」と出る（再起動後） | §2.3・§2.4 の形（画面から押された形・`actor='human'`・対象は img2img の 2 枚） |
| **(b) 調査や道具の残骸なら、解除する** | **複製で確認済み**: この 1 行を消すと **21 群 / 57 枚・17/39・5/12・28/87** に戻る | §2.2 |

解除する口（**人だけ**。私は実行していない）:

```
POST /api/duplicates/exclude/remove
{"a_id": "01M4Z0KJR893495T88VC0V90E5", "b_id": "01M4Z0KJS89CAB2T0QNT1WAVPF"}
（ヘッダ X-Image-Reviewer-Actor: human）
```

帯を作り直す手順（**今回は不要**。将来 `phash_band` を疑うときのために書く）:

```
1. 実データを mode=ro で開き、backup() で複製を作る
2. 複製で「行ごとの照合」: 各枚の phash_band の (band, value) が bands_of(asset.phash) と同じか
3. 直すなら `Store(複製)` を開く（起動時の _top_up_v6 が rebuild_stale_bands + fill_missing_bands を回す）
   —— 16 本でない枚を数え直し、帯が 1 行も無い枚を埋める。**何度呼んでも同じ**
4. それでも直らない（値が古い 8bit のまま等）なら `DELETE FROM phash_band` → もう一度開く（全部埋め直す）
5. 実データに当てる前に、複製で「API の群と枚 = 総当たり − 除外」を確かめる（§6 の表）
```

---

## 8. 申し送り・設計の穴

1. **`near` の応答に 2 欄を足した**（`total_pairs` / `excluded_pairs`）。契約 schema ではなく口の応答なので
   `abi` は上げていない。`docs/p8-design.md` §3.1 の表と `docs/design.md` §16.x に 1 行ずつ足すのは
   **次の段か親で**（私は `design.md` を触らない約束）。
2. **`total_groups` は `limit` で切った後の数**（前からの意味。実データでは `limit` を 100 にしても 1000 にしても
   20 群だったので、件数の上限は効いていない）。全数が要る人は `total_pairs` を見る。
3. **`unhashed` は帯だけ欠けた枚を数えない**（P8-3 の記録の「設計の穴 2」のまま。今回は触っていない）。
4. **`probe_p8.py` の総当たりは除外を引く形にした**ので、除外のある DB でも嘘の NG が出ない。
   逆に、**除外そのものが効いているか**は線 5（`svc.exclude` → `remove`）が見ている。
5. **`gui_layout` の 3 画面はデータ依存**（§6）。素の実データで回すと NG になるのは**前から**の物で、
   私の変更が原因ではない（変更前のコードでも同じ）。必要なら道具側で
   「除外の理由が無いときはその検査を飛ばす」形にできるが、**今回は触っていない**（検査を緩める話は別の判断）。
6. 一時物（**消してよい**）: `.tmp-audit-redo/p8-3-band-miss/`
   （`diag.py` `diag2.py` `diag3.py` `proof_copy.py` `why_mutant_survives.py` `missing_row.py`
   `mutants.py` `make_test.py` `setup_srv.py` `make_copy_show.py` `final_check.py`
   `real_phash.json` `copy/` `missing/` `srv/`・ログ `srv.log` `layout.log` `layout2.log`）。
   複製サーバ（8791）は**止めた**（後始末は §9）。
7. **`tests/test_duplicates_real_shape.py` は実データの pHash 263 個を写している**。実データが増えても
   **この試験は動く**（形を固定するための写し）。実データの pHash を作り直すと当然この試験は古くなるが、
   そのときは `REAL_BRUTE` と `REAL_GROUPS` を実際の値に合わせて写し直す（**写しであることを docstring に明記**）。

## 9. 後始末

- 8791（複製サーバ）は停止し、`netstat` で消えていることを確認した。**8790 は止めていない・触っていない。**
- `.backup/` は消していない。`git` のコミットはしていない。
- 実データ `.data/` への書き込みは 0（mtime が調査の前後で同じ。§6）。
