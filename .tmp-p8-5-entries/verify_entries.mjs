// **本物の Chrome** で上部バーの入口を確かめる（P8-5 の追い込み。実装者の手元の確認）
//
//   node .tmp-p8-5-entries/verify_entries.mjs --base http://127.0.0.1:8797 --out .tmp-p8-5-entries/shots
//
// 見るもの（複製のサーバに向ける。**実データの 8790 では回さない**）:
// 1. ヘッダの「重複の整理」が**見える**（スクロール無し。`rect` が窓の中）→ **押すと `#/duplicates`**
// 2. 「最近の削除」が**まだ戻せる行があるとき見える**（段 1 だけでも出る）→ **押すと `#/pending-deletes`**、
//    **行が出て「戻す」が押せる**
// 3. 上部バーが横に溢れない（1400x900 と 768x1360 の両方）
// 4. 写真を撮る（`--out` の中。**人が見て確かめられる形で残す**）
//
// 約束: `fetch` の差し替えはしない（**本物のサーバを見る**）。押すのは**道を変える入口だけ**
// （「戻す」は**別の検査**が 1 回だけ押す。ここでは**押せるか**を見る）。

import { spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function argOf(name, fallback = null) {
  const at = process.argv.indexOf(`--${name}`);
  return at >= 0 && process.argv[at + 1] ? process.argv[at + 1] : fallback;
}

const BASE = (argOf('base', 'http://127.0.0.1:8797') || '').replace(/\/$/, '');
const OUT = argOf('out', '.tmp-p8-5-entries/shots');
const PORT = Number(argOf('port', '9341'));
const CHROME = argOf('chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe');
const VIEWPORTS = [[1400, 900], [768, 1360]];

mkdirSync(OUT, { recursive: true });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), 'verify-entries-'));

const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1400,900', '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
  `${BASE}/#/`,
], { stdio: 'ignore' });

async function pageTarget() {
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      if (res.ok) {
        const page = (await res.json()).find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
        if (page) return page.webSocketDebuggerUrl;
      }
    } catch (error) { /* まだ起動していない */ }
    await sleep(250);
  }
  throw new Error('Chrome のページが見つかりません');
}

const ws = new WebSocket(await pageTarget());
let seq = 0;
const pending = new Map();
ws.addEventListener('message', (event) => {
  const msg = JSON.parse(String(event.data));
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(msg.error.message)); else resolve(msg.result);
  }
});
await new Promise((resolve, reject) => {
  ws.addEventListener('open', resolve);
  ws.addEventListener('error', () => reject(new Error('CDP につながりません')));
});
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params }));
});
async function evaluate(expression) {
  const got = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (got.exceptionDetails) throw new Error(JSON.stringify(got.exceptionDetails));
  return got.result.value;
}
async function shot(name) {
  const png = await send('Page.captureScreenshot', { format: 'png' });
  const path = join(OUT, name);
  writeFileSync(path, Buffer.from(png.data, 'base64'));
  return path;
}

// 上部バーを測る（入口の見え方と、はみ出し）
const MEASURE = `(() => {
  const read = (id) => {
    const el = document.getElementById(id);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { id, hidden: el.hidden === true, text: (el.textContent || '').trim(),
             href: el.getAttribute('href'),
             top: Math.round(r.top), left: Math.round(r.left), right: Math.round(r.right),
             width: Math.round(r.width), height: Math.round(r.height),
             visible: el.hidden !== true && r.width > 0 && r.height > 0
               && r.top >= 0 && r.top < innerHeight && r.right <= innerWidth + 1 };
  };
  const bar = document.querySelector('#app > .topbar');
  return {
    bar: bar ? { scrollWidth: bar.scrollWidth, clientWidth: bar.clientWidth,
                 overflow: Math.max(0, bar.scrollWidth - bar.clientWidth) } : null,
    pageOverflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
    duplicates: read('stat-duplicates'),
    deletes: read('stat-deletes'),
    settings: read('stat-settings'),
  };
})()`;

