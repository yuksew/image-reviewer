# Agent skills の置き場と配り方（2026-10-16 に Fable が決めた）

**結論: 原本は `.agents/skills/<name>/SKILL.md` の 1 か所。Claude Code が読む `.claude/skills/<name>` は、そこへの
Windows ジャンクション。利用者レベル（`~/.claude/skills` / `~/.agents/skills`）と `docs/skills/` の写しは撤去した。**
直すのは `.agents/skills/` だけ。新しい skill を足したら `powershell -ExecutionPolicy Bypass -File .agents\link-skills.ps1` を 1 回打つ。

```
C:\work\image-reviwer\
├─ .agents\
│  ├─ skills\                      ← 原本（DSH が rank 200 で読む。Claude Code はここを直接は読まない）
│  │  ├─ image-reviewer-dev\SKILL.md
│  │  ├─ image-reviewer-audit\SKILL.md
│  │  └─ orca-relay\SKILL.md
│  └─ link-skills.ps1              ← .claude\skills のジャンクションを作り直す（何度打っても同じ）
└─ .claude\
   └─ skills\                      ← Claude Code が読む。中身はジャンクションだけ
      ├─ image-reviewer-dev    <JUNCTION> → ..\..\.agents\skills\image-reviewer-dev
      ├─ image-reviewer-audit  <JUNCTION> → ..\..\.agents\skills\image-reviewer-audit
      └─ orca-relay            <JUNCTION> → ..\..\.agents\skills\orca-relay
```

## 1. 誰が・どこを・どう読むか（自分で確かめた。前提にしていた話で違っていた所は §4）

### Claude Code（Fable。2.1.301）

| 場所 | 読むか | 根拠 |
| --- | --- | --- |
| `~/.claude/skills/<name>/SKILL.md`（利用者） | 読む | 文書「Choose where skills load」。このセッションでも最初はここから出ていた |
| `<プロジェクト>/.claude/skills/<name>/SKILL.md`（プロジェクト） | 読む。**起動した場所から親へ辿ってリポジトリの根まで** | 文書。**実行で確認**: 探り skill `probe-claude-project` を置いて `claude -p` の新しいセッションを起こすと一覧に出た |
| `.claude/skills/<name>` が**シンボリックリンク／ジャンクション** | 読む（向き先の `SKILL.md` を読み、同じ向き先は 1 回だけ数える） | 文書「entry can be a symlink」。**ジャンクションは実行で確認**: `probe-junction`（`.claude/skills` → `.agents/skills` のジャンクション）が新しいセッションに出た |
| `<プロジェクト>/.agents/skills` / `~/.agents/skills` | **読まない** | 文書に無い。**実行で確認**: `probe-agents-project` を `.agents/skills` だけに置いても出なかった |
| `~/.claude/skills/synced/` | claude.ai の自分のアカウントの skill を**一方向で**下ろす場所。手で置いた他のフォルダは動かさない・消さない | 文書（v2.1.280 より前は `manifest.json` があると `.trash/` に移すことがあった） |

- **同名は 利用者 > プロジェクト**（`~/.claude/skills/deploy` と `.claude/skills/deploy` があれば利用者の方が走る）。
  → **利用者レベルに写しを残すと、リポジトリ側を直しても古い方が勝つ。** だから利用者レベルの写しは撤去した。
- 変更は**見張りつき**で同じセッション内に反映される。ただし**起動時に無かった最上位の skills フォルダは見張られない**
  （`/reload-skills` か再起動が要る）。このセッションは `.claude/skills` を作る前に始まっていたので、探りは同じセッションでは
  見えず（`Unknown skill`）、`claude -p` の新しいセッションで確かめた。
- 下位フォルダの `<subdir>/.claude/skills/` は、そのフォルダのファイルに触れたときに読む（名前の前置きは無い）。

### DSH（DeepSeek。dsh 0.2.0-rc.2、`@deepseek-ai/dsh-skill-filesystem` 5.0.0、`dsh-skill` 0.2.0-rc.2）

`lib/index.js` の `roots()` を読んだ。走査する根と rank:

| 根 | source | rank | 条件 |
| --- | --- | --- | --- |
| `<projectRoot>/.dsh/skills` | `project-dsh` | 100 | `cwd` が渡されたとき |
| **`<projectRoot>/.agents/skills`** | `project-agents` | **200** | 同上 |
| 設定の `customSkillDirs` | `custom` | 300 | 設定があるとき |
| `~/.dsh/skills` | `user-dsh` | 400 | 常に（`dshHome` 設定で変更可） |
| `~/.agents/skills` | `user-agents` | 500 | 常に（**`DSH_AGENTS_HOME`** か設定 `agentsHome` で変更可） |
| 同梱 | `bundled` | 別枠 | |

