// フォルダ（カタログ。`#/folders`。P2-1）
// 設計: docs/design.md §5.3（表）・§6.1（口 8 本）・§10.1（多対多。**実ファイルは動かさない**）・
//       docs/frontend-design.md §3（画面の一覧 14）・§4.5.1（上部バー）・§6（文言）・§11（フォルダの画面）
//
// 約束:
// - **`GET` は 1 バイトも書かない**（読むのは `/api/folders` と `/api/folders/{id}/assets` だけ。
//   書くのは押したときだけ）
// - **書く口は人だけ**（`X-Image-Reviewer-Actor: human` を付ける。付け忘れると 403 `human_only`）
// - **消すのは名前を打ち込ませてから**（仮想フォルダは作り直せない分類。§6.1 の `confirm` と同じ語）
// - **画像は入れても外しても消えない・動かない**（`folder_member` の行だけ。文でもそう言う）
// - **同じ親の中で同名は 422**（サーバの文をそのまま出す。画面で作り直さない）
// - 書き込むボタンは**押している間 `disabled`**（二度押しで POST を 2 回出さない。P8-5 の監査 C-1）
// - `esc()` を必ず通す。**文は 1 文 40 字まで**（`frontend-design.md` §6.1 の規則 5）

import { esc } from './pending.js';
import { fmtCount } from './counts.js';

const FOLDERS = '/api/folders';
const $ = (id) => document.getElementById(id);

