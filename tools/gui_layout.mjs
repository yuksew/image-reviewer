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
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen duplicates       # 重複の整理（P8-3）
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending          # 最近の削除（P8-3）
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen pending --ids a,b  # 削除の確認つき
//   node tools/gui_layout.mjs --base http://127.0.0.1:8791 --screen library          # 下部バーの削除の入口（P8-3）
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
//     一覧が横に溢れない／**入口がスクロール無しで見える**（監査 §F-1）／
//     **（P8-3 の監査 C-1）削除の入口が画像のすぐ下に見え、押すと `#/pending-deletes?ids=` へ行く**
//     （POST は押す直前に差し替えた `fetch` が飲むので、**サーバのデータは書かない**）
//   - ライブラリ（`--screen library`。P8-3 の監査 C-1）: 下部バーの「選んだ N 枚を削除へ回す」が
//     **スクロール無しで見える**／1 枚も選んでいなければ押せない／2 枚選ぶと押せて
//     `#/pending-deletes?ids=` へ行く
//   - 重複の整理（`--screen duplicates`。P8-3）: 横に溢れない／**群と枚が出る**／
//     **入口（まとまりにする）がスクロール無しで見える**／**既定で 1 枚も選ばない**／
//     **押すと POST が 1 回だけ**。**前提の行（理由が `<script>` の除外）が無くても NG にしない**
//     （監査 D-6。空の 1 行を見る）
//   - 最近の削除（`--screen pending`。P8-3）: 横に溢れない／**残り時間と段の印が出る**／
//     **上部バーの入口が見える**（保留があるとき。**0 件なら出ないのが正**＝監査 D-6）／
//     **押すと POST が 1 回だけ**
//     （`--ids a,b` を渡すと削除の確認も押す。POST は差し替えた `fetch` が飲む）
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
const SCREEN = argOf('screen', 'compare');  // compare | requests | tags | jobs
                                            // | duplicates / pending / library（P8-3）| group（P6-1b）
const GROUP = argOf('group', null);         // --screen group のまとまり id

// **まとまりの id が空だと Chrome を開く前に落ちる**（実際に踏んだ: Node が
// `Assertion failed: !(handle->flags & UV_HANDLE_CLOSING)` で落ちて、原因が分からなかった）。
// **人が読める形で止める**（複製にまとまりが無いときはこれが出る）
if (SCREEN === 'group' && (!GROUP || GROUP === 'true')) {
  console.error('--screen group には --group <まとまりの id> が要ります'
    + '（複製にまとまりが無いときは `/api/groups` が空です。まとまりのある複製を使ってください）');
  process.exit(2);
}
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
  node tools/gui_layout.mjs --base <url> --screen duplicates           重複の整理（P8-3）
  node tools/gui_layout.mjs --base <url> --screen pending              最近の削除（P8-3）
  node tools/gui_layout.mjs --base <url> --screen pending --ids a,b    最近の削除（削除の確認つき）
  node tools/gui_layout.mjs --base <url> --screen library              下部バーの削除の入口（P8-3）
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
    // **P8-3 の監査 C-1**: **削除の入口**（#del-entry）が**画像のすぐ下**に在り、
    // **スクロール無しで見える**か（tgTop と同じ形。P7 の rcTop と同じ考え方）。
    // 設計: p8-design.md §5 の「入口」行・frontend-design.md §11
    delTop: toDetail(document.getElementById('del-entry')),
    delVisible: (() => {
      const box = document.getElementById('del-entry');
      if (!box) return false;
      const r = box.getBoundingClientRect();
      return r.top >= 0 && r.top < innerHeight && r.height > 0;
    })(),
    delText: ((document.getElementById('del-one') || {}).textContent || '').trim(),
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

