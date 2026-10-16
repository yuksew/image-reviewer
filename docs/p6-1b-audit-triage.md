# P6-1b 監査の仕分け（Fable の監査 → どう直したか）

- 監査報告: [`p6-1b-audit-report.md`](p6-1b-audit-report.md)（総合判定 **条件つきで使える**。A 1 / B 2 / 中程度 2 / 申し送り 4 件の判定つき）
- 立場: **推奨どおり採用**。実装は [`p6-1b-implementation.md`](p6-1b-implementation.md)。

| # | 指摘 | どうしたか |
| --- | --- | --- |
| **A1** | 「断る」の textarea を押すとカードの `click` に伝わり、一覧を描き直して**フォームが消える**（マウスだけでは理由を書けない） | **直した**（私）: `.req-decline-form` の `click` で `stopPropagation`（`apps/gui/requests.js`） |
| **B1** | 「この 1 枚に決める」で**キープの理由を集めない**ので `response.reason_code_id` / `reason_label` が常に `null`（`wants: ["reason"]` に答えられない） | **直し中**: `group.js` に「キープの理由（任意）」を足し、keep の項目に `reason_code_id` を入れて送る（`review.py` が「1 枚に決めたときはその枚のキープ理由をまとまりの理由に写す」ので `response` が埋まる） |
| **B2** | 実装者が実機で見つけた**バグ 3 件に「壊すと落ちる」検査が無い**（カードの入れ子・`decide` の名前隠し・競合で二重描画）。`--screen group` も無い | **直し中**: カード枚数を API の件数と比べる（`--screen requests`）／`#group-decide` を実際に押す検査／競合の検査／**`--screen group` を実装** |
| **中程度** | 見出しに `selected` / `all_rejected` の**英語**。`all_reject_only` でも「この 1 枚に決める」が有効 | **直し中**（日本語化、`all_reject_only` では無効化） |
| **申し送り 1** | 一覧が対象の並びを返さない（画面が最大 20 回追加取得。21 枚目から番号が消える） | **API を足した**（私）: `ai.pick_index`（1 始まり。`schemas/review-export.schema.json` と `review_requests.doc_of`）。**画面が使うよう直し中** |
| **申し送り 3** | 一覧にまとまりの絞り込みが無い（open を 200 件取って突き合わせ） | **API を足した**（私）: `GET /api/review-requests?group_id=<id>`。**画面が使うよう直し中** |
| **申し送り 2** | `GET /api/groups/{id}` に来歴が無い | **足さない**（監査の判定どおり）。選択中の 1 枚だけ `GET /api/assets/{id}` を引く |
| **申し送り 4** | `counts` が `open` だけ | **足さない**（監査の判定どおり） |
| **P6-2 の穴** | まとまりレビュー → 拡大で `group_id` が引き継がれず、その画面の注記が `response.annotations` に入らない | **直し中**（`group.js` の拡大リンクに `group_id` を渡し、`annotations.js` の `POST` 本文に入れる） |

- **確認**: `pytest` 222 passed、`gui_smoke` すべて ok（直し中の分は追って確認）。
