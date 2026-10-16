# 引継書 — image-reviewer / P6 完了・P4 完了（2026-10-16 12:50 時点）

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

---

## 0. 最初に読む: 触ってはいけないもの・危ない操作

| 危ないこと | なぜ | どうする |
| --- | --- | --- |
| **利用者のアプリを止める/干渉する** | `image-reviewer.exe serve --port 8790`（**PID 35164・2026-10-15 19:26 起動**）が動いていて、**`.venv` の exe を握っています** | **`uv run …` は `os error 32` で落ちます。必ず `uv run --no-sync …`** か `.venv\Scripts\python.exe` を使ってください。止めてよいかは**利用者に確認**（`onnxruntime` の導入時に必要） |
| **実データ `.data/` を起動して移行させる** | 実データは**まだ `user_version = 3`**。いま起動すると **古い形の v5 に上がってしまう**（`V5_TAG_DDL` に `CHECK (known IN (0,1))`・`asset_tag.actor`・`job.note` が無い版） | **修正が入るまで起動しない**。修正後は起動してよい（v3 → v5 が 1 回で通る） |
| 実データへの書き込み | 壊す試験・検証で実データを汚さない | **`mode=ro` のみ**。コピーは **`sqlite3` の `backup()`** で作る（**`copy` だけだと WAL が抜けて判断 3 件が消える**）。使い捨ては `.tmp-audit-redo/` |
| `.backup/` を消す | 移行前の控え | `C:\work\image-reviwer\.backup\pre-p4-20261016-093705`（301 ファイル・9.9 MB・v3・asset 263・decision 3）。**消さない** |
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

**テストは 260 passed**（P4-1 の監査修正まで。**P4-2 の実装中**）／`gui_smoke` すべて ok／`gui_layout` は**比較・要求・まとまり・注記の 4 画面**すべて ok。`SCHEMA_VERSION = 5`。

### いま走っているもの（このセッションの終了時）

**進行中の作業はありません。**（下の「このセッションで終わったこと」まで全部完了。**サーバを起動して大丈夫**です。）

### 未着手

- **P4-1 の線 8**（内蔵タガー。**`onnxruntime` が要る**。利用者のサーバを止める許可待ち）。
- **P4-3 の監査の指摘の反映**（実行中。A-1 / A-2 / B-1 / B-2 ＋ 中程度。`docs/p4-3-audit-report.md`）。
- **P4 の `design.md` 本体への反映は済んだ**（§5.1 の `tag`/`asset_tag` に `known` と `CHECK`・§5.5 の `job`（P4 で作った）・
  §8.2 の前処理 9 手順と方式ごとの実測値・§8.4 の語釈の頼み方・§6.1 のタグと API の一覧。
  **`frontend-design.md` は実装者が §4.13 として先に足している**）。
- `README.md` の更新（テスト件数・機能一覧。**最後にまとめて**）。

### セッションを切り替えるときの注意

**進行中の作業は無いので、いつ切っても安全です。** ただし次のセッションの最初に**これを回して緑を確かめてください**:
`uv run --no-sync pytest -q`（**260 passed が期待値**）。
**`git` は使っていません**（非 git リポジトリ）ので、巻き戻しは効きません。控えは `.backup/pre-p4-20261016-093705/` です。


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

### ⚠ まだ残っている宿題（P4-1 の申し送り）

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

### 修正 1: v5 の DDL を設計に揃える【**完了（2026-10-16 10:20）**】

`docs/p4-0-audit-report.md` の A-1。**`db.py` に `_top_up_v5()` を入れて、`migrate()` の早期 return 側でも列を見て補う形にした**
（`tag.known` / `asset_tag.actor` / `job.note`。`SCHEMA_VERSION` は 5 のまま＝v6 の作り直しにしない）。
**古い v5 の DB（`data-p40`）を開くと列が戻り、263 枚・タグ 3 語が無傷**なのを実測で確認。**サーバを起動してよい。**

### 修正 2: P4-1 監査の 3 件＋中程度【**完了（2026-10-16 10:20）**】

