// 要求の件数と、タブのタイトル（P6-1b）
// 設計: docs/p6-design.md §5.4（件数と知らせ方）・§0.10（画面を開いている間だけ 5 秒ごとに取得）、
//       docs/frontend-design.md §4.5（件数と通知）・§4.5.1（上部バーに出す 6 つ。P8-5）
//
// 約束:
// - **画面を奪わない。** 要求が来ても画面を切り替えない（件数とタブのタイトルだけ。§5.1）
// - **音は使わない**（`design.md` §16.1）
// - SSE は作らない（`p5-design.md` §0.1）。**開いている間だけ** 5 秒ごとに叩く
// - **黙って失敗しない**（P8-5）: バックアップの失敗（`last_error`）と走査中も
//   上部バーに出す。**同じ 1 行を各所に写さない**（P8-4 の監査 G-6）
// - **（P8-5）`GET` でも人だと名乗る**（P8-3 の監査 D-8。`undoable` / `mine` は
//   「誰が読んだか」で決まるので、名乗らないと**人の画面で「取り消す」が消える**）
// - このモジュールは**読み込んだだけでは何も始めない**（`wireBadge()` を呼んだときだけ）。
//   テスト（`tools/gui_smoke.mjs`）がタイマーを残さないため

const COUNT_API = '/api/review-requests?state=open&count_only=1';
const JOBS_API = '/api/jobs?limit=5';       // P4-3: 進行と完了（§5.5）
// P8-3: 取り消せる削除（`frontend-design.md` §4.6 の上部バーの入口）。**読むだけ**
const DELETES_API = '/api/pending-deletes';
// P8-5: バックアップの失敗と走査中（`frontend-design.md` §4.5.1）。**どちらも読むだけ**
const BACKUP_API = '/api/backup';
const SCAN_API = '/api/scan';
const TITLE_BASE = 'image-reviewer';       // `(3) image-reviewer` の土台（§5.4）
const POLL_MS = 5000;
const DONE_NOTICE_MS = 60000;              // 「終わりました」を出しておく長さ

const $ = (id) => document.getElementById(id);

// 「あと 3:12」の書き方は `pending.js` と 1 つにする（**画面の語は 1 つ**。§4.6）
import { fmtRemain } from './pending.js';

/** **読むときも人だと名乗る**（P8-3 の監査 D-8。`pending.js` の `asHuman()` と同じ理由）。 */
function asHuman() {
  return { 'X-Image-Reviewer-Actor': 'human' };
}

let timer = null;
let lastStates = new Map();                // job_id → state（実行中 → 完了 の移り変わりを見る）
let doneNotice = null;                     // {at, text}
let lastSeenAt = 0;                        // 前回の周期の時刻（短いジョブの完了を拾う。監査 C-3）
let notified = new Set();                  // 「終わりました」を出した job（二度言わない）

// バーの `要求 3`（0 なら出さない。`--accent` の文字。`frontend-design.md` §4.5）
export function renderBadge(count) {
  const el = $('stat-requests');
  if (!el) return;
  const n = Number(count) || 0;
  el.textContent = n > 0 ? `要求 ${n}` : '';
  el.hidden = n <= 0;
}

// タブのタイトルを `(3) image-reviewer` にする（0 なら素の名前。§5.4）
export function applyTitle(count) {
  const n = Number(count) || 0;
  if (typeof document !== 'undefined') {
    document.title = n > 0 ? `(${n}) ${TITLE_BASE}` : TITLE_BASE;
  }
}

export function renderCount(count) {
  renderBadge(count);
  applyTitle(count);
}

async function fetchCount() {
  try {
    const res = await fetch(COUNT_API);
    if (!res.ok) return;
    const body = await res.json();
    renderCount((body.counts || {}).open ?? 0);
  } catch (error) {
    // 件数が取れないだけで画面は止めない（次の周期で再挑戦する）
  }
}

// ---- P4-3: ジョブの進行と完了（`p4-design.md` §5.5）----
//
// - 進行中: 「タグ付け中 12 / 263」（押すと `#/jobs`）
// - 終わった直後: 「タグ付けが終わりました（263 枚）」を 60 秒だけ（**音は使わない**）
// - **画面を開いている間だけ**見る（5 秒ごと。SSE は作らない）

