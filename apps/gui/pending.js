// 最近の削除（`#/pending-deletes`。P8-3）
// 設計: docs/p8-design.md §5（画面）・§3.2〜§3.4（使う口）・§4.1 / §4.3（状態）・§0.14 の Q2・Q7・Q8、
//       docs/frontend-design.md §4.6（常設）・§6（文言）・§11（細部）
//
// 約束:
// - **`GET` は書かない**（残り時間も減らさない。減らすのはサーバのタイマー）
// - 残り時間の**見た目**だけを毎秒書き換える（`あと 3:12`）
// - **人は誰の削除でも戻せる**（§0.14 の e-2）。エージェントは自分の分だけ（押せない）
// - 「いま消す」「別名で戻す」「ゴミ箱から戻す」は**人だけ**の口（押す前に確認を 1 回挟む）
// - 拾い物（`found`）は**消さない**（人が決める）
// - `esc()` を必ず通す

const PENDING = '/api/pending-deletes';
const TRASH = '/api/trash';
const PREVIEW = '/api/locations/bulk-delete/preview';
const BULK = '/api/locations/bulk-delete';

export const STAGE_LABEL = { 1: 'カタログから外す', 2: 'ゴミ箱へ移す', 3: '完全に消す用意をする' };
export const STATE_LABEL = {
  hidden: 'カタログから外しました', trashed: 'ゴミ箱にあります', pending: '取り消せます',
  stuck: '戻せませんでした', purged: '完全に消しました', restored: '戻しました',
};

const $ = (id) => document.getElementById(id);