// 重複の整理（`#/duplicates`。P8-3）。群・枚・横のはみ出し・**入口が見えるか**を見る
const MEASURE_DUP = `(() => {
  const list = document.getElementById('dup-list');
  const groups = [...document.querySelectorAll('#dup-list .dup-group')];
  const items = [...document.querySelectorAll('#dup-list .dup-item')];
  const de = document.documentElement;
  const head = groups.length ? groups[0].querySelector('.dup-ghead') : null;
  const box = list ? list.getBoundingClientRect() : null;
  const right = box ? box.right + 1 : 0;
  return {
    groups: groups.length,
    items: items.length,
    marks: document.querySelectorAll('#dup-list .dup-mark').length,
    scripts: document.querySelectorAll('#dup-list script').length,
    exclusions: document.querySelectorAll('#dup-list .dup-ex-row').length,
    exReason: (document.querySelector('#dup-list .dup-ex-reason') || {}).textContent || '',
    exEmpty: (document.querySelector('#dup-list .dup-exclusions .note') || {}).textContent || '',
    checked: document.querySelectorAll('#dup-list .dup-on-box:checked').length,
    allText: ((document.querySelector('#dup-bar .dup-all') || {}).textContent || '').trim(),
    bodyClass: document.body.className,
    thumbs: [...document.querySelectorAll('#dup-list .dup-item img')]
      .filter((im) => im.naturalWidth > 0).length,
    exact: !!document.querySelector('#dup-list .dup-exact'),
    exactText: (document.querySelector('#dup-list .dup-exact') || {}).textContent || '',
    compute: !!document.querySelector('#dup-list .dup-compute'),
    thresholds: document.querySelectorAll('#dup-thresholds .dup-th').length,
    chosen: (document.querySelector('#dup-thresholds .dup-th.on') || {}).textContent || '',
    brief: (document.getElementById('dup-brief') || {}).textContent || '',
    listOverflow: list ? Math.max(0, list.scrollWidth - list.clientWidth) : 0,
    pageOverflow: Math.max(0, de.scrollWidth - de.clientWidth),
    wide: items.filter((it) => it.getBoundingClientRect().right > right).length,
    entryVisible: (() => {
      if (!head) return false;
      const r = head.getBoundingClientRect();
      return r.top >= 0 && r.top < innerHeight;
    })(),
  };
})()`;

// 重複の整理で**押す**（POST は差し替えた `fetch` が飲む。サーバのデータは書かない）。
// 「まとまりにする」と「別物として確定」（2 枚だけ残す）を押して、POST の回数と本文を見る
const PRESS_DUP = `(async () => {
  const real = window.fetch;
  const json = (body) => new Response(JSON.stringify(body),
    { status: 200, headers: { 'Content-Type': 'application/json' } });
  window.__posts = [];
  window.fetch = (url, opt = {}) => {
    const method = (opt.method || 'GET').toUpperCase();
    if (method !== 'POST') return real(url, opt);
    window.__posts.push({ url: String(url), body: opt.body || null });
    return Promise.resolve(json({ id: 'gui-made-group', kind: 'duplicates',
                                  a_id: 'a', b_id: 'b', excluded: true }));
  };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const out = { pressedMake: false, pressedExclude: false, error: null };
  try {
    // **（P8-3 の監査の注意）既定では 1 枚も選ばれていない。** 押すには**人が選ぶ**必要が
    // あるので、ここでも選んでから押す（選ばずに押せるなら、それ自体が危ない）。
    // **1 枚選ぶたびに一覧が描き直される**ので、**毎回クエリし直す**（掴んだままだと
    // 文書から外れ、change が委譲の聞き手まで上がらない）
    const boxesAt = () => [...document.querySelectorAll('#dup-list .dup-item .dup-on-box')];
    for (let i = 0; i < 2; i++) {
      const box = boxesAt()[i];
      if (box && !box.checked) {
        box.checked = true;
        box.dispatchEvent(new Event('change', { bubbles: true }));
        await wait(150);
      }
    }
    for (const box of boxesAt().slice(2)) {
      if (box.checked) {
        box.checked = false;
        box.dispatchEvent(new Event('change', { bubbles: true }));
        await wait(80);
      }
    }
    await wait(200);
    // **押す直前に取り直す**: 描き直し（render）が一覧を作り直すので、先に掴んだ要素は
    // **文書から外れて**委譲の聞き手（#dup-list）まで上がらない（押しても何も起きない）。
    // **（実測: ここで「まとまりにする」の POST が 0 回になった）**
    const make = document.querySelector('#dup-list .dup-group .dup-make');
    if (make && !make.disabled) { make.click(); out.pressedMake = true; await wait(400); }
    const ex = document.querySelector('#dup-list .dup-group .dup-exclude');
    if (ex && !ex.disabled) { ex.click(); out.pressedExclude = true; await wait(500); }
  } catch (error) { out.error = String(error); }
  window.fetch = real;
  out.posts = window.__posts;
  return out;
})()`;

