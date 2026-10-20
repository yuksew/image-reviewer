#!/usr/bin/env node
// 比較画面（`apps/gui/compare.js`）の**描いた文字列**を、ブラウザ無しで確かめる
// （監査 C1・B2、監査 A1、P5-3 の差分ヒートマップと似ている順）。
//
// 見ているもの（見ていないもの）:
// - 見る: `renderStage()` / `renderDiff()` が作った HTML 文字列（基準の印・「基準にする」・
//   分からないセル・`changed` だけを描くこと・並び順・差分の理由と強制）と、
//   マウス / キーで `base=` が書き換わること、
//   **キーを 1 つも押さずに「それでも出す」へ届くこと**（監査 A1。
//   `index.html` の入れ子を読んで、**祖先の `hidden`** も見る）
// - **見ない**: 見た目（CSS の当たり方）、画像の表示、実際のブラウザの挙動、
//   タイルの選択の印（`document.querySelector` は作り物なので `select()` は何もしない）と
//   `transform`。見た目の確認は人の目で行う（ここで「見た」とは言わない）
//
// 使い方: node tools/gui_smoke.mjs   （依存は無し。DOM は最小の作り物）
'use strict';

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

// ---- `index.html` の入れ子（監査 A1 / 監査 D2）----
//
// 作り物の DOM は「親の `hidden`」を知らないので、`#cmp-heatforce` が
// `hidden` で開閉する包み（`#cmp-heatwrap`）の中にあるかを見られなかった。
// `index.html` から**入れ子と静的な `hidden`** だけを読んで、祖先の `hidden` を見られるようにする
// （読むのは id を持つ要素だけ。JS が触れるのは id か選択子で引いた要素なので、これで足りる）。
const HTML = readFileSync(join(HERE, '..', 'apps', 'gui', 'index.html'), 'utf8');
const VOID_TAGS = new Set(['br', 'hr', 'img', 'input', 'link', 'meta', 'source']);
const staticHidden = new Set();
const parents = new Map();          // id -> [祖先の id（外側から順）]

function readStructure(html) {
  const tagRe = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>/g;
  const stack = [];
  let at;
  while ((at = tagRe.exec(html)) !== null) {
    const [, closing, rawTag, attrs] = at;
    const tag = rawTag.toLowerCase();
    if (closing) {
      for (let i = stack.length - 1; i >= 0; i -= 1) {
        if (stack[i].tag === tag) { stack.length = i; break; }
      }
      continue;
    }
    const found = /\bid="([^"]+)"/.exec(attrs);
    const id = found ? found[1] : null;
    const hidden = /(^|\s)hidden(\s|=|$)/.test(attrs);
    if (id) {
      parents.set(id, stack.map((entry) => entry.id).filter(Boolean));
      if (hidden) staticHidden.add(id);
    }
    if (!VOID_TAGS.has(tag)) stack.push({ tag, id });
  }
}
readStructure(HTML);

// ---- 最小の DOM（compare.js が使う口だけ）----

class ClassList {
  constructor() { this.set = new Set(); }
  add(...names) { for (const n of names) this.set.add(n); }
  remove(...names) { for (const n of names) this.set.delete(n); }
  contains(name) { return this.set.has(name); }
  toggle(name, on) {
    if (on === undefined) { this.set.has(name) ? this.set.delete(name) : this.set.add(name); }
    else if (on) this.set.add(name);
    else this.set.delete(name);
  }
}

class El {
  constructor(tag = 'div', id = '') {
    this.tagName = String(tag).toUpperCase();
    this.id = id;
    this.children = [];
    this.html = '';
    this.textContent = '';
    this.className = '';
    this.dataset = {};
    this.value = '';
    this.clientWidth = 900;
    this.clientHeight = 400;
    this.style = { setProperty() {}, };
    this.classList = new ClassList();
    this.attrs = new Map();
    this._listeners = new Map();
    this._found = new Map();          // querySelector の結果を覚える（同じ相手に配れる）
  }
  // 本物の DOM と同じく、`innerHTML` を入れ直すと子は消える（作り物でも揃えておく）
  set innerHTML(value) { this.html = String(value); this.children = []; }
  get innerHTML() { return this.html; }
  setAttribute(name, value) { this.attrs.set(String(name), String(value)); }
  getAttribute(name) {
    return this.attrs.has(String(name)) ? this.attrs.get(String(name)) : null;
  }
  removeAttribute(name) { this.attrs.delete(String(name)); }
  addEventListener(type, fn) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(fn);
  }
  removeEventListener(type, fn) {
    const list = this._listeners.get(type) || [];
    const at = list.indexOf(fn);
    if (at >= 0) list.splice(at, 1);
  }
  querySelector(selector) {
    if (!this._found.has(selector)) this._found.set(selector, new El('div'));
    return this._found.get(selector);
  }
  querySelectorAll() { return []; }
  appendChild(child) { this.children.push(child); return child; }
  // P6-2 の注記が使う（作り物でも本物と同じ形で返す。`replaceWith` は器を差し替えるだけ）
  replaceWith(node) { this._replacedWith = node; return node; }
  insertAdjacentHTML(_where, html) { this.html += String(html); }
  click() { this.dispatch('click'); }
  getBoundingClientRect() {
    return { left: 0, top: 0, right: this.clientWidth, bottom: this.clientHeight,
             width: this.clientWidth, height: this.clientHeight };
  }
  dispatch(type, event = {}) {
    for (const fn of this._listeners.get(type) || []) {
      fn({ type, target: this, preventDefault() {}, stopPropagation() {}, ...event });
    }
  }
}

const byId = new Map();
function el(id) {
  if (!byId.has(id)) {
    const made = new El('div', id);
    // `index.html` に `hidden` が付いている要素は、最初から隠れている（`#cmp-heatwrap`）
    if (staticHidden.has(id)) made.hidden = true;
    byId.set(id, made);
  }
  return byId.get(id);
}

// **見えていて押せるか**（監査 A1）。`hidden` は祖先から継承する（本物の DOM と同じ。
// 作り物の DOM がこれを見ていなかったので、`#cmp-heatwrap` の中の強制の口を見逃していた）
function visible(id) {
  const node = el(id);
  if (node.hidden === true || node.disabled === true) return false;
  for (const parent of parents.get(id) || []) {
    const ancestor = el(parent);
    if (ancestor.hidden === true || ancestor.disabled === true) return false;
  }
  return true;
}

// `inner` が `outer` の**中**にあるか（`index.html` の入れ子。監査 A1 / D2）
function isInside(id, outerId) {
  return (parents.get(id) || []).includes(outerId);
}

class Document {
  constructor() {
    this.body = new El('body');
    this._listeners = new Map();
    this.documentElement = new El('html');
    // `createElement` で作った物を覚える（P6-2 の注記の舞台のように、id を持たない要素を
    // テストから掴むため）
    this.created = [];
  }
  // `index.html` にある id は必ず見つかる（`cmp-stage` / `cmp-diff` / `cmp-brief` …）
  getElementById(id) { return el(id); }
  createElement(tag) { const made = new El(tag); this.created.push(made); return made; }
  querySelector(selector) {
    // 本物の DOM と同じく、`createElement` で作った要素を**クラス名で**引けるようにする。
    // ここが null のままだと、注記の印（`document.querySelector('.anno-stage')` から描く）が
    // 作り物の DOM では描かれず、**一覧の番号と印の番号のずれ**（P6-2 の監査 上位 3）を
    // 確かめられない
    const text = String(selector);
    if (!text.startsWith('.')) return null;
    const want = text.slice(1);
    return this.created
      .filter((node) => String(node.className).split(/\s+/).includes(want)).pop() || null;
  }
  querySelectorAll() { return []; }
  addEventListener(type, fn) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(fn);
  }
  removeEventListener(type, fn) {
    const list = this._listeners.get(type) || [];
    const at = list.indexOf(fn);
    if (at >= 0) list.splice(at, 1);
  }
  dispatchKey(key) {
    for (const fn of this._listeners.get('keydown') || []) {
      fn({ key, target: { tagName: 'BODY' }, preventDefault() {}, stopPropagation() {} });
    }
  }
}

const location = { hash: '' };
const document_ = new Document();
const window_ = { addEventListener() {}, CSS: { escape: (s) => String(s) } };

globalThis.document = document_;
globalThis.window = window_;
globalThis.CSS = window_.CSS;
Object.defineProperty(globalThis, 'location',
  { value: location, writable: true, configurable: true });

// ---- サーバが返す 1 文書（監査 B2 の形: 捕獲 1 枚 vs 未捕獲 1 枚）----

const A = '01M4Z0KJSS8EXT49JGAZMZGTFJ';
const B = '01M4Z0KJRD9JFSJEQVFX3S40Z7';
const PREFIX = '(masterpiece, best quality), safe,';
const CAPTURED = `${PREFIX}\n\n1girl. solo. chibi.`;

function item(id, prompt, extra) {
  return {
    asset_id: id,
    thumb: `/api/assets/${id}/thumb?size=1024`,
    thumb_small: `/api/assets/${id}/thumb?size=256`,
    // P5-3: seed は **A が 2 / B が 1**（入力順と seed 順が食い違うようにして、
    // 並び順の切り替えを確かめられるようにする）
    provenance: { model: 'anima.safetensors', seed: id === A ? '2' : '1', steps: 10,
                  cfg: 1.0, width: 1024, height: 1024 },
    prompts: { ja_text: id === A ? '1girl。' : '1girl。海。', en_text: id === A ? '1girl.' : null,
               final_prompt: prompt, final_prompt_unknown: id !== A,
               concat_prefix: id === A ? null : PREFIX,
               final_prompt_source: 'reconstructed', negative_literal: null },
    tags: null, phash: null, review_state: extra || 'unreviewed',
  };
}

const FIXTURE = {
  base: A,
  ids: [A, B],
  items: [item(A, CAPTURED, 'kept'), item(B, null)],
  // P5-3: 似ている順（サーバが距離を決める）と、差分ヒートマップの規則
  nearest: { base: A, order: [A, B], distances: { [A]: 0, [B]: 3 } },
  pairs: [{ a_id: A, b_id: B, phash_distance: 3, same_seed: false,
            heatmap: { enabled: true, reason: null } }],
  diff: {
    keys: ['final_prompt', 'steps'],
    changed: [{
      key: 'seed', label: 'seed', kind: 'text', state: 'changed',
      values: ['2', '1'], cells: ['same', 'changed'],
    }, {
      key: 'final_prompt', label: '最終プロンプト', kind: 'prompt', state: 'incomplete',
      values: [CAPTURED, null], cells: ['same', 'unknown'],
      unknown: [B], known_prefix: { [B]: PREFIX },
    }],
    same: [{
      key: 'steps', label: 'steps', kind: 'num', state: 'same',
      values: ['10', '10'], cells: ['same', 'same'],
    }],
    prompt_diff: {
      key: 'final_prompt', base: A,
      per_asset: { [A]: [{ t: '1girl', state: 'same' }], [B]: [] },
      tokens: [{ t: '1girl', state: 'same', assets: [A] }],
      words_equal: false, normalized_equal: false, reweighted: false, unknown: [B],
    },
    ja_diff: { base: A, normalized_equal: false,
               per_asset: { [A]: { sentences: [{ t: '1girl。', state: 'same' }], chars: [] },
                            [B]: { sentences: [{ t: '1girl。', state: 'same' },
                                               { t: '海。', state: 'added' }], chars: [] } } },
  },
};

// 1 組の指標（`POST /api/compare/pair` の応答。P5-3）
const PAIR_FIXTURE = {
  a_id: A, b_id: B, algo_version: 1, phash_distance: 3,
  ssim: 0.9812, changed_fraction: 0.0421, mean_abs: 3.5, cached: false,
  heatmap: { enabled: true, forced: false, reason: null, distance_threshold: 6,
             available: true, aligned: true, dx: -2, dy: 0, peak_ratio: 120.5,
             image: 'data:image/webp;base64,UklGRg==' },
};

let asked = [];
let writes = [];        // 状態を変える要求（`GET` 以外）。§8.2-6 の「1 回だけ」を見るのに使う

// P6-2 の監査 上位 3: 一覧の番号と画像の印の番号を**同じ規則**にする検査の作り物。
// **メモ（領域なし）を間に挟む**（別々に数えると「一覧 3: 楕円 ↔ 印 2」にずれる形）
let ANNO_ITEMS = [];
globalThis.fetch = async (url, options) => {
  asked.push(String(url));
  const method = String(options?.method || 'GET').toUpperCase();
  if (method !== 'GET') writes.push({ url: String(url), method, body: options?.body });
  // `res.json()` も `res.text()` も使えるようにする（`compare.js` は `text()`、
  // P6-1b の画面は `json()` を使う。本物の `fetch` はどちらもある）
  const asJson = (body) => ({
    ok: true, status: 200,
    text: async () => JSON.stringify(body),
    json: async () => JSON.parse(JSON.stringify(body)),
  });
  if (String(url).startsWith('/api/compare/pair')) return asJson(PAIR_FIXTURE);
  return asJson(FIXTURE);
};

// ---- 実行 ----

