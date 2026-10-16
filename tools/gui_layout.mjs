// 比較画面のレイアウト検査（Chrome headless + CDP）。
//
// 使い方:
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --ids <id,id,...>
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --count 8         # API から拾う（比較）
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen requests # 要求の一覧（枚数の整合も見る）
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen group --group <id>  # まとまりレビュー
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen asset --ids <1 枚>  # 注記とタグの欄（P6-2 / P4-3）
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen tags             # 語の一覧（P4-3）
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen jobs             # ジョブ（P4-3）
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen recipe --ids <1 枚>  # 条件の記録（P7-4）
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen recipes          # 記録の一覧（P7-4）
//   オプション: --viewport 1200x800 / --dump / --rows 2 / --min-used 0.6 / --chrome <path> / --help
//
// なぜ要るか（監査 B1・実行込みのやり直し）:
//   `tools/gui_smoke.mjs` は軽い DOM の身代わりなので、**CSS もレイアウトも持たない**。
//   そのため「8 枚が 3 行に溢れて 5 枚がスクロールの外」という壊れ方を**見つけられなかった**。
//   ここでは本物の Chrome で描いて確かめる。
//
// 見るもの（各窓の大きさで）:
//   - 比較: 舞台の外に出ているタイルが 0（`outside === 0`）／タイルの幅が**枠**で決まっている
//   - 要求の一覧（`--screen requests`）: 横に溢れない／**入れ子のカードが 0**／**枚数が API と一致**
//   - まとまりレビュー（`--screen group`）: フィルムストリップが溢れない／**決めるボタンで POST が 1 回**
//   - 注記の画面（`--screen asset`。P6-2）: **印が画像の中**／**印の番号が一覧の番号と同じ**／
//     一覧が横に溢れない／**入口がスクロール無しで見える**（監査 §F-1）
//     （POST は押す直前に差し替えた `fetch` が飲むので、**サーバのデータは書かない**）
//
// 前提: サーバが動いていること（GUI と API を同じオリジンで配る）。

import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function argOf(name, fallback = null) {
  const at = process.argv.indexOf(`--${name}`);
  return at >= 0 && process.argv[at + 1] ? process.argv[at + 1] : fallback;
}

const BASE = argOf('base', 'http://127.0.0.1:8791');
let IDS = (argOf('ids', '') || '').split(',').map((s) => s.trim()).filter(Boolean);
const COUNT = Number(argOf('count', '0'));          // --ids を省いたとき、API から何枚選ぶか
const EXPECTED_ROWS = Number(argOf('rows', '0'));   // 0 = 行数は窓次第（合否に使わない）
const MIN_USED = Number(argOf('min-used', '0'));    // 舞台の使われ方の下限（0〜1。0 で見ない）
const VIEWPORTS = [[1400, 900], [1200, 800], [1920, 1080]];
const ONLY = argOf('viewport', null);       // 例: --viewport 1200x800
const SCREEN = argOf('screen', 'compare');  // compare（既定）| requests | group（P6-1b）
const GROUP = argOf('group', null);         // --screen group のまとまり id
const DUMP = process.argv.includes('--dump');
const CHROME = argOf('chrome', 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe');
const PORT = Number(argOf('port', '9334'));

if (process.argv.includes('--help') || process.argv.includes('-h')) {
  console.log(`使い方:
  node tools/gui_layout.mjs --base <url> --ids <id,id,...>       比較（並べる）
  node tools/gui_layout.mjs --base <url> --count 8               比較（id を API から拾う）
  node tools/gui_layout.mjs --base <url> --screen requests       要求の一覧（枚数の整合も見る）
  node tools/gui_layout.mjs --base <url> --screen group --group <id>   まとまりレビュー
  node tools/gui_layout.mjs --base <url> --screen asset --ids <1 枚>   注記とタグの欄（P6-2 / P4-3）
  node tools/gui_layout.mjs --base <url> --screen tags                 語の一覧（P4-3）
  node tools/gui_layout.mjs --base <url> --screen jobs                 ジョブ（P4-3）
node tools/gui_layout.mjs --base <url> --screen recipe --ids <1 枚>  条件の記録（P7-4）
node tools/gui_layout.mjs --base <url> --screen recipes              記録の一覧（P7-4）
オプション:
  --viewport 1200x800   1 つの窓だけ見る
  --rows 2              行数を合否に使う（既定は窓次第で見ない）
  --min-used 0.6        舞台の使われ方（縦）の下限を合否に使う
  --dump                はみ出しの詳細を出す（比較）
  --chrome <path>       Chrome の場所
  --port 9334           CDP のポート`);
  process.exit(0);
}

if (!IDS.length && COUNT > 0) {
  // `--ids` を省いたときは API から拾う（`GET /api/assets?limit=`）。id を調べなくて済む
  try {
    const res = await fetch(`${BASE}/api/assets?limit=${COUNT}`);
    const body = await res.json();
    IDS = (body.items || body.assets || []).map((row) => row.id).slice(0, COUNT);
  } catch (error) {
    console.error(`API から id を取れませんでした（--ids を使ってください）: ${error.message}`);
    process.exit(2);
  }
}
if (!IDS.length && SCREEN === 'compare') {
  console.error('--ids（または --count）が要ります。例: --ids a,b,c,d  /  --count 8');
  process.exit(2);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let seq = 0;

function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  const pending = new Map();
  ws.addEventListener('message', (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, (msg) => (msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)));
    ws.send(JSON.stringify({ id, method, params }));
  });
  return new Promise((resolve) => ws.addEventListener('open', () => resolve({ send, ws })));
}

