# 監査の指示書（P8-1: 重複の検出と整理。合格の線 1〜3）

あなたは**実装の監査者**です。**P8-1** を監査してください。

- 対象: `C:\work\image-reviwer` ／ 出力: **`docs/p8-1-audit-report.md` を新規に書くだけ** ／ 言語: 日本語 ／ **実行してよい**
- **形式は前の段と同じ**（`docs/p8-audit-brief-p8-0.md` の §0〜§4 を踏襲。**A/B/C/D/E/F/G/H** と「最も重大な 3 件」）。

## 0. 環境（**利用者のアプリが 8790 で動いています。止めないでください**）

```powershell
cd C:\work\image-reviwer
$env:UV_CACHE_DIR = "C:\work\image-reviwer\.uv-cache"      # 必須
uv run --no-sync pytest -q                                  # ★ --no-sync。いま 314 件
node tools/gui_smoke.mjs                                    # 129 件
uv run --no-sync python tools/probe_p8.py --help
```

- **実データ `.data/` は `mode=ro` のみ**（**v6・23 表**（`sqlite_sequence` を除く）・263 枚・判断 3 件・**pHash は 91 枚だけ・帯は 0 行**）。
  壊す試験は複製（**`sqlite3` の `backup()` で WAL を畳む**）。**`.backup/` は消さない**。
  複製にサーバを立てるときは **`IMAGE_REVIEWER_DATA=<複製>`** を必ず付ける（**付け忘れると実データが上がる**。P7 で実際に起きた）。
- 一時物は `.tmp-audit-redo/`。**ソースは編集しない**。**`git` のコミットもしない**。**ComfyUI は使わない段**。

## 1. P8-1 で入ったもの

- 設計: `docs/p8-design.md`（837 行。**§0.5 / §0.9 / §0.10 / §3.1 / §7 / §8.1 / §8.4 / §9 の P8-1 の行**）
- 実装の記録: [`p8-1-implementation.md`](p8-1-implementation.md)（**自分で決めた点・申し送り 3 件・設計の穴 3 件**）
- 新規: `src/image_reviewer/duplicates.py`（428 行）・`src/image_reviewer/api/duplicates.py`（74）・
  `tests/test_duplicates.py`（330 行・16 件）・`tools/probe_p8.py`（176）
- 触った既存: `api/__init__.py`（`duplicates_of` と `require_human(actor, what=…)`）・`app.py`・**`store.py`（`set_hashes` が帯も書く）**・`db.py`・`tests/test_db.py`
- **P8-0 の監査の条件 3 件**（`docs/p8-0-audit-triage.md`）: **F-1 / C-1 / F-2**

## 2. 確かめてほしいこと

1. **合格の線 1〜3 をあなたの手で**（**実データの複製**で `tools/probe_p8.py` を回す）:
   **背景ジョブが 202 で返り 263 枚を計算**（実装者は 2.3 秒・8.6 ms/枚）／**pHash が 91 → 263**／**帯 2104 行**／
   **≤3 が 17 群 / 39 枚・≤6 が 21 群 / 57 枚・≤10 が 28 群 / 87 枚**（**点検の実測と一致するか**）／**完全重複 0 群**／
   **除外と解除**が群に効く／**`GET` は書かない**（**帯と pHash の行数が前後で同じ**）。
2. **線 2（取りこぼし 0）**: **帯の候補 = 総当たりの組**であること（**実装者の主張を自分で再現する**。
   **帯の作り方（8bit × 8 本）が正しいか**・**境界（帯 0 と帯 7）が落ちないか**）。
3. **「壊すと落ちる」テストが本当に落ちるか**（**実装者が 6 通り＋監査の 3 通りを確認**と主張）。
   **自分で壊して**確かめる（`BANDS` を変える・帯の結合を 0 本目固定・代表の規則を逆・`set_hashes` から帯を外す・群の並び・`compute` から `require_human` を外す）。
   **とくに「帯 0 固定」**: 実装者は「最初のテストが穴を隠していた」として**値を直した**と言っている。**本当に落ちるか**。
4. **代表の推薦**（§0.9 の規則: 人が選んだ物 → 画素数 → サイズ → **`mtime_ns` が新しい** → id）を**実行で**確かめる（**同点の扱い**も）。
5. **`GET` の守り**（403 / 422 / `Host: evil` / `Content-Type: text/plain`）・**`?max_distance=` の語彙外**・**`actor` の語彙外**・
   **新しい `POST` は `require_human`**（**利用者の回答 Q2 で「削除はエージェントにも許す」だが、P8-1 の `compute` と `exclude` はどうなっているか**——設計と突き合わせる）。
6. **P8-0 の条件 3 件が本当に直ったか**（**`CHECK` を外して落ちる**・**版だけ 6 の DB に表が入る**・**索引のテスト**）。
7. **`store.set_hashes` が帯も書く**判断（**設計より 1 段下**）が妥当か。**書き手が散っていないか**。
8. **性能**: **未計測を「未計測」と書いているか**（**1 万枚の 2 秒は届かない**と点検が言っている）。**`probe` の実測値**を確かめる。
9. **回帰**: `pytest` **314**（**複数回**）・`gui_smoke` **129**・`gui_layout`（**6 画面**）。**実データの pHash が 91 のまま・帯が 0 のまま**か。
10. **実装者が自分で決めた点と申し送り 3 件**（`job_item` に成功を書けない・帯の書き手・群からまとまりを作る口）を判定する。
11. **設計とのずれ**（`docs/p8-design.md` と違う所・**設計が黙っているのに実装が決めた**所）。

## 3. 報告の形式

`docs/p8-1-audit-report.md` に A/B/C/D/E/F/G/H と**最も重大な 3 件**。各項目に**場所**と**実行したコマンド / 再現手順**。

## 4. 往復

```powershell
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p8-1-audit-done --body (Get-Content -Raw $env:TEMP\p8-1-audit.txt) --json
```

- subject は `p8-1-audit-start` / `-mid` / `-done`。待たずに続けて `G` に推奨つきで書いてください。