const { showCompare, wireCompare } = await import('../apps/gui/compare.js');
const failures = [];
function check(ok, message) {
  if (!ok) failures.push(message);
  console.log(`${ok ? 'ok  ' : 'NG  '} ${message}`);
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const ids = () => el('cmp-stage').children.map((tile) =>
  tile.querySelector('.cmp-frame').dataset.id || tile.innerHTML.match(/data-id="([^"]+)"/)[1]);
wireCompare();

await showCompare(`ids=${A},${B}`);
check(asked.length === 1 && asked[0].startsWith('/api/compare?ids='), `要求は 1 回: ${asked[0]}`);

const stage = el('cmp-stage');
const diffHtml = el('cmp-diff').innerHTML;
const tileHtml = stage.children.map((tile) => tile.innerHTML);
check(stage.children.length === 2, `タイルは 2 枚: ${stage.children.length}`);
check(stage.children[0].className.includes('is-base'),
  `基準のタイルに is-base: ${stage.children[0].className}`);
check(!stage.children[1].className.includes('is-base'), '基準でないタイルには is-base を付けない');
check(tileHtml[0].includes('aria-pressed="true"') && tileHtml[0].includes('基準 ✓'),
  '基準のタイルのボタンは押された状態で出る');
check(tileHtml[1].includes('aria-pressed="false"') && tileHtml[1].includes('基準にする'),
  '他のタイルには「基準にする」が出る（マウスの経路。監査 C1）');
check(diffHtml.includes('tr class="row changed"'), '違う行を描いている');
check(!diffHtml.includes('tr class="row same"'), '既定では同じ行を描かない（畳む）');
check(diffHtml.includes('同じ 1 行は畳んであります'), '畳んだ行数を出している');
check(diffHtml.includes('tr class="row incomplete"'), '分からない枚がある行も描いている（監査 B2）');
check(diffHtml.includes('badge incomplete') && diffHtml.includes('一部が分からない'),
  '分からない枚がある行に印が出る（監査 B2）');
check(diffHtml.includes('class="cell unknown"') && diffHtml.includes('分からない'),
  '分からないセルを「分からない」と描く（監査 B2）');
check(diffHtml.includes('前置語: (masterpiece'), '分かっている前置語を添えている（監査 B2）');
check(!/class="cell unknown"[^>]*>—</.test(diffHtml), '分からないセルを「無い（—）」と描かない');
check(diffHtml.includes('訳を取り込んでいない（分かりません）'), '語の差分に「分からない」を出す');
check(diffHtml.includes('訳を取り込んでいない画像がある'), '語の差分の要約が「同じ」と言わない');
// 監査 C1（数値の書体）: 数値のセルだけ `num` を付ける（等幅版の一族を当てるため）
check(/class="cell changed num"/.test(diffHtml),
  'seed のセルに num を付ける（監査 C1。`seed` は kind が text でも数値）');
check(!/class="cell [a-z]* num"/.test(diffHtml.split('row incomplete')[1] || ''),
  '数値でない行のセルには num を付けない');

// マウスだけで基準を変えられる（監査 C1）
location.hash = '';
stage.children[1].querySelector('.cmp-base').dispatch('click', { stopPropagation() {} });
check(location.hash === `#/compare?ids=${A},${B}&base=${B}`,
  `「基準にする」で base= が変わる（マウス）: ${location.hash}`);

// キーでも変えられる（補助。選択中のタイルを基準にする）
location.hash = '';
document_.dispatchKey('2');            // 2 番を選ぶ
document_.dispatchKey('b');            // 基準にする
check(location.hash === `#/compare?ids=${A},${B}&base=${B}`,
  `b キーで base= が変わる（キー）: ${location.hash}`);

// URL が正（reload / 戻るで同じ見え方になる）。`base=` が要求に載ることを確かめる
asked = [];
await showCompare(`ids=${A},${B}&base=${B}`);
check(asked[0] === `/api/compare?ids=${A}%2C${B}&base=${B}`,
  `URL の base= が要求に載る: ${asked[0]}`);

// ---- P5-3: 似ている順（`comparison.md` §4.1）----

await showCompare(`ids=${A},${B}`);
check(ids().join(',') === `${A},${B}`, `既定は入力順: ${ids().join(',')}`);

document_.dispatchKey('r');                       // 入力順 → seed 順
check(el('cmp-order').textContent.includes('seed 順'),
  `r で並びが seed 順に変わる: ${el('cmp-order').textContent}`);
check(ids().join(',') === `${B},${A}`,
  `seed 順（B が seed 1、A が seed 2）で入れ替わる: ${ids().join(',')}`);

document_.dispatchKey('r');                       // seed 順 → 似ている順
check(el('cmp-order').textContent.includes('似ている順'),
  `r で並びが似ている順に変わる: ${el('cmp-order').textContent}`);
check(ids().join(',') === `${A},${B}`,
  `似ている順はサーバの nearest.order に従う: ${ids().join(',')}`);
check(el('cmp-stage').children[1].innerHTML.includes('距離 3'),
  '似ている順ではサーバが返した距離を出す（画面では数えない）');

// ---- P5-3: 差分ヒートマップ（`comparison.md` §2.3・点検 G6）----

check(el('cmp-heatwhy').textContent.includes('出せます'),
  `出せる組では理由の行が「出せます」: ${el('cmp-heatwhy').textContent}`);
check(el('cmp-heat').disabled === false, '出せる組ではボタンが押せる');
check(el('cmp-heat').getAttribute('aria-disabled') === 'false',
  '出せる組は aria-disabled=false（監査 A1）');
check(visible('cmp-heatforce'),
  '出せる組でも「それでも出す」を出しておく（監査 C1。同じ seed でも 85 組中 81 組は合わない）');

// 「同じ seed」は「合う」の予測ではない（監査 C1）。言い切らない文言になっているか
FIXTURE.pairs[0].same_seed = true;
await showCompare(`ids=${A},${B}`);
check(el('cmp-heatwhy').textContent.includes('同じ seed')
  && el('cmp-heatwhy').textContent.includes('出してみるまで'),
  `同じ seed では言い切らない（監査 C1）: ${el('cmp-heatwhy').textContent}`);
FIXTURE.pairs[0].same_seed = false;
check(visible('cmp-heatforce'),
  '出せる組でも「それでも出す」を出しておく（監査 C1。同じ seed でも 85 組中 81 組は合わない）');

// 条件の外（遠い組）。ここから **キーは 1 つも押さない**（監査 A1: マウスだけで届くか。
// 以前のこの節は `d` を押してから見ていたので、包みの中の強制の口を見逃していた）
FIXTURE.pairs[0].heatmap = { enabled: false, reason: '同じ seed ではなく、pHash 距離 40 がしきい値 6 より大きい' };
asked = [];
await showCompare(`ids=${A},${B}`);
check(el('cmp-heat').disabled !== true,
  '出せない組でも「差分ヒートマップ」を disabled にしない（監査 A1）');
check(el('cmp-heat').getAttribute('aria-disabled') === 'true',
  '押せないことは aria-disabled で示す（監査 A1）');
check(el('cmp-heatwhy').textContent.includes('pHash 距離 40'),
  `出せない理由を 1 行で出す: ${el('cmp-heatwhy').textContent}`);
check(visible('cmp-heatforce'),
  'キーを押さなくても「それでも出す」が見えている（監査 A1）');
check(!isInside('cmp-heatforce', 'cmp-heatwrap'),
  '強制の口は `hidden` の包み（`#cmp-heatwrap`）の中に無い（監査 A1）');
check(el('cmp-heatforce').disabled !== true, '強制の口は押せる（監査 A1）');

// 「差分ヒートマップ」を**マウスで**押す → 理由と強制の口が開く（サーバは叩かない）
el('cmp-heat').dispatch('click');
await tick();
check(!asked.some((url) => url.startsWith('/api/compare/pair')),
  '規則で出せない組では画像を作りに行かない（復号を無駄に走らせない）');
check(el('cmp-heatimg').innerHTML.includes('差分を出せません'),
  '出せない組では画像ではなく理由を出す');
check(visible('cmp-heatforce'), '理由を出した後も強制の口が見えている（監査 A1）');

// 「それでも出す」を**マウスで**押す → 組の口を叩く
PAIR_FIXTURE.heatmap = { enabled: false, forced: true, reason: null, distance_threshold: 6,
                         available: true, aligned: true, dx: -24, dy: 0, peak_ratio: 55.9,
                         corr: 0.949, image: 'data:image/webp;base64,UklGRg==' };
asked = [];
el('cmp-heatforce').dispatch('click');
await tick();
await tick();
check(asked.some((url) => url.startsWith('/api/compare/pair')),
  `強制では組の口を叩く（キーを押さずに）: ${asked.join(' ')}`);
check(el('cmp-heatimg').innerHTML.includes('data:image/webp'),
  '強制した差分の画像を描く');
check(el('cmp-heatmetrics').textContent.includes('SSIM 0.981'),
  `指標はサーバの値をそのまま出す: ${el('cmp-heatmetrics').textContent}`);
check(el('cmp-heatforce').hidden === true, '強制した絵が出たら強制の口は隠す（監査 A1）');

// `d` キーでも同じところへ行ける（**補助**。§6。監査 A1 で主の経路ではなくなった）
await showCompare(`ids=${A},${B}`);
asked = [];
document_.dispatchKey('d');
await tick();
check(!asked.some((url) => url.startsWith('/api/compare/pair')),
  '出せない組では `d` で画像を作りに行かない（復号を無駄に走らせない）');
check(el('cmp-heatimg').innerHTML.includes('差分を出せません'),
  '`d` でも画像ではなく理由を出す');
check(el('cmp-heatforce').hidden === false, '`d` で開いても強制の口は残る（点検 G6）');

// 出せない + 位置が合わない（force でも画像を出さない）
PAIR_FIXTURE.heatmap = { enabled: false, forced: true,
                         reason: '位置が合いません（平行移動が大きすぎます: 80×0px）',
                         available: false, aligned: false, dx: -80, dy: 0, corr: -0.1,
                         image: null };
await showCompare(`ids=${A},${B}`);         // 組を選び直す（強制の口がまた見える）
check(visible('cmp-heatforce'), '組を選び直すと強制の口がまた見える（監査 A1）');
el('cmp-heatforce').dispatch('click');
await tick();
await tick();
check(el('cmp-heatimg').innerHTML.includes('位置が合いません'),
  '位置が合わないときは画像ではなく「位置が合いません」を出す');

// ---- P6-1b: 要求の一覧・件数・タブのタイトル（設計 §8.2 の 1〜5）----
//
// 見る: カードの描画（`ask` / `conditions` / AI の推しの番号 / `ai_note`）と `esc()`、
//       「断る」の入力の検査（空なら送らない）、空の状態の文言、バーの件数とタブのタイトル、
//       まとまりレビューの判断の payload（純関数）
// 見ない: 見た目（CSS）と、まとまりレビューの描画（本物のブラウザで見る。`gui_layout.mjs`）

const REQ_A = '01M4Z0KJREQ0000000000000A';
const REQ_B = '01M4Z0KJREQ0000000000000B';
const GRP_A = '01M4Z0KJGRP0000000000000A';
const PICK = '01M4Z0KJSS8EXT49JGAZMZGTFJ';       // `compare.js` の A と同じ id（groups の並びで 3 番目）

function requestFixture(over) {
  return {
    id: REQ_A, group_id: GRP_A, state: 'open', target_key: 'cut-1', actor: 'agent',
    ask: '<script>alert(1)</script> この 8 枚から 1 枚選んでほしい',
    conditions: ['左手の形', '<b>背景</b>の窓の位置'], origin: '作品A / カット03',
    wants: ['selected_ids', 'reason'], created_at: new Date(Date.now() - 180000).toISOString(),
    closed_at: null, closed_by: null, decline_note: null, superseded_by: null, response: null,
    ai: { pick_asset_id: PICK, note: '<i>手が素直</i>で窓の位置も合っている' },
    ...over,
  };
}

const GROUPS_FIXTURE = {
  id: GRP_A, title: '同じ指示で出した候補', kind: 'request', policy: 'pick_one', state: 'open',
  items: [
    { asset_id: 'id-1', review_state: 'unreviewed', position: 0 },
    { asset_id: 'id-2', review_state: 'unreviewed', position: 1 },
    { asset_id: PICK, review_state: 'unreviewed', position: 2 },
  ],
  selected_asset_ids: [], decision: null,
};

const REQ_FIXTURES = [requestFixture({}), requestFixture({ id: REQ_B, state: 'declined', decline_note: 'この 3 枚は別のカットです' })];

// P6-1b の監査 B2（3）: `load()` を重ねたときの検査で使う「1 回だけ遅く返す」仕掛け
let slowList = null;      // { items, delayMs } を 1 回だけ使う
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

globalThis.fetch = async (url, options) => {
  const text = String(url);
  asked.push(text);
  const method = String(options?.method || 'GET').toUpperCase();
  if (method !== 'GET') writes.push({ url: text, method, body: options?.body });
  const ok = (body) => ({
    ok: true, status: 200,
    text: async () => JSON.stringify(body),
    json: async () => JSON.parse(JSON.stringify(body)),
  });
  if (text.startsWith('/api/review-requests?')) {
    const body = { items: REQ_FIXTURES, next_cursor: null, counts: { open: 1 } };
    if (text.includes('count_only=1')) return ok({ items: [], next_cursor: null, counts: { open: 3 } });
    if (slowList) {
      const plan = slowList;
      slowList = null;
      await sleep(plan.delayMs);
      return ok({ items: plan.items, next_cursor: null, counts: { open: plan.items.length } });
    }
    return ok(body);
  }
  if (text.startsWith('/api/review-requests/')) return ok({ ok: true });
  if (text.startsWith('/api/groups/')) return ok(GROUPS_FIXTURE);
  if (text.startsWith('/api/reason-codes')) {
    return ok({ items: [{ id: 'rc.reject.other', label: 'その他', applies_to: 'reject' }] });
  }
  if (text.startsWith('/api/compare/pair')) {
    return { ok: true, status: 200, text: async () => JSON.stringify(PAIR_FIXTURE) };
  }
  // P6-2: 注記（一覧・作成・書き出し）。テストは「何回叩いたか」と body を見る
  if (text.includes('/annotations')) {
    return ok({ items: ANNO_ITEMS, next_cursor: null,
                schema: 'urn:image-reviewer:schema:annotation-export',
                abi: '0.1', asset_id: 'asset-1', image: { width: 900, height: 400 },
                annotations: ANNO_ITEMS, crops: [] });
  }
  return ok(FIXTURE);
};

const badge = await import('../apps/gui/badge.js');
const requestsUi = await import('../apps/gui/requests.js');
const groupUi = await import('../apps/gui/group.js');

// 1. バーの件数（0 なら出さない）
badge.renderCount(3);
check(el('stat-requests').textContent === '要求 3', `バーに件数を出す: ${el('stat-requests').textContent}`);
check(el('stat-requests').hidden === false, '件数があるときは出す');
badge.renderCount(0);
check(el('stat-requests').hidden === true, '0 件のときは出さない（§5.4）');

// 2. タブのタイトル
badge.applyTitle(3);
check(document_.title === '(3) image-reviewer', `タブのタイトル: ${document_.title}`);
badge.applyTitle(0);
check(document_.title === 'image-reviewer', `0 件なら素の名前: ${document_.title}`);

// 3. カードの描画と `esc()`
asked = [];
await requestsUi.showRequests('');
const list = el('req-list');
check(list.children.length === 2, `カードを 2 枚描く: ${list.children.length}`);
const card0 = list.children[0];
const cardHtml = card0.innerHTML;
check(cardHtml.includes('この 8 枚から 1 枚選んでほしい'), 'カードに `ask` を出す');
check(cardHtml.includes('左手の形') && cardHtml.includes('背景'), 'カードに `conditions` を出す');
check(cardHtml.includes('AI の推し: 3 番'), `AI の推しの番号を出す: ${cardHtml.match(/AI の推し[^<]*/)}`);
check(cardHtml.includes('手が素直'), 'カードに `ai_note` を出す');
check(!cardHtml.includes('<script>') && cardHtml.includes('&lt;script&gt;'),
  'エージェントの自由文をエスケープする（§4.4）');
check(cardHtml.includes('未対応'), '状態の語を出す');
check(list.children[1].innerHTML.includes('断りました'), '断った要求は理由を出す');

// 4. 「断る」の入力の検査（空なら送らない／理由つきなら 1 回だけ）
const send = card0.querySelector('.req-decline-send');
const note = card0.querySelector('.req-decline-note');
asked = [];
note.value = '   ';
send.dispatch('click');
await tick();
check(!asked.some((url) => url.includes('/decline')), '空のままでは断りを送らない（§5.1）');
asked = [];
note.value = 'この 3 枚は別のカットなので、まとめて選べません';
send.dispatch('click');
await tick();
await tick();
const declineCalls = asked.filter((url) => url.includes('/decline'));
check(declineCalls.length === 1, `理由を入れたら 1 回だけ叩く: ${declineCalls.length}`);
check(declineCalls[0] === `/api/review-requests/${REQ_A}/decline`,
  `断りの口を叩く: ${declineCalls[0]}`);

// 5. 空の状態の文言
REQ_FIXTURES.length = 0;
await requestsUi.showRequests('state=all');
check(el('req-list').children.length === 0, '0 件ならカードを描かない');
check(el('req-empty').textContent.includes('エージェントからの要求はありません'),
  `空の文言: ${el('req-empty').textContent}`);
check(el('req-empty').hidden === false, '空の文言を出す');

// 6. まとまりレビューの判断の payload（純関数。設計 §5.1b）
const items = GROUPS_FIXTURE.items;
const one = groupUi.decideOnePayload(items, PICK, 'rc.reject.other');
check(one.length === 3 && one[2].verdict === 'keep' && one[0].verdict === 'reject',
  '「この 1 枚に決める」は選んだ 1 枚だけ keep');
check(one.filter((row) => row.verdict === 'reject').every((row) => row.reason_code_id === 'rc.reject.other'),
  'ボツには理由を付ける（枚ごと。§9.2）');
// P6-1b の監査 B1: **キープの理由**を選んだ枚に入れる（要求の `response.reason_code_id` が埋まる）
const oneKeep = groupUi.decideOnePayload(items, PICK, 'rc.reject.other', 'rc.keep.favorite');
check(oneKeep[2].reason_code_id === 'rc.keep.favorite',
  `キープの理由を選んだ枚に入れる（監査 B1）: ${oneKeep[2].reason_code_id}`);
check(groupUi.decideOnePayload(items, PICK, 'rc.reject.other')[2].reason_code_id === null,
  'キープの理由は任意（選ばなければ null）');
const all = groupUi.allRejectPayload(items, 'rc.reject.other');
check(all.length === 3 && all.every((row) => row.verdict === 'reject'),
  '「全部ボツ」は全枚 reject');

// 6b. **決めるボタンを実際に押す**（監査 B2（2）。実装者が踏んだ「関数の名前隠し」の検査）
//     —— `gui_layout.mjs --screen group` が本物の Chrome で見るものの、軽い DOM 版
groupUi.wireGroup();
await groupUi.showGroup(GRP_A);
el('group-reason').value = 'rc.reject.other';
el('group-reason').dispatch('change');
el('group-keep-reason').value = 'rc.keep.favorite';
el('group-keep-reason').dispatch('change');
writes.length = 0;
el('group-decide').dispatch('click');
await tick();
await tick();
const decidePosts = writes.filter((w) => w.method === 'POST' && w.url.endsWith('/decide'));
check(decidePosts.length === 1, `決めるボタンで 1 回だけ送る（監査 B2）: ${decidePosts.length} 回`);
const decideBody = JSON.parse(String(decidePosts[0]?.body || '{}'));
const kept = (decideBody.items || []).filter((row) => row.verdict === 'keep');
check(kept.length === 1 && kept[0].reason_code_id === 'rc.keep.favorite',
  `押したときもキープの理由を送る（監査 B1）: ${JSON.stringify(kept)}`);
check((decideBody.items || []).filter((row) => row.verdict === 'reject')
  .every((row) => row.reason_code_id === 'rc.reject.other'), '押したときもボツの理由を送る');
// 拡大への入口は**まとまりを引き継ぐ**（注記が要求の応答に出る。P6-2 の穴）
groupUi.wireGroup();
location.hash = '';
el('group-zoom').dispatch('click');
check(String(location.hash).includes(`#/asset/`) && String(location.hash).includes(`group=${GRP_A}`),
  `拡大にまとまりを引き継ぐ: ${location.hash}`);

// 6b-2. **（監査 C-1）まとまりからも削除へ回せる**（拡大と同じ 1 枚。**押す検査**）
const chose = String(location.hash).split('#/asset/')[1].split('?')[0];
location.hash = '';
el('group-delete').dispatch('click');
check(el('group-delete').textContent === '選んだ 1 枚を削除する…',
  `まとまりの入口の文言: ${el('group-delete').textContent}`);
check(location.hash === `#/pending-deletes?ids=${chose}`,
  `まとまりの入口が削除の確認へ渡す（監査 C-1）: ${location.hash}`);
location.hash = '';

// 6c. `ai.pick_index` があれば、まとまりを引かずに番号を出す（P6-1a の監査 C1）
REQ_FIXTURES.length = 0;
REQ_FIXTURES.push(requestFixture({ ai: { pick_asset_id: PICK, pick_index: 2, note: '手が素直' } }));
asked = [];
await requestsUi.showRequests('');
check(el('req-list').children[0].innerHTML.includes('AI の推し: 2 番'),
  `サーバの pick_index を使う（監査 C1）: ${el('req-list').children[0].innerHTML.match(/AI の推し[^<]*/)}`);
check(!asked.some((url) => url.startsWith('/api/groups/')),
  '番号のためにまとまりを引かない（監査 C1）');

// 6d. `load()` を重ねても、**後から始めた方**の結果だけが残る（監査 B2（3）。世代番号）
REQ_FIXTURES.length = 0;
REQ_FIXTURES.push(requestFixture({}), requestFixture({ id: REQ_B }));
slowList = { items: REQ_FIXTURES.slice(), delayMs: 120 };   // 1 回目（2 件）は遅く返す
const slowLoad = requestsUi.showRequests('');
await tick();
REQ_FIXTURES.length = 0;
REQ_FIXTURES.push(requestFixture({}));
const fastLoad = requestsUi.showRequests('');                // 2 回目（1 件）が先に返る
await Promise.all([slowLoad, fastLoad]);
await tick();
await tick();
check(el('req-list').children.length === 1,
  `重ねた load は最後の結果だけ描く（監査 B2）: ${el('req-list').children.length} 枚`);

// 7. 注記の描き始め（§8.2-6。P6-2）
//    **4 px 未満のドラッグでは作らない**／それ以上で `POST /annotations` を 1 回だけ叩く
const { mountAnnotations } = await import('../apps/gui/annotations.js');
const detail = new El('div');
const preview = new El('img');
preview.className = 'preview';
preview.clientWidth = 900;
preview.clientHeight = 400;
detail.querySelector = (selector) => (selector === 'img.preview' ? preview : new El('div'));
writes.length = 0;
await mountAnnotations(detail, 'asset-1');
const annoStage = document_.created.find((node) => node.className === 'anno-stage');
check(!!annoStage, '注記の舞台を作る（§5.3）');
// 既定は「見るだけ」。描くには切り替える（`frontend-design.md` §4.3）
el('anno-toggle').dispatch('click');
const annoPosts = () => writes.filter((w) => w.method === 'POST' && w.url.endsWith('/annotations'));

annoStage.dispatch('mousedown', { clientX: 10, clientY: 10, button: 0 });
annoStage.dispatch('mousemove', { clientX: 13, clientY: 12 });
annoStage.dispatch('mouseup', { clientX: 13, clientY: 12, shiftKey: false });
await tick();
await tick();
check(annoPosts().length === 0, `4 px 未満では作らない: ${annoPosts().length} 回`);

annoStage.dispatch('mousedown', { clientX: 10, clientY: 10, button: 0 });
annoStage.dispatch('mousemove', { clientX: 110, clientY: 110 });
annoStage.dispatch('mouseup', { clientX: 110, clientY: 110, shiftKey: false });
await tick();
await tick();
const made = annoPosts();
check(made.length === 1, `4 px 以上なら 1 回だけ叩く: ${made.length} 回`);
check(String(made[0]?.body || '').includes('"shape":"rect"'),
  `形を送る: ${made[0]?.body}`);
const sent = JSON.parse(String(made[0]?.body || '{}'));
check(Math.abs(sent.x - 10 / 900) < 1e-6 && Math.abs(sent.w - 100 / 900) < 1e-6,
  `座標は 0〜1 の割合: ${JSON.stringify(sent)}`);

// 7b. 一覧の番号と画像の印の番号（P6-2 の監査 上位 3）
//     **メモが間にあっても**、一覧の N 番と印の N が一致する（別々に数えるとずれる）
ANNO_ITEMS = [
  { id: 'an1', asset_id: 'asset-1', shape: 'rect', x: 0.1, y: 0.1, w: 0.2, h: 0.2,
    body: '矩形', actor: 'human', created_at: '2026-10-16T00:00:00Z', group_id: null },
  { id: 'an2', asset_id: 'asset-1', shape: null, x: null, y: null, w: null, h: null,
    body: 'メモ', actor: 'human', created_at: '2026-10-16T00:00:01Z', group_id: null },
  { id: 'an3', asset_id: 'asset-1', shape: 'ellipse', x: 0.5, y: 0.5, w: 0.2, h: 0.2,
    body: '楕円', actor: 'human', created_at: '2026-10-16T00:00:02Z', group_id: null },
];
writes.length = 0;
await mountAnnotations(detail, 'asset-1');
// 作り物の DOM は `innerHTML` を**文字列として**持つ（子は解析しない）ので、HTML を読む
const listHtml = String(el('anno-list').innerHTML || '');
const rowBlocks = listHtml.split('<div class="anno-row"').slice(1);
const rowNos = rowBlocks.map((block) => (block.match(/class="anno-no">(\d+)</) || [])[1]);
const rowCrop = rowBlocks.map((block) => block.includes('anno-get'));
// 印は `stage.querySelector('.anno-layer')` に書かれる。作り物の DOM の `querySelector` は
// 子を解決せず**セレクタごとの器**を返すので、その器（`_found`）から読む。
// 舞台は**最後に作った物**（`document.querySelector` が `.pop()` で返すのと揃える）
const stageNode = document_.created.filter((n) => n.className === 'anno-stage').pop();
const layerNode = stageNode?._found?.get('.anno-layer');
const markNos = [...String(layerNode?.innerHTML || '').matchAll(/<span>(\d+)<\/span>/g)]
  .map((m) => m[1]);
check(rowBlocks.length === 3, `注記の一覧は全件: ${rowBlocks.length} 行`);
check(rowNos.join(',') === '1,2,3',
  `一覧の番号は古い順に全件: ${rowNos.join(',')}`);
check(markNos.join(',') === '1,3',
  `印の番号は一覧と同じ（メモは飛ばす）: 印=${markNos.join(',')} / 一覧=${rowNos.join(',')}`);
check(rowCrop[1] === false && rowCrop[0] === true,
  `メモの行には「切り出し」を出さない（押すと 422。監査 C-8）: ${rowCrop.join(',')}`);

// ---- P4-3: タグの画面（設計 p4-design.md §8.2 の 8 件）----
const tagsUi = await import('../apps/gui/tags.js');
const jobsUi = await import('../apps/gui/jobs.js');
const taglistUi = await import('../apps/gui/taglist.js');

const TAG_ITEMS = [
  { name: 'rem_(re:zero)', category: 4, category_name: 'character', score: 0.9931, known: true,
    source: 'wd14', sources: ['wd14'], gloss: null, gloss_edited: null },
  { name: 'long_hair', category: 0, category_name: 'general', score: 0.8812, known: true,
    source: 'wd14', sources: ['wd14'], gloss: '長い髪', gloss_edited: false },
  { name: 'long_hair', category: 0, category_name: 'general', score: null, known: true,
    source: 'png', sources: ['png'], gloss: '長い髪', gloss_edited: false },
  { name: 'first_girl:_black_hair', category: null, category_name: null, score: null, known: false,
    source: 'png', sources: ['png'], gloss: null, gloss_edited: null },
  { name: 'comic', category: null, category_name: null, score: null, known: true,
    source: 'manual', sources: ['manual'], gloss: null, gloss_edited: null },
  { name: '<script>x</script>', category: 0, category_name: 'general', score: null, known: true,
    source: 'manual', sources: ['manual'], gloss: '<script>alert(1)</script>', gloss_edited: true },
];
const TAG_PANEL = { asset_id: 'asset-1', items: TAG_ITEMS,
                    glosses: { long_hair: { ja: '長い髪' } },
                    pending_gloss: ['rem_(re:zero)', 'first_girl:_black_hair', 'comic'],
                    counts: { png: 2, wd14: 2, manual: 2 } };
const TAG_LIST = { items: [
  { tag_id: 12, name: 'long_hair', uses: 3, assets: 3, category: 0, category_name: 'general', known: true, gloss: '長い髪', gloss_edited: false },
  { tag_id: 40, name: 'first_girl:_black_hair', uses: 1, assets: 1, category: null, category_name: null, known: false, gloss: null, gloss_edited: null },
], total: 2, counts: { known: 1, unknown: 1 }, next_cursor: null };

globalThis.fetch = async (url, options) => {
  const u = String(url);
  const method = String(options?.method || 'GET').toUpperCase();
  asked.push(u);
  if (method !== 'GET') writes.push({ url: u, method, body: options?.body });
  const asJson = (body) => ({ ok: true, status: 200,
    text: async () => JSON.stringify(body), json: async () => JSON.parse(JSON.stringify(body)) });
  if (u.includes('/gloss')) {
    return asJson({ translated: [{ tag_id: 12, name: 'long_hair', ja: '長い髪', engine: 'fake' }],
                    skipped: [], untranslated: [], calls: 1, elapsed_ms: 1200 });
  }
  if (u.startsWith('/api/tags?')) return asJson(TAG_LIST);
  if (u.includes('/tags')) return asJson(TAG_PANEL);
  return asJson({ items: [] });
};

const words = tagsUi.mergeWords(TAG_PANEL.items);
const longHair = words.find((w) => w.name === 'long_hair');
check(words.length === 5, `同じ語は 1 行にまとめる: ${words.length} 行`);
check(longHair.sources.join(',') === 'wd14,png', `出所は全部持つ: ${longHair.sources.join(',')}`);
check(longHair.score === 0.8812, `スコアは最大を出す: ${longHair.score}`);

const rowWithGloss = tagsUi.wordRowHtml(longHair);
const rowNoGloss = tagsUi.wordRowHtml(words.find((w) => w.name === 'comic'));
check(rowWithGloss.includes('class="en"') && rowWithGloss.includes('class="ja"'),
  '2 行 1 組で出す（§8.2-1）');
check(!/[()]/.test(rowWithGloss.split('class="ja"')[1].split('</div>')[0]),
  '日本語訳の行に括弧を足さない（§8.2-1）');
check(rowWithGloss.includes('rem_(re:zero)') === false && tagsUi.wordRowHtml(words[0]).includes('rem_(re:zero)'),
  '語そのものの括弧は消さない（点検 A-1）');
check(rowNoGloss.includes('日本語訳はまだありません。') && rowNoGloss.includes('tg-translate'),
  '日本語訳が無ければ文と「訳す」を出す（§8.2-2）');
check(!rowWithGloss.includes('日本語訳はまだありません。'),
  '日本語訳があれば「まだありません」を出さない（§8.2-2）');

const marks = tagsUi.sourceMarks(['png', 'wd14', 'manual']);
check(marks.includes('>PNG<') && marks.includes('>タガー<') && marks.includes('>手<'),
  `出所の印は 3 種（§8.2-3）: ${marks.replace(/</g, '‹')}`);
check(tagsUi.sourceMarks(longHair.sources).split('tg-src ').length - 1 === 2,
  '同じ語の 2 出所は印 2 つ（§8.2-3）');
check(tagsUi.scoreText(longHair).includes('0.881'),
  `スコアはタガーの行だけ 3 桁（§5.1）: ${tagsUi.scoreText(longHair)}`);
check(tagsUi.scoreText(words[3]) === '', 'スコアが無い行には出さない');
const unknownWord = words.find((w) => w.known === false);
check(tagsUi.wordRowHtml(unknownWord).includes('tg-unknown'), '語彙外の印を出す（§0.8）');
check(tagsUi.wordRowHtml(words.find((w) => w.name === 'comic')).includes('tg-remove'),
  '「外す」は manual の行に出す（§8.2-6）');
check(!rowWithGloss.includes('tg-remove'), '「外す」は png / wd14 の行に出さない（§8.2-6）');
const scriptRow = tagsUi.wordRowHtml(words.find((w) => w.name.startsWith('<script>')));
check(!scriptRow.includes('<script>') && scriptRow.includes('&lt;script&gt;'),
  '日本語訳の `<script>` を生のまま出さない（§8.2-7）');

writes.length = 0;
const idMap = await tagsUi.loadIds();
check(idMap.get('long_hair') === 12, `語の id を引ける: ${idMap.get('long_hair')}`);
const translated = await tagsUi.translate(['long_hair']);
const glossPosts = writes.filter((w) => w.url === '/api/tags/gloss');
check(glossPosts.length === 1, `「訳す」は 1 回だけ叩く（§8.2-4）: ${glossPosts.length} 回`);
check(JSON.parse(String(glossPosts[0]?.body || '{}')).tag_ids.join(',') === '12',
  '押した語だけを送る（§8.2-4）');
check(tagsUi.messageOf(translated).includes('1 語を訳しました'), '訳した数を出す');
writes.length = 0;
const nothing = await tagsUi.translate(['unknown_word']);
check(writes.length === 0 && nothing.calls === 0,
  'id が分からない語では模型を回さない（押さなければ 0 回。§8.2-4）');

check(tagsUi.panelHtml(TAG_PANEL).includes('訳す（20 語まで）'), 'まとめて訳すの口を出す');
check(tagsUi.panelHtml(TAG_PANEL).includes('タガーの結果は下書きです。手の破綻までは読めません。'),
  'タガーの限界の 1 行を出す（§5.1）');
check(tagsUi.briefHtml(TAG_PANEL).includes('訳待ち 3 語'),
  `訳待ちの数を出す: ${tagsUi.briefHtml(TAG_PANEL)}`);

const running = { id: 'j1', kind: 'tag', state: 'running', progress: { done: 3, total: 10 },
                  counts: { tagged: 3, skipped: 0, failed: 0 }, note: null, message: null,
                  started_at: new Date(Date.now() - 3000).toISOString(), finished_at: null,
                  items_failed: [{ ref: 'a1', error: '実体がありません' }] };
const jobHtml = jobsUi.jobHtml(running);
check(jobHtml.includes('3 / 10'), 'ジョブの進行を出す（§8.2-8）');
check(jobHtml.includes('残り約'), '残り時間を出す（§8.2-8）');
check(jobHtml.includes('進行中') && jobHtml.includes('中断'), '進行中は中断を出す');
check(jobsUi.jobHtml({ ...running, state: 'cancelled' }).includes('中断'),
  '`cancelled` の印を出す（§8.2-8）');
check(jobsUi.jobHtml(running).includes('実体がありません'), '失敗の理由を出す（§5.3）');
jobsUi.startPoll(10000);
check(jobsUi.pollActive() === true, '見ている間はポーリングする（§5.3）');
jobsUi.stopPoll();
check(jobsUi.pollActive() === false, '離れたらポーリングを止める（§5.3）');

// ---- P4-3 の監査で足した検査（A-1 / B-1 / C-2 / C-3 / C-5）----

check(jobsUi.STATE_LABEL.queued === '待っています',
  `queued は「待っています」（監査 C-5）: ${jobsUi.STATE_LABEL.queued}`);

// B-1: 終わったジョブの 1 枚あたりは **`finished_at` で固定**（時間とともに増えない）
const doneJob = { ...running, state: 'done', progress: { done: 3, total: 3 },
                  started_at: '2026-10-16T02:49:10.050Z', finished_at: '2026-10-16T02:49:11.350Z' };
const paceA = jobsUi.pace(doneJob, Date.parse('2026-10-16T02:50:00Z'));
const paceB = jobsUi.pace(doneJob, Date.parse('2026-10-16T03:10:00Z'));
check(paceA.perItem === paceB.perItem && Math.abs(paceA.perItem - 0.4333) < 0.01,
  `終わったジョブの 1 枚あたりが動く（監査 B-1）: ${paceA.perItem} → ${paceB.perItem}`);

// A-1: 失敗だけのジョブ（付いた 0・飛ばした 0）でも **理由**と「もう一度」と **counts の行**を出す
const failedOnly = { ...doneJob, counts: { tagged: 0, skipped: 0, failed: 1 } };
const failedOnlyHtml = jobsUi.jobHtml(failedOnly);
check(failedOnlyHtml.includes('jb-fail') && failedOnlyHtml.includes('jb-again'),
  '失敗した項目と「もう一度」を出す（監査 A-1）');
check(failedOnlyHtml.includes('失敗 1'), '失敗だけでも counts の行を出す（監査 A-1）');

// C-2: 200 語で打ち切らず、`next_cursor` があれば続きを読める
const savedCursor = TAG_LIST.next_cursor;
TAG_LIST.next_cursor = 'long_hair';
await taglistUi.showTags('?known=1');
check(String(el('tags-list').innerHTML || '').includes('次の 200 語'),
  '続きを読む口を出す（監査 C-2）');
TAG_LIST.next_cursor = savedCursor;

// C-3: **5 秒より短いジョブ**でも「終わりました」を知らせる（`finished_at` が前回の周期以降）
badge.resetBadge();
const justDone = { id: 'short-1', kind: 'tag', state: 'done', progress: { done: 1, total: 1 },
                   counts: { tagged: 1, skipped: 0, failed: 0 }, note: null, message: null,
                   started_at: new Date(Date.now() - 900).toISOString(),
                   finished_at: new Date(Date.now() - 100).toISOString(), items_failed: [] };
badge.renderJobBadge([], Date.now() - 5000);          // 1 回目（基準の時刻を置く）
badge.renderJobBadge([justDone], Date.now());          // 2 回目で「終わった」に気づく
check(el('stat-jobs').textContent.includes('タグ付けが終わりました'),
  `短いジョブでも終わりを知らせる（監査 C-3）: ${el('stat-jobs').textContent}`);
const textAfter = el('stat-jobs').textContent;
badge.renderJobBadge([justDone], Date.now() + 1000);
check(el('stat-jobs').textContent === textAfter, '同じジョブで二度言わない（監査 C-3）');
badge.resetBadge();

// ---- P8-3: 重複の整理（`#/duplicates`）と最近の削除（`#/pending-deletes`）----
//
// **押す検査**を入れる（P7-4 の教訓: 押さないテストは穴を隠す）。押すのは
// `wireDuplicates()` / `wirePending()` が付けた**本物の委譲の聞き手**（作り物の DOM の
// `dispatch` に `target` を渡す）。`fetch` は飲むので**サーバのデータは書かない**。
const dupUi = await import('../apps/gui/duplicates.js');
const pdUi = await import('../apps/gui/pending.js');
// **本物の配線を通す**（`app.js` は読み込まないので、ここで張る。押す検査はこの聞き手を叩く）
dupUi.wireDuplicates();
pdUi.wirePending();

const DUP_ITEM = (id, extra) => ({
  id, sha256: `sha-${id}`, width: 1024, height: 1024, phash: '0f0f', dhash: null,
  first_seen_at: '2026-10-01T00:00:00Z', size: 1_400_000, mtime_ns: 1,
  path: `D:\\lib\\${id}.png`, verdict: null, ...extra,
});
const DUP_NEAR = {
  max_distance: 6, hashed: 91, unhashed: 2, total_groups: 1, total_images: 3,
  excluded_pairs: 1,
  groups: [{
    suggested_id: 'a2', reason: '画素数がいちばん多い', max_distance_within: 3, count: 3,
    items: [DUP_ITEM('a1', { verdict: 'reject' }), DUP_ITEM('a2', { verdict: 'keep' }),
            DUP_ITEM('a3', { path: '<script>alert(1)</script>' })],
  }],
};
const DUP_EXACT = {
  items: [], count: 0,
  message: '完全に同じファイルはありません（同じ内容は 1 行にまとめています）',
};
const PENDING_BODY = {
  items: [
    { id: 'd1', asset_id: 'a1', stage: 3, path: 'd:\\lib\\a1.png',
      display_path: 'D:\\lib\\A1.png', from_path: 'D:\\lib\\A1.png',
      to_path: null, hold_path: 'C:\\data\\pending-delete\\d1\\A1.png', remaining_sec: 192,
      purge_at: '2026-10-18T03:20:00Z', restored_at: null, size: 1_400_000, reason: null,
      actor: 'agent', at: '2026-10-18T03:15:00Z', request_id: 'r1', state: 'pending',
      mine: false, undoable: true, needs_as_copy: false, stuck_reason: null,
      closed_at: null, close_reason: null, closeable: false },
    { id: 'd2', asset_id: 'a2', stage: 3, path: 'd:\\lib\\a2.png',
      display_path: 'D:\\lib\\A2.png', from_path: 'D:\\lib\\A2.png',
      to_path: null, hold_path: 'C:\\data\\pending-delete\\d2\\A2.png', remaining_sec: null,
      purge_at: null, restored_at: null, size: 900_000, reason: null,
      actor: 'human', at: '2026-10-18T02:00:00Z', request_id: 'r2', state: 'stuck',
      mine: true, undoable: true, needs_as_copy: true, stuck_reason: 'target_exists',
      closed_at: null, close_reason: null, closeable: false },
    { id: 'd3', asset_id: 'a3', stage: 3, path: 'd:\\lib\\a3.png',
      display_path: 'D:\\lib\\A3.png', from_path: 'D:\\lib\\A3.png',
      to_path: null, hold_path: null, remaining_sec: 10, purge_at: '2026-10-18T03:20:00Z',
      restored_at: null, size: 10, reason: null, actor: 'human', at: '2026-10-18T03:00:00Z',
      request_id: null, state: 'pending', mine: false, undoable: false, needs_as_copy: false,
      stuck_reason: null, closed_at: null, close_reason: null, closeable: false },
    // **（監査 C-2）段 1 の行**: 前の版は段 3 しか返さなかったので、画面で段 1 を実行しても
    // その行が出ず「戻す」の押し先が無かった（`undo` は元から段 1〜3 に効く）
    { id: 'd4', asset_id: 'a4', stage: 1, path: 'd:\\lib\\a4.png',
      display_path: 'D:\\lib\\A4.png', from_path: 'D:\\lib\\A4.png',
      to_path: null, hold_path: null, remaining_sec: null, purge_at: null,
      restored_at: null, size: 800_000, reason: null, actor: 'human',
      at: '2026-10-18T01:00:00Z', request_id: null, state: 'hidden', mine: true,
      undoable: true, needs_as_copy: false, stuck_reason: null,
      // **（P10）** 段 1 の行は「アプリのゴミ箱へ移す」と「ファイルが無いので片付ける」を出す
      closed_at: null, close_reason: null, closeable: true },
    // **段 2 の行は「取り消せる削除」に出さない**（すぐ下のゴミ箱の欄に出る。二重に出さない）
    { id: 'd5', asset_id: 'a5', stage: 2, path: 'd:\\lib\\a5.png',
      display_path: 'D:\\lib\\A5.png', from_path: 'D:\\lib\\A5.png',
      to_path: 'C:\\data\\trash\\20261018\\A5.png', hold_path: null, remaining_sec: null,
      purge_at: null, restored_at: null, size: 700_000, reason: null, actor: 'human',
      at: '2026-10-18T00:30:00Z', request_id: null, state: 'trashed', mine: true,
      undoable: true, needs_as_copy: false, stuck_reason: null,
      // **（P10）** 段 2 の行は「片付ける」だけ（下のゴミ箱の欄に出る）
      closed_at: null, close_reason: null, closeable: true },
  ],
  count: 5, window_sec: 300, pending: 2,
  found: [{ path: 'C:\\data\\pending-delete\\orphan\\lost.png', size: 12, mtime_ns: 7 }],
  found_count: 1,
};
const TRASH_BODY = {
  days: [{ date: '20261018', count: 1, bytes: 500_000, items: [
    { id: 't1', asset_id: 'a9', stage: 2, path: 'd:\\lib\\a9.png',
      display_path: 'D:\\lib\\A9.png', from_path: 'D:\\lib\\A9.png',
      to_path: 'C:\\data\\trash\\20261018\\A9.png', hold_path: null, remaining_sec: null,
      purge_at: null, restored_at: null, size: 500_000, reason: null, actor: 'human',
      at: '2026-10-18T01:00:00Z', request_id: null, state: 'trashed', mine: true,
      undoable: false, needs_as_copy: false, closed_at: null, close_reason: null,
      closeable: true },
  ] }],
  count: 1, bytes: 500_000,
};
const PREVIEW_BODY = {
  preview_id: 'pv1', stage: 1, count: 2, bytes: 2_900_000, last_copies: 0,
  expires_at: '2026-10-18T03:30:00Z', not_allowed: [], not_allowed_count: 0,
  frees: { stage: 1, bytes: 0, at: null, note: 'カタログから外すだけです（容量は空きません）' },
  items: [
    { asset_id: 'a1', path: 'd:\\lib\\a1.png', display_path: 'D:\\lib\\A1.png', size: 1_400_000,
      mtime_ns: 1 },
    { asset_id: 'a2', path: 'd:\\lib\\a2.png', display_path: 'D:\\lib\\A2.png', size: 1_500_000,
      mtime_ns: 2 },
  ],
};

let DUP_BODY = DUP_NEAR;
let PREVIEW_NOW = PREVIEW_BODY;
let BULK_FAILS = null;                       // 409 の本文を入れると失敗の道を見られる
let BULK_STAGE = 1;                          // 実行の応答の `stage`（P9 の監査 G-5 の検査用）
// **（P11 の監査 A-1）** まとめて削除の `skipped`（理由と本文）。画面が**そのまま出す**かを見る
let BULK_SKIPPED = [];
let UNDO_FAILS = null;                       // **（監査 C-3）** 取り消しの失敗の道
// **（P10）** まとめての応答（1 件の口の失敗の道は `ADVANCE_FAILS` / `CLOSE_FAILS`）
let ADVANCE_NOW = { advanced: [], skipped: [], count: 0, skipped_count: 0, replayed: false };
let CLOSE_NOW = { closed: [{ deletion_id: 'd4', closed: true, files_touched: 0 },
                           { deletion_id: 't1', closed: true, files_touched: 0 }],
                  skipped: [], count: 2, skipped_count: 0, replayed: false, reason: 'missing' };
let ADVANCE_FAILS = null;
let CLOSE_FAILS = null;
let PENDING_NOW = PENDING_BODY;              // 409 の後の読み直しを見るために差し替える
const res = (body, status = 200) => ({
  ok: status >= 200 && status < 300, status,
  text: async () => JSON.stringify(body), json: async () => JSON.parse(JSON.stringify(body)),
});

globalThis.fetch = async (url, options) => {
  const u = String(url);
  const method = String(options?.method || 'GET').toUpperCase();
  asked.push(u);
  if (method !== 'GET') writes.push({ url: u, method, body: options?.body });
  if (u.startsWith('/api/duplicates/near')) return res(DUP_BODY);
  if (u.startsWith('/api/duplicates/exact')) return res(DUP_EXACT);
  if (u.startsWith('/api/duplicates/exclusions')) return res({ items: [], count: 0 });
  if (u.startsWith('/api/duplicates/compute')) return res({ job_id: 'j9', total: 2 }, 202);
  if (u.startsWith('/api/jobs/j9')) return res({ id: 'j9', kind: 'hash', state: 'running',
    progress: { done: 1, total: 2 }, counts: {}, items_failed: [] });
  if (u.startsWith('/api/jobs/')) return res({ id: 'j9', kind: 'hash', state: 'done',
    progress: { done: 2, total: 2 }, counts: {}, items_failed: [] });
  if (u.startsWith('/api/locations/bulk-delete/preview')) return res(PREVIEW_NOW);
  if (u.startsWith('/api/roots')) {
    // **（監査 G-4）** 段 3 の前置きは**実際の置き場**から組む（固定のツール名を埋め込まない）。
    // **（P8-5）** 印の付け外しは `id`（正規化した鍵）を使う（`GET /api/roots` の実物と同じ形）
    return res({ roots: [
      { id: 'd:\\lib', path: 'd:\\lib', display_path: 'D:\\lib', allow_stage3: false,
        added_at: 't' },
      { id: 'c:\\other', path: 'c:\\other', display_path: 'C:\\other', allow_stage3: true,
        added_at: 't' },
    ] });
  }
  if (u.startsWith('/api/locations/bulk-delete')) {
    if (BULK_FAILS) return res(BULK_FAILS, 409);
    return res({ preview_id: 'pv1', stage: BULK_STAGE, deleted: [], skipped: BULK_SKIPPED, count: 2,
                 bytes: 2_900_000, requested: 2, replayed: false });
  }
  if (u.startsWith('/api/pending-deletes') && u.endsWith('/undo')) {
    if (UNDO_FAILS) return res(UNDO_FAILS, 409);          // **（監査 C-3）** 失敗の道
    return res({ deleted: false, restored: true });
  }
  if (u.startsWith('/api/pending-deletes')) return res({ deleted: false, restored: true });
  if (u.startsWith('/api/trash')) return res({ restored: true, deletion_id: 't1' });
  // **（P10）後から段 2 へ進める・実体が無い行を片付ける**。**下の `/api/deletions/` の
  // 総当たりより先に置く**（後に置くと `purged` の本文が返り、本文の検査が素通りする）
  if (u === '/api/deletions/advance') return res({ ...ADVANCE_NOW, kind: 'advance', stage: 2 });
  if (u === '/api/deletions/close') return res(CLOSE_NOW);
  if (/^\/api\/deletions\/[^/]+\/advance$/.test(u)) {
    if (ADVANCE_FAILS) return res(ADVANCE_FAILS.body, ADVANCE_FAILS.status);
    return res({ deletion_id: 'd4', stage: 2, asset_id: 'a4', advanced: true, replayed: false,
                 to_path: 'C:\\data\\trash\\20261018\\A4.png' });
  }
  if (/^\/api\/deletions\/[^/]+\/close$/.test(u)) {
    if (CLOSE_FAILS) return res(CLOSE_FAILS.body, CLOSE_FAILS.status);
    return res({ deletion_id: 'd4', closed: true, closed_at: '2026-10-18T04:00:00Z',
                 close_reason: 'missing', stage: 1, files_touched: 0, replayed: false });
  }
  if (u.startsWith('/api/deletions/')) return res({ deletion_id: 'd2', purged: true });
  if (u.startsWith('/api/groups')) return res({ id: 'grp-1', kind: 'duplicates' });
  if (u.startsWith('/api/pending') || u.startsWith('/api/trash')) return res(PENDING_BODY);
  return res(PENDING_BODY);
};
// `GET /api/pending-deletes` と `GET /api/trash` は本文が違う（POST の宛先と字が重なる）
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, options) => {
  const u = String(url);
  const method = String(options?.method || 'GET').toUpperCase();
  if (method === 'GET' && u.startsWith('/api/pending-deletes')) {
    asked.push(u);
    return res(PENDING_NOW);
  }
  if (method === 'GET' && u.startsWith('/api/trash')) {
    asked.push(u);
    return res(TRASH_BODY);
  }
  return realFetch(url, options);
};

