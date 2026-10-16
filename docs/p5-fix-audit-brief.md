# 監査の指示書（実行込みの再監査: 9 件の修正）

あなたは**実装の監査者**です。前回の「実行込みのやり直し」（`docs/p5-audit-redo.md` /
`docs/p5-2-audit-redo.md` / `docs/p5-3-audit-redo.md`）で出た指摘のうち、**依頼者が 9 件を実装しました**。
**その 9 件が本当に直っているか**を、独立に、**実行して**確かめてください。**回帰（新たに壊した所）も探してください。**

- 対象: `C:\work\image-reviwer`
- 出力: **`docs/p5-fix-audit-report.md` を新規に書くだけ**（既存の報告・設計文書は**書き換えない**）
- 言語: 日本語

## 0. 環境（前回と同じ）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"   # 必須
uv run pytest -q                                        # いまは 175 件（前回 169＋今回の 6）
node tools/gui_smoke.mjs                                # 47 件以上（今回 2 件足した）
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\data-p52"   # 前回のコピーが残っています
uv run image-reviewer serve --port 8791                 # 8790 は使用中。8791〜8799 は空き
```

- 前回のあなたの一時物（`.tmp-audit-redo/` の `cdp.mjs`・`page_layout.js`・`pick_ids.json`・
  データのコピー `data-p52` / `data-p5`・画面写真）は**そのまま残っています**。再利用してかまいません。
- 実データ `.data/` は **`mode=ro` のみ**。壊す試験はコピーで。**ソースは編集しない**。
- 前回と同じく、`tools/probe_p5.py` は `%TEMP%` の SQLite で落ちます（今回は直していません）。

## 1. 実装した 9 件と、確かめてほしいこと

**「直っている / 直っていない / 別の問題が残る」を 1 件ずつ判定**し、**実行したコマンドと結果**を添えてください。
コードを読んだだけの判断は「読んだだけ」と明記を。

| # | 実装した内容（ファイル） | 確かめてほしいこと（**疑ってかかってください**） |
| --- | --- | --- |
| **1** | `export.py`: `_atomic_write` の `os.replace` を try で囲み、失敗時に `tmp.unlink()`。`clean_stale_tmp()` を新設し `flush_dirty()` の先頭で呼ぶ | 失敗しても `*.tmp` が残らないか。**起動時の掃除が「書き込み中の別プロセスの一時ファイル」を消して壊さないか**（消えた側は `os.replace` で失敗→再試行に回るだけで済むか）。`flush_dirty()` を呼ぶたびに走るのが重くないか。**再試行の意味が変わっていないか**（失敗した ID が `_pending` に戻る経路） |
| **2** | `styles.css` に `td.cell.num`（`BIZ UDGothic` 優先）／`compare.js` が `kind==='num'` か `key==='seed'` の行のセルに `num` を付ける | **実際に桁が揃うか**（ブラウザで幅を実測）。`num` を付ける行の選び方が正しいか（`steps`/`cfg`/`denoise`/`幅`/`高さ`/`seed`。**付け過ぎ・付け忘れ**）。**「分からない」セルにも付いている**——それは正しいか。数字が細く小さく見えることで**読みにくくなっていないか**（前回の指摘は「揃わない」だったが、代償を見る） |
| **3** | `compare.js`: `render()` を `renderDiff()` → `renderStage()` の順に。`stageHeight()` が**見出し（`.cmp-cap`）と行間**を引く（`captionHeight()` / `stageMetrics()`） | **初回描画で 4×2 になるか**（実測: 1400×900・8 枚）。**枚数 2 / 3〜4 / 5〜6 / 7〜8 の全部**で `comparison.md` §2.1 の表どおりか。**別の窓の大きさ**（例 1200×800 / 1920×1080）でも溢れないか。`resize`・`r`・`b`・`m`・`d`（ヒートマップの開閉）の後に崩れないか。**見出しの高さの仮定**（`.cmp-cap` は `nowrap`。拡大縮小やフォント差で変わりうる）が破れないか |
| **4** | `review.py`: `PATCH /api/reason-codes/{id}` の `label` 変更で、参照しているまとまり（**まとまりの結論**＋**属する枚の現在値**）に `_touch_groups` → `_notify` | 改名で `groups/<id>.json` の `reason_label` が**実際に更新されるか**（3 秒のタイマーで）。**触るべきなのに触っていないまとまりが無いか**（例: 過去の判断だけが参照している場合。契約は「書き出し時点のマスタ」）。`position` / `active` の変更で**余計に触っていないか**。PATCH の**応答の形が変わっていないか** |
| **5** | `compare.js`: `displayIndex()` を新設し、`1`〜`8` キー・語の差分の「N 番」・日本語原文の「N 番」を**画面の並び**（`orderedIds()`）に | 似ている順・seed 順で**押した番号のタイルが選ばれるか**。語の差分と日本語原文の番号が**表の列と一致**するか。**値（`cells`/`values`）の添字はサーバ順のまま**で正しいか（取り違えが残っていないか）。**他に「人に見せる番号」でサーバ順を引いている所が残っていないか**（画面全体を探す） |
| **6** | `compare.js`: 同じ seed の文言を「差分: 同じ seed の組です（合うかは出してみるまで分かりません）」に。**「強制して出す」を常に表示**（`showForce(true)`。絵が出ているときは `showForce()` が隠す） | 文言と実際の挙動が合っているか（同じ seed で「位置が合いません」になる組で、利用者が誤解しないか）。**強制の口が常に見えることで、押してはいけない場面ができていないか**（復号を無駄に走らせる等）。`comparison.md` §2.3 の改訂（同じ seed は**手がかり**）と実装が一致しているか |
| **7** | `api/export.py`: `_export(..., write=)`。**GET は返すだけ**、`POST` の `scope=all` だけが書く | GET が**本当に書かない**か（mtime で確認）。POST は今までどおり書くか。**GET が書くことに依存していた呼び出し元が他に無いか**（GUI・`tools/`・テスト・文書）。`scope=group:` / `asset:` の挙動が変わっていないか。**返す文書が GET と POST で同じ**か（`generated_at` を除いて） |
| **8** | `review.py`: 同じ `client_token` で**中身が同じ**再送は **200**（古くても）。**その後に新しい判断が入っていれば `superseded: true`**。中身が違う再送は今までどおり 409 | 設計 §3.1/§3.2 の約束（再送 → 200）と一致するか。**`superseded` の判定が正しいか**（枚: 最新の判断が自分でない／まとまり: 最新でない or `open` に戻った）。**行が増えない**こと。**「中身が違う」409 が今も効く**こと。**古い再送で状態が巻き戻らない**こと（`superseded` を返すだけで何も書かない）。**この 200 化で壊れた前提が無いか**（前回 409 を期待していたテスト・画面） |
| **9** | `compare.py`: `COMPARE_KEYS` に `textgen_system_prompt`（kind `prompt`）と `en_source`（kind `text`）を追加。`asset_item()` の `provenance` にも写す | `diff.keys` に入り、差が出るか（`changed` / `only_in_some`）。**置き場所（`provenance`）が正しいか**（`prompts` と取り違えていないか）。**文書が無駄に大きくならないか**（system prompt は長い）。`node_types` の集合差や `params` の正規化と**同じ扱い**でよいか。`/api/groups/{id}/compare` でも出るか |

## 2. 特に見てほしい回帰（新しく壊した所）

- **`tests/` と `tools/gui_smoke.mjs` の期待を書き換えています。** とくに smoke の
  「出せる組では『強制して出す』を出さない」→「出しておく」への反転、`num` クラスの検査、
  同じ seed の文言の検査。**「テストを実装に合わせて緩めただけ」になっていないか**を見てください
  （元の主張が今も守られているか、別の守り方に置き換わっているか）。
- 新規テスト 6 件（`tests/test_export.py` の 3 件、`tests/test_review.py` の 2 件、
  `tests/test_compare.py` の 1 件）が**本当に壊すと落ちる**か（実装を一時的に戻すのは不可なので、
  読んで「何を守っているか」を判定し、**守っていないならその旨**を）。
- `export.py` の `flush_dirty()` の先頭で掃除する位置が、**書き出しの直前**として正しいか
  （`clean_stale_tmp()` を `__init__` の `flush_on_start` 経路と `app.py` の経路の両方で通るか）。
- `review.py` の `_notify()` に渡す辞書（`{"affected_group_ids": ...}`）が**他の呼び出しと形として揃っている**か。

## 3. 報告の形式

`docs/p5-fix-audit-report.md` に:

```markdown
# 9 件の修正の再監査報告（実行込み）

