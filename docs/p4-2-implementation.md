# P4-2（日本語の語釈）の実装の記録

- 実装: DeepSeek（dsh）／2026-10-16
- 設計: [`p4-design.md`](p4-design.md) **§0.9**（点検 A-3 / G-1・G-7 で確定）・§0.10・§3.4・§3.5・§4.2・§7・§8.1 の 9〜11・21・23
- 点検の仕分け: [`p4-review-triage.md`](p4-review-triage.md)／P4-1 の監査: [`p4-1-audit-report.md`](p4-1-audit-report.md)（**C-6** の宿題をここで果たした）

## 1. 作ったもの

| ファイル | 行 | 中身 |
| --- | --- | --- |
| **`src/image_reviewer/gloss.py`**（新規） | 485 | 語釈の一式。`settings_of`（設定 `gloss.*`）／**純関数** `is_japanese` / `format_prompt`（`1. 1girl` の形）/ **`parse_numbered`**（`^(\d+)[.)]\s*(.+)$` で番号を取り、空行は読み飛ばし・**番号の重複は捨て**・**英語のままは捨てる**）／`GlossEngine`（`CLIPLoader`→`TextGenerate`→`PreviewAny`、`sampling_mode="off"`、`/history` を 0.05 秒ごと、**ノード番号を決め打ちしない**）／`GlossService`（**読む → 模型（錠の外）→ 短い 1 取引で書く**）／読み出しの `lookup` / `pending` / `block_for`（§3.4 の `glosses` / `pending_gloss` / `counts`）／`set_manual`（人が直す） |
| **`src/image_reviewer/api/tags.py`**（変更） | +65 | `POST /api/tags/gloss`（訳す）／`GET /api/tags/gloss/pending`（数えるだけ）／`GET /api/tags/{tag_id}/gloss`（訳さない）／`POST /api/tags/{tag_id}/gloss`（**人だけ**。`tags.require_human`）／`GET /api/assets/{id}/tags` に §3.4 の 3 欄を追加 |
| `src/image_reviewer/api/__init__.py`（変更） | +6 | `gloss_of`（`app.state` から取る） |
| `src/image_reviewer/app.py`（変更） | +3 | `GlossService` を作って `app.state.gloss` に入れる |
| **`tests/test_gloss.py`**（新規） | 356 | **18 件**（下の §3） |
| **`tools/probe_p4.py`**（変更） | +150 | **`--gloss`**（線 4・5・6 を実機で出す。注入は in-process の偽の模型） |
| `docs/p4-design.md`（変更） | +30 | §3.4 に「P4-2 で実装した」1 行＋`counts` は出所ごと・`pending_gloss` は名前の配列と明記／§3.5 に**実装で決めた 7 点**の表／§4.2 に `source` の扱いを 1 行 |

**足していないもの**: 表の変更（`tag_gloss` は P4-0 の v5 に既にある。`engine` / `edited` / `source` を使った）・
スキーマの変更（`Tag` の `gloss` / `gloss_edited` は P4-0 で足りている）・画面（P4-3）。

## 2. 実行したコマンドと結果

```powershell
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"     # 必須
uv run --no-sync pytest -q                                # 278 passed（260 → +18）
node tools/gui_smoke.mjs                                  # すべて ok（回帰なし）
uv run --no-sync python tools/probe_p4.py --gloss          # すべて OK（下の §4）
# 画面（実データの写しを 8799 で立てて。**写しは `sqlite3.backup()` で作った**）
node tools/gui_layout.mjs --base http://127.0.0.1:8799 --count 8                 # ok（3 窓）
node tools/gui_layout.mjs --base http://127.0.0.1:8799 --screen requests         # ok
node tools/gui_layout.mjs --base http://127.0.0.1:8799 --screen group --group <id>  # ok（写しに 1 つ作った）
node tools/gui_layout.mjs --base http://127.0.0.1:8799 --screen asset --ids <id>    # ok
```

- **実データ `.data/` は読むだけ**（`mode=ro` と `backup()` のみ。mtime も変わっていない）。
- 使い捨ては `.tmp-audit-redo/`（`p4/`（probe が自分で消す）・**`p42layout/data`**（画面の確認に使った写し。
  263 枚・まとまり 1 つ・**語釈は 0 件**。監査で使うならどうぞ。消してもらって構いません）。