function human() {
  return { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' };
}

// ---- 純関数（`gui_smoke` が固定する）----

/** 木を**描く順**に平らにする（深さつき）。**親の直後に子**（前順）。 */
export function flattenTree(items, depth = 0, out = []) {
  for (const item of Array.isArray(items) ? items : []) {
    out.push({ node: item, depth });
    flattenTree(item.children, depth + 1, out);
  }
  return out;
}

/** 見出しの 1 行（`フォルダ 3 個、画像 12 枚`。**枚は助数詞だけ**。規則 4）。 */
export function briefText(tree) {
  const folders = Number(tree && tree.total) || flattenTree((tree && tree.items) || []).length;
  const images = flattenTree((tree && tree.items) || [])
    .reduce((sum, row) => sum + (Number(row.node.count) || 0), 0);
  return `フォルダ ${fmtCount(folders)} 個、画像 ${fmtCount(images)} 枚`;
}

/** 空の案内（フォルダが無い）。**いまの状態＋次に押す物**の 2 文（規則 3）。 */
export function emptyTreeText() {
  return 'フォルダがまだありません。上の入力に名前を入れて「作る」を押すと、ここに並びます。';
}

/** 空の案内（フォルダの中身が無い）。 */
export function emptyFolderText(addCount = 0) {
  const n = Number(addCount) || 0;
  const lead = n > 0
    ? `選んだ ${fmtCount(n)} 枚を、上の「ここに入れる」でこのフォルダに入れられます。`
    : '一覧で画像を選んで「選んだ画像をフォルダに入れる…」を押すと、ここに入ります。';
  return `このフォルダには画像がありません。${lead}`;
}

/** 木の 1 行。`add=` がある間だけ「ここに入れる」を出す（画面を 2 つ行き来させない）。 */
export function rowHtml(row, opts = {}) {
  const node = row.node || row;
  const depth = Number(row.depth) || 0;
  const add = opts.addCount || 0;
  const busy = Boolean(opts.busy);
  const on = opts.selectedId === node.id;
  const pad = Math.min(depth, 12) * 14;
  const kind = node.kind === 'smart' ? '<span class="fl-kind">条件で選ぶ</span>' : '';
  const put = add > 0
    ? `<button class="fl-put" data-id="${esc(node.id)}"${busy ? ' disabled' : ''}>ここに入れる</button>`
    : '';
  return `<div class="fl-row${on ? ' on' : ''}${node.kind === 'smart' ? ' smart' : ''}"
      data-id="${esc(node.id)}" style="padding-left:${8 + pad}px">
      <span class="fl-name">${esc(node.name)}</span>${kind}
      <span class="fl-count">${fmtCount(node.count || 0)} 枚</span>
      ${put}
    </div>`;
}

/** 木の HTML（空なら 1 行）。 */
export function treeHtml(tree, opts = {}) {
  const rows = flattenTree((tree && tree.items) || []);
  if (!rows.length) return `<div class="fl-note">${esc(emptyTreeText())}</div>`;
  return rows.map((row) => rowHtml(row, opts)).join('');
}

/** 中身の 1 枚（サムネイルと「外す」）。 */
export function itemHtml(item, opts = {}) {
  const busy = Boolean(opts.busy);
  const kept = item.review_state === 'kept' ? ' kept' : '';
  const rejected = item.review_state === 'rejected' ? ' rejected' : '';
  return `<div class="fl-item${kept}${rejected}" data-id="${esc(item.id)}">
      <img loading="lazy" decoding="async" src="/api/assets/${esc(item.id)}/thumb?size=256" alt="">
      <span class="fl-item-path" title="${esc(item.path || '')}">${esc(shortPath(item.path))}</span>
      <button class="fl-remove" data-id="${esc(item.id)}"${busy ? ' disabled' : ''}>外す</button>
    </div>`;
}

function shortPath(value) {
  const text = String(value || '');
  if (!text) return '見つかりません';
  const parts = text.split(/[\\/]/);
  return parts.length <= 3 ? text : '…\\' + parts.slice(-2).join('\\');
}

/** 中身の HTML（空なら 1 行）。 */
export function itemsHtml(contents, opts = {}) {
  const items = (contents && contents.items) || [];
  if (contents && contents.smart) {
    // **黙って空にしない**（条件での絞り込みは P2-2 以降）
    return `<div class="fl-note">${esc(contents.note || 'スマートフォルダの条件はまだ使えません。')}</div>`;
  }
  if (!items.length) return `<div class="fl-note">${esc(emptyFolderText(opts.addCount))}</div>`;
  return items.map((item) => itemHtml(item, opts)).join('');
}

/** 押した後に出す 1 行（作った）。 */
export function createdText(name) {
  return `フォルダ「${name}」を作りました。`;
}

/** 押した後に出す 1 行（名前を変えた）。 */
export function renamedText() {
  return '名前を変えました。';
}

/** 消す前の確認の文（**何が起きるか**＋**画像は消えない**）。 */
export function deleteAskText(name) {
  return `「${name}」を消します。下にフォルダ名を打ち込むと消せます。画像は消えません。`;
}

/** 打ち込んだ名前が合っているか。**合わなければ送らない**（画面でも確かめる）。 */
export function deleteTypedOk(name, typed) {
  return String(typed || '').trim() === String(name || '').trim();
}

/** 打ち込んだ名前が違うときの 1 行。 */
export function deleteTypedText() {
  return 'フォルダ名が違います。もう一度打ち込んでください。';
}

/** 消した後の 1 行（**画像は消えていない**と添える）。 */
export function deletedText(name) {
  return `フォルダ「${name}」を消しました。画像は消えていません。`;
}

/** 入れた後の 1 行（**既に入っていた枚は分けて言う**。数を黙って捨てない）。 */
export function addedText(name, added, already = []) {
  const add = (added || []).length;
  const had = (already || []).length;
  if (!add) return `フォルダ「${name}」には、もう入っていました。`;
  const head = `${fmtCount(add)} 枚をフォルダ「${name}」に入れました。`;
  return had > 0 ? `${head}（${fmtCount(had)} 枚は既に入っていました。）` : head;
}

/** 外した後の 1 行（**画像は消していない**と添える）。 */
export function removedText(count) {
  return `${fmtCount(count)} 枚をこのフォルダから外しました。画像は消していません。`;
}

/** URL の `?folder=<id>&add=<id,id>` を読む（**状態は URL**。§8-8）。 */
export function parseSearch(search) {
  const params = new URLSearchParams(String(search || ''));
  const folder = params.get('folder') || '';
  const add = (params.get('add') || '').split(',').map((s) => s.trim()).filter(Boolean);
  return { folder, add };
}

/** フォルダの操作（名前を変える・消す）の HTML。 */
export function headHtml(node, opts = {}) {
  if (!node) {
    return '<div class="fl-sub">フォルダを選ぶと、ここに中身が出ます。</div>';
  }
  const busy = Boolean(opts.busy);
  if (opts.confirming) {
    return `<div class="fl-sub">${esc(node.name)}
        <span class="stat">${fmtCount(node.count || 0)} 枚</span></div>
      <div class="fl-ask">${esc(deleteAskText(node.name))}</div>
      <div class="fl-actions">
        <input id="fl-del-name" class="fl-del-name" type="text" placeholder="フォルダ名を打ち込む"
               autocomplete="off" value="${esc(opts.typed || '')}">
        <button id="fl-del-go" class="fl-del-go"${busy || !deleteTypedOk(node.name, opts.typed)
          ? ' disabled' : ''}>このフォルダを消す</button>
        <button id="fl-del-cancel" class="fl-del-cancel">やめる</button>
      </div>
      <div id="fl-del-hint" class="fl-bad">${opts.typed && !deleteTypedOk(node.name, opts.typed)
        ? esc(deleteTypedText()) : ''}</div>`;
  }
  if (opts.renaming) {
    return `<div class="fl-actions">
        <input id="fl-rename-name" class="fl-rename-name" type="text" value="${esc(node.name)}"
               autocomplete="off" maxlength="120">
        <button id="fl-rename-go" class="fl-rename-go"${busy ? ' disabled' : ''}>保存する</button>
        <button id="fl-rename-cancel" class="fl-rename-cancel">やめる</button>
      </div>`;
  }
  return `<div class="fl-sub">${esc(node.name)}
      <span class="stat">${fmtCount(node.count || 0)} 枚</span>
      ${node.kind === 'smart' ? '<span class="fl-kind">条件で選ぶ</span>' : ''}</div>
    <div class="fl-actions">
      <button id="fl-rename" class="fl-rename"${busy ? ' disabled' : ''}>名前を変える</button>
      <button id="fl-delete" class="fl-delete"${busy ? ' disabled' : ''}>フォルダを消す…</button>
    </div>`;
}

/** 上に出す「選んだ N 枚を…」の帯（`add=` があるときだけ）。 */
export function addBannerHtml(addCount) {
  const n = Number(addCount) || 0;
  if (n <= 0) return '';
  return `<div class="fl-banner">選んだ ${fmtCount(n)} 枚を入れるフォルダを選んでください。</div>`;
}

/** 入口（ライブラリの下部バー）の文言。**0 枚のときは枚数を書かない**（C-22）。 */
export function folderEntryLabel(count) {
  const n = Number(count) || 0;
  return n > 0 ? `選んだ ${fmtCount(n)} 枚をフォルダに入れる…` : '選んだ画像をフォルダに入れる…';
}

/** 入口のボタンを描く（押せないときは枚数を書かない）。 */
export function renderFolderEntry(button, count) {
  if (!button) return;
  button.textContent = folderEntryLabel(count);
  button.disabled = (Number(count) || 0) <= 0;
}

/** 入口を押したときの行き先。 */
export function folderHref(ids) {
  const list = (ids || []).filter(Boolean);
  return list.length ? `#/folders?add=${list.join(',')}` : '#/folders';
}

// ---- 画面の状態 ----

const state = {
  tree: null,
  folderId: '',
  contents: null,
  addIds: [],
  renaming: false,
  confirming: false,
  typed: '',
  busy: false,
  msg: '',
  bad: false,
};

// ---- 読み込み（`GET` は書かない）----

function searchNow() {
  const hash = String(location.hash || '');
  const at = hash.indexOf('?');
  return at < 0 ? '' : hash.slice(at + 1);
}

async function load() {
  state.busy = true;
  render();
  const res = await fetch(FOLDERS, { headers: { 'X-Image-Reviewer-Actor': 'human' } });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    state.busy = false;
    state.msg = `フォルダを読めませんでした。もう一度試してください（詳細: ${res.status}）。`;
    state.bad = true;
    render();
    return;
  }
  state.tree = body;
  // 選んでいるフォルダが消えていたら選択を外す
  const rows = flattenTree(body.items || []);
  if (state.folderId && !rows.some((row) => row.node.id === state.folderId)) {
    state.folderId = '';
    state.contents = null;
  }
  if (state.folderId) {
    const got = await fetch(`${FOLDERS}/${encodeURIComponent(state.folderId)}/assets?limit=200`, {
      headers: { 'X-Image-Reviewer-Actor': 'human' },
    });
    if (got.ok) {
      state.contents = await got.json().catch(() => null);
    } else {
      state.contents = null;
      state.msg = `中の画像を読めませんでした。もう一度試してください（詳細: ${got.status}）。`;
      state.bad = true;
    }
  } else {
    state.contents = null;
  }
  state.busy = false;
  render();
}