function human() {
  return { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' };
}

/** **読むときも人だと名乗る**（`undoable` / `mine` は「誰が読んだか」で決まる）。
 *
 * `actor_of()` は**ヘッダが無ければ `agent`** を返す（`api/__init__.py`）ので、名乗らないと
 * **人が消した物でも `undoable: false`** が返り、画面が「取り消す」を隠してしまう
 * （画面の写真で見つけた。**P8-3 の実装で見つけた穴**）。
 */
function asHuman() {
  return { 'X-Image-Reviewer-Actor': 'human' };
}

export function esc(value) {
  return String(value ?? '').replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

export function fmtBytes(n) {
  if (n == null) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** `あと 3:12`（**分:秒**。`frontend-design.md` §4.6）。負は 0 に丸める。 */
export function fmtRemain(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** 1 秒ぶん減らす（**見た目だけ**。サーバは触らない）。 */
export function stepRemain(items) {
  for (const item of items || []) {
    if (item.remaining_sec != null) item.remaining_sec = Math.max(0, item.remaining_sec - 1);
  }
  return items;
}

export function fmtDay(iso) {
  return iso ? String(iso).slice(0, 10) : '—';
}

/** `2026-10-18T03:15:00Z` → `2026-10-18 12:15`（**現地の時刻**。台帳は UTC で持っている）。 */
export function fmtWhen(iso) {
  if (!iso) return '—';
  const got = new Date(iso);
  if (Number.isNaN(got.getTime())) return String(iso).replace('T', ' ').replace('Z', '');
  const two = (n) => String(n).padStart(2, '0');
  return `${got.getFullYear()}-${two(got.getMonth() + 1)}-${two(got.getDate())}`
    + ` ${two(got.getHours())}:${two(got.getMinutes())}`;
}

/** `#/pending-deletes?ids=a,b` を読む（削除の確認へ渡された枚）。 */
export function idsOf(search) {
  const params = new URLSearchParams(search || '');
  return (params.get('ids') || '').split(',').map((s) => s.trim()).filter(Boolean);
}

/** 誰が消したか（**色ではなく語で**。Q2 の帰結 b）。 */
export function actorText(actor) {
  return actor === 'agent' ? 'エージェント' : '人';
}

/** 3 段階の進行（**印 → ゴミ箱 → 実削除**）。いまの段に印を付ける。 */
export function stageStrip(stage) {
  const steps = ['1 印', '2 ゴミ箱', '3 実削除'];
  return `<span class="pd-strip">` + steps.map((text, i) =>
    `<span class="pd-step${i + 1 === Number(stage) ? ' on' : ''}">${esc(text)}</span>`
  ).join('<span class="pd-arrow">→</span>') + '</span>';
}

// ---- 画面の状態 ----

const state = {
  items: [], windowSec: 300, found: [], foundCount: 0,
  trash: { days: [], count: 0, bytes: 0 },
  ids: [], stage: 1, preview: null, exec: null, msg: '', bad: false,
  confirmLast: false, timer: null, busy: false,
};

// ---- 描く（文字列）----

export function rowHtml(item) {
  const stage = Number(item.stage);
  const remain = stage === 3 && item.state === 'pending'
    ? `<span class="pd-remain num" data-remain="${esc(item.id)}">あと ${esc(fmtRemain(item.remaining_sec))}</span>`
    : '<span class="pd-remain num">—</span>';
  const stuck = item.state === 'stuck'
    ? '<div class="pd-reason">戻せませんでした。保留していたファイルが見つかりません。'
      + '「別名で戻す」か「いま消す」を選べます。</div>'
    : '';
  const buttons = [];
  if (item.undoable) buttons.push(`<button class="pd-undo" data-id="${esc(item.id)}">取り消す</button>`);
  if (stuck && item.needs_as_copy) {
    buttons.push(`<button class="pd-ascopy" data-id="${esc(item.id)}">別名で戻す</button>`);
  }
  if (stage === 3 && item.state !== 'purged') {
    buttons.push(`<button class="pd-purge" data-id="${esc(item.id)}">いま消す</button>`);
  }
  return `<div class="pd-row pd-${esc(item.state)}" data-id="${esc(item.id)}">
    ${remain}
    ${stageStrip(stage)}
    <span class="pd-path mono" title="${esc(item.display_path || item.path)}">${esc(item.display_path || item.path)}</span>
    <span class="pd-meta num">${esc(fmtBytes(item.size))} ・ ${esc(actorText(item.actor))}`
    + ` ・ ${esc(fmtWhen(item.at))}</span>
    <span class="spacer"></span>${buttons.join('')}
    ${stuck}
  </div>`;
}

export function runningHtml() {
  if (!state.items.length) {
    return '<div class="note">取り消せる削除はありません。</div>';
  }
  return state.items.map(rowHtml).join('');
}

/** 拾い物（台帳に無い保留領域の中身。**消さない**。G-4）。 */
export function foundHtml() {
  if (!state.foundCount) return '';
  const shown = state.found.slice(0, 5).map((f) =>
    `<div class="pd-found-row"><span class="mono">${esc(f.path)}</span>`
    + `<span class="pd-meta num">${esc(fmtBytes(f.size))}</span></div>`).join('');
  return `<div class="pd-found"><div class="pd-sub">台帳に無いファイルが保留領域に`
    + ` ${state.foundCount} 件あります。消しません。`
    + '<span class="stat">エクスプローラーで確かめてから決めてください。</span></div>'
    + shown
    + (state.foundCount > state.found.length
      ? `<div class="stat">ほか ${state.foundCount - state.found.length} 件</div>` : '')
    + '</div>';
}

/** ゴミ箱（段 2。日付ごと。**自動では消さない**。Q7）。 */
export function trashHtml() {
  if (!state.trash.count) {
    return '<div class="pd-sub">ゴミ箱</div><div class="note">ゴミ箱は空です。</div>';
  }
  const days = state.trash.days.map((day) => `<div class="pd-day">`
    + `<div class="pd-day-head">${esc(day.date)} ・ ${day.count} 件 ・ ${esc(fmtBytes(day.bytes))}</div>`
    + day.items.map((item) => `<div class="pd-row pd-trashed" data-id="${esc(item.id)}">
        ${stageStrip(2)}
        <span class="pd-path mono" title="${esc(item.display_path || item.path)}">${esc(item.display_path || item.path)}</span>
        <span class="pd-meta num">${esc(fmtBytes(item.size))} ・ ${esc(actorText(item.actor))}</span>
        <span class="spacer"></span>
        <button class="pd-trash-restore" data-id="${esc(item.id)}">戻す</button>
      </div>`).join('')
    + '</div>').join('');
  return `<div class="pd-sub">ゴミ箱<span class="stat">掃除の前に一覧を出します。`
    + '自動では消しません。</span></div>'
    + `<div class="pd-trash-head">${state.trash.count} 件 ・ ${esc(fmtBytes(state.trash.bytes))}</div>`
    + days;
}

/** 削除の確認（**モーダルではなく画面の中の段**。`?ids=` で渡されたときだけ）。 */
export function confirmHtml() {
  if (!state.ids.length) return '';
  if (state.exec) {
    const skipped = (state.exec.skipped || []).length;
    return `<div class="pd-confirm"><div class="pd-sub">削除の確認</div>
      <div class="pd-done">${state.exec.count} 枚を消す用意をしました。`
      + `あと ${esc(fmtRemain(state.exec.window_sec ?? state.windowSec))} は取り消せます。</div>`
      + (skipped ? `<div class="stat">${skipped} 件は中身が変わっていたので消しませんでした。</div>` : '')
      + '<div class="pd-confirm-actions">'
      + '<a class="back" href="#/pending-deletes">最近の削除で確かめる</a></div></div>';
  }
  const stages = [1, 2, 3].map((n) => `<label class="pd-stage${state.stage === n ? ' on' : ''}">`
    + `<input type="radio" name="pd-stage" class="pd-stage-box" value="${n}"`
    + `${state.stage === n ? ' checked' : ''}> 段 ${n} ${esc(STAGE_LABEL[n])}</label>`).join('');
  const thumbs = state.ids.slice(0, 12).map((id) =>
    `<img loading="lazy" src="/api/assets/${esc(id)}/thumb?size=256" alt="">`).join('');
  const preview = state.preview;
  const items = preview
    ? `<div class="pd-items">${preview.items.map((item) => `<div class="pd-item">
        <span class="mono pd-path">${esc(item.display_path || item.path)}</span>
        <span class="pd-meta num">${esc(fmtBytes(item.size))}</span></div>`).join('')}</div>
      <div class="pd-sum">${preview.count} 枚 ・ ${esc(fmtBytes(preview.bytes))}</div>
      <div class="pd-frees">${esc(preview.frees?.note || '')}</div>
      ${preview.not_allowed_count
        ? `<div class="pd-warn">印の無い置き場の ${preview.not_allowed_count} 枚は段 3 にできません（段 1・2 はできます）。</div>` : ''}
      ${preview.stage === 3 ? '<div class="pd-warn">この置き場は別のツール illust-authoring の管理下です。段 3 は実体を消します。</div>' : ''}
      ${preview.last_copies
        ? `<div class="pd-warn">最後の 1 つが ${preview.last_copies} 枚あります。ほかに実体がありません。`
          + `<label class="pd-last"><input type="checkbox" class="pd-last-box"`
          + `${state.confirmLast ? ' checked' : ''}> これも消す</label></div>` : ''}
      <div class="pd-confirm-actions">
        <button class="pd-exec"${preview.expired ? ' disabled' : ''}>${preview.count} 枚を消す用意をする</button>
        <button class="pd-forget">やめる</button>
        ${preview.expired ? '<span class="stat">確認した一覧の有効期限が切れました。もう一度確認してください。</span>' : ''}
      </div>`
    : `<div class="pd-picked">${thumbs}</div>
      <div class="pd-sum">選んだ ${state.ids.length} 枚</div>
      <div class="pd-confirm-actions">
        <button class="pd-preview">消す物を確かめる</button>
        <button class="pd-forget">やめる</button>
      </div>`;
  return `<div class="pd-confirm"><div class="pd-sub">削除の確認</div>
    <div class="pd-stages">${stages}</div>${items}</div>`;
}

export function messageHtml() {
  if (!state.msg) return '';
  return `<div class="pd-msg${state.bad ? ' bad' : ''}">${esc(state.msg)}</div>`;
}

export function legendHtml() {
  // **凡例は段に印を付けない**（`stageStrip(null)`。行と見分けが付かなくなる）
  return `<div class="pd-legend">${stageStrip(null)}<span class="stat">`
    + '段 1 はカタログから外すだけ（容量は空きません）・段 2 はゴミ箱・段 3 は実体を消す用意。'
    + '取り消せるのは段 3 の 5 分の窓の間だけです。</span></div>';
}

// ---- 読み込み（`GET` は書かない）----

async function load() {
  state.busy = true;
  const [pending, trash] = await Promise.all([
    fetch(PENDING, { headers: asHuman() }).then((r) => r.json()),
    fetch(TRASH, { headers: asHuman() }).then((r) => r.json()),
  ]);
  state.items = pending.items || [];
  state.windowSec = pending.window_sec || 300;
  state.found = pending.found || [];
  state.foundCount = pending.found_count || 0;
  state.trash = trash;
  state.busy = false;
  render();
}

function render() {
  const confirm = $('pd-confirm');
  if (confirm) confirm.innerHTML = confirmHtml();
  const legend = $('pd-legend');
  if (legend) legend.innerHTML = legendHtml();
  const running = $('pd-running');
  if (running) running.innerHTML = runningHtml();
  const found = $('pd-found');
  if (found) found.innerHTML = foundHtml();
  const trash = $('pd-trash');
  if (trash) trash.innerHTML = trashHtml();
  const msg = $('pd-msg');
  if (msg) msg.innerHTML = messageHtml();
  const brief = $('pd-brief');
  if (brief) {
    const pending = state.items.filter((i) => i.state === 'pending').length;
    brief.textContent = `${pending} 件 ・ ${fmtBytes(state.items.reduce((n, i) => n + (i.size || 0), 0))}`;
  }
}

/** 毎秒の見た目だけの書き換え（サーバは触らない）。 */
export function startTick(tickMs = 1000) {
  stopTick();
  if (tickMs > 0) state.timer = setInterval(tickRemain, tickMs);
}

export function stopTick() {
  if (state.timer !== null) { clearInterval(state.timer); state.timer = null; }
}

export function tickActive() { return state.timer !== null; }

function tickRemain() {
  stepRemain(state.items);
  for (const item of state.items) {
    if (item.remaining_sec == null) continue;
    const cell = document.querySelector(`[data-remain="${item.id}"]`);
    if (cell) cell.textContent = `あと ${fmtRemain(item.remaining_sec)}`;
  }
}

// ---- 押されたとき ----

export function stageTaken() {
  return state.stage;
}

export function askStage(n) {
  const got = Number(n);
  if (![1, 2, 3].includes(got) || got === state.stage) return false;
  state.stage = got;
  state.preview = null;                 // 段を変えたら凍結は捨てる（評価し直さない）
  state.exec = null;
  state.msg = '';
  render();
  return true;
}

export async function preview() {
  const res = await fetch(PREVIEW, {
    method: 'POST',
    headers: human(),
    body: JSON.stringify({ scope: { kind: 'assets', asset_ids: state.ids }, stage: state.stage }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) { state.msg = body.detail || `確かめられません（${res.status}）`; state.bad = true; render(); return null; }
  state.preview = body;
  state.msg = '';
  state.bad = false;
  state.confirmLast = false;
  render();
  return body;
}

export async function exec() {
  const got = state.preview;
  if (!got) return null;
  if (got.last_copies && state.stage === 3 && !state.confirmLast) {
    state.msg = '最後の 1 つを消すには「これも消す」に印を付けてください。';
    state.bad = true;
    render();
    return null;
  }
  const res = await fetch(BULK, {
    method: 'POST',
    headers: human(),
    body: JSON.stringify({
      preview_id: got.preview_id, confirm: true,
      client_token: token(), confirm_last_copy: Boolean(state.confirmLast),
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    state.msg = body.code === 'preview_expired'
      ? '確認した一覧の有効期限が切れました。もう一度確認してください。'
      : (body.detail || `消せません（${res.status}）`);
    state.bad = true;
    if (body.code === 'preview_expired') state.preview = { ...got, expired: true };
    render();
    return null;
  }
  state.exec = { ...body, window_sec: state.windowSec };
  state.preview = null;
  state.msg = '';
  state.bad = false;
  await load();
  return body;
}

export function token() {
  // 同じ操作の二重送信で二重に消さないための鍵（§0.13）。**押すたびに新しくする**
  return (globalThis.crypto?.randomUUID?.() || `t-${Date.now()}-${Math.random().toString(16).slice(2)}`);
}

export async function undo(id, asCopy = false) {
  const res = await fetch(`${PENDING}/${encodeURIComponent(id)}/undo`, {
    method: 'POST', headers: human(), body: JSON.stringify({ as_copy: Boolean(asCopy) }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    state.msg = body.code === 'target_exists'
      ? '元の場所に既にファイルがあります。「別名で戻す」で戻せます。'
      : (body.detail || `戻せません（${res.status}）`);
    state.bad = true;
    render();
    return null;
  }
  state.msg = body.recovered
    ? '戻しました（削除は起きていませんでした。ファイルは元のままです）。'
    : '1 枚を元の場所に戻しました。';
  state.bad = false;
  await load();
  return body;
}

export async function purge(id, confirmed = false) {
  if (!confirmed) return null;
  const res = await fetch(`/api/deletions/${encodeURIComponent(id)}/purge`, {
    method: 'POST', headers: human(), body: JSON.stringify({ confirm: true }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    state.msg = body.code === 'not_in_hold'
      ? '保留に実体がありません。「取り消す」を試してください。'
      : (body.detail || `消せません（${res.status}）`);
    state.bad = true;
    render();
    return null;
  }
  state.msg = '実体を消しました。元に戻せません。';
  state.bad = false;
  await load();
  return body;
}

export async function trashRestore(id) {
  const res = await fetch('/api/trash/restore', {
    method: 'POST', headers: human(), body: JSON.stringify({ deletion_id: id }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    state.msg = body.code === 'target_exists'
      ? '元の場所に既にファイルがあります（ゴミ箱からの復帰は上書きしません）。'
      : (body.detail || `戻せません（${res.status}）`);
    state.bad = true;
    render();
    return null;
  }
  state.msg = '1 枚をゴミ箱から戻しました。';
  state.bad = false;
  await load();
  return body;
}

export function forget() {
  state.ids = [];
  state.preview = null;
  state.exec = null;
  state.msg = '';
  location.hash = '#/pending-deletes';
}

export async function onClick(event) {
  const target = event.target;
  const hit = (selector) => target.closest(selector);
  const stageBox = hit('.pd-stage-box');
  if (stageBox && askStage(stageBox.value)) return;
  if (hit('.pd-preview')) { await preview(); return; }
  if (hit('.pd-exec')) { await exec(); return; }
  if (hit('.pd-forget')) { forget(); return; }
  const undoBtn = hit('.pd-undo');
  if (undoBtn) { await undo(undoBtn.dataset.id); return; }
  const copyBtn = hit('.pd-ascopy');
  if (copyBtn) { await undo(copyBtn.dataset.id, true); return; }
  const purgeBtn = hit('.pd-purge');
  if (purgeBtn) {
    if (globalThis.confirm('実体をいま消します。元に戻せません。')) await purge(purgeBtn.dataset.id, true);
    return;
  }
  const restoreBtn = hit('.pd-trash-restore');
  if (restoreBtn) { await trashRestore(restoreBtn.dataset.id); return; }
}

export function onChange(event) {
  const target = event.target;
  if (target.closest('.pd-last-box')) {
    state.confirmLast = Boolean(target.checked);
    return;
  }
  const box = target.closest('.pd-stage-box');
  if (box) askStage(box.value);
}

// ---- 入口 ----

export async function showPending(search) {
  state.ids = idsOf(search);
  state.preview = null;
  state.exec = null;
  state.msg = '';
  document.body.classList.add('pending');
  await load();
  startTick();
}

export function hidePending() {
  document.body.classList.remove('pending');
  stopTick();
}

export function wirePending() {
  for (const id of ['pd-confirm', 'pd-running', 'pd-trash']) {
    const node = $(id);
    if (!node) continue;
    node.addEventListener('click', onClick);
    node.addEventListener('change', onChange);
  }
  const again = $('pd-again');
  if (again) again.addEventListener('click', () => { load().catch(() => {}); });
}
