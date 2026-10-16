# 監査の指示書（P4-3: タグの画面）

あなたは**実装の監査者**です。**P4-3（`#/asset/<id>` のタグ欄・`#/tags`・`#/jobs`。P4 の最後の段）**を監査してください。

- 対象: `C:\work\image-reviwer` ／ 出力: **`docs/p4-3-audit-report.md` を新規に書くだけ** ／ 言語: 日本語 ／ **実行してよい**

## 0. 環境

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"      # 必須
uv run --no-sync pytest -q                                  # ★ --no-sync（利用者のサーバが .venv の exe を握っている）
node tools/gui_smoke.mjs
# 画面は本物の Chrome で。検証のサーバは実データの複製（sqlite3 の backup() で WAL を畳む）
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\<自分で作った複製>"
uv run --no-sync image-reviewer serve --port 8791
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <id>
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8        # 比較（回帰）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>
```

- **`image-reviewer.exe serve --port 8790`（利用者のアプリ）が `.venv` の exe を握っているので、`uv run` の再インストールが `os error 32` で落ちます。必ず `--no-sync`。**
- 実データ `.data/` は `user_version = 3`・263 枚（**触らない**。`mode=ro` と `backup()` のみ）。**`.tmp-audit-redo/p42layout/data`（263 枚・まとまり 1 つ）**が使えます。
- 一時物は `.tmp-audit-redo/`。**`.backup/` は消さない**。**ソースは編集しない。**
- **ComfyUI（127.0.0.1:8188）は動いています**。**投げてよいのは「タグ付け」と「訳」だけ**。

## 1. P4-3 で入ったもの

- 設計: [`p4-design.md`](p4-design.md) **§0.7（括弧は消さない）/ §0.8（`known` の印と検索の既定）/ §1.2 の線 3（2 行で出る）/ §3.4〜§3.6（タグと語釈の口）/ §5.1〜§5.5（画面の挙動・`frontend-design.md` に足すもの・知らせ方）/ §8.2（`gui_smoke` の 8 件）/ §8.3（`gui_layout` の 4 件）/ §9 の P4-3 の行**
- 実装の記録: [`p4-3-implementation.md`](p4-3-implementation.md)（自分で決めた点・申し送り・設計の穴）
- 指示書: [`p4-3-implementation-brief.md`](p4-3-implementation-brief.md)（**何を作ると指示したか**。ここからの逸脱も見る）
- 主なファイル: `apps/gui/`（`app.js`・新しい画面のモジュール・`index.html`・`styles.css`）、`docs/frontend-design.md`、`tools/gui_smoke.mjs`、`tools/gui_layout.mjs`

## 2. 確かめてほしいこと

1. **線 3 をあなたの手で**（§1.2）: `#/asset/<id>` のタグ欄の各行が「英語の行」＋「語釈の行」の **2 行 1 組**であること。
   **行の本文に `(` と `)` が無い**（語釈の行に括弧書きを足していない）。**語そのものの括弧は残っている**（`rem_(re:zero)`）。
2. **画面の作り**（`frontend-design.md` §4.5・§6・§11 と突き合わせる）:
   - **並び**（カテゴリ 4 → 0 → 他 → スコア降順（NULL 最後）→ 名前）。**無いカテゴリの見出しを出さない**。
   - **出所の印**（`PNG` / `タガー` / `手`）。**スコアはタガーの行だけ 3 桁**。同じ語の 2 出所は印 2 つ。
   - **`known=false` の印**。**「訳す」は語釈が無い語にだけ**、**「外す」は `manual` の行にだけ**。
   - **「語を足す」**（候補が `GET /api/tags?q=` の前方一致で出るか。空なら送らないか）。
   - **タガーの限界の 1 行**。
   - **`#/tags`**: 件数順・既定 `known=1`・`?q=` 検索・語釈の確認と修正・20 語まで訳す・一括タグ付けの入口。
   - **`#/jobs`**: `done / total`・1 枚あたり・残り時間・**中断**・失敗した項目（先頭 20 件）・**`queued` は「待っています」**。
3. **`esc()` が実物で効く**か。**語釈に `<script>` を入れて**、生のまま出ないこと（**軽い DOM ではなく Chrome で**。
   P6-1b の監査で「`gui_smoke` では見えず、本物の Chrome で見つかった穴」が 3 件あった）。
4. **ポーリング**: `#/jobs` が **2 秒ごと**か。**画面を離れたら止まる**か（P6-1b の監査と同じ観点）。
   **上部バーの知らせ**（タグ付けが終わったら 1 行・進行中は `#/jobs` に 1 つあること）が**音を使っていない**か。
5. **`gui_smoke` の 8 件**（§8.2）と **`gui_layout` の 4 件**（§8.3: `listOverflow=0`・**200 語で縦に伸びるだけ**・**100 語で行の高さが揃う**・
   `#/tags` と `#/jobs` が 3 窓で `overflow=0`）。**新しい画面の検査が実物（Chrome）で入っているか**。
6. **実機で 1 枚**（実データの複製）: タグを付けて（`POST /api/assets/tag`。`IllustTagger` なら 0.3 秒/枚）→
   画面で 2 行表示・印・スコア → 「訳す」→ 語釈が出る、を**あなたの目で**確かめ、**画面写真**を残す。
7. **`GET` に副作用が無い**か（画面の読み込みで `tag_gloss` / `asset_tag` が増えないこと）。
   **人為の操作（語を足す・外す・訳す・直す）が `human` で送られている**か（`X-Image-Reviewer-Actor`）。
8. **回帰**: `pytest`（**278 + 新規**）・`gui_smoke`・`gui_layout` の**4 画面（比較・要求・まとまり・注記）**が緑か。
   **`GET` が書かない**ままか。P5 / P6 / P4-1 / P4-2 の口と契約が変わっていないか。**実データ `.data/` の mtime が変わっていない**か。
9. **実装者が自分で決めた点**（`p4-3-implementation.md`）と**指示書からの逸脱**を 1 つずつ妥当か判定する。
10. **設計とのずれ**: 実装が `docs/p4-design.md` §5 と違う所。**設計が黙っているのに実装が決めた**所。

## 3. 報告の形式

`docs/p4-3-audit-report.md` に、これまでと同じ形（A / B / C / D / E / F / G（推奨つき）/ H）。
各項目に**場所**と**実行したコマンド / 再現手順**。最後に**最も重大な 3 件**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p4-3-audit-done `
  --body (Get-Content -Raw $env:TEMP\p4-3-audit.txt) --json
```

- subject は `p4-3-audit-start` / `-mid` / `-done`。待たずに続けて `G` に推奨つきで書いてください。