// **除外の一覧を開いて、その場で測る**（理由の script タグが要素にならないこと。§8.2-7）。
// 描き直しと競合しないよう、**押すのと測るのを同じ評価の中で**行う
const OPEN_EXCLUSIONS = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  for (let i = 0; i < 10; i++) {
    if (document.querySelectorAll('#dup-list .dup-ex-row').length > 0) break;
    const btn = document.querySelector('#dup-bar .dup-show-ex');
    if (btn && !document.querySelector('#dup-list .dup-exclusions')) btn.click();
    await wait(400);
  }
  return {
    rows: document.querySelectorAll('#dup-list .dup-ex-row').length,
    scripts: document.querySelectorAll('#dup-list script').length,
    reason: (document.querySelector('#dup-list .dup-ex-reason') || {}).textContent || '',
    empty: (document.querySelector('#dup-list .dup-exclusions .note') || {}).textContent || '',
  };
})()`;

// **（P8-3 の監査 C-1）拡大の削除の入口を押す**。`#/pending-deletes?ids=<この 1 枚>` へ行き、
// 削除の確認（段の選択）が出ることを見る。**押さないテストは穴を隠す**（P7-4 の教訓）。
// POST はしない（画面が移るだけ。渡す先は GET だけを読む）
const PRESS_ASSET_DELETE = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const out = { pressed: false, hash: '', confirmShown: false };
  const btn = document.getElementById('del-one');
  if (btn) { btn.click(); out.pressed = true; await wait(600); }
  out.hash = location.hash;
  const confirm = document.getElementById('pd-confirm');
  out.confirmShown = !!confirm && /削除の確認/.test(confirm.textContent || '')
    && document.querySelectorAll('#pd-confirm .pd-stage').length === 3;
  return out;
})()`;

// ライブラリ（`#/`）の下部バー。**削除の入口**（監査 C-1）が**スクロール無しで見える**か
const MEASURE_LIBRARY = `(() => {
  const btn = document.getElementById('btn-delete');
  const bar = document.querySelector('.bottombar');
  const frames = document.querySelectorAll('#rows .frame');
  const de = document.documentElement;
  return {
    frames: frames.length,
    barVisible: (() => {
      if (!bar) return false;
      const r = bar.getBoundingClientRect();
      return r.height > 0 && r.top >= 0 && r.top < innerHeight;
    })(),
    text: btn ? (btn.textContent || '').trim() : '',
    disabled: btn ? btn.disabled === true : null,
    buttonVisible: (() => {
      if (!btn) return false;
      const r = btn.getBoundingClientRect();
      return !btn.hidden && r.width > 0 && r.height > 0 && r.top >= 0 && r.top < innerHeight;
    })(),
    picked: document.querySelectorAll('#rows .frame.picked').length,
    pageOverflow: Math.max(0, de.scrollWidth - de.clientWidth),
  };
})()`;

// 2 枚を Ctrl + クリックで選んでから下部バーの入口を押す（**1 枚も選んでいなければ押せない**）
const PRESS_LIBRARY = `(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const out = { picked: 0, text: '', disabled: null, pressed: false, hash: '' };
  const btn = document.getElementById('btn-delete');
  out.beforeText = btn ? (btn.textContent || '').trim() : '';
  out.beforeDisabled = btn ? btn.disabled === true : null;
  for (const frame of [...document.querySelectorAll('#rows .frame')].slice(0, 2)) {
    frame.dispatchEvent(new MouseEvent('click', { ctrlKey: true, bubbles: true }));
    await wait(200);
  }
  out.picked = document.querySelectorAll('#rows .frame.picked').length;
  const now = document.getElementById('btn-delete');
  out.text = now ? (now.textContent || '').trim() : '';
  out.disabled = now ? now.disabled === true : null;
  if (now && !now.disabled) { now.click(); out.pressed = true; await wait(500); }
  out.hash = location.hash;
  return out;
})()`;

