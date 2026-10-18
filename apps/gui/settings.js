// 設定（`#/settings`。P8-5）
// 設計: docs/p8-design.md §3.3（バックアップと段 3 の印）・§5（画面）・§0.21（P8-5 で確定）、
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
// - 印は**利用者の明示の意思表示**（Q8）。押した後は**読み直す**（画面と DB をずらさない）
// - `esc()` を必ず通す

import { esc, fmtBytes, fmtWhen } from './pending.js';

const BACKUP = '/api/backup';
const ROOTS = '/api/roots';
const SETTINGS = '/api/settings';

const $ = (id) => document.getElementById(id);

function human() {
  return { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' };
}

/** 控えの種類の語（利用者の言葉で。`backup.py` の `kind` をそのまま出さない）。 */
export const KIND_TEXT = {
  daily: '日次', manual: 'いま取る', 'pre-migrate': '版を上げる前の控え',
  'pre-topup': '表の形を変える前の控え', other: 'その他',
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
  roots: [],
  rootsOk: true,       // 古いサーバでは口が無い（404）。そのときは 1 行出す
  msg: '',
  bad: false,
  busy: false,
};

// ---- 描く（文字列）----

/** 読み取り専用の案内（DB が壊れている / 版が新しい / 控えが取れない。§3.4）。 */
export function readOnlyHtml() {
  const got = state.backup || {};
  const reason = got.details?.reason || got.reason || null;
  const why = {
    malformed: 'DB の検査に通りませんでした。',
    ahead: 'DB の版がこのアプリより新しいものです。',
    pre_migrate_backup_failed: '版を上げる前の控えを取れませんでした。',
    pre_topup_backup_failed: '表の形を変える前の控えを取れませんでした。',
    unopenable: 'DB を開けませんでした。',
  }[reason] || 'DB に書き込めない状態です。';
  return `<div class="st-readonly"><div class="st-sub">読み取り専用</div>
    <div class="st-warn">DB を読み取り専用で開いています。${esc(why)}</div>
    <div class="st-note">${esc(got.guidance || got.detail || '')}</div>
    <div class="st-note">バックアップから戻すことを検討してください:
      <code>image-reviewer restore &lt;バックアップのフォルダ&gt;</code></div></div>`;
}

/** 直近の一覧（新しい順。**日次と「いま取る」だけ**を「最後に取った時刻」に数える）。 */
export function snapshotsHtml() {
  const snaps = (state.backup && state.backup.snapshots) || [];
  if (!snaps.length) return '<div class="st-note">まだ控えはありません。</div>';
  const rows = snaps.map((snap) => `<div class="st-snap">
      <span class="st-snap-when num">${esc(fmtWhen(snap.created_at) || snap.name)}</span>
      <span class="st-snap-kind">${esc(kindText(snap.kind))}</span>
      <span class="st-snap-size num">${esc(fmtBytes(snap.bytes))}</span>
      <span class="st-snap-name mono">${esc(snap.name)}</span>
      ${snap.ok ? '' : '<span class="st-snap-bad">控えを読めません</span>'}
    </div>`).join('');
  return `<div class="st-snaps">${rows}</div>`;
}

/** バックアップの欄（最後に取った時刻・置き場・今日の分・**最後の失敗の全文**）。 */
export function backupHtml() {
  if (state.status === 503) return readOnlyHtml();
  const got = state.backup;
  if (!got) return '<div class="st-note">バックアップの状態を読めません。</div>';
  const lastAt = lastTakenAt(got);
  const failed = got.last_error
    ? `<div class="st-failed">最後の失敗（${esc(fmtWhen(got.last_error_at))}）:
        <span class="mono">${esc(got.last_error)}</span></div>
      <div class="st-note">置き場を作れないときは、書き込める場所に変えてください。</div>`
    : '';
  const readOnly = got.read_only ? '<div class="st-warn">読み取り専用で開いています。</div>' : '';
  return `<div class="st-sub">バックアップ<span class="stat">黙って失敗しません。失敗はここに出ます。</span></div>
    ${readOnly}
    <div class="st-line">${lastAt
      ? `最後に取ったのは <span class="num">${esc(fmtWhen(lastAt))}</span> です。`
      : 'まだ取っていません。'}</div>
    <div class="st-line">置き場: <span class="mono">${esc(got.backup_dir || '—')}</span>
      <span class="stat">${got.backup_dir_source === 'settings' ? '設定の値です' : '既定の場所です'}</span></div>
    <div class="st-line">${esc(got.next_run_note || '')}${
      got.next_run_at ? `（次は <span class="num">${esc(fmtWhen(got.next_run_at))}</span>）` : ''}</div>
    <div class="st-line">${got.count} 個の控えがあります（直近 ${esc(got.keep ?? 7)} 個を残します）。</div>
    ${failed}
    <div class="st-actions">
      <button class="st-now"${state.busy ? ' disabled' : ''}>いま取る</button>
      <span class="stat">同じ日でも必ず新しく取ります。</span>
    </div>
    <div class="st-actions">
      <label class="st-dir-label">置き場を変える
        <input id="st-dir" class="st-dir" type="text" value="${esc(got.backup_dir || '')}"
               spellcheck="false"></label>
      <button class="st-save"${state.busy ? ' disabled' : ''}>保存する</button>
      <span class="stat">データ置き場の中は指定できません。</span>
    </div>
    <div class="st-note">復元はコマンドで行います（
      <code>image-reviewer restore &lt;フォルダ&gt;</code>）。画面からは戻しません。</div>
    ${snapshotsHtml()}`;
}

/** 置き場ごとの「段 3 を許す」印（Q8。**人だけ**）。 */
export function rootsHtml() {
  if (!state.rootsOk) {
    return `<div class="st-sub">置き場ごとの「段 3 を許す」印</div>
      <div class="st-note">このサーバは置き場の一覧を返しません（古い版です）。</div>`;
  }
  if (!state.roots.length) {
    return `<div class="st-sub">置き場ごとの「段 3 を許す」印</div>
      <div class="st-note">登録された置き場はありません（走査するフォルダを足すと入ります）。</div>`;
  }
  const rows = state.roots.map((root) => `<div class="st-root">
      <span class="st-root-path mono" title="${esc(root.display_path || root.path)}">${
        esc(root.display_path || root.path)}</span>
      <span class="st-mark${root.allow_stage3 ? ' on' : ''}">${
        root.allow_stage3 ? '印あり' : '印なし'}</span>
      <span class="spacer"></span>
      <button class="st-allow" data-id="${esc(root.id)}" data-allow="${
        root.allow_stage3 ? 'false' : 'true'}">${
        root.allow_stage3 ? '印を外す' : 'この置き場で段 3 を許す'}</button>
    </div>`).join('');
  return `<div class="st-sub">置き場ごとの「段 3 を許す」印
      <span class="stat">印の無い置き場では段 3（実ファイルの削除）を選べません。段 1・2 はいつでも使えます。</span></div>
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
    brief.textContent = state.status === 503
      ? '読み取り専用'
      : `${got.count ?? 0} 個の控え ・ 段 3 の印 ${marks} / ${state.roots.length}`;
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
    state.msg = body.detail || `取れません（${res.status}）`;
    state.bad = true;
    await load();
    return null;
  }
  state.msg = `いま取りました: ${body.dir || ''}`
    + (body.counts ? `（${body.counts.assets ?? 0} 枚・判断 ${body.counts.decisions ?? 0} 件）` : '')
    + (body.pruned && body.pruned.length
      ? ` 古い控えを ${body.pruned.length} 個消しました。` : '');
  state.bad = false;
  await load();
  return body;
}

export async function saveDir(value) {
  const wanted = wantedDir(value ?? ($('st-dir') ? $('st-dir').value : ''));
  if (!wanted) {
    state.msg = '置き場のパスを入れてください。';
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
    state.msg = body.detail || `変えられません（${res.status}）`;
    state.bad = true;
    await load();
    return null;
  }
  state.msg = `置き場を変えました: ${body.backup_dir || wanted}`;
  state.bad = false;
  await load();
  return body;
}

export async function setAllow(rootId, allow) {
  const res = await fetch(`${ROOTS}/${encodeURIComponent(rootId)}/allow-stage3`, {
    method: 'POST', headers: human(), body: JSON.stringify({ allow: Boolean(allow) }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    state.msg = body.detail || `変えられません（${res.status}）`;
    state.bad = true;
    await load();
    return null;
  }
  state.msg = body.allow_stage3
    ? 'この置き場で段 3 を許します。'
    : 'この置き場の印を外しました。';
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