/** 作り物の「押された的」（`closest` と `dataset` だけを持つ）。 */
function hitOf(selector, data = {}, extra = {}) {
  const node = { dataset: data, ...extra };
  return { ...node, closest: (sel) => (sel === selector ? node : null) };
}

/** **描いた HTML の中のボタン**を 1 つ見る（`disabled` かどうか）。
 *
 * 本物のブラウザは **`disabled` のボタンに `click` を届けない**（これが「二度押しでも 1 回」の
 * 仕組み。P8-5 の監査 C-1）。この作り物の DOM はそこまで知らないので、**描いた HTML から見て**
 * 「人の二度押しの 2 回目が届くか」を決める（`gui_layout` の本物の Chrome が最終の確認）。
 */
function buttonIn(containerId, className) {
  const html = String(el(containerId).innerHTML || '');
  const tag = new RegExp(`<button class="${className}"[^>]*>`).exec(html);
  if (!tag) return { seen: false, disabled: true };
  return { seen: true, disabled: /(^|\s)disabled(\s|>)/.test(tag[0]) };
}

/** `GET /api/pending-deletes` に**人だと名乗るヘッダ**が付いているか（P8-3 の穴）。 */
let pendingGetHeaders = null;
const asHumanFetch = globalThis.fetch;
globalThis.fetch = async (url, options) => {
  const u = String(url);
  const method = String(options?.method || 'GET').toUpperCase();
  if (method === 'GET' && u.startsWith('/api/pending-deletes')) {
    pendingGetHeaders = options?.headers || null;
  }
  return asHumanFetch(url, options);
};

// ---- P8-5: 走査中（`GET /api/scan`）・バックアップ（`GET /api/backup`）・設定 ----
//
// `pending.js` は段 3 の出し分けのために**選んだ枚のパス**（`GET /api/assets`）を引き、
// 走査中の 1 行のために `GET /api/scan` を見る。設定の画面は `GET /api/backup` と
// `GET /api/roots` を読む。**押す検査**は本物の委譲の聞き手を叩く（`fetch` は飲む）。
let ASSET_PATHS = { a1: 'C:\\other\\A1.png', a2: 'C:\\other\\A2.png' };  // 既定は**印のある**置き場
let ASSETS_FAILS = false;
// **（P8-5 の監査 D-5）一覧の上限を超える置き場**の道: 一覧に無い枚は `/api/assets/<id>` で引く。
// `null` なら 404（引けない）＝安全側（段 3 を出さない）
let SINGLE_ASSET = null;
let SCAN_NOW = { scanning: false, started_at: null, elapsed_sec: null, scans: 1,
                 note: '走査していません。' };
const BACKUP_BODY = {
  backup_dir: 'C:\\work\\image-reviwer\\.backup\\daily',
  backup_dir_source: 'settings',
  default_backup_dir: 'C:\\Users\\yukse\\image-reviewer-backups',
  keep: 7, interval_sec: 30, count: 3, today_done: true,
  next_run_at: '2026-10-18T15:00:00Z',
  next_run_note: '今日の分は取りました（次は日付が変わったとき）',
  // **P8-4 の再確認 B-1' の実際の形**（実機の 8790 が返していた物）
  last_error: "[WinError 5] アクセスが拒否されました: 'C:\\Users\\yukse\\image-reviewer-backups'",
  last_error_at: '2026-10-17T23:38:25Z', read_only: false, running: true, ticks: 5,
  // **サーバの並びと同じ**（名前の降順。`pre-topup-*` は `p` なので数字より先に来る）
  snapshots: [
    { name: 'pre-topup-20261018-084455', kind: 'pre-topup', created_at: '2026-10-18T08:44:55Z',
      bytes: 900_000, ok: true },
    { name: '20261018-121500', kind: 'manual', created_at: '2026-10-18T03:15:00Z',
      bytes: 1_500_000, ok: true },
    { name: '20261018', kind: 'daily', created_at: '2026-10-18T00:00:00Z', bytes: 1_400_000,
      ok: true },
  ],
};
let BACKUP_NOW = BACKUP_BODY;
let BACKUP_STATUS = 200;
// **（P8-5 の監査 C-3・D-3）読み取り専用の理由と案内**（`GET /api/health/db?full=0`）。
// **語彙は API の物**（`malformed` / `unreadable` / `unopenable` / `version_ahead` /
// `pre_migrate_backup_failed`）を使う（`pre_topup_backup_failed` / `ahead` は API に無い）
let HEALTH_BODY = { mode: 'ok', reason: 'ok', read_only: false, guidance: null };
let SETTINGS_FAILS = null;             // 422 の本文を入れると失敗の道を見られる
let settingsWrites = [];               // 人だけの口に**名乗っているか**を見る

