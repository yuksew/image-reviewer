// image-reviewer プロトタイプの画面
// 設計: docs/frontend-design.md（同じ見た目の言語を使う）
// 範囲: 閲覧と来歴の表示、比較（P5-2。`#/compare?ids=a,b&base=<id>`）、
//       要求の一覧とまとまりレビュー（P6-1b。`#/requests` / `#/group/<id>`）

import { MAX_IDS, hideCompare, showCompare, wireCompare } from './compare.js';
import { mountAnnotations, resetAnnotations, setAnnotationGroup } from './annotations.js';
import { hideGroup, showGroup, wireGroup } from './group.js';
import { hideRequests, showRequests, wireRequests } from './requests.js';
import { wireBadge } from './badge.js';
// P4-3: タグ（1 枚の欄 / 語の一覧 / ジョブ）
import { mountTags, resetTags } from './tags.js';
import { hideTags, showTags, wireTags } from './taglist.js';
import { hideJobs, showJobs, wireJobs } from './jobs.js';
// P7-4: 条件の記録（`#/asset/<id>/recipe` と `#/recipes`）
import { hideRecipe, recipeLinkHtml, showRecipe, wireRecipe } from './recipe.js';
import { hideRecipes, showRecipes, wireRecipes } from './recipelist.js';

const $ = (id) => document.getElementById(id);

const state = {
  assets: [],
  stats: null,
  filter: 'all',
  provenance: 'all', // all | with | without
  density: 'normal',
  theme: 'dark',
  selected: null,
  picked: [],        // 比較に選んだ asset_id（Ctrl / Shift + クリック。2〜8 枚）
};

const DENSITY = { dense: 140, normal: 200, sparse: 300 };
const DENSITY_LABEL = { dense: '密', normal: '普', sparse: '疎' };

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${res.status} ${text.slice(0, 200)}`);
  }
  return res.json();
}

function fmtBytes(n) {
  if (n == null) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

function shortPath(p) {
  if (!p) return '（実体なし）';
  const parts = p.split(/[\\/]/);
  return parts.length <= 3 ? p : '…\\' + parts.slice(-2).join('\\');
}

// ---- 読み込み ----

async function load() {
  state.stats = await api('/api/stats');
  const data = await api('/api/assets?limit=2000&sort=path');
  state.assets = data.items;
  renderStats();
  renderSheet();
}

async function capture() {
  const btn = $('btn-capture');
  btn.disabled = true;
  btn.textContent = '捕獲中…';
  try {
    const s = await api('/api/capture', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    alert(`/history ${s.history_entries} 件を走査。\n訳が未取得の ${s.checked} 枚のうち ${s.captured} 枚で訳を捕獲しました。`);
    await load();
    if (state.selected) await select(state.selected);
  } catch (e) {
    alert(`捕獲できません: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = '訳を捕獲';
  }
}