// ページの中で走る計測（`{ rows, perRow, outside, tile, frame, cap }` を返す）
const MEASURE = `(() => {
  const stage = document.getElementById('cmp-stage');
  if (!stage) return null;
  const box = stage.getBoundingClientRect();
  const tiles = [...stage.querySelectorAll('.cmp-tile')];
  if (!tiles.length) return null;
  const tops = tiles.map((t) => Math.round(t.getBoundingClientRect().top));
  const first = tops[0];
  return {
    tiles: tiles.length,
    rows: new Set(tops).size,
    perRow: tops.filter((t) => t === first).length,
    outside: tiles.filter((t) => t.getBoundingClientRect().bottom > box.bottom + 1
                              || t.getBoundingClientRect().right > box.right + 1).length,
    tile: Math.round(tiles[0].getBoundingClientRect().width),
    frame: Math.round(tiles[0].querySelector('.cmp-frame').getBoundingClientRect().width),
    cap: Math.round(tiles[0].querySelector('.cmp-cap').scrollWidth),
    // 監査 fix2-8: 「溢れていない」だけでは**半分空いた舞台**を ok と言ってしまう。
    // 使われ方（縦の使用率）と、見出しが何文字見えているかも返す
    used: Math.round((Math.max(...tiles.map((t) => t.getBoundingClientRect().bottom))
                      - box.top) / (box.height || 1) * 100) / 100,
    capVisible: (() => {
      const cap = tiles[0].querySelector('.cmp-cap');
      const full = cap.textContent || '';
      const width = cap.getBoundingClientRect().width;
      if (!full.length || !width) return 0;
      const probe = document.createElement('span');
      probe.style.font = getComputedStyle(cap).font;
      probe.style.whiteSpace = 'nowrap';
      probe.style.position = 'absolute';
      probe.style.visibility = 'hidden';
      probe.textContent = full;
      document.body.appendChild(probe);
      const fullWidth = probe.getBoundingClientRect().width;
      probe.remove();
      return Math.round(Math.min(1, width / (fullWidth || 1)) * 100) / 100;
    })(),
  };
})()`;

// 要求のカードのはみ出しと**枚数の整合**を見る（P6-1b。設計 §8.3-1 と監査 B2）
// - 一覧の**外に横へ出ていない**こと（`overflow === 0`）
// - **入れ子のカードが 0**（`.req-card .req-card`。実装者が実機で踏んだバグ。
//   入れ子になると同じ class が二重になり、`querySelectorAll('.req-card')` が 2 倍返る）
const MEASURE_REQUESTS = `(() => {
  const list = document.getElementById('req-list');
  if (!list) return null;
  const cards = [...list.querySelectorAll('.req-card')];
  const box = list.getBoundingClientRect();
  const rights = cards.map((c) => c.getBoundingClientRect().right);
  return {
    cards: cards.length,
    nested: list.querySelectorAll('.req-card .req-card').length,
    overflow: cards.filter((c) => {
      const r = c.getBoundingClientRect();
      return r.right > box.right + 1 || r.left < box.left - 1;
    }).length,
    listWidth: Math.round(box.width),
    maxRight: rights.length ? Math.round(Math.max(...rights)) : 0,
    listRight: Math.round(box.right),
  };
})()`;

