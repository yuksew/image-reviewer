# 落ちていた 1 件の修正の記録（`test_the_stuck_reason_says_why_it_could_not_go_back`）

- 日付: 2026-10-19 / 直した人: DeepSeek（実装者） / 指示: 依頼者の「**落ちているテストを 1 件、原因から直す**」
- 症状: `uv run --no-sync pytest -q` → **1 failed, 546 passed**（毎回）。落ちるのは
  `tests/test_deletions.py::test_the_stuck_reason_says_why_it_could_not_go_back` の 531 行
  （`assert svc.ledger(actor="human")["items"][0]["stuck_reason"] == "different"` が `None`。
  **直した後は 550 行**）。
  同時に `deletions.py:620` の警告「保留に移す前に落ちた行を戻しました（削除は起きていません）」。
- **直した物: `tests/test_deletions.py` の 1 件（+20 / −1）だけ。**
  **`src/image_reviewer/deletions.py` は 1 行も触っていない**（実装は仕様どおりだった。§2）。
- **テストは緩めていない。** 期待値は `== "different"` のまま。直したのは**前提**（§2）で、
  **壊すと落ちる**ことを 4 通りで確かめた（§3）。
- **実データ `.data/` は `mode=ro` でしか開いていない**（画像は 1 枚も動かしていない。`.backup/daily` の
  3 世代もそのまま。**8790 は止めていない**。サーバは 1 つも立てていない）。壊す試験は**複製の写し**で（§3）。
- **8790 について観察**: 私が `GET http://127.0.0.1:8790/api/health` を打った時点（14:19）で
  **接続できなかった**（`Get-NetTCPConnection` でも **8780〜8800 に listen が 1 つも無い**。python の
  プロセスは hermes の 2 つだけ）。**私は止めていない**（プロセスを止める操作・サーバの起動は 1 つもしていない。
  `uv run` は `--no-sync` だけ）。**別の担当か利用者側で落ちている可能性があるので、親に申し送る。**
- **P10 の監査（`docs/p10-audit-report.md`）とその複製サーバ（8798・8799 など）には触っていない。**
  `docs/p10-audit-report.md` は Fable の作業中なので**書き込みも削除もしない**（`grep` で読んだだけ。
  `git status` で「M」なのは Fable の分）。**サーバは 1 つも立てていないので、止めた物も無い。**

---

## 1. 原因

### 1-1. 何と何を比べているか

`_original_state(row)`（`deletions.py:565`）は、**保留の実体が無い行**の後始末
（`_recover_missing_hold` → `tick()` → `_purge_expired`）で**元の場所**を 3 つに分ける。

| 見る物 | どこから取るか |
| --- | --- |
| **登録の値** | `asset_location` の行（`WHERE path = row["path"]`）の `size` / `mtime_ns` |
| **いまの実体** | `identity_of(display_path)` = `os.stat` の `(st_size, st_mtime_ns)`（`deletions.py:131`） |

`size` か `mtime_ns` が違えば `different`。**両方一致なら `same`**（＝「動かす前に落ちた」と読んで
`restored_at` を立てる。`deletions.py:619-627`）。**中身（ハッシュ）は見ていない。**

### 1-2. 落ちていた形（実測）

テストの (3) は「段 3 で消す → 保留の実体を消す → **元の場所を別の中身で作り直す** →
`remaining_sec = 0` → `tick()` 2 回 → `stuck_reason == 'different'` を期待」。

**作り直しは登録の 0.3 ms 後**に起きる。実測（`.tmp-audit-redo/probe_gran2.py`）:

| 測った物 | 値 |
| --- | --- |
| seed 53 の書き込み → seed 54 の書き直しまでの**実時間**（15 回） | 290,000〜375,000 ns（**0.3 ms**） |
| そのうち **`mtime_ns` が同じ**だった回 | **14 / 15** |
| 別の測り方（20 回。`probe_gran.py`） | **15 / 20 で同じ** |
| **落ちるテストの中**（`probe_stuck3.py` で `_recover_missing_hold` を覗いた。4 回） | **3 回が差 0 ns**、1 回が差 504 µs |

この機械のファイル時刻の刻みは 0.5〜1 ms 程度で、**0.3 ms 後の書き直しは同じ刻みに落ちる**。
`make_png(seed=53)` と `make_png(seed=54)` は**どちらも 93 B**（16x16 の PNG）なので、
`mtime_ns` が同じなら **`(size, mtime_ns)` が完全に一致**する。

