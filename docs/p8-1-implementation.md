# P8-1 の実装の記録（重複の検出と整理）

- 日付: 2026-10-17。設計: `docs/p8-design.md`（837 行）の **§0.5 / §0.9 / §0.10 / §0.16 / §2.1 / §3.1 / §7 / §8.1 / §8.4 / §9 の P8-1 の行**
- 先に **P8-0 の監査の条件 3 件**（F-1 / C-1 / F-2）を直した → [`p8-0-audit-triage.md`](p8-0-audit-triage.md)
- **合格の線 1〜3**（実データの複製で通した。下の「実行した結果」）

## 作ったもの

| ファイル | 行 | 何 |
| --- | --- | --- |
| **`src/image_reviewer/duplicates.py`** | **新規 428** | 帯（`bands_of` / `write_bands`）・群（`candidate_pairs` / `near_groups`）・代表の推薦（`representative`）・完全重複（`exact_groups`）・**背景ジョブ**（`DuplicatesService`。`job` を使う。kind='hash'）・除外（`exclude` / `remove_exclusion` / `exclusions`） |
| **`src/image_reviewer/api/duplicates.py`** | **新規 74** | 6 つの口（§3.1）。**計算と除外は人だけ**（403 `human_only`）／`compute` は **202** |
| `src/image_reviewer/api/__init__.py` | +19 | `duplicates_of()` と **`require_human(actor, what=…)`**（人が要る口の検査を 1 か所に） |
| `src/image_reviewer/app.py` | +6 | `DuplicatesService` の生成・`app.state.duplicates`・`include_router` |
| `src/image_reviewer/store.py` | +6 | **`set_hashes` が帯も書く**（`asset.phash` と帯が食い違わないように。**書き手を 1 つにする**） |
| `tests/test_duplicates.py` | **新規 330・16 件** | 帯の分割・**取りこぼし 0**・代表の 4 規則・群の並び・`max_distance`・除外と解除・**背景ジョブ**・二重起動の 409・`GET` が書かない・口の形・守り（403 / 422）・`store` が帯を書く |
| `tests/test_db.py` | +3 件 | 監査の条件（F-1 / F-2 / C-1） |
| `tools/probe_p8.py` | **新規 176** | **線 1〜3 を実データの複製で出す**（帯と総当たりの一致・群の数・除外・`GET` の無副作用） |

## 実行した結果（実測）

### 合格の線（`uv run --no-sync python tools/probe_p8.py`。実データの複製 263 枚）

| 見た物 | 結果 |
| --- | --- |
| **背景ジョブ**（`POST /api/duplicates/compute`） | **202**・`total=263`・**done**・**実測 2.3 秒（8.6 ms/枚）**・**pHash 91 → 263 枚（+172）**・**帯 0 → 2104 行**（263 × 8） |
| **線 2（帯と総当たり）** | **帯の候補 54 組 = 総当たり 54 組**（**取りこぼし 0**・7 ms） |
| **線 1・3（群）** | **≤3: 17 群 / 39 枚**・**≤6: 21 群 / 57 枚**・**≤10: 28 群 / 87 枚**（**点検の実測と一致**） |
| 先頭の群（確実な物から） | 2 枚・最大距離 0・推薦は「ファイルが大きい」 |
| **完全重複** | **0 群**（空のときは 1 行の説明を返す） |
| **除外と解除** | 群 21 → 20 → 21／同じ群か True → False → True |
| **`GET` は書かない** | `near` / `exact` / `exclusions` の前後で**帯 2104 → 2104・pHash 263 → 263** |

### 検証の三点セット

| 確認 | 結果 |
| --- | --- |
| `uv run --no-sync pytest -q` | **314 passed**（296 → +18。**揺れなし**を複数回） |
| `node tools/gui_smoke.mjs` | **すべて ok**（129 件） |
| `node tools/gui_layout.mjs`（複製にサーバを立てて） | **6 画面すべて ok**（比較・要求・まとまり・注記・語の一覧・ジョブ） |
| 実データ `.data/` | **無傷**（v6・24 表・263 枚・判断 3 件・**pHash 91 のまま・帯 0 のまま**・除外 0） |

