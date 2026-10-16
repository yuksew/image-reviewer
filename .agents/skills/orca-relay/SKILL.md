---
name: orca-relay
description: >-
  Orca 経由で別のエージェント（DeepSeek の dsh セッションや利用者）と依頼・報告をやり取りするときの作法。
  orca orchestration send（本文の作り方・二重引用符と山括弧を本文に入れない・UTF-8 のファイルから渡す）、
  orchestration check --ack / --wait、terminal send、subject の付け方（<段>-audit-start / -mid / -done）、返信先の run id、
  「【Orca 経由の依頼 / 送信元 …】」で届いた依頼への答え方。「orca で知らせて」「orchestration send」「run_… へ送って」
  「subject は …」「Orca 経由の依頼」と言われたとき、または指示書の §4（往復）を実行するときは必ずこのスキルを読む。
  Orca そのものの操作（worktree・browser・skills）は orca-cli スキル。
---

# Orca 経由の往復

このプロジェクト（image-reviewer）では、依頼は **Orca のメッセージとして届き**（本文の先頭が
`【Orca 経由の依頼 / 送信元 dsh セッション(DeepSeek)】`）、返事は **`orca orchestration send` で依頼者の run へ送る**。
以下は P5〜P4 の往復で実際に使った形と、実際に失敗した形。

## 1. 送る（完了・途中・開始の知らせ）

```powershell
# 1) 本文を UTF-8 のファイルに書く（Git Bash から日本語を直接渡すと cp932 で化ける）
@'
P4-1（タガーと背景ジョブ）の実行込み監査が終わりました。報告: docs/p4-1-audit-report.md（新規）。
判定: … 最も重大な 3 件: (1) … (2) … (3) …
'@ | Out-File -Encoding utf8 $env:TEMP\p4-1-audit.txt

# 2) ファイルを -Raw -Encoding UTF8 で読んで渡す
orca orchestration send --to run:run_5bdd431bf57b --type status --subject p4-1-audit-done `
  --body (Get-Content -Raw -Encoding UTF8 $env:TEMP\p4-1-audit.txt) --json
```

- **返信先の run id は指示書の §4 に書いてある**（例: `run_5bdd431bf57b`（P6〜P4 の設計者）、`run_5cb7f377da7d`（P5 の直し）、
  `run_d631469a552e`（P5 のやり直し））。依頼の本文の「こちら(run_…)へ」がそれ。根拠: `docs/p4-audit-brief-p4-1.md` §4、`README.md` の文書表。
- **subject は指示書が決める**: `<段>-audit-start` / `<段>-audit-mid` / `<段>-audit-done`（設計の点検は `p4-review-start` / `-mid` / `-done`）。
  同じ subject を 2 回使っても同じ糸として届く（§J の追記は `p4-review-done` を再送した）。
- `--type` は `status` を使う。有効な値は `status, dispatch, worker_done, merge_ready, escalation, handoff, decision_gate, question, heartbeat`
  （`orca orchestration send --help`）。`worker_done` は `--outcome succeeded|failed` が要り、Dispatch からしか完結しない。
- 成功すると JSON に `"ok": true` と `"id": "msg_…"` が返る。**`msg_…` を控える**（報告や記憶に書く）。
- **本文に `"`（二重引用符）と `<` `>` を入れない。** PowerShell の引数が割れて `Unknown command: orchestration send …` で落ちる
  （P6-1b の完了通知で実際に落ち、本文を書き直して再送した）。送る前に確かめる:

  ```bash
  grep -nE '["<>]' "$LOCALAPPDATA/Temp/p4-1-audit.txt" || echo "禁止文字なし"
  ```
  コードの名前は `` `x` `` でなく裸で書く。`<id>` は `…` か `id` に。HTML の `<script>` は「script 要素」と書く。
- **`Get-Content -Raw` だけでは日本語が化けることがある。** 指示書の例に `-Encoding UTF8` が無くても付ける。
- 本文は**結論 → 最も重大な 3 件 → 数字（判定を変えるものだけ）→ 質問の数と置き場**の順で 1 画面に収める。
  詳細は報告ファイルに任せ、**ファイルのパスを本文の最初に書く**。

## 2. 受け取る・確かめる

- 届いた依頼は会話の中に `【Orca 経由の依頼 / 送信元 …】` として現れる（Claude Code の場合。自分で `check` しなくても届く）。
  自分で見るなら:

  ```powershell
  orca orchestration check --json                 # 未読の最古の 1 束
  orca orchestration check --ack <delivery_id> --json   # 前の束を既読にしてから次を見る
  orca orchestration check --wait --timeout-ms 60000 --json   # 届くまで待つ（15 秒ごとに keepalive 行が stderr に出る）
  orca orchestration check --peek --json          # 既読にせず見る
  ```
  （`orca orchestration check --help`）。
- 質問（`--type question`）に答えるときは **`orca orchestration reply --id <msg_id> --body <text>`**（同じ `orca` 実行ファイルで）。
- 相手のターミナルに直接打ち込みたいときは `orca terminal send --terminal <handle> --text "<text>" --enter`
  （`orca terminal send --help`。`--wait-submit <秒>` で投入の観測。曖昧な失敗は `--retry-request <id>` で**同じ命令を**再発行する）。
  通常の報告には使わない（run の受信箱に送る方が追える）。

## 3. 依頼への答え方（この体制の規律）

1. **まず開始の知らせ**（`-start`）。何を読み、何を実行で確かめ、どこに書くかを 3 行で。
2. **依頼者は待たない**。質問は報告の G に推奨つきで書き、推奨どおりで進める（指示書 §4「待たずに続けて」）。
   途中経過は `-mid` で（任意。長い監査や、依頼者が起きているときに重い指摘が出たら送る）。
3. 依頼の途中で**別の依頼**が来たら、いまの仕事を区切り（どこまで見たかを報告に書く）、優先順位を依頼者に合わせる。
   監査の最中に設計やソースが変わったら、**どの版を見たか**を報告と本文に書く。
4. **完了の知らせ**（`-done`）は報告ファイルを書き終えてから。報告の冒頭（判定・最も重大な 3 件）と同じ内容にする。
5. 本文に**作ったファイルの場所・触っていないもの（実データ・ソース）・止めたサーバ・残した一時物**を 1 行で添える。

## 4. 送る前の 5 点

- [ ] 本文は UTF-8 のファイルから `-Raw -Encoding UTF8` で読む
- [ ] `"` `<` `>` が無い
- [ ] `--to run:<指示書の id>`、`--subject <指示書の名前>`、`--type status`、`--json`
- [ ] 報告ファイルは書き終わっている（先に durable にする）
- [ ] 返った `msg_…` を控える