→ `_original_state` は `same` を返す → `_recover_missing_hold` は「動かす前に落ちた」と読んで
`restored_at` を立てる（`deletions.py:620` の警告）→ 台帳の行は `stuck` にならないので
**`stuck_reason` は `NULL`** ＝ テストの期待（`different`）と食い違う。

**これは設計が明記した「規則の限界」そのもの**である。

- `_original_state` は `(size, mtime_ns)` で見る（**P8-2 の監査 D-2** の仕分け:
  「`same` は `(size, mtime_ns)` が**登録の行と一致**するときだけ」。`docs/p8-2-audit-recheck-triage.md`）。
- `docs/p8-design.md` §8.4 **F4**: 「**同じ大きさ・同じ `mtime_ns` に差し替えた物**（`os.utime` で再現）→
  **検出できないことを明記**したテスト（規則の限界を固定）」。その試験は既にある
  （`tests/test_deletions.py:675` `test_the_limit_of_the_rule_a_same_size_swap_is_not_detected`）。
- つまりテスト (3) は「**検出できる**差し替え」を作ったつもりで、**検出できない形（F4）に落ちる**ことがある。
  **期待ではなく前提が保証されていなかった。**

### 1-3. いつ入ったか（**P10 ではない**）

**足した日から揺れている。** 複製（`git archive <版>`）で 6 回ずつ回した結果:

| 版 | 6 回の結果 |
| --- | --- |
| `755316f`（この試験を足した版。2026-10-18 P8-3 の監査の反映） | **3 通り / 3 落ち** |
| `3f75484`（P8-5） | 0 / 6 |
| `4bdb7e9`（**P10 の直前**） | 1 / 5 |
| `4b251d7`（P10） | 0 / 6 |
| HEAD（直す前） | 0 / 6（単体で 6 回、全体でも 1 回） |

P10（`4b251d7`。`deletions.py` を +446 / −20）は、**この道の 2 つの関数を 1 文字も変えていない**
（`git show <版>:src/image_reviewer/deletions.py` から関数だけを取り出して比べた。**実物は触っていない**。
`.tmp-audit-redo/diff_original_state.py`）:

| 関数 | `1da1a08`（P8-3 で新設） | `755316f` | `4b251d7^` | `4b251d7` | HEAD |
| --- | --- | --- | --- | --- | --- |
| `_original_state`（34 行） | 同じ | 同じ | 同じ | **同じ** | 同じ |
| `_recover_missing_hold`（38 行） | ★違う | 同じ | 同じ | **同じ** | 同じ |

（P10 が触ったのは `advance` / `close` / `_target_for_advance` / `_files_of_row` / `pending` などで、
**この不具合の道ではない**。日本語 UI の適用も文言だけ。）

**再現**（直す前の実リポジトリ、単体）: `6 回中 6 回` 落ちた。写し（`git archive HEAD`）の全体実行でも
`tests/test_deletions.py:531` で落ち、`deletions.py:620` の警告が出た（exit=1）。
**同じ写しの 2 回目は緑**（542 passed, 5 skipped。写しの実行では cwd が写しなので 5 件が skip になる。
どちらも 547 件）——**揺れそのもの**が証拠である。

---

## 2. 直した物（**テスト**。実装ではない）

**実装は仕様どおり**（`(size, mtime_ns)` で見る。§1-2）なので、直すのはテストの**前提**にした。
期待値（`== "different"`）も、シナリオ（同じ大きさ・違う中身）も変えていない。

| 直した所 | 前 | 後 |
| --- | --- | --- |
| 登録の値を覚える | （無し） | `registered = swapped.stat()`（`add_asset` が見る物と同じ） |
| 差し替えの `mtime_ns` | 書き直しの時計任せ（0.3 ms 後なので**同じ刻みに落ちうる**） | `os.utime(swapped, ns=(registered.st_atime_ns, registered.st_mtime_ns + 1_000_000))` で**登録と違える** |
| 前提の検査 | （無し） | `assert (now.st_size, now.st_mtime_ns) != (registered.st_size, registered.st_mtime_ns)`（「試験の前提…が崩れている」） |
| docstring | — | 「(3) の前提は登録と `(size, mtime_ns)` が違うこと」＋ F4 の試験への参照＋実測値（0.3 ms / 20 回中 15 回） |

