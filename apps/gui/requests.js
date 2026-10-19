// 要求の一覧（`#/requests`。P6-1b）
// 設計: docs/p6-design.md §5.1（一覧）・§5.2（詳細は一覧の中で開く）・§3.3（一覧 API）、
//       docs/frontend-design.md §4.4（要求のカード）・§6（文言）・§7（状態）
//
// 約束:
// - **`ask` / `conditions` / `origin` / `ai_note` はエージェントの自由文**。必ず `esc()` を通す
// - **「あとで」は何も書かない**（既読の概念を作らない。§5.1 / 点検 C6）
// - **断るには理由が要る**（空なら送らない。§5.1）
// - **画面を奪わない**: この画面は `#/requests` で明示的に開いたときだけ出す
// - 状態は URL に持つ（`#/requests?state=all` / `#/requests?open=<id>`）。戻る・再読込に耐える

const API = '/api/review-requests';
const MAX_INDEX_FETCH = 20;      // AI の推しの「何番目」を出すために groups を引く上限（下の注記）

// **（A-1）** 時刻の形は画面で 1 つ（`pending.js` の `fmtWhen` を借りる。`2026-10-19 02:31`）
import { fmtWhen } from './pending.js';

const $ = (id) => document.getElementById(id);

const state = {
  items: [],
  counts: {},
  view: 'open',        // open | all
  openId: null,        // 詳細を開いている要求
  targets: {},         // request_id -> 対象の asset_id（並びが分かるものだけ）
  order: {},           // request_id -> [asset_id, ...]（AI の推しの番号を出すため）
  loading: false,
  error: null,
};

let wired = false;

