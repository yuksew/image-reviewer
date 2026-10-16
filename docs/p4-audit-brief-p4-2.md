# 監査の指示書（P4-2: 日本語の語釈）

あなたは**実装の監査者**です。**P4-2（日本語の語釈。番号付きで訳す・番号で対応・`edited=1` の保護）**を監査してください。

- 対象: `C:\work\image-reviwer`
- 出力: **`docs/p4-2-audit-report.md` を新規に書くだけ** ／ 言語: 日本語 ／ **実行してよい**

## 0. 環境（**注意: 利用者のサーバが動いています**）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"      # 必須
uv run --no-sync pytest -q                                  # ★ --no-sync が要る（理由は下）
node tools/gui_smoke.mjs
# 実データは mode=ro のみ。複製は sqlite3 の backup() で作る（WAL を畳まないと判断が抜ける）
$env:IMAGE_REVIEWER_DATA = "C:\work\image-reviwer\.tmp-audit-redo\<自分で作った複製>"
uv run --no-sync image-reviewer serve --port 8791
uv run --no-sync python tools/probe_p4.py --gloss --base http://127.0.0.1:8791
```

- **`image-reviewer.exe serve --port 8790`（利用者のアプリ）が `.venv` の exe を握っているので、`uv run` の再インストールが `os error 32` で落ちます。必ず `--no-sync`。**
- 実データ `.data/` は `user_version = 3`・263 枚・判断 3 件（**触らない**。`mode=ro` と `backup()` のみ）。
- 一時物は `.tmp-audit-redo/`。**`.backup/` は消さない**（利用者の控え）。**ソースは編集しない。**
- **ComfyUI（127.0.0.1:8188）は動いています**。**投げてよいのは「訳」だけ**（画像の生成はしない）。

## 1. P4-2 で入ったもの

- 設計: [`p4-design.md`](p4-design.md) **§0.9（語釈の作法）/ §0.14（模型は `qwen3vl_8b_int8_convrot`・`sampling off`）/ §1.2 の線 3〜6 / §3.5（3 つの口と応答の表）/ §4.2 / §7 / §8.1 の 9・10・11・21・23〜26 / §9 の P4-2 の行**
- 実装の記録: [`p4-2-implementation.md`](p4-2-implementation.md)（**自分で決めた点・申し送り・設計の穴**が書いてある）
- 主なファイル（実装者が埋める）: `src/image_reviewer/gloss.py`（新規）/ `src/image_reviewer/api/tags.py`（追加）/ `tests/test_gloss.py`（新規）/ `tools/probe_p4.py`（`--gloss`）

## 2. 確かめてほしいこと

1. **線 4・5・6 をあなたの手で**（§1.2）:
   - **線 4**: 語釈の無い語に「訳す」→ `POST /api/tags/gloss` を 1 回で `tag_gloss` が増える。**押さなければ 1 行も増えない**（`GET` を何回叩いても）。
   - **線 5**: 人が直す（`POST /api/tags/{tag_id}/gloss {ja}`）→ `GET` がその値・`edited: true` → `POST /api/tags/gloss` を流しても**上書きされない**。
   - **線 6**: 模型の応答に**番号の無い行・番号の重複・英語のままの行・空の応答**を注入 → **それらの語は `tag_gloss` に入らない**（取れた番号の語だけ入る）。
2. **番号での対応（§0.9。点検 A-3 / G-1-(b)）**: `^(\d+)[.)]\s*(.+)$` で番号を取り、**位置に依存していない**か。
   **保存する条件は「番号が取れた」かつ「本文が ASCII だけではない」**か。**空行は読み飛ばす**か。**番号の重複は捨てる**か。
   **部分的に当てはめてよい**（20 語のうち 17 語だけ取れたとき、17 語が入り 3 語は入らない）か。
   **1 語ずつの落とし方の成功条件が「行数 1」ではなく「番号が取れて日本語が返った」**か。
3. **模型の呼び方**: `1. 1girl` の形（番号＋`.`＋空白＋語）か。`system_prompt` が**設定**にあるか（コードに埋めていないか）。
   `CLIPLoader`（`qwen3vl_8b_int8_convrot.safetensors`）→ `TextGenerate` → **`PreviewAny` を繋いでいる**か（繋がないと 400）。
   `max_length=512`・**`sampling_mode="off"`**・`thinking=false`・`use_default_template=true`・`mtp="auto"` か。
   **ノード番号を決め打ちしていない**か（`tagger.py` と同じ作法）。
4. **取引の外で模型を待つ**か（`jobs.py` と同じ形）。**模型 0.5 秒の間に `store.locked()` が 0.25 秒以内に取れる**ことを実行で確かめる
   （**P4-1 の監査 B-1 と同じ型の穴**）。
5. **`GET` に副作用が無い**か（§0.10。`GET /api/assets/{id}/tags`・`GET /api/tags/{tag_id}/gloss`・`GET /api/tags/gloss/pending` の
   前後で `tag_gloss` の行数が変わらない）。**模型を回すのは `POST` だけ**か。
6. **§3.5 の表のとおりの応答**か: `tag_ids` 空 → 422／`limit` 超え → 422／既にある語は `skipped`（**模型を回さない**。
   **2 回押しても 2 回目は呼び出し 0 回**）／`force=true` でも `edited=1` は `skipped`／ComfyUI 不通 → **409 `gloss_engine_unavailable`**／
   保存しなかった語は `untranslated` に入る。応答に `translated` / `skipped` / `untranslated` / `calls` / `elapsed_ms` があるか。
7. **`tag_gloss` の中身**: `engine` に使った模型名が入るか。`source='manual'` と `edited=1` が人為の訂正で立つか。
   **`edited=1` を上書きしない**か。**`GET /api/assets/{id}/tags` の `counts` / `pending_gloss`**（P4-1 の監査 C-6 の宿題）が設計どおりか。
8. **`POST /api/tags/gloss` の actor**: 人が押す口か、エージェントも押せるか。**設計の判断**（`human` だけか）と一致するか。
   **新しい `POST` に `Host: evil` / `Content-Type: text/plain` で 403** のテストがあるか。
9. **テストが本当に落ちるか**（§8.1 の 9・10・11・21）。**偽の engine** で模型を呼ばずに検査しているか。
   **本物の模型を呼ぶテストが既定で走らない**か。
10. **性能**（§7）: 20 語の訳の時間を**あなたの手で測り直す**（設計の実測は 4.6〜4.8 秒、`sampling off` の初回 10.1 秒）。
    **測り方**（初回か 2 回目か）を書く。**10,000 枚での見積り**（見えている語だけ訳す前提）が設計と合うか。
11. **実装者が自分で決めた点**（`p4-2-implementation.md`）を 1 つずつ妥当か判定する。
12. **回帰**: `pytest`（**260 + 新規**）・`gui_smoke`・`gui_layout` **4 画面**が緑か。**`GET` が書かない**ままか。
    P5 / P6 / P4-1 の口と契約が変わっていないか。**実データ `.data/` の mtime が変わっていない**か。
13. **設計とのずれ**: 実装が `docs/p4-design.md` §0.9 / §3.5 と違う所。**設計が黙っているのに実装が決めた**所。

## 3. 報告の形式

`docs/p4-2-audit-report.md` に、これまでと同じ形（A / B / C / D / E / F / G（推奨つき）/ H）。
各項目に**場所**と**実行したコマンド / 再現手順**。最後に**最も重大な 3 件**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p4-2-audit-done `
  --body (Get-Content -Raw $env:TEMP\p4-2-audit.txt) --json
```

- subject は `p4-2-audit-start` / `-mid` / `-done`。待たずに続けて `G` に推奨つきで書いてください。
