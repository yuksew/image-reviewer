// 重複の整理（`#/duplicates`。P8-3）
// 設計: docs/p8-design.md §5（画面）・§3.1（使う口）・§4.2（群の状態）・§0.14 の Q3 / Q4 / Q5、
//       docs/frontend-design.md §3・§6（文言）・§11（細部）
//
// 約束:
// - **`GET` は計算しない**（pHash は `POST /api/duplicates/compute` の背景ジョブだけが計算する。§0.5）
// - **おすすめは推薦するだけ**（自動で外さない・自動でまとめない。Q4）
// - **（監査の注意）開いた直後は 1 枚も選ばない。** 全部を選ぶのは人が押したときだけ
//   （この画面の「削除へ回す」は壊す操作への入口なので、既定で選ばれた状態にしない）
// - **ここでは消さない**。選んだ枚を `#/pending-deletes` へ**渡すだけ**（段の選択と確認はあちら）
// - 除外（別物として確定）は**人だけ**の口（`403 human_only` が返る）
// - `esc()` を必ず通す

const NEAR = '/api/duplicates/near';
const EXACT = '/api/duplicates/exact';
const COMPUTE = '/api/duplicates/compute';
const EXCLUDE = '/api/duplicates/exclude';
const REMOVE = '/api/duplicates/exclude/remove';
const EXCLUSIONS = '/api/duplicates/exclusions';
const GROUPS = '/api/groups';

// **削除へ回す行き先は 1 か所で組む**（`pending.js`。監査 C-1。入口が 4 つあるので散らさない）
import { toDelete as toDeleteHash } from './pending.js';

/** しきい値の切り替え（Q3。**既定は 6**）。 */
export const THRESHOLDS = [3, 6, 10];
export const DEFAULT_MAX = 6;

const $ = (id) => document.getElementById(id);