- `os.utime` は**このファイルに既にある書き方**（`tests/test_deletions.py:1587` の C-5 の試験が
  同じ形で `mtime_ns + 1_000_000` を使っている）。
- **なぜテストか（「期待が古い」と言える根拠）**: ①`_original_state` の仕様は
  「`(size, mtime_ns)` が登録の行と一致するときだけ `same`」（P8-2 の監査 D-2 の仕分け）で、
  実装はそれに一致している。②同じ大きさ・同じ `mtime_ns` の差し替えを**検出できない**ことは
  §8.4 F4 が**設計の限界として明記**し、`test_the_limit_of_the_rule_a_same_size_swap_is_not_detected`
  が固定している。③テスト (3) の前提（書き直せば `mtime_ns` が変わる）は**どの設計文書にも保証が無く**、
  実測で 20 回中 15 回崩れた。→ **期待ではなく前提が古い/甘い。**
- **なぜ実装をハッシュで見るようにしないか**: それは**設計の変更**である（F4 の試験の docstring 自身が
  「もし将来ハッシュで見るようにしたら、このテストは落ちる（そのときは設計を直す）」と書いている）。
  この指示の範囲（`deletions.py` と `tests/test_deletions.py`）で設計を変えるのは越権なので、**§6 に申し送り**した。

---

## 3. 壊すと落ちる（**複製の写し**で）

`git archive` で写しを `.tmp-audit-redo/mutate/` に置き、**写しの `deletions.py` だけ**を壊して走らせた
（`.tmp-audit-redo/mutate_run.py`。`run_in_copy.py` が**写しの `image_reviewer.deletions` を読み込んだこと**を毎回表示する。
**実物の `deletions.py` は 1 バイトも変えていない**）。

| # | 壊した所 | 結果 |
| --- | --- | --- |
| — | （壊さない） | **1 passed**（exit=0） |
| M1 | `_original_state` の `different` 判定を丸ごと外す（必ず `same`） | **failed**（`test_deletions.py:550`、`None == 'different'`） |
| M2 | **`mtime_ns` の比較だけ**外す（`size` は見る） | **failed**（同 550 行） |
| M3 | `_original_state` が必ず `different` を返す | **failed**（561 行、`missing` の道） |
| M4 | `_mark_unrestorable` が理由を残さない | **failed**（511 行、`target_exists` の道） |

**M2 が要る**: 直したテストが **`mtime_ns` の比較そのもの**を見ていることの証拠である
（直す前は、時計の刻み次第で `size` の比較に落ちていた。`size` は 93 B のままなので、
`mtime_ns` の比較を外すと `same` に戻って落ちる）。

---

## 4. `pytest` 3 回（**547 passed**）

```
uv run --no-sync pytest -q     # 1 回目: 547 passed, 1 warning in 38.24s
uv run --no-sync pytest -q     # 2 回目: 547 passed, 1 warning in 37.97s
uv run --no-sync pytest -q     # 3 回目: 547 passed, 1 warning in 37.94s
```

- **件数は 547 のまま**（試験を足しても削ってもいない。546 passed + 1 failed と同じ 547 件）。
- 直したテストだけを 8 回続けて回しても **8 / 8 通り**（直す前は 6 / 6 落ちた）。
- 生の出力: `.tmp-audit-redo/final-pytest-1..3.txt`

---

## 5. 実データが無傷

`.data/` は `mode=ro` と `sqlite3.backup()`（写しへ）だけで触った。**画像は 1 枚も動かしていない**
（`.data` の外の画像には触れていない。複製サーバも立てていない）。