`docs/p4-1-audit-report.md` の指摘は**全部直した**（§1 の「このセッションで終わったこと」に一覧）。
**検証**: `pytest` **260 passed**・`gui_smoke` ok・`gui_layout` 4 画面 ok・`probe_p4.py --engine comfyui` OK。

### 修正 3: 設計の小物

`?tag=` も `known=1|0|all`（既定 1）に揃える（`docs/p4-review-report.md` §J）。`job_item.state` の語彙を確定して `CHECK`。
`?source=` の複数指定が AND か OR かを決めて設計に書く。`temp` の複製の消し方を設計に反映。

### 次: P4-2（語釈）

`docs/p4-design.md` §3.5・§0.9・§8.1・§9 の P4-2 の行。要点:
- **番号付きで頼む**（`1. 1girl` → `^(\d+)[.)]\s*(.+)$` で対応）。**番号が取れて本文が ASCII だけではない行だけ保存**。
  取れなかった番号だけ 1 語ずつ再送。`sampling off`（決定的）。**20 語で 2 回同じ出力を確認済み（4.6〜4.8 秒）**。
- **`GET` は訳さない**（訳すのは `POST /api/tags/gloss`）。既定は「語釈の無い語だけ」。
- **`edited=1` は上書きしない**。人が直すのは `POST /api/tags/{tag_id}/gloss`（`source='manual'`・`edited=1`）。
- 模型は **`qwen3vl_8b_int8_convrot.safetensors`**（利用者の回答 Q5）。呼び方は §0.9（`CLIPLoader` → `TextGenerate` → **`PreviewAny` を繋ぐ**）。

### その次: P4-3（画面）と線 8

- `#/tags`（上位 200 語・既定 `known=1`）と `#/jobs`（新しい 50 件）を**新しく作る**。拡大のタグ欄は**2 行（英語／日本語）**で**括弧を使わない**。
- **線 8（内蔵と ComfyUI の語の一致）**: `onnxruntime` を入れる必要がある（**利用者のサーバを止める**許可が要る）。
  `pyproject.toml` に `tagger = ["onnxruntime>=1.20"]` を足す（**書くだけなら今でもできる**。入れるのはサーバ停止後）。
  **CUDA の DLL** が要る（無いと黙って CPU に落ちる。`get_providers()` の実値を出す）。

---

