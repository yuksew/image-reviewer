#!/usr/bin/env node
// 比較画面（`apps/gui/compare.js`）の**描いた文字列**を、ブラウザ無しで確かめる
// （監査 C1・B2、監査 A1、P5-3 の差分ヒートマップと似ている順）。
//
// 見ているもの（見ていないもの）:
// - 見る: `renderStage()` / `renderDiff()` が作った HTML 文字列（基準の印・「基準にする」・
//   分からないセル・`changed` だけを描くこと・並び順・差分の理由と強制）と、
//   マウス / キーで `base=` が書き換わること、
//   **キーを 1 つも押さずに「強制して出す」へ届くこと**（監査 A1。
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
check(diffHtml.includes('badge incomplete') && diffHtml.includes('一部不明'),
  '分からない枚がある行に印が出る（監査 B2）');
check(diffHtml.includes('class="cell unknown"') && diffHtml.includes('分からない'),
  '分からないセルを「分からない」と描く（監査 B2）');
check(diffHtml.includes('前置語: (masterpiece'), '分かっている前置語を添えている（監査 B2）');
check(!/class="cell unknown"[^>]*>—</.test(diffHtml), '分からないセルを「無い（—）」と描かない');
check(diffHtml.includes('訳が未捕獲（分からない）'), '語の差分に「分からない」を出す');
check(diffHtml.includes('訳が未捕獲の枚がある'), '語の差分の要約が「同じ」と言わない');
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
  '出せる組でも「強制して出す」を出しておく（監査 C1。同じ seed でも 85 組中 81 組は合わない）');

// 「同じ seed」は「合う」の予測ではない（監査 C1）。言い切らない文言になっているか
FIXTURE.pairs[0].same_seed = true;
await showCompare(`ids=${A},${B}`);
check(el('cmp-heatwhy').textContent.includes('同じ seed')
  && el('cmp-heatwhy').textContent.includes('出してみるまで'),
  `同じ seed では言い切らない（監査 C1）: ${el('cmp-heatwhy').textContent}`);
FIXTURE.pairs[0].same_seed = false;
check(visible('cmp-heatforce'),
  '出せる組でも「強制して出す」を出しておく（監査 C1。同じ seed でも 85 組中 81 組は合わない）');

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
  'キーを押さなくても「強制して出す」が見えている（監査 A1）');
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

// 「強制して出す」を**マウスで**押す → 組の口を叩く
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
  '語釈の行に括弧を足さない（§8.2-1）');
check(rowWithGloss.includes('rem_(re:zero)') === false && tagsUi.wordRowHtml(words[0]).includes('rem_(re:zero)'),
  '語そのものの括弧は消さない（点検 A-1）');
check(rowNoGloss.includes('日本語の語釈はまだありません。') && rowNoGloss.includes('tg-translate'),
  '語釈が無ければ文と「訳す」を出す（§8.2-2）');
check(!rowWithGloss.includes('日本語の語釈はまだありません。'),
  '語釈があれば「まだありません」を出さない（§8.2-2）');

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
  '語釈の `<script>` を生のまま出さない（§8.2-7）');

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
check(tagsUi.panelHtml(TAG_PANEL).includes('タガーは下ごしらえです'),
  'タガーの限界の 1 行を出す（§5.1）');
check(tagsUi.briefHtml(TAG_PANEL).includes('語釈待ち 3 語'),
  `語釈待ちの数を出す: ${tagsUi.briefHtml(TAG_PANEL)}`);

const running = { id: 'j1', kind: 'tag', state: 'running', progress: { done: 3, total: 10 },
                  counts: { tagged: 3, skipped: 0, failed: 0 }, note: null, message: null,
                  started_at: new Date(Date.now() - 3000).toISOString(), finished_at: null,
                  items_failed: [{ ref: 'a1', error: '実体がありません' }] };
const jobHtml = jobsUi.jobHtml(running);
check(jobHtml.includes('3 / 10'), 'ジョブの進行を出す（§8.2-8）');
check(jobHtml.includes('残り 約'), '残り時間を出す（§8.2-8）');
check(jobHtml.includes('実行中') && jobHtml.includes('中断'), '実行中は中断を出す');
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

console.log(failures.length ? `\n${failures.length} 件 NG` : '\nすべて ok');
process.exit(failures.length ? 1 : 0);