- **rank は小さい方が勝つ**（`dsh-skill/lib/index.js` `compareIndexedCandidates`: `rank` 昇順 → provider の順 → 読んだ順。
  同じ層の中の重複だけを rank で決め、「Project entries outrank runtime entries, which outrank user entries」）。
  → **プロジェクトの `.agents/skills`（200）が利用者の `~/.agents/skills`（500）に勝つ。**
- **`projectRoot` は `cwd` から親へ `.git` を探して決め、無ければ `cwd` そのもの**（`findProjectRoot`）。
  **このリポジトリは git 管理外**なので、**DSH をリポジトリの根（`C:\work\image-reviwer`）で起動したときだけ** `.agents/skills` が
  プロジェクトの根として読まれる。下のフォルダで起動すると読まれない（§5 の G-1）。
- 見張りは chokidar、**`watchFollowSymlinks` の既定は `true`**。ジャンクション越しでも追える（原本は実体なので関係しない）。
- `~/.claude/skills` は**読まない**（DSH の観察どおり。`roots()` に無い）。

### `skills` CLI（vercel-labs/skills 1.7.2。`npx skills`）

`~/.agents/.skill-lock.json` と `~/.claude/skills/{orca-cli,find-skills}` がシンボリックリンクになっていたのはこれの仕業。
`dist/cli.mjs` を読んだ:

- **原本は `.agents/skills/<name>`**（`getCanonicalSkillsDir`。`-g` なら `~/.agents/skills`）、各エージェントの置き場
  （`.claude/skills` など）には**原本へのリンク**を作る。**Windows ではジャンクション**（`symlink(..., "junction")`）。
  `--copy` でコピーにもできる。
- つまり **この文書の形（原本 `.agents/skills` ＋ `.claude/skills` はジャンクション）は、`skills` CLI が自分で作る形と同じ**。
  後から CLI で別の skill を入れても共存する。
- `createSymlink` は**同じ名前の既存の物を消してから**リンクを張る（`rm`）。別の名前の手置きは触らない。
  **消される条件は「同名の skill を CLI で入れ直したとき」だけ**。この 3 つを CLI で入れる予定は無いので当たらない。
- `.skill-lock.json` は CLI が入れた物の出所の記録。手置きの skill は載らない（載らなくても読まれる）。

## 2. なぜこの形か（条件 a〜d との対応）

| 条件 | この形での答え |
| --- | --- |
| (a) 両方が自動で読める | DSH は `.agents/skills`（rank 200）を直接、Claude Code は `.claude/skills` のジャンクション越しに読む。**両方を新しいセッションで確認**（§3） |
| (b) リポジトリに残る | 原本もジャンクションも `C:\work\image-reviwer` の中。`docs/` の写しは要らない（この文書が置き場を説明する） |
| (c) 1 か所だけ直す | 原本は `.agents/skills` だけ。ジャンクションは同じ実体を指すので**写しが無い**。利用者レベルの写しは撤去した（残すと Claude Code では利用者側が勝って古い物が使われる） |
| (d) 仕様が変わっても壊れにくい | `.agents/skills` は Agent Skills の共通規約で `skills` CLI の原本の置き場でもある。Claude Code が将来 `.agents/skills` を直接読むようになっても、同じ向き先なので 1 回だけ数えられる。ジャンクションは管理者権限なしで作れ、`link-skills.ps1` で作り直せる |

代案と捨てた理由:
- **両方に実体を置く**（`.claude/skills` と `.agents/skills` にコピー）→ 直すとずれる（実際に 4 か所になって、DSH が 3 か所直してから 4 か所目を作った）。
- **`docs/skills/` を原本にして両方へ写す道具** → 道具を打ち忘れると古い物が読まれる。ジャンクションなら写し自体が無い。
- **`skills` CLI で入れる** → 出所が GitHub 前提。ローカルの原本を `add` することもできるが、結局この形（原本＋ジャンクション）になる。
- **利用者レベルに置く** → この 3 つはこのプロジェクト専用（run id・パス・家風）。他のプロジェクトで出てくると邪魔で、
  Claude Code では利用者側が勝つので引継ぎの版管理から外れる。

## 3. 確かめ方（両方から読めることの証拠）

- **Claude Code**: 利用者レベルの写しを消し、ジャンクションだけにした状態で
  `claude -p "… skill names that contain 'image-reviewer' or 'orca' …" --output-format text` → `image-reviewer-audit` /
  `image-reviewer-dev` / `orca-relay` / `orca-cli`（利用者レベル）が出た。探り 3 つ（`probe-claude-project` 実体・`probe-junction`
  ジャンクション・`probe-agents-project` `.agents` だけ）では**前 2 つだけ**が出た（2026-10-16 10:40 と 10:50）。
