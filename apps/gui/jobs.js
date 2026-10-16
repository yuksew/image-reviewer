// ジョブ（`#/jobs`。P4-3）
// 設計: docs/p4-design.md §5.3（進行・中断・失敗した項目＋もう一度・**2 秒ごとにポーリング**）/
//       §3.3（`GET /api/jobs` / `{id}` / `{id}/items` / `cancel`）/ docs/frontend-design.md §4.13
//
// 約束:
// - **ポーリングは画面を開いている間だけ**（離れたら止める。P6-1b の監査と同じ観点）
// - **`GET` は書かない**。中断は `POST /api/jobs/{id}/cancel`
// - 失敗の全部は `GET /api/jobs/{id}/items?state=failed` で読む（`items_failed` は先頭 20 件）

const API = '/api/jobs';
export const POLL_MS = 2000;

const $ = (id) => document.getElementById(id);

const state = { items: [], detail: null, timer: null, wired: false };

export const STATE_LABEL = {
  queued: '待っています', running: '実行中', done: '完了', failed: '失敗', cancelled: '中断',
};

export function esc(value) {
  return String(value ?? '').replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/** 1 枚あたりの秒と残り時間（実測から。§5.3）。**測れないときは「—」**。 */
export function pace(job, now = Date.now()) {
  const done = Number(job.progress?.done || 0);
  const total = Number(job.progress?.total || 0);
  const started = job.started_at ? Date.parse(job.started_at) : null;
  if (!started || done <= 0) return { perItem: null, remainSec: null };
  // **P4-3 の監査 B-1**: 終わったジョブは `finished_at` で計算する（**値が動かない**）。
  // 以前は状態を問わず `now - started_at` だったので、2 秒ごとの描き直しで
  // 「1 枚 1 分 20 秒」が 4 秒後に「1 分 22 秒」と**増え続けた**（1.3 秒で終わった 3 枚のジョブ）。
  const finished = job.finished_at ? Date.parse(job.finished_at) : null;
  const end = finished !== null ? finished : now;
  const perItem = (Math.max(0, end - started) / 1000) / done;
  const remain = job.state === 'running' || job.state === 'queued'
    ? Math.max(0, Math.round(perItem * Math.max(0, total - done))) : 0;
  return { perItem, remainSec: remain };
}

export function fmtSec(sec) {
  if (sec == null) return '—';
  if (sec < 60) return `${sec.toFixed(1)} 秒`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec - m * 60);
  return `${m} 分 ${s} 秒`;
}

/** 1 つの job の行（進行・中断・失敗）。 */
export function jobHtml(job, now = Date.now()) {
  const { perItem, remainSec } = pace(job, now);
  const done = Number(job.progress?.done || 0);
  const total = Number(job.progress?.total || 0);
  const pct = total ? Math.round((done / total) * 100) : 0;
  const counts = job.counts || {};
  const active = job.state === 'running' || job.state === 'queued';
  const cancel = active
    ? `<button class="jb-cancel" data-id="${esc(job.id)}">中断</button>` : '';
  const failedCount = Number(counts.failed || 0);
  const failed = (job.items_failed || []).length
    ? `<div class="jb-failed"><b>失敗 ${failedCount || job.items_failed.length} 件</b>`
      + `<div class="jb-failed-list">`
      + job.items_failed.map((it) => `<div class="jb-fail"><span class="mono">${esc(it.ref)}</span>`
        + `<span class="jb-err">${esc(it.error || '')}</span></div>`).join('')
      + '</div>'
      + (failedCount > job.items_failed.length
        ? `<div class="stat">ほか ${failedCount - job.items_failed.length} 件</div>` : '')
      + `<button class="jb-again" data-id="${esc(job.id)}">もう一度</button></div>`
    : '';
  return `<div class="jb-row${active ? ' on' : ''}" data-id="${esc(job.id)}">`
    + `<div class="jb-top"><span class="jb-state jb-${esc(job.state)}">${esc(STATE_LABEL[job.state] || job.state)}</span>`
    + `<span class="jb-kind">${esc(job.kind)}</span>`
    + `<span class="jb-count num">${done} / ${total}</span>`
    + `<span class="stat">1 枚 ${esc(fmtSec(perItem))}${active ? ` ・ 残り 約 ${esc(fmtSec(remainSec))}` : ''}</span>`
    + `<span class="spacer"></span>${cancel}</div>`
    + `<div class="jb-bar"><span style="width:${pct}%"></span></div>`
    // **P4-3 の監査 A-1**: 失敗だけの job（付いた 0・飛ばした 0）でも行を出す
    + ((counts.tagged || counts.skipped || failedCount)
      ? `<div class="stat">付いた ${counts.tagged || 0} ・ 飛ばした ${counts.skipped || 0} ・ 失敗 ${failedCount}</div>` : '')
    + (job.note ? `<div class="stat">${esc(job.note)}</div>` : '')
    + (job.message ? `<div class="stat">${esc(job.message)}</div>` : '')
    + failed
    + '</div>';
}

export function listHtml(now = Date.now()) {
  if (!state.items.length) return '<div class="note">まだジョブがありません。</div>';
  return state.items.map((job) => jobHtml(job, now)).join('');
}

async function load() {
  const body = await (await fetch(`${API}?limit=50`)).json();
  state.items = body.items || [];
  const list = $('jobs-list');
  if (list) list.innerHTML = listHtml();
  const brief = $('jobs-brief');
  if (brief) {
    const active = state.items.filter((j) => j.state === 'running' || j.state === 'queued').length;
    brief.textContent = active ? `${active} 件が進行中` : `${state.items.length} 件`;
  }
}

/** 失敗した項目の全部（`items_failed` は先頭 20 件なので、必要ならここで読む）。 */
export async function loadItems(jobId, stateName = 'failed') {
  const body = await (await fetch(`${API}/${encodeURIComponent(jobId)}/items?state=${stateName}&limit=200`)).json();
  return body.items || [];
}

async function cancel(jobId) {
  await fetch(`${API}/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
  await load();
}

/** 「もう一度」= 失敗した項目だけを新しいジョブにする（`ref` は asset_id。§3.2）。 */
async function again(jobId) {
  const items = await loadItems(jobId);
  const ids = items.map((it) => it.ref).filter(Boolean);
  if (!ids.length) return;
  const res = await fetch('/api/assets/tag', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ asset_ids: ids, engine: 'auto' }),
  });
  const body = await res.json().catch(() => ({}));
  if (res.ok && body.job_id) await load();
}

export async function showJobs() {
  document.body.classList.add('jobs');
  await load();
  startPoll();
}

export function hideJobs() {
  document.body.classList.remove('jobs');
  stopPoll();
}

export function startPoll(pollMs = POLL_MS) {
  stopPoll();
  if (pollMs > 0) state.timer = setInterval(() => { load().catch(() => {}); }, pollMs);
}

export function stopPoll() {
  if (state.timer !== null) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

export function pollActive() {
  return state.timer !== null;
}

export function wireJobs() {
  const list = $('jobs-list');
  if (list) {
    list.addEventListener('click', (event) => {
      const cancelBtn = event.target.closest('.jb-cancel');
      if (cancelBtn) { cancel(cancelBtn.dataset.id); return; }
      const againBtn = event.target.closest('.jb-again');
      if (againBtn) again(againBtn.dataset.id);
    });
  }
  const back = $('jobs-back');
  if (back) back.addEventListener('click', () => { location.hash = ''; });
  state.wired = true;
}
