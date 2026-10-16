// 1 つの画面の写真を撮る（実機の確認と記録用。P4-3）
//
//   node tools/gui_shot.mjs --base http://127.0.0.1:8791 --hash "#/tags" --out .tmp-audit-redo/shot.png
//   node tools/gui_shot.mjs --base http://127.0.0.1:8791 --hash "#/jobs" --out shot.png --viewport 1920x1080 --wait 2500
//
// 設計: docs/p4-design.md §8.3（実物で見る）/ `tools/gui_layout.mjs` と同じ作り
// （Chrome headless + CDP。**プロファイルは一時フォルダに作り、終わったら消す**）
//
// 約束:
// - サーバは**別ポートで立てた複製**に向ける（実データを触らない）
// - 消せないプロファイルは残しても失敗にしない（Chrome がまだ掴んでいることがある）

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function argOf(name, fallback = null) {
  const at = process.argv.indexOf(`--${name}`);
  return at >= 0 && process.argv[at + 1] ? process.argv[at + 1] : fallback;
}

const BASE = (argOf('base', 'http://127.0.0.1:8791') || '').replace(/\/$/, '');
const HASH = argOf('hash', '');
const OUT = argOf('out', join('.tmp-audit-redo', 'shot.png'));
const WAIT = Number(argOf('wait', '2500'));
const [W, H] = (argOf('viewport', '1400x900') || '1400x900').split('x').map(Number);
const CHROME = argOf('chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe');
const PORT = Number(argOf('port', '9333'));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), 'gui-shot-'));

const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  `--window-size=${W},${H}`, '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
  `${BASE}/${HASH}`,
], { stdio: 'ignore' });

async function pageTarget() {
  for (let i = 0; i < 40; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      if (res.ok) {
        const list = await res.json();
        const page = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
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

try {
  await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });
  await send('Page.enable');
  await send('Page.reload', { ignoreCache: true });
  await sleep(WAIT);
  // `--scroll <セレクタ>`: その要素まで送ってから撮る（詳細パネルのように**内側がスクロールする**画面で要る）
  const SCROLL = argOf('scroll', null);
  if (SCROLL) {
    await send('Runtime.evaluate', {
      expression: `(() => { const el = document.querySelector(${JSON.stringify(SCROLL)});`
        + ` if (!el) return 'not found'; el.scrollIntoView({ block: 'center' }); return 'ok'; })()`,
      returnByValue: true,
    });
    await sleep(600);
  }
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(OUT, Buffer.from(shot.data, 'base64'));
  console.log(`撮りました: ${OUT}（${W}x${H} / ${HASH || '(一覧)'}${SCROLL ? ` / ${SCROLL} まで` : ''}）`);
} finally {
  ws.close();
  chrome.kill();
  await sleep(500);
  try { rmSync(profile, { recursive: true, force: true }); } catch (error) { /* 残ってもよい */ }
}