function esc(value) {
  return String(value ?? '').replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// `state=all&open=x` を読む（`#/requests?…` の ? 以降を渡す）
export function query(search) {
  const out = {};
  for (const part of String(search || '').replace(/^[?#]/, '').split('&')) {
    if (!part) continue;
    const at = part.indexOf('=');
    const key = decodeURIComponent(at < 0 ? part : part.slice(0, at));
    out[key] = at < 0 ? '' : decodeURIComponent(part.slice(at + 1).replace(/\+/g, ' '));
  }
  return out;
}

// 「3 分前」（`frontend-design.md` §4.4 の経過）
export function agoText(iso, now = Date.now()) {
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return '';
  const sec = Math.max(0, Math.round((now - at) / 1000));
  if (sec < 60) return `${sec} 秒前`;
  if (sec < 3600) return `${Math.floor(sec / 60)} 分前`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} 時間前`;
  return `${Math.floor(sec / 86400)} 日前`;
}

// **（ワーディング監査 W-54）** 状態の語の形を揃える（名詞で揃える。動詞の過去形を混ぜない）
const STATE_LABEL = { open: '未対応', done: '決定', declined: '断り', superseded: '差し替え' };

// **（ワーディング監査 W-9）** `wants` の値を日本語のラベルに写す（契約の値は英語のまま）
const WANTS_LABEL = {
  selected_ids: '選ぶ画像', reason: '理由', annotations: '注記', asset_ids: '画像', memo: 'メモ',
};

// AI の推しが何番目か（1 始まり）。
// **サーバの `ai.pick_index` を使う**（P6-1a の監査 C1 で契約に足した）。無ければ
// 対象の並び（`state.order`。`fillOrder()` が引く）から数える＝古い応答へのフォールバック
export function pickIndex(item) {
  const given = (item.ai || {}).pick_index;
  if (typeof given === 'number' && given > 0) return given;
  const pick = (item.ai || {}).pick_asset_id;
  const order = state.order[item.id];
  if (!pick || !order) return null;
  const at = order.indexOf(pick);
  return at < 0 ? null : at + 1;
}

// カード 1 枚（`frontend-design.md` §4.4）
export function cardHtml(item) {
  const conditions = (item.conditions || []).filter(Boolean);
  const pick = (item.ai || {}).pick_asset_id || null;
  const note = (item.ai || {}).note || null;
  const index = pickIndex(item);
  const aiLine = pick
    ? `<div class="req-ai">AI の推し${index ? `: ${index} 番` : ''}`
      + `<img src="/api/assets/${esc(pick)}/thumb?size=256" alt="">`
      + (note ? `<span class="req-note">「${esc(note)}」</span>` : '')
      + '<span class="req-draft">これは下書きです。決めるのは人です。</span></div>'
    : '';
  // **（C-16・G-1）** 押すと何かが起きるボタンは終止形（「断る」は終止形でよい）
  const buttons = item.state === 'open'
    ? '<div class="req-actions">'
      + `<button class="req-open" data-group="${esc(item.group_id)}">開いて決める</button>`
      + '<button class="req-later">あとで</button>'
      + '<button class="req-decline">断る</button>'
      + '</div>'
      + '<div class="req-decline-form" hidden>'
      + '<div class="req-decline-why">断る理由を書いてください。エージェントはこれを読んで次の手を決めます。</div>'
      + '<textarea class="req-decline-note" rows="2" placeholder="例: この 3 枚は別のカットなので、まとめて選べません"></textarea>'
      + '<button class="req-decline-send">断る</button>'
      + '</div>'
    : '';
  // **（B-8）** 決めた枚の**番号が引けるときは「N 番に決めました」**（まとまりレビューの帯と同じ語）。
  // 引けないときだけ「1 枚を選びました」（要求のカードは枚数しか分からないことがある）
  const closed = item.state === 'done' && item.response
    ? (() => {
      const sel = (item.response.selected_asset_ids || [])[0] || null;
      const order = state.order[item.id] || [];
      const at = sel ? order.indexOf(sel) + 1 : 0;
      const how = at > 0 ? `（${at} 番に決めました）` : (sel ? '（1 枚を選びました）' : '');
      return `<div class="req-closed">この要求は閉じました${how}。エージェントがここを読みます。</div>`;
    })()
    : '';
  const declined = item.state === 'declined'
    ? `<div class="req-declined">断りました: ${esc(item.decline_note || '（なし）')}</div>` : '';
  const superseded = item.state === 'superseded' && item.superseded_by
    ? '<div class="req-superseded">同じ対象の新しい要求で差し替わりました。前の要求はここに残っています。'
      + `<a href="#/requests?state=all&open=${esc(item.superseded_by)}">新しい要求を開く</a></div>` : '';
  const detail = state.openId === item.id
    ? '<div class="req-detail">'
      + `<div class="req-line"><span class="k">用件</span>${esc(item.ask || '（用件なし）')}</div>`
      + `<div class="req-line"><span class="k">見てほしいこと</span>${conditions.length ? conditions.map(esc).join(' / ') : '（なし）'}</div>`
      // **（ワーディング監査 W-55）** 「どこから」だけ砕けていた。ほかの見出しと同じ漢語に揃える
      + `<div class="req-line"><span class="k">出どころ</span>${esc(item.origin || '（なし）')}</div>`
      // **（ワーディング監査 W-9。D-17）** `wants` の値を英語のまま出さない（§6.1 の規則 4）。
      // 「応答に求めるもの」は硬いので「返してほしいもの」にする
      + `<div class="req-line"><span class="k">返してほしいもの</span>${(item.wants || []).map((w) => esc(WANTS_LABEL[w] || `その他（${w}）`)).join(' / ') || '（なし）'}</div>`
      + `<div class="req-line"><span class="k">まとまり</span><a href="#/group/${esc(item.group_id)}">${esc(item.group_id)}</a></div>`
      // **（A-1）** 閉じた時刻も画面の形（現地の `2026-10-19 02:31`）に揃える
      + (item.closed_at ? `<div class="req-line"><span class="k">閉じた時刻</span>${esc(fmtWhen(item.closed_at))}（${esc(item.closed_by || '—')}）</div>` : '')
      + '</div>'
    : '';
  // **カードの外側（`.req-card` の枠）は `render()` が作る**（ここは中身だけ）。
  // 入れ子にすると同じ class が二重になり、`querySelectorAll('.req-card')` が 2 倍返る
  return `<div class="req-head"><span class="req-ask">${esc(item.ask || '（用件なし）')}</span>`
    + `<span class="req-ago">${esc(agoText(item.created_at))}</span></div>`
    + `<div class="req-cond">見てほしいこと: ${conditions.length ? conditions.map(esc).join(' / ') : '（なし）'}</div>`
    + (item.origin ? `<div class="req-origin">${esc(item.origin)}</div>` : '')
    + aiLine + closed + declined + superseded + detail + buttons
    + `<div class="req-state">${esc(STATE_LABEL[item.state] || item.state)}</div>`;
}

function render() {
  const list = $('req-list');
  if (!list) return;
  const items = state.items;
  $('req-empty').hidden = items.length > 0 || !!state.error;
  // **（C-8）** 英語の例外文は本文に出さず、次の一手を添える（§6.1 の規約 3）
  $('req-empty').textContent = state.error
    ? `要求を読めませんでした。もう一度試してください（詳細: ${state.error}）。`
    : 'エージェントからの要求はありません。要求が来るとここに出ます。';
  $('req-brief').textContent = state.loading ? '読み込み中…'
    : `${Number(items.length).toLocaleString('ja-JP')} 件${state.counts.open ? `（未対応 ${Number(state.counts.open).toLocaleString('ja-JP')}）` : ''}`;
  // カードは**要素として**組む（`innerHTML` の文字列だけにすると、軽い DOM の身代わり
  // 〔`tools/gui_smoke.mjs`〕が中身を拾えない。`compare.js` のタイルと同じ流儀）
  list.innerHTML = '';
  for (const item of items) {
    const card = document.createElement('div');
    card.className = 'req-card';
    card.dataset.request = item.id;
    card.innerHTML = cardHtml(item);
    wireCard(card);
    list.appendChild(card);
  }
}

function wireCard(card) {
  const open = card.querySelector('.req-open');
  if (open) {
    open.addEventListener('click', (event) => {
      event.stopPropagation();
      location.hash = `#/group/${open.dataset.group}`;
    });
  }
  const later = card.querySelector('.req-later');
  if (later) {
    // 「あとで」は**何も書かない**（既読を作らない。§5.1 / 点検 C6）
    later.addEventListener('click', (event) => event.stopPropagation());
  }
  const decline = card.querySelector('.req-decline');
  const form = card.querySelector('.req-decline-form');
  const note = card.querySelector('.req-decline-note');
  const send = card.querySelector('.req-decline-send');
  if (decline && form) {
    decline.addEventListener('click', (event) => {
      event.stopPropagation();
      form.hidden = false;
    });
  }
  if (form) {
    // 監査 A1（P6-1b）: **フォームの中のクリックをカードに伝えない**。伝えるとカードの
    // `click`（詳細の開閉）が走って一覧を描き直し、開いたフォームごと消える——
    // マウスだけでは理由を書けなくなる（textarea に caret を置くクリックで起きる）
    form.addEventListener('click', (event) => event.stopPropagation());
  }
  if (send && note && form) {
    send.addEventListener('click', async (event) => {
      event.stopPropagation();
      const id = card.dataset.request;
      const text = String(note.value || '').trim();
      if (!text) return;                       // 空なら送らない（§5.1）
      send.disabled = true;
      try {
        await fetch(`${API}/${id}/decline`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' },
          body: JSON.stringify({ note: text }),
        });
      } finally {
        send.disabled = false;
      }
      await load();
    });
  }
  card.addEventListener('click', () => {
    state.openId = state.openId === card.dataset.request ? null : card.dataset.request;
    render();
  });
}

