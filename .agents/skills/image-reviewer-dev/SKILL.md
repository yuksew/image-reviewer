---
name: image-reviewer-dev
description: >-
  image-reviewer（C:\work\image-reviwer。画像の登録・閲覧・判断・比較・要求・注記・タグのローカル Web アプリ）で
  設計書を書く・実装する・直すときに必ず要る知識。段の分け方（設計 → 点検 → 仕分け → 小段ごとの実装 → 監査）、
  正になる文書の優先順位、検証の三点セット（pytest / gui_smoke / gui_layout の 4 画面）、道具（tools/probe_*.py・
  check_contract_*.py）、データの安全（.data は読むだけ・複製は sqlite3 の backup()）、環境の罠（UV_CACHE_DIR・
  os error 32・%TEMP%）、家風（日本語・GET は書かない・CHECK・移行は足すだけ・client_token・actor の検査は 1 か所）、
  合格の線の書き方。このリポジトリで src/ tools/ tests/ apps/ schemas/ docs/ のどれかを触るとき、P4〜P6 の設計や
  実装の話が出たとき、「image-reviewer」「image-reviwer」「P4-2 を実装」「設計書を書いて」「合格の線」と言われたときは
  必ずこのスキルを読む。監査（実行して確かめる側）は image-reviewer-audit、Orca の往復は orca-relay を見る。
---

# image-reviewer の開発

このリポジトリは **DeepSeek（dsh セッション）が設計書を書いて実装し、Claude Code（Fable）が点検・監査する**体制で進んでいる
（根拠: `README.md`「進め方」、`docs/p6-morning-report.md`「いまの状態」）。実装者がこのスキルを読む前提で書く。
すべての規則に**根拠の文書**を添えてある。根拠が無い規則は書いていない。

## 1. 流れ（1 段 = 設計 → 点検 → 仕分け → 小段ごとの実装 → 監査）

| 順 | 何をするか | 成果物 | 根拠 |
| --- | --- | --- | --- |
| 1 | 段の設計書を書く。`§0` に**拘束力のある差分**（本文 `design.md` と食い違う点・本文が黙っている点）を集める | `docs/p<N>-design.md` | `docs/p4-design.md` 4-5 行「この段の正はこの文書。本文と食い違うときは §0 が正」 |
| 2 | 点検の指示書を書いて Fable に渡す | `docs/p<N>-review-brief.md` → `docs/p<N>-review-report.md` | `docs/p4-review-brief.md` |
| 3 | 指摘を仕分けて設計に反映する（**推奨はすべて採用**が慣例。利用者が決める問いは朝の報告に集める） | `docs/p<N>-review-triage.md`、`docs/p<N>-morning-report.md` | `docs/p6-review-triage.md` 冒頭、`docs/p6-morning-report.md` |
| 4 | 小段に割って実装する。**最初の小段（`-0`）は機能を足さない**（表と契約だけ） | `src/` `tests/` `tools/` | `docs/p6-design.md` §0.1、`docs/p4-design.md` §0.1 |
| 5 | 小段ごとに**実装の記録**を書き、監査の指示書を書いて Fable に渡す | `docs/p<N>-<k>-implementation.md`、`docs/p4-audit-brief-p<N>-<k>.md` → `docs/p<N>-<k>-audit-report.md` | `docs/p6-1a-implementation.md`、`docs/p4-audit-brief-p4-1.md` |
| 6 | 監査の指摘を仕分けて直す。全段が終わったら `design.md` 本体を 1 回で直す | `docs/p<N>-<k>-audit-triage.md`、`docs/design.md` §16.x | `docs/p6-review-triage.md` §E、`docs/design.md` §16.4 |

実装の記録に必ず入れるもの（監査がそこを見る）: **作ったもの（ファイルと行数）／実行したコマンドと結果／自分で決めた点／
申し送り／設計の穴**。根拠: `docs/p6-1a-implementation.md` の構成、`docs/p6-2-implementation.md`（決めた 7 点・未実装 2 点・穴 3 件）。
**記録を書かないと、監査は指示書の列挙を記録として扱うしかなくなる**（`docs/p4-0-audit-report.md` 冒頭、`docs/p4-1-audit-report.md` 冒頭）。

## 2. 正になる文書と優先順位

1. **その段の設計書の `§0`**（`docs/p<N>-design.md`）。本文より強い。
2. その段の設計書の本文。
3. `docs/design.md`（全体）と `docs/frontend-design.md`（画面）。**段の決定は実装後に §16.x へ 1 回で反映**する（`docs/design.md` §16.4 が P6 の例）。
4. 契約 `schemas/review-export.schema.json` / `schemas/annotation-export.schema.json`（draft 2020-12、`abi: 0.1`。
   **足すだけなら `abi` は上げない**。根拠: `docs/p6-design.md` §0.5、`docs/p4-design.md` §6.2）。