const beforeSettings = globalThis.fetch;
globalThis.fetch = async (url, options) => {
  const u = String(url);
  const method = String(options?.method || 'GET').toUpperCase();
  // **この包みが自分で答える要求だけ**を `writes` に写す（下の包みと二重に数えない）。
  // 写さないと「1 回だけ叩く」の検査が 0 回に見える
  const mine = u.startsWith('/api/assets') || u.startsWith('/api/scan')
    || u.startsWith('/api/backup') || u.startsWith('/api/settings')
    || u.includes('/allow-stage3');
  if (mine && method !== 'GET') writes.push({ url: u, method, body: options?.body });
  if (method !== 'GET' && (u.startsWith('/api/backup') || u.startsWith('/api/settings')
      || u.includes('/allow-stage3'))) {
    settingsWrites.push({ url: u, method, headers: options?.headers || null,
                          body: options?.body });
  }
  // **（P8-5 の監査 D-5）1 枚の口**（`/api/assets/<id>`）。**一覧より先に見る**（前方一致が被る）
  if (u.startsWith('/api/assets/')) {
    asked.push(u);
    const id = decodeURIComponent(u.slice('/api/assets/'.length).split('?')[0]);
    if (!SINGLE_ASSET) return res({ detail: 'asset not found' }, 404);
    // **本物の形**（`store.asset` は `locations` を返す。`path` は無い）
    return res({ id, sha256: 'x', size: 1, locations: [
      { path: SINGLE_ASSET.path, display_path: SINGLE_ASSET.path, is_primary: 1, missing_at: null },
    ] });
  }
  if (u.startsWith('/api/assets')) {
    asked.push(u);
    if (ASSETS_FAILS) return res({ detail: '読めません' }, 503);
    // **本物の形**（`GET /api/assets` は `total`＝生きた枚を返す。P9 の監査 C-2 で足した）
    return res({ items: Object.entries(ASSET_PATHS).map(([id, path]) => ({ id, path })),
                 total: Object.keys(ASSET_PATHS).length, next_cursor: null });
  }
  if (u.startsWith('/api/health/db')) {
    asked.push(u);
    return res(HEALTH_BODY);
  }
  if (u.startsWith('/api/scan')) {
    asked.push(u);
    return res(SCAN_NOW);
  }
  if (u.startsWith('/api/backup')) {
    asked.push(u);
    if (BACKUP_STATUS === 503) {
      return res({ detail: 'DB が壊れているので書き込めません', code: 'read_only',
                   details: { mode: 'read_only', reason: 'malformed' },
                   guidance: 'image-reviewer restore <バックアップのフォルダ> で戻せます' }, 503);
    }
    if (method === 'POST') {
      // **本物の応答の形**（`snapshot()` は `count` ではなく `dir` / `counts` / `pruned` を返す）
      return res({ dir: `${BACKUP_NOW.backup_dir}\\20261018-121500`, name: '20261018-121500',
                   manual: true, pruned: [], counts: { assets: 263, decisions: 3 },
                   files: 5, backup_dir: BACKUP_NOW.backup_dir, already: false });
    }
    return res(BACKUP_NOW);
  }
  if (u.startsWith('/api/settings')) {
    asked.push(u);
    if (SETTINGS_FAILS) return res(SETTINGS_FAILS, 422);
    return res({ backup_dir: JSON.parse(String(options?.body || '{}')).backup_dir,
                 backup_dir_source: 'settings' });
  }
  if (u.includes('/allow-stage3')) {
    asked.push(u);
    return res({ id: 'd:\\lib', path: 'D:\\lib', display_path: 'D:\\lib',
                 allow_stage3: JSON.parse(String(options?.body || '{}')).allow === true });
  }
  return beforeSettings(url, options);
};

const dupIds = () => dupUi.pickedIds().join(',');

// 1. しきい値の切り替えと既定（Q3）
check(dupUi.THRESHOLDS.join(',') === '3,6,10', `しきい値は 3 つ: ${dupUi.THRESHOLDS}`);
check(dupUi.query('?max=6').max === 6 && dupUi.query('?max=10').max === 10,
  'しきい値を URL から読む');
check(dupUi.query('?max=7').max === 6 && dupUi.query('').max === 6,
  '語彙の外と無指定は既定の 6（Q3）');

// 2. 群の描画（サムネイル・距離・おすすめ・寸法とサイズと日時）
writes.length = 0;
await dupUi.showDuplicates('?max=6');
const dupHtml = String(el('dup-list').innerHTML || '');
check(dupHtml.includes('同じ絵が 3 枚'), '群の枚数を出す');
check(dupHtml.includes('距離 3'), '群の中の最大距離を出す（点検 C3）');
check(dupHtml.includes('おすすめ: 2 番') && dupHtml.includes('画素数がいちばん多い'),
  `おすすめと理由を出す（Q4）: ${(dupHtml.match(/おすすめ[^<]*/) || [])[0]}`);
check(dupHtml.includes('1024 × 1024') && dupHtml.includes('1.3 MB') && dupHtml.includes('2026-10-01'),
  '寸法・サイズ・日時を出す');
check(dupHtml.includes('/api/assets/a1/thumb?size=256'), 'サムネイルを出す');
check(dupHtml.includes('完全重複はありません。同じ中身が 2 か所以上にあるものです。'),
  '完全重複が 0 のときの 1 行を出す（§0.4・§5）');
check(dupHtml.includes('まだ計算していない画像が 2 枚あります。') && dupHtml.includes('計算する'),
  `未計算の枚と「計算する」を出す: ${(dupHtml.match(/まだ計算[^<]*/) || [])[0]}`);
// **（監査 G-4）固定の数を文言に埋めない**（別の置き場では嘘になる）
check(!/263 枚で 2\.6 秒/.test(dupHtml) && dupHtml.includes('絵を読んで指紋を作ります'),
  `秒数と枚数を埋め込まない（監査 G-4）: ${(dupHtml.match(/絵を読んで[^<]*/) || [])[0]}`);
check(dupHtml.includes('&lt;script&gt;alert(1)&lt;/script&gt;') && !dupHtml.includes('<script>alert'),
  'パスの `<script>` を生のまま出さない');
// **（利用者の要望）ラジオに「残す」を画面に見える語で出す**（`title` だけにしない。§6 の文言表）。
// **タグの中の `title` ではなく、ラベルの中の要素**であることを見る（見えないと意味が無い）
check(/<label class="dup-keep" title="[^"]*"><input type="radio"[^>]*><span class="dup-keep-word">残す<\/span><\/label>/.test(dupHtml),
  'ラジオのラベルに「残す」を出す（title だけにしない）');
check((dupHtml.match(/<span class="dup-keep-word">残す<\/span>/g) || []).length === 3,
  `「残す」を行の数（3 枚）だけ出す: ${(dupHtml.match(/dup-keep-word/g) || []).length} 個`);
// **（P8-3 の取り落とし調査）**「別物として確定」で隠れている組の数を出す。出さないと
// **群が 1 つ足りないのが帯の取りこぼしに見える**（実データで実際にそう見えた）
check(dupHtml.includes('別物として確定した 1 組は隠しています。'),
  `隠れている組の数を出す: ${(dupHtml.match(/別物として確定[^<]*/) || [])[0]}`);
DUP_BODY = { ...DUP_NEAR, excluded_pairs: 0 };
await dupUi.showDuplicates('?max=6');
check(!String(el('dup-list').innerHTML || '').includes('隠しています'),
  '隠れている組が 0 なら出さない');
DUP_BODY = DUP_NEAR;
await dupUi.showDuplicates('?max=6');
// **（監査の注意）既定は 1 枚も選ばない。** この画面の「削除へ回す」は**壊す操作**への入口なので、
// 開いた直後に全部へ印が付いていると、押し間違いが全群の削除に化ける（複製で 56 枚が掛かった）
check(dupIds() === '', `既定は 1 枚も選ばない（監査の注意）: ${dupIds()}`);
check(String(el('dup-bar').innerHTML || '').includes('選択 0 枚')
  && String(el('dup-bar').innerHTML || '').includes('全部選ぶ'),
  '「選択 0 枚」と「全部選ぶ」を出す');
check(/dup-delete[^>]*disabled/.test(String(el('dup-bar').innerHTML || '')),
  '1 枚も選んでいなければ「削除へ回す」を押せない');

// 2b. **押す検査**: 「全部選ぶ」→ 全部に印が付く（**人が押したときだけ**）
el('dup-bar').dispatch('click', { target: hitOf('.dup-all', {}) });
check(dupIds() === 'a1,a2,a3', `「全部選ぶ」で全部に印: ${dupIds()}`);
check(String(el('dup-bar').innerHTML || '').includes('全部外す'),
  '押したら「全部外す」に変わる（同じ 1 つのボタン）');
el('dup-bar').dispatch('click', { target: hitOf('.dup-all', {}) });
check(dupIds() === '', `「全部外す」で 0 枚に戻る: ${dupIds()}`);
el('dup-bar').dispatch('click', { target: hitOf('.dup-all', {}) });   // 以降の検査のために全部選ぶ

// 3. **押す検査**: 印を外して「別物として確定」→ 除外の口が 1 回だけ
const list_ = el('dup-list');
list_.dispatch('change', { target: hitOf('.dup-on-box', { id: 'a3', g: '0' }, { checked: false }) });
check(dupIds() === 'a1,a2', `外した枚は選択から落ちる: ${dupIds()}`);
writes.length = 0;
list_.dispatch('click', { target: hitOf('.dup-exclude', { g: '0' }) });
await tick();
await tick();
const exPosts = writes.filter((w) => w.url === '/api/duplicates/exclude');
check(exPosts.length === 1, `「別物として確定」は 1 回だけ叩く: ${exPosts.length} 回`);
check(JSON.parse(String(exPosts[0]?.body || '{}')).a_id === 'a1',
  `選んだ 2 枚を送る: ${exPosts[0]?.body}`);
check(String(el('dup-headline').innerHTML || '').includes('別物として覚えました'),
  '確定したことを知らせる');

// 4. **押す検査**: 「まとまりにする」→ `kind='duplicates'` の口が 1 回だけ・知らせと行き先
// （除外の POST の後は読み直しで**選択が空に戻る**＝既定の「何も選ばない」に戻る。だから選び直す）
for (const id of ['a1', 'a2', 'a3']) {
  list_.dispatch('change', { target: hitOf('.dup-on-box', { id, g: '0' }, { checked: true }) });
}
check(dupIds() === 'a1,a2,a3', `選び直せる: ${dupIds()}`);
writes.length = 0;
list_.dispatch('click', { target: hitOf('.dup-make', { g: '0' }) });
await tick();
await tick();
const mkPosts = writes.filter((w) => w.url === '/api/groups');
check(mkPosts.length === 1, `「まとまりにする」は 1 回だけ叩く: ${mkPosts.length} 回`);
const mkBody = JSON.parse(String(mkPosts[0]?.body || '{}'));
check(mkBody.kind === 'duplicates' && mkBody.policy === 'pick_one',
  `まとまりの種類は duplicates / pick_one: ${JSON.stringify(mkBody.kind)} ${mkBody.policy}`);
check(mkBody.asset_ids.join(',') === 'a1,a2,a3', `群の枚を全部入れる: ${mkBody.asset_ids}`);
check(String(el('dup-headline').innerHTML || '').includes('#/group/grp-1'),
  '作ったまとまりへ行ける（まとまりレビュー）');

// 5. **押す検査**: 「削除へ回す」→ 最近の削除へ**渡すだけ**（ここでは消さない）
// **（利用者の要望）「残す」に付けた 1 枚（a2）は、チェックが付いていても渡さない**（二重の守り）。
// 下部バーの枚数も**渡す枚**で数える（「これから何が起きるか」を言う。§6.1 の規則 4）
check(String(el('dup-bar').innerHTML || '').includes('選んだ 2 枚を削除する…')
  && String(el('dup-bar').innerHTML || '').includes('残す 1 枚は渡しません。'),
  `チェック 3 枚でも「残す」を外した 2 枚で数える: `
  + `${(String(el('dup-bar').innerHTML || '').match(/選んだ[^<]*/) || [])[0]}`);
writes.length = 0;
el('dup-bar').dispatch('click', { target: hitOf('.dup-delete', {}) });
check(writes.length === 0, `重複の画面では消さない（POST ${writes.length} 回）`);
check(location.hash === '#/pending-deletes?ids=a1,a3',
  `選んだ枚を削除の確認へ渡す（「残す」の a2 は渡さない）: ${location.hash}`);
check(!location.hash.includes('a2'), '「残す 1 枚」を行き先に入れない（二重の守り）');

// 5b. **（監査 C-1）削除の入口が 3 つとも同じ行き先を使う**（組み立ては `pending.js` の 1 か所）。
//     押さないテストは穴を隠すので、**下部バーの入口とまとまりの入口も押す**
check(pdUi.deleteHref(['a1', 'a2']) === '#/pending-deletes?ids=a1,a2'
  && pdUi.deleteHref([]) === '', `行き先の組み立て: ${pdUi.deleteHref(['a1', 'a2'])}`);
const barDel = el('btn-delete');
pdUi.wireDeleteEntry(barDel, () => ['a1', 'a2']);
pdUi.renderDeleteEntry(barDel, 0);
check(barDel.textContent === '選んだ画像を削除する…' && barDel.disabled === true,
  `1 枚も選んでいなければ押せない: ${barDel.textContent}`);
pdUi.renderDeleteEntry(barDel, 2);
check(barDel.textContent === '選んだ 2 枚を削除する…' && barDel.disabled === false,
  `選んだ枚を文言に出す（下部バー）: ${barDel.textContent}`);
location.hash = '';
barDel.dispatch('click');
check(location.hash === '#/pending-deletes?ids=a1,a2',
  `下部バーの入口が削除の確認へ渡す（監査 C-1）: ${location.hash}`);
location.hash = '';

// 5c. **押す検査（利用者の要望）**: 群ごとの「残す 1 枚以外を削除する…」→
//     **その群の「残す」以外の全部**を `#/pending-deletes?ids=` へ渡す（**`keep` は入れない**）。
//     まず**ラジオで残す 1 枚を変えて**から押す（おすすめの a2 ではなく a1 を残す）
await dupUi.showDuplicates('?max=6');                 // 既定に戻す（keep はおすすめの a2）
check(dupUi.keepOutIds(0).join(',') === 'a1,a3',
  `既定ではおすすめ以外を組む: ${dupUi.keepOutIds(0)}`);
check(buttonIn('dup-list', 'dup-keep-out').disabled === false, '2 枚以上ある群では押せる');
el('dup-list').dispatch('change',
  { target: hitOf('.dup-keep-box', { id: 'a1', g: '0' }, { checked: true }) });
check(dupUi.keepOutIds(0).join(',') === 'a2,a3',
  `ラジオで変えた「残す」以外を組む（人が選び直せる）: ${dupUi.keepOutIds(0)}`);
writes.length = 0;
location.hash = '';
el('dup-list').dispatch('click', { target: hitOf('.dup-keep-out', { g: '0' }) });
check(writes.length === 0, `群ごとのボタンでも消さない（POST ${writes.length} 回）`);
check(location.hash === '#/pending-deletes?ids=a2,a3',
  `群ごとのボタンは「残す」以外を削除の確認へ渡す: ${location.hash}`);
check(!location.hash.includes('a1'), 'ラジオで選んだ「残す 1 枚」を渡さない');

// 5d. **（利用者の要望）1 枚しかない群では押せない**（「残す」以外が 0 枚）。
//     理由は `title` に出す（人が次の手を選べるように）。押しても道は変わらない
DUP_BODY = { ...DUP_NEAR, total_groups: 1, total_images: 1, excluded_pairs: 0,
             groups: [{ suggested_id: 'b1', reason: '1 枚だけ', max_distance_within: 0, count: 1,
                        items: [DUP_ITEM('b1', {})] }] };
await dupUi.showDuplicates('?max=6');
const oneBtn = buttonIn('dup-list', 'dup-keep-out');
check(oneBtn.seen && oneBtn.disabled,
  `1 枚の群では「残す 1 枚以外を削除する…」を押せない（見えた=${oneBtn.seen}）`);
check(String(el('dup-list').innerHTML || '').includes('この群は 1 枚だけです。削除する枚がありません。'),
  `押せない理由を title に出す: ${(String(el('dup-list').innerHTML || '')
    .match(/title="この群[^"]*"/) || [])[0]}`);
check(dupUi.keepOutIds(0).length === 0, '1 枚の群では渡す枚が 0');
location.hash = '';
el('dup-list').dispatch('click', { target: hitOf('.dup-keep-out', { g: '0' }) });
check(location.hash === '', `押せない群では道が変わらない: ${JSON.stringify(location.hash)}`);
DUP_BODY = DUP_NEAR;
await dupUi.showDuplicates('?max=6');                 // 以降の検査のために戻す

// 6. **押す検査**: 「計算する」→ 202 の口が 1 回だけ・進行が出る
writes.length = 0;
el('dup-list').dispatch('click', { target: hitOf('.dup-do-compute', {}) });
await tick();
await tick();
const cpPosts = writes.filter((w) => w.url === '/api/duplicates/compute');
check(cpPosts.length === 1, `「計算する」は 1 回だけ叩く: ${cpPosts.length} 回`);
check(String(el('dup-list').innerHTML || '').includes('計算中 0 / 2'),
  `進行を出す（背景ジョブ）: ${(String(el('dup-list').innerHTML).match(/計算中[^<]*/) || [])[0]}`);
check(dupUi.pollActive() === true, '見ている間は進行を見る');
dupUi.stopPoll();
check(dupUi.pollActive() === false, '離れたら止める');

// 7. 最近の削除: 残り時間の書き方と 3 段階の進行（§4.6・§11）
check(pdUi.fmtRemain(192) === '3:12', `あと 3:12 の形: ${pdUi.fmtRemain(192)}`);
check(pdUi.fmtRemain(0) === '0:00' && pdUi.fmtRemain(-5) === '0:00', '負は 0 に丸める');
const stepped = pdUi.stepRemain([{ remaining_sec: 5 }, { remaining_sec: null }]);
check(stepped[0].remaining_sec === 4 && stepped[1].remaining_sec === null,
  '毎秒の見た目だけを減らす（`GET` は書かない）');
const strip3 = pdUi.stageStrip(3);
check(strip3.includes('1 カタログから外す') && strip3.includes('2 アプリのゴミ箱') && strip3.includes('3 ファイルを消す'),
  `3 段階の進行を出す: ${strip3.replace(/</g, '‹')}`);
check(/class="pd-step on">3 ファイルを消す/.test(strip3), 'いまの段に印を付ける');
check(!/class="pd-step on">1 印/.test(strip3), '前の段には印を付けない');

// 8. 行の描画（誰が・残り時間・戻せない理由）
pendingGetHeaders = null;
await pdUi.showPending('?ids=');
check(String(pendingGetHeaders?.['X-Image-Reviewer-Actor'] || '') === 'human',
  `GET でも人だと名乗る（名乗らないと undoable が false で「取り消す」が消える）: `
  + `${JSON.stringify(pendingGetHeaders)}`);
check(pdUi.fmtWhen('2026-10-18T03:15:00Z') !== '—' && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(
  pdUi.fmtWhen('2026-10-18T03:15:00Z')), `現地の時刻で出す: ${pdUi.fmtWhen('2026-10-18T03:15:00Z')}`);
check(!/pd-step on/.test(pdUi.legendHtml()), '凡例の段には印を付けない（行と見分ける）');
const runHtml = String(el('pd-running').innerHTML || '');
check(runHtml.includes('あと 3:12'), '残り時間を出す');
check(runHtml.includes('エージェント') && runHtml.includes('、人、'),
  '誰が消したかを語で出す（Q2 の帰結 b）');
// **（監査 G-3）戻せなかった理由を 4 通りに分ける**（前の版は `target_exists` でも
// 「保留していたファイルが見つかりません」と出ていた）
check(runHtml.includes('戻せませんでした。元の場所に既にファイルがあります。'),
  `stuck の行に理由を出す（監査 G-3）: ${(runHtml.match(/戻せませんでした[^<]*/) || [])[0]}`);
check(pdUi.stuckText('move_failed').includes('元の場所へ移せませんでした')
  && pdUi.stuckText('different').includes('元の場所には別のファイルがあります')
  && pdUi.stuckText('missing').includes('一時置き場に移したファイルが見つかりません')
  && pdUi.stuckText(null).includes('一時置き場に移したファイルが見つかりません'),
  '理由ごとに 1 行（古い行は missing と同じ）');
check(runHtml.includes('別名で戻す'), 'stuck には「別名で戻す」を出す');
// **（監査 C-2）段 1 の行も出て、そこから戻せる**（`deletion_log` の 1 行 = 画面の 1 行）。
// 段 3 の窓 2 枚（d1・d2）＋段 1 の 1 枚（d4）＝ 3 つ。**段 2（d5）はここに出さない**
check(runHtml.includes('D:\\lib\\A4.png') && runHtml.includes('>戻す<'),
  `段 1 の行を出して「戻す」を押せるようにする（監査 C-2）: ${(runHtml.match(/>戻す</g) || []).length} 個`);
check((runHtml.match(/pd-undo/g) || []).length === 3,
  `戻せる行にだけ出す（他人の分も人は戻せる。e-2。段 1 を含む）: ${(runHtml.match(/pd-undo/g) || []).length}`);
check(!runHtml.includes('D:\\lib\\A5.png'),
  '段 2 の行は「取り消せる削除」に二重に出さない（すぐ下のゴミ箱の欄に出る）');
check(pdUi.rowHtml(PENDING_BODY.items[3]).includes('>戻す<')
  && pdUi.rowHtml(PENDING_BODY.items[0]).includes('>取り消す<'),
  '語を段で分ける（段 1・2 は「戻す」、段 3 の窓は「取り消す」）');
