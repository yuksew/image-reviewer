> **廃止（2026-10-17。利用者の判断）**: この段は**削除しました**。理由と控えは [`p7-decision.md`](p7-decision.md) を見てください（①PNG を ComfyUI にドラッグすればワークフローが戻るので記録は重複 ②ja2en の英訳も実行すれば取り直せる）。**記録として残しています。**

# 監査の指示書（P7-1: 記録と判定）

あなたは**実装の監査者**です。**P7-1（記録と判定。R12 の前半）**を監査してください。

- 対象: `C:\work\image-reviwer` ／ 出力: **`docs/p7-1-audit-report.md` を新規に書くだけ** ／ 言語: 日本語 ／ **実行してよい**

## 0. 環境（**利用者のアプリが 8790 で動いています**）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"      # 必須
uv run --no-sync pytest -q                                  # ★ --no-sync。いま 340 件
node tools/gui_smoke.mjs                                    # 129 件
uv run --no-sync python tools/probe_p7.py --judge           # 実データの複製 263 枚で判定（--keep で残す）
uv run --no-sync python tools/probe_p7.py --http            # 複製にサーバを立てて口から数枚
```

- **実データ `.data/` は `mode=ro` のみ**（**すでに v6**・263 枚・判断 3 件・`recipe_record` は 0 行）。壊す試験は複製で
  （**`sqlite3` の `backup()` で WAL を畳む**）。**`.backup/` は消さない**。
- **利用者のアプリ（8790）は P7 より前のコードで動いています**（P7 の口を載せるには再起動が要る。**あなたは止めないでください**）。
- 一時物は `.tmp-audit-redo/`。**ソースは編集しない**。**`git` のコミットもしない**。
- **ComfyUI（127.0.0.1:8188）は `GET` だけ**（`/object_info/{class_type}` を含む）。**画像は生成しない**。

## 1. P7-1 で入ったもの

- 設計: [`p7-design.md`](p7-design.md) **§0.5（再現キー＝グラフだけの純関数）/ §0.6（判定と理由。記録時は 7 語だけ）/ §0.7（グラフの置き場）/ §0.10（`GET` は書かない・`actor`・`client_token`）/ §2.1（表。もう在る）/ §3.1〜§3.2（記録の口）/ §4（状態）/ §7（性能）/ §8.1（テストのうち P7-1 の担当）/ §9 の P7-1 の行**
- 実装の記録: [`p7-1-implementation.md`](p7-1-implementation.md)（**自分で決めた 4 点・見つけた穴 4 件・申し送り 4 件**）
- 主なファイル: `src/image_reviewer/recipe.py`（**新規 642 行**）/ `src/image_reviewer/api/recipes.py`（新規）/ `api/__init__.py` / `app.py` / `tests/test_recipe.py`（**430 行・23 件**）/ `tools/probe_p7.py`（新規）

## 2. 確かめてほしいこと

1. **線 1・2 をあなたの手で**（§1.2）:
   - **線 1**: 実データの複製で `POST /api/assets/{id}/recipe` を**グラフありの 1 枚**と**グラフ無しの 1 枚**に打ち、
     `GET` が `status` と `reasons` を返すか（グラフ無しは **`impossible` ＋ `missing`**）。
   - **線 2**: `tools/probe_p7.py --judge` が **`exact` 182 / `approx` 1 / `impossible` 80** を出すか（**自分で回す**）。
     **1 枚の `approx` が ja2en の画像**（`CLIPTextEncode` はあるが文字列が不明＝`text_not_captured`）であることを**確かめる**
     （設計 §1.2 の数を**この実測に直した**。点検の「183 / 0 / 80」は誤り）。
2. **`recipe_hash` が「グラフだけの純関数」か**（§0.5）。**環境の値（`size` / `mtime` / ComfyUI 版 / GPU）を混ぜていない**か。
   **印（`filename_prefix`）を変えても鍵が変わらない**か。**seed を変えると鍵が変わる**か（実データで 180/180 だったという点検の実測と比べる）。
   **`_meta` を除いている**か。**リテラルと結線を分けて記録**しているか。**キー昇順・空白なし**か。
3. **判定の規則**（§0.6）: **記録時の `reasons` が 7 語だけ**か（`text_pinned` などを記録時に付けていないか）。
   **`text_not_captured` が「到達部分グラフに `CLIPTextEncode` があるのに文字列が分からないとき」だけ**か。
   **`unresolved` を原因で分けている**か（モデルが combo に無い→`impossible`／入力キーの差→`approx` ＋キー名）。
   **動的コンボ（`COMFY_DYNAMICCOMBO_V3`）を展開してから照合**しているか（**展開を外すと落ちるテストがあるか**）。
   **展開できない `COMFY_DYNAMIC*` は検査の対象外にして `notes` に出している**か。
4. **`/object_info` の引き方**: **`/object_info/{class_type}` だけ**引き、**2.39 MB の一括を引いていない**か（§7・点検 B-2）。
   **1 枚あたりの時間**を測り直す（実装者の値: 中央 1.1 ms・平均 2.1 ms・最悪 146 ms）。
5. **グラフの置き場**（§0.7）: `<data>/workflows/<sha256>.json` に**原子的に**書いているか（一時ファイル → `os.replace`。
   **失敗したら一時ファイルを消す**）。**PNG から作り直せる**か（無ければ `graph_path: null`）。
   **同じ内容なら同じファイル**（上書きで増えない）か。
6. **口**（§3.1〜§3.2）: **`GET` は 1 バイトも書かない**か（**複製の全ファイルの size / mtime と行数**の前後で確かめる）。
   **`actor` をヘッダから**取っているか。**`client_token` の再送は 200 で既存**（**行が増えない**）か。
   **画像 1 枚に 1 記録**（`ux_recipe_source`）か。**`POST` に `Host: evil` / `Content-Type: text/plain` で 403** か。
7. **`env_snapshot` と `record_json`** の中身（§4.1）。**取れなかった項目は `null` で明示**か。**`graph_source` は `png` だけ**か（P7 では）。
8. **テストが本当に落ちるか**（`tests/test_recipe.py` の 23 件）。**壊すと落ちる**形か。
   **実装者が自分で見つけた 4 件の穴**（`reasons` の形の不一致・**コンボ判定の誤り**・`canonical_graph` の形・`node_missing` の意味）に
   **テストがあるか**（とくに**`["STRING", {…}]` を選択肢と誤認しない**こと）。
9. **回帰**: `pytest` **340**・`gui_smoke` **129**・`gui_layout`（6 画面）が緑か。**`GET` が書かない**ままか。
   **実データの `recipe_record` が 0 行のまま**か（`.data` を触っていないか）。
10. **実装者が自分で決めた 4 点**と**申し送り 4 件**（`graph_source` は `png` のみ・**口が 1 回ごとに `ComfyProbe` を作る**
    （263 枚で約 3,000 回の `/object_info/{class_type}`）・`ON DELETE` は P7-2・`reasons` の形を統一）を判定する。

## 3. 報告の形式

`docs/p7-1-audit-report.md` に、これまでと同じ形（A 直っていない / B 重大 / C 中程度 / D 軽微 /
E 設計とのずれ / F テストが守っていないもの / G 依頼者への質問（推奨つき）/ H 確かめられなかったこと）。
各項目に**場所**と**実行したコマンド / 再現手順**。最後に**最も重大な 3 件**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p7-1-audit-done `
  --body (Get-Content -Raw $env:TEMP\p7-1-audit.txt) --json
```

- subject は `p7-1-audit-start` / `-mid` / `-done`。待たずに続けて `G` に推奨つきで書いてください。