| 見た物 | 直す前 | **3 回の `pytest` の後（最終確認）** |
| --- | --- | --- |
| `.data` のファイル数 / 合計 | 675 / 22,718,758 B | **同じ** |
| `.data` の署名（**mtime を外した** `(パス, size)`） | `54991b92feea05773fc411d1f0484dbc76ecde44cfc2b64e68263f511ba74152` | **同じ** |
| `db.sqlite3` の sha256 | `a906f73a78f19bd3f8838b8d150d4cba914d0ab283964d33139ff217599b0da5` | **同じ** |
| `db.sqlite3-wal` の sha256 | `a5e3647cf5b4e9e7b8ee230262907545c6bb6bed4db4ac243c55927701dde04c` | **同じ** |
| `db.sqlite3-shm` の sha256 | `f9a28f8febc36c4e7ce6e5d94df3ab130d948328eeb31004bf889d58ae9bf176` | **同じ** |
| `store.json` の sha256 | `e18d6b84966d3995b1af99838d55682645b24bde09e1b5fa32e8f7e8282a716e` | **同じ** |
| `deletion_log` | **194 行・全部段 1**（`restored` 0 / `closed` 0 / `purge` 0） | **同じ** |
| `asset` / `asset_location` / `decision` / `review_group` | 461 / 455 / 3 / 2 | **同じ** |
| `asset.deleted_at` あり | 194 | **同じ** |
| `.data/pending-delete` | 無い | **無い** |
| `.backup/daily` | `20261018` / `20261018-171143` / `20261019` の 3 世代 | **3 世代のまま** |

- **mtime が動いたのは `db.sqlite3-shm` だけ**（最終 14:16:17。読むたびに動く）。これは**他のプロセスが
  `mode=ro` で開くだけで動く**（`docs/handoff.md` §573-581 に既知の罠として書いてある）。**中身の sha256 は同じ**で、
  `db.sqlite3`（9:22:54）/ `-wal`（9:30:46）/ `store.json`（10/15）の mtime は**1 つも動いていない**。
- 確認は 3 回（直す前・1 回目の `pytest` の後・**3 回とも回した後**）行い、**どれも同じ**だった。
- `.data` の**中身を数えるのも写し**（`sqlite3.backup()` → `.tmp-audit-redo/data-check/db.sqlite3`）で行った。
  生の出力: `.tmp-audit-redo/data-before.txt` / `data-after.txt` / `data-after-all.txt`。

---

## 6. 申し送り

1. **`src/image_reviewer/deletions.py` は 1 行も変えていない。** 直したのは `tests/test_deletions.py` の 1 件だけ
   （`git diff --numstat` = `20 1 tests/test_deletions.py` ＝ 20 行足して 1 行消した）。
2. **設計に申し送る穴（直していない）**: **保留の実体が消え、元の場所に「同じ大きさ・同じ `mtime_ns`」の
   別のファイルが置かれた**形では、`_recover_missing_hold` が `same` と読んで `restored_at` を立てる
   （＝登録した画像が無いのに「戻した」と台帳に残る）。**F4 の試験は `delete` の道だけを固定していて、
   この後始末の道は固定していない。** 塞ぐなら `asset.sha256`（か実体のハッシュ）で見る形になるが、
   **それは設計の変更**（F4 の docstring がそう書いている）なので、この指示の範囲では触っていない。
   試験を 1 件足すと 547 が 548 になるので、**数え方の約束（547）を崩さないためにも足していない。**
3. **緑の報告を信じすぎない**: この 1 件は足した日（`755316f`）から 3/6〜0/6 で落ちていた。
   「547 passed」と記録された過去の実行は**運が良かった回**である。**時計に依存する試験**は
   `(size, mtime_ns)` のような**同じ刻みに落ちうる値**を前提にしない（今回の教訓）。
4. `README.md` の文書表には**行を足していない**（触ってよい範囲の外だったため）。足すなら 1 行。
5. **8790（利用者のアプリ）が listen していない**（14:19 時点。8780〜8800 に listen が 1 つも無い）。
   **私は止めていない**（`--no-sync` の `uv run` と GET 1 回だけで、プロセスにもサーバにも触っていない）。
   P10 の監査の複製サーバ（8798・8799）も同じ時点で listen していない。**親で確かめてほしい。**
6. 一時物は `.tmp-audit-redo/` に置いた（`probe_stuck*.py` / `probe_gran*.py` / `mutate_run.py` /
   `run_in_copy.py` / `diff_original_state.py` / `data_check.py` / `data-*.txt` / `final-pytest-*.txt`）。
   **版ごとの写し（`before-p10` / `at-*` / `before-fix` / `mutate`）は再現の手順を残して消した**（`git archive <版>` +
   `run_in_copy.py` で作り直せる）。**この実行で作った一時フォルダは 1 つも残っていない**
   （`conftest.py` の見張りが緑。`tests/.tmp/<pid>` の**空の**フォルダは以前から残る形で、私の回も 0 件）。