check(runHtml.includes('戻せる削除はありません。') === false, '0 件の文は出さない');
check(String(el('pd-found').innerHTML || '').includes('台帳に無いファイルが一時置き場に 1 件あります。消しません。'),
  '拾い物を出して「消しません」と言う（G-4）');
check(String(el('pd-trash').innerHTML || '').includes('20261018')
  && String(el('pd-trash').innerHTML).includes('戻す'), 'ゴミ箱を日付ごとに出す（Q7）');

// 9. **押す検査**: 「取り消す」→ `undo` が 1 回だけ
writes.length = 0;
el('pd-running').dispatch('click', { target: hitOf('.pd-undo', { id: 'd1' }) });
await tick();
await tick();
const undoPosts = writes.filter((w) => w.url === '/api/pending-deletes/d1/undo');
check(undoPosts.length === 1, `「取り消す」は 1 回だけ叩く: ${undoPosts.length} 回`);
check(JSON.parse(String(undoPosts[0]?.body || '{}')).as_copy === false,
  '普通の取り消しは as_copy を付けない');

// 9b. **押す検査**: 段 1 の行の「戻す」→ 同じ `undo` の口（監査 C-2）
writes.length = 0;
el('pd-running').dispatch('click', { target: hitOf('.pd-undo', { id: 'd4' }) });
await tick();
await tick();
check(writes.filter((w) => w.url === '/api/pending-deletes/d4/undo').length === 1,
  '段 1 の行の「戻す」も 1 回だけ叩く（監査 C-2）');

// 10. **押す検査**: 「別名で戻す」は as_copy: true（人だけ）
writes.length = 0;
el('pd-running').dispatch('click', { target: hitOf('.pd-ascopy', { id: 'd2' }) });
await tick();
await tick();
const copyPosts = writes.filter((w) => w.url === '/api/pending-deletes/d2/undo');
check(copyPosts.length === 1 && JSON.parse(String(copyPosts[0]?.body || '{}')).as_copy === true,
  `「別名で戻す」は as_copy を付ける: ${copyPosts[0]?.body}`);

// 10b. **（監査 C-3）409 の直後に「別名で戻す」が出る**（失敗の道でも `load()` する）。
//      前の版は `render()` だけだったので、文は「『別名で戻す』で戻せます」と言うのに
//      **ボタンが 1 つも無く、再読込するまで押せなかった**
UNDO_FAILS = { detail: '元の場所に既にファイルがあります', code: 'target_exists' };
PENDING_NOW = { ...PENDING_BODY, items: PENDING_BODY.items.map((it) => (it.id === 'd1'
  ? { ...it, state: 'stuck', remaining_sec: null, purge_at: null, needs_as_copy: true,
      stuck_reason: 'target_exists' }
  : it)) };
writes.length = 0;
el('pd-running').dispatch('click', { target: hitOf('.pd-undo', { id: 'd1' }) });
await tick();
await tick();
await tick();
const c3Html = String(el('pd-running').innerHTML || '');
check(writes.filter((w) => w.url === '/api/pending-deletes/d1/undo').length === 1,
  '失敗した取り消しも 1 回だけ叩く');
check(c3Html.includes('別名で戻す'),
  `409 の直後に「別名で戻す」を出す（監査 C-3。読み直していない）: ${(c3Html.match(/pd-ascopy/g) || []).length} 個`);
check(c3Html.includes('戻せませんでした。元の場所に既にファイルがあります。'),
  '読み直した行の理由も出す（監査 G-3）');
check(String(el('pd-msg').innerHTML || '').includes('元の場所に既にファイルがあります'),
  `失敗の理由を 1 行で知らせる: ${String(el('pd-msg').innerHTML || '').slice(0, 80)}`);
UNDO_FAILS = null;
PENDING_NOW = PENDING_BODY;

// 11. **押す検査**: 「いま消す」は確認を 1 回挟む（取り消したら叩かない）
writes.length = 0;
globalThis.confirm = () => false;
el('pd-running').dispatch('click', { target: hitOf('.pd-purge', { id: 'd2' }) });
await tick();
check(writes.filter((w) => w.url.includes('/purge')).length === 0,
  '確認でやめたら消さない（押し間違いを防ぐ）');
globalThis.confirm = () => true;
el('pd-running').dispatch('click', { target: hitOf('.pd-purge', { id: 'd2' }) });
await tick();
await tick();
const purgePosts = writes.filter((w) => w.url === '/api/deletions/d2/purge');
check(purgePosts.length === 1, `「いま消す」は 1 回だけ叩く: ${purgePosts.length} 回`);
check(JSON.parse(String(purgePosts[0]?.body || '{}')).confirm === true, 'confirm: true を送る');

// 12. **押す検査**: ゴミ箱の「戻す」→ `trash/restore` が 1 回だけ
writes.length = 0;
el('pd-trash').dispatch('click', { target: hitOf('.pd-trash-restore', { id: 't1' }) });
await tick();
await tick();
const trPosts = writes.filter((w) => w.url === '/api/trash/restore');
check(trPosts.length === 1 && JSON.parse(String(trPosts[0]?.body || '{}')).deletion_id === 't1',
  `ゴミ箱の「戻す」は 1 回だけ叩く: ${trPosts.length} 回`);

// 12b. **（P10。利用者の要望）後から段 2 へ進める・実体が無い行を片付ける**
//
// 段 1 の行が行き止まりだったのを塞ぐ口（`docs/deletions-advance.md`）。**押す検査**を入れる
// （`wirePending()` の本物の聞き手を叩く）。**確認を挟むのは片付けだけ**（戻せないため）。
await pdUi.showPending('?ids=');
const p10Rows = String(el('pd-running').innerHTML || '');
check(p10Rows.includes(pdUi.ADVANCE_LABEL), `段 1 の行に「${pdUi.ADVANCE_LABEL}」を出す`);
check((p10Rows.match(/class="pd-advance"/g) || []).length === 1,
  `段 1 の行だけに出す（段 3 の行には出さない）: ${(p10Rows.match(/class="pd-advance"/g) || []).length} 個`);
check((p10Rows.match(/class="pd-close"/g) || []).length === 1,
  `片付けは段 1 の行に出す: ${(p10Rows.match(/class="pd-close"/g) || []).length} 個`);
check(pdUi.rowHtml(PENDING_BODY.items[0]).includes('pd-advance') === false
  && pdUi.rowHtml(PENDING_BODY.items[0]).includes('pd-close') === false,
  '段 3 の行には新しいボタンを出さない（今までどおり）');
check(pdUi.rowHtml(PENDING_BODY.items[4]).includes('pd-close') === true,
  '段 2 の行には「片付ける」だけを出す');
check(String(el('pd-trash').innerHTML || '').includes('class="pd-close"'),
  'ゴミ箱の欄（段 2）にも「片付ける」を出す');
check(/title="[^"]*ファイルは消しません/.test(p10Rows), '片付けのボタンに「ファイルは消しません」を添える');
check(p10Rows.includes('class="pd-pick"'), 'まとめてのチェックを出す');
check(String(el('pd-bulk').innerHTML || '').includes('全部選ぶ')
  && String(el('pd-bulk').innerHTML).includes('選んだ行をまとめて片付ける'),
  `選ぶ前は 0 件と書かない（押せない）: ${(String(el('pd-bulk').innerHTML || '')
    .match(/選んだ[^<]*/) || [])[0]}`);

// 12c. **全部選ぶ**（段 1 とゴミ箱の段 2 を選ぶ）→ 枚はその操作が効く行で数える
el('pd-bulk').dispatch('change', { target: hitOf('.pd-all-box', {}, { checked: true }) });
const bulkHtml = String(el('pd-bulk').innerHTML || '');
check(bulkHtml.includes('選んだ 1 件をまとめてアプリのゴミ箱へ移す')
  && bulkHtml.includes('選んだ 2 件をまとめて片付ける'),
  `枚は操作ごとに数える: ${(bulkHtml.match(/選んだ [0-9,]+ 件をまとめて[^<]*/g) || []).join(' / ')}`);
check(/class="pd-all-box" checked/.test(bulkHtml), '全部選ぶに印が付く');

// 12d. **押す検査**: まとめて片付けるは**確認を 1 回挟む**（やめたら叩かない）
writes.length = 0;
globalThis.confirm = () => false;
el('pd-bulk').dispatch('click', { target: hitOf('.pd-close-many', {}) });
await tick();
check(writes.filter((w) => w.url === '/api/deletions/close').length === 0,
  '確認でやめたら片付けない');
globalThis.confirm = () => true;
el('pd-bulk').dispatch('click', { target: hitOf('.pd-close-many', {}) });
await tick();
await tick();
const closePosts = writes.filter((w) => w.url === '/api/deletions/close');
check(closePosts.length === 1, `まとめて片付けるは 1 回だけ叩く: ${closePosts.length} 回`);
const closeBody = JSON.parse(String(closePosts[0]?.body || '{}'));
check(closeBody.reason === 'missing' && closeBody.ids.length === 2,
  `reason と選んだ行を送る: ${JSON.stringify(closeBody)}`);
check(closeBody.ids.includes('d4') && closeBody.ids.includes('t1'),
  '段 1 と段 2 の選んだ行を送る（段 3 は送らない）');
check(String(el('pd-msg').innerHTML || '').includes('2 件を片付けました。'),
  `結果は「N 件を片付けました。」: ${String(el('pd-msg').innerHTML || '').slice(0, 60)}`);

// 12e. 断られた行は**数えて 1 行で知らせる**（黙って捨てない）・その行だけ選択に残す
CLOSE_NOW = {
  kind: 'close', requested: 2, count: 1, skipped_count: 1, replayed: false,
  reason: 'missing', closed: [{ deletion_id: 't1', closed: true, files_touched: 0 }],
  skipped: [{ deletion_id: 'd4', reason: 'file_found', message: 'ファイルがまだあります' }],
};
await pdUi.showPending('?ids=');
pdUi.pickAll(true);
writes.length = 0;
globalThis.confirm = () => true;
el('pd-bulk').dispatch('click', { target: hitOf('.pd-close-many', {}) });
await tick();
await tick();
const partialHtml = String(el('pd-msg').innerHTML || '');
check(partialHtml.includes('1 件を片付けました。')
  && partialHtml.includes('1 件は片付けませんでした（ファイルがまだあります）。'),
  `成功と断りを別々に数える: ${partialHtml.slice(0, 90)}`);
check(String(el('pd-bulk').innerHTML || '').includes('選んだ 1 件をまとめて片付ける'),
  '断られた行だけ選択に残す（そのまま押し直せる）');
CLOSE_NOW = { kind: 'close', requested: 0, count: 2, skipped_count: 0, replayed: false,
              reason: 'missing', closed: [], skipped: [] };

// 12f. **押す検査**: まとめてアプリのゴミ箱へ移す（**確認は挟まない**＝戻せる）
await pdUi.showPending('?ids=');
pdUi.pickAll(true);
ADVANCE_NOW = { advanced: [{ deletion_id: 'd4', stage: 2 }], skipped: [], count: 1,
                skipped_count: 0, replayed: false };
writes.length = 0;
globalThis.confirm = () => false;                    // 押しても確認は**呼ばれない**
el('pd-bulk').dispatch('click', { target: hitOf('.pd-advance-many', {}) });
await tick();
await tick();
const advPosts = writes.filter((w) => w.url === '/api/deletions/advance');
check(advPosts.length === 1, `まとめて移すは 1 回だけ叩く: ${advPosts.length} 回`);
const advBody = JSON.parse(String(advPosts[0]?.body || '{}'));
check(advBody.stage === 2 && advBody.ids.length === 1 && advBody.ids[0] === 'd4',
  `段 2 への要求は段 1 の行だけ: ${JSON.stringify(advBody)}`);
check(String(el('pd-msg').innerHTML || '').includes('1 件をアプリのゴミ箱へ移しました。'),
  `結果は「N 件をアプリのゴミ箱へ移しました。」: ${String(el('pd-msg').innerHTML || '').slice(0, 60)}`);
ADVANCE_NOW = { advanced: [], skipped: [], count: 0, skipped_count: 0, replayed: false };

// 12g. **押す検査**: 1 行ずつ（段 1 → 段 2）
writes.length = 0;
await pdUi.showPending('?ids=');
el('pd-running').dispatch('click', { target: hitOf('.pd-advance', { id: 'd4' }) });
await tick();
await tick();
const oneAdv = writes.filter((w) => w.url === '/api/deletions/d4/advance');
check(oneAdv.length === 1 && JSON.parse(String(oneAdv[0]?.body || '{}')).stage === 2,
  `1 行の「アプリのゴミ箱へ移す」は 1 回だけ叩く: ${oneAdv.length} 回`);
check(String(el('pd-msg').innerHTML || '').includes('1 件をアプリのゴミ箱へ移しました。'),
  '1 行の結果も同じ語で知らせる');

// 12h. **実体が無いときの 409 は、本文がそのまま次の一手**（「ファイルが無いので片付ける」）
ADVANCE_FAILS = { status: 409, body: {
  detail: '登録した場所にファイルがありません。「ファイルが無いので片付ける」で、この行を終わりにできます',
  code: 'missing_file' } };
writes.length = 0;
el('pd-running').dispatch('click', { target: hitOf('.pd-advance', { id: 'd4' }) });
await tick();
await tick();
check(String(el('pd-msg').innerHTML || '').includes('ファイルが無いので片付ける'),
  `断りの文で次の一手を案内する: ${String(el('pd-msg').innerHTML || '').slice(0, 80)}`);
check(String(el('pd-running').innerHTML || '').includes('class="pd-close"'),
  '断られた後も読み直して「片付ける」が押せる（失敗の道でも `load()`）');
ADVANCE_FAILS = null;

// 12i. **押す検査**: 1 行の片付けは確認を 1 回挟む（やめたら叩かない）
writes.length = 0;
globalThis.confirm = () => false;
el('pd-running').dispatch('click', { target: hitOf('.pd-close', { id: 'd4' }) });
await tick();
check(writes.filter((w) => w.url === '/api/deletions/d4/close').length === 0,
  '確認でやめたら片付けない');
globalThis.confirm = () => true;
el('pd-running').dispatch('click', { target: hitOf('.pd-close', { id: 'd4' }) });
await tick();
await tick();
const oneClose = writes.filter((w) => w.url === '/api/deletions/d4/close');
check(oneClose.length === 1 && JSON.parse(String(oneClose[0]?.body || '{}')).reason === 'missing',
  `1 行の「ファイルが無いので片付ける」は 1 回だけ叩く: ${oneClose.length} 回`);
check(String(el('pd-msg').innerHTML || '').includes('1 件を片付けました。'),
  '1 行の片付けも同じ語で知らせる');

// 12j. **上限（200 件）を超える選択は分けて送る**（サーバの上限は 1 回 200 件）
const MANY_ROWS = Array.from({ length: 201 }, (_, n) => ({
  id: `m${n}`, asset_id: `a${n}`, stage: 1, path: `d:\\lib\\m${n}.png`,
  display_path: `D:\\lib\\M${n}.png`, from_path: null, to_path: null, hold_path: null,
  remaining_sec: null, purge_at: null, restored_at: null, closed_at: null, size: 10,
  reason: null, actor: 'human', at: '2026-10-18T01:00:00Z', request_id: null, state: 'hidden',
  mine: true, undoable: true, needs_as_copy: false, stuck_reason: null, closeable: true,
}));
PENDING_NOW = { ...PENDING_BODY, items: MANY_ROWS, count: 201, pending: 0 };
await pdUi.showPending('?ids=');
pdUi.pickAll(true);
writes.length = 0;
globalThis.confirm = () => true;
el('pd-bulk').dispatch('click', { target: hitOf('.pd-close-many', {}) });
for (let n = 0; n < 6; n += 1) await tick();          // 2 回の POST を待つ
const chunkPosts = writes.filter((w) => w.url === '/api/deletions/close');
const chunkSizes = chunkPosts.map((w) => JSON.parse(String(w.body || '{}')).ids.length);
check(chunkPosts.length === 2, `200 件ずつ分けて送る: ${chunkPosts.length} 回`);
// 201 行（段 1）＋ゴミ箱の 1 行（段 2）＝ 202 件。**足すと全部**（黙って捨てない）
check(chunkSizes[0] === 200 && chunkSizes[1] < 200
  && chunkSizes.reduce((a, b) => a + b, 0) === 202,
  `1 回目 200 件・2 回目は残り全部: ${chunkSizes.join(' / ')}`);
PENDING_NOW = PENDING_BODY;
CLOSE_NOW = { kind: 'close', requested: 0, count: 2, skipped_count: 0, replayed: false,
              reason: 'missing', closed: [], skipped: [] };
globalThis.confirm = () => true;

// 12k. **（P10 の監査 B-1）二度押しで POST を 2 回飛ばさない**（本物の Chrome で再現した穴）。
//
// `advance` / `closeRow` / `runBatch` に `busy` が無かったので、2 回目の応答が 1 回目の結果の
// 文を上書きしていた（**1 回の操作が成功しているのに「既にアプリのゴミ箱へ移しています」の赤**／
// まとめては**6 枚動いたのに「0 件を…移しました。」**）。**待たずに 2 回**押して数える（罠 27）。
// 壊すと落ちる: `state.busy` の見張りを 3 つの関数から外す（POST が 2 回になる）。
let confirms = 0;
const countConfirm = (value) => { confirms += 1; return value; };
await pdUi.showPending('?ids=');
writes.length = 0;
const oneAdvance = hitOf('.pd-advance', { id: 'd4' });
el('pd-running').dispatch('click', { target: oneAdvance });
el('pd-running').dispatch('click', { target: oneAdvance });      // **await を挟まず 2 回目**
await tick();
await tick();
check(writes.filter((w) => w.url === '/api/deletions/d4/advance').length === 1,
  `1 行の「移す」の二度押しは 1 回だけ: ${writes.filter((w) => w.url === '/api/deletions/d4/advance').length} 回`);
check(String(el('pd-msg').innerHTML || '').includes('1 件をアプリのゴミ箱へ移しました。'),
  `二度押しでも 1 回目の結果の文が残る: ${String(el('pd-msg').innerHTML || '').slice(0, 60)}`);

await pdUi.showPending('?ids=');
pdUi.pickAll(true);
ADVANCE_NOW = { advanced: [{ deletion_id: 'd4', stage: 2 }], skipped: [], count: 1,
                skipped_count: 0, replayed: false };
writes.length = 0;
const manyAdvance = hitOf('.pd-advance-many', {});
el('pd-bulk').dispatch('click', { target: manyAdvance });
el('pd-bulk').dispatch('click', { target: manyAdvance });
await tick();
await tick();
check(writes.filter((w) => w.url === '/api/deletions/advance').length === 1,
  `まとめて移すの二度押しは 1 回だけ: ${writes.filter((w) => w.url === '/api/deletions/advance').length} 回`);
check(String(el('pd-msg').innerHTML || '').includes('1 件をアプリのゴミ箱へ移しました。'),
  `まとめて移すも 1 回目の結果の文が残る: ${String(el('pd-msg').innerHTML || '').slice(0, 60)}`);
ADVANCE_NOW = { advanced: [], skipped: [], count: 0, skipped_count: 0, replayed: false };

await pdUi.showPending('?ids=');
pdUi.pickAll(true);
confirms = 0;
globalThis.confirm = () => countConfirm(true);
writes.length = 0;
const manyClose = hitOf('.pd-close-many', {});
el('pd-bulk').dispatch('click', { target: manyClose });
el('pd-bulk').dispatch('click', { target: manyClose });
await tick();
await tick();
check(writes.filter((w) => w.url === '/api/deletions/close').length === 1,
  `まとめて片付けるの二度押しは 1 回だけ: ${writes.filter((w) => w.url === '/api/deletions/close').length} 回`);
check(confirms === 1, `確認も 1 回だけ: ${confirms} 回`);

writes.length = 0;
confirms = 0;
const closeButtonHit = hitOf('.pd-close', { id: 'd4' });
el('pd-running').dispatch('click', { target: closeButtonHit });
el('pd-running').dispatch('click', { target: closeButtonHit });
await tick();
await tick();
check(writes.filter((w) => w.url === '/api/deletions/d4/close').length === 1,
  `1 行の片付けの二度押しは 1 回だけ: ${writes.filter((w) => w.url === '/api/deletions/d4/close').length} 回`);
check(confirms === 1, `1 行の片付けの確認も 1 回だけ: ${confirms} 回`);
globalThis.confirm = () => true;

// 12l. **（P10 の監査 D-1・D-2）数を実際に起きたことに合わせる**
//   - **既に片付いていた行**（`replayed_count`）は「既に片付けていました」と分けて言う
//     （成功に数えたままだと「2 件を片付けました。」に見える）
//   - **1 件も選んでいないときは「選んだ 0 件」と書かない**（数ではなく状態を言う）
CLOSE_NOW = { kind: 'close', requested: 2, count: 2, skipped_count: 0, replayed_count: 2,
              reason: 'missing', skipped: [],
              closed: [{ deletion_id: 'd4', closed: true, replayed: true, files_touched: 0 },
                       { deletion_id: 't1', closed: true, replayed: true, files_touched: 0 }] };
await pdUi.showPending('?ids=');
pdUi.pickAll(true);
writes.length = 0;
el('pd-bulk').dispatch('click', { target: hitOf('.pd-close-many', {}) });
await tick();
await tick();
const replayHtml = String(el('pd-msg').innerHTML || '');
check(replayHtml.includes('2 件を片付けました。') && replayHtml.includes('2 件は既に片付けていました。'),
  `既に片付いていた数を分けて言う（監査 D-1）: ${replayHtml.slice(0, 80)}`);
CLOSE_NOW = { kind: 'close', requested: 0, count: 2, skipped_count: 0, replayed: false,
              reason: 'missing', closed: [], skipped: [] };
await pdUi.showPending('?ids=');
const freshBulk = String(el('pd-bulk').innerHTML || '');
check(freshBulk.includes('選んだ行はありません') && !freshBulk.includes('選んだ 0 件'),
  `1 件も選んでいないときは「選んだ 0 件」と書かない（監査 D-2）: ${(freshBulk.match(/選んだ[^<]*/) || [])[0]}`);
check(pdUi.skipText('different_file') === '別の画像があります',
  `新しい断りの理由も日本語で出す（監査 A-1）: ${pdUi.skipText('different_file')}`);

// 13. **押す検査**: 削除の確認（`?ids=`）→ 段の選択 → 凍結 → 実行（**画面の中の段**）
// **ボタンと結果の 1 行は、選んだ段の名前をそのまま動詞にする**（`frontend-design.md` §6.1 の規則 4）。
// 段ごとに語が変わることを見る（前は段に関係なく「消す用意をする」だった）
await pdUi.showPending('?ids=a1,a2');
let confirmHtml = String(el('pd-confirm').innerHTML || '');
check(confirmHtml.includes('選んだ 2 枚') && confirmHtml.includes('消す内容を確かめる'),
  '渡された枚と「消す内容を確かめる」を出す');