function human() {
  return { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' };
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

/** `2026-10-16T12:00:00Z` → `2026-10-16`（時計は出さない。並びの判断には要らない）。 */
export function fmtDay(iso) {
  return iso ? String(iso).slice(0, 10) : '—';
}

/** `3 番`（おすすめの言い方。群の中の位置）。 */
export function labelOf(position) {
  return `${position} 番`;
}

/** `#/duplicates?max=6` を読む（**語彙の外は既定に戻す**）。 */
export function query(search) {
  const params = new URLSearchParams(search || '');
  const got = Number(params.get('max'));
  return { max: THRESHOLDS.includes(got) ? got : DEFAULT_MAX };
}

// ---- 群ごとの画面の状態（人が押した物だけを持つ）----

const state = {
  max: DEFAULT_MAX,
  groups: [], hashed: 0, unhashed: 0, totalGroups: 0, totalImages: 0, excludedPairs: 0,
  exact: { count: 0, message: null },
  exclusions: [], showExclusions: false,
  view: new Map(),          // 群の番号 → {keep: asset_id, on: Set(asset_id)}
  job: null, timer: null, msg: '', bad: false, made: null, busy: false,
};

/** 群から既定の選択を作る（**既定は 1 枚も選ばない**。おすすめは印だけ）。
 *
 * **（P8-3 の監査の注意）既定で全群を選ばない。** この画面の「削除へ回す」は**壊す操作**への
 * 入口なので、開いた直後に全部へ印が付いていると、押し間違いが**全群の削除**に化ける
 * （監査の複製で実際に 56 枚が掛かった）。選ぶのは人が押したときだけにする。
 * 「残す 1 枚」のおすすめ（`keep`）は**印**であって選択ではない（従来どおり助言のまま）。
 */
export function makeView(groups) {
  const view = new Map();
  (groups || []).forEach((group, i) => {
    view.set(i, { keep: group.suggested_id, on: new Set() });
  });
  return view;
}

/** 人が見ている選択（群の番号 → {keep, on}）。無ければ既定（**何も選ばない**）。 */
export function viewOf(i) {
  if (!state.view.has(i)) {
    const group = state.groups[i];
    state.view.set(i, { keep: group ? group.suggested_id : null, on: new Set() });
  }
  return state.view.get(i);
}

/** いま「まとまりに入れる」に印が付いている枚（全部の群を通して）。 */
export function pickedIds() {
  const out = [];
  state.groups.forEach((_g, i) => { for (const id of viewOf(i).on) out.push(id); });
  return out;
}

/** 全部の群の枚（「全部選ぶ」で入れる物）。 */
export function allIds() {
  const out = [];
  state.groups.forEach((group) => { for (const item of group.items || []) out.push(item.id); });
  return out;
}

/** 全部に印が付いているか（「全部選ぶ」と「全部外す」を 1 つのボタンで切り替える）。 */
export function allPicked() {
  const all = allIds();
  return all.length > 0 && pickedIds().length === all.length;
}

// ---- 描く（文字列）----

export function headHtml() {
  const groups = state.totalGroups;
  const images = state.totalImages;
  const bits = [`候補 ${groups} 群`, `${images} 枚`];
  if (!state.unhashed) bits.push(`計算済み ${state.hashed} 枚`);
  // **（P8-3 の取り落とし調査）人が「別物として確定」した組は候補から外れる**ので、
  // その数を出す。出さないと「群が 1 つ足りない」が**帯の取りこぼしに見える**
  // （実データで実際にそう見えた。`docs/p8-3-band-miss.md`）。0 のときは出さない。
  if (state.excludedPairs) {
    bits.push(`別物として確定で ${state.excludedPairs} 組を隠しています`);
  }
  return `<div class="dup-head">${bits.map(esc).join(' ・ ')}</div>`;
}

/** 完全重複（この環境では 0 群）。**空でも 1 行で説明する**（黙って空を返さない。§0.4）。 */
export function exactHtml() {
  if (state.exact.count > 0) {
    return `<div class="dup-exact">完全重複が ${state.exact.count} 件あります。`
      + `同じ中身が 2 か所以上にある物です。</div>`;
  }
  return '<div class="dup-exact">完全重複はありません。同じ中身が 2 か所以上にある物です。'
    + '<span class="stat">準重複は下に出ます。</span></div>';
}

/** まだ計算していない枚と、その計算（背景ジョブ。§0.5）。 */
export function computeHtml() {
  const job = state.job;
  if (job) {
    const done = Number(job.progress?.done || 0);
    const total = Number(job.progress?.total || 0) || job.total || 0;
    const active = job.state === 'running' || job.state === 'queued';
    const line = active
      ? `計算中 ${done} / ${total}`
      : `計算が${job.state === 'cancelled' ? '中断' : job.state === 'failed' ? '失敗' : '終わり'}ました`
        + `（${done} / ${total}）`;
    return '<div class="dup-compute">'
      + `<span class="dup-cmsg">${esc(line)}</span>`
      + (active ? `<button class="dup-cancel" data-id="${esc(job.id)}">中断</button>` : '')
      + `<a class="back" href="#/jobs">ジョブへ</a></div>`;
  }
  if (!state.unhashed) return '';
  // **（監査 G-4）枚数は実際の値（`unhashed`）から組む。秒数は埋め込まない**——
  // 前の版は「263 枚で 2.6 秒」と書いてあり、**別の置き場では嘘**になった
  return '<div class="dup-compute">'
    + `<span class="dup-cmsg">まだ計算していない枚が ${state.unhashed} 枚あります。</span>`
    + '<button class="dup-do-compute">計算する</button>'
    + '<span class="stat">絵を読んで指紋を作ります。画面は止まりません。</span></div>';
}

export function groupHtml(group, i) {
  const view = viewOf(i);
  const items = group.items || [];
  const picked = view.on.size;
  const rows = items.map((item, position) => {
    const on = view.on.has(item.id);
    const keep = view.keep === item.id;
    const marks = [];
    if (item.id === group.suggested_id) marks.push('<span class="dup-mark">おすすめ</span>');
    if ((item.verdict || '') === 'keep') marks.push('<span class="dup-mark keep">キープ</span>');
    if ((item.verdict || '') === 'reject') marks.push('<span class="dup-mark drop">ボツ</span>');
    return `<div class="dup-item${keep ? ' keep' : ''}" data-id="${esc(item.id)}" data-g="${i}">`
      + `<label class="dup-on" title="まとまりに入れる">`
      + `<input type="checkbox" class="dup-on-box" data-id="${esc(item.id)}" data-g="${i}"`
      + `${on ? ' checked' : ''}></label>`
      + `<label class="dup-keep" title="残す 1 枚にする">`
      + `<input type="radio" name="dup-keep-${i}" class="dup-keep-box" data-id="${esc(item.id)}"`
      + ` data-g="${i}"${keep ? ' checked' : ''}></label>`
      + `<span class="dup-no num">${position + 1}</span>`
      + `<img loading="lazy" decoding="async" src="/api/assets/${esc(item.id)}/thumb?size=256" alt="">`
      + `<span class="dup-meta num">${esc(item.width)} × ${esc(item.height)}`
      + ` ・ ${esc(fmtBytes(item.size))} ・ ${esc(fmtDay(item.first_seen_at))}</span>`
      + `<span class="dup-path mono">${esc(item.path || item.id)}</span>`
      + marks.join('')
      + '</div>';
  }).join('');
  return `<div class="dup-group" data-g="${i}">
    <div class="dup-ghead">
      <span class="dup-title">同じ絵が ${items.length} 枚</span>
      <span class="dup-dist num">距離 ${esc(group.max_distance_within)}</span>
      <span class="dup-sug">おすすめ: ${esc(labelOf(items.findIndex((it) => it.id === group.suggested_id) + 1))}`
      + ` ・ ${esc(group.reason)}</span>
      <span class="spacer"></span>
      <button class="dup-make" data-g="${i}"${picked < 2 ? ' disabled' : ''}>まとまりにする</button>
      <button class="dup-exclude" data-g="${i}"${picked !== 2 ? ' disabled' : ''}>別物として確定</button>
    </div>
    <div class="dup-items">${rows}</div>
  </div>`;
}

export function exclusionsHtml() {
  if (!state.showExclusions) return '';
  const items = state.exclusions;
  const rows = items.length
    ? items.map((row) => `<div class="dup-ex-row">
        <img loading="lazy" src="/api/assets/${esc(row.a_id)}/thumb?size=256" alt="">
        <img loading="lazy" src="/api/assets/${esc(row.b_id)}/thumb?size=256" alt="">
        <span class="dup-ex-ids mono">${esc(row.a_id.slice(0, 8))} / ${esc(row.b_id.slice(0, 8))}</span>
        <span class="dup-ex-reason">${esc(row.reason || '理由なし')}</span>
        <span class="stat">${esc(row.actor === 'agent' ? 'エージェント' : '人')} ・ ${esc(fmtDay(row.at))}</span>
        <span class="spacer"></span>
        <button class="dup-unexclude" data-a="${esc(row.a_id)}" data-b="${esc(row.b_id)}">解除</button>
      </div>`).join('')
    : '<div class="note">別物として確定した組はありません。</div>';
  return `<div class="dup-exclusions"><div class="dup-exhead">別物として確定した組`
    + `<span class="stat">解除すると、もう一度候補に出ます。</span></div>${rows}</div>`;
}

export function listHtml() {
  if (state.busy && !state.groups.length) return '<div class="note">読み込んでいます。</div>';
  const groups = state.groups.length
    ? state.groups.map((group, i) => groupHtml(group, i)).join('')
    : '<div class="note">この距離の候補はありません。'
      + 'しきい値を上げる（≤ 10）と、似ている物まで出ます。</div>';
  return `${exactHtml()}${computeHtml()}${headHtml()}<div class="dup-groups">${groups}</div>`
    + exclusionsHtml();
}

export function barHtml() {
  const picked = pickedIds();
  const all = allPicked();
  return `<span class="dup-picked">選択 ${picked.length} 枚</span>`
    + '<span class="spacer"></span>'
    // **（監査の注意）既定では 1 枚も選ばない。** 全部を選ぶのは**人が押したときだけ**
    // （「全部選ぶ」は残す。危ないのは「既定で選ばれている」こと）
    + `<button class="dup-all">${all ? '全部外す' : '全部選ぶ'}</button>`
    + `<button class="dup-delete"${picked.length ? '' : ' disabled'}>`
    + `選んだ ${picked.length} 枚を削除へ回す</button>`
    + `<button class="dup-show-ex">別物として確定した組</button>`;
}

export function messageHtml() {
  if (!state.msg) return '';
  return `<div class="dup-msg${state.bad ? ' bad' : ''}">${esc(state.msg)}`
    + (state.made
      ? ` <a class="back" href="#/group/${esc(state.made)}">まとまりレビューへ</a>` : '')
    + '</div>';
}

// ---- 読み込み（`GET` は書かない）----

async function load() {
  state.busy = true;
  render();
  const params = new URLSearchParams({ max_distance: String(state.max) });
  const [near, exact] = await Promise.all([
    fetch(`${NEAR}?${params}`).then((r) => r.json()),
    fetch(EXACT).then((r) => r.json()),
  ]);
  state.groups = near.groups || [];
  state.hashed = near.hashed || 0;
  state.unhashed = near.unhashed || 0;
  state.totalGroups = near.total_groups || 0;
  state.totalImages = near.total_images || 0;
  // **（P8-3 の取り落とし調査）** 「別物として確定」で隠れている組の数（数の辻褄を画面に出す）
  state.excludedPairs = near.excluded_pairs || 0;
  state.exact = { count: exact.count || 0, message: exact.message || null };
  state.view = makeView(state.groups);
  state.busy = false;
  render();
}

async function loadExclusions() {
  const body = await (await fetch(EXCLUSIONS)).json();
  state.exclusions = body.items || [];
}

function render() {
  const head = $('dup-headline');
  if (head) head.innerHTML = messageHtml();
  const list = $('dup-list');
  if (list) list.innerHTML = listHtml();
  const bar = $('dup-bar');
  if (bar) bar.innerHTML = barHtml();
  const brief = $('dup-brief');
  if (brief) {
    brief.textContent = `距離 ≤ ${state.max}`
      + (state.totalGroups ? ` ・ ${state.totalGroups} 群` : '');
  }
}

// ---- 押されたとき ----

async function makeGroup(i) {
  const view = viewOf(i);
  const ids = [...view.on];
  if (ids.length < 2) { state.msg = 'まとまりには 2 枚以上が要ります。'; state.bad = false; render(); return; }
  const res = await fetch(GROUPS, {
    method: 'POST',
    headers: human(),
    // **（監査 D-4）題名に括弧を使わない**（まとまりレビューの見出しに出る。§6 の語）
    body: JSON.stringify({
      title: `重複の候補: 距離 ${state.groups[i]?.max_distance_within} の ${ids.length} 枚`,
      kind: 'duplicates', policy: 'pick_one', asset_ids: ids,
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) { state.msg = body.detail || `まとまりを作れません（${res.status}）`; state.bad = true; render(); return; }
  state.made = body.id;
  state.msg = 'まとまりを作りました。代表を選ぶのはまとまりレビューで行います。';
  state.bad = false;
  render();
}

async function excludePair(i) {
  const view = viewOf(i);
  const ids = [...view.on];
  if (ids.length !== 2) { state.msg = '別物として確定するには 2 枚だけを選んでください。'; render(); return; }
  const res = await fetch(EXCLUDE, {
    method: 'POST',
    headers: human(),
    body: JSON.stringify({ a_id: ids[0], b_id: ids[1] }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) { state.msg = body.detail || `確定できません（${res.status}）`; state.bad = true; render(); return; }
  state.msg = 'この 2 枚は別物として覚えました。解除できます。';
  state.bad = false;
  await loadExclusions();
  await load();
}

async function removeExclusion(a, b) {
  const res = await fetch(REMOVE, {
    method: 'POST', headers: human(), body: JSON.stringify({ a_id: a, b_id: b }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) { state.msg = body.detail || `解除できません（${res.status}）`; state.bad = true; render(); return; }
  state.msg = '解除しました。もう一度候補に出ます。';
  state.bad = false;
  await loadExclusions();
  await load();
}

async function compute() {
  const res = await fetch(COMPUTE, {
    method: 'POST', headers: human(), body: JSON.stringify({ force: false }),
  });
  const body = await res.json().catch(() => ({}));
  if (res.status !== 202) {
    state.msg = body.detail || `計算を始められません（${res.status}）`;
    state.bad = true;
    render();
    return;
  }
  state.job = { id: body.job_id, state: 'running',
                progress: { done: 0, total: body.total || 0 }, total: body.total || 0 };
  state.msg = '';
  state.bad = false;
  render();
  startPoll();
}

async function pollJob() {
  if (!state.job) return;
  try {
    const body = await (await fetch(`/api/jobs/${encodeURIComponent(state.job.id)}`)).json();
    state.job = body;
    if (!['running', 'queued'].includes(body.state)) {
      stopPoll();
      await load();                       // 計算が終わったら群を作り直す
      if (state.unhashed === 0) state.job = null;
    }
  } catch (error) { /* 次の周期で再挑戦する */ }
  render();
}

/** **画面を開いている間だけ** 2 秒ごとに進行を見る（SSE は作らない）。 */
export function startPoll(pollMs = 2000) {
  stopPoll();
  if (state.job && pollMs > 0) state.timer = setInterval(() => { pollJob(); }, pollMs);
}

export function stopPoll() {
  if (state.timer !== null) { clearInterval(state.timer); state.timer = null; }
}

export function pollActive() { return state.timer !== null; }

async function cancelJob(id) {
  await fetch(`/api/jobs/${encodeURIComponent(id)}/cancel`, { method: 'POST', headers: human() });
  await pollJob();
}

function toDelete() {
  const ids = pickedIds();
  if (!ids.length) return;
  toDeleteHash(ids);
}

/** 全部を選ぶ／外す（人が押したときだけ。**既定では選ばない**）。 */
function toggleAll() {
  const on = !allPicked();
  state.groups.forEach((group, i) => {
    const view = viewOf(i);
    view.on = new Set(on ? (group.items || []).map((it) => it.id) : []);
  });
  state.made = null;
  render();
}

export async function onClick(event) {
  const target = event.target;
  const hit = (selector) => target.closest(selector);
  const computeBtn = hit('.dup-do-compute');
  if (computeBtn) { await compute(); return; }
  const cancelBtn = hit('.dup-cancel');
  if (cancelBtn) { await cancelJob(cancelBtn.dataset.id); return; }
  const makeBtn = hit('.dup-make');
  if (makeBtn) { await makeGroup(Number(makeBtn.dataset.g)); return; }
  const exBtn = hit('.dup-exclude');
  if (exBtn) { await excludePair(Number(exBtn.dataset.g)); return; }
  const unexBtn = hit('.dup-unexclude');
  if (unexBtn) { await removeExclusion(unexBtn.dataset.a, unexBtn.dataset.b); return; }
  const showBtn = hit('.dup-show-ex');
  if (showBtn) {
    state.showExclusions = !state.showExclusions;
    if (state.showExclusions) await loadExclusions();
    render();
    return;
  }
  if (hit('.dup-all')) { toggleAll(); return; }
  if (hit('.dup-delete')) toDelete();
}

export function onChange(event) {
  const target = event.target;
  const box = target.closest('.dup-on-box');
  const keep = target.closest('.dup-keep-box');
  const node = box || keep;
  if (!node) return;
  const view = viewOf(Number(node.dataset.g));
  if (box) {
    if (target.checked) view.on.add(box.dataset.id); else view.on.delete(box.dataset.id);
  } else {
    view.keep = keep.dataset.id;
  }
  state.made = null;
  render();
}

// ---- 入口 ----

export async function showDuplicates(search) {
  const parsed = query(search);
  state.max = parsed.max;
  document.body.classList.add('duplicating');
  await load();
  const buttons = THRESHOLDS.map((n) => `<button class="dup-th${n === state.max ? ' on' : ''}"`
    + ` data-max="${n}">距離 ≤ ${n}</button>`).join('');
  const holder = $('dup-thresholds');
  if (holder) holder.innerHTML = buttons;
}

export function hideDuplicates() {
  document.body.classList.remove('duplicating');
  stopPoll();
}

export function wireDuplicates() {
  const holder = $('dup-thresholds');
  if (holder) {
    holder.addEventListener('click', (event) => {
      const btn = event.target.closest('.dup-th');
      if (btn) location.hash = `#/duplicates?max=${btn.dataset.max}`;
    });
  }
  const list = $('dup-list');
  if (list) {
    list.addEventListener('click', onClick);
    list.addEventListener('change', onChange);
  }
  const bar = $('dup-bar');
  if (bar) {
    bar.addEventListener('click', onClick);
    bar.addEventListener('change', onChange);
  }
}
