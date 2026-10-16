// 語の一覧（`#/tags`。P4-3）
// 設計: docs/p4-design.md §5.2（語の一覧・検索・語釈の確認と修正・訳す・一括タグ付けの入口）/
//       §3.6（`GET /api/tags`。**既定は known=1**）/ §3.5（語釈の口）/ docs/frontend-design.md §4.13
//
// 約束:
// - **`GET` は訳さない**（§0.10）。訳すのは `POST /api/tags/gloss` だけ
// - **`known` の既定は `1`**（点検 §I-2。実データでは件数順の上位が品質語で埋まる）
// - `esc()` を必ず通す

const API = '/api/tags';
const GLOSS_LIMIT = 20;

// カテゴリの呼び名は 1 枚の欄と揃える（`tags.js`。**画面の語は 1 つ**）
import { CATEGORY_LABEL } from './tags.js';
const categoryText = (item) =>
  CATEGORY_LABEL[item.category] || (item.category_name ? String(item.category_name) : '—');

const $ = (id) => document.getElementById(id);

const state = { q: '', known: '1', items: [], total: 0, counts: {}, selected: null, busy: false,
                next: null };

const KNOWN_LABEL = { 1: '語彙あり', 0: '語彙外', all: 'すべて' };

export function esc(value) {
  return String(value ?? '').replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

/** `#/tags?q=...&known=...` を読む。 */
export function query(search) {
  const params = new URLSearchParams(search || '');
  return { q: params.get('q') || '', known: params.get('known') || '1' };
}

export function rowHtml(item) {
  const gloss = item.gloss
    ? `<span class="tl-gloss">${esc(item.gloss)}${item.gloss_edited ? '<span class="tg-edited">直した</span>' : ''}</span>`
    : '<span class="tl-none">語釈なし</span>';
  const unknown = item.known === false ? '<span class="tg-unknown">語彙外</span>' : '';
  return `<div class="tl-row${state.selected === item.name ? ' on' : ''}" data-name="${esc(item.name)}" data-id="${esc(String(item.tag_id))}">`
    + `<span class="tl-name">${esc(item.name)}</span>${unknown}`
    + `<span class="tl-count num">${esc(String(item.uses))} 枚</span>`
    + `<span class="tl-cat">${esc(categoryText(item))}</span>`
    + gloss
    + '</div>';
}

export function listHtml() {
  const head = `${state.items.length} / ${state.total} 語`
    + `（語彙あり ${state.counts.known ?? 0} ・ 語彙外 ${state.counts.unknown ?? 0}）`;
  const rows = state.items.length
    ? state.items.map(rowHtml).join('')
    : '<div class="note">この条件の語はありません。</div>';
  // **P4-3 の監査 C-2**: 200 語で打ち切らず、続きを読めるようにする（`next_cursor`）。
  // 設計 §10-11 は「上位 200 語・残りは検索」だが、頭に「200 / 291」と出るのに
  // 続きが無いと分からないので、1 つだけ足す
  const more = state.next
    ? `<div class="tl-more"><button id="tl-more">次の 200 語を読む</button>`
      + `<span class="stat">いま ${state.items.length} 語。残りは検索でも届きます。</span></div>`
    : '';
  return `<div class="tl-head">${esc(head)}</div><div class="tl-rows">${rows}</div>${more}`;
}

function detailHtml(item) {
  if (!item) return '<div class="note">左の語を選ぶと、語釈を確認して直せます。</div>';
  const gloss = item.gloss || '';
  return `<div class="tl-detail-name">${esc(item.name)}`
    + `<span class="tl-count num">${esc(String(item.uses))} 枚</span>`
    + `<span class="tl-cat">${esc(categoryText(item))}</span></div>`
    + `<div class="stat">${item.gloss ? (item.gloss_edited ? '人が直した語釈です。' : '自動で訳した語釈です。直せます。') : '日本語の語釈はまだありません。'}</div>`
    + `<textarea id="tl-ja" rows="2" placeholder="日本語の語釈（例: 長い髪）">${esc(gloss)}</textarea>`
    + '<div class="tl-detail-actions">'
    + '<button id="tl-save">保存</button>'
    + `<button id="tl-translate">訳す</button>`
    + '<span class="stat" id="tl-msg"></span></div>'
    + '<div class="tg-help">訳は自動です。直すと `edited` が立ち、訳し直しでも上書きされません。</div>';
}

async function fetchPage({ cursor = null } = {}) {
  const params = new URLSearchParams({ known: state.known, limit: '200' });
  if (state.q) params.set('q', state.q);
  if (cursor) params.set('cursor', cursor);
  const body = await (await fetch(`${API}?${params}`)).json();
  return { items: body.items || [], total: body.total || 0, counts: body.counts || {},
           next: body.next_cursor || null };
}

function render() {
  const list = $('tags-list');
  if (list) list.innerHTML = listHtml();
  const detail = $('tags-detail');
  if (detail) {
    const item = state.items.find((it) => it.name === state.selected) || null;
    detail.innerHTML = detailHtml(item);
    wireDetail(item);
  }
  const brief = $('tags-brief');
  if (brief) brief.textContent = KNOWN_LABEL[state.known] || state.known;
  const back = $('tags-known');
  if (back) back.textContent = `表示: ${KNOWN_LABEL[state.known] || state.known}`;
  const more = $('tl-more');
  if (more) more.addEventListener('click', loadMore);
}

async function load() {
  const page = await fetchPage();
  state.items = page.items;
  state.total = page.total;
  state.counts = page.counts;
  state.next = page.next;
  render();
}

/** 「次の 200 語を読む」（**足す**。置き換えない）。 */
async function loadMore() {
  if (!state.next || state.busy) return;
  state.busy = true;
  try {
    const page = await fetchPage({ cursor: state.next });
    state.items = state.items.concat(page.items);
    state.total = page.total;
    state.counts = page.counts;
    state.next = page.next;
  } finally {
    state.busy = false;
    render();
  }
}

function wireDetail(item) {
  const ja = $('tl-ja');
  const save = $('tl-save');
  const translate = $('tl-translate');
  const msg = (text, bad) => {
    const el = $('tl-msg');
    if (el) { el.textContent = text; el.classList.toggle('bad', Boolean(bad)); }
  };
  if (save && ja && item) {
    save.addEventListener('click', async () => {
      const value = ja.value.trim();
      if (!value) { msg('日本語を入れてください', true); return; }
      const res = await fetch(`${API}/${item.tag_id}/gloss`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' },
        body: JSON.stringify({ ja: value }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) { msg(body.detail || `保存できません（${res.status}）`, true); return; }
      // **P4-3 の監査 B-2**: `load()` は詳細を `innerHTML` で作り直すので、
      // **先に描き直してから**知らせる（前は知らせた直後に消えていた）
      await load();
      msg('保存しました（人が直した語釈になります）。');
    });
  }
  if (translate && item) {
    translate.addEventListener('click', async () => {
      // **P4-3 の監査 A-2**: `tag_id` を渡す（名前を渡すと `Number()` が `NaN` になり
      // `tag_ids: []` → **必ず 422** になっていた）
      const got = await translateIds([item.tag_id]);
      await load();                       // 先に描き直す（監査 B-2）
      msg(got.ok ? `${(got.translated || []).length} 語を訳しました。` : got.detail, !got.ok);
    });
  }
}

/** 語釈を作る（**`tag_id` の配列**を渡す）。**DOM は触らない**（知らせは呼んだ側が `load()` の後に出す。監査 B-2）。 */
async function translateIds(ids) {
  const tagIds = ids.map((n) => Number(n)).filter((n) => Number.isFinite(n));
  if (!tagIds.length) return { ok: false, detail: '訳す語がありません' };
  const res = await fetch('/api/tags/gloss', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' },
    body: JSON.stringify({ tag_ids: tagIds, limit: GLOSS_LIMIT }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) return { ok: false, detail: body.detail || `訳せません（${res.status}）` };
  return { ok: true, ...body };
}

async function translatePending() {
  const pending = state.items.filter((it) => !it.gloss).slice(0, GLOSS_LIMIT);
  if (!pending.length) { const el = $('tl-msg'); if (el) el.textContent = '語釈の無い語がありません。'; return; }
  const got = await translateIds(pending.map((it) => it.tag_id));
  // **知らせは `load()` の後**（監査 B-2。先に出すと描き直しで消える）
  await load();
  const el = $('tl-msg');
  if (el) el.textContent = got.ok ? `${(got.translated || []).length} 語を訳しました。` : got.detail;
}

/** 一括タグ付け（条件を入れて `POST /api/assets/tag` → `#/jobs` へ）。 */
async function startJob() {
  const limit = Number($('tl-job-limit')?.value || 0);
  const engine = $('tl-job-engine')?.value || 'auto';
  const force = Boolean($('tl-job-force')?.checked);
  const msg = $('tl-job-msg');
  const res = await fetch('/api/assets/tag', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ engine, limit, force }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) { if (msg) msg.textContent = body.detail || `始められません（${res.status}）`; return; }
  if (!body.job_id) { if (msg) msg.textContent = '付ける対象がありませんでした。'; return; }
  location.hash = '#/jobs';
}

export async function showTags(search) {
  const parsed = query(search);
  state.q = parsed.q;
  state.known = parsed.known;
  document.body.classList.add('taglist');
  const input = $('tags-q');
  if (input) input.value = state.q;
  await load();
}

export function hideTags() {
  document.body.classList.remove('taglist');
}

export function wireTags() {
  const form = $('tags-search');
  if (form) {
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const q = ($('tags-q')?.value || '').trim();
      location.hash = `#/tags?known=${state.known}${q ? `&q=${encodeURIComponent(q)}` : ''}`;
    });
  }
  const knownBtn = $('tags-known');
  if (knownBtn) {
    knownBtn.addEventListener('click', () => {
      state.known = state.known === '1' ? '0' : state.known === '0' ? 'all' : '1';
      location.hash = `#/tags?known=${state.known}${state.q ? `&q=${encodeURIComponent(state.q)}` : ''}`;
    });
  }
  const list = $('tags-list');
  if (list) {
    list.addEventListener('click', (event) => {
      const row = event.target.closest('.tl-row');
      if (!row) return;
      state.selected = row.dataset.name;
      load();
    });
  }
  const translate = $('tags-translate');
  if (translate) translate.addEventListener('click', translatePending);
  const start = $('tags-start');
  if (start) start.addEventListener('click', startJob);
}