- **DSH**: `.agents/skills` は DSH が 10:27 に写してカタログに現れたと報告した場所で、原本をここにしたので変わらない。
  利用者レベルの `~/.agents/skills` の 3 つは消したので、**いま DSH のカタログに出ているのはプロジェクトの `.agents/skills`（rank 200）だけ**。
  DSH 側は `dsh` を**リポジトリの根で**起動し、カタログに 3 つが出ることを確かめる（非対話で一覧する口は見つからなかった。
  `dsh skills` は profile の名前と解釈される）。
- **ジャンクションの確認**: `Get-ChildItem -Force .claude\skills | Select Name, LinkType, Target` で 3 つとも `Junction`。

## 4. DSH が書いた前提で、違っていた所・条件付きだった所

| 前提 | 実際 |
| --- | --- |
| 「4 か所に置いて直すときは全部直す」（`handoff.md` §9 の旧記述） | 1 か所にした。写しは無い |
| 「`docs/skills/` が記録・原本」 | 原本は `.agents/skills`。`docs/skills/` は撤去し、この文書が置き場を説明する |
| 「CLI 経由で入れ直すと手で置いた物が消える可能性」 | 消えるのは**同名を入れ直したときだけ**。別名の手置きは触らない（`cli.mjs` の `createSymlink` / `cleanAndCreateDirectory`） |
| 「`.agents/skills` はリポジトリと一緒に版管理できる」 | そのとおり。ただし **DSH は `.git` でプロジェクトの根を決める**ので、git 管理外のいまは**起動した `cwd` が根**。根以外で起動すると読まれない |
| （暗黙）Claude Code もプロジェクトの `.agents/skills` を読む | 読まない（実行で確認）。だからジャンクションが要る |
| （暗黙）利用者レベルに写しがあっても害は無い | Claude Code では**利用者 > プロジェクト**なので、古い写しが勝つ。撤去が要る |

## 5. 直し方・足し方・困ったとき

- **直す**: `.agents/skills/<name>/SKILL.md` を編集するだけ。両方のエージェントに見張りがあるので、同じセッション内に反映される。
- **足す**: `.agents/skills/<new>/SKILL.md` を作り、`powershell -ExecutionPolicy Bypass -File .agents\link-skills.ps1` を打つ
  （ジャンクションを作る。既にある物は `ok`、原本が無くなった物は消す）。Claude Code のセッションが `.claude/skills` の存在しない
  うちに始まっていたら `/reload-skills`。
- **消す**: `.agents/skills/<name>` を消して `link-skills.ps1` を打つ（残ったジャンクションを消す）。
- **ジャンクションが壊れた／リポジトリを別の場所に複製した**: `link-skills.ps1` を打つ（絶対パスで張り直す）。
  コピー道具がジャンクションを実体に展開してしまったときも、原本と同じ中身なので `link-skills.ps1` が張り直す（`replace`）。
- **`link-skills.ps1` が何も言わずに終わる**: ファイルの先頭に UTF-8 の BOM が要る（PowerShell 5.1 は BOM 無しを cp932 で読み、
  日本語の行で構文が壊れる。実際に 1 回踏んだ）。`[IO.File]::WriteAllText($p, $text, [Text.UTF8Encoding]::new($true))` で保存し直す。
- **質問（推奨つき）**
  - **G-1** DSH の根の決め方が `.git` 依存なので、リポジトリを git 管理にするか、DSH を必ず根で起動する運用にするか。
    **推奨: git 管理にする**（`README.md` も改名の方針を書いている。`.git` が無いままなら「DSH は `C:\work\image-reviwer` で起動」を `handoff.md` §1 に 1 行）。
  - **G-2** 利用者レベルの `~/.agents/skills` にも `orca-relay` を置くか（他のプロジェクトの Orca の往復でも使える部分がある）。
    **推奨: 置かない**。run id とパスがこのプロジェクト固有。汎用の部分は `orca-cli` の側に足す。

## 6. 版（この判断の前提。変わったら §1 を測り直す）

Claude Code 2.1.301（`claude --version`）／dsh 0.2.0-rc.2（`dsh --version`）／`@deepseek-ai/dsh-skill-filesystem` 5.0.0・`dsh-skill` 0.2.0-rc.2
（`AppData\Roaming\npm\node_modules\@deepseek-ai\dsh\node_modules\@deepseek-ai\*\package.json`）／`skills` CLI 1.7.2（`npm-cache\_npx\...\node_modules\skills`）。
Claude Code の文書: https://code.claude.com/docs/en/skills（2026-10-16 に claude-code-guide で読んだ）。