function selectedNode() {
  return flattenTree((state.tree && state.tree.items) || [])
    .map((row) => row.node)
    .find((node) => node.id === state.folderId) || null;
}

function render() {
  const tree = $('fl-tree');
  if (tree) {
    tree.innerHTML = treeHtml(state.tree, {
      addCount: state.addIds.length, selectedId: state.folderId, busy: state.busy,
    });
  }
  const banner = $('fl-add-banner');
  if (banner) banner.innerHTML = addBannerHtml(state.addIds.length);
  const node = selectedNode();
  const head = $('fl-head');
  if (head) {
    head.innerHTML = state.folderId
      ? headHtml(node, { renaming: state.renaming, confirming: state.confirming,
                         typed: state.typed, busy: state.busy })
      : headHtml(null);
  }
  const items = $('fl-items');
  if (items) {
    items.innerHTML = state.folderId
      ? itemsHtml(state.contents, { busy: state.busy, addCount: state.addIds.length })
      : '';
  }
  const brief = $('fl-brief');
  if (brief) brief.textContent = briefText(state.tree);
  const msg = $('fl-msg');
  if (msg) {
    msg.innerHTML = state.msg ? `<span class="${state.bad ? 'fl-bad' : 'fl-ok'}">${
      esc(state.msg)}</span>` : '';
  }
  // **押している間は押せなくする**（二度押しで POST を 2 回出さない）
  for (const id of ['fl-create']) {
    const node2 = $(id);
    if (node2) node2.disabled = state.busy;
  }
}

