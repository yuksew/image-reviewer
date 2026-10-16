# P6-1a 監査の仕分け（Fable の監査 → どう直したか）

- 監査報告: [`p6-1a-audit-report.md`](p6-1a-audit-report.md)（総合判定 **条件つきで使える**。A 1 / B 3 / 自己決定 9 点は妥当 / 設計の穴 6 件）
- 立場: **推奨どおり採用**。実装は [`p6-1a-implementation.md`](p6-1a-implementation.md)。

| # | 指摘 | どうしたか（**直した**） |
| --- | --- | --- |
| **A1** | `X-Image-Reviewer-Actor: robot` で **500**（`review_request.actor` の `CHECK` に当たり `IntegrityError`） | `api/__init__.py` の `actor_of()` で `human` / `agent` 以外を **422** に（`details.actor`）。口を通すテストを足した |
| **B1** | `group_id` を指名した要求が書き出しの対象に積まれず、`groups/<id>.json` の `requests[]` が空のまま | `review_requests.create()` の既存まとまりの経路でも `dirty.append(gid)`。**ファイルに載ることをテストで固定** |
| **B2** | 「判断が 1 つも無い」が広すぎ、画像が**別のまとまり**で判断済みだと古いまとまりが閉じず既定の一覧に残る | `_no_decisions()` を **`decision.group_id = このまとまり`** の行だけを見る形に（このまとまりをレビューした記録だけを数える）。テストを足した |
| **B3** | 再送経路の `closed_request_ids` が近似で、同じ秒の reopen → 再 decide で 2 件返る | **再送では `closed_request_ids` を `[]` にする**（再送で閉じた事実は無い）。テストを足した |
| **設計の穴 5** | `group_id` を指名したとき `policy` を黙って捨てる | **違う値を送ったら 422**（`details.policy` / `requested`）。送らなければ通る（まとまりの設定が正）。テストを足した |
| **tools** | `tools/probe_p6_1a.py` が `.tmp-p6-1a`（約 90 MB）を残す | 実行の最後に消す（`--keep` で残せる）。いま残っていた 90 MB も消した |
| **設計文書** | §3.2 の検査順序が実装と違う／§7 に測り方が無い | §3.2 を実装の順序（対象解決 → 照合 → 業務検査 → 差し替え → INSERT）に直し、**対象が消えた再送は 404/422** と **`policy` 不一致は 422** を明記。§7 に **P6-1a の実測表（keep-alive と `--fresh` の両方）**を足した |

- **残り**: 設計の穴 1・2・6 は **P6-1b**（画面）、3・4 は **P6-2**（注記）で扱う（監査の判定どおり）。
- **確認**: `pytest` **208 passed**（+5。P6-1a の 21 に、直した 5 件のテストを足した）、`gui_smoke` すべて ok。
