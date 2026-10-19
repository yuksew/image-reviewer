// 設定（`#/settings`。P8-5）
// 設計: docs/p8-design.md §3.3（バックアップと段 3 の許可）・§5（画面）・§0.21（P8-5 で確定）、
//       docs/frontend-design.md §3（画面の一覧 10）・§4.5.1（上部バー）・§6（文言）・§11（設定の画面）
//
// 約束:
// - **`GET` は 1 バイトも書かない**（状態を読むだけ。書くのは押したときだけ）
// - **人だけ**の口（`POST /api/backup`・`PATCH /api/settings`・
//   `POST /api/roots/{id}/allow-stage3`）には `X-Image-Reviewer-Actor: human` を付ける
// - **復元は CLI**（画面から戻さない。危険な操作を画面の口に置かない。設計 §3.3）
// - **最後の失敗は全文で出す**（黙って失敗しない。P8-4 の再確認 B-1'・G-4）
// - **「最後に取った時刻」は `daily` / `manual` だけ**から組む（`pre-topup` を数えない。
//   P8-4 の再確認 D-5）
// - 許可は**利用者の明示の意思表示**（Q8）。押した後は**読み直す**（画面と DB をずらさない）
// - `esc()` を必ず通す
// - **（P8-5 の監査 C-1）書き込むボタンは押している間 `disabled`。** `busy` を立てて描き直してから
//   `fetch` する（`takeNow` / `saveDir` と同じ形）。**二度押しで POST を 2 回出さない**
// - **（同 C-3・D-3）`read_only` なら `GET /api/backup` が 200 でも読み取り専用の案内**を出し、
//   書き込むボタンは**置かない**。理由と案内は `GET /api/health/db` から引き、
//   語彙は API の物（`malformed` / `unreadable` / `unopenable` / `version_ahead` /
//   `pre_migrate_backup_failed`）に合わせる
// - **（同 D-1・D-2）文言は `frontend-design.md` §6 が正**: ボタンは「取り直す」、
//   「今日の分は取れています。」/「今日の分はまだです。」は `today_done` から組む

import { esc, fmtBytes, fmtWhen } from './pending.js';

const BACKUP = '/api/backup';
const ROOTS = '/api/roots';
const SETTINGS = '/api/settings';
//: 読み取り専用の**理由と案内**（`GET /api/backup` の本文には `read_only` しか無い。C-3）
const HEALTH = '/api/health/db?full=0';

const $ = (id) => document.getElementById(id);

