# P8-2 監査の再確認の仕分け（P8-3 の最初に直した 3 件）

- 日付: 2026-10-18（JST）
- 元: [`p8-2-audit-recheck.md`](p8-2-audit-recheck.md)（判定 **合格**（条件なし）。残った軽微 2 件＝D-1・D-2、設計のずれ 1 件＝E-3）
- 指示: [`p8-3-implementation-brief.md`](p8-3-implementation-brief.md)「まず直す（P8-3 の最初に。再確認の軽微 2 件＋設計の 1 行）」
- 直した物: `src/image_reviewer/deletions.py`（`_drop_request`・`_original_state` 新設・`_recover_missing_hold`・`_restore`）、
  `tests/test_deletions.py`（+3 件）、`docs/p8-design.md`（§3.2 の `undo` の行）

## 仕分け（全部採用。推奨どおり）

| # | 指摘 | 決定 | 直し方 |
| --- | --- | --- | --- |
| **D-1** | 移動の後で取引が落ちると `delete()` の `_drop_request` が**台帳の外部キー**に当たって `IntegrityError` になり、**元の例外が隠れる**（`deletions.py:1289`） | **採用**（G-1） | `_drop_request` を「**台帳が参照していなければ消す**」に変え、消せたかを返す（`DELETE … WHERE id = ? AND result_json IS NULL AND NOT EXISTS (SELECT 1 FROM deletion_log WHERE request_id = ?)`）。`_replay` の D-8 の巻き取りも同じ関数を通し、**台帳が参照していて消せないときは 409 `client_token_in_progress` で断る**（黙って再送を通すと二重に消す。外部キーで 500 にしない） |
| **D-2** | 「戻したことにする」（`_recover_missing_hold` / `_restore` の `_mark_recovered`）が**元の場所の中身を見ない**（`deletions.py:449`・`:1091`） | **採用**（G-2） | `_original_state(row)` を新設し、`missing` / `same` / **`different`** の 3 つに分ける（`same` は `(size, mtime_ns)` が**登録の行と一致**するときだけ）。`different` は `_mark_unrestorable`（`stuck`）にして、**戻したことにしない**（`missing_at` と `restored_at` が両方立つ矛盾を作らない）。`undo` は 409 `restore_failed`、窓切れの後始末は**何も消さずに** `stuck` で残す。登録の値が `NULL` の欄は比べない（古い行で「分からない」を「違う」と読まない） |
| **E-3** | **エージェントが自分の段 2 を `undo` で戻せる**ことが設計の本文に無い（`trash/restore` は人だけのまま） | **採用**（G-4） | `docs/p8-design.md` §3.2 の `undo` の行に「**段 1〜3 の全部に効く**（段 2 の行もここで戻せる＝`trash/restore` と同じ道。あちらは人だけ、こちらは**エージェントも自分の分だけ**戻せる）」＋ D-2 の 409 `restore_failed` を 1 行ずつ足した |

- **D-3（走査の間はタイマーと削除の口が待つ）は設計どおり**（§3.4 の「待たせる」）。P8-3 では**画面に「走査中」を出す**（G-3 の推奨）——
  `POST /api/scan` の間は `POST /api/locations/delete` も `undo` も返らないので、**画面は「走査中は削除と取り消しが待ちます」を出す**。
  ただし**走査中かどうかを外から見る口が無い**（`scan` は job を持たない。設計の穴 5）ので、P8-3 の画面では
  「走査中」を**判定できない**。この 1 行は画面に出さず、**実行の記録の「設計の穴」に申し送る**（§3.4 L631 の字義どおり、押した要求が待つだけ）。

## 壊すと落ちる（実行して確かめた）

`tests/test_deletions.py` に 3 件足した。**4 通りの壊し方で、狙った試験が落ちる**ことを実行で確かめた
（`.tmp-audit-redo/p8-3-fix/mutants.py`。実物を 1 か所ずつ壊して戻す。前後で `deletions.py` の sha256 が一致＝
`df48b46d8c8c1bd4`。デッドコード（使わなくなった `_original_exists`）を消す前の `4e51d91aaf910090` でも 4 / 4 が落ちる）:

| 壊し方 | 落ちる試験 |
| --- | --- |
| D-1: 台帳が参照していても消す（元の形） | `test_a_failure_after_the_move_keeps_the_original_error` |
| D-2: 中身を見ない（元の形） | `test_a_different_file_at_the_original_place_is_not_recovered` |
| D-2: 窓切れの道だけ中身を見ない | 同上 |
| D-2: 取り消しの道だけ中身を見ない | `test_undo_refuses_when_the_original_place_holds_another_file` |

- **4 通り中 4 通りが落ちた**（`4 通り中 4 通りが落ちた`）。
- 途中で 1 回**嘘の「通ってしまった」**が出た。原因は **CPython の pyc の無効化が「mtime（秒）＋大きさ」**なので、
  同じ秒に書いた**大きさの同じ別の壊し方**（3 と 4）で**古い pyc が使われた**ため。`mutants.py` は毎回
  `deletions.*.pyc` を消してから回す形に直した（**キャッシュに当たった計測を実測と呼ばない**。P4 の教訓）。