async function rescan() {
  const roots = (state.stats && state.stats.roots) || [];
  $('btn-scan').disabled = true;
  $('btn-scan').textContent = '走査中…';
  try {
    await api('/api/scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
  } finally {
    $('btn-scan').disabled = false;
    $('btn-scan').textContent = '再走査';
  }
  await load();
}

// ---- 上部・左の集計 ----

function renderStats() {
  const s = state.stats || {};
  $('stat-brief').textContent = `${s.assets ?? 0} 枚`;
  $('c-all').textContent = s.assets ?? 0;
  $('c-with').textContent = s.with_provenance ?? 0;
  $('c-without').textContent = s.without_provenance ?? 0;
  const byKind = {};
  for (const a of state.assets) byKind[a.kind] = (byKind[a.kind] || 0) + 1;
  $('c-gen').textContent = byKind.generated || 0;
  $('c-photo').textContent = (byKind.photo || 0) + (byKind.reference || 0);

  const models = $('models');
  models.innerHTML = '';
  for (const [name, n] of Object.entries(s.by_model || {})) {
    const el = document.createElement('div');
    el.className = 'item';
    el.dataset.filter = `model:${name}`;
    el.innerHTML = `<span>${esc(name)}</span><span class="n">${n}</span>`;
    el.addEventListener('click', () => setFilter(`model:${name}`));
    models.appendChild(el);
  }

  $('bar-count').textContent =
    `${s.assets ?? 0} 枚   来歴あり ${s.with_provenance ?? 0}   来歴なし ${s.without_provenance ?? 0}` +
    (s.missing ? `   参照切れ ${s.missing}` : '');
}

// ---- フィルタ ----

function setFilter(f) {
  state.filter = f;
  for (const el of document.querySelectorAll('.rail .item')) {
    el.classList.toggle('on', el.dataset.filter === f);
  }
  renderSheet();
}

function visibleAssets() {
  let items = state.assets;
  if (state.provenance === 'with') items = items.filter((a) => a.has_provenance);
  if (state.provenance === 'without') items = items.filter((a) => !a.has_provenance);
  const f = state.filter;
  if (f.startsWith('kind:')) items = items.filter((a) => a.kind === f.slice(5));
  else if (f.startsWith('model:')) items = items.filter((a) => a.model === f.slice(6));
  return items;
}

// ---- フィルム（一覧） ----

function renderSheet() {
  const items = visibleAssets();
  const rows = $('rows');
  rows.innerHTML = '';
  $('sheet-empty').hidden = items.length > 0;
  $('bar-shown').textContent = `表示 ${items.length} 枚`;

  const frag = document.createDocumentFragment();
  const H = DENSITY[state.density];
  items.forEach((a) => {
    const el = document.createElement('div');
    el.className = 'frame' + (a.has_provenance ? '' : ' no-prov') +
      (a.review_state === 'kept' ? ' kept' : a.review_state === 'rejected' ? ' rejected' : '') +
      (state.selected === a.id ? ' selected' : '') +
      (state.picked.includes(a.id) ? ' picked' : '');
    el.title = a.path || a.id;
    // 高さは密度で固定、幅は絵の縦横比に従う（点検 B5: cover で手や足を切らない）
    const ratio = (a.width && a.height) ? a.width / a.height : 1;
    const w = Math.max(Math.round(H * 0.5), Math.min(Math.round(H * 2.2), Math.round(H * ratio)));
    el.style.width = `${w}px`;
    el.style.height = `${H}px`;
    el.innerHTML =
      `<div class="wedge"></div><div class="warn"></div><div class="no"></div>` +
      `<img loading="lazy" decoding="async" src="/api/assets/${a.id}/thumb?size=256" alt="">` +
      `<div class="cap">${esc(a.model || '')}${a.seed ? ' · ' + esc(a.seed) : ''}</div>`;
    el.querySelector('.no').textContent = String(items.indexOf(a) + 1);
    // 点検 C9: 比較の画面は**まとまりが無くても**入れる。Ctrl / Shift + クリックで選ぶ
    el.addEventListener('click', (event) => {
      if (event.ctrlKey || event.metaKey || event.shiftKey) {
        togglePick(a.id);
        return;
      }
      select(a.id);
    });
    frag.appendChild(el);
  });
  rows.appendChild(frag);
}

// ---- 詳細（来歴） ----

async function select(id) {
  state.selected = id;
  resetAnnotations();          // P6-2: 別の 1 枚へ移ったら注記の状態も捨てる
  resetTags();                 // P4-3: タグの欄も作り直す
  const asset = await api(`/api/assets/${id}`);
  const meta = asset.meta || {};
  const d = $('detail');
  d.classList.remove('hidden');

  const rows = [];
  const row = (k, v, cls = '') => {
    if (v === null || v === undefined || v === '') return;
    rows.push(`<tr><th>${esc(k)}</th><td class="${cls}">${v}</td></tr>`);
  };
  row('モデル', esc(meta.model));
  row('テクストエンコーダ', esc(meta.clip));
  row('VAE', esc(meta.vae));
  row('LoRA', (meta.loras || []).map(esc).join('<br>'));
  row('seed', esc(meta.seed), 'num');
  row('steps', meta.steps, 'num');
  row('cfg', meta.cfg, 'num');
  row('denoise', meta.denoise, 'num');
  row('sampler', esc(meta.sampler));
  row('scheduler', esc(meta.scheduler));
  row('大きさ', `${esc(asset.width)} × ${esc(asset.height)}`);
  row('実体', fmtBytes(asset.size), 'num');
  row('種別', esc(asset.kind));
  const nodes = meta.node_types ? Object.entries(meta.node_types).map(([k, v]) => `${k}×${v}`).join(', ') : '';
  row('ノード', `<span class="mono">${esc(nodes)}</span>`);

  d.innerHTML = `
    <img class="preview" src="/api/assets/${id}/thumb?size=1024" alt="">
    <div class="stat" style="margin-top:6px">${esc(shortPath(asset.locations?.[0]?.path))}</div>
    ${asset.meta_note ? `<div class="note" style="margin-top:6px">${esc(asset.meta_note)}</div>` : ''}

    <div class="prov-recipe">${recipeLinkHtml(id, null)}</div>

    <h3>タグ<span class="src">（PNG の語 / タガー / 手）</span></h3>
    <div id="tg-panel" class="tg-panel"></div>

    <h3>生成の来歴</h3>
    ${meta.model || meta.seed ? `<table>${rows.join('')}</table>`
      : `<div class="note">この画像には生成条件が残っていません（prompt チャンクが無い）。</div>`}

    ${meta.ja_text ? `<h3>生成に用いた日本語</h3><textarea readonly>${esc(meta.ja_text)}</textarea>
      <div class="stat">出所: ${esc(meta.ja_source || '—')}</div>` : ''}

    ${meta.en_text ? `
      <h3>当時の英訳<span class="src">（生成の瞬間に捕獲）</span></h3>
      <textarea readonly>${esc(meta.en_text)}</textarea>
      <div class="stat">出所: ${esc(meta.en_source)}
        ${meta.prompt_id ? ` ・ prompt_id ${esc(meta.prompt_id.slice(0, 8))}…` : ''}
        ${meta.captured_from_node ? ` ・ ノード ${esc(meta.captured_from_node)}` : ''}</div>
      ${meta.final_prompt ? `
        <h3>実際に渡った最終プロンプト<span class="src">（再構成）</span></h3>
        <textarea readonly>${esc(meta.final_prompt)}</textarea>
        <div class="stat">捕獲値に前置語を足して組み直したもの（出所: ${esc(meta.final_prompt_source)}）。
          L1 で書き出すならこれを固定する（品質語を落とさない）。</div>` : ''}
    ` : (meta.has_textgen ? `
      <h3>当時の英訳</h3>
      <div class="note">この画像は日本語→英語の翻訳を通していますが、訳がまだ捕獲できていません。
      ComfyUI を起動した状態で「訳を捕獲」を押すと、<code>/history</code> に残っていれば取れます
      （残っていなければ訳し直しになります。design.md §7.3.1）。</div>
      <table>${Object.entries(meta.textgen_params || {}).map(([k, v]) => `<tr><th>${esc(k)}</th><td>${esc(String(v))}</td></tr>`).join('')}</table>
    ` : '')}

    <h3>ワークフロー</h3>
    <div class="actions">
      <a href="/api/assets/${id}/graph?format=api" download>API 形式を保存</a>
      <a href="#" data-ui-graph="${id}">UI 形式を保存</a>
      <a href="/api/assets/${id}/file" target="_blank">原本を開く</a>
    </div>
    <div class="stat" style="margin-top:6px">
      API 形式のまま ComfyUI のキャンバスへドラッグ&ドロップすると開けます（実機で確認済み）。
      URL 一発で開く方法は ComfyUI にありません。
    </div>
    <div class="stat mono" style="margin-top:6px">sha256 ${esc(asset.sha256)}</div>
  `;

  d.querySelector('[data-ui-graph]')?.addEventListener('click', async (e) => {
    e.preventDefault();
    const res = await fetch(`/api/assets/${id}/graph?format=ui`);
    if (!res.ok) {
      alert('この画像は UI 形式のグラフを持っていません（API 生成のため）。');
      return;
    }
    const blob = await res.blob();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${id.slice(0, 12)}-ui.json`;
    a.click();
  });

  renderSheet();
  // P6-2: 注記の取り付け（この画面が**注記の入口**。点検 C5 / C13）。
  // `await` しない（取り付けの失敗で詳細の表示を止めない）
  mountAnnotations(d, id).catch(() => {});
  // P4-3: タグの欄（2 行 1 組）。ここも `await` しない
  mountTags($('tg-panel'), id).catch(() => {});
}

// ---- 比較に選ぶ（P5-2。Ctrl / Shift + クリック）----

function togglePick(id) {
  const at = state.picked.indexOf(id);
  if (at >= 0) {
    state.picked.splice(at, 1);
  } else if (state.picked.length >= MAX_IDS) {
    alert(`一度に並べられるのは ${MAX_IDS} 枚までです（比較の画面の上限。まとまりの上限ではありません）。`);
    return;
  } else {
    state.picked.push(id);
  }
  renderPickBar();
  renderSheet();
}

function renderPickBar() {
  $('bar-pick').textContent = `選択 ${state.picked.length} 枚`;
  $('btn-compare').disabled = state.picked.length < 2;
}

function openCompare() {
  if (state.picked.length < 2) return;
  // 計算はサーバが行う（設計 §10-4）。画面は入り口を作るだけ
  location.hash = `#/compare?ids=${state.picked.join(',')}`;
}

// ---- 道（ハッシュ）----

// `#/compare` / `#/requests` / `#/group/<id>` / `#/asset/<id>` / `#/tags` / `#/jobs` の 6 つ。
// **要求が来ても画面を切り替えない**（`#/requests` を開いたときだけ出す。§5.1）
function route() {
  const hash = location.hash || '';
  const queryOf = (h) => {
    const at = h.indexOf('?');
    return at < 0 ? '' : h.slice(at + 1);
  };
  const pathOf = (h, prefix) => decodeURIComponent(h.slice(prefix.length).split('?')[0]);
  const comparing = hash.startsWith('#/compare');
  const requesting = hash.startsWith('#/requests');
  const grouping = hash.startsWith('#/group/');
  // **P7-4**: `#/asset/<id>/recipe` は `#/asset/<id>` より**先**に見る
  // （後ろだと拡大の画面が勝ってしまう）
  const recipeOf = hash.match(/^#\/asset\/([^/?]+)\/recipe/);
  const recipeList = hash.startsWith('#/recipes');
  const zooming = hash.startsWith('#/asset/') && !recipeOf;
  const tagging = hash.startsWith('#/tags');
  const jobbing = hash.startsWith('#/jobs');
  document.body.classList.toggle('comparing', comparing);
  document.body.classList.toggle('requests', requesting);
  document.body.classList.toggle('grouping', grouping);
  if (recipeOf) {
    hideRequests(); hideGroup(); hideTags(); hideJobs(); hideRecipes();
    showRecipe(decodeURIComponent(recipeOf[1])).catch(() => {});
    return;
  }
  if (recipeList) {
    hideRequests(); hideGroup(); hideTags(); hideJobs(); hideRecipe();
    showRecipes(queryOf(hash)).catch(() => {});
    return;
  }
  if (comparing) {
    hideRequests();
    hideGroup();
    hideTags();
    hideJobs();
    hideRecipe();
    hideRecipes();
    showCompare(queryOf(hash));
    return;
  }
  hideCompare();
  if (requesting) {
    hideGroup();
    hideTags();
    hideJobs();
    hideRecipe();
    hideRecipes();
    showRequests(queryOf(hash));
    return;
  }
  if (grouping) {
    hideRequests();
    hideTags();
    hideJobs();
    hideRecipe();
    hideRecipes();
    showGroup(pathOf(hash, '#/group/'));
    return;
  }
  if (tagging) {
    hideRequests();
    hideGroup();
    hideJobs();
    hideRecipe();
    hideRecipes();
    showTags(queryOf(hash)).catch(() => {});
    return;
  }
  if (jobbing) {
    hideRequests();
    hideGroup();
    hideTags();
    hideRecipe();
    hideRecipes();
    showJobs().catch(() => {});
    return;
  }
  hideRequests();
  hideGroup();
  hideTags();
  hideJobs();
  hideRecipe();
  hideRecipes();
  // 拡大（`#/asset/<id>`。まとまりレビューの「選んだ 1 枚を拡大で開く」の行き先）。
  // **注記の入口**（点検 C5）: ここで印を付けてから決める。
  // `?group=<id>` が付いていれば、そのまとまりの注記として記録する（要求の応答に出る）
  setAnnotationGroup(null);
  if (zooming) {
    const id = pathOf(hash, '#/asset/');
    if (id) {
      setAnnotationGroup(new URLSearchParams(queryOf(hash)).get('group'));
      select(id).catch(() => {});
    }
  }
}

// ---- 切替 ----

function cycleProvenance() {
  state.provenance = state.provenance === 'all' ? 'with' : state.provenance === 'with' ? 'without' : 'all';
  $('btn-provenance').textContent = `来歴: ${{ all: 'すべて', with: 'あり', without: 'なし' }[state.provenance]}`;
  renderSheet();
}

function cycleDensity() {
  state.density = state.density === 'dense' ? 'normal' : state.density === 'normal' ? 'sparse' : 'dense';
  document.documentElement.dataset.density = state.density;
  document.documentElement.style.setProperty('--frame', `${DENSITY[state.density]}px`);
  $('btn-density').textContent = `密度: ${DENSITY_LABEL[state.density]}`;
}

function cycleTheme() {
  state.theme = state.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = state.theme;
  $('btn-theme').textContent = `テーマ: ${state.theme === 'dark' ? '暗幕' : '表'}`;
}

// ---- 起動 ----

for (const el of document.querySelectorAll('.rail .item[data-filter]')) {
  el.addEventListener('click', () => setFilter(el.dataset.filter));
}
$('btn-provenance').addEventListener('click', cycleProvenance);
$('btn-density').addEventListener('click', cycleDensity);
$('btn-theme').addEventListener('click', cycleTheme);
$('btn-scan').addEventListener('click', rescan);
$('btn-capture').addEventListener('click', capture);
$('btn-compare').addEventListener('click', openCompare);
window.addEventListener('hashchange', route);

wireCompare();
wireRequests();
wireGroup();
// P4-3: タグの一覧とジョブ
wireTags();
wireJobs();
wireRecipe();          // P7-4: 条件の記録（`#/asset/<id>/recipe`）
wireRecipes();         // P7-4: 記録の一覧（`#/recipes`）
// P6-1b: 画面を開いている間だけ 5 秒ごとに要求の件数を取る（SSE は作らない。§5.4 / §0.10）
// P4-3: 同じ周期でジョブの進行も見る（`#/jobs` に入らなくても気づける。p4-design §5.5）
wireBadge();
renderPickBar();
route();

load().catch((e) => {
  $('sheet-empty').hidden = false;
  $('sheet-empty').textContent = `読み込めません: ${e.message}`;
});
