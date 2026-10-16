# 監査の指示書（P7-4: 条件の記録の画面）

あなたは**実装の監査者**です。**P7-4（画面 2 つ）**を監査してください。**P7 の最後の小段**です。

- 対象: `C:\work\image-reviwer` ／ 出力: **`docs/p7-4-audit-report.md` を新規に書くだけ** ／ 言語: 日本語 ／ **実行してよい**
- **形式は前の 3 つと同じ**（`docs/p7-audit-brief-p7-3.md` の §0〜§4 をそのまま踏襲。A/B/C/D/E/F/G/H と「最も重大な 3 件」、各項目に場所と再現手順）。
- **P7-3 の再確認も同時に**お願いします（`docs/p7-3-audit-report.md` の **A-1〜A-3** が直ったか。仕分けは `docs/p7-3-audit-triage.md`。
  とくに **A-1 = 新しい job 25 件で合計 25 行**・**詳細が失敗した job が次の周期で拾える**・**A-2 = 再起動して `GET /api/watcher` が 200**・
  **A-3 = 英訳を捕まえて `approx` → `exact` に上がる**・**20 枚の上限で基準を上げない**）。報告は `docs/p7-3-audit-recheck.md` に分けてよいです。

## 0. 環境（**利用者のアプリが 8790 で動いています。止めないでください**）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
uv run --no-sync pytest -q                                  # いま 397 件
node tools/gui_smoke.mjs                                    # 142 件
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <id>
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen recipe --ids <id>   # 新しい
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen recipes            # 新しい
```

- **実データ `.data/` は `mode=ro` のみ**（v6・263 枚・判断 3 件・`recipe_record` 0 行）。壊す試験は複製（`sqlite3` の `backup()`）。**`.backup/` は消さない**。
- **ComfyUI は生きています**（8188・0.39.2）。**`GET` だけ**。**`POST /prompt` は禁止**（画像の生成をしない）。
- 一時物は `.tmp-audit-redo/`。**ソースは編集しない**。**`git` のコミットもしない**。

## 1. 見てほしいこと

1. **画面が本当に在るか**（P6 の教訓）: `#/asset/<id>/recipe` と `#/recipes` を**本物の Chrome**（`gui_layout` の `--screen recipe --ids` / `--screen recipes`）で開き、
   **判定の印**・**理由**・**束とファイル（印つき）**・**結果の行と合否のボタン**・**はみ出し 0**・**入口が画像のすぐ下でスクロール無しで見えるか**（P4-3 で踏んだ穴）。
2. **記録時の 7 語と書き出し時の 3 語を画面で混ぜていないか**（設計 §5.1〜§5.3）。**`reasons` と `reason_details` の出し方**。
3. **往復を実物で**: 記録 → 判定 → 検査 → 書き出し（seed・印）→ 一覧 → 手で紐付け → 合否（**human だけ**・上書き）。
   **P7-3 の修正で `approx` → `exact` に上がる**ことも（英訳つきの job を偽の ComfyUI で流す）。
4. **`GET` が 1 バイトも書かない**（2 画面を開く前後で**全ファイルの size/mtime と 7 表の行数の指紋**）。
   **esc**（理由や語釈に `<script>` を入れても要素にならない。`script` 要素 0）。
5. **`#/jobs` の監視 1 行**（`GET /api/watcher`。**見る / 止める は人だけ**。**`agent` は 403**）。
6. **新しい `POST` の守り**（`Host: evil` / `Content-Type: text/plain` で 403・`actor` の語彙外は 422・`?status=` の語彙外は 422）。
7. **`fetched` 列**: v6 の DDL にあり、**既に v6 の古い DB にも `_top_up_v6` で入る**か（**PRAGMA table_info を見てから ALTER**）。
   **`/view` で取り込んだときに 1 が立つ**か。
8. **テストが本当に落ちるか**（`gui_smoke` 142 件・`gui_layout` の新しい 2 画面の検査）。**揺れないか**（`pytest` を複数回）。
9. **回帰**: `pytest` **397**・`gui_smoke` **142**・`gui_layout` **8 画面**が緑か。**実データ `.data/` が無傷**（`recipe_record` 0 行・mtime 不変）。
10. **P7-4 の申し送り**（`docs/p7-4-implementation.md`）: **プリセットの画面が無い**（口が無いため）ことを妥当と見るか。**設計 §5.5 / §4.12 との差**。
11. **設計とのずれ**（`docs/frontend-design.md` §4.7〜§4.12 と §6 の文言・`docs/p7-design.md` §5）。
12. **`docs/p7-3-audit-triage.md` の主張を自分で再現する**（A-1〜A-3 と `#/jobs` の 1 行）。

## 2. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p7-4-audit-done --body (Get-Content -Raw $env:TEMP\p7-4-audit.txt) --json
```

- subject は `p7-4-audit-start` / `-mid` / `-done`。待たずに続けて `G` に推奨つきで書いてください。