check(confirmHtml.includes('段 1 カタログから外す') && confirmHtml.includes('段 2 アプリのゴミ箱へ移す')
  && confirmHtml.includes('段 3 ファイルを消す') && !confirmHtml.includes('用意'), '段を 3 つ出す');
check(pdUi.stageTaken() === 1, '既定は段 1（いきなり消さない）');
check(pdUi.askStage(3) === true && pdUi.stageTaken() === 3, '段を選べる');
pdUi.askStage(1);
writes.length = 0;
el('pd-confirm').dispatch('click', { target: hitOf('.pd-preview', {}) });
await tick();
await tick();
const pvPosts = writes.filter((w) => w.url === '/api/locations/bulk-delete/preview');
check(pvPosts.length === 1, `「消す内容を確かめる」は 1 回だけ叩く: ${pvPosts.length} 回`);
const pvBody = JSON.parse(String(pvPosts[0]?.body || '{}'));
check(pvBody.stage === 1 && pvBody.scope.asset_ids.join(',') === 'a1,a2',
  `段と枚を送る: ${JSON.stringify(pvBody)}`);
confirmHtml = String(el('pd-confirm').innerHTML || '');
check(confirmHtml.includes('2 枚、2.8 MB'), `凍結した件数と合計バイトを出す: ${(confirmHtml.match(/2 枚[^<]*/) || [])[0]}`);
check(confirmHtml.includes('D:\\lib\\A1.png'), '対象の一覧そのもの（パスとサイズ）を出す');
check(confirmHtml.includes('カタログから外すだけです') && confirmHtml.includes('容量は空きません'),
  'いつ空くかを出す（段 1 は空かない。§8.1 の 16）');
// **段 1 の実行のボタンは「2 枚をカタログから外す」**（前は「2 枚を消す用意をする」）
check(confirmHtml.includes('>2 枚をカタログから外す</button>'),
  `段 1 の実行のボタン（${(confirmHtml.match(/pd-exec[^>]*>[^<]*/) || [])[0]}）`);
writes.length = 0;
el('pd-confirm').dispatch('click', { target: hitOf('.pd-exec', {}) });
await tick();
await tick();
const blPosts = writes.filter((w) => w.url === '/api/locations/bulk-delete');
check(blPosts.length === 1, `段 1 の「2 枚をカタログから外す」は 1 回だけ叩く: ${blPosts.length} 回`);
const blBody = JSON.parse(String(blPosts[0]?.body || '{}'));
check(blBody.confirm === true && blBody.preview_id === 'pv1', `confirm と preview_id を送る: ${JSON.stringify(blBody)}`);
check(blBody.client_token && blBody.client_token.length > 8, '二重に消さない鍵を付ける（§0.13）');
check(String(el('pd-confirm').innerHTML || '')
  .includes('2 枚をカタログから外しました。いつでも戻せます。'),
  '段 1 の結果は「カタログから外しました」＋「いつでも戻せます」（窓が無い）');
check(!/あと \d+:\d\d/.test(String(el('pd-confirm').innerHTML || '')),
  '段 1 は窓の残り時間を出さない（窓が無いので嘘になる）');
// **利用者に見える文に「用意」を出さない**（規則 4。前はボタン・結果・凡例にあった）
check(!/用意/.test(String(el('pd-confirm').innerHTML || '') + String(el('pd-legend').innerHTML || '')),
  `「用意」を利用者に見せない（規則 4）: ${(String(el('pd-legend').innerHTML || '').match(/段 3[^<]*/) || [])[0]}`);
// **（P9 の監査 G-5。C-2）段 1・3 の直後に「取り直す」の道を 1 行で案内する**（自動では取らない）。
// **画面に無い「いま取る」を案内しない**（監査 C-2 が見つけた誤り）
check(String(el('pd-confirm').innerHTML || '').includes('取り直す'),
  `段 1 の直後にバックアップの道を案内する（G-5）: ${(String(el('pd-confirm').innerHTML || '').match(/バックアップは[^<]*/) || [])[0]}`);
check(String(el('pd-confirm').innerHTML || '').includes('#/settings'),
  '案内は設定（「取り直す」のある画面）へ行く');
BULK_STAGE = 2;                                    // 段 2（ゴミ箱）では案内しない
PREVIEW_NOW = { ...PREVIEW_BODY, stage: 2,
                frees: { stage: 2, bytes: 0, at: null, note: 'ゴミ箱へ移すだけです（容量は空きません）' } };
await pdUi.showPending('?ids=a1,a2');
pdUi.askStage(2);
await pdUi.preview();
// **段 2 の実行のボタンは「2 枚をアプリのゴミ箱へ移す」**
let stageHtml = String(el('pd-confirm').innerHTML || '');
check(stageHtml.includes('>2 枚をアプリのゴミ箱へ移す</button>'),
  `段 2 の実行のボタン（${(stageHtml.match(/pd-exec[^>]*>[^<]*/) || [])[0]}）`);
el('pd-confirm').dispatch('click', { target: hitOf('.pd-exec', {}) });
await tick();
await tick();
check(!String(el('pd-confirm').innerHTML || '').includes('取り直す'),
  '段 2（アプリのゴミ箱へ移す）ではバックアップの案内を出さない（戻せるので急がない）');
stageHtml = String(el('pd-confirm').innerHTML || '');
check(stageHtml.includes('2 枚をアプリのゴミ箱へ移しました。いつでも戻せます。'),
  `段 2 の結果は「ゴミ箱へ移しました」＋「いつでも戻せます」: ${(stageHtml.match(/pd-done[^>]*>[^<]*/) || [])[0]}`);
check(!/あと \d+:\d\d/.test(stageHtml), '段 2 も窓の残り時間を出さない');

// 13b. **（P11 の監査 A-1）断られた理由は API の `skipped[].reason` をそのまま出す**。
//   前は段 2 の結果に「1 件は中身が変わっていたので消しませんでした。」と**固定で**書いていた
//   （`move_failed` でも中身は変わっていない＝嘘。本物の Chrome で見つかった）。
//   **`skipped[].message`（次の一手）もそのまま出す**（理由の語だけでは何もできない）。
const MOVE_FAILED_NOW = 'このファイルは移動できませんでした。ほかのフォルダにあるファイルは、'
  + 'エクスプローラーで消してから「ファイルが無いので片付ける」を押してください。'
  + '（詳細: [WinError 5] アクセスが拒否されました。）';
BULK_SKIPPED = [{ asset_id: 'a1', reason: 'move_failed', message: MOVE_FAILED_NOW }];
await pdUi.showPending('?ids=a1,a2');
pdUi.askStage(2);
await pdUi.preview();
el('pd-confirm').dispatch('click', { target: hitOf('.pd-exec', {}) });
await tick();
await tick();
stageHtml = String(el('pd-confirm').innerHTML || '');
check(stageHtml.includes('1 件は移しませんでした（移動できませんでした）。'),
  `段 2 の断りの理由は API から（P11 の監査 A-1）: ${(stageHtml.match(/pd-confirm[\s\S]{0,300}/) || [])[0]?.slice(0, 90)}`);
check(!stageHtml.includes('中身が変わっていたので消しませんでした'), '嘘の理由を固定で書かない');
check(stageHtml.includes(MOVE_FAILED_NOW), '次の一手（`skipped[].message`）をそのまま出す');
// 段 3 は動詞が「消し」（選んだ段の動詞。§6.1 の規約 3）
BULK_STAGE = 3;
BULK_SKIPPED = [{ asset_id: 'a1', reason: 'move_failed', message: MOVE_FAILED_NOW }];
PREVIEW_NOW = { ...PREVIEW_BODY, stage: 3 };
await pdUi.showPending('?ids=a1,a2');
pdUi.askStage(3);
await pdUi.preview();
el('pd-confirm').dispatch('click', { target: hitOf('.pd-exec', {}) });
await tick();
await tick();
stageHtml = String(el('pd-confirm').innerHTML || '');
check(stageHtml.includes('1 件は消しませんでした（移動できませんでした）。'),
  `段 3 の断りは「消しませんでした」（段 2 は「移しませんでした」）: ${(stageHtml.match(/1 件は[^<]*/) || [])[0]}`);
BULK_STAGE = 1;
BULK_SKIPPED = [];
PREVIEW_NOW = PREVIEW_BODY;
pdUi.askStage(1);

// 13c. **（P11 の監査 A-1）まとめての結果も `skipped[].message` を出す**。
//   前は「2 件は移しませんでした（できませんでした）。」で終わり、**次の一手が画面に 1 度も出なかった**。
ADVANCE_NOW = { advanced: [], skipped: [
  { deletion_id: 'd4', reason: 'move_failed', message: MOVE_FAILED_NOW },
  { deletion_id: 'd5', reason: 'move_failed', message: MOVE_FAILED_NOW }],
  count: 0, skipped_count: 2, replayed: false };
await pdUi.showPending('?ids=');
pdUi.pickAll(true);
el('pd-bulk').dispatch('click', { target: hitOf('.pd-advance-many', {}) });
await tick();
await tick();
const manyHtml = String(el('pd-msg').innerHTML || '');
check(manyHtml.includes('2 件は移しませんでした（移動できませんでした）。')
  && manyHtml.includes(MOVE_FAILED_NOW),
  `まとめての断りに次の一手を続ける（P11 の監査 A-1）: ${manyHtml.slice(0, 120)}`);
check(!manyHtml.includes('できませんでした）。') || manyHtml.includes('移動できませんでした）。'),
  '「できませんでした」で終わらせない');
ADVANCE_NOW = { advanced: [], skipped: [], count: 0, skipped_count: 0, replayed: false };
BULK_STAGE = 1;
PREVIEW_NOW = PREVIEW_BODY;
pdUi.askStage(1);

// 14. 最後の 1 つは重い確認（段 3 のときだけ。§8.1 の 43）
BULK_STAGE = 3;                                    // 段 3 の結果の文（§6.1 の規則 4）
PREVIEW_NOW = { ...PREVIEW_BODY, stage: 3, last_copies: 1, not_allowed_count: 1,
                frees: { stage: 3, bytes: 2_900_000, at: null, note: '5 分の窓が過ぎた時点で空きます' } };
await pdUi.showPending('?ids=a1,a2');
pdUi.askStage(3);
await pdUi.preview();
confirmHtml = String(el('pd-confirm').innerHTML || '');
// **段 3 の実行のボタンは「2 枚のファイルを消す」**
check(confirmHtml.includes('>2 枚のファイルを消す</button>'),
  `段 3 の実行のボタン（${(confirmHtml.match(/pd-exec[^>]*>[^<]*/) || [])[0]}）`);
check(confirmHtml.includes('この 1 枚は、ほかの場所にコピーがありません。消すと中身そのものが無くなります。')
  && confirmHtml.includes('コピーの無い画像も消す'), 'コピーの無い画像の確認を出す（C-6）');
// **（監査 G-4）段 3 の前置きは実際の置き場から組む**（固定のツール名を埋め込まない）。
// 印が無いのは `D:\lib` だけなので、そこだけ出す（`C:\other` には印がある）
check(confirmHtml.includes('このフォルダは段 3 の許可が付いていません（D:\\lib）'),
  `段 3 の前置きを実際のフォルダから組む（監査 G-4。D-6）: ${(confirmHtml.match(/このフォルダ[^<]*/) || [])[0]}`);
check(!confirmHtml.includes('illust-authoring') && !confirmHtml.includes('C:\\other'),
  '固定の名前を埋め込まない（印のある置き場は黙る。監査 G-4）');
check(confirmHtml.includes('許可の無いフォルダの 1 枚'), '段 3 にできない枚を出す（D-2・D-6）');
writes.length = 0;
el('pd-confirm').dispatch('click', { target: hitOf('.pd-exec', {}) });
await tick();
check(writes.filter((w) => w.url === '/api/locations/bulk-delete').length === 0,
  '「コピーの無い画像も消す」に印が無ければ消さない（C-6）');
check(String(el('pd-msg').innerHTML || '').includes('コピーの無い画像も消す'),
  '印を付けるよう促す');
el('pd-confirm').dispatch('change', { target: hitOf('.pd-last-box', {}, { checked: true }) });
writes.length = 0;
el('pd-confirm').dispatch('click', { target: hitOf('.pd-exec', {}) });
await tick();
await tick();
const bl3 = writes.filter((w) => w.url === '/api/locations/bulk-delete');
check(bl3.length === 1 && JSON.parse(String(bl3[0]?.body || '{}')).confirm_last_copy === true,
  `印を付けたら confirm_last_copy を送る: ${bl3[0]?.body}`);
// **段 3 の結果は「ファイルを消しました」＋「あと M:SS は取り消せます」**（段 3 だけ窓がある。§4.6）
stageHtml = String(el('pd-confirm').innerHTML || '');
check(stageHtml.includes('2 枚のファイルを消しました。') && /あと \d+:\d\d は取り消せます。/.test(stageHtml),
  `段 3 の結果は「ファイルを消しました」＋「あと M:SS は取り消せます」: ${(stageHtml.match(/pd-done[^>]*>[^<]*/) || [])[0]}`);
BULK_STAGE = 1;

// 15. 凍結が失効したら 1 行出して押せなくする（§5）
BULK_FAILS = { detail: '確認した一覧の有効期限が切れました', code: 'preview_expired' };
PREVIEW_NOW = { ...PREVIEW_BODY, stage: 1 };
await pdUi.showPending('?ids=a1,a2');
await pdUi.preview();
writes.length = 0;
el('pd-confirm').dispatch('click', { target: hitOf('.pd-exec', {}) });
await tick();
await tick();
confirmHtml = String(el('pd-confirm').innerHTML || '');
check(confirmHtml.includes('確認した一覧の有効期限が切れました。もう一度確認してください。'),
  '失効したら 1 行出す');
check(/pd-exec[^>]*disabled/.test(confirmHtml), '失効したら押せなくする');
BULK_FAILS = null;

// 15b. **段 2 だけのとき**の空の文（**監査 C-2**）: 「ゴミ箱の N 件は下から戻せます。」
//      （段 2 は「取り消せる削除」の一覧に出さないので、空でも戻せる物があると分かるようにする）
PENDING_NOW = { ...PENDING_BODY, items: PENDING_BODY.items.filter((i) => i.state === 'trashed') };
await pdUi.showPending('?ids=');
check(String(el('pd-running').innerHTML || '')
  .includes('戻せる削除はありません。アプリのゴミ箱の 1 件は下から戻せます。'),
  `段 2 だけのときはゴミ箱を案内する: ${String(el('pd-running').innerHTML || '').slice(0, 60)}`);
check(String(el('pd-trash').innerHTML || '').includes('戻す'), 'その行はゴミ箱の欄から戻せる');
PENDING_NOW = PENDING_BODY;
await pdUi.showPending('?ids=');
check(String(el('pd-running').innerHTML || '').includes('あと 3:12'), '本体の応答に戻した');

// 16. 上部バーの入口（§4.6。**段 1 の行だけでも出す**。0 件なら出さない）
//
// **P8-5 の追い込み（実装漏れ）**: 前の版は `state === 'pending'`（段 3 の窓がある行）だけで
// 数えていたので、**段 1 で外した 88 枚があっても入口が出ず、戻す導線が見えなかった**。
// `pending()` は P8-5 で段 1〜3 を返しているので、入口もそれに合わせる。
badge.renderDeleteBadge(PENDING_BODY.items);
check(el('stat-deletes').textContent === '最近の削除 5（あと 0:10）',
  `入口に件数と残り時間（いちばん短い物）を出す: ${el('stat-deletes').textContent}`);
check(el('stat-deletes').hidden === false, 'まだ戻せる行があるときは出す');
// **段 1 の行だけ**（窓が無い）でも出す。件数は出し、**残り時間は出さない**（窓が無いので嘘になる）
badge.renderDeleteBadge([PENDING_BODY.items[3]]);
check(el('stat-deletes').textContent === '最近の削除 1',
  `段 1 の行だけでも出す（残り時間は出さない）: ${el('stat-deletes').textContent}`);
check(el('stat-deletes').hidden === false, '段 1 の行だけでも入口を出す（P8-5 の追い込み）');
// **段 3 でも窓が無い行**（`stuck`。画面では「別名で戻す」を押せる）だけでも出す。
// 前の版は「戻せない物だけなら出さない」だったが、**画面には出ていて押せる**ので出さないと辻褄が合わない
badge.renderDeleteBadge([PENDING_BODY.items[1]]);
check(el('stat-deletes').textContent === '最近の削除 1' && el('stat-deletes').hidden === false,
  `戻せなかった行だけでも出す（画面で「別名で戻す」を押せる）: ${el('stat-deletes').textContent}`);
badge.renderDeleteBadge([]);
check(el('stat-deletes').hidden === true, '0 件なら出さない（§4.6）');
badge.renderDeleteBadge(null);
check(el('stat-deletes').hidden === true, '取れないとき（null）も出さない（古いサーバでも止めない）');

// 16b. **押す検査**: 上部バーの「重複の整理」（P8-5 の追い込み）と「最近の削除」（§4.6）の入口。
//
// 作り物の DOM は**リンクを辿らない**（ページを読み直さない）。ブラウザがする事のうち
// **`href` を `location.hash` に入れる**ところだけを、`index.html` の**本物の `href`** で行う。
// **押して行き先の画面が出るかは `gui_layout --screen library` が本物の Chrome で見る。**

/** `index.html` の `<a id="...">` を 1 つ読む（入口はここにしかないので、ここを出所にする）。 */
function anchorOf(id) {
  const got = new RegExp(`<a[^>]*\\bid="${id}"[^>]*>([^<]*)</a>`).exec(HTML);
  if (!got) return null;
  const tag = got[0].slice(0, got[0].indexOf('>'));
  const at = HTML.indexOf('<div class="topbar">');
  const firstTopbar = HTML.slice(at, HTML.indexOf('</div>', at));
  return {
    text: got[1].trim(),
    html: got[0],
    href: (/\bhref="([^"]*)"/.exec(tag) || [])[1] || null,
    hidden: /(^|\s)hidden(\s|=|$)/.test(tag),
    inTopbar: firstTopbar.includes(`id="${id}"`),
  };
}

const dupEntry = anchorOf('stat-duplicates');
check(!!dupEntry, '上部バーに「重複の整理」の入口がある（P8-5 の追い込み）');
check(dupEntry && dupEntry.text === '重複の整理', `入口の文言: ${dupEntry && dupEntry.text}`);
check(dupEntry && dupEntry.href === '#/duplicates', `入口の行き先: ${dupEntry && dupEntry.href}`);
check(dupEntry && dupEntry.hidden === false, '入口は隠れていない（出る条件は無い。§4.5.1）');
check(dupEntry && dupEntry.inTopbar === true, '入口は上部バーにある（§4.5.1・§11）');
check(dupEntry && dupEntry.html.includes('set-open'),
  `設定と同じ見た目（押せる物だと分かる）: ${dupEntry && dupEntry.html}`);
location.hash = '';
if (dupEntry) location.hash = dupEntry.href;      // ブラウザが押されたときにする事
check(location.hash === '#/duplicates', `押すと #/duplicates へ行く: ${location.hash}`);

const delEntry = anchorOf('stat-deletes');
check(delEntry && delEntry.href === '#/pending-deletes',
  `「最近の削除」の入口の行き先: ${delEntry && delEntry.href}`);
check(delEntry && delEntry.inTopbar === true, '「最近の削除」の入口は上部バーにある（§4.6）');
location.hash = '';

// ---- P8-5: 設定（`#/settings`）と上部バー（バックアップの失敗・走査中）----
//
// 設計: `docs/frontend-design.md` §4.5.1（上部バーに出す 6 つ）・§6（文言）・§11（設定の画面）、
//       `docs/p8-design.md` §0.21・§3.3。
// **押す検査**は `wireSettings()` が付けた**本物の委譲の聞き手**を叩く（`fetch` は飲む）。
const stUi = await import('../apps/gui/settings.js');
stUi.wireSettings();

// 17. 上部バー: **バックアップの失敗**（P8-4 の再確認 B-1' / G-4）
badge.renderBackupBadge(BACKUP_NOW);
check(el('stat-backup').textContent === 'バックアップに失敗しています',
  `失敗していることを上部バーに出す: ${el('stat-backup').textContent}`);
check(el('stat-backup').hidden === false, '失敗しているときは出す（黙って失敗しない）');
check(String(el('stat-backup').title).includes('WinError 5'),
  `押す前に理由の頭を見せる（title）: ${String(el('stat-backup').title).slice(0, 40)}`);
badge.renderBackupBadge({ ...BACKUP_NOW, last_error: null });
check(el('stat-backup').hidden === true, '失敗が無ければ出さない');
badge.renderBackupBadge({ ...BACKUP_NOW, last_error: null, read_only: true });
check(el('stat-backup').textContent === '読み取り専用です', '読み取り専用は別の語で出す');
badge.renderBackupBadge(null, { status: 503 });
check(el('stat-backup').textContent === '読み取り専用です' && el('stat-backup').hidden === false,
  '状態が読めない（503）ときも同じ場所に出す（P8-4 の再確認 D-2・G-4）');
// **（P9 の監査 D-1 / D-2）一時的な 503 を「読み取り専用」と言わない。**
// `disk i/o error`（503 `io_error`）と `database is locked`（503 `busy`）は**もう一度で直る**
badge.renderBackupBadge({ code: 'io_error', detail: 'DB の読み書きで一時的なエラーが起きました' },
                        { status: 503 });
check(el('stat-backup').textContent === 'バックアップに失敗しています'
  && !String(el('stat-backup').title).includes('読み取り専用'),
  `一時的な 503 は読み取り専用と言わない（D-1）: ${el('stat-backup').textContent}`);
badge.renderBackupBadge({ code: 'busy', detail: 'DB がいま混んでいます' }, { status: 503 });
check(el('stat-backup').textContent === 'バックアップに失敗しています',
  `混んでいるだけの 503 も同じ（D-2）: ${el('stat-backup').textContent}`);
check(badge.isReadOnlyStatus(503, { code: 'db_error' }) === true
  && badge.isReadOnlyStatus(503, { code: 'busy' }) === false,
  '読み取り専用の語彙は 1 か所（db_error / read_only / code なし）');
badge.renderBackupBadge(null);
check(el('stat-backup').hidden === true, '取れないだけなら出さない（古いサーバでも止めない）');
// 印は**上部バー**にあり、押すと `#/settings` へ行く（**下の画面に埋めない**）
const topbarAt = HTML.indexOf('<div class="topbar">');
const firstTopbar = HTML.slice(topbarAt, HTML.indexOf('</div>', topbarAt));
check(firstTopbar.includes('id="stat-backup"') && firstTopbar.includes('href="#/settings"'),
  '上部バーの印から設定（全文）へ入れる');