function human() {
  return { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' };
}

/** バックアップの種類の語（利用者の言葉で。`backup.py` の `kind` をそのまま出さない）。
 *
 * **（ワーディング監査 W-65。D-3）** 動詞を種類の名前にしない（「取り直す」→「取り直し」）。
 * 画面では 1 回分を「バックアップ」、数えるときは「世代」で通す（W-29・G-4）。**「控え」と呼ばない。**
 */
export const KIND_TEXT = {
  daily: '日次', manual: '取り直し',
  'pre-migrate': '版を上げる前', 'pre-topup': '表の形を変える前',
  other: 'その他',
};

export function kindText(kind) {
  return KIND_TEXT[kind] || KIND_TEXT.other;
}

/** **最後に取った時刻**（`daily` / `manual` の新しい物だけ。P8-4 の再確認 D-5）。 */
export function lastTakenAt(backup) {
  const snaps = (backup && backup.snapshots) || [];
  for (const snap of snaps) {                    // サーバは**新しい順**に返す
    if (snap.kind === 'daily' || snap.kind === 'manual') {
      return snap.created_at || snap.name || null;
    }
  }
  return null;
}

/** **置き場を変える**の値（入力が空なら保存しない）。 */
export function wantedDir(value) {
  return String(value == null ? '' : value).trim();
}

// ---- 画面の状態 ----

const state = {
  backup: null,        // `GET /api/backup` の本文（503 のときは本文＋read_only）
  status: 0,           // その番号（503 = 読み取り専用）
  dbinfo: null,        // `GET /api/health/db?full=0` の本文（読み取り専用の理由と案内。C-3）
  roots: [],
  rootsOk: true,       // 古いサーバでは口が無い（404）。そのときは 1 行出す
  msg: '',
  bad: false,
  busy: false,
};

// ---- 描く（文字列）----

/** 読み取り専用の案内（DB が壊れている / 版が新しい / バックアップが取れない。§3.4・§6）。
 *
 * **語彙は API の物**（`backup.inspect_db` と `app.py` が返す `reason`。D-3）:
 * `malformed` / `unreadable` / `unopenable` / `version_ahead` / `pre_migrate_backup_failed`。
 * **書き込むボタンは置かない**（§6「書き込みのボタンは押せなくする」。C-3）。
 */
export function readOnlyHtml() {
  const got = state.backup || {};
  const info = state.dbinfo || {};
  const reason = info.reason || got.details?.reason || got.reason || null;
  const why = {
    malformed: 'DB の検査に通りませんでした。',
    unreadable: 'DB を開けませんでした（ファイルが壊れています）。',
    unopenable: 'DB を開けませんでした。',
    version_ahead: 'DB の版がこのアプリより新しいものです。',
    pre_migrate_backup_failed: '版を上げる前のバックアップを取れませんでした。',
  }[reason] || 'DB に書き込めない状態です。';
  // 案内（`guidance`）は **API の物をそのまま**出す（正しい説明は API が持っている。D-3）
  const guidance = info.guidance || got.guidance || got.detail || '';
  return `<div class="st-readonly"><div class="st-sub">読み取り専用</div>
    <div class="st-warn">DB を読み取り専用で開いています。${esc(why)}</div>
    ${guidance ? `<div class="st-note">${esc(guidance)}</div>` : ''}
    <div class="st-note">バックアップから戻してください:
      <code>image-reviewer restore &lt;フォルダ&gt;</code></div></div>`;
}

/** 直近の一覧（新しい順。**日次と「取り直す」だけ**を「最後に取った時刻」に数える）。 */
export function snapshotsHtml() {
  const snaps = (state.backup && state.backup.snapshots) || [];
  // **（C-21）** 空にも次の一手を書く（規則 3「空の状態は『いまの状態』＋『次に押す物』の 2 文」）
  if (!snaps.length) {
    return '<div class="st-note">まだバックアップはありません。「取り直す」で今すぐ取れます。</div>';
  }
  const rows = snaps.map((snap) => `<div class="st-snap">
      <span class="st-snap-when num">${esc(fmtWhen(snap.created_at) || snap.name)}</span>
      <span class="st-snap-kind">${esc(kindText(snap.kind))}</span>
      <span class="st-snap-size num">${esc(fmtBytes(snap.bytes))}</span>
      <span class="st-snap-name mono">${esc(snap.name)}</span>
      ${snap.ok ? '' : '<span class="st-snap-bad">バックアップを読めません</span>'}
    </div>`).join('');
  return `<div class="st-snaps">${rows}</div>`;
}

/** バックアップの欄（最後に取った時刻・保存先・今日の分・**最後の失敗の全文**）。
 *
 * **読み取り専用なら `readOnlyHtml()` の道へ**（`GET /api/backup` が 200 でも
 * `read_only: true` なら書き込めない。§6・C-3）。
 */
export function backupHtml() {
  const got = state.backup;
  if (state.status === 503 || (got && got.read_only)) return readOnlyHtml();
  if (!got) return '<div class="st-note">バックアップの状態を読めませんでした。もう一度試してください。</div>';
  const lastAt = lastTakenAt(got);
  const failed = got.last_error
    ? `<div class="st-failed">最後の失敗（${esc(fmtWhen(got.last_error_at))}）:
        <span class="mono">${esc(got.last_error)}</span></div>
      <div class="st-note">保存先を作れないときは、書き込める場所に変えてください。</div>`
    : '';
  // **（ワーディング監査 W-28）** 「黙って失敗しません」は fail silently の直訳で、同じ文が
  // 画面の下にもう 1 回あった（index.html から消した）。**ここ 1 か所だけ**にする
  // **（D-6）** バックアップの場所は「保存先」（登録したフォルダは「フォルダ」）
  // **（A-5）** 添え書きは括弧書きにして、文の「。」と区別する
  return `<div class="st-sub">バックアップ<span class="stat">失敗したときは、ここにその全文が出ます。</span></div>
    <div class="st-line">${lastAt
      ? `最後に取ったのは <span class="num">${esc(fmtWhen(lastAt))}</span> です。`
      : 'まだ取っていません。'}</div>
    <div class="st-line">保存先: <span class="mono">${esc(got.backup_dir || '—')}</span>
      <span class="stat">${got.backup_dir_source === 'settings' ? '（設定の値）' : '（既定）'}</span></div>
    <div class="st-line">${got.today_done ? '今日の分は取れています。' : '今日の分はまだです。'}</div>
    <div class="st-line">バックアップが ${got.count} 世代あります（直近 ${esc(got.keep ?? 7)} 世代を残します）。</div>
    ${failed}
    <div class="st-actions">
      <button class="st-now"${state.busy ? ' disabled' : ''}>取り直す</button>
      <span class="stat">同じ日でも必ず新しく取ります。</span>
    </div>
    <div class="st-actions">
      <label class="st-dir-label">保存先を変える
        <input id="st-dir" class="st-dir" type="text" value="${esc(got.backup_dir || '')}"
               placeholder="例: D:\\backups\\image-reviewer" spellcheck="false"></label>
      <button class="st-save"${state.busy ? ' disabled' : ''}>保存する</button>
      <!-- **（ワーディング監査 W-30。D-6）** 「データ置き場」ではなく、利用者の言葉で言う -->
      <span class="stat">保存先はアプリの中（.data）にはできません。</span>
    </div>
    <div class="st-note">復元はコマンドで戻します（<code>image-reviewer restore &lt;フォルダ&gt;</code>）。画面からは戻しません。</div>
    ${snapshotsHtml()}`;
}

/** フォルダごとの「段 3 の許可」（Q8。**人だけ**）。
 *
 * **読み取り専用のときは押せなくする**（許可も書き込みの口。§6・C-3）。
 * **（ワーディング監査 §4。D-5・D-6）** 「印」は 6 つの物を指していて分からないので、ここでは「許可」と呼ぶ
 * （`root.allow_stage3`）。**登録したフォルダは「フォルダ」**（バックアップの場所は「保存先」）。
 */
export function rootsHtml() {
  const readOnly = state.status === 503 || Boolean(state.backup && state.backup.read_only);
  if (!state.rootsOk) {
    return `<div class="st-sub">フォルダごとの「段 3 の許可」</div>
      <div class="st-note">このサーバはフォルダの一覧を返しません（古い版です）。</div>`;
  }
  if (!state.roots.length) {
    // **（C-21）** 空にも次の一手を書く。**フォルダを追加する画面はアプリに無い**ので CLI を出す
    return `<div class="st-sub">フォルダごとの「段 3 の許可」</div>
      <div class="st-note">フォルダがまだありません。コマンド <code>image-reviewer scan --root &lt;フォルダ&gt;</code> で登録すると、ここに出ます。</div>`;
  }
  const rows = state.roots.map((root) => `<div class="st-root">
      <span class="st-root-path mono" title="${esc(root.display_path || root.path)}">${
        esc(root.display_path || root.path)}</span>
      <span class="st-mark${root.allow_stage3 ? ' on' : ''}">${
        root.allow_stage3 ? '許可あり' : '許可なし'}</span>
      <span class="spacer"></span>
      <button class="st-allow" data-id="${esc(root.id)}" data-allow="${
        root.allow_stage3 ? 'false' : 'true'}"${
        state.busy || readOnly ? ' disabled' : ''}>${
        root.allow_stage3 ? '許可を外す' : 'このフォルダで段 3 を許す'}</button>
    </div>`).join('');
  return `<div class="st-sub">フォルダごとの「段 3 の許可」
      <span class="stat">許可の無いフォルダでは段 3（ファイルを消す）を選べません。段 1・2 はいつでも使えます。</span></div>
    ${readOnly ? '<div class="st-note">読み取り専用で開いているので、許可は変えられません。</div>' : ''}
    ${rows}`;
}

export function messageHtml() {
  if (!state.msg) return '';
  return `<div class="st-msg${state.bad ? ' bad' : ''}">${esc(state.msg)}</div>`;
}

// ---- 読み込み（`GET` は書かない）----

async function load() {
  state.busy = true;
  const backupRes = await fetch(BACKUP, { headers: { 'X-Image-Reviewer-Actor': 'human' } });
  state.status = backupRes.status;
  const body = await backupRes.json().catch(() => ({}));
  // **503 でも本文を読む**（読み取り専用の案内がそこにある。P8-4 の再確認 D-2）
  state.backup = backupRes.ok || backupRes.status === 503 ? body : null;
  if (backupRes.status === 503) state.backup = { ...body, read_only: true };
  // **読み取り専用なら理由と案内を `GET /api/health/db` から引く**（`GET /api/backup` の本文には
  // `read_only` しか無い。200 の読み取り専用＝版が新しい形も拾う。C-3・D-3）
  state.dbinfo = state.backup && state.backup.read_only
    ? await fetch(HEALTH, { headers: { 'X-Image-Reviewer-Actor': 'human' } })
      .then((r) => r.json().catch(() => ({}))).catch(() => ({}))
    : null;
  const rootsRes = await fetch(ROOTS, { headers: { 'X-Image-Reviewer-Actor': 'human' } });
  state.rootsOk = rootsRes.ok;
  const rootsBody = rootsRes.ok ? await rootsRes.json().catch(() => ({})) : {};
  state.roots = rootsBody.roots || [];
  state.busy = false;
  render();
}

function render() {
  const backup = $('st-backup');
  if (backup) backup.innerHTML = backupHtml();
  const roots = $('st-roots');
  if (roots) roots.innerHTML = rootsHtml();
  const msg = $('st-msg');
  if (msg) msg.innerHTML = messageHtml();
  const brief = $('st-brief');
  if (brief) {
    const got = state.backup || {};
    const marks = state.roots.filter((r) => r.allow_stage3).length;
    // **読み取り専用は 200 の形（版が新しい）でも「読み取り専用」と言う**（C-3）
    // **（ワーディング監査 W-29・§4）** 「個の控え」ではなく「世代のバックアップ」、「印」は「許可」
    brief.textContent = state.status === 503 || got.read_only
      ? '読み取り専用'
      : `バックアップ ${got.count ?? 0} 世代、段 3 の許可 ${marks} / ${state.roots.length}`;
  }
}

// ---- 押されたとき ----

export async function takeNow() {
  state.busy = true;
  render();
  const res = await fetch(BACKUP, { method: 'POST', headers: human(), body: JSON.stringify({}) });
  const body = await res.json().catch(() => ({}));
  state.busy = false;
  if (!res.ok) {
    // **（C-7）** 「取れません（409）」では次の一手が無い。2 文にして、番号は括弧の中へ
    state.msg = body.detail || `取り直せませんでした。もう一度試してください（詳細: ${res.status}）。`;
    state.bad = true;
    await load();
    return null;
  }
  state.msg = `取り直しました: ${body.dir || ''}`
    + (body.counts ? `（${body.counts.assets ?? 0} 枚、判断 ${body.counts.decisions ?? 0} 件）` : '')
    + (body.pruned && body.pruned.length
      ? ` 古いバックアップを ${body.pruned.length} 世代消しました。` : '');
  state.bad = false;
  await load();
  return body;
}

export async function saveDir(value) {
  const wanted = wantedDir(value ?? ($('st-dir') ? $('st-dir').value : ''));
  if (!wanted) {
    state.msg = '保存先のパスを入れてください。';
    state.bad = true;
    render();
    return null;
  }
  state.busy = true;
  render();
  const res = await fetch(SETTINGS, { method: 'PATCH', headers: human(),
                                      body: JSON.stringify({ backup_dir: wanted }) });
  const body = await res.json().catch(() => ({}));
  state.busy = false;
  if (!res.ok) {
    state.msg = body.detail || `保存できませんでした。もう一度試してください（詳細: ${res.status}）。`;
    state.bad = true;
    await load();
    return null;
  }
  state.msg = `保存先を変えました: ${body.backup_dir || wanted}`;
  state.bad = false;
  await load();
  return body;
}

export async function setAllow(rootId, allow) {
  // **（P8-5 の監査 C-1）押している間は押せなくする。** `takeNow` / `saveDir` と同じ形で
  // 先に `busy` を立てて描き直す（描き直したボタンは `disabled` なので、人の二度押しの
  // 2 回目は本物のブラウザが届けない）。**同じ対象への 2 回目の POST を出さない**
  state.busy = true;
  render();
  const res = await fetch(`${ROOTS}/${encodeURIComponent(rootId)}/allow-stage3`, {
    method: 'POST', headers: human(), body: JSON.stringify({ allow: Boolean(allow) }),
  });
  const body = await res.json().catch(() => ({}));
  state.busy = false;
  if (!res.ok) {
    state.msg = body.detail || `変えられませんでした。もう一度試してください（詳細: ${res.status}）。`;
    state.bad = true;
    await load();
    return null;
  }
  state.msg = body.allow_stage3
    ? 'このフォルダで段 3 を許します。'
    : 'このフォルダの許可を外しました。';
  state.bad = false;
  await load();
  return body;
}

export async function onClick(event) {
  const target = event.target;
  const hit = (selector) => target.closest(selector);
  if (hit('.st-now')) { await takeNow(); return; }
  if (hit('.st-save')) { await saveDir(); return; }
  const allow = hit('.st-allow');
  if (allow) {
    await setAllow(allow.dataset.id, allow.dataset.allow === 'true');
  }
}

// ---- 入口 ----

export async function showSettings() {
  state.msg = '';
  state.bad = false;
  document.body.classList.add('settings');
  await load();
}

export function hideSettings() {
  document.body.classList.remove('settings');
}

export function wireSettings() {
  for (const id of ['st-backup', 'st-roots']) {
    const node = $(id);
    if (!node) continue;
    node.addEventListener('click', onClick);
  }
  const again = $('st-again');
  if (again) again.addEventListener('click', () => { load().catch(() => {}); });
  const back = $('st-back');
  if (back) {
    back.addEventListener('click', (event) => { event.preventDefault(); location.hash = ''; });
  }
}