// 表示中の要求について、対象の並び（AI の推しの番号）を引く。
// **ふつうは引かない**: 一覧 API が `ai.pick_index` を返す（P6-1a の監査 C1）ので、
// サーバが古い（`pick_index` が無い）ときだけ、先頭 `MAX_INDEX_FETCH` 件について
// `GET /api/groups/{id}` で並びを引く（番号が出せないだけ。一覧は出す）
async function fillOrder(items) {
  const need = items
    .filter((item) => typeof (item.ai || {}).pick_index !== 'number')
    .slice(0, MAX_INDEX_FETCH);
  if (!need.length) return;
  await Promise.all(need.map(async (item) => {
    try {
      const res = await fetch(`/api/groups/${encodeURIComponent(item.group_id)}`);
      if (!res.ok) return;
      const group = await res.json();
      state.order[item.id] = (group.items || []).map((row) => row.asset_id);
    } catch (error) {
      // 番号が出せないだけ（一覧は出す）
    }
  }));
}

async function load() {
  // 世代番号: **古い load の描画を捨てる**（`route()` と再読込が重なると、
  // 先に始まった load の `finally` が後から描いて、カードが二重に並ぶことがあった）
  const mine = (load.generation = (load.generation || 0) + 1);
  state.loading = true;
  state.error = null;
  render();
  const params = new URLSearchParams();
  if (state.view !== 'open') params.set('state', state.view);
  params.set('limit', '50');
  try {
    const res = await fetch(`${API}?${params.toString()}`);
    if (!res.ok) throw new Error(`${res.status}`);
    const body = await res.json();
    if (mine !== load.generation) return;
    state.items = body.items || [];
    state.counts = body.counts || {};
    state.order = {};
    await fillOrder(state.items);
    if (mine !== load.generation) return;
  } catch (error) {
    if (mine !== load.generation) return;
    state.items = [];
    state.error = error.message;
  } finally {
    if (mine === load.generation) {
      state.loading = false;
      render();
    }
  }
}

export async function showRequests(search) {
  const q = query(search);
  state.view = q.state === 'all' ? 'all' : 'open';
  state.openId = q.open || null;
  document.body.classList.add('requests');
  const tabs = $('req-tabs');
  if (tabs) {
    tabs.innerHTML = '';
    for (const view of ['open', 'all']) {
      const tab = document.createElement('button');
      tab.className = `req-tab${state.view === view ? ' on' : ''}`;
      tab.dataset.view = view;
      tab.textContent = view === 'open' ? '未対応' : 'すべて';
      tab.addEventListener('click', () => {
        state.view = view;
        state.openId = null;
        location.hash = `#/requests?state=${view}`;
      });
      tabs.appendChild(tab);
    }
  }
  await load();
}

export function hideRequests() {
  document.body.classList.remove('requests');
  state.items = [];
  state.error = null;
}

export function wireRequests() {
  if (wired) return;
  wired = true;
  const back = $('req-again');
  if (back) back.addEventListener('click', () => load());
}