check(firstTopbar.includes('id="stat-scan"') && firstTopbar.includes('id="stat-settings"'),
  '走査中の印と設定の入口も上部バーにある');

// 18. 上部バー: 走査中（走査の間は削除と取り消しが待つ。§4.5.1）
badge.renderScanBadge({ scanning: true, elapsed_sec: 3.5 });
check(el('stat-scan').textContent === '走査中です' && el('stat-scan').hidden === false,
  `走査中を出す: ${el('stat-scan').textContent}`);
badge.renderScanBadge({ scanning: false });
check(el('stat-scan').hidden === true, '走査していないときは出さない');
badge.renderScanBadge(null);
check(el('stat-scan').hidden === true, '取れないときは出さない（古いサーバ。404）');

// 19. 設定の画面: バックアップの状態（**最後の失敗の全文**。B-1'）
check(stUi.lastTakenAt(BACKUP_NOW) === '2026-10-18T03:15:00Z',
  `最後に取った時刻は daily / manual だけから（pre-topup を数えない。D-5）: ${stUi.lastTakenAt(BACKUP_NOW)}`);
check(stUi.kindText('pre-topup') === '表の形を変える前'
  && stUi.kindText('daily') === '日次' && stUi.kindText('manual') === '取り直し'
  && stUi.kindText('nazo') === 'その他',
  'バックアップの種類は利用者の言葉で出す（`kind` をそのまま出さない。文言表は「取り直し」。D-1）');
writes.length = 0;
settingsWrites.length = 0;
await stUi.showSettings();
let bkHtml = String(el('st-backup').innerHTML || '');
check(bkHtml.includes('最後に取ったのは') && bkHtml.includes(pdUi.fmtWhen('2026-10-18T03:15:00Z')),
  `最後に取った時刻を出す: ${(bkHtml.match(/最後に取ったのは[^<]*/) || [])[0]}`);
check(bkHtml.includes('C:\\work\\image-reviwer\\.backup\\daily') && bkHtml.includes('（設定の値）'),
  '置き場と、それが設定の値か既定かを出す');
check(bkHtml.includes('今日の分は取れています。'), '今日の分の状態を出す（文言表の文。D-2）');
check(!bkHtml.includes('（次は'), '「今日の分」に括弧を重ねない（API の `next_run_note` は出さない。D-2）');
check(bkHtml.includes('バックアップが 3 世代あります（直近 7 世代を残します）'), 'バックアップの数と残す数を出す');
check(bkHtml.includes("[WinError 5] アクセスが拒否されました: "
  + "'C:\\Users\\yukse\\image-reviewer-backups'"),
  `最後の失敗を**全文**で出す（B-1'）: ${(bkHtml.match(/st-failed[\s\S]{0,60}/) || [])[0]}`);
check(bkHtml.includes('保存先を作れないときは、書き込める場所に変えてください。'),
  '次にできることを 1 行で出す');
check(bkHtml.includes('20261018-121500') && bkHtml.includes('日次') && bkHtml.includes('取り直す')
  && bkHtml.includes('表の形を変える前'), '直近の一覧を種類つきで出す');
check(/class="st-now"[^>]*>取り直す</.test(bkHtml),
  `ボタンは「取り直す」（文言表が正。D-1）: ${(bkHtml.match(/class="st-now"[^>]*>[^<]*/) || [])[0]}`);
check(bkHtml.includes('placeholder="例: D:\\backups\\image-reviewer"'), '保存先の入力に例を書く（C-17）');
check(bkHtml.includes('image-reviewer restore') && !bkHtml.includes('st-restore'),
  '復元はコマンドだと書く（画面から戻さない。§3.3）');

// 19b. 「今日の分」は API の `today_done` から組む（`next_run_note` をそのまま出さない。D-2）
BACKUP_NOW = { ...BACKUP_BODY, today_done: false };
await stUi.showSettings();
check(String(el('st-backup').innerHTML || '').includes('今日の分はまだです。'),
  'まだの日は「今日の分はまだです。」と出す（D-2）');

// 19c. **読めないバックアップ**（`manifest.json` が無い物）も語で出す
//      （P8-5 の監査 D-6。壊し試験 G11「文言を消しても緑」だった穴）
BACKUP_NOW = { ...BACKUP_BODY, snapshots: [...BACKUP_BODY.snapshots,
  { name: '20261018-130000', kind: 'manual', created_at: '2026-10-18T04:00:00Z',
    bytes: 1000, ok: false }] };
await stUi.showSettings();
check(String(el('st-backup').innerHTML || '').includes('バックアップを読めません'),
  '読めないバックアップは「バックアップを読めません」と出す（D-6）');
BACKUP_NOW = BACKUP_BODY;
await stUi.showSettings();

// 20. 設定の画面: 置き場ごとの「段 3 を許す」印（Q8）
let rtHtml = String(el('st-roots').innerHTML || '');
check(rtHtml.includes('許可あり') && rtHtml.includes('許可なし'), '置き場ごとに段 3 の許可の状態を出す');
check(rtHtml.includes('許可を外す') && rtHtml.includes('このフォルダで段 3 を許す'),
  '付け外しのボタンを分ける');
check(rtHtml.includes('許可の無いフォルダでは段 3（ファイルを消す）を選べません。段 1・2 はいつでも使えます。'),
  '許可の意味を 1 行で書く');
check(el('st-brief').textContent === 'バックアップ 3 世代、段 3 の許可 1 / 2',
  `見出しにバックアップと許可の数を出す: ${el('st-brief').textContent}`);

// 21. **押す検査**: 印を付ける（1 回だけ・allow: true・**人だと名乗る**）
writes.length = 0;
settingsWrites.length = 0;
el('st-roots').dispatch('click', { target: hitOf('.st-allow', { id: 'd:\\lib', allow: 'true' }) });
await tick();
await tick();
const allowPosts = writes.filter((w) => w.url.includes('/allow-stage3'));
check(allowPosts.length === 1, `印を付けるのは 1 回だけ叩く: ${allowPosts.length} 回`);
check(decodeURIComponent(String(allowPosts[0]?.url || '')).includes('/api/roots/d:\\lib/allow-stage3'),
  `置き場の id を送る: ${allowPosts[0]?.url}`);
check(JSON.parse(String(allowPosts[0]?.body || '{}')).allow === true, 'allow: true を送る');
check(settingsWrites[0]?.headers?.['X-Image-Reviewer-Actor'] === 'human',
  `人だけの口に名乗る（P8-3 の監査 D-8）: ${JSON.stringify(settingsWrites[0]?.headers)}`);
check(String(el('st-msg').innerHTML || '').includes('このフォルダで段 3 を許します。'),
  `押した結果を 1 行で知らせる: ${String(el('st-msg').innerHTML || '').slice(0, 60)}`);

// 21b. **二度押し**（1 回目の応答が返る前に 2 回目を押す。**P8-5 の監査 C-1**）→ POST は 1 回
writes.length = 0;
settingsWrites.length = 0;
el('st-roots').dispatch('click', { target: hitOf('.st-allow', { id: 'd:\\lib', allow: 'true' }) });
const allowBusy = buttonIn('st-roots', 'st-allow');
check(allowBusy.seen && allowBusy.disabled,
  `印のボタンは押している間は押せない（「取り直す」と同じ形。C-1）: ${JSON.stringify(allowBusy)}`);
// 本物のブラウザは `disabled` のボタンに 2 回目を届けない（届く形なら押して数える）
if (allowBusy.seen && !allowBusy.disabled) {
  el('st-roots').dispatch('click', { target: hitOf('.st-allow', { id: 'd:\\lib', allow: 'true' }) });
}
await tick();
await tick();
const dblPosts = writes.filter((w) => w.url.includes('/allow-stage3'));
check(dblPosts.length === 1, `印のボタンの二度押しでも POST は 1 回: ${dblPosts.length} 回`);

// 22. **押す検査**: 印を外す（allow: false）
writes.length = 0;
el('st-roots').dispatch('click', { target: hitOf('.st-allow', { id: 'c:\\other', allow: 'false' }) });
await tick();
await tick();
const offPosts = writes.filter((w) => w.url.includes('/allow-stage3'));
check(offPosts.length === 1 && JSON.parse(String(offPosts[0]?.body || '{}')).allow === false,
  `印を外すときは allow: false: ${offPosts[0]?.body}`);

// 23. **押す検査**: 「取り直す」→ `POST /api/backup`（同じ日でも必ず新しく取る。§3.3）
writes.length = 0;
settingsWrites.length = 0;
el('st-backup').dispatch('click', { target: hitOf('.st-now', {}) });
const nowBusy = buttonIn('st-backup', 'st-now');
check(nowBusy.seen && nowBusy.disabled, `「取り直す」も押している間は押せない: ${JSON.stringify(nowBusy)}`);
if (nowBusy.seen && !nowBusy.disabled) {
  el('st-backup').dispatch('click', { target: hitOf('.st-now', {}) });
}
await tick();
await tick();
const nowPosts = writes.filter((w) => w.url === '/api/backup' && w.method === 'POST');
check(nowPosts.length === 1, `「取り直す」は二度押しでも 1 回だけ叩く: ${nowPosts.length} 回`);
check(settingsWrites.some((w) => w.url === '/api/backup'
  && w.headers?.['X-Image-Reviewer-Actor'] === 'human'), '「取り直す」も人だけの口');
check(String(el('st-msg').innerHTML || '').includes('取り直しました'), '取れたことを 1 行で知らせる');

// 24. **押す検査**: 置き場を変える → `PATCH /api/settings`
el('st-dir').value = 'D:\\image-reviewer-backups';
writes.length = 0;
settingsWrites.length = 0;
el('st-backup').dispatch('click', { target: hitOf('.st-save', {}) });
await tick();
await tick();
const patchPosts = writes.filter((w) => w.url === '/api/settings' && w.method === 'PATCH');
check(patchPosts.length === 1, `置き場を変えるのは 1 回だけ叩く: ${patchPosts.length} 回`);
check(JSON.parse(String(patchPosts[0]?.body || '{}')).backup_dir === 'D:\\image-reviewer-backups',
  `入力の値を送る: ${patchPosts[0]?.body}`);
check(settingsWrites.some((w) => w.method === 'PATCH'
  && w.headers?.['X-Image-Reviewer-Actor'] === 'human'), '置き場を変えるのも人だけの口');

// 24b. 断られたら理由をそのまま出す（`422 bad_backup_dir`）
SETTINGS_FAILS = { detail: 'その置き場はデータ置き場の中です', code: 'bad_backup_dir' };
writes.length = 0;
el('st-backup').dispatch('click', { target: hitOf('.st-save', {}) });
await tick();
await tick();
check(String(el('st-msg').innerHTML || '').includes('その置き場はデータ置き場の中です'),
  `断られた理由をそのまま出す: ${String(el('st-msg').innerHTML || '').slice(0, 70)}`);
check(String(el('st-msg').innerHTML || '').includes('bad'), '失敗は失敗の見た目にする');
SETTINGS_FAILS = null;

// 25. 読み取り専用のときの案内（`GET /api/backup` が 503。P8-4 の再確認 D-2）
//     **語彙は API の物**（`GET /api/health/db` の `reason`。D-3）
BACKUP_STATUS = 503;
HEALTH_BODY = { mode: 'read_only', reason: 'malformed', read_only: true,
                guidance: 'バックアップから戻してください: image-reviewer restore <フォルダ>' };
await stUi.showSettings();
const roHtml = String(el('st-backup').innerHTML || '');
check(roHtml.includes('DB を読み取り専用で開いています。'), '読み取り専用だと 1 行で言う');
check(roHtml.includes('DB の検査に通りませんでした。'), '理由を語で出す（`malformed` をそのまま出さない）');
check(roHtml.includes('image-reviewer restore'), '復元の案内を出す');
check(!/st-now|st-save/.test(roHtml),
  '書き込むボタンは出さない（押せないのではなく置かない）');
check(el('st-brief').textContent === '読み取り専用', `見出しも読み取り専用: ${el('st-brief').textContent}`);
const roAllow = buttonIn('st-roots', 'st-allow');
check(roAllow.seen && roAllow.disabled,
  `読み取り専用では印のボタンも押せなくする（§6「書き込みのボタンは押せなくする」）: ${JSON.stringify(roAllow)}`);
check(String(el('st-roots').innerHTML || '').includes('読み取り専用で開いているので、許可は変えられません。'),
  '許可が変えられない理由を 1 行で出す');

// 25b. **版が新しい DB**（`GET /api/backup` は 200 だが `read_only`。§6・C-3）
BACKUP_STATUS = 200;
BACKUP_NOW = { ...BACKUP_BODY, read_only: true };
HEALTH_BODY = { mode: 'read_only', reason: 'version_ahead', read_only: true,
                guidance: 'DB の版がこのアプリより新しいので、読み取り専用で起動しています。'
                  + '新しいアプリで開くか、バックアップから戻してください: '
                  + 'image-reviewer restore <バックアップのフォルダ>' };
await stUi.showSettings();
const aheadHtml = String(el('st-backup').innerHTML || '');
check(aheadHtml.includes('DB を読み取り専用で開いています。'), '200 でも `read_only` なら 1 行で言う（C-3）');
check(aheadHtml.includes('DB の版がこのアプリより新しいものです。'),
  `理由は API の語彙（\`version_ahead\`）で出す（D-3）: ${(aheadHtml.match(/st-warn[^<]*/) || [])[0]}`);
check(aheadHtml.includes('新しいアプリで開くか'), 'API の案内（`guidance`）をそのまま出す（D-3）');
check(!/st-now|st-save/.test(aheadHtml), '200 の読み取り専用でも書き込むボタンは置かない（C-3）');
check(el('st-brief').textContent === '読み取り専用', `見出しも読み取り専用: ${el('st-brief').textContent}`);

// 25c. 語彙の残り（`unreadable` / `unopenable` / `pre_migrate_backup_failed` が API の物）
HEALTH_BODY = { mode: 'unusable', reason: 'unreadable', read_only: true,
                guidance: 'DB を開けません（ファイルが壊れています）。' };
await stUi.showSettings();
check(String(el('st-backup').innerHTML || '').includes('DB を開けませんでした（ファイルが壊れています）。'),
  '`unreadable` も語で出す（D-3。API の語彙に揃えた）');
HEALTH_BODY = { mode: 'ok', reason: 'ok', read_only: false, guidance: null };
BACKUP_NOW = BACKUP_BODY;
await stUi.showSettings();

// ---- P8-5: 最近の削除の段 3 の出し分け（Q8）と走査中の 1 行 ----

// 26. **印の無い置き場では段 3 のラジオを出さない**（P8-3 の監査 E-3）
ASSET_PATHS = { a1: 'D:\\lib\\A1.png', a2: 'D:\\lib\\A2.png' };       // `D:\lib` は印なし
await pdUi.showPending('?ids=a1,a2');
let pdConfirm = String(el('pd-confirm').innerHTML || '');
check(!pdConfirm.includes('value="3"') && pdConfirm.includes('value="1"')
  && pdConfirm.includes('value="2"'),
  '許可の無い置き場では段 3 を出さない（段 1・2 だけ。Q8・E-3）');
check(pdConfirm.includes('このフォルダには段 3 の許可がありません。段 1・2 だけ選べます。許可は設定で付けられます。'),
  `断りの 1 行を出す: ${(pdConfirm.match(/このフォルダ[^<]*/) || [])[0]}`);
check(pdConfirm.includes('href="#/settings"'), '許可を付ける場所（設定）へ行ける');
check(pdUi.askStage(3) === false && pdUi.stageTaken() === 1,
  '出していない段は押しても選ばない（段 1 のまま）');

// 27. 印のある置き場では出す（選べる）
ASSET_PATHS = { a1: 'C:\\other\\A1.png', a2: 'C:\\other\\A2.png' };   // `C:\other` は印あり
await pdUi.showPending('?ids=a1,a2');
pdConfirm = String(el('pd-confirm').innerHTML || '');
check(pdConfirm.includes('value="3"') && !pdConfirm.includes('段 3 の許可がありません'),
  '許可のある置き場では段 3 を出す');
check(pdUi.askStage(3) === true, '印のある置き場では段 3 を選べる');
pdUi.askStage(1);

// 28. 置き場を**確かめられない**ときは出さない（安全側。文は「印が無い」と言い切らない）
ASSETS_FAILS = true;
await pdUi.showPending('?ids=a1,a2');
pdConfirm = String(el('pd-confirm').innerHTML || '');
check(!pdConfirm.includes('value="3"'), '確かめられないときも段 3 を出さない（安全側）');
check(pdConfirm.includes('フォルダを確かめられないので、段 3 は出していません。'),
  `確かめられなかったと言う: ${(pdConfirm.match(/フォルダを確かめ[^<]*/) || [])[0]}`);
ASSETS_FAILS = false;

// 28b. **一覧の上限（2000 枚）を超える置き場**（P8-5 の監査 D-5）。
//      一覧に選んだ枚が無いので、**1 枚の口**（`/api/assets/<id>`）で引く
ASSET_PATHS = {};                                            // 一覧には 1 枚も無い
SINGLE_ASSET = { path: 'C:\\other\\A1.png' };                 // `C:\other` は印あり
await pdUi.showPending('?ids=a1,a2');
pdConfirm = String(el('pd-confirm').innerHTML || '');
check(pdConfirm.includes('value="3"'),
  '一覧に無い枚は 1 枚の口で引いて段 3 を出す（D-5。2000 枚を超える置き場）');
check(asked.some((u) => u.startsWith('/api/assets/')), '1 枚の口を引く（足りない枚だけ）');
// 1 枚の口も引けないときは**出さない**（安全側）
SINGLE_ASSET = null;
await pdUi.showPending('?ids=a1,a2');
check(!String(el('pd-confirm').innerHTML || '').includes('value="3"'),
  '1 枚の口も引けないときは段 3 を出さない（安全側）');
ASSET_PATHS = { a1: 'C:\\other\\A1.png', a2: 'C:\\other\\A2.png' };
await pdUi.showPending('?ids=a1,a2');

// 29. **走査中の 1 行**（`GET /api/scan`。走査は削除と同じ錠を取る）
SCAN_NOW = { scanning: true, started_at: '2026-10-18T03:00:00Z', elapsed_sec: 3.5, scans: 2,
             note: '走査中です。終わるまで削除と取り消しは待ちます。' };
await pdUi.showPending('?ids=');
check(String(el('pd-scan').innerHTML || '')
  .includes('走査中です。終わるまで削除と取り消しは待ちます。'),
  `最近の削除にも走査中を出す: ${String(el('pd-scan').innerHTML || '').slice(0, 40)}`);
SCAN_NOW = { scanning: false, started_at: null, elapsed_sec: null, scans: 3,
             note: '走査していません。' };
await pdUi.showPending('?ids=');
check(String(el('pd-scan').innerHTML || '') === '', '走査が終わったら 1 行を消す');

// 30. **（P8-3 の再確認 D-1）** `target_exists` の文は「別名で戻す」を勧め、「いま消す」は
//      ボタンだけにする（消す方を文で勧めない）
const teRow = pdUi.rowHtml({ ...PENDING_BODY.items[1] });     // d2: target_exists + as_copy 可
check(teRow.includes('戻せませんでした。元の場所に既にファイルがあります。「別名で戻す」で戻せます。'),
  `target_exists の文を直した（P8-3 の再確認 D-1）: ${(teRow.match(/戻せませんでした[\s\S]{0,60}/) || [])[0]}`);
check(!teRow.includes('いま消す」を選べます'), '「いま消す」を文で勧めない');
check(teRow.includes('>いま消す<') && teRow.includes('>別名で戻す<'), 'ボタンは両方残す');
const otherRow = pdUi.rowHtml({ ...PENDING_BODY.items[1], stuck_reason: 'different' });
check(otherRow.includes('「別名で戻す」か「いま消す」を選べます。'),
  '他の理由では今までどおり両方を案内する');
// **（P11 の監査 B-1）取り消しで移せなかった行は「元へ移す」道を言う**——「別名で戻す」も
// 「いま消す」も通らない（元のフォルダに書けない）。**消す側を案内しない**（戻したかった物が消える）
const moveFailedRow = pdUi.rowHtml({ ...PENDING_BODY.items[1], stage: 2, state: 'stuck',
  stuck_reason: 'move_failed' });
check(moveFailedRow.includes('エクスプローラーで、アプリのゴミ箱から元の場所へ移してください。'),
  `move_failed の行は元へ移す道を言う（P11 の監査 B-1）: ${(moveFailedRow.match(/戻せませんでした[\s\S]{0,80}/) || [])[0]}`);
check(!moveFailedRow.includes('「いま消す」を選べます'), 'move_failed で消す側を文で勧めない');
const moveFailedHoldRow = pdUi.rowHtml({ ...PENDING_BODY.items[1], stage: 3, state: 'stuck',
  stuck_reason: 'move_failed' });
check(moveFailedHoldRow.includes('エクスプローラーで、一時置き場から元の場所へ移してください。'),
  `段 3 の取り消しは一時置き場を案内する: ${(moveFailedHoldRow.match(/戻せませんでした[\s\S]{0,80}/) || [])[0]}`);

// 31. **（P9 の監査 C-2）画面に出す「枚」は 1 つの規則**（生きた枚）。
//     実データ: `/api/stats` の `assets` = 455（段 1〜3 で外した 193 枚を含む）、
//     `GET /api/assets` の `total` = 262（生きた枚）。前は上部だけが 262 で、
//     「すべて」(`#c-all`) と下部バーが 455 だった（同じ画面に 2 つの数）。
const countsUi = await import('../apps/gui/counts.js');
const REAL_STATS = { assets: 455, with_provenance: 375, without_provenance: 80, missing: 0 };
const live = countsUi.liveTotal(REAL_STATS, 262);
check(live === 262, `上部と「すべて」は生きた枚: ${live}（455 と混ざらない）`);
check(countsUi.briefText(live, 262) === '262 枚', `切れていないときは素の枚数: ${countsUi.briefText(live, 262)}`);
check(countsUi.liveTotal(REAL_STATS, undefined) === 455,
  '`total` が無い古いサーバでは /api/stats に落とす（画面を止めない）');
// 一覧が全部そろっていれば内訳も生きた枚から（375+80=455 を持ち込まない）
const liveItems = Array.from({ length: 262 }, (_, i) => ({ id: `x${i}`, has_provenance: i < 200 }));
const prov = countsUi.provenanceCounts(liveItems, 262, REAL_STATS);
check(prov.with === 200 && prov.without === 62,
  `来歴あり／なしも生きた枚の内訳: ${prov.with} / ${prov.without}（stats の 375/80 を使わない）`);
check(countsUi.briefText(10000, 2000) === '10,000 枚（先頭 2,000 枚を表示）',
  `切れているときだけ添える: ${countsUi.briefText(10000, 2000)}`);

