// 記録の一覧（`#/recipes`。P7-4）
// 設計: docs/p7-design.md §5.4（一覧は**要約だけ**。点検 G-6-(a)）/ §3.1（`GET /api/recipes`）/
//       docs/frontend-design.md §4.11
//
// 約束:
// - **`GET` は書かない**（開くだけでは行が増えない）
// - **要約だけ**を出す（`env` / `record` は 1 枚の口。重い物を一覧に載せない）
// - `esc()` を必ず通す

import { STATUS_LABEL, esc, REASON_LABEL } from './recipe.js';

const $ = (id) => document.getElementById(id);

const state = { items: [], status: 'all', next: null };

const reasonText = (kind) => REASON_LABEL[kind] || String(kind);

/** 判定で絞る（`?status=` は口が受け取る）。 */
export function query(search) {
  const params = new URLSearchParams(search || '');
  const status = params.get('status') || 'all';
  return { status: ['exact', 'approx', 'impossible'].includes(status) ? status : 'all' };
}

export function rowHtml(item) {
  const status = item.status || 'missing';
  const cls = status === 'exact' ? 'ok' : status === 'approx' ? 'warn' : 'bad';
  const reasons = (item.reasons || []).slice(0, 3).map(reasonText).join(' / ');
  return `<div class="rl-row" data-recipe="${esc(item.recipe_id)}">`
    + `<a class="rl-open" href="#/asset/${esc(item.asset_id)}/recipe">`
    + `<span class="rc-badge ${esc(cls)}">${esc(STATUS_LABEL[status] || status)}</span>`
    + `<span class="rl-name">${esc(item.asset_id)}</span></a>`
    + `<span class="rl-reason">${esc(reasons || '—')}</span>`
    + `<span class="rl-when">${esc(item.created_at || '')}</span>`
    + '</div>';
}

export function listHtml() {
  const rows = state.items.length
    ? state.items.map(rowHtml).join('')
    : '<div class="note">この条件の記録はありません。</div>';
  const more = state.next
    ? `<div class="rl-more"><button id="rl-more">次の 50 件を読む</button></div>` : '';
  return `<div class="rl-head">${esc(String(state.items.length))} 件`
    + `（判定: ${esc(state.status === 'all' ? 'すべて' : (STATUS_LABEL[state.status] || state.status))}）</div>`
    + `<div class="rl-rows">${rows}</div>${more}`;
}

async function load() {
  const params = new URLSearchParams({ limit: '50' });
  if (state.status !== 'all') params.set('status', state.status);
  if (state.next) params.set('cursor', state.next);
  const res = await fetch(`/api/recipes?${params.toString()}`);
  const got = res.ok ? await res.json() : { items: [] };
  const items = got.items || [];
  // **「次の 50 件」は足す**（置き換えない。P4-3 の監査 C-2 と同じ）
  state.items = state.next ? [...state.items, ...items] : items;
  state.next = got.next_cursor || null;
  render();
}

function render() {
  const list = $('recipes-list');
  if (list) list.innerHTML = listHtml();
  const brief = $('recipes-brief');
  if (brief) {
    brief.textContent = state.status === 'all' ? 'すべての判定'
      : `判定: ${STATUS_LABEL[state.status] || state.status}`;
  }
  const help = $('recipes-help');
  if (help) help.textContent = '記録の要約です。中身（環境の写し・条件の全体）は 1 枚の画面で見ます。';
}

export async function showRecipes(search) {
  state.status = query(search).status;
  state.items = [];
  state.next = null;
  document.body.classList.add('recipelist');
  render();
  await load();
}

export function hideRecipes() {
  document.body.classList.remove('recipelist');
}

export function wireRecipes() {
  const toggle = $('recipes-status');
  if (toggle) {
    toggle.addEventListener('click', () => {
      const order = ['all', 'exact', 'approx', 'impossible'];
      state.status = order[(order.indexOf(state.status) + 1) % order.length];
      state.items = [];
      state.next = null;
      location.hash = state.status === 'all' ? '#/recipes' : `#/recipes?status=${state.status}`;
    });
  }
  const list = $('recipes-list');
  if (list) {
    list.addEventListener('click', (event) => {
      if (event.target.id !== 'rl-more') return;
      event.preventDefault();
      load();
    });
  }
}
