# 監査の指示書（P6-1b: 要求まわりの画面）

あなたは**実装の監査者**です。**P6-1b（`#/requests` と `#/group/<id>`、件数とタブのタイトル）**を監査してください。

- 対象: `C:\work\image-reviwer`
- あなたの出力: **`docs/p6-1b-audit-report.md` を新規に書くだけ**
- 言語: 日本語

## 0. 環境（実行してよい）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"   # 必須
uv run pytest -q                                        # いま 208 件が緑
node tools/gui_smoke.mjs                                # 73 ok
# サーバはデータのコピーで。要求を作ってから画面を見る
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\data-p52"
uv run image-reviewer serve --port 8791
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>   # 実装者が足した口（--help を見る）
```

- 実データ `.data/` は **`mode=ro` のみ**。**ソースは編集しない**。一時物は `.tmp-audit-redo/`。
- **PowerShell の `Invoke-RestMethod` で日本語の JSON を投げると本文が化けます**（実装者が踏んだ。`curl.exe --data-binary @file` を使う）。

## 1. P6-1b で入ったもの

- 設計: [`p6-design.md`](p6-design.md) §5.1（要求の一覧）・**§5.1b（まとまりレビューの最小形）**・§5.4（件数と知らせ方）・§5.5（`frontend-design.md` に足すもの）・§8.2（smoke で守るもの）・§8.3（layout で見るもの）・§1.2 の**合格の線 2**
- 実装の記録: [`p6-1b-implementation.md`](p6-1b-implementation.md)（**自分で見つけて直したバグ 3 件**と、**API に足りないと思う点 4 つ**が書いてある）
- 主なファイル: `apps/gui/requests.js`（新規）/ `apps/gui/group.js`（新規）/ `apps/gui/badge.js`（新規）/ `index.html` / `styles.css` / `app.js` / `docs/frontend-design.md`（+52）/ `tools/gui_smoke.mjs`（+22）/ `tools/gui_layout.mjs`（`--screen`）
- 画面写真: `.tmp-audit-redo/shot-p6-1b-requests.png` / `shot-p6-1b-group.png`

## 2. 確かめてほしいこと

1. **合格の線 2 をあなたの手で通す**（設計 §1.2 の 2）: 要求を作る → `#/requests` から開く →
   `#/group/<id>` で 1 枚選び理由を選んで「この 1 枚に決める」 → `GET /api/review-requests/{id}` が
   **`done`** で `response.selected_asset_ids` が選んだ 1 枚と一致 → **`reopen` しても `response` は
   変わらない**（`annotations` を除く）。**ブラウザで**（Chrome headless + CDP。既存の `tools/gui_layout.mjs`
   と `.tmp-audit-redo/cdp.mjs` が使える）。
2. **画面の作り**（`frontend-design.md` と突き合わせる）:
   - カード: `ask` / `conditions` / `origin` / **AI の推しと理由** / 経過 / 状態。**`esc()` が効く**か
     （`<script>` や `"` を入れた要求で**生のまま出ない**こと。`gui_smoke` の検査だけでなく**実物**で）。
   - 「断る」: 理由が空なら**送らない**（`fetch` が呼ばれない）。理由つきで `POST .../decline` が**1 回だけ**。
   - 「あとで」: **何も書かない**（API を叩かない）。
   - 空の状態の文言。0 件のときバーの件数とタブのタイトルが**元に戻る**か。
   - まとまりレビュー: フィルムストリップ・理由の選択（`applies_to=reject`）・**全部ボツ**（理由必須）・
     **「選んだ 1 枚を拡大で開く」→ `#/asset/<id>`**（注記の入口。前回の点検 C13）。
   - **キーが無くてもマウスだけで完結**するか（P5 の原則）。
3. **件数とタブのタイトル**（§5.4）: 5 秒ごとに `count_only=1` を叩くか。**画面を離れたら止まる**か
   （止まらないと無駄なポーリングが残る）。タブのタイトルが `(N) image-reviewer` になり、0 で戻るか。
4. **`app.js` の経路**: `#/requests` / `#/group/<id>` / `#/asset/<id>` が壊れていないか。
   **既存の画面（一覧・拡大・比較）が変わっていない**か（回帰）。
5. **テストが本当に落ちるか**: `tools/gui_smoke.mjs` の +22 件と `tools/gui_layout.mjs` の `--screen requests`。
   **実装者が自分で見つけたバグ 3 件**（カードの入れ子・`decide` の名前隠し・競合で二重描画）を、
   **もう一度壊すと落ちる**形になっているか（とくに 1 と 3 は軽い DOM では見えなかった。**本物の Chrome で
   見る検査に入っているか**）。
6. **API に足りないという申し送り 4 件**（一覧が対象の並びを返さない／`GET /api/groups/{id}` に来歴が無い／
   `?group_id=` が無い／`counts` が `open` だけ）を、**P6-2 の後で足すべきか、いま足すべきか**、
   あるいは**足さない方がよいか**を判定する（実装は画面側で回避している。回避の費用も見る）。
7. **回帰**: `pytest` 208・`gui_smoke` 73・`gui_layout`（比較と要求の両方）が緑か。P5 の判断・比較・
   書き出しが変わっていないか。**`GET` が書かない**ままか。
8. **実装者が決めた所**（`p6-1b-implementation.md` にある）を 1 つずつ妥当か判定する。

## 3. 報告の形式

`docs/p6-1b-audit-report.md` に、これまでと同じ形（A 直っていない / B 重大 / C 中程度 / D 軽微 /
E 設計とのずれ / F テストが守っていないもの / G 依頼者への質問（推奨つき）/ H 確かめられなかったこと）で。
各項目に**場所**と**実行したコマンド / 再現手順**。最後に**最も重大な 3 件**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p6-1b-audit-done `
  --body (Get-Content -Raw $env:TEMP\p6-1b-audit.txt) --json
```

- subject は `p6-1b-audit-mid` / `p6-1b-audit-done`。**依頼者は寝ている**ので、質問は `G` に書いて待たずに続けてください。