5. 点検と監査の報告（`docs/p<N>-review-report.md`、`docs/p<N>-<k>-audit-report.md`）と仕分け。**採用した指摘は設計に
   `（点検 …）` の印で書き戻す**（`docs/p6-morning-report.md`「58 か所に印」）。

`README.md` の文書表が入口。フォルダ名は `reviwer`（`reviewer` ではない）で、改名はできない（`README.md` 冒頭）。

## 3. 検証の三点セット（どの小段でも緑に保つ）

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"      # 必須（README「動かす」）
uv run pytest -q                                            # 260 件（P4-1 の監査修正まで。段が進むと増える）
node tools/gui_smoke.mjs                                    # CSS を持たない軽い DOM。fetch の回数と本文を見る
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8                    # 比較（3 窓）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests            # 要求の一覧
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>  # まとまりレビュー
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <id>    # 注記
```

- 4 画面すべてを回す（根拠: `README.md`「動かす」、`docs/p6-morning-report.md`「最終状態」）。`gui_layout` は本物の Chrome を
  使い、`%TEMP%\gui-layout-*` にプロファイルを残す（`docs/p5-fix2-audit-report.md`）。
- **`gui_smoke` の偽の DOM は見た目を見ない**。実機でしか見つからないバグ（カードの入れ子・`decide` の名前隠し・競合の
  二重描画）は `gui_layout` に「壊すと落ちる」検査を足して守る（`docs/p6-1b-audit-report.md` B2、`docs/p6-1b-audit-triage.md`）。
- 口（`POST`）を足すたびに **`Host: evil` と `Content-Type: text/plain` が 403** のテストを書く（`docs/p6-review-report.md` C8、
  `tests/test_tags.py` `test_the_new_tag_endpoints_are_guarded`）。

## 4. 道具

| 道具 | 何をするか | 注意 | 根拠 |
| --- | --- | --- | --- |
| `tools/probe_p<N>*.py` | 段の**合格の線を実機で出す**（別プロセスで uvicorn を立て、HTTP で叩く） | 自分の置き場は自分で消す（`--keep` で残す）。`probe_p6_1a.py` は 90 MB 残したことがある。`probe_p6_2.py` は注記が白紙の画像でしか通らない | `docs/p6-1a-audit-triage.md`「tools」、`docs/p6-2-audit-report.md` C-6、`tools/probe_p4.py` |
| `tools/check_contract_p6.py` | **本物の `jsonschema`** で契約を検証する（`uv run --with jsonschema`） | テストの自前の検査（`tests/test_export.py` `check_contract`）とは別に回す | `docs/p6-0-audit-triage.md` F7、`docs/p4-0-audit-report.md` D-3 |
| `tools/gui_layout.mjs` | Chrome headless + CDP で 4 画面を計測 | 新しい画面を作ったら `--screen` を足す（P6-2 の `--screen asset` が例） | `docs/p6-2-audit-triage.md` §F |
| `tools/verify_against_history.py` | ComfyUI の `/history` と突き合わせ | | `tools/` |

## 5. データの安全

- **実データ `.data/` は読むだけ**（`sqlite3.connect("file:...?mode=ro", uri=True)`）。書く試験は複製で。
  サーバは `IMAGE_REVIEWER_DATA=<複製>` で別フォルダに向ける（根拠: 全部の監査の指示書 §0、`README.md`）。
- **複製は `sqlite3.Connection.backup()` で作る。** `.data/db.sqlite3` は WAL で、`-wal` に 0.26 MB の未畳み込み分がある。
  `db.sqlite3` だけ `cp` すると**判断 3 件が全部抜ける**（根拠: `docs/p4-0-audit-report.md` D-1「`cp` だけだと判断 0 件」）。

  ```python
  src = sqlite3.connect("file:C:/work/image-reviwer/.data/db.sqlite3?mode=ro", uri=True)
  dst = sqlite3.connect(r"C:\work\image-reviwer\.tmp-audit-redo\<name>\db.sqlite3"); src.backup(dst)
  ```
- **使い捨ては `.tmp-audit-redo/`**（監査も実装者もここ。消されることがある前提で、報告に手順を書く）。
  **控えは `.backup/<label>-<YYYYMMDD-HHMMSS>/`**（`.backup/pre-p4-20261016-093705/` が例。`db.sqlite3` / `export` / `sidecar` /
  `store.json` / `thumbs`）。
- 複製で監査した試験データ（実体の無い asset など）は複製に残る。`gui_layout --screen asset` が拾って NG になることがある
  （`docs/p6-morning-report.md`「1 つ注意」）。複製は作り直す。

## 6. 環境の罠（全部、実際に踏んだ）

| 罠 | どうする | 根拠 |
| --- | --- | --- |
| `UV_CACHE_DIR` が無いと `uv` が動かない | `$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"` を最初に | `README.md`、各指示書 §0 |
| 利用者のサーバ（`image-reviewer.exe serve --port 8790`）が `.venv` の exe を握っていると `uv sync` / `uv run` の再インストールが **`os error 32`** で落ちる | **`uv run --no-sync …`** か **`.venv\Scripts\python.exe`** を使う。`uv sync` はサーバを止めてから | `README.md`「`uv sync` はサーバを止めてから」、`docs/p4-audit-brief-p4-1.md` §0 |
| `%TEMP%` に SQLite のファイルを作れない | 一時物はリポジトリの中（`.tmp-audit-redo/`）。pytest は `-p no:tmpdir` で `tests/.tmp` を使う | `pyproject.toml` `addopts`、`tools/probe_p5.py` の失敗 |
| `uv run image-reviewer serve` は uv → ランチャ → python の 3 段。uv を止めても python が生き、`lifespan` の書き出しは後から走る | 止めた直後に `export/groups/*.json` を読むなら 1 秒待つ。終了の試験は `python.exe -m uvicorn` 直起動で | `README.md`「止めた直後に…」 |
| ComfyUI は同じグラフの再投入を **`execution_cached`** で返す（実行しない） | 時間は**別々の画像**で測る。同じ画像を 3 回投げた「定常 0.40 s」は嘘になる | `docs/p4-review-report.md` A-4、`docs/p4-design.md` §7 |
| ComfyUI の `LoadImage` は `input/` の一覧しか受けない | `POST /upload/image`（`type=temp`）で複製を作り `<subfolder>/<name>.png [temp]` を渡す。複製は溜まる（53 枚で 19 MB） | `docs/p4-design.md` §0.5、`docs/p4-1-audit-report.md` D-14 |
| `onnxruntime-gpu` は CUDA の DLL が無いと**黙って CPU に落ちる**（例外なし、12 倍遅い） | `session.get_providers()[0]` の実値を起動のログに出す | `docs/p4-review-report.md` B-2、`src/image_reviewer/tagger.py` `BuiltinTagger` |
| Git Bash の日本語は cp932 で化ける | Python は `PYTHONIOENCODING=utf-8` `PYTHONUTF8=1`。Orca への本文は `Out-File -Encoding utf8` | orca-relay スキル |