// ---- 押されたとき（書く口は人だけ）----

export async function createFolder(value) {
  const name = String(value == null ? ($('fl-new-name') ? $('fl-new-name').value : '') : value)
    .trim();
  if (!name) {
    state.msg = 'フォルダ名を入れてください。';
    state.bad = true;
    render();
    return null;
  }
  state.busy = true;
  state.msg = '';
  render();
  const body = { name };
  if (state.folderId) body.parent_id = state.folderId;
  const res = await fetch(FOLDERS, { method: 'POST', headers: human(),
                                     body: JSON.stringify(body) });
  const got = await res.json().catch(() => ({}));
  state.busy = false;
  if (!res.ok) {
    state.msg = got.detail || `作れませんでした。もう一度試してください（詳細: ${res.status}）。`;
    state.bad = true;
    render();
    return null;
  }
  state.msg = createdText(got.name || name);
  state.bad = false;
  if ($('fl-new-name')) $('fl-new-name').value = '';
  await load();
  return got;
}

export async function renameFolder(name) {
  const node = selectedNode();
  if (!node) return null;
  const wanted = String(name == null ? ($('fl-rename-name') ? $('fl-rename-name').value : '') : name)
    .trim();
  if (!wanted) {
    state.msg = 'フォルダ名を入れてください。';
    state.bad = true;
    render();
    return null;
  }
  state.busy = true;
  render();
  const res = await fetch(`${FOLDERS}/${encodeURIComponent(node.id)}`, {
    method: 'PATCH', headers: human(), body: JSON.stringify({ name: wanted }),
  });
  const got = await res.json().catch(() => ({}));
  state.busy = false;
  if (!res.ok) {
    state.msg = got.detail || `変えられませんでした。もう一度試してください（詳細: ${res.status}）。`;
    state.bad = true;
    render();
    return null;
  }
  state.renaming = false;
  state.msg = renamedText();
  state.bad = false;
  await load();
  return got;
}