export function renderJobBadge(jobs, now = Date.now()) {
  const el = $('stat-jobs');
  if (!el) return;
  const items = jobs || [];
  const active = items.filter((j) => j.state === 'running' || j.state === 'queued');
  // **P4-3 の監査 C-3**: 前回の周期以降に `finished_at` が入った `done` も知らせる。
  // 以前は「`running` を見たことがある job」だけだったので、**5 秒より短いジョブ
  // （画面の「語を足す」の後の 1 枚など）は「終わりました」が出なかった**。
  const since = lastSeenAt || now;          // 初回は「いま」から（古い完了で知らせない）
  lastSeenAt = now;
  for (const job of items) {
    const before = lastStates.get(job.id);
    const sawActive = before === 'running' || before === 'queued';
    const finishedNow = job.state === 'done' && job.finished_at
      && Date.parse(job.finished_at) >= since;
    if (job.state === 'done' && !notified.has(job.id) && (sawActive || finishedNow)) {
      const total = (job.progress || {}).total || 0;
      doneNotice = { at: now, text: `タグ付けが終わりました（${total} 枚）` };
      notified.add(job.id);
    }
    lastStates.set(job.id, job.state);
  }
  let text = '';
  let cls = '';
  if (active.length) {
    const job = active[0];
    const done = (job.progress || {}).done || 0;
    const total = (job.progress || {}).total || 0;
    text = `タグ付け中 ${done} / ${total}`;
    cls = 'on';
  } else if (doneNotice && now - doneNotice.at < DONE_NOTICE_MS) {
    text = doneNotice.text;
    cls = 'done';
  } else {
    doneNotice = null;
  }
  el.textContent = text;
  el.hidden = !text;
  el.classList.toggle('job-on', cls === 'on');
  el.classList.toggle('job-done', cls === 'done');
}

async function fetchJobs() {
  try {
    const res = await fetch(JOBS_API);
    if (!res.ok) return;
    const body = await res.json();
    renderJobBadge(body.items || []);
  } catch (error) {
    // 進行が取れないだけ（次の周期で再挑戦する）
  }
}

// ---- P8-3: 取り消せる削除の入口（上部バー。§4.6・§11）----
//
// - **まだ戻せる行が 1 件でもある間**だけ出す（**段 1 の行だけでも出す**。P8-5 の追い込み）
// - 件数は返った行の数をそのまま出す（段 1〜3。`GET /api/pending-deletes` の `count` と同じ）
// - **窓のある段 3 があれば**いちばん短い残り時間を添える（`最近の削除 3 ・ あと 3:12`。
//   **窓が切れる順**。§11）。窓の無い段 1・2 の行だけなら `最近の削除 88`（残り時間は出さない）
// - **`GET` は書かない**（残り時間はサーバのタイマーだけが減らす）。ここも読むだけ
//
// **P8-5 の追い込み（実装漏れ）**: 前の版は `state === 'pending' && remaining_sec != null`
// （＝段 3 の窓がある行）だけで数えていた。`pending()` は P8-5 で段 1〜3 を返すようになったのに、
// ここが段 3 のままだったので、**段 1 で外しただけの行しか無いときは入口が 1 つも出ず、
// 画面から戻す導線が見えなかった**（`asset.deleted_at` は立っているのに、
// `#/pending-deletes` へ入る道が URL だけだった。実データで起きていた）。

export function renderDeleteBadge(items) {
  const el = $('stat-deletes');
  if (!el) return;
  // 段 1（`hidden`）・段 2（`trashed`）・段 3（`pending`）・戻せなかった行（`stuck`）は
  // **どれも画面の「最近の削除」に出て、そこから戻せる**（`deletions.py` の `pending()` が
  // 戻せない行＝`purged` / `restored` を元から返さない）
  const rows = (items || []).filter((it) => it && it.id);
  const windows = rows
    .filter((it) => it.state === 'pending' && it.remaining_sec != null)
    .map((it) => Number(it.remaining_sec) || 0);
  // **（ワーディング監査 W-71）** メタ情報の中黒をやめ、「あと 3:12」は括弧に入れる（規則 1）
  const text = rows.length
    ? `最近の削除 ${rows.length}`
      + (windows.length ? `（あと ${fmtRemain(Math.min(...windows))}）` : '')
    : '';
  el.textContent = text;
  el.hidden = !text;
}

async function fetchDeletes() {
  try {
    const res = await fetch(DELETES_API, { headers: asHuman() });
    if (!res.ok) return;
    const body = await res.json();
    renderDeleteBadge(body.items || []);
  } catch (error) {
    // 件数が取れないだけ（次の周期で再挑戦する）
  }
}