// 注記の画面（`#/asset/<id>`。P6-2 の監査 §F-1 / 設計 §8.3-2・3）を見る。
// - **一覧の番号と画像の印の番号が一致**するか（メモが間にあるとずれる。監査 上位 3）
// - **印が画像の矩形の中**に収まっているか
// - 一覧が**右の列からはみ出さない**か（横。20 行でも）
// - 注記の入口が**スクロール無しで見える**か（監査: 来歴の下 2700 px にあった）
const MEASURE_ASSET = `(() => {
  const img = document.querySelector('.preview') || document.querySelector('img.preview');
  const layer = document.querySelector('.anno-layer');
  const marks = layer ? [...layer.querySelectorAll('.anno-mark')] : [];
  const rect = img ? img.getBoundingClientRect() : null;
  const detail = document.getElementById('detail');
  const toDetail = (node) => {
    if (!node || !detail) return null;
    const r = node.getBoundingClientRect();
    return Math.round(r.top - detail.getBoundingClientRect().top);
  };
  const rows = [...document.querySelectorAll('#anno-list .anno-row')];
  const box = document.querySelector('.anno-box');
  const listBox = document.getElementById('anno-list');
  return {
    marks: marks.length,
    // 印の番号（一覧と同じ規則か）
    markNos: marks.map((m) => (m.textContent || '').trim()),
    rowNos: rows.map((r) => {
      const no = r.querySelector('.anno-no');
      return no ? (no.textContent || '').trim() : '';
    }),
    // 印が画像の矩形の中か（1 px の余裕）
    outside: rect ? marks.filter((m) => {
      const r = m.getBoundingClientRect();
      return r.left < rect.left - 1 || r.top < rect.top - 1
          || r.right > rect.right + 1 || r.bottom > rect.bottom + 1;
    }).length : 0,
    // 一覧の横あふれ（scrollWidth が clientWidth を超えない）
    listOverflow: listBox ? Math.max(0, listBox.scrollWidth - listBox.clientWidth) : 0,
    rowsCount: rows.length,
    // 入口が見える位置か（#detail の先頭からの距離と、スクロール無しで見えるか）
    boxTop: toDetail(box),
    boxVisible: (() => {
      if (!box) return false;
      const r = box.getBoundingClientRect();
      return r.top >= 0 && r.top < innerHeight;
    })(),
    detailScrollTop: detail ? Math.round(detail.scrollTop) : 0,
    // ---- P4-3: タグの欄（設計 §8.3 の 1〜3）----
    // 語の行が**右の列から溢れない**か・**行の高さが揃っている**か（2 行 1 組が目で追えるか）
    tagRows: document.querySelectorAll('#tg-panel .tg-row').length,
    tagOverflow: (() => {
      const panel = document.getElementById('tg-panel');
      if (!panel) return 0;
      return Math.max(0, panel.scrollWidth - panel.clientWidth);
    })(),
    // **P4-3 の監査 C-1**: タグ欄の入口が**スクロール無しで見える**か（注記の箱と同じ見方）。
    // 以前は来歴の下 1,635 px で見えなかった（注記は 2,665 → 341 px に直した前例がある）
    tgTop: toDetail(document.getElementById('tg-panel')),
    tgVisible: (() => {
      const panel = document.getElementById('tg-panel');
      if (!panel) return false;
      const r = panel.getBoundingClientRect();
      return r.top >= 0 && r.top < innerHeight;
    })(),
    // **P4-3 の監査（§8.3-3 の作り直し）**: 長い語釈は**折り返すのが正しい**ので、
    // 折り返した行（2 行以上）を除いて「1 行目の語と 2 行目の語釈の組が崩れていない」を見る
    tagHeightSpread: (() => {
      // **折り返しを含む行は除いて比べる**（長い語名・長い語釈は折り返すのが正しい。
      // P4-3 の再確認 C-1 で、語釈の行だけでなく語名の行の折り返しも除くようにした）
      const tooTall = (el) => el && el.getBoundingClientRect().height > 26;
      const hs = [...document.querySelectorAll('#tg-panel .tg-row')]
        .filter((r) => !tooTall(r.querySelector('.en')) && !tooTall(r.querySelector('.ja')))
        .map((r) => Math.round(r.getBoundingClientRect().height));
      if (hs.length < 2) return 0;
      return Math.max(...hs) - Math.min(...hs);
    })(),
    tagWrapped: [...document.querySelectorAll('#tg-panel .tg-row .ja')]
      .filter((ja) => ja.getBoundingClientRect().height > 26).length,
    tagWrappedEn: [...document.querySelectorAll('#tg-panel .tg-row .en')]
      .filter((en) => en.getBoundingClientRect().height > 26).length,
    tagWithGloss: document.querySelectorAll('#tg-panel .tg-row .ja').length,
    tagMarks: document.querySelectorAll('#tg-panel .tg-src').length,
    // **エスケープ**（§8.2-7 を実物で見る。語釈に script タグを入れても要素にならないこと）
    tagScripts: document.querySelectorAll('#tg-panel script').length,
    tagRawScript: (document.getElementById('tg-panel') || {}).innerHTML
      ? String(document.getElementById('tg-panel').innerHTML).includes('<script>alert') : false,
  };
})()`;

// 語の一覧（`#/tags`。P4-3 / 設計 §8.3-4）を見る。
// 条件の記録（`#/asset/<id>/recipe`。P7-4）
const MEASURE_RECIPE = `(() => {
  const panel = document.getElementById('recipe');
  if (!panel) return null;
  const inner = panel.querySelector('.rc-body');
  const body = document.querySelector('.rc-body');
  const badge = panel.querySelector('.rc-badge');
  const txt = (n, sel) => (n && n.querySelector(sel) ? String(n.querySelector(sel).textContent).trim() : '');
  const mark = panel.querySelector('.rc-status');
  return {
    empty: !!(body && String(body.innerHTML).includes('まだ記録していません')),
    badge: badge ? String(badge.textContent).trim() : null,
    rows: panel.querySelectorAll('.rc-attempt').length,
    results: panel.querySelectorAll('.rc-result').length,
    verdictButtons: panel.querySelectorAll('.rc-v').length,
    scripts: panel.querySelectorAll('script').length,
    markTop: mark ? Math.round(mark.getBoundingClientRect().top) : null,
    overflow: Math.max(0, (panel.scrollWidth || 0) - (panel.clientWidth || 0)),
    pageOverflow: Math.max(0, (document.documentElement.scrollWidth || 0) - innerWidth),
  };
})()`;