export async function deleteFolder(typed) {
  const node = selectedNode();
  if (!node) return null;
  const typedNow = typed == null ? state.typed : typed;
  if (!deleteTypedOk(node.name, typedNow)) {
    state.typed = String(typedNow || '');
    state.msg = deleteTypedText();
    state.bad = true;
    render();
    return null;                       // **合わない名前では送らない**
  }
  state.busy = true;
  render();
  const res = await fetch(`${FOLDERS}/${encodeURIComponent(node.id)}`, {
    method: 'DELETE', headers: human(), body: JSON.stringify({ confirm: node.name }),
  });
  const got = await res.json().catch(() => ({}));
  state.busy = false;
  if (!res.ok) {
    state.msg = got.detail || `消せませんでした。もう一度試してください（詳細: ${res.status}）。`;
    state.bad = true;
    render();
    return null;
  }
  const name = node.name;
  state.confirming = false;
  state.typed = '';
  state.folderId = '';
  state.contents = null;
  state.msg = deletedText(name);
  state.bad = false;
  location.hash = '#/folders';
  await load();
  return got;
}

export async function addTo(folderId) {
  const ids = state.addIds.slice();
  if (!ids.length || !folderId) return null;
  const node = flattenTree((state.tree && state.tree.items) || [])
    .map((row) => row.node).find((item) => item.id === folderId);
  state.busy = true;
  render();
  const res = await fetch(`${FOLDERS}/${encodeURIComponent(folderId)}/members`, {
    method: 'POST', headers: human(), body: JSON.stringify({ asset_ids: ids }),
  });
  const got = await res.json().catch(() => ({}));
  state.busy = false;
  if (!res.ok) {
    state.msg = got.detail || `入れられませんでした。もう一度試してください（詳細: ${res.status}）。`;
    state.bad = true;
    render();
    return null;
  }
  state.msg = addedText((node && node.name) || 'フォルダ', got.added, got.already);
  state.bad = false;
  state.addIds = [];                   // 入れたら `add=` は畳む（同じ枚を二度入れない）
  state.folderId = folderId;
  location.hash = `#/folders?folder=${encodeURIComponent(folderId)}`;
  await load();
  return got;
}

export async function removeFrom(assetId) {
  const node = selectedNode();
  if (!node || !assetId) return null;
  state.busy = true;
  render();
  const res = await fetch(`${FOLDERS}/${encodeURIComponent(node.id)}/members`, {
    method: 'DELETE', headers: human(), body: JSON.stringify({ asset_ids: [assetId] }),
  });
  const got = await res.json().catch(() => ({}));
  state.busy = false;
  if (!res.ok) {
    state.msg = got.detail || `外せませんでした。もう一度試してください（詳細: ${res.status}）。`;
    state.bad = true;
    render();
    return null;
  }
  state.msg = removedText((got.removed || []).length);
  state.bad = false;
  await load();
  return got;
}

export function selectFolder(folderId) {
  state.folderId = String(folderId || '');
  state.renaming = false;
  state.confirming = false;
  state.typed = '';
  const query = state.folderId ? `?folder=${encodeURIComponent(state.folderId)}` : '';
  const add = state.addIds.length ? `${query ? '&' : '?'}add=${state.addIds.join(',')}` : '';
  location.hash = `#/folders${query}${add}`;
  return load();
}