// ---- P8-5: バックアップの失敗（上部バー。§4.5.1）----
//
// - `GET /api/backup` の `last_error` があるときだけ「バックアップに失敗しています」を出す
// - **503 のときは「読み取り専用です」**（DB が壊れている / 版が新しい。P8-4 の再確認 D-2）
// - **（P9 の監査 D-1 / D-2）503 でも「読み取り専用」とは限らない。** `disk i/o error`（一時的な
//   読み書き。503 `io_error`）と `database is locked`（503 `busy`）は**もう一度で直る**ので、
//   「読み取り専用です」（＝バックアップから戻す話）とは**別の語**にする。読み取り専用として
//   出すのは `read_only` / `db_error`（DB が壊れている）と、`code` の無い古いサーバだけ
// - **文言はここ 1 つ**。押すと `#/settings` へ行き、そこで全文が読める（G-6）
//
// 「読み取り専用」の見せ方: 状態そのものが読めない（503）ときも**同じ場所に出す**。

/** その 503 は「読み取り専用」か（**一時的な物を読み取り専用と言わない**。D-1 / D-2）。 */
export function isReadOnlyStatus(status, state) {
  if (Number(status) !== 503) return Boolean((state || {}).read_only);
  const code = String((state || {}).code || '');
  // `code` が無いのは古いサーバ（今までどおり読み取り専用として出す）
  return code === '' || code === 'read_only' || code === 'db_error';
}

export function renderBackupBadge(state, { status = 0 } = {}) {
  const el = $('stat-backup');
  if (!el) return;
  const got = state || {};
  const unavailable = Number(status) === 503;
  const readOnly = isReadOnlyStatus(status, got);
  // **（D-1 / D-2）** 503 でも一時的な物（`io_error` / `busy`）は「失敗」として出す
  const failed = Boolean(got.last_error) || (unavailable && !readOnly);
  let text = '';
  if (readOnly) text = '読み取り専用です';
  else if (failed) text = 'バックアップに失敗しています';
  el.textContent = text;
  el.hidden = !text;
  el.classList.toggle('bk-readonly', readOnly);
  el.classList.toggle('bk-failed', failed);
  // **押すと詳細**（全文は `#/settings` の「バックアップ」にある。§4.5.1）
  const why = got.last_error || got.detail || '状態を読めません';
  el.title = readOnly
    ? 'DB を読み取り専用で開いています。押すと設定に案内が出ます'
    : (failed ? `最後の失敗: ${String(why).slice(0, 300)}（押すと設定に全文が出ます）`
      : '');
}

async function fetchBackup() {
  try {
    const res = await fetch(BACKUP_API, { headers: asHuman() });
    if (res.status === 503) {
      const body = await res.json().catch(() => ({}));
      renderBackupBadge({ ...body, read_only: true }, { status: 503 });
      return;
    }
    if (!res.ok) { renderBackupBadge(null); return; }        // 404 など（古いサーバ。黙る）
    renderBackupBadge(await res.json());
  } catch (error) {
    // 状態が取れないだけ（次の周期で再挑戦する）
  }
}

// ---- P8-5: 走査中（上部バー。§4.5.1）----
//
// 「走査中です」だけ（走査は job を持たないので進行の枚数は出せない。§3.4）。
// **押せない**（行き先が無い）。取れなければ出さない（古いサーバでは 404）。

export function renderScanBadge(state) {
  const el = $('stat-scan');
  if (!el) return;
  const on = Boolean(state && state.scanning);
  el.textContent = on ? '走査中です' : '';
  el.hidden = !on;
  el.title = on ? '走査中は削除と取り消しが待ちます（順番に進めます）' : '';
}

async function fetchScan() {
  try {
    const res = await fetch(SCAN_API, { headers: asHuman() });
    if (!res.ok) { renderScanBadge(null); return; }
    renderScanBadge(await res.json());
  } catch (error) {
    // 走査中かどうかが取れないだけ
  }
}

// 画面を開いている間だけ回す。`stop` を呼ぶか、タブを閉じれば止まる
export function wireBadge({ pollMs = POLL_MS } = {}) {
  stopBadge();
  fetchCount();
  fetchJobs();
  fetchDeletes();
  fetchBackup();
  fetchScan();
  if (pollMs > 0) {
    timer = setInterval(() => {
      fetchCount(); fetchJobs(); fetchDeletes(); fetchBackup(); fetchScan();
    }, pollMs);
  }
}

export function stopBadge() {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
}

// テストのために状態を戻す（タイマーは残さない）
export function resetBadge() {
  stopBadge();
  lastStates = new Map();
  doneNotice = null;
  lastSeenAt = 0;
  notified = new Set();
}
