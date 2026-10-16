# 監査の指示書（P6-2: 注記と切り出し）

あなたは**実装の監査者**です。**P6-2（注記。R11。P6 の最後の段）**を監査してください。

- 対象: `C:\work\image-reviwer` ／ 出力: **`docs/p6-2-audit-report.md` を新規に書くだけ** ／ 言語: 日本語

## 0. 環境（実行してよい）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"   # 必須
uv run pytest -q                                        # いま 222 件が緑
node tools/gui_smoke.mjs                                # すべて ok（注記 4 件を追加済み）
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\data-p52"
uv run image-reviewer serve --port 8791
uv run python tools/probe_p6_2.py --base http://127.0.0.1:8791
uv run --no-project --with jsonschema python tools/check_contract_p6.py
```

- 実データ `.data/` は **`mode=ro` のみ**。**ソースは編集しない**。一時物は `.tmp-audit-redo/`。
- PowerShell の `Invoke-RestMethod` は日本語の JSON を化けさせる（`curl.exe --data-binary @file` を使う）。

## 1. P6-2 で入ったもの

- 設計: [`p6-design.md`](p6-design.md) **§0.7（座標と切り出しの式）/ §0.8（原子性）/ §0.9（`client_token`）/ §1.2 の線 3 / §3.6（口）/ §4.2 / §6.2（契約）/ §6.3（置き場と命名）/ §7（性能）/ §8.1 の 11〜19・28〜30 / §8.2-6 / §8.3-2・3**
- 実装の記録: [`p6-2-implementation.md`](p6-2-implementation.md)（**自分で決めた 4 点**・**未実装 2 点**・**設計の穴 3 件**）
- 主なファイル: `src/image_reviewer/annotations.py`（新規）/ `src/image_reviewer/api/annotations.py`（新規）/ `apps/gui/annotations.js`（新規）/ `tests/test_annotations.py`（新規 14 件）/ `tools/probe_p6_2.py`（新規）/ `tools/gui_smoke.mjs`（+4）
- 画面写真: `.tmp-audit-redo/shot-p6-2-annotations.png` / `shot-p6-2-list.png`

## 2. 確かめてほしいこと

1. **合格の線 3 をあなたの手で**（§1.2）: 1024×1024 と 2048×1536 の絵に `{x:0.25,y:0.5,w:0.25,h:0.25}` を作り、
   `GET .../export?format=json` が**同じ座標**を返し、`POST .../export {format:'crops'}` の PNG が
   **式どおりの画素**（256×256 / 512×384）であること。**丸めずに往復**すること。
2. **切り出しの式と点検 B1**: `round(v, 6)` を挟んであるか。**1360² の `x=0, w=0.275` → 374 画素**
   （挟まないと 375）。境界（`x + w` が 1 ちょうど、`1 + 1e-9`）、1 画素クランプ、`w=0` は 422。
3. **`GET` は書かない**（§0.6）: `GET .../export?format=json` の前後で**ファイルも mtime も変わらない**か。
   `GET` の `format=crops` は **422 で `POST` を案内**するか。`GET /api/annotations/{id}/crop` が
   **ディスクに書かない**か（その場で作って返す）。
4. **原子性**（§0.8）: `os.replace` を落として `*.tmp` が 0 個か。**起動時の掃除**が `*.tmp` を消すか。
   **削除で PNG も消える**か（点検 G3）。
5. **actor と状態**（点検 C7 / D5 / A1）: `PATCH` / `DELETE` は**自分の `actor` の注記だけ**（違えば 403）か。
   2 回目の `DELETE` は **404** か。**領域なしのメモ**（座標が全部 null）が作れて、**切り出しは 422** か。
   `actor: robot` は 422 か（P6-1a の監査 A1 と同じ検査）。
6. **`annotation-export` 契約**: 本物の `jsonschema` で通るか（`crops: null` と配列の両方）。
   `Annotation` の形が `review-export` と一致しているか（テストがある）。
7. **実体が無いとき 409**、`annotation_ids` に他の画像の id を混ぜたら 422、領域なしが混ざる切り出しは 422
   （実装者の決定 3）。**その決定が妥当か**を判定する。
8. **性能**（§7）: 1024² / 2048² の切り出しの時間が**画素数比例**の範囲か。`compress_level=1` が効いているか。
9. **画面**（§8.2-6 / §8.3-2・3）: 4 px 未満では作らないか。**注記 20 個で一覧が外に出ないか**・
   **印が画像の外に出ないか**（実装者は §8.3-2・3 を**未実装**と申告。**足りない検査を特定**してほしい）。
   **まとまりレビューから拡大へ移るとき `group_id` が引き継がれない**（実装者の設計の穴 2。
   §0.2 の `response.annotations` に画面から付けた印が入らない）——**この穴の影響**を確かめる。
10. **回帰**: `pytest` 222・`gui_smoke` すべて ok・`gui_layout`（比較・要求）が緑か。P5 / P6-1 の口が変わっていないか。
    **`GET` が書かない**ままか。
11. **実装者が決めた 4 点・未実装 2 点・設計の穴 3 件**を 1 つずつ判定する。

## 3. 報告の形式

`docs/p6-2-audit-report.md` に、これまでと同じ形（A / B / C / D / E / F / G（推奨つき）/ H）で。
各項目に**場所**と**実行したコマンド / 再現手順**。最後に**最も重大な 3 件**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p6-2-audit-done `
  --body (Get-Content -Raw $env:TEMP\p6-2-audit.txt) --json
```

- subject は `p6-2-audit-mid` / `p6-2-audit-done`。**依頼者は寝ている**ので、質問は `G` に書いて待たずに続けてください。