## 3. テスト（`tests/test_gloss.py`。**本物の模型は呼ばない**＝偽の engine を差し込む）

| # | 何を壊すと落ちるか | テスト |
| --- | --- | --- |
| **9** | 番号での対応を外す（位置で対応にする） | `test_parse_numbered_keeps_only_numbered_japanese_lines`（番号の無い行・**重複**・英語のまま・空行を注入）／`test_numbered_reply_maps_by_number_and_retries_only_the_missing`（**取れた番号の語だけ保存**・取れなかった番号は 1 語ずつ）／`test_an_empty_reply_stores_nothing`／`test_partial_reply_applies_what_was_returned`（20 語中 17 語だけ返る） |
| **10** | `edited=1` の保護を外す | `test_edited_gloss_is_never_overwritten`（`force=true` でも守る） |
| **11** | `GET` が訳すように変える | `test_get_endpoints_do_not_write`（4 つの `GET` の前後で行数が変わらず、**模型を 1 回も呼ばない**） |
| **21** | 語数の上限を外す | `test_too_many_words_and_empty_ids_are_422`（21 語・空） |
| **23** | 既に語釈がある語を訳し直す | `test_second_call_does_not_call_the_model`（2 回目は `calls=0`。`force=true` なら回す） |
| — | 繋がらないとき | `test_engine_unavailable_is_409`（`code: gloss_engine_unavailable`）／`test_everything_skipped_does_not_ping_the_engine` |
| — | 知らない id | `test_unknown_tag_id_is_404` |
| — | **模型を待つのは取引の外** | `test_the_model_is_called_outside_the_transaction`（偽の模型 0.5 秒の間に `locked()` が **0.25 秒以内**） |
| — | §3.4 の 3 欄 | `test_asset_payload_carries_glosses_pending_and_counts`（`counts` は**出所ごと**）／`test_pending_counts_words_without_gloss` |
| — | 人が直す口 | `test_a_human_can_write_and_edit_the_gloss`（403 / 422 / 200・`edited=true`・**`source` は由来を保つ**・`engine` を触らない） |
| — | 応答の形と守り | `test_translate_endpoint_shape_and_guards`（`translated` / `skipped` / `untranslated` / `calls` / `elapsed_ms`、`Host: evil` と `Content-Type: text/plain` で 403） |

## 4. 実機（`tools/probe_p4.py --gloss` → **すべて OK**）

```
1. 未タグの画像に語が付く（線 1）: 8/8・1 枚 0.51 秒（8 枚 4.1 秒）
4/5/6. 語釈（線 4・5・6）
  POST /api/tags/gloss（18 語）→ 200
  返った数 18 / 18（番号が取れて日本語になった数）   例: comic → コミック / monochrome → モノクロ /
      no_humans → 人無し / polka_dot → ポルカドット / polka_dot_background → ポルカドット背景 /
      text_focus → テキストフォーカス
  calls=1 elapsed_ms=9730（初回は模型の読み込み込み。§7 の実測は 20 語 4.6〜4.8 秒）
  2 回目（既定 force=false）→ calls=0（**0 が正**）skipped=18
  人が直す → 200 / エージェント 403 / force で訳し直す → calls=0 skipped=1
  いまの値 '人の手で直した語釈' edited=True（人が直した値のまま・edited=true が正）
  語釈の無い語: 0 語
  線 6: 4 語 → 保存 ['語1', '語3'] / 保存しなかった ['inject_2', 'inject_4'] / tag_gloss 18 → 20
        番号の重複 1 語 → 保存 0（0 が正）/ tag_gloss 20 → 20（増えないが正）
```

- **18 語**なのは、まっさらな置き場に 18 語しか無かったため（20 語の上限は `--gloss` の対象数で決まる）。
  **18/18 が日本語で返った**＝点検の「20/20」と同じ形。
- 注入した 4 種（番号の無い行・番号の重複・英語のまま・空の応答）で**誤った行は 1 つも入らなかった**。

## 5. 自分で決めた点（設計が黙っていた。**設計 §3.5 の表にも書いた**）