export function startRename() {
  state.renaming = true;
  state.msg = '';
  render();
}

export function cancelRename() {
  state.renaming = false;
  render();
}

export function startDelete() {
  state.confirming = true;
  state.typed = '';
  state.msg = '';
  render();
}

export function cancelDelete() {
  state.confirming = false;
  state.typed = '';
  render();
}

export function setTyped(value) {
  state.typed = String(value == null ? '' : value);
  // **描き直さない**（入力の途中で描き直すと、打っている欄から焦点が外れる）。
  // 変えるのはボタンの可否と 1 行の案内だけ
  const node = selectedNode();
  const ok = Boolean(node) && deleteTypedOk(node.name, state.typed);
  const go = $('fl-del-go');
  if (go) go.disabled = state.busy || !ok;
  const hint = $('fl-del-hint');
  if (hint) hint.textContent = node && state.typed && !ok ? deleteTypedText() : '';
}

/** 中身の「外す」と木の「ここに入れる」と操作のボタンを 1 か所で受ける（家風）。 */
export async function onClick(event) {
  const target = event && event.target;
  if (!target || typeof target.closest !== 'function') return;
  const hit = (selector) => target.closest(selector);
  if (hit('.fl-row')) {
    // 「ここに入れる」は行のクリックより先に見る（行の選択と取り違えない）
    const put = hit('.fl-put');
    if (put) { await addTo(put.dataset.id); return; }
    const row = hit('.fl-row');
    if (row && row.dataset && row.dataset.id) await selectFolder(row.dataset.id);
    return;
  }
  const remove = hit('.fl-remove');
  if (remove) { await removeFrom(remove.dataset.id); return; }
  if (hit('.fl-rename')) { startRename(); return; }
  if (hit('.fl-delete')) { startDelete(); return; }
  if (hit('.fl-rename-go')) { await renameFolder(); return; }
  if (hit('.fl-rename-cancel')) { cancelRename(); return; }
  if (hit('.fl-del-go')) { await deleteFolder(); return; }
  if (hit('.fl-del-cancel')) { cancelDelete(); return; }
}

// ---- 入口 ----

export async function showFolders(search) {
  const params = parseSearch(search == null ? searchNow() : search);
  state.folderId = params.folder || state.folderId || '';
  state.addIds = params.add;
  state.msg = '';
  state.bad = false;
  state.renaming = false;
  state.confirming = false;
  state.typed = '';
  document.body.classList.add('foldering');
  await load();
}

export function hideFolders() {
  document.body.classList.remove('foldering');
}

export function wireFolders() {
  for (const id of ['fl-tree', 'fl-head', 'fl-items']) {
    const node = $(id);
    if (node) node.addEventListener('click', (event) => { onClick(event).catch(() => {}); });
  }
  const again = $('fl-again');
  if (again) again.addEventListener('click', () => { load().catch(() => {}); });
  const back = $('fl-back');
  if (back) back.addEventListener('click', (event) => { event.preventDefault(); location.hash = ''; });
  const create = $('fl-create');
  if (create) create.addEventListener('click', () => { createFolder().catch(() => {}); });
  const name = $('fl-new-name');
  if (name) {
    name.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { createFolder().catch(() => {}); }
    });
  }
  // 入力（名前を打ち込む欄）は**動的に出る**ので、`input` を包みで受ける
  for (const id of ['fl-head']) {
    const node = $(id);
    if (!node) continue;
    node.addEventListener('input', (event) => {
      const target = event && event.target;
      if (target && target.id === 'fl-del-name') setTyped(target.value);
    });
  }
}

/** ライブラリの下部バーの入口（削除の入口と同じ形。**渡すだけ**）。 */
export function wireFolderEntry(button, idsFn) {
  if (!button) return;
  button.addEventListener('click', () => {
    const ids = idsFn ? idsFn() : [];
    location.hash = folderHref(ids);
  });
}