// 最近の削除（`#/pending-deletes`。P8-3）。行・残り時間・段の印・拾い物・ゴミ箱・横のはみ出し
const MEASURE_PENDING = `(() => {
  const rows = [...document.querySelectorAll('#pd-running .pd-row')];
  const found = [...document.querySelectorAll('#pd-found .pd-found-row')];
  const trash = [...document.querySelectorAll('#pd-trash .pd-row')];
  const confirm = document.getElementById('pd-confirm');
  const items = [...document.querySelectorAll('#pd-confirm .pd-item')];
  const body = document.querySelector('#pending .pd-body');
  const de = document.documentElement;
  const first = rows[0] || null;
  return {
    rows: rows.length,
    found: found.length,
    trash: trash.length,
    remain: (document.querySelector('#pd-running .pd-remain') || {}).textContent || '',
    remains: [...document.querySelectorAll('#pd-running .pd-remain')].map((m) => m.textContent || ''),
    strip: (document.querySelector('#pd-running .pd-strip') || {}).textContent || '',
    actors: [...document.querySelectorAll('#pd-running .pd-meta')].map((m) => m.textContent || ''),
    brief: (document.getElementById('pd-brief') || {}).textContent || '',
    empty: !!document.querySelector('#pd-running .note'),
    scripts: document.querySelectorAll('#pending script').length,
    bodyClass: document.body.className,
    confirmText: (confirm || {}).textContent || '',
    confirmVisible: (() => {
      if (!confirm || !(confirm.textContent || '').trim()) return false;
      const r = confirm.getBoundingClientRect();
      return r.height > 0 && r.top >= 0 && r.top < innerHeight;
    })(),
    entryVisible: (() => {
      if (!first) return false;
      const r = first.getBoundingClientRect();
      return r.top >= 0 && r.top < innerHeight;
    })(),
    bodyOverflow: body ? Math.max(0, body.scrollWidth - body.clientWidth) : 0,
    pageOverflow: Math.max(0, de.scrollWidth - de.clientWidth),
  };
})()`;

// 上部バーの入口（取り消せる削除があるときに見えるか。§4.6）
const ENTRY_DELETES = `(() => {
  const el = document.getElementById('stat-deletes');
  if (!el) return { exists: false };
  const r = el.getBoundingClientRect();
  return { exists: true, hidden: el.hidden === true, text: (el.textContent || '').trim(),
           top: Math.round(r.top), height: Math.round(r.height),
           visible: el.hidden !== true && r.top >= 0 && r.top < innerHeight && r.height > 0 };
})()`;

