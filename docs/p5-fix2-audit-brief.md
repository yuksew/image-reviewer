# 監査の指示書（追加 6 件の再監査）

あなたは**実装の監査者**です。前回の再監査（`docs/p5-fix-audit-report.md`）で残った指摘に対して、
依頼者が**追加で 6 件**を実装しました。**それを独立に、実行して確かめてください。**

- 対象: `C:\work\image-reviwer`
- 出力: **`docs/p5-fix2-audit-report.md` を新規に書くだけ**（既存の報告・設計文書は**書き換えない**）
- 言語: 日本語

## 0. 環境

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"   # 必須
uv run pytest -q                                        # 176 件（前回 175 ＋ 今回 1）
node tools/gui_smoke.mjs                                # 51 ok（変更なし）
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\data-p52"   # 前回のコピー
uv run image-reviewer serve --port 8791
# 新設した検査（サーバが動いていること。Chrome headless + CDP を自分で立てる）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --ids <id,id,...>
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --ids <...> --viewport 1200x800 --dump
```

- 実データは `mode=ro`、**ソースは編集しない**、一時物は `.tmp-audit-redo/`。
- 前回のあなたの一時物（`cdp.mjs`・`page_fix.js` など）は残っています。

## 1. 実装した 6 件と、確かめてほしいこと

**「直っている / 直っていない / 別の問題が残る」を 1 件ずつ判定**し、実行したコマンドと結果を添えてください。

| # | 実装した内容 | 確かめてほしいこと |
| --- | --- | --- |
| **1** | **B1**: `renderStage()` が**タイルにも枠の幅**を付ける（`tile.style.width = width + 'px'`）。`stageHeight()` の `byWidth` は**いちばん広い枠**×`perRow` で見積もる | 本当に直ったか（あなたの計測で）。**タイル幅＝枠幅**になっているか。**1200×800 の 7〜8 枚**、**1400×900 の seed 順**で溢れないか。**別の窓**（例 1024×768 / 1600×1000）や**縦横比が混ざった組**（1024² と 2048² と 96² が混ざる実データ）でも溢れないか。**見出しが読めなくなっていないか**（310 px が 135〜210 px の枠の中で省略される） |
| **2** | **`comparison.md` §2.1 の解釈変更**: 「上の表（7〜8 枚は 4×2）は**1 画面に収める**という意味で、窓が狭いときに 4×2 を強制はしない」と書き、実測（3 窓・各 3 状態）を添えた | **この解釈でよいか**を判断してください（設計判断。**あなたの意見**を求めます）。いまは 1400×900 の 8 枚が **1 行 8 枚**（162 px 角）になる。§2.1 の表どおり **4×2** にするなら 1 枚 350 px 角＝舞台に 700 px 必要で、**縦に溢れてスクロール**になる（「1 画面に並べる」と矛盾）。どちらが設計の意図に合うか、**代案つき**で |
| **3** | **F2**: `test_stale_tmp_files_are_cleaned_at_startup` を `flush_dirty()` 経由に変えた | これで**本当に守るか**（`flush_dirty()` の先頭の `clean_stale_tmp()` を消せば落ちる形か）。他に「直接呼ぶだけ」のテストが残っていないか |
| **4** | **C2**: 顔ぶれが変わったら `state.order = 'input'` に戻す（`syncOrderLabel()` に集約） | 開き直しで**入力順に戻る**か。`r` の巡回・ボタン表示・`state.views` / `selected` の保持と矛盾しないか。**同じ 8 枚を基準だけ変えて開き直したとき**は並びが保たれるか（`sameIds` の分岐） |
| **5** | **D5**: 語の差分・日本語原文の**行の並び**も `displayIndex()` 順に | 行が画面の番号順に並ぶか。**基準の行**（`基準` / `全`）の位置が変わっていないか。値の対応（`per_asset` の引き方）が崩れていないか |
| **6** | **C1(b)**: `reason_codes[]` を**その文書が参照している理由だけ**に絞る（`export.py` の `_referenced_reason_ids()`。契約 `schemas/review-export.schema.json` の `description` も更新） | **改名の食い違いが消えたか**（参照しないファイルに旧名のマスタが残らないか。あなたの前回の再現手順で）。**`reason_codes` が空の文書**が出ないか（判断の無い画像だけの `scope=asset:` など。契約は `required` なので**空配列でも型は合う**が、他ツールが困らないか）。`scope=all` では参照する全部が入るか。**決定性**（`generated_at` を除いて同一）が保たれているか。鍵名で拾う実装（`endswith("reason_code_id")`）が**取りこぼし・拾い過ぎ**をしないか |
| **7** | **README:161** の古い記述（「と `scope=all` の GET」）を直した | 他に古い記述が残っていないか（`README.md` 全体を軽く見る） |
| **8** | **新設 `tools/gui_layout.mjs`**（Chrome headless + CDP で 3 窓 × 3 状態を検査。`outside === 0` と `tile === frame` を見る） | **検査として甘くないか**（偽陰性: 本当の崩れを見逃す。偽陽性: 正しい描画で落ちる）。`--dump` / `--viewport` の使い勝手。**CI や手順に載せられる形か**（サーバが要る、Chrome の path 固定、profile の後始末）。あなたの `page_fix.js` と**見ているものが同じか**（同じ穴を別の道具で見ているだけになっていないか） |

## 2. 報告の形式

`docs/p5-fix2-audit-report.md` に:

```markdown
# 追加 6 件の再監査報告（実行込み）

- 監査した版 / **実行できたかどうか（実行したコマンドと結果）**
- 総合判定: 使える / 条件つきで使える / 作り直す

## A. 直っていない（必ず直す）
## B. 直っているが別の問題が残る（重大）
## C. 中程度
## D. 軽微
## E. 設計文書とのずれ
## F. テスト・検査が守っていないもの
## G. 依頼者への質問（**§1-2 の解釈の判断を必ず入れる**）
## H. 今回も確かめられなかったこと
## R. 6 件それぞれの判定（1 行ずつ: 番号・判定・根拠）
```

- 各項目に**必ず「場所」**と**実行したコマンド / 再現手順**。
- 問題が無いと確認した観点は 1 行で「確かめた結果、問題なし」。
- 最後に**最も重大な 3 件**を理由 2〜3 文で。

## 3. 往復

```powershell
orca orchestration send --to run:run_5cb7f377da7d --type status --subject fix2-audit-done `
  --body (Get-Content -Raw $env:TEMP\fix2-audit.txt) --json
```

- subject は途中経過 `fix2-audit-mid`、完了 `fix2-audit-done`。
- **6 件の判定が出た時点で一度**知らせてください。