- 監査した版 / **実行できたかどうか（実行したコマンドと結果）**
- 総合判定: 使える / 条件つきで使える / 作り直す

## A. 直っていない（必ず直す）
## B. 直っているが別の問題が残る（重大）
## C. 中程度
## D. 軽微
## E. 設計文書とのずれ（comparison.md / p5-design.md / design.md / frontend-design.md / README.md を今回更新した）
## F. テストが守っていないもの
## G. 依頼者への質問
## H. 今回も確かめられなかったこと（＋できない理由）
## R. 9 件それぞれの判定（1 行ずつ: 番号・判定・根拠（実行したコマンド））
```

- 各項目に**必ず「場所」**（ファイルと行）と、**実行したコマンド or 再現手順**。
- **問題が無いと確認した観点は 1 行**で「確かめた結果、問題なし」。
- 最後に**最も重大な 3 件**を理由 2〜3 文で。**新しく見つけたもの**を優先。

## 4. 往復

段の区切り（9 件の判定が終わった時点、および全部終わった時点）で、依頼者へ知らせてください:

```powershell
# 1) 本文を UTF-8 の一時ファイルに書く（例: $env:TEMP\fix-audit.txt）
# 2) Orca 経由で送る
orca orchestration send --to run:run_5cb7f377da7d --type status --subject fix-audit-done `
  --body (Get-Content -Raw $env:TEMP\fix-audit.txt) --json
```

- subject は途中経過 `fix-audit-mid`、完了 `fix-audit-done`。
- 全部を一度に終えようとせず、**9 件の判定が出た時点で一度**知らせてください。