## 4. 検証の三点セットと道具

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
uv run --no-sync pytest -q                      # 251 件（修正後は増える）
node tools/gui_smoke.mjs                        # 91 ok（軽い DOM。CSS を持たない）
# 本物の Chrome。サーバは実データのコピーで立てる（8791〜）
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\data-XXXX"
uv run --no-sync image-reviewer serve --port 8791
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8                    # 比較
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests            # 要求の一覧
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>  # まとまりレビュー
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <id>    # 注記
# 実機の線（合否を出す）
uv run --no-sync python tools/probe_p4.py --engine comfyui   # P4 の線 1・2・7
uv run --no-sync python tools/probe_p6_1a.py                 # P6 の性能（線 150ms / 20ms）
uv run --no-sync python tools/probe_p6_2.py --base http://127.0.0.1:8791   # 切り出しの画素
uv run --no-sync --with jsonschema python tools/check_contract_p6.py       # 契約の検証
```

---

## 5. 数字の記録（次のセッションが前提にできる実測）

- **P6**: 要求の受付 p95 1.5 ms（keep-alive。線 150）／一覧 1,000 件 p95 2.8 ms（線 20）／切り出しは画素数比例（1024² 全面 21 ms・`compress_level=1`）。
- **P4-1**: ComfyUI の `IllustTagger` **0.26〜0.31 s/枚**（スコア付き）／`WD14Tagger` は**キャッシュが当たらないと 2.8〜3.4 s/枚**（設計にあった 0.40 s/枚は `execution_cached` の値）／内蔵 GPU **0.063 s/枚**・CPU 0.75 s/枚（未導入）。
  1 万枚の見積り: **内蔵 GPU 約 11 分 / IllustTagger 約 45 分 / WD14Tagger 約 8 時間**。
- **語釈**: 位置対応は 6 回中 2 回しか行数が合わない／**番号付きなら 4 回とも 20/20**（20 語 4.6〜4.8 秒）。
- **実データ**: 263 枚・判断 3 件・`user_version = 3`・WAL 263 KB（**畳まないと判断が消える**）。
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

**進め方**

- **コードを読んだだけの監査は何も守らない**（P5 の「実行込みのやり直し」で判明）。監査は**実行**させる。
- **「既存の画面」があると思い込まない**（P6 A2: 設計が「既存のまとまりレビュー」と書いていたが、P5 は作っていなかった）。
- **テストは「壊すと落ちるか」を言える形**にする（何も守っていないテストが見つかった）。
- 利用者の判断が要る点は**勝手に決めずに記録して聞く**（推奨つきで）。決定は**仕分け文書と設計本体の両方**に書く。

---

## 7. 利用者（人間）の判断待ち・確認待ち

1. **`onnxruntime` の導入**（利用者の回答 Q4: 「入れる。ただし後回しでよい」）。**入れるにはサーバを止める**許可が要る
   （`pyproject.toml` への 1 行＋導入。**線 8 はこれが無いと測れない**）。
2. **`.data` を v5 に上げるタイミング**（**v5 の DDL の修正後**。控えは取得済み）。
3. **P4 の `?source=` の AND / OR**（設計に無い。実装は AND。決めたら設計に書く）。
4. 語釈の**模型**は回答済み（`qwen3vl_8b_int8_convrot`）。**P4-2 で使い始める**。
5. Fable が作った **skill の置き場と配り方は決着済み**（§9。原本は `.agents/skills/` の 1 か所、`.claude/skills/` はジャンクション）。
   **残る判断は 2 つ**（`docs/skills-layout.md` §5 に推奨つき）:
   - **G-1**: DSH はプロジェクトの根を `.git` で探すので、このリポジトリが git 管理外だと **DSH を `C:\work\image-reviwer` で起動したときだけ** `.agents/skills` が読まれる。
     推奨は**このリポジトリを git 管理にする**（別の場所で起動しても読まれる）。次点は「必ず根で起動する」運用。
   - **G-2**: `orca-relay` を利用者レベル（`~/.agents/skills`）にも置くか。推奨は**置かない**（run id とパスがこのプロジェクト固有）。

---

## 8. 主要ファイルの地図

| 何 | どこ |
| --- | --- |
| 全体の設計（正） | `docs/design.md`（P6 の決定は **§16.4**） |
| フロントの設計 | `docs/frontend-design.md`（画面一覧は §3。**3 番＝まとまりレビュー・5 番＝要求の一覧**） |
| 段ごとの設計 | `docs/p5-design.md` / `docs/p6-design.md` / `docs/p4-design.md`（**各 §0 が拘束力のある差分**） |
| 点検と仕分け | `docs/p6-review-report.md` ＋ `p6-review-triage.md` / `docs/p4-review-report.md` ＋ `p4-review-triage.md` |
| 監査と仕分け | `docs/p6-{0,1a,1b,2}-audit-report.md` ＋ `p6-*-audit-triage.md` / `docs/p4-0-audit-report.md` / `docs/p4-1-audit-report.md` |
| 実装の記録（実装者が自分で決めた点・穴） | `docs/p6-1a-implementation.md` / `p6-1b-` / `p6-2-implementation.md` |
| 朝のまとめ（利用者向け） | `docs/p6-morning-report.md` |
| 監査・点検の指示書 | `docs/p6-audit-brief-*.md` / `docs/p4-review-brief.md` / `docs/p4-audit-brief-*.md` |
| 控え | `.backup\pre-p4-20261016-093705` |
| 検証の道具 | `tools/gui_smoke.mjs` / `tools/gui_layout.mjs` / `tools/probe_p4.py` / `tools/probe_p6_1a.py` / `tools/probe_p6_2.py` / `tools/check_contract_p6.py` |

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