## 7. 家風（実装の約束）

| 約束 | 具体 | 根拠 |
| --- | --- | --- |
| **日本語**で書く | コメント・docstring・文書・エラーの文言・画面の文言。テストの docstring には「**何を壊すと落ちるか**」を書く | 全ファイル。`docs/p4-design.md` §8 冒頭、`docs/p5-audit-report.md` F1 |
| **`GET` は 1 バイトも書かない** | 書き出し・切り出し・訳すは `POST` だけ。`GET` は「その場で作って返す」まで | `docs/p6-design.md` §0.6（P5 の監査 C8/G2 の教訓）、`docs/p4-design.md` §0.10 |
| **語彙は DB の `CHECK` でも守る** | `state` / `source` / `actor` / `known` など。`db.py` は 11 か所で使っている | `docs/p6-design.md` §0.10「表の制約」、`src/image_reviewer/db.py` |
| **ヘッダの語彙は口で検査する** | `X-Image-Reviewer-Actor` は `human` / `agent` だけ。外れたら **422**（`CHECK` に当てて 500 にしない） | `docs/p6-1a-audit-report.md` A1、`src/image_reviewer/api/__init__.py` `actor_of()` |
| **移行は足すだけ・何度呼んでも同じ** | `migrate()` は版ごとに `current < N` を順に当てる。DDL は `IF NOT EXISTS`。列を足すときは **`PRAGMA table_info` で見てから `ALTER TABLE ADD COLUMN`**（同じ版番号で形が違う DB が残るため） | `src/image_reviewer/db.py` `migrate()` / `_migrate_v4`、`docs/p4-1-audit-report.md` A-1、`docs/p6-0-audit-triage.md` 末尾 |
| **`client_token` の再送は 200 で同じ id** | 行が増える口に付ける。**照合は `target_key` より先**。置き場の無い口（`decline` / `export`）には付けず状態機械で冪等に | `docs/p6-design.md` §3.2、`docs/p6-review-report.md` B4 / B5 |
| **`actor` の検査は 1 か所** | `require_human()` のような関数に集め、後でエージェントにも許せる形に。`source='manual'` と `actor` は別の欄 | `docs/p4-design.md` §0.14 Q3、`src/image_reviewer/tags.py` |
| **契約に足した欄は実際に出す** | 足した欄を 1 回も出さないまま監査に出さない。テストは「値を 1 件入れてから、その欄に値がある」まで | `docs/p6-0-audit-report.md` B1、`docs/p4-review-report.md` B-5 |
| **差し替えは UPDATE → INSERT の順** | 部分 UNIQUE 索引（`ux_request_target_open`）があるので逆だと落ちる | `docs/p6-review-report.md` C4、`docs/p6-1a-audit-report.md` §2-2 |
| **浮動小数の境界は `round(v, 6)` してから `floor` / `ceil`** | `ceil((x+w)*W)` は幅 1360 で 1 画素はみ出す。端ぴったり（`left == W`）は 1 画素に丸める | `docs/p6-review-report.md` B1、`docs/p6-2-audit-report.md` 上位 1 |
| **取引の中で外部を待たない** | 模型・HTTP の呼び出しは `store.transaction()` の外。書き込みだけを短い取引に（`Store` は接続 1 本を RLock で直列化） | `docs/p4-1-audit-report.md` B-1、`src/image_reviewer/store.py` |
| **ワーカーは 1 本。`queued` も忙しい** | 検査と `INSERT` を同じ取引で | `docs/p4-1-audit-report.md` B-2 |
| **ノードの前処理は 1 つも変えない** | `int()` と `round()` の違いで語が変わる（縦長 4 枚中 2 枚） | `docs/p4-1-audit-report.md` B-3、`docs/p4-design.md` §0.6 |
| **語の正規化で括弧とコロンを落とさない** | CSV の 1,619 語（キャラ名の 51%）が括弧を含む。外すのは `\(` `\)` のエスケープだけ | `docs/p4-review-report.md` A-1、`src/image_reviewer/tagger.py` `normalize_name` |
| **数を黙って捨てない** | 落とした断片・飛ばした枚数は `job.note` / `counts` に出す | `docs/p4-design.md` §0.8-5 |
| **画面の語は 1 つ** | 「あとで」＝判断を書かない、「判断を消す」、削除だけ「取り消す」。括弧書きは語釈に使わない | `docs/p6-review-triage.md` C6、`docs/design.md` §16.1 |