const PRESS_DUP = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const el = document.getElementById('stat-duplicates');
  if (!el) return { pressed: false };
  el.click();
  await wait(1600);
  const root = document.getElementById('duplicates');
  const groups = document.querySelectorAll('#dup-list .dup-group').length;
  return { pressed: true, hash: location.hash, bodyClass: document.body.className,
           shown: !!root && root.getBoundingClientRect().height > 0,
           title: (document.querySelector('#duplicates .name') || {}).textContent || '',
           groups, brief: (document.getElementById('dup-brief') || {}).textContent || '' };
})()`;

const PRESS_DEL = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const el = document.getElementById('stat-deletes');
  if (!el || el.hidden === true) return { pressed: false, hidden: true };
  el.click();
  await wait(1800);
  const root = document.getElementById('pending');
  const rows = [...document.querySelectorAll('#pd-running .pd-row')];
  const undo = [...document.querySelectorAll('#pd-running .pd-undo')];
  const first = undo[0] || null;
  const r = first ? first.getBoundingClientRect() : null;
  // **段 1 の行の「戻す」**を 1 つ探す（人が押す導線そのもの）
  const stage1 = undo.find((b) => (b.textContent || '').trim() === '戻す') || null;
  const r1 = stage1 ? stage1.getBoundingClientRect() : null;
  return {
    pressed: true, hash: location.hash, bodyClass: document.body.className,
    shown: !!root && root.getBoundingClientRect().height > 0,
    rows: rows.length, undoButtons: undo.length,
    firstRow: rows.length ? (rows[0].textContent || '').trim().slice(0, 60) : '',
    firstUndoText: first ? (first.textContent || '').trim() : '',
    firstUndoDisabled: first ? first.disabled === true : null,
    firstUndoVisible: !!r && r.height > 0 && r.top >= 0 && r.top < innerHeight,
    stage1UndoText: stage1 ? (stage1.textContent || '').trim() : null,
    stage1UndoDisabled: stage1 ? stage1.disabled === true : null,
    stage1UndoVisible: !!r1 && r1.height > 0 && r1.top >= 0 && r1.top < innerHeight,
    brief: (document.getElementById('pd-brief') || {}).textContent || '',
    firstRowRemain: (document.querySelector('#pd-running .pd-remain') || {}).textContent || '',
  };
})()`;

// **段 1 の行の「戻す」を実際に押す**（複製なので書いてよい。**実データでは絶対に押さない**）。
// 押した結果（1 行の知らせと行数）を返す。
const PRESS_STAGE1_UNDO = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const undo = [...document.querySelectorAll('#pd-running .pd-undo')];
  const btn = undo.find((b) => (b.textContent || '').trim() === '戻す') || null;
  if (!btn) return { pressed: false };
  const before = document.querySelectorAll('#pd-running .pd-row').length;
  const id = btn.dataset ? btn.dataset.id : null;
  btn.click();
  await wait(2500);
  return {
    pressed: true, id, before,
    after: document.querySelectorAll('#pd-running .pd-row').length,
    msg: (document.getElementById('pd-msg') || {}).textContent || '',
    firstRowAfter: (document.querySelector('#pd-running .pd-row') || {}).textContent || '',
  };
})()`;

const out = { base: BASE, viewports: [] };
try {
  for (const [width, height] of VIEWPORTS) {
    await send('Emulation.setDeviceMetricsOverride',
      { width, height, deviceScaleFactor: 1, mobile: false });
    // 1. ライブラリ（入口が見えるか）
    await send('Page.navigate', { url: 'about:blank' });
    await sleep(200);
    await send('Page.navigate', { url: `${BASE}/#/` });
    await sleep(2200);
    const lib = await evaluate(MEASURE);
    const libShot = await shot(`library-${width}x${height}.png`);
    // 2. 「重複の整理」を押す
    const dup = await evaluate(PRESS_DUP);
    const dupShot = await shot(`duplicates-${width}x${height}.png`);
    // 3. 「最近の削除」を押す（読み直してから）
    await send('Page.navigate', { url: 'about:blank' });
    await sleep(200);
    await send('Page.navigate', { url: `${BASE}/#/` });
    await sleep(2200);
    const del = await evaluate(PRESS_DEL);
    const delShot = await shot(`pending-${width}x${height}.png`);
    // 4. **段 1 の行の「戻す」を押す**（**複製なので書いてよい**。実データでは押さない）
    let undoPress = null;
    if (width === VIEWPORTS[0][0]) undoPress = await evaluate(PRESS_STAGE1_UNDO);
    out.viewports.push({ width, height, lib, dup, del, undoPress, shots: [libShot, dupShot, delShot] });
  }
  console.log(JSON.stringify(out, null, 2));
} finally {
  ws.close();
  chrome.kill();
  await sleep(500);
  try { rmSync(profile, { recursive: true, force: true }); } catch (error) { /* 残ってもよい */ }
}
