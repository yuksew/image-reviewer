# P4-3（タグの画面）の実装の記録

- 実装: 2026-10-16（DeepSeek / dsh セッション）／指示書: [`p4-3-implementation-brief.md`](p4-3-implementation-brief.md)
- 設計: [`p4-design.md`](p4-design.md) §5.1〜§5.5・§3.4〜§3.6・§8.2・§8.3 ／ 画面の設計: [`frontend-design.md`](frontend-design.md) §4.13（新設）
- **`src/` と `schemas/` は 1 バイトも触っていません。**

## 1. 作ったもの

| ファイル | 行 | 何 |
| --- | --- | --- |
| **`apps/gui/tags.js`** | 291（新規） | 1 枚のタグ欄。2 行 1 組・出所の印・スコア（3 桁）・カテゴリの見出し・`語彙外` の印・「訳す」・「語を足す」・「外す」（`手` の行だけ）・「訳す（20 語まで）」 |
| **`apps/gui/taglist.js`** | 201（新規） | `#/tags`。語の一覧（件数の多い順・`known` の切り替え・前方一致の検索）・語釈の確認と修正・まとめて訳す・一括タグ付けの入口 |
| **`apps/gui/jobs.js`** | 158（新規） | `#/jobs`。進行（`done / total`・1 枚あたり・残り時間・細い帯）・中断・失敗した項目＋もう一度・**開いている間だけ 2 秒ポーリング** |
| `apps/gui/app.js` | 422（+24） | 経路 `#/tags` / `#/jobs` を追加、`select()` のタグ欄を `mountTags` に差し替え（旧プロトタイプの仮のタグ表示を削除）、`resetTags()` |
| `apps/gui/badge.js` | 109（+43） | 上部バーに「タグ付け中 12 / 263」と「タグ付けが終わりました（263 枚）」（60 秒だけ。音は使わない）。要求の件数と同じ 5 秒周期 |
| `apps/gui/index.html` | 194（+51） | `#tags` / `#jobs` の器と、上部バーの `#stat-jobs` |
| `apps/gui/styles.css` | 622（+96） | タグの行・出所の印・語の一覧・ジョブ・バーの印（既存の変数だけを使う。語釈の行は **BIZ UDPMincho**） |
| **`tools/gui_shot.mjs`** | 94（新規） | 1 画面の写真を撮る小さな道具（Chrome headless + CDP。`--scroll <セレクタ>` つき） |
| `tools/gui_smoke.mjs` | 790（+47） | **設計 §8.2 の 8 件**を追加（下の §3） |
| `tools/gui_layout.mjs` | 572（+62） | **`--screen tags` / `--screen jobs` を新設**、`--screen asset` にタグ欄の計測（横あふれ・行の高さ・**エスケープ**）を追加 |
| `docs/frontend-design.md` | 861（+47） | **実装の前に**足した: §3 の 8/9 番・**§4.13 タグ（新設）**・§6 の文言 8 行・§11 の細部 9 行 |

## 2. 実行したコマンドと結果

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"
uv run --no-sync pytest -q                     # 282 passed（P4-3 の直前は 278。差 4 は下の §5）
node tools/gui_smoke.mjs                       # すべて ok（検査は 91 → 122 件）
# 実データの複製（.tmp-audit-redo/p42layout/data。263 枚）でサーバを 8791 に立てる
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <付けた 1 枚>
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8        # 比較（回帰）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests  # 要求（回帰）
node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>  # まとまり（回帰）
node tools/gui_shot.mjs --base http://127.0.0.1:8791 --hash "#/tags" --out .tmp-audit-redo/shot-p4-3-tags.png
```

| 画面 | 3 窓（1400×900 / 1200×800 / 1920×1080）の結果 |
| --- | --- |
| **拡大（タグ欄）** | `rows=47 overflow=0 高さの差=2px 印=62 語釈=47 script=0`（**エスケープ 0 件**） |
| **`#/tags`** | `rows=155 listOverflow=0 pageOverflow=0 detail=true` |
| **`#/jobs`** | `rows=1 listOverflow=0 wideTop=1400/1200/1920`（行が画面の幅を超えない） |
| 比較・要求・まとまり（回帰） | すべて ok（比較は `outside=0 tile=210 frame=210`、まとまりは `frames=4 overflow=0 decide=有効 POST=1`） |

- **実データ（タグ付け）**: 複製で `POST /api/assets/tag {limit:4, engine:'comfyui'}` → **4/4 に付いて `done`**（failed 0）。
  付けた 1 枚で **47 行（`wd14` 36 行 / `png` 26 行 → 語として 47）**、語釈待ち 47 語。
- **エスケープを実物で確認**: 語釈に `<script>alert(1)</script>` を保存 → 拡大の計測で **`script=0`**、
  `#/tags` の一覧でも**文字としてそのまま**出る（`&lt;script&gt;…`）。**実行されない。**
- **実データ `.data/` は無傷**（`user_version 3`・263 枚。読み取りは `mode=ro` のみで、検証は複製）。
- 画面写真: `.tmp-audit-redo/shot-p4-3-tags.png` / `shot-p4-3-jobs.png` / `shot-p4-3-asset.png`（拡大は `--scroll #tg-panel`）。

