# 点検の指摘の仕分け（DeepSeek 点検 1 回目への対応）

`docs/review-report-deepseek.md`（A10 / B16 / C21 / D15 / E8 / F11 / G12）を、
**そのまま採用するもの・形を変えて採用するもの・却下するもの**に仕分けた記録。
Fable の点検と突き合わせるときにも使う。

- 点検した版: 2026-10-15 02:0x 時点の文書
- 仕分け: 依頼者（設計を書いた側）が自分で実機を確かめたうえで行った

---

## 1. 私が実機で確かめ直したこと（点検者の主張の検証）

### 1.1 B3 / B4 / E4「英訳の捕獲が実測と合わない」→ **半分は正しい。核心の主張は誤り**

点検者の主張: `outputs[node].text` は**リスト**で、中身は**翻訳ではなく VLM の説明文**。だから捕獲は使えない。

**自分で確かめた結果:**

| 主張 | 判定 | 根拠 |
| --- | --- | --- |
| `outputs[].text` はリストである | **正しい** | 実測: `{"11": {"text": ["Assistant\n- The character's eyes are ..."]}}`（`len=1`） |
| グラフ上、その値は `TextGenerate` の出力である | **正しい** | 実測した `prompt_id=a605f2f5-...` のノード 11 `PreviewAny.inputs.source = ["9", 0]`、ノード 9 が `TextGenerate` |
| 捕獲値は `StringConcatenate` を**通す前**である | **正しい** | ノード 10 `StringConcatenate.string_b = ["9", 0]`。品質語 `string_a = "(masterpiece, best quality, good quality, score_9), safe,"` は後で前置される |
| 中身は**翻訳ではなく** VLM の画像説明である | **誤り** | 同じ実行のノード 7（日本語・297 文字）は「背景に催眠にかかっていることを示すハートのエフェクトがある。女の子は四つん這いになっている…」。捕獲された英文は**その訳**。日本語が元々情景説明なので、英文も説明文の形になる |

**→ 設計への影響**: 捕獲は**使える**（`en_text` として正しい）。直すべきは次の 3 点だけ。

1. `outputs[].text` は**リスト**として扱う（先頭を取る。複数あれば全部持つ）
2. **グラフを辿って**、そのテキスト出力が `TextGenerate` に由来することを確かめてから `en_text` にする。
   辿れないものは `en_text` にせず、別の欄（`text_probe`）に「由来不明のテキスト出力」として残す
3. **最終プロンプトは捕獲値そのものではない。** `string_a + delimiter + 捕獲値` を**再構成**して
   `final_prompt`（`final_prompt_source='reconstructed'`）として持つ。ここを混同すると L1 が壊れる

### 1.2 B1 / E3「鳩の巣原理が偽」→ **正しい**

64bit を 16bit × 4 帯に分けたとき、ハミング距離 ≤ 6 で「必ず 1 帯は一致する」は**成り立たない**。
距離 k のとき、k 個の帯までが別々に食い違える。保証できるのは **k < 帯の数** まで。
点検者は距離 1〜6 の配分 209 通りのうち 15 通りで一致帯が 0 になると数え上げで示した（理論と一致）。

**→ 設計への影響**: 帯を **8bit × 8 本**にする（距離 ≤ 7 まで保証）。しきい値 ≤ 6 を満たす。

### 1.3 B2「走査が UNIQUE(path) と衝突する」→ **正しい**

`asset_location` に `UNIQUE(path)` を置いたまま「パスは同じで size/mtime が違う → ハッシュを計算し直す →
別の `asset` を作って同じパスに場所を足す」（`duplicates-deletion-backup.md` §1.4）と、
**同じパスで 2 行目を挿そうとして制約違反**になる。初回走査で必ず踏む。

**→ 設計への影響**: パスの中身が変わったら、**古い `asset` からその場所を外してから**（行を消し、
「別の内容に入れ替わった」ことを `location_history` に残す）新しい `asset` に付け直す。