## 8. 合格の線の書き方（設計書 §1.2）

設計の各段に、**そのまま打てる手順と合否**の表を置く。監査はこの表を自分の手で通す。

```markdown
| # | 線 | 確かめ方（そのまま打てる形） | 合否 |
| 1 | 未タグ画像にタグが付く | 合成 8 枚を登録 → POST /api/assets/tag {engine:'comfyui'} → GET /api/jobs/{id} が done → 8 枚とも source='wd14' が 1 語以上 | 8/8 に 1 語以上。0 語の画像があれば落ち |
```

- 数値・手順・合否がある線だけを書く。**測れない条件は書かない**（`docs/p4-design.md` §1.2 末尾）。
- 性能は **「未計測」を「未計測」と書き、どの段で測るかを決める**（`docs/p4-design.md` §7、P5・P6 と同じ規律）。
- 計測は**別々の入力**で、**測り方（keep-alive か毎回接続か、何回の中央値か）を表に添える**
  （`docs/p6-1a-audit-report.md` C3「keep-alive と毎回接続で桁が違う」、`docs/p4-review-report.md` A-4）。
- 線が画面を要求するなら、**その画面が本当に存在するか**を先に確かめる（P6 の線 2 は「既存のまとまりレビュー」が無かった。
  `docs/p6-review-report.md` A2）。
- テストは「**壊すと落ちる**」形で書き、設計 §8.1 に「壊すもの／確かめること／なぜ要るか」の表を置く（`docs/p4-design.md` §8.1）。
  同一プロセスの錠で直列化されるテストは `BEGIN IMMEDIATE` を外しても落ちない（`docs/p6-review-report.md` C9）し、
  `ORDER BY` を外しても 2 回の比較は一致する（`docs/p4-0-audit-report.md` F）。**並びそのものを期待値にする**。

## 9. 段の記録の置き場（すべて `docs/`）

`p<N>-design.md` → `p<N>-review-brief.md` / `p<N>-review-report.md` / `p<N>-review-triage.md` →
`p<N>-morning-report.md`（利用者が決めること）→ `p4-audit-brief-p<N>-<k>.md` / `p<N>-<k>-implementation.md` /
`p<N>-<k>-audit-report.md` / `p<N>-<k>-audit-triage.md`。`README.md` の文書表に行を足す。