1. **知らない `tag_id` は 404**（他の口に揃えた）。設計は黙っていた。
2. **`tag_ids` の重複は黙って畳む**（冪等なのでエラーにしない）。
3. **`limit` は既定 20・上限 20**（`limit` で小さくできる）。§0.9 の「最大 20 語」を口でも守る。
4. **`tag_gloss.engine` には使った模型名**を入れる（§3.4 の例の形）。
5. **人が既存の語釈を直したときは `source` を書き換えない**（`edited=1` だけ立てる）。§4.2 の括弧書き
   （「自動の訳を人が直したなら `textgenerate` のまま `edited=1`」）をそのまま読んだ。画面の出し分けは
   `edited` だけを見るので食い違わない。**親の指示（`source='manual'`・`edited=1`）とはここだけ違う**ので、
   `manual` に揃えるなら `set_manual` の 1 行（`UPDATE` に `source='manual'` を足す）で変えられる。
6. **模型のエラー（502 / 504）はそのまま返す**（書くのは全部訳し終えてから 1 取引なので、部分保存は起きない）。
7. **`GET /api/tags/gloss/pending` は使用数の多い順**に返す（画面が「見えている語」から訳すとき、
   よく使う語が先に来る方がよい）。
8. **`gloss.batch`（まとめて訳す単位）も設定にした**（既定 20・上限 20。§10-4 で見直す余地）。

## 6. 申し送り

1. **`counts` の形は設計 §3.4（出所ごと）に従った。** 親の指示は「`total` / `with_gloss` / `without_gloss`」だったが、
   §3.4 の例と P4-1 の監査 C-6（「`counts`（出所ごとの数）」）が**出所ごと**と言っているのでそちらに合わせた。
   語釈の有無の数は `len(pending_gloss)` で出せる（**欄は足していない**）。
2. **語釈を書いても、まとまりの書き出しファイル（`export/groups/<id>.json`）は書き直していない。**
   `review.json` の `tags[]` は `include_tags=true` のときに読むだけで、P4-1 のタグ付けも同じ（`export` に
   印を付けていない）。**語を入れた全件は 100 MB 規模**（§10-14）なので、既定を `false` のままにする判断と整合。
   気にするなら「語釈を書いたら `notify_export` する」を 1 行足す（設計の判断待ち）。
3. **`_http_json` は `tagger.py` の私的な関数を借りている**（`from .tagger import _http_json`）。
   写しを作らないためだが、`tagger` 側で名前を変えると `gloss` も直す必要がある（2 箇所）。
4. **模型の読み込みは毎回**（初回 9.7 秒）。ComfyUI 側に載せっぱなしにする仕組みは無い（`IllustTagger` と同じ）。
   語釈を 1,000 語訳すなら 20 語ずつで 50 回 × 約 4.7 秒 ≒ 4 分＋初回（§7 の見積りどおり）。
5. **`gloss.llm` を変えたときの既存の語釈**は残る（`engine` に古い模型名が入ったまま）。訳し直すなら
   `force=true`（`edited=1` は守られる）。

## 7. 気づいた設計の穴

1. **§0.9 の「20 語」の根拠が点検の測定（`sampling off`・番号付き）に依存している。** `system_prompt` を
   利用者が書き換えると**行数の崩れ方が変わりうる**（点検 §H も「文面依存」と書いている）。
   `gloss.system_prompt` を変えたら **§10-4 の 5 / 10 / 20 / 40 語の測り直しが要る**（設計に注記が無い）。
2. **`GET /api/tags/gloss/pending` の `count` は「`tag` 表にあって語釈が無い語の数」**で、
   「画像に付いている語」に限っていない。画面が「見えている語のうち訳していない数」を出すには
   `GET /api/assets/{id}/tags` の `pending_gloss` を使う（こちらの方が正しい）。
   バーの件数のように `pending` の `count` を使うと**画面より大きい数**になるので、使い分けを §5.4 に 1 行足すとよい。
3. **`max_length=512` は 40 語でも足りた**（点検の実測）が、**語釈が長い言語だと切れうる**。
   切れた場合は「行数が合わない」として 1 語ずつに落ちるので**壊れはしない**（気づきにくいだけ）。