### 1.4 A1「『実行しない』と `/prompt` の記述が衝突」→ **正しい（表現の問題）**

`design.md` §3 の図と §6.1 は、タグ付け（`assets/tag`）と訳し直し（`retranslate`、`tags/gloss`）に
ComfyUI の `/prompt` を使う。`workflow-reproduction.md` §1・§6-1 は「`POST /prompt` を投げない」と書いた。

**→ 設計への影響**: 意図は「**画像の生成を実行しない**」であって「ComfyUI を一切呼ばない」ではない。
文言を両方で直す（生成はしない。タグ付けと訳し直しには使う）。

---

## 2. 仕分け

### 2.1 そのまま採用（直す）

| # | 指摘 | 直す場所 |
| --- | --- | --- |
| A1 | 「実行しない」の意味を明確に（生成はしない／タグ付けと訳し直しには使う） | `design.md` §3・§6.1・§7.3.2、`workflow-reproduction.md` §1・§6 |
| A2 | 救済の口が 2 経路ある → `/api/comfyui/rescue-history` に統一 | `design.md` §6.1 |
| A3 | `/api/export/*` が §6.1 から消えている → 復活させる | `design.md` §6.1 |
| A4 | `duplicates` §1.3 の表が `design.md` §5.1 と食い違い、`kind`/`source_url`/`ref_tags` が消えている | `duplicates-deletion-backup.md` §1.3 |
| A5 | 工程 3-3 に Ollama が残存（不使用と決定済み） | `workflow-reproduction.md` §7 |
| A6 | `--no-hash` の目標が 30 秒 vs 60 秒で衝突、存在しない行を引用 | `design.md` §12.1、`duplicates-deletion-backup.md` §6 |
| A7 | 「最近の削除」が常設されておらず、トレイ項目にも無い（5 分の窓が使えない） | `design.md` §4.1・§11、`frontend-design.md` §3・§4・§11 |
| A8 | 「8.4 MB 空きます」は 5 分後まで空かないので誤り | `frontend-design.md` §6 |
| B1/E3 | 帯を 8bit × 8 本に | `duplicates-deletion-backup.md` §2.2 |
| B2 | パスの中身が変わったときの扱い | `design.md` §5.1、`duplicates-deletion-backup.md` §1.4 |
| B3/B4/E4 | 捕獲は**リスト**。グラフで由来を確かめる。最終プロンプトは再構成 | `design.md` §7.3・§7.3.1、`workflow-reproduction.md` §4.2・§4.7・§4.9 |
| B7 | `decide` が理由を 1 つしか受けない → 枚ごとの理由を受ける | `design.md` §6.1 |
| B8 | 契約に要求（`review_request`）が無い → `requests` を足す | `schemas/…`、`docs/review-export.example.json`、`design.md` §6.2 |
| B9 | 契約の `runs[]` に `seed`/`attempt_id`/`marker`/`matched_by` が無い | 同 |
| B10 | 決定性テストが `generated_at` のせいで必ず落ちる → 比較から外す | `design.md` §14 |
| B11 | Host / Origin の検査が無く、外部から段 3 の削除に到達しうる | `design.md` §6.3（新設） |
| B12 | 取り消しの `os.replace` が元パスの別ファイルを無警告で上書き | `duplicates-deletion-backup.md` §3.4 |
| B14 | `asset_meta` に CLIP/TE の列が無い（§4.1 が必須にしている） | `design.md` §5.2 |
| B15 | `changed_fraction` の定義が 2 文書で違う → `comparison.md` を正とし、他は参照 | `comparison.md` §4、`workflow-reproduction.md` §4.8 |
| B16 | 工程の完了条件が確かめられない（1 万枚が無い、60fps の条件なし、実生成が要る） | `design.md` §14 |
| C1 | `recipe_*` / `phash_band` / `deletion_log` / `duplicate_exclusion` が §5 に無い → §5.7 で参照 | `design.md` §5.7（新設） |
| C16 | 64bit の seed / pHash が SQLite の符号付き INTEGER を超える → TEXT（16 進） | `design.md` §5.1・§5.2・§5.6 |
| C19 | `Asset.decided_at` だけ `Timestamp` を使っていない | schema |
| D2 | 「1.25 倍の階段」は実際には比になっていない → 比ではなく段階と書く | `frontend-design.md` §2.3 |
| D4 | 「seed は 18 桁」→ 上限は 20 桁 | `frontend-design.md` §2.3 |
| E1 | 1 万枚の総量が 13.7 GB / 11.1 GB で食い違い、計測の帰属も誤り | `design.md` §12.1、`metadata-findings.md` §7 |
| E2 | §12.1 の 14 行中 8 行に実測の出所が無い | `design.md` §12.1 |
| E5 | サムネイル実測は 256px のみ。1024px は未計測 | `design.md` §12.1、`metadata-findings.md` §7 |

