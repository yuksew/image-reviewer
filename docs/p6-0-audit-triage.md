# P6-0 監査の仕分け（Fable の監査 → どう直したか）

- 監査報告: [`p6-0-audit-report.md`](p6-0-audit-report.md)（総合判定 **使える（条件つき）**。A 無し / B 1 / C 2 / D 数件 / G 3）
- 立場: **推奨どおり採用**（P6-0 の監査 G1・G2。G3 は「残す」も可なので現状維持）。

| # | 指摘 | どうしたか |
| --- | --- | --- |
| **B1** | 契約に足した `Group.superseded_by` を `review.json` が**一度も出さない**（名指しでもファイルでも印が消える） | **直った。** `export.py` の `_group_doc` が `superseded_by` を出す（P6-1a の実装で入った）。**テストに「出したときは印が載っている」を足した**（`test_superseded_groups_are_hidden_by_default` に `== 'r-new'` の 1 行。隠れることだけ見ていた穴） |
| **C1** | `GET /api/groups` が `superseded_by` を返さず、既定からも外さない（設計 §0.3 の半分） | **直った。** P6-1a の実装で `list_groups` に `superseded_by` と `include_superseded`、`api/groups.py` に `?include_superseded=1` が入った |
| **C2** | 座標の範囲（0〜1、`w > 0`）を DB も契約も縛っていない | **直した。** `db.py` の v4 DDL に `CHECK`（`0 <= x,y <= 1`、`w,h > 0`、`x+w <= 1+1e-9`）を足し、**両方の契約**の `Annotation` に `minimum` / `maximum` / `exclusiveMinimum` を足した（2 契約の形が同じことはテストで守っている） |
| **G3** | `CHECK` の冗長な項 | **残す**（Fable も「残してもよい」）。 |
| **F7** | 本物の `jsonschema` のテストが無い | **道具で代替**（`tools/check_contract_p6.py`。P6-1a の実装で作った）。CI に入れるかは朝に相談 |

- **影響**: `pytest` **203 passed**（P6-0 の 182 + P6-1a の 21）。`gui_smoke` 51 ok、`gui_layout` 3 窓 × 3 状態 ok。
- **`data-p52`（v4 済みのコピー）には新しい `CHECK` が効いていない**（既に作られた表のため）。実データは
  v3 のままなので、**利用者の DB が v4 に上がるときには効く**。監査で使うコピーを作り直すときは
  新規作成（v0 → v4）にすれば効く。