// 記録の一覧（`#/recipes`。P7-4）
const MEASURE_RECIPES = `(() => {
  const list = document.getElementById('recipes-list');
  if (!list) return null;
  return {
    rows: list.querySelectorAll('.rl-row').length,
    empty: String(list.innerHTML).includes('記録はありません'),
    brief: (document.getElementById('recipes-brief') || {}).textContent || '',
    listOverflow: Math.max(0, (list.scrollWidth || 0) - (list.clientWidth || 0)),
    pageOverflow: Math.max(0, (document.documentElement.scrollWidth || 0) - innerWidth),
  };
})()`;

const MEASURE_TAGS = `(() => {
  const list = document.getElementById('tags-list');
  const rows = [...document.querySelectorAll('#tags-list .tl-row')];
  const detail = document.getElementById('tags-detail');
  const de = document.documentElement;
  return {
    rows: rows.length,
    listOverflow: list ? Math.max(0, list.scrollWidth - list.clientWidth) : 0,
    pageOverflow: Math.max(0, de.scrollWidth - de.clientWidth),
    detailVisible: detail ? !!(detail.textContent || '').trim() : false,
    brief: (document.getElementById('tags-brief') || {}).textContent || '',
  };
})()`;

// ジョブ（`#/jobs`。P4-3 / 設計 §8.3-4）を見る。
const MEASURE_JOBS = `(() => {
  const list = document.getElementById('jobs-list');
  const rows = [...document.querySelectorAll('#jobs-list .jb-row')];
  const tops = rows.map((r) => Math.round(r.getBoundingClientRect().right));
  return {
    rows: rows.length,
    empty: !!document.querySelector('#jobs-list .note'),
    listOverflow: list ? Math.max(0, list.scrollWidth - list.clientWidth) : 0,
    wideTop: tops.length ? Math.max(...tops) : 0,
    brief: (document.getElementById('jobs-brief') || {}).textContent || '',
  };
})()`;

// まとまりレビュー（`#/group/<id>`。P6-1b / 設計 §5.1b）を見る。
// フィルムストリップが横に溢れないこと・見出し・**決めるボタンの配線**。
// 決めるボタンは**押す前に `fetch` を差し替えて POST を止める**（データを書かない。
// 数えるのは「押したら POST が 1 回だけ飛ぶか」＝実装者が踏んだ「名前隠し」の検査）
const MEASURE_GROUP = `(() => {
  const strip = document.getElementById('group-strip');
  const frames = strip ? [...strip.querySelectorAll('.grp-frame')] : [];
  const box = strip ? strip.getBoundingClientRect() : null;
  return {
    frames: frames.length,
    overflow: box ? frames.filter((f) => {
      const r = f.getBoundingClientRect();
      return r.right > box.right + 1 || r.left < box.left - 1;
    }).length : 0,
    brief: (document.getElementById('group-brief') || {}).textContent || '',
    note: (document.getElementById('group-note') || {}).textContent || '',
    decideDisabled: !!(document.getElementById('group-decide') || {}).disabled,
    prov: (document.querySelector('.grp-prov') || {}).textContent || '',
  };
})()`;

// 決めるボタンを押して、POST が**1 回だけ**飛ぶことを見る（監査 B2）。
// POST は差し替えた `fetch` が飲む（サーバのデータを書かない）
const PRESS_DECIDE = `(async () => {
  const real = window.fetch;
  window.__posts = [];
  window.fetch = (url, opt = {}) => {
    const method = (opt.method || 'GET').toUpperCase();
    if (method !== 'POST') return real(url, opt);
    window.__posts.push({ url: String(url), body: opt.body || null });
    return Promise.resolve(new Response(JSON.stringify({
      items: [], group: { selected_asset_ids: [] }, closed_request_ids: [],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
  };
  const sel = document.getElementById('group-reason');
  const opt = sel ? [...sel.options].find((o) => o.value) : null;
  if (sel && opt) { sel.value = opt.value; sel.dispatchEvent(new Event('change')); }
  const btn = document.getElementById('group-decide');
  if (!btn) return { pressed: false, reason: 'no button' };
  if (btn.disabled) return { pressed: false, reason: 'disabled' };
  btn.click();
  await new Promise((r) => setTimeout(r, 400));
  window.fetch = real;
  return { pressed: true, posts: window.__posts };
})()`;

// どこがはみ出しているかを見るための詳細（`--dump`）
const DUMP_EXPR = `(() => {
  const stage = document.getElementById('cmp-stage');
  const box = stage.getBoundingClientRect();
  return {
    stage: { top: Math.round(box.top), bottom: Math.round(box.bottom), right: Math.round(box.right),
             h: Math.round(box.height), clientH: stage.clientHeight, scrollH: stage.scrollHeight },
    tiles: [...stage.querySelectorAll('.cmp-tile')].map((t) => {
      const r = t.getBoundingClientRect();
      return { no: (t.querySelector('.no') || {}).textContent, top: Math.round(r.top),
               bottom: Math.round(r.bottom), right: Math.round(r.right),
               w: Math.round(r.width), h: Math.round(r.height) };
    }),
  };
})()`;