### 2.2 形を変えて採用

| 指摘 | 形 |
| --- | --- |
| B4「L1 は結線を宙に浮かせ、品質語を落とし、鍵まで変える」 | L1 を**「最終プロンプトを確定する」**と定義し直す。`StringConcatenate` の `string_b` を捕獲値のリテラルに置き換える（`string_a` の品質語は残る）。**鍵が変わるのは設計どおり**と明記し、判定は「完全」ではなく `approx` ＋ 理由 `text_pinned` にする |
| B13「再現の合否を書く口が無い」 | `POST /api/recipes/{id}/results/{result_id}/verdict` を足す |
| C8「一括削除のスコープを取る口が無い」 | `POST /api/locations/bulk-delete` に `{scope:{kind,id}}` を足す |
| C3「`reviews{subject_type:'group'}` と `decide` が重複」 | `decide` を正とし、`reviews` は**画像 1 枚のときだけ**受けると明記 |
| C16 の一部（seed の並べ替え） | `seed` は TEXT（10 進）。並べ替え用に `seed_sort INTEGER`（下位 63bit）を持ち、厳密な順序が要る画面だけ使う |

### 2.3 却下

| 指摘 | 却下の理由 |
| --- | --- |
| B3 の核心「捕獲値は翻訳ではないので捕獲は使えない」 | 実機で確かめた結果、**捕獲値は翻訳**（§1.1）。日本語が情景説明なので英文も説明文に見える。捕獲の設計は維持し、リスト処理と再構成だけ直す |
| B12 の一部「取り消しは危険だから 5 分の窓をやめる」 | 窓をやめると「戻せない削除」になり、利用者の回答（5 分は取り消せる）に反する。**上書きの検査を足す**ことで対応する |
| B11 の一部「認証を入れる」 | 利用者は「制限なし」と回答。**Host/Origin の検査**（ブラウザ経由の攻撃を防ぐ）だけ入れる。認証は入れない |

---

## 3. 未対応（Fable の点検と突き合わせてから決める）

- `H. 見落とし観点` の内容
- `G. 質問` の 12 件（利用者の判断が要るもの）。特に:
  - 外部契約に要求（`review_request`）を入れるか → **入れる**方針で進める（B8 として採用）
  - 1 万枚の目標をどう確かめるか（手元に最大 3,999 枚）
  - クリップボードの経路（`POST /api/assets/from-clipboard` はサーバ側から読めない）
  - Host / Origin 検査をどこまで厳しくするか

## 4. 点検者が検証できなかったこと（未確認のまま残る）

ComfyUI の実機動作（ブラウザでの D&D、`POST /api/userdata` の実書き込み、`control_after_generate` の復元、
`POST /prompt` の実挙動）と、画面の実描画。権限と環境が無いため。
→ `docs/metadata-findings.md` §6 と `docs/workflow-reproduction.md` §4.7.2 に**未確認**として既に記載がある。