// 最近の削除で**押す**（取り消す・削除の確認の 2 段。POST は飲む）。
// 凍結の応答は作り物を返すので、**サーバに凍結は作られない**
const PRESS_PENDING = `(async () => {
  const real = window.fetch;
  const json = (body, status = 200) => new Response(JSON.stringify(body),
    { status, headers: { 'Content-Type': 'application/json' } });
  const preview = {
    preview_id: 'gui-preview', stage: 1, count: 2, bytes: 2000000, last_copies: 0,
    expires_at: '2999-01-01T00:00:00Z', not_allowed: [], not_allowed_count: 0,
    frees: { stage: 1, bytes: 0, at: null, note: 'カタログから外すだけです（容量は空きません）' },
    items: [
      { asset_id: 'x1', path: 'd:\\\\lib\\\\x1.png', display_path: 'D:\\\\lib\\\\X1.png',
        size: 1000000, mtime_ns: 1 },
      { asset_id: 'x2', path: 'd:\\\\lib\\\\x2.png', display_path: 'D:\\\\lib\\\\X2.png',
        size: 1000000, mtime_ns: 2 },
    ],
  };
  window.__posts = [];
  window.confirm = () => true;              // 「いま消す」の確認は自動で yes
  window.fetch = (url, opt = {}) => {
    const method = (opt.method || 'GET').toUpperCase();
    if (method !== 'POST') return real(url, opt);
    const u = String(url);
    window.__posts.push({ url: u, body: opt.body || null });
    if (u.includes('bulk-delete/preview')) return Promise.resolve(json(preview));
    if (u.includes('/bulk-delete')) {
      return Promise.resolve(json({ preview_id: 'gui-preview', stage: 1, deleted: [], skipped: [],
                                    count: 2, bytes: 2000000, requested: 2, replayed: false }));
    }
    return Promise.resolve(json({ restored: true, deletion_id: 'gui' }));
  };
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const out = { pressedUndo: false, pressedPreview: false, pressedExec: false, error: null };
  try {
    const undo = document.querySelector('#pd-running .pd-undo');
    if (undo) { undo.click(); out.pressedUndo = true; await wait(400); }
    const pv = document.querySelector('#pd-confirm .pd-preview');
    if (pv) {
      pv.click(); out.pressedPreview = true; await wait(600);
      // **凍結した一覧は「消す用意」を押す前に測る**（押すと結果の 1 行に置き換わる）
      out.items = document.querySelectorAll('#pd-confirm .pd-item').length;
      out.itemsText = (document.querySelector('#pd-confirm .pd-items') || {}).textContent || '';
      out.sumText = (document.querySelector('#pd-confirm .pd-sum') || {}).textContent || '';
      out.freesText = (document.querySelector('#pd-confirm .pd-frees') || {}).textContent || '';
      const exec = document.querySelector('#pd-confirm .pd-exec');
      if (exec && !exec.disabled) { exec.click(); out.pressedExec = true; await wait(600); }
    }
  } catch (error) { out.error = String(error); }
  window.fetch = real;
  out.posts = window.__posts;
  out.doneText = (document.querySelector('#pd-confirm .pd-done') || {}).textContent || '';
  return out;
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
      // **P8-3 の監査 C-1**: **削除の入口が画像のすぐ下に見える**こと（`tgTop` と同じ形）。
      // 押すと `#/pending-deletes?ids=` へ行くこと（**押さないテストは穴を隠す**）
      if (!got.delVisible) bad.push(`削除の入口が見える（delTop=${got.delTop}px）`);
      if (got.delText !== 'この 1 枚を削除へ回す') bad.push(`入口の文言（${got.delText}）`);
      const pressed = await evaluate(PRESS_ASSET_DELETE);
      if (!pressed || !pressed.pressed) bad.push('削除の入口を押せない');
      else if (!String(pressed.hash).startsWith('#/pending-deletes?ids=')) {
        bad.push(`削除の確認へ渡す（${pressed.hash}）`);
      } else if (!pressed.confirmShown) bad.push('削除の確認が出る');
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
        + ` delTop=${got.delTop}px delVisible=${got.delVisible}`
        + ` 削除の入口=${JSON.stringify((pressed || {}).hash)}`
        + ` markNos=[${got.markNos.join(',')}] rowNos=[${got.rowNos.join(',')}]`
        + ` タグ: rows=${got.tagRows} overflow=${got.tagOverflow} 高さの差=${got.tagHeightSpread}px`
        + ` 折り返し=${got.tagWrapped}/語名=${got.tagWrappedEn} 印=${got.tagMarks} 語釈=${got.tagWithGloss} script=${got.tagScripts}`
        + (bad.length ? `  ← ${bad.join(', ')}` : ''));
    }
    ws.close();
    console.log(failures ? `${failures} 件 NG` : 'すべて ok');
    process.exit(failures ? 1 : 0);
  }

  // 重複の整理（`#/duplicates`。P8-3）。群と枚が出るか・横に溢れないか・**押すと POST 1 回**
  if (SCREEN === 'duplicates') {
    const url = `${BASE}/#/duplicates?max=6`;
    let expectedGroups = null;
    try {
      const body = await (await fetch(`${BASE}/api/duplicates/near?max_distance=6`)).json();
      expectedGroups = (body.groups || []).length;
    } catch (error) {
      console.log(`注意: API から群を取れませんでした（群の数は見ない）: ${error.message}`);
    }
    if (expectedGroups === 0) {
      console.log('注意: 距離 ≤ 6 の群が 0 です（複製に重複が無いと押す検査はできません）');
    }
    for (const [width, height] of VIEWPORTS) {
      if (ONLY && ONLY !== `${width}x${height}`) continue;
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      // **同じ URL への `Page.navigate` は再読み込みしない**（ハッシュだけ違うと同一文書の移動に
      // なる）。前の窓で押した結果（選んだ枚）が残るので、**間に `about:blank` を挟む**
      await send('Page.navigate', { url: 'about:blank' });
      await sleep(200);
      await send('Page.navigate', { url });
      let got = null;
      for (let i = 0; i < 60; i++) {
        got = await evaluate(MEASURE_DUP);
        if (got && (got.groups > 0 || got.exact)) break;
        await sleep(250);
      }
      if (got) { await sleep(400); got = await evaluate(MEASURE_DUP); }
      if (!got) {
        failures++;
        console.log(`NG   ${width}x${height} 重複: 計測できません`);
        continue;
      }
      const pressed = got.groups > 0 ? await evaluate(PRESS_DUP) : null;
      const ex = got.groups > 0 ? await evaluate(OPEN_EXCLUSIONS) : null;
      const posts = (pressed && pressed.posts) || [];
      const makePosts = posts.filter((p) => String(p.url).includes('/api/groups'));
      const exPosts = posts.filter((p) => String(p.url).includes('/api/duplicates/exclude'));
      const bad = [];
      if (expectedGroups !== null && got.groups !== expectedGroups) {
        bad.push(`群=${expectedGroups}`);
      }
      if (got.items < got.groups * 2) bad.push('群に 2 枚以上');
      // **（監査 D-6）前提の行（理由が `<script>` の除外）が無くても NG にしない。**
      // 素の複製では 0 件が普通なので、そのときは**空の 1 行**を見る（前提を作らないと
      // 通らない検査は、複製を作り直すたびに落ちる。`gui_smoke` は自分の作り物で文字を見る）
      if (ex && ex.rows < 1) {
        if (!String(ex.empty).includes('別物として確定した組はありません')) {
          bad.push('除外の一覧の空の 1 行');
        }
        console.log(`注意: 除外の組が 0 です（理由の文字の検査はしません。D-6）`);
      } else if (ex && ex.scripts !== 0) bad.push('除外の理由の script タグを実行しない');
      else if (ex && !String(ex.reason).includes('<script>alert(1)</script>')) {
        console.log(`注意: 除外の理由が <script>… ではありません（文字の検査はしません。D-6）: `
          + `${JSON.stringify(String(ex.reason).slice(0, 24))}`);
      }
      if (!String(got.bodyClass).includes('duplicating')) bad.push('道が重複の画面になっている');
      if (got.thresholds !== 3) bad.push('しきい値が 3 つ');
      if (!got.chosen.includes('≤ 6')) bad.push('既定は ≤ 6');
      if (!got.exact) bad.push('完全重複の 1 行');
      // **（監査の注意）既定で 1 枚も選ばない**（この画面の「削除へ回す」は壊す操作への入口）
      if (got.groups > 0 && got.checked !== 0) bad.push(`既定の選択は 0 枚（${got.checked} 枚）`);
      if (got.groups > 0 && got.allText !== '全部選ぶ') bad.push(`全選択のボタン（${got.allText}）`);
      if (got.listOverflow !== 0) bad.push('一覧が横に溢れない');
      if (got.pageOverflow !== 0) bad.push('画面が横に溢れない');
      if (got.wide !== 0) bad.push(`行が右へ出ない（${got.wide}）`);
      if (got.groups > 0 && !got.entryVisible) bad.push('入口が見える（まとまりにする）');
      if (got.groups > 0) {
        if (!pressed || !pressed.pressedMake) bad.push('「まとまりにする」を押せない');
        else if (makePosts.length !== 1) bad.push(`まとまりの POST=${makePosts.length}`);
        else if (JSON.parse(String(makePosts[0].body || '{}')).kind !== 'duplicates') {
          bad.push('まとまりの種類が duplicates');
        }
        if (!pressed || !pressed.pressedExclude) bad.push('「別物として確定」を押せない');
        else if (exPosts.length !== 1) bad.push(`除外の POST=${exPosts.length}`);
      }
      if (bad.length) failures++;
      console.log(`${bad.length ? 'NG  ' : 'ok  '}${width}x${height} 重複: `
        + `groups=${got.groups}${expectedGroups === null ? '' : `/${expectedGroups}`} items=${got.items} `
        + `おすすめの印=${got.marks} 絵=${got.thumbs} しきい値=${got.thresholds}(${got.chosen}) `
        + `既定の選択=${got.checked}(${got.allText}) `
        + `overflow=${got.listOverflow}/${got.pageOverflow} wide=${got.wide} 入口=${got.entryVisible} `
        + `除外の一覧=${(ex || {}).rows} 理由=${JSON.stringify(String((ex || {}).reason).slice(0, 24))} `
        + `script=${(ex || {}).scripts} body=${JSON.stringify(got.bodyClass)} `
        + `POST まとまり=${makePosts.length} 除外=${exPosts.length} brief=${JSON.stringify(got.brief)}`
        + (bad.length ? `  ← ${bad.join(', ')}` : ''));
    }
    ws.close();
    console.log(failures ? `${failures} 件 NG` : 'すべて ok');
    process.exit(failures ? 1 : 0);
  }

  // 最近の削除（`#/pending-deletes`。P8-3）。**上部バーの入口**・行・段の印・押す検査
  if (SCREEN === 'pending') {
    const url = IDS.length
      ? `${BASE}/#/pending-deletes?ids=${IDS.map(encodeURIComponent).join(',')}`
      : `${BASE}/#/pending-deletes`;
    let pendingExpected = null;
    try {
      const body = await (await fetch(`${BASE}/api/pending-deletes`)).json();
      pendingExpected = (body.items || []).filter((it) => it.state === 'pending').length;
    } catch (error) {
      console.log(`注意: API から保留を取れませんでした（入口の可視は見ない）: ${error.message}`);
    }
    for (const [width, height] of VIEWPORTS) {
      if (ONLY && ONLY !== `${width}x${height}`) continue;
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      // **入口（上部バーの「最近の削除」）を先に見る**（ライブラリの画面）
      await send('Page.navigate', { url: 'about:blank' });
      await sleep(200);
      await send('Page.navigate', { url: `${BASE}/#/` });
      await sleep(1200);
      const entry = await evaluate(ENTRY_DELETES);
      await send('Page.navigate', { url });
      let got = null;
      for (let i = 0; i < 60; i++) {
        got = await evaluate(MEASURE_PENDING);
        if (got && (got.rows > 0 || got.empty)) break;
        await sleep(250);
      }
      if (got) { await sleep(400); got = await evaluate(MEASURE_PENDING); }
      if (!got) {
        failures++;
        console.log(`NG   ${width}x${height} 最近の削除: 計測できません`);
        continue;
      }
      const pressed = await evaluate(PRESS_PENDING);
      const posts = (pressed && pressed.posts) || [];
      const undoPosts = posts.filter((p) => String(p.url).includes('/undo'));
      const pvPosts = posts.filter((p) => String(p.url).includes('/bulk-delete/preview'));
      const bulkPosts = posts.filter((p) => /\/bulk-delete$/.test(String(p.url)));
      const bad = [];
      if (got.rows <= 0 && !got.empty) bad.push('行か空の文が出る');
      if (got.scripts !== 0) bad.push('パスの `<script>` を実行しない');
      if (!String(got.bodyClass).includes('pending')) bad.push('道が最近の削除になっている');
      if (got.rows > 0 && !/3 実削除/.test(got.strip)) bad.push('段の印（3 実削除）');
      if (got.bodyOverflow !== 0) bad.push('本体が横に溢れない');
      if (got.pageOverflow !== 0) bad.push('画面が横に溢れない');
      if (got.rows > 0 && !got.entryVisible) bad.push('入口が見える（先頭の行）');
      if (pendingExpected) {
        if (!entry || entry.hidden || !entry.visible) bad.push('上部バーの入口が見える');
        else if (!/最近の削除/.test(entry.text)) bad.push('入口に「最近の削除」と出る');
        else if (!/あと \d+:\d\d/.test(entry.text)) bad.push(`入口に残り時間（${entry.text}）`);
        if (!got.remains.some((t) => /あと \d+:\d\d/.test(t))) {
          bad.push(`行に残り時間（${got.remains.join('/')}）`);
        }
      } else if (pendingExpected === 0) {
        // **（監査 D-6）前提の行（段 3 の保留）が無くても NG にしない。** 0 件のときは
        // **入口を出さない**のが正（`frontend-design.md` §4.6）ので、そちらを見る
        if (entry && entry.exists && entry.hidden !== true) {
          bad.push('段 3 の窓が 0 なのに上部バーの入口が出ている');
        }
        console.log('注意: 段 3 の保留が 0 です（入口は出ないのが正。前提の行は要りません。D-6）');
      }
      if (pressed && pressed.pressedUndo && undoPosts.length !== 1) bad.push(`取り消しの POST=${undoPosts.length}`);
      if (IDS.length) {
        if (!got.confirmVisible) bad.push('削除の確認が見える');
        if (!pressed || !pressed.pressedPreview) bad.push('「消す物を確かめる」を押せない');
        else if (pvPosts.length !== 1) bad.push(`凍結の POST=${pvPosts.length}`);
        if (pvPosts.length === 1 && pressed.items < 2) bad.push('凍結した一覧を出す');
        if (pvPosts.length === 1 && !/2 枚/.test(pressed.sumText || '')) bad.push('凍結の件数を出す');
        if (pvPosts.length === 1 && !/カタログから外すだけ/.test(String(pressed.freesText))) {
          bad.push('いつ空くかを出す');
        }
        if (pressed && pressed.pressedExec) {
          if (bulkPosts.length !== 1) bad.push(`消す用意の POST=${bulkPosts.length}`);
          else if (JSON.parse(String(bulkPosts[0].body || '{}')).confirm !== true) bad.push('confirm: true');
          if (!/消す用意をしました/.test(pressed.doneText || '')) bad.push('用意ができた 1 行');
        }
      }
      if (bad.length) failures++;
      console.log(`${bad.length ? 'NG  ' : 'ok  '}${width}x${height} 最近の削除: `
        + `rows=${got.rows} 拾い物=${got.found} ゴミ箱=${got.trash} 残り=${JSON.stringify(got.remains)} `
        + `段=${JSON.stringify(got.strip)} overflow=${got.bodyOverflow}/${got.pageOverflow} `
        + `入口=${got.entryVisible} バー=${entry ? JSON.stringify(entry.text) : '—'} `
        + `確認=${got.confirmVisible}(${String(got.confirmText).trim().slice(0, 12)}) `
        + `POST 取り消し=${undoPosts.length} 凍結=${pvPosts.length} 用意=${bulkPosts.length} `
        + `一覧=${(pressed || {}).items} script=${got.scripts} body=${JSON.stringify(got.bodyClass)} `
        + `brief=${JSON.stringify(got.brief)}`
        + (bad.length ? `  ← ${bad.join(', ')}` : ''));
    }
    ws.close();
    console.log(failures ? `${failures} 件 NG` : 'すべて ok');
    process.exit(failures ? 1 : 0);
  }

  // ライブラリ（`#/`）の下部バー。**削除の入口**（P8-3 の監査 C-1）が**スクロール無しで
  // 見える**か、2 枚選ぶと押せて、押すと `#/pending-deletes?ids=` へ行くか（**押す検査**）
  if (SCREEN === 'library') {
    for (const [width, height] of VIEWPORTS) {
      if (ONLY && ONLY !== `${width}x${height}`) continue;
      await send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false });
      // **同じ URL への `Page.navigate` は再読み込みしない**（ハッシュだけ違うと同一文書の移動に
      // なる）。前の窓で押した結果（選んだ枚・行き先）が残るので、**間に `about:blank` を挟む**
      await send('Page.navigate', { url: 'about:blank' });
      await sleep(200);
      await send('Page.navigate', { url: `${BASE}/#/` });
      let got = null;
      for (let i = 0; i < 60; i++) {
        got = await evaluate(MEASURE_LIBRARY);
        if (got && got.frames > 0) break;
        await sleep(250);
      }
      if (got) { await sleep(400); got = await evaluate(MEASURE_LIBRARY); }
      if (!got) {
        failures++;
        console.log(`NG   ${width}x${height} ライブラリ: 計測できません`);
        continue;
      }
      const pressed = await evaluate(PRESS_LIBRARY);
      const bad = [];
      if (got.frames <= 0) bad.push('画像が出る');
      if (!got.barVisible) bad.push('下部バーが見える');
      if (!got.buttonVisible) bad.push('削除の入口が見える（下部バー）');
      if (got.text !== '選んだ 0 枚を削除へ回す') bad.push(`入口の文言（${got.text}）`);
      if (got.disabled !== true) bad.push('1 枚も選んでいなければ押せない');
      if (pressed.picked !== 2) bad.push(`Ctrl + クリックで 2 枚選ぶ（${pressed.picked}）`);
      else if (pressed.text !== '選んだ 2 枚を削除へ回す') bad.push(`選んだ枚を文言に出す（${pressed.text}）`);
      if (!pressed.pressed) bad.push('削除へ回すを押せない');
      else if (!/^#\/pending-deletes\?ids=/.test(String(pressed.hash))) {
        bad.push(`削除の確認へ渡す（${pressed.hash}）`);
      }
      if (got.pageOverflow !== 0) bad.push('画面が横に溢れない');
      if (bad.length) failures++;
      console.log(`${bad.length ? 'NG  ' : 'ok  '}${width}x${height} ライブラリ: `
        + `frames=${got.frames} 下部バー=${got.barVisible} 入口=${got.buttonVisible} `
        + `文言=${JSON.stringify(got.text)} 押せる=${got.disabled === false} `
        + `選んだ枚=${pressed.picked}(${JSON.stringify(pressed.text)}) `
        + `行き先=${JSON.stringify(pressed.hash)} overflow=${got.pageOverflow}`
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