const profile = mkdtempSync(join(tmpdir(), 'gui-layout-'));
const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--disable-gpu', '--hide-scrollbars',
  'about:blank',
], { stdio: 'ignore' });

let failures = 0;
try {
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}/json/version`); if (r.ok) break; } catch {}
    await sleep(250);
  }
  const target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  const { send, ws } = await connect(target.webSocketDebuggerUrl);
  await send('Page.enable');
  await send('Runtime.enable');

  const evaluate = async (expression) => {
    const res = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true, timeout: 30000 });
    if (res.exceptionDetails) throw new Error(res.exceptionDetails.exception?.description || 'evaluate failed');
    return res.result.value;
  };
  const measureNow = async () => {
    let got = null;
    for (let i = 0; i < 60; i++) {
      got = await evaluate(MEASURE);
      if (got) break;
      await sleep(250);
    }
    if (got) { await sleep(300); got = await evaluate(MEASURE); }   // 描画が落ち着くのを待つ
    return got;
  };

  // 要求の一覧（P6-1b）: カードが横に溢れないか＋**枚数が API と合うか**（設計 §8.3-1 / 監査 B2）
  if (SCREEN === 'requests') {
    const url = `${BASE}/#/requests`;
    // 期待値は API から引く（入れ子のバグは「DOM の枚数が 2 倍」として出る）
    let expected = null;
    try {
      const res = await fetch(`${BASE}/api/review-requests?state=open&limit=50`);
      const body = await res.json();
      expected = (body.items || []).length;
    } catch (error) {
      console.log(`注意: API から件数を取れませんでした（枚数の整合は見ない）: ${error.message}`);
    }
    if (expected === 0) {
      console.log('注意: open な要求が 0 件です（先に要求を作ってください。例: POST /api/review-requests）');
    }
    for (const [width, height] of VIEWPORTS) {
      if (ONLY && ONLY !== `${width}x${height}`) continue;
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      await send('Page.navigate', { url });
      let got = null;
      for (let i = 0; i < 60; i++) {
        got = await evaluate(MEASURE_REQUESTS);
        const ready = got && (got.cards > 0 || expected === 0);
        if (ready) break;
        await sleep(250);
      }
      if (got) { await sleep(300); got = await evaluate(MEASURE_REQUESTS); }
      if (!got) {
        failures++;
        console.log(`NG   ${width}x${height} 要求: カードを計測できません`);
        continue;
      }
      const bad = [];
      if (got.overflow !== 0) bad.push('overflow=0');
      if (got.maxRight > got.listRight + 1) bad.push('maxRight<=list.right');
      if (got.nested !== 0) bad.push('入れ子 0');                      // 監査 B2（1）
      if (expected !== null && got.cards !== expected) bad.push(`cards=${expected}`);
      if (bad.length) failures++;
      console.log(`${bad.length ? 'NG  ' : 'ok  '}${width}x${height} 要求: `
        + `cards=${got.cards}${expected === null ? '' : `/${expected}`} nested=${got.nested} `
        + `overflow=${got.overflow} list=${got.listWidth} maxRight=${got.maxRight} listRight=${got.listRight}`
        + (bad.length ? `  ← ${bad.join(', ')}` : ''));
    }
    ws.close();
    console.log(failures ? `${failures} 件 NG` : 'すべて ok');
    process.exit(failures ? 1 : 0);
  }

  // 注記の画面（P6-2 の監査 §F-1 / 設計 §8.3-2・3）。`--screen asset --ids <1 枚>`
  if (SCREEN === 'asset') {
    if (IDS.length !== 1) {
      console.error('--screen asset には --ids <1 枚> が要ります（例: --ids 01M4…）');
      process.exit(2);
    }
    const url = `${BASE}/#/asset/${encodeURIComponent(IDS[0])}`;
    for (const [width, height] of VIEWPORTS) {
      if (ONLY && ONLY !== `${width}x${height}`) continue;
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      await send('Page.navigate', { url });
      let got = null;
      for (let i = 0; i < 60; i++) {
        got = await evaluate(MEASURE_ASSET);
        if (got && (got.marks > 0 || got.rowsCount >= 0) && got.boxTop !== null) break;
        await sleep(250);
      }
      if (got) { await sleep(300); got = await evaluate(MEASURE_ASSET); }
      if (!got) {
        failures++;
        console.log(`NG   ${width}x${height} 注記: 計測できません`);
        continue;
      }
      const bad = [];
      if (got.outside !== 0) bad.push('印が画像の中');
      if (got.listOverflow !== 0) bad.push('一覧が横に溢れない');
      // 印の番号は「一覧の全件番号」から取る（メモは印を持たないので、**部分列**になる。
      // 別々に数えるとここがずれる＝P6-2 の監査 上位 3）
      const expected = got.rowNos.filter((no) => got.markNos.includes(no));
      if (got.markNos.join(',') !== expected.join(',')) {
        bad.push(`印の番号=一覧の番号（印=[${got.markNos.join(',')}] 期待=[${expected.join(',')}]）`);
      }
      if (!got.boxVisible) bad.push('入口が見える');
      // **P4-3 の監査 C-1**: タグ欄もスクロール無しで見えること（注記の箱と同じ見方）
      if (!got.tgVisible) bad.push(`タグ欄が見える（tgTop=${got.tgTop}px）`);
      // P4-3: タグの欄（設計 §8.3 の 1〜3）
      if (got.tagOverflow !== 0) bad.push('タグ欄が横に溢れない');
      // **折り返した語釈は正しい**ので、折り返しを含む行を除いて比べる（監査 §8.3-3 の作り直し）
      if (got.tagRows > 1 && got.tagHeightSpread > 2) {
        bad.push(`行の高さが揃う（差 ${got.tagHeightSpread}px）`);
      }
      if (got.tagScripts !== 0 || got.tagRawScript) bad.push('語釈の `<script>` を実行しない（§8.2-7）');
      if (bad.length) failures++;
      console.log(`${bad.length ? 'NG  ' : 'ok  '}${width}x${height} 注記: `
        + `marks=${got.marks} rows=${got.rowsCount} outside=${got.outside} `
        + `listOverflow=${got.listOverflow} boxTop=${got.boxTop}px visible=${got.boxVisible}`
        + ` tgTop=${got.tgTop}px tgVisible=${got.tgVisible}`
        + ` markNos=[${got.markNos.join(',')}] rowNos=[${got.rowNos.join(',')}]`
        + ` タグ: rows=${got.tagRows} overflow=${got.tagOverflow} 高さの差=${got.tagHeightSpread}px`
        + ` 折り返し=${got.tagWrapped}/語名=${got.tagWrappedEn} 印=${got.tagMarks} 語釈=${got.tagWithGloss} script=${got.tagScripts}`
        + (bad.length ? `  ← ${bad.join(', ')}` : ''));
    }
    ws.close();
    console.log(failures ? `${failures} 件 NG` : 'すべて ok');
    process.exit(failures ? 1 : 0);
  }

  // 語の一覧（`#/tags`。P4-3 / 設計 §8.3-4）。3 窓で横に溢れない・行が出ている
  if (SCREEN === 'tags') {
    const url = `${BASE}/#/tags`;
    for (const [width, height] of VIEWPORTS) {
      if (ONLY && ONLY !== `${width}x${height}`) continue;
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      await send('Page.navigate', { url });
      let got = null;
      for (let i = 0; i < 40; i++) {
        got = await evaluate(MEASURE_TAGS);
        if (got && got.rows > 0) break;
        await sleep(250);
      }
      if (got) { await sleep(300); got = await evaluate(MEASURE_TAGS); }
      if (!got) {
        failures++;
        console.log(`NG   ${width}x${height} タグ: 計測できません`);
        continue;
      }
      const bad = [];
      if (got.rows <= 0) bad.push('語の行が出る');
      if (got.listOverflow !== 0) bad.push('一覧が横に溢れない');
      if (got.pageOverflow !== 0) bad.push('画面が横に溢れない');
      if (bad.length) failures++;
      console.log(`${bad.length ? 'NG  ' : 'ok  '}${width}x${height} タグ: `
        + `rows=${got.rows} listOverflow=${got.listOverflow} pageOverflow=${got.pageOverflow}`
        + ` detail=${got.detailVisible} brief=${JSON.stringify(got.brief)}`
        + (bad.length ? `  ← ${bad.join(', ')}` : ''));
    }
    ws.close();
    console.log(failures ? `${failures} 件 NG` : 'すべて ok');
    process.exit(failures ? 1 : 0);
  }

  // ジョブ（`#/jobs`。P4-3 / 設計 §8.3-4）。進行の行が**折り返しても崩れない**か
  if (SCREEN === 'jobs') {
    const url = `${BASE}/#/jobs`;
    for (const [width, height] of VIEWPORTS) {
      if (ONLY && ONLY !== `${width}x${height}`) continue;
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      await send('Page.navigate', { url });
      let got = null;
      for (let i = 0; i < 40; i++) {
        got = await evaluate(MEASURE_JOBS);
        if (got && (got.rows > 0 || got.empty)) break;
        await sleep(250);
      }
      if (got) { await sleep(300); got = await evaluate(MEASURE_JOBS); }
      if (!got) {
        failures++;
        console.log(`NG   ${width}x${height} ジョブ: 計測できません`);
        continue;
      }
      const bad = [];
      if (got.rows <= 0 && !got.empty) bad.push('ジョブの行か空の文が出る');
      if (got.listOverflow !== 0) bad.push('一覧が横に溢れない');
      if (got.wideTop > width) bad.push(`行が画面の幅を超えない（${got.wideTop}px）`);
      if (bad.length) failures++;
      console.log(`${bad.length ? 'NG  ' : 'ok  '}${width}x${height} ジョブ: `
        + `rows=${got.rows} empty=${got.empty} listOverflow=${got.listOverflow}`
        + ` wideTop=${got.wideTop} brief=${JSON.stringify(got.brief)}`
        + (bad.length ? `  ← ${bad.join(', ')}` : ''));
    }
    ws.close();
    console.log(failures ? `${failures} 件 NG` : 'すべて ok');
    process.exit(failures ? 1 : 0);
  }

  // 条件の記録（`#/asset/<id>/recipe`。P7-4 / 設計 §5.1〜§5.3）。判定の印が出るか・はみ出さないか
  if (SCREEN === 'recipe') {
    if (!IDS.length) {
      console.error('--screen recipe には --ids <1 枚> が要ります');
      process.exit(2);
    }
    const url = `${BASE}/#/asset/${encodeURIComponent(IDS[0])}/recipe`;
    for (const [width, height] of VIEWPORTS) {
      if (ONLY && ONLY !== `${width}x${height}`) continue;
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      await send('Page.navigate', { url });
      let got = null;
      for (let i = 0; i < 40; i++) {
        got = await evaluate(MEASURE_RECIPE);
        if (got && (got.badge || got.empty)) break;
        await sleep(250);
      }
      if (got) { await sleep(300); got = await evaluate(MEASURE_RECIPE); }
      if (!got) {
        failures++;
        console.log(`NG   ${width}x${height} 条件: 計測できません`);
        continue;
      }
      const bad = [];
      if (!got.badge && !got.empty) bad.push('判定の印か「まだ記録していません」が出る');
      if (got.overflow !== 0) bad.push('中身が横に溢れない');
      if (got.pageOverflow !== 0) bad.push('画面が横に溢れない');
      if (got.scripts !== 0) bad.push(`script 要素を作らない（${got.scripts}）`);
      if (got.badge && got.verdictButtons < 4 && got.results > 0) bad.push('合否のボタンが 4 つ');
      if (bad.length) failures++;
      console.log(`${bad.length ? 'NG  ' : 'ok  '}${width}x${height} 条件: `
        + `badge=${JSON.stringify(got.badge)} rows=${got.rows} results=${got.results}`
        + ` verdicts=${got.verdictButtons} overflow=${got.overflow} pageOverflow=${got.pageOverflow}`
        + ` scripts=${got.scripts} markTop=${got.markTop}`
        + (bad.length ? `  ← ${bad.join(', ')}` : ''));
    }
    ws.close();
    console.log(failures ? `${failures} 件 NG` : 'すべて ok');
    process.exit(failures ? 1 : 0);
  }

  // 記録の一覧（`#/recipes`。P7-4 / 設計 §5.4）。行が出るか・はみ出さないか
  if (SCREEN === 'recipes') {
    const url = `${BASE}/#/recipes`;
    for (const [width, height] of VIEWPORTS) {
      if (ONLY && ONLY !== `${width}x${height}`) continue;
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      await send('Page.navigate', { url });
      let got = null;
      for (let i = 0; i < 40; i++) {
        got = await evaluate(MEASURE_RECIPES);
        if (got && (got.rows > 0 || got.empty)) break;
        await sleep(250);
      }
      if (got) { await sleep(300); got = await evaluate(MEASURE_RECIPES); }
      if (!got) {
        failures++;
        console.log(`NG   ${width}x${height} 記録: 計測できません`);
        continue;
      }
      const bad = [];
      if (got.rows <= 0 && !got.empty) bad.push('行か空の文が出る');
      if (got.listOverflow !== 0) bad.push('一覧が横に溢れない');
      if (got.pageOverflow !== 0) bad.push('画面が横に溢れない');
      if (bad.length) failures++;
      console.log(`${bad.length ? 'NG  ' : 'ok  '}${width}x${height} 記録: `
        + `rows=${got.rows} empty=${got.empty} listOverflow=${got.listOverflow}`
        + ` pageOverflow=${got.pageOverflow} brief=${JSON.stringify(got.brief)}`
        + (bad.length ? `  ← ${bad.join(', ')}` : ''));
    }
    ws.close();
    console.log(failures ? `${failures} 件 NG` : 'すべて ok');
    process.exit(failures ? 1 : 0);
  }

  // まとまりレビュー（P6-1b / 設計 §5.1b）。`--screen group --group <id>`
  if (SCREEN === 'group') {
    if (!GROUP) {
      console.error('--screen group には --group <id> が要ります');
      process.exit(2);
    }
    const url = `${BASE}/#/group/${encodeURIComponent(GROUP)}`;
    for (const [width, height] of VIEWPORTS) {
      if (ONLY && ONLY !== `${width}x${height}`) continue;
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      await send('Page.navigate', { url });
      let got = null;
      for (let i = 0; i < 60; i++) {
        got = await evaluate(MEASURE_GROUP);
        if (got && got.frames > 0) break;
        await sleep(250);
      }
      if (got) { await sleep(300); got = await evaluate(MEASURE_GROUP); }
      if (!got) {
        failures++;
        console.log(`NG   ${width}x${height} まとまり: 計測できません`);
        continue;
      }
      // **決めるボタンを押す**（POST は差し替えた `fetch` が飲む。監査 B2（2））。
      // ただし「ボツのみ」のまとまりでは**無効が正しい**（監査 C6）ので、押さずに無効を見る
      const onlyReject = got.brief.includes('ボツのみ');
      const pressed = onlyReject ? null : await evaluate(PRESS_DECIDE);
      const posts = (pressed && pressed.posts) || [];
      const bad = [];
      if (got.overflow !== 0) bad.push('overflow=0');
      if (got.frames === 0) bad.push('フィルムストリップ');
      if (onlyReject) {
        if (!got.decideDisabled) bad.push('ボツのみなのに決めるボタンが有効');
      } else if (!pressed || !pressed.pressed) {
        bad.push(`押せない(${(pressed || {}).reason})`);
      } else if (posts.length !== 1) bad.push(`POST=${posts.length}`);
      else if (!String(posts[0].url).endsWith('/decide')) bad.push('POST の宛先');
      if (bad.length) failures++;
      console.log(`${bad.length ? 'NG  ' : 'ok  '}${width}x${height} まとまり: `
        + `frames=${got.frames} overflow=${got.overflow} `
        + `decide=${got.decideDisabled ? (onlyReject ? '無効（ボツのみ。正しい）' : '無効') : '有効'} `
        + `POST=${posts.length} brief="${got.brief}"`
        + (got.prov ? ` 来歴="${got.prov}"` : '')
        + (bad.length ? `  ← ${bad.join(', ')}` : ''));
    }
    ws.close();
    console.log(failures ? `${failures} 件 NG` : 'すべて ok');
    process.exit(failures ? 1 : 0);
  }

  const url = `${BASE}/#/compare?ids=${IDS.map(encodeURIComponent).join(',')}`;
  for (const [width, height] of VIEWPORTS) {
    if (ONLY && ONLY !== `${width}x${height}`) continue;
    await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
    await send('Page.navigate', { url });
    const afterLoad = await measureNow();
    if (DUMP) console.log(JSON.stringify(await evaluate(DUMP_EXPR), null, 1));
    await evaluate('window.dispatchEvent(new Event("resize")); true');
    await sleep(400);
    const afterResize = await evaluate(MEASURE);

    // `r` を 1 回押して seed 順にし、並び替えで崩れないかを見る（監査 B1 が拾った条件）
    await evaluate('document.getElementById("cmp-order").click(); true');
    await sleep(600);
    const afterOrder = await evaluate(MEASURE);

    for (const [label, got] of [['初回', afterLoad], ['resize 後', afterResize], ['seed 順', afterOrder]]) {
      if (!got) {
        failures++; console.log(`NG   ${width}x${height} ${label}: 計測できません`);
        continue;
      }
      // 守るのは「**舞台の外に出ていない**」ことと「**タイルの幅が枠で決まっている**」こと。
      // 行数は窓の大きさと絵の縦横比で決まる（`--rows` を渡したときだけ合否に使う）。
      // `comparison.md` §2.1 の表は「1 画面に収める」の意味で、**枚数ごとの行数を強制しない**。
      // `--min-used` を渡すと、舞台の使われ方（縦）の下限も見る（半分空いた状態を検出する用）。
      const checks = [
        ['outside=0', got.outside === 0],
        ['tile=frame', got.tile === got.frame],
      ];
      if (EXPECTED_ROWS > 0) checks.push([`rows=${EXPECTED_ROWS}`, got.rows === EXPECTED_ROWS]);
      if (MIN_USED > 0) checks.push([`used>=${MIN_USED}`, got.used >= MIN_USED]);
      const bad = checks.filter(([, ok]) => !ok).map(([name]) => name);
      if (bad.length) failures++;
      console.log(`${bad.length ? 'NG  ' : 'ok  '}${width}x${height} ${label}: `
        + `rows=${got.rows} perRow=${got.perRow} outside=${got.outside} `
        + `tile=${got.tile} frame=${got.frame} cap=${got.cap} used=${got.used} `
        + `見出し可視=${Math.round(got.capVisible * 100)}%`
        + (bad.length ? `  ← ${bad.join(', ')}` : ''));
    }
    if (afterLoad && afterLoad.tile !== afterLoad.frame) {
      console.log(`     ヒント: タイルの幅（${afterLoad.tile}）が見出し（${afterLoad.cap}）で決まっています`
        + '（`renderStage()` が `tile.style.width` を付けているか）');
    }
  }
  ws.close();
} finally {
  chrome.kill();
  // 監査 fix2-8: `chrome.kill()` の直後は子プロセスがまだ掴んでいるので消せない
  // （毎回 18MB が %TEMP% に残っていた）。少し待ってから、数回試す
  for (let i = 0; i < 10; i++) {
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* まだ掴まれている */ }
    await sleep(300);
    try {
      const { existsSync } = await import('node:fs');
      if (!existsSync(profile)) break;
    } catch { /* 確認できなければ続ける */ }
  }
}

console.log(failures ? `${failures} 件 NG` : 'すべて ok');
process.exit(failures ? 1 : 0);
