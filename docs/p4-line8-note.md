# 線 8（内蔵と ComfyUI の語の一致）— 達成の記録（2026-10-16）

- 対象: P4-1 の **線 8**（`docs/p4-design.md` §1.2 の 8）。**利用者の了解を得て `onnxruntime` を入れて測った**。
- 環境: **`onnxruntime 1.31.0`（CPU 版）**。`providers = ['AzureExecutionProvider', 'CPUExecutionProvider']`
  （**CUDA は入っていない**。`onnxruntime-gpu` は CUDA の DLL が無いと黙って CPU に落ちるので、
  いまは CPU 版を入れてある。GPU が要るなら `onnxruntime-gpu` ＋ CUDA の DLL を別途）。
- 入れた形: `pyproject.toml` の **任意依存 `tagger = ["onnxruntime>=1.20"]`** ＋ `uv sync --extra tagger`。
  **入らなくても ComfyUI 経由で動く**（`auto` の検出が `comfyui` に落ちる）。

## 結果: **一致 4 / 4**（実画像。語の集合が完全に一致）

| 方式 | 4 枚の語数 | 時間 |
| --- | --- | --- |
| **内蔵（WD14 eva02 v3・CPU）** | **36 / 47 / 73 / 41** | 5.2 秒 / 4 枚（**1.30 秒/枚**。模型の読み込み込み） |
| **ComfyUI の WD14 ノード**（`tagger.node=wd14`） | **36 / 47 / 73 / 41** | 10.3 秒 / 4 枚（2.57 秒/枚） |

- 測り方: 実データの複製（`sqlite3` の `backup()` で WAL を畳む。263 枚）にサーバを立て、
  `POST /api/assets/tag {engine:'builtin', sources:['wd14'], force:true}` → `done` → 語を読む →
  `tagger.node='wd14'` にして同じ 4 枚を ComfyUI 経由で付け直す → 語の集合を比べる。
- **合成画像では内蔵が 0 語になる**（`tools/probe_p4.py` の `seed()` は Pillow の合成画像。
  閾値 0.35 に対して WD14 が何も出さない）。**線 8 は実画像で測る**こと（点検の 66/66 も実画像）。

## 途中で見つけて直した不具合（**`onnxruntime` を入れて初めて出た**）

**`jobs.py` は方式を選ばずに `engine_obj.tag(path, name=...)` と呼ぶのに、`BuiltinTagger.tag()` が
`name` を受けていなかった** → 内蔵のときだけ全件
`TypeError: BuiltinTagger.tag() got an unexpected keyword argument 'name'` で失敗し、
**ジョブは `failed`・語は 0**（実データの複製で再現。`job_item.error` に残っていた）。

- 直し: `BuiltinTagger.tag()` を **`tag(self, image_path, *, name=None)`** に（`name` は受けるだけで使わない。
  ComfyUI 経由は複製の名前が要る）。**口を揃えた**。
- 再発防止: **`tests/test_tags.py::test_both_taggers_accept_the_same_call_shape`**（`inspect` で
  両方の `tag` がキーワード専用の `name` を受けることを固定。**模型は呼ばない**）。
  **`onnxruntime` を入れないと絶対に踏まない経路**だったので、テストで押さえた。
- あわせて `tools/probe_p4.py` の `--engine both` を直した（**ワーカーは 1 本**なので、次のジョブを投げる前に
  終わるまで待つ。待たないと 409 `job_running` が返り `job_id` が無くて落ちていた）。

## これで P4 の完了条件が全部そろった

`docs/p4-design.md` §1.2 の 9 つ（線 1・2・7 は P4-1 の監査、線 3〜6 は P4-2/P4-3 の監査と再確認、
**線 8 はこの記録**、線 9「GPU の実測時間を記録」は §7 の表に反映済み）。
**テストは 285 件**（線 8 の不具合の再発防止を足して 284 → 285）。
