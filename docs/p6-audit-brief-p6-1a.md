# 監査の指示書（P6-1a: 要求の API）

あなたは**実装の監査者**です。**P6-1a（エージェントからの要求の API。画面は含まない）**を監査してください。

- 対象: `C:\work\image-reviwer`
- あなたの出力: **`docs/p6-1a-audit-report.md` を新規に書くだけ**
- 言語: 日本語

## 0. 環境（実行してよい）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"   # 必須
uv run pytest -q                                        # いま 203 件が緑
node tools/gui_smoke.mjs                                # 51 ok
uv run python tools/probe_p6_1a.py                      # HTTP の計測（uvicorn を自分で立てる）
uv run --no-project --with jsonschema python tools/check_contract_p6.py
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\data-p52"
uv run image-reviewer serve --port 8791
```

- 実データ `.data/` は **`mode=ro` のみ**。壊す試験はコピーで。**ソースは編集しない**。一時物は `.tmp-audit-redo/`。

## 1. P6-1a で入ったもの

- 設計: [`p6-design.md`](p6-design.md) §3.1〜§3.5（口）・§0.2〜§0.4（応答の保存・上書き・判断で閉じる）・§4.1（状態）・§6.1（契約）・§8.1（テスト）
- 実装の記録: [`p6-1a-implementation.md`](p6-1a-implementation.md)（**実装者が自分で決めた 9 点と、見つけた設計の穴 6 件**が表になっている。ここが最重要）
- 主なファイル: `src/image_reviewer/review_requests.py`（新規 508 行）、`src/image_reviewer/api/requests.py`（新規）、`review.py`（`decide` と同一取引で閉じる・`closed_request_ids`・`list_groups`）、`export.py`（`requests[]` の充填）、`tests/test_requests.py`（新規 21 件）、`tools/probe_p6_1a.py` / `tools/check_contract_p6.py`（新規）

## 2. 確かめてほしいこと

1. **検査の順序の逸脱**（実装者自身が「設計から意図的にずらした」と申告した点）。設計 §3.2 は
   「`client_token` の照合を最初に行い、一致すれば `target_key` を見ない」だが、実装は
   **①対象の解決 → ②`client_token` の照合 → ③業務検査（`decided` の 422 など）→ ④差し替え → ⑤INSERT**。
   実装者の理由は「再送で id 送り・パス送り・`group_id` 送りを同一視できる」「`decide` / `decline` 後の再送も
   200 にしたい」。**この順序で穴が開かないか**（とくに「照合より前に業務検査がある」ことで、
   再送が 422 になったり、行が 2 つになったりしないか）。**書き込みより前**であることは保たれているか。
2. **差し替え（`superseded`）**。**古い `open` を UPDATE してから INSERT**（逆だと部分 UNIQUE で落ちる）。
   同じ `target_key` の**同時投入**（別接続 × 8）で `open` が 1 本・他は `superseded` になるか。
   `done` / `declined` は触られないか。`superseded_by` の連鎖が 1 本に繋がるか。
   **古いまとまりに判断が無いときだけ** `review_group.superseded_by` が入るか（判断があるときは残す）。
3. **判断で閉じる**。`decide` の**同じ取引**で要求が `done` になり、`response`（選ばれた枚・理由・メモ）が入るか。
   **`reopen` しても `response` は変わらない**か（点検 B3。`annotations` を除いて比較）。
   **判断の後に付けた注記が `response.annotations` に入る**か（読むとき導出）。
   `closed_request_ids` が正しいか（実装者は「再送経路では `decided_at` と `closed_at` の一致で近似」と申告。
   **同じ秒に reopen → 再 decide すると 1 つ前を拾いうる**と自分で書いている。**実際に再現するか**、
   するなら害は何か）。
4. **断る（`decline`）**。`human` 以外 403・空の `note` 422・同じ `note` の 2 回目 200・違う `note` 409
   `request_not_open`。`client_token` を使っていないこと（点検 B5）。
5. **一覧と取得**。キーセット（`created_at DESC, id DESC`）が**取りこぼし・重複なく**ページングできるか
   （同じ秒に複数入れて試す）。`target_key` の絞り込み。`count_only`。**どちらの `GET` も書かない**か
   （P5 の C8/G2 と同じ観点）。
6. **契約**。`scope=all` / `group:` / `asset:` の `requests[]` が設計どおり入るか（`superseded` も残る）。
   本物の `jsonschema` で通るか。**`response` が契約の形か**（`annotations` は id の配列）。
   **決定性**（`generated_at` を除いて 2 回同一）。
7. **守り**。新しい `POST`（受付・`decline`）に `Host: evil` / `Content-Type: text/plain` で **403**。
8. **性能**。§1.2 の線（`POST` 8 枚で **p95 150 ms**、一覧 1,000 件で **p95 20 ms**）を**あなたの手で測り直す**。
   実装者の値（1.5 / 2.8 ms）と桁が合うか。**測り方**（keep-alive か毎回接続か）も書く。
9. **テストが本当に落ちるか**（§8.1 の 1〜11・24〜27 の P6-1a 担当分）。とくに
   「上書きの判定と更新を**別の取引**に分けると落ちる」形になっているか（点検 C9）。
10. **実装者が自分で決めた 9 点**（`p6-1a-implementation.md` の表）を 1 つずつ見て、**妥当か**を判定する。
    とくに: 要求のまとまりの `title` を `ask` から取る／`limit` を 1〜200 に丸める（422 にしない）／
    `counts` が `open` だけ／再送の応答が「いまの状態」／`response.annotations` が id 文字列。
11. **実装者が挙げた設計の穴 6 件**（同 §4）も見て、**P6-1b / P6-2 に持ち越してよいか**を判定する。
12. **回帰**。`pytest` 203・`gui_smoke` 51 が緑か。P5 の判断・比較の口が変わっていないか。
    `GET /api/export/review.json` が**書かない**ままか。

## 3. 報告の形式

`docs/p6-1a-audit-report.md` に、これまでと同じ形で:

```markdown
# P6-1a（要求の API）の監査報告
- 監査した版 / **実行できたかどうか（実行したコマンドと結果）**
- 総合判定: 使える / 条件つきで使える / 作り直す
## A. 直っていない（必ず直す）
## B. 直っているが別の問題が残る（重大）
## C. 中程度
## D. 軽微
## E. 設計とのずれ（とくに §2-1 の検査順序の逸脱の妥当性）
## F. テストが守っていないもの
## G. 依頼者への質問（推奨つき。朝に読む）
## H. 確かめられなかったこと
```

- 各項目に**場所**と**実行したコマンド / 再現手順**。実行していないことは「実行していない」と明記。
- 最後に**最も重大な 3 件**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p6-1a-audit-done `
  --body (Get-Content -Raw $env:TEMP\p6-1a-audit.txt) --json
```

- subject は `p6-1a-audit-mid` / `p6-1a-audit-done`。**依頼者は寝ている**ので、質問は `G` に書いて待たずに続けてください。