### 壊すと落ちる（自分で壊して確かめた 6 通り）

| 壊し方 | 落ちたテスト |
| --- | --- |
| `BANDS = 4` にする | `test_bands_split_a_phash_into_eight_hex_pairs` |
| 帯の結合を **帯 0 固定**にする | `test_the_band_index_never_misses_a_near_pair`（**最初の版はこれを通してしまった**。値を「違う帯のビットを 1 つ反転」に直して、初めて落ちるようになった） |
| 代表の規則 1（人がキープ）を最下位に | `test_the_representative_prefers_the_one_a_human_kept` |
| `store.set_hashes` から帯の書き込みを外す | `test_the_store_writes_bands_whenever_it_writes_a_phash` |
| 群の並びを「大きい群から」に | `test_near_groups_orders_by_certainty_and_reports_unhashed` |
| `compute` から `require_human` を外す | `test_the_compute_endpoint_is_202_and_human_only` |
| 監査の条件: `band` の `CHECK` を外す／`ix_phash_band` を消す／`_top_up_v6` の表作成を消す | それぞれ狙ったテストが落ちる（`p8-0-audit-triage.md`） |

## 自分で決めた点（申し送り）

1. **帯を `store.set_hashes` で書く**。設計 §0.5 は「`compare.capture_hashes` / `ensure_hashes` の隣に 1 手足す」と
   言うが、**書き手が 3 つに散る**（`compare` の 2 つ・背景ジョブ）ので、**一番下の `store.set_hashes` に 1 回だけ**置いた
   （`asset.phash` を書く道は必ずここを通る）。**設計より 1 段下**なので、記録として残す。
2. **`phash_band` が無い枚は `force` 無しでも計算対象に入れる**（`NOT EXISTS (SELECT 1 FROM phash_band …)`）。
   これを入れないと、**P5-3 が pHash を入れた 91 枚の帯が一生入らない**（その 91 枚は群に出てこない）。
   `_run` では **pHash がある枚は復号せず帯だけ書く**（91 枚 × 14 ms の無駄を避ける）。
3. **`job_item` には失敗だけを書く**（`state='failed'`）。`job_item.state` の `CHECK` は
   `tagged` / `skipped` / `failed` の 3 語で、**「ハッシュを計算した」に当てはまる語が無い**ため
   （成功は `progress` と `note` に残す）。**表の語彙を増やすのは P8 の範囲外**（`ALTER` で `CHECK` は変えられない）。
4. **`max_distance` は 0〜64 を許し**、`ALLOWED_MAX_DISTANCE`（3 / 6 / 10）は**画面が選ぶ 3 段**として持つ
   （API を 3 値に縛ると、`≤2` を試したいときに口が塞がる）。範囲外は **422**。
5. **除外は `exclude` の中で `(小さい方, 大きい方)` に正規化**する（表の `CHECK (a_id < b_id)` が最後の砦）。
6. **完全重複は「2 か所以上に生きている場所がある `asset`」**で数える（`asset.sha256` は `UNIQUE` なので 0 群）。
   `roots` の列は**入れない**（使わない物を応答に足さない。**最初に書いて `no such column: r.id` で落ちた**）。

## 設計の穴（気づいた物）

1. **§0.5 の「帯を `compare` の隣に足す」は書き手が散る**（上記 1）。**`store.set_hashes` に 1 回**が正しい。
2. **§7 の「1 万枚で 2 秒以内」は SQL の自己結合では届かない**（点検 B6 が既に指摘。**未計測のまま**にしてある）。
   実データ 263 枚では**帯の候補づくり 7 ms**。1 万枚は**未計測**（合成で 2.2 秒という点検の実測がある）。
3. **`review_group` の `kind` に `duplicates` がある**（点検 A1 で確認済み）。`POST /api/groups` で
   **群からまとまりを作る**口は**P8-3（画面）で使う**ので、**P8-1 では作っていない**（§3.1 の表にあるが、
   まとまりの作成は既存の口をそのまま使う）。
4. **`/api/duplicates/near` は頁送りを付けない**（連結成分は切れない。点検 C7）。**`limit` は群の数**に掛かる。
   100 群を超える環境では `offset` を足す必要がある（§10 の未確認に残っている）。