// 32. **（ワーディング監査 G-12）左の列の「来歴あり」「来歴なし」は押したら絞る。**
//     前は `data-filter="with" / "without"` を持っていて**押せるのに何も絞られなかった**
//     （`visibleAssets()` が `kind:` と `model:` しか見ていなかった）。**軸の決め方を
//     純関数（`filters.js`）にして、押したときの結果をここで固定する。**
//     `app.js` は読み込まない（作り物の DOM では `route()` が走ってしまう）ので、
//     絞り込みそのものを検査する——**押す検査は `gui_layout`（本物の Chrome）**が持つ。
const filtersUi = await import('../apps/gui/filters.js');
const FILTER_ITEMS = [
  { id: 'f1', has_provenance: true, kind: 'generated', model: 'anima' },
  { id: 'f2', has_provenance: false, kind: 'photo', model: 'unknown' },
  { id: 'f3', has_provenance: false, kind: 'photo', model: 'unknown' },
];
check(filtersUi.railSelection('without', 'all').provenance === 'without'
  && filtersUi.railSelection('without', 'all').filter === 'all',
  `「来歴なし」を押すと来歴の軸が動く: ${JSON.stringify(filtersUi.railSelection('without', 'all'))}`);
check(filtersUi.visibleAssets(FILTER_ITEMS, filtersUi.railSelection('without', 'all')).length === 2,
  `「来歴なし」で 2 枚に絞る（前は 3 枚のまま）: ${
    filtersUi.visibleAssets(FILTER_ITEMS, filtersUi.railSelection('without', 'all')).length}`);
check(filtersUi.visibleAssets(FILTER_ITEMS, filtersUi.railSelection('with', 'all')).length === 1,
  '「来歴あり」で 1 枚に絞る');
check(filtersUi.visibleAssets(FILTER_ITEMS, filtersUi.railSelection('kind:photo', 'all')).length === 2,
  '種別の行は今までどおり絞る（kind）');
check(filtersUi.visibleAssets(FILTER_ITEMS, filtersUi.railSelection('model:anima', 'all')).length === 1,
  'モデルの行も今までどおり絞る（model）');
check(filtersUi.railSelection('kind:photo', 'without').provenance === 'all',
  '左の列は 1 つだけ選べる（他の軸は外す）');
// **（ワーディング監査 W-3）絞り込みで 0 枚のときに「まだ画像がありません」と言わない**
check(filtersUi.emptyText(true).includes('条件に合う画像がありません')
  && filtersUi.emptyText(true).includes('絞り込みを外すと全部が見えます'),
  `絞り込みで 0 枚のときの文（W-3）: ${filtersUi.emptyText(true)}`);
check(filtersUi.emptyText(false).includes('画像がまだ登録されていません'),
  '絞り込みでないときは今までどおり（走査していない）');
check(filtersUi.isFiltering('all', 'all') === false && filtersUi.isFiltering('all', 'without') === true,
  '来歴の軸だけでも「絞り込み中」と数える');
check(filtersUi.visibleAssets(FILTER_ITEMS, { filter: 'all', provenance: 'all' }).length === 3,
  '軸が全部「すべて」なら全枚');

﻿
// ---- P2-1: フォルダ（カタログ。`#/folders`）----
//
// 設計: docs/frontend-design.md §3（画面の一覧 14）・§6（文言）・§11（フォルダの画面）。
// **見る**: 木の順と深さ・枚数・空の案内・確認の語（名前を打ち込むまで送らない）・
// 押したら 1 回だけ叩くこと（作る／入れる／外す／名前を変える／消す）・
// `add=` がある間だけ「ここに入れる」が出ること・**画像は消えないと言うこと**。
// **見ない**: 見た目（CSS）・本物のブラウザの焦点（`gui_layout` が見る）。
const FL_TREE = { total: 3, items: [
  { id: 'f1', parent_id: null, name: '旅行', kind: 'manual', count: 1, children: [
    { id: 'f2', parent_id: 'f1', name: '海', kind: 'manual', count: 0, children: [] }] },
  { id: 'f3', parent_id: null, name: '1girl だけ', kind: 'smart', count: 0, children: [] },
] };
const FL_ITEMS = {
  folder: { id: 'f1', name: '旅行', kind: 'manual', count: 1 },
  total: 1, cursor: 0, limit: 200, next_cursor: null,
  items: [{ id: 'a1', path: 'D:\\lib\\a.png', review_state: 'kept', width: 16, height: 16,
            position: 0, added_at: '2026-10-20T00:00:00Z' }],
};
const FL_SMART = {
  folder: { id: 'f3', name: '1girl だけ', kind: 'smart', count: 0 },
  total: 0, cursor: 0, limit: 200, next_cursor: null, items: [], smart: true,
  note: 'スマートフォルダの条件はまだ使えません。この段では、手で入れた画像だけが出ます。',
};
let flAsked = [];
let flWrites = [];
globalThis.fetch = async (url, options) => {
  const method = String(options?.method || 'GET').toUpperCase();
  const path = String(url);
  flAsked.push(`${method} ${path}`);
  if (method !== 'GET') flWrites.push({ url: path, method, body: options?.body });
  const asJson = (body, status = 200) => ({
    ok: status < 400, status,
    text: async () => JSON.stringify(body), json: async () => JSON.parse(JSON.stringify(body)),
  });
  if (path === '/api/folders' && method === 'GET') return asJson(FL_TREE);
  if (path === '/api/folders' && method === 'POST') {
    const body = JSON.parse(String(options.body || '{}'));
    if (body.name === '旅行') {
      return asJson({ detail: '同じ親の下に「旅行」があります（別の名前を付けてください）',
                      code: 'folder_name_taken' }, 422);
    }
    return asJson({ created: true, id: 'f9', name: body.name, parent_id: body.parent_id || null });
  }
  if (path.startsWith('/api/folders/f1/assets')) return asJson(FL_ITEMS);
  if (path.startsWith('/api/folders/f3/assets')) return asJson(FL_SMART);
  if (path.startsWith('/api/folders/f2/assets')) {
    return asJson({ ...FL_ITEMS, folder: { id: 'f2', name: '海', count: 0 },
                    total: 0, items: [] });
  }
  if (method === 'POST' && path.endsWith('/members')) {
    return asJson({ folder_id: 'f1', added: ['a1', 'a2'], already: ['a3'], count: 3 });
  }
  if (method === 'DELETE' && path.endsWith('/members')) {
    return asJson({ folder_id: 'f1', removed: ['a1'], not_member: [], count: 0 });
  }
  if (method === 'PATCH') return asJson({ updated: true, id: 'f1', name: '海' });
  if (method === 'DELETE') {
    return asJson({ deleted: true, purged: false, folder_id: 'f1', folders: 1, members: 1,
                    assets_deleted: 0 });
  }
  return asJson({});
};
const flUi = await import('../apps/gui/folders.js');

// 33a. 木の形（**親の直後に子**。深さで字下げ）
const flat = flUi.flattenTree(FL_TREE.items);
check(flat.map((row) => row.node.id).join(',') === 'f1,f2,f3',
  `木は前順に平らにする: ${flat.map((row) => row.node.id).join(',')}`);
check(flat.map((row) => row.depth).join(',') === '0,1,0',
  `深さが付く（子は 1）: ${flat.map((row) => row.depth).join(',')}`);
check(flUi.briefText(FL_TREE) === 'フォルダ 3 個、画像 1 枚',
  `見出しはフォルダ数と画像の枚数（片付け済みは数えない）: ${flUi.briefText(FL_TREE)}`);
check(flUi.briefText({ total: 2, items: [] }) === 'フォルダ 2 個、画像 0 枚',
  '木が空でも数える（total を使う）');

// 33b. 空の案内は「いまの状態＋次に押す物」の 2 文（規則 3）
check(flUi.emptyTreeText().includes('フォルダがまだありません')
  && flUi.emptyTreeText().includes('「作る」を押すと'),
  `空の案内（フォルダ無し）: ${flUi.emptyTreeText()}`);
check(flUi.emptyFolderText(0).includes('このフォルダには画像がありません')
  && flUi.emptyFolderText(0).includes('選んだ画像をフォルダに入れる…'),
  `空の案内（中身無し）: ${flUi.emptyFolderText(0)}`);
check(flUi.emptyFolderText(3).includes('選んだ 3 枚を'),
  `枚数があるときはその数を出す: ${flUi.emptyFolderText(3)}`);

// 33c. 木の 1 行（枚数・選んだ印・`add=` のときだけ「ここに入れる」）
const f1Row = flUi.rowHtml({ node: FL_TREE.items[0], depth: 0 },
  { addCount: 0, selectedId: 'f1' });
check(f1Row.includes('旅行') && f1Row.includes('1 枚'),
  `行に名前と枚数: ${f1Row}`);
check(f1Row.includes('class="fl-row on"'), '選んでいる行に印を付ける');
check(!f1Row.includes('ここに入れる'), 'add= が無いときは「ここに入れる」を出さない');
const f1Add = flUi.rowHtml({ node: FL_TREE.items[0], depth: 0 }, { addCount: 2 });
check(f1Add.includes('ここに入れる'), `add= があるときだけ入れる口を出す: ${f1Add}`);
check(flUi.rowHtml({ node: { id: 'x', name: '深い', kind: 'manual', count: 0 }, depth: 2 })
  .includes('padding-left:36px'), '深さ 2 は 36px 字下げする');
check(flUi.treeHtml(FL_TREE, { addCount: 1 }).includes('海')
  && flUi.treeHtml(FL_TREE, { addCount: 1 }).includes('1girl だけ'),
  '木の HTML に子とスマートフォルダも出る');
check(flUi.treeHtml({ items: [], total: 0 }).includes('フォルダがまだありません'),
  '木が空なら案内の 1 行を出す');

// 33d. URL の形（`?folder=` / `?add=`）
const flSearch = flUi.parseSearch('folder=f1&add=a1,a2');
check(flSearch.folder === 'f1' && flSearch.add.join(',') === 'a1,a2',
  `URL から選んだフォルダと枚を読む: ${JSON.stringify(flSearch)}`);
check(flUi.folderHref(['a1', 'a2']) === '#/folders?add=a1,a2',
  `入口の行き先: ${flUi.folderHref(['a1', 'a2'])}`);
check(flUi.folderHref([]) === '#/folders', '0 枚ならフォルダの画面だけ開く');

// 33e. 入口（下部バー）の文言。**0 枚のときは枚数を書かない**（C-22）
check(flUi.folderEntryLabel(0) === '選んだ画像をフォルダに入れる…',
  `0 枚の文言: ${flUi.folderEntryLabel(0)}`);
check(flUi.folderEntryLabel(3) === '選んだ 3 枚をフォルダに入れる…',
  `3 枚の文言: ${flUi.folderEntryLabel(3)}`);
const flBtn = new El('button', 'btn-folder');
flUi.renderFolderEntry(flBtn, 0);
check(flBtn.disabled === true && !flBtn.textContent.includes('0 枚'),
  '0 枚なら押せない（枚数も書かない）');
flUi.renderFolderEntry(flBtn, 2);
check(flBtn.disabled === false && flBtn.textContent === '選んだ 2 枚をフォルダに入れる…',
  `2 枚なら押せる: ${flBtn.textContent}`);

// 33f. 消す前の確認（**名前を打ち込むまで送らない**）
check(flUi.deleteAskText('旅行').includes('下にフォルダ名を打ち込むと消せます')
  && flUi.deleteAskText('旅行').includes('画像は消えません'),
  `消す前の確認の文: ${flUi.deleteAskText('旅行')}`);
// **子も一緒に消えることを言う**（P2-1 の監査 B-2。`dry_run` の `folders` / `names` から）
const askWithKids = flUi.deleteAskText('旅行', { folders: 3, names: ['旅行', '海', '山'] });
check(askWithKids.includes('下のフォルダ 2 個（海、山）も一緒に消えます'),
  `子を持つフォルダの確認文に数と名前: ${askWithKids}`);
check(!askWithKids.includes('下のフォルダ 2 個も一緒に'), '名前も出す（数だけにしない）');
const askNoKids = flUi.deleteAskText('旅行', { folders: 1, names: ['旅行'] });
check(askNoKids === '「旅行」を消します。下にフォルダ名を打ち込むと消せます。画像は消えません。',
  `子が無いときは子のことを言わない: ${askNoKids}`);
const askManyKids = flUi.deleteAskText('旅行', { folders: 5, names: ['旅行', 'あ', 'い', 'う', 'え'] });
check(askManyKids.includes('下のフォルダ 4 個（あ、い、う ほか 1 個）も一緒に消えます'),
  `名前が多いときは「ほか N 個」でまとめる: ${askManyKids}`);
check(flUi.childFolders({ folders: 2, names: ['旅行', '旅行'] }, '旅行').count === 1
  && flUi.childFolders({ folders: 2, names: ['旅行', '旅行'] }, '旅行').names.join(',') === '旅行',
  '同名の子がいても自分の名前は 1 つだけ除く');
check(flUi.deleteTypedOk('旅行', ' 旅行 ') === true
  && flUi.deleteTypedOk('旅行', '海') === false,
  '打ち込んだ名前は前後の空白を落として比べる');
check(flUi.deletedText('旅行').includes('画像は消えていません'),
  `消した後の 1 行: ${flUi.deletedText('旅行')}`);
const askHtml = flUi.headHtml(FL_TREE.items[0], { confirming: true, typed: '' });
check(askHtml.includes('このフォルダを消す') && /id="fl-del-go"[^>]*disabled/.test(askHtml),
  `名前を打ち込むまで消すボタンは押せない: ${askHtml}`);
check(flUi.headHtml(FL_TREE.items[0], { confirming: true, typed: '旅行' })
  .includes('id="fl-del-go"'), '名前が合えば送れる形になる');
check(!/disabled/.test((flUi.headHtml(FL_TREE.items[0], { confirming: true, typed: '旅行' })
  .match(/<button id="fl-del-go"[^>]*>/) || [''])[0]), '名前が合えば disabled を付けない');
check(flUi.headHtml(FL_TREE.items[0], { renaming: true }).includes('保存する')
  && flUi.headHtml(FL_TREE.items[0], { renaming: true }).includes('やめる'),
  '名前を変える欄は「保存する」「やめる」を出す');
check(flUi.headHtml(null).includes('フォルダを選ぶと'),
  '選んでいないときは案内を出す');
check(flUi.addBannerHtml(3).includes('選んだ 3 枚を入れるフォルダを選んでください'),
  `add= の帯の文: ${flUi.addBannerHtml(3)}`);
check(flUi.addBannerHtml(0) === '', 'add= が無ければ帯を出さない');

// 33g. **押す検査**: 一覧を開く（GET 2 本。書かない）
location.hash = '';
await flUi.showFolders('folder=f1&add=a1,a2');
check(flAsked.includes('GET /api/folders')
  && flAsked.includes('GET /api/folders/f1/assets?limit=200'),
  `開くと木と中身を引く（書かない）: ${flAsked.join(' / ')}`);
check(flWrites.length === 0, `開いただけでは 1 つも書かない: ${JSON.stringify(flWrites)}`);
check(String(el('fl-tree').innerHTML).includes('旅行')
  && String(el('fl-tree').innerHTML).includes('ここに入れる'),
  'add= があるので木に入れる口が出る');
check(String(el('fl-items').innerHTML).includes('/api/assets/a1/thumb?size=256'),
  '中身はサムネイルつきで出る');
check(String(el('fl-items').innerHTML).includes('>外す<'), '中身の行に「外す」がある');
check(el('fl-brief').textContent === 'フォルダ 3 個、画像 1 枚',
  `画面の見出し: ${el('fl-brief').textContent}`);
check(String(el('fl-add-banner').innerHTML).includes('選んだ 2 枚'),
  '入れる先を選ぶ帯を出す');
check(String(el('fl-head').innerHTML).includes('名前を変える')
  && String(el('fl-head').innerHTML).includes('フォルダを消す…'),
  '選んだフォルダの操作が出る');

// 33h. **押す検査**: 木の行を押すと中身が変わる（GET だけ）
flAsked = [];
await flUi.onClick({ target: hitOf('.fl-row', { id: 'f2' }) });
check(location.hash === '#/folders?folder=f2' || location.hash === '#/folders?folder=f2&add=a1,a2',
  `行を押すと選ぶ: ${location.hash}`);
check(flAsked.includes('GET /api/folders/f2/assets?limit=200'), `中身を引き直す: ${flAsked.join(' / ')}`);
check(flAsked.every((line) => line.startsWith('GET')), '行を押しても書かない');

// 33i. **押す検査**: 「ここに入れる」（`add=` の 2 枚を 1 回の POST で入れる）
flAsked = [];
flWrites = [];
flUi.selectFolder('f1');
await flUi.showFolders('folder=f1&add=a1,a2');
const putHit = hitOf('.fl-put', { id: 'f1' });
putHit.closest = (sel) => (sel === '.fl-put' || sel === '.fl-row' ? putHit : null);
await flUi.onClick({ target: putHit });
const addWrites = flWrites.filter((w) => w.method === 'POST' && w.url.endsWith('/members'));
check(addWrites.length === 1, `入れるのは 1 回だけ: ${addWrites.length} 回`);
check(JSON.parse(String(addWrites[0]?.body || '{}')).asset_ids.join(',') === 'a1,a2',
  `選んだ 2 枚を送る: ${String(addWrites[0]?.body)}`);
check(String(el('fl-msg').innerHTML).includes('2 枚をフォルダ「旅行」に入れました。')
  && String(el('fl-msg').innerHTML).includes('1 枚は既に入っていました。'),
  `既に入っていた枚も言う: ${String(el('fl-msg').innerHTML)}`);

// 33j. **押す検査**: 「外す」（`folder_member` の 1 行だけ。**画像は消さない**と言う）
flWrites = [];
await flUi.onClick({ target: hitOf('.fl-remove', { id: 'a1' }) });
const rmWrites = flWrites.filter((w) => w.method === 'DELETE' && w.url.endsWith('/members'));
check(rmWrites.length === 1, `外すのは 1 回だけ: ${rmWrites.length} 回`);
check(JSON.parse(String(rmWrites[0]?.body || '{}')).asset_ids.join(',') === 'a1',
  '外す 1 枚を送る');
check(String(el('fl-msg').innerHTML).includes('1 枚をこのフォルダから外しました。画像は消していません。'),
  `外した後の 1 行: ${String(el('fl-msg').innerHTML)}`);

// 33k. **押す検査**: 作る（1 回の POST。同じ親の同名はサーバの文をそのまま出す）
flWrites = [];
el('fl-new-name').value = '  大阪  ';
await flUi.createFolder();
const madePost = flWrites.filter((w) => w.method === 'POST' && w.url === '/api/folders');
check(madePost.length === 1, `作るのは 1 回だけ: ${madePost.length} 回`);
const madeBody = JSON.parse(String(madePost[0]?.body || '{}'));
check(madeBody.name === '大阪', `前後の空白を落として送る: ${JSON.stringify(madeBody)}`);
check(madeBody.parent_id === 'f1', `選んでいるフォルダの下に作る: ${JSON.stringify(madeBody)}`);
check(String(el('fl-msg').innerHTML).includes('フォルダ「大阪」を作りました。'),
  `作った後の 1 行: ${String(el('fl-msg').innerHTML)}`);
flWrites = [];
el('fl-new-name').value = '旅行';
await flUi.createFolder();
check(String(el('fl-msg').innerHTML).includes('同じ親の下に「旅行」があります'),
  `断られた理由はサーバの文: ${String(el('fl-msg').innerHTML)}`);
check(String(el('fl-msg').innerHTML).includes('fl-bad'), '断られたら失敗の見た目にする');
flWrites = [];
el('fl-new-name').value = '   ';
await flUi.createFolder();
check(flWrites.length === 0 && String(el('fl-msg').innerHTML).includes('フォルダ名を入れてください'),
  '空の名前は送らない');

// 33l. **押す検査**: 名前を変える（1 回の PATCH）
await flUi.showFolders('folder=f1');
flUi.startRename();
el('fl-rename-name').value = '海';
flWrites = [];
await flUi.onClick({ target: hitOf('.fl-rename-go', {}) });
const patchWrites = flWrites.filter((w) => w.method === 'PATCH');
check(patchWrites.length === 1, `名前を変えるのは 1 回だけ: ${patchWrites.length} 回`);
check(JSON.parse(String(patchWrites[0]?.body || '{}')).name === '海', '新しい名前を送る');
check(String(el('fl-msg').innerHTML).includes('名前を変えました。'),
  `変えた後の 1 行: ${String(el('fl-msg').innerHTML)}`);

// 33m. **押す検査**: 消す（**名前が違えば送らない**。合っていれば 1 回）
await flUi.showFolders('folder=f1');
flAsked = [];
await flUi.startDelete();
check(flAsked.includes('DELETE /api/folders/f1?dry_run=true'),
  `消える範囲を先に読む（子の数と名前。dry_run は消さない）: ${flAsked.join(' / ')}`);
check(String(el('fl-head').innerHTML).includes('下にフォルダ名を打ち込むと消せます'),
  '確認の欄を出す');
flUi.setTyped('違う名前');
flWrites = [];
await flUi.deleteFolder();
check(flWrites.length === 0, `名前が違えば消さない: ${flWrites.length} 回`);
check(String(el('fl-msg').innerHTML).includes('フォルダ名が違います'),
  `違う名前のときの 1 行: ${String(el('fl-msg').innerHTML)}`);
flUi.setTyped('旅行');
await flUi.deleteFolder();
const delWrites = flWrites.filter((w) => w.method === 'DELETE' && w.url === '/api/folders/f1');
check(delWrites.length === 1, `名前が合えば 1 回だけ消す: ${delWrites.length} 回`);
check(JSON.parse(String(delWrites[0]?.body || '{}')).confirm === '旅行',
  '確認の名前を送る（サーバでも確かめる）');
check(String(el('fl-msg').innerHTML).includes('画像は消えていません'),
  `消した後の 1 行: ${String(el('fl-msg').innerHTML)}`);

// 33n. スマートフォルダは**黙って空にしない**（1 行でそう言う）
await flUi.showFolders('folder=f3');
check(String(el('fl-items').innerHTML).includes('スマートフォルダの条件はまだ使えません'),
  `スマートフォルダの中身の注記: ${String(el('fl-items').innerHTML)}`);

// 33o. 押している間は押せない（二度押しで POST を 2 回出さない。P8-5 の監査 C-1）
const busyRow = flUi.rowHtml({ node: FL_TREE.items[0], depth: 0 },
  { addCount: 1, busy: true });
check(/<button class="fl-put"[^>]*disabled/.test(busyRow),
  'busy の間は「ここに入れる」を押せない');
check(flUi.treeHtml({ items: [], total: 0 }).includes('fl-note'),
  '木が空のときは案内を 1 行（行を作らない）');

console.log(failures.length ? `\n${failures.length} 件 NG` : '\nすべて ok');
process.exit(failures.length ? 1 : 0);