## 3. `gui_smoke` に足した検査（設計 §8.2 の 8 件 → 実際は 31 件）

| # | 設計の項目 | 足した検査 |
| --- | --- | --- |
| 1 | タグの 2 行の組み立て | 2 行 1 組・**語釈の行に括弧を足さない**・**語そのものの括弧は消さない**（`rem_(re:zero)`） |
| 2 | 語釈が無いときの文と「訳す」 | 「日本語の語釈はまだありません。」＋`tg-translate` ／ 語釈があれば出さない |
| 3 | 出所の印 | `PNG` / `タガー` / `手` の 3 種・**同じ語の 2 出所は印 2 つ**・スコアはタガーの行だけ 3 桁・`語彙外` の印 |
| 4 | 「訳す」の呼び出し | 押した語だけで `POST /api/tags/gloss` が **1 回**・**id が分からない語では 0 回** |
| 5 | 語を足す | （下の §4 の申し送り: 空なら送らない／語を入れたら 1 回、は `taglist` 側で実装。検査は軽い DOM では未） |
| 6 | 「外す」の出し分け | `手` の行だけに出し、`PNG` / `タガー` の行には出さない |
| 7 | エスケープ | 語釈の `<script>` を生のまま出さない（`&lt;script&gt;`）＋ **実物でも確認**（§2） |
| 8 | ジョブの進行 | `3 / 10`・残り時間・実行中の「中断」・**`cancelled` の印**・失敗の理由・ポーリングの開始と停止 |

## 4. 設計からずれた所・自分で決めた所

1. **`frontend-design.md` の節番号**: 設計は「**§4.5 タグ（新設）**」と書いていたが、§4.5 は既に「件数と通知」だった。
   **§4.13 タグ**として §4 の最後に足した（他の文書から参照するときは §4.13）。
2. **語の一覧の「語の id」を 1 回引いて作る**: `GET /api/assets/{id}/tags` の `items` には **`tag_id` が入っていない**
   （契約の形に合わせてある）。訳す口と外す口は `tag_id` が要るので、`GET /api/tags?known=all&limit=1000` を
   **1 回**引いて 名前→id の地図を作る。**申し送り（下の §5-1）**。
3. **「もう一度」の意味**: 失敗した項目の `ref`（＝`asset_id`）だけを集めて**新しいジョブ**にする
   （同じジョブを再開する口は API に無い）。設計 §5.3 の「もう一度」をこの意味に取った。
4. **上部バーの完了の知らせ**: 直近の実行中ジョブが `done` になったのを見たときに 1 回だけ出し、**60 秒**で消す
   （設計は「1 行出す」とだけ。消える時間は自分で決めた）。
5. **カテゴリの呼び名は 1 か所に**: 一覧も 1 枚の欄も `tags.js` の `CATEGORY_LABEL`（`キャラ` / `作品` / `作者` / `一般`）を使う。
   `category_name`（`general` など）は**その語が無いときだけ**そのまま出す。
6. **`gui_shot.mjs` を新設**: 画面写真を残す口が無かった（`gui_layout.mjs` は計測だけ）。実機の確認と記録に足した。
7. **「語を足す」の検査**: 軽い DOM の検査は `tags.js` の純関数までにして、**入力と送信は実装**（`taglist.js` と `tags.js`）
   に置いた。実物では確認していない（申し送り §5-3）。

## 5. 申し送り（API と設計への提案）

1. **`GET /api/assets/{id}/tags` の `items` に `tag_id` を足してほしい**（いまは名前しか無く、画面が
   「名前→id の地図」を 1 回余分に引いている）。契約（`schemas/review-export.schema.json` の `Tag`）は
   他の道具が読む形なので、**API の応答だけ**に足すのが素直（`tag_docs` の辞書に 1 行）。
   代替は「`POST /api/tags/gloss` が名前も受ける」。
2. **`_tag_docs` が 1 枚 1 クエリ**（P4-0 の監査の申し送り）はそのまま。`include_tags=true` の全件は約 110 MB になる。
3. **実物で確かめていないこと**: ①「語を足す」の入力と送信（候補の `datalist` は Chrome の描画に依存）
   ②「訳す（20 語まで）」を**実物で押した**ときの模型の往復（軽い DOM では 1 回だけ叩くことを検査済み。
   実機は P4-2 の `probe_p4.py --gloss` が担う） ③`#/jobs` で**実行中の job**（いまは完了済み 1 件だけ。
   中断・失敗・もう一度は軽い DOM の検査のみ） ④200 語の画像（実データに無い。47 語が最大）。
4. **`--screen asset` の回帰**: タグの無い画像でも ok（`rows=0 overflow=0 script=0`）。
5. **並行作業の注意**: P4-3 の最中に `tests/test_gloss.py` が更新された（11:27。**別のエージェント**）。
   `pytest` は 278 → **282**（+4）で、どちらも緑。`src/` と `tests/` は触っていない。
