// image-reviewer の比較画面（P5-2 / P5-3）
// 設計: docs/p5-design.md §5.3（比較の画面）・§6.1（差分表）・§6.2（指標）・§0.5 G6（force）、
//       docs/comparison.md §2.1（並べる）・§2.2（同期ズーム）・§2.3（差分ヒートマップ）・
//       §3.1（表）・§4.1（似ている順）・§6（操作）
//
// 約束:
// - **計算はサーバ（`/api/compare`）が済ませてある。ここは描くだけ**（設計 §10-4）。
//   どの行が違うか・どのセルが違うか（`cells`）・語の差分（`prompt_diff`）もサーバの値。
//   **似ている順の距離**（`nearest`）と**ヒートマップの可否**（`pairs`）もサーバが決める
//   （画面は `order` の順に並べ替え、`enabled` と `reason` をそのまま描く）。
//   seed 順だけは、サーバが返した `provenance.seed` を並べ替える（値の計算はしない）
// - 差分ヒートマップの画像は `POST /api/compare/pair` が**要求のたびに作る**（保存しない）。
//   条件の外でも「強制して出す」で見られる（点検 G6）。位置が合わないときは
//   画像ではなく理由（「位置が合いません」）が出る
// - 絞り込み（`cover`）を使わない。枠の高さを揃え、幅は絵の縦横比に従う（`comparison.md` §2.1）
// - マウスだけで完結する（ホイールで拡大・ドラッグで移動）。キーは補助（§6）
//   **監査 A1**: 出せない組の「強制して出す」もマウスだけで届く（理由の 1 行の隣に出し、
//   「差分ヒートマップ」のボタンも `disabled` にしない。`d` は補助）
// - **基準（`base`）は URL が正**（`#/compare?ids=…&base=…`。監査 C1）。タイルの
//   「基準にする」でも `b` キーでも、`base=` を書き換えてサーバから取り直す
//   （reload でも「戻る」でも同じ見え方になる）。マウスだけで変えられる（キーは補助）
// - 比較は**読むだけ**なので `X-Image-Reviewer-Actor` は要らない（状態を変える口を叩かない）

const API = '/api/compare';
const PAIR_API = '/api/compare/pair';
export const MAX_IDS = 8;       // サーバと同じ上限（`compare.MAX_COMPARE_IDS`）
const MIN_SCALE = 0.5;
const MAX_SCALE = 8;
// 並び順（`comparison.md` §4.1）。`r` で巡回する。既定は入力順
const ORDERS = [
  { id: 'input', label: '入力順' },
  { id: 'seed', label: 'seed 順' },
  { id: 'near', label: '似ている順' },
];

const $ = (id) => document.getElementById(id);

// ULID 以外の id が来ても選択子が壊れないようにする
function sel(assetId) {
  const text = String(assetId);
  return (window.CSS && CSS.escape) ? CSS.escape(text) : text.replace(/["\\]/g, '\\$&');
}

const state = {
  doc: null,
  group: null,                  // まとまりの比較の `?group=`（基準を変えても保つ。監査 C1）
  showSame: false,
  sync: true,
  selected: null,
  order: 'input',               // 並び順（P5-3。`comparison.md` §4.1）
  heat: null,                   // 出している差分ヒートマップの応答（P5-3）
  heatPair: null,               // その組（選択が変わったら閉じる）
  views: new Map(),             // asset_id -> {s, x, y}
};

let keyHandler = null;

function esc(value) {
  return String(value ?? '').replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// `ids=a,b&base=x` を読む（`#/compare?...` の ? 以降を渡す）
function query(search) {
  const out = {};
  for (const part of String(search || '').replace(/^[?#]/, '').split('&')) {
    if (!part) continue;
    const at = part.indexOf('=');
    const key = decodeURIComponent(at < 0 ? part : part.slice(0, at));
    out[key] = at < 0 ? '' : decodeURIComponent(part.slice(at + 1).replace(/\+/g, ' '));
  }
  return out;
}

// `comparison.md` §2.1 のレイアウト（2 | 3〜4 | 5〜6 | 7〜8）
function layoutFor(count) {
  if (count <= 2) return { perRow: Math.max(count, 1), rows: 1 };
  if (count <= 4) return { perRow: 2, rows: 2 };
  if (count <= 6) return { perRow: 3, rows: 2 };
  return { perRow: 4, rows: 2 };
}

function ratioOf(item) {
  const w = item.provenance.width;
  const h = item.provenance.height;
  if (!w || !h) return 1;
  return Math.max(0.25, Math.min(4, w / h));
}

function brief(text) {
  const el = $('cmp-brief');
  if (el) el.textContent = text;
}

// ---- 入り口 ----

export async function showCompare(search) {
  const q = query(search);
  const ids = String(q.ids || '').split(',').map((s) => s.trim()).filter(Boolean);
  const params = new URLSearchParams();
  if (ids.length) params.set('ids', ids.join(','));
  if (q.base) params.set('base', q.base);
  const path = q.group ? `/api/groups/${encodeURIComponent(q.group)}/compare` : API;
  state.group = q.group || null;

  brief('読み込み中…');
  $('cmp-stage').innerHTML = '';
  $('cmp-diff').innerHTML = '';
  try {
    const res = await fetch(`${path}?${params.toString()}`);
    const text = await res.text();
    if (!res.ok) throw new Error(detailOf(res.status, text));
    const doc = JSON.parse(text);
    // 同じ顔ぶれなら、基準を変えただけなので拡大と選択を保つ（監査 C1）
    const sameIds = state.doc ? state.doc.ids.join(',') === doc.ids.join(',') : false;
    state.doc = doc;
    if (!sameIds) {
      state.views = new Map();
      state.selected = doc.base;
      // 監査 C2: 顔ぶれが変わったら並び順も既定（入力順。`comparison.md` §2.1）に戻す。
      // 戻さないと、seed 順のまま別の組を開いて「1 番が基準」と思い込む
      state.order = 'input';
      syncOrderLabel();
    }
    for (const item of doc.items) {
      if (!state.views.has(item.asset_id)) state.views.set(item.asset_id, { s: 1, x: 0, y: 0 });
    }
    if (!state.selected || !state.views.has(state.selected)) state.selected = doc.base;
    closeHeat();
    render();
  } catch (error) {
    state.doc = null;
    brief('比較できません');
    $('cmp-diff').innerHTML =
      `<div class="cmp-note">比較できません: ${esc(error.message)}</div>`;
  }
}

export function hideCompare() {
  if (keyHandler) {
    document.removeEventListener('keydown', keyHandler);
    keyHandler = null;
  }
  closeHeat();
  state.doc = null;
}

function detailOf(status, text) {
  try {
    const body = JSON.parse(text);
    if (body && body.detail) return `${status} ${body.detail}`;
  } catch (error) { /* JSON でなければ本文をそのまま出す */ }
  return `${status} ${String(text || '').slice(0, 200)}`;
}

// ---- 描く ----

function render() {
  const doc = state.doc;
  if (!doc) return;
  const seed = doc.diff.changed.concat(doc.diff.same).find((row) => row.key === 'seed');
  const sameSeed = seed ? seed.state === 'same' : false;
  brief(`${doc.items.length} 枚 / 基準 ${indexOfBase() + 1} 番`
    + (sameSeed ? ' / 同一 seed' : ' / seed が違うので画素は別物'));

  renderDiff();
  renderStage();
  renderZoomLabel();
  syncHeatBar();
}

function indexOfBase() {
  const at = orderedIds().indexOf(state.doc ? state.doc.base : null);
  return at < 0 ? 0 : at;
}

// ---- 並び順（P5-3。`comparison.md` §4.1）----

// 表示する順。**距離はサーバ（`nearest.order`）が決める**（画面は並べ替えるだけ。設計 §10-4）。
// seed 順だけは、サーバが返した `provenance.seed` を並べ替える（値の計算はしない）。
function orderedIds() {
  const doc = state.doc;
  if (!doc) return [];
  const ids = doc.items.map((item) => item.asset_id);
  if (state.order === 'near') {
    const given = ((doc.nearest && doc.nearest.order) || []).filter((id) => ids.includes(id));
    return given.concat(ids.filter((id) => !given.includes(id)));
  }
  if (state.order === 'seed') {
    const seedOf = (id) => {
      const at = doc.ids.indexOf(id);
      const item = doc.items[at] || {};
      const value = (item.provenance || {}).seed;
      return value == null || value === '' ? null : String(value);
    };
    // seed の無い枚は末尾（「分からない」を先頭に置かない）。同じ seed は入力順のまま
    return ids.map((id, index) => ({ id, index, seed: seedOf(id) }))
      .sort((a, b) => {
        if ((a.seed === null) !== (b.seed === null)) return a.seed === null ? 1 : -1;
        if (a.seed !== b.seed) return a.seed < b.seed ? -1 : 1;
        return a.index - b.index;
      })
      .map((entry) => entry.id);
  }
  return ids;
}

// サーバの並び（`doc.ids`）での添字。値（`values` / `cells`）はこの順で返ってくる
function serverIndex(assetId) {
  return state.doc ? state.doc.ids.indexOf(assetId) : -1;
}

// **画面の並び**（`orderedIds()`）での添字。番号を人に見せるときは必ずこちらを使う
// （監査 C2: 似ている順で `3` を押すと番号 4 のタイルが選ばれ、語の差分の「2 番」が
//  表の 2 列目と別の枚を指していた。値の添字だけがサーバ順でよい）
function displayIndex(assetId) {
  return orderedIds().indexOf(assetId);
}

// 基準でない方の 1 枚（差分ヒートマップの相手。選択中が基準なら先頭の他の枚）
function otherId() {
  const doc = state.doc;
  if (!doc) return null;
  const order = orderedIds();
  if (state.selected && state.selected !== doc.base) return state.selected;
  return order.find((id) => id !== doc.base) || null;
}

function itemOf(assetId) {
  const at = serverIndex(assetId);
  return at < 0 ? null : state.doc.items[at];
}

function stageHeight(ratios) {
  const stage = $('cmp-stage');
  const layout = layoutFor(state.doc.items.length);
  // 監査 B1（実行込みのやり直し）: **見出し（`.cmp-cap`）と行間を数える**。
  // 数えないと、`resize` で 4×2 になった後も 2 行目の見出しが枠の外に出る（実測 32 px）。
  const { padY, gap } = stageMetrics(stage);
  const cap = captionHeight();
  const rows = layout.rows;
  const usable = (stage.clientHeight || 420) - padY - gap * (rows - 1) - cap * rows;
  const byHeight = Math.floor(usable / rows);
  // 監査 B1: 1 行に入る枚数は**枠の幅**で数える（`renderStage()` がタイルにも同じ幅を付ける）。
  // 縦横比が混ざる組でも溢れないよう、**いちばん広い枠**で見積もる
  const widest = Math.max(0.5, ...ratios);
  const byWidth = Math.floor(((stage.clientWidth || 900) - 16) / (widest * layout.perRow));
  return Math.max(110, Math.min(420, byHeight, byWidth));
}

// 舞台の内側の余白と行間。**CSS を 1 か所から読む**（`styles.css` の `.cmp-stage`）。
// 軽い DOM（`tools/gui_smoke.mjs`）には `getComputedStyle` が無いので、そのときは
// `styles.css` の値（`padding: 6px` / `gap: 2px`）で代用する。
function stageMetrics(stage) {
  if (typeof getComputedStyle !== 'function') return { padY: 12, gap: 2 };
  const style = getComputedStyle(stage);
  return {
    padY: (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0),
    gap: parseFloat(style.rowGap) || 0,
  };
}

// 見出し 1 行の高さ（`.cmp-cap`）。まだ描いていない初回は `styles.css` の値
// （font-size 11px / line-height 16px）を使う。見出しは `white-space: nowrap` で 1 行。
function captionHeight() {
  const existing = typeof document.querySelector === 'function'
    ? document.querySelector('.cmp-cap') : null;
  return (existing && existing.offsetHeight) || 16;
}

function renderStage() {
  const doc = state.doc;
  const stage = $('cmp-stage');
  const order = orderedIds();
  const items = order.map(itemOf);
  const ratios = items.map(ratioOf);
  const height = stageHeight(ratios);
  // 枠の高さは `--frame`（行の高さ）。幅は絵の縦横比に従う（`comparison.md` §2.1）
  stage.style.setProperty('--frame', `${height}px`);
  stage.innerHTML = '';

  order.forEach((assetId, index) => {
    const item = itemOf(assetId);
    if (!item) return;
    const tile = document.createElement('div');
    const isBase = item.asset_id === doc.base;
    tile.className = 'cmp-tile' + (item.asset_id === state.selected ? ' selected' : '')
      + (isBase ? ' is-base' : '');                    // 基準の印（監査 C1）
    const width = Math.max(60, Math.round(height * ratios[index]));
    // 監査 B1: **タイルにも同じ幅を付ける**。付けないと、`nowrap` の見出し（モデル名・seed・
    // steps・cfg。実測 309〜434px）がタイルを広げ、`stageHeight()` の幅の見積り
    // （枠の幅が前提）が当たらない（見出しは `max-width: 100%` と省略記号で切れる）
    tile.style.width = `${width}px`;
    const meta = item.provenance;
    const caption = [meta.model ? shortModel(meta.model) : null,
                     meta.seed ? `seed ${meta.seed}` : null,
                     meta.steps != null ? `steps ${meta.steps}` : null,
                     meta.cfg != null ? `cfg ${meta.cfg}` : null]
      .filter(Boolean).join('、');
    const flag = item.review_state === 'kept' ? 'キープ'
      : item.review_state === 'rejected' ? 'ボツ' : '';
    // 似ている順のときは距離をキャプションに足す（サーバが返した値。画面では数えない）
    const distance = state.order === 'near' && doc.nearest
      ? doc.nearest.distances[assetId] : null;
    const near = distance == null ? '' : `距離 ${distance}`;
    tile.innerHTML = `
      <div class="cmp-frame" data-id="${esc(item.asset_id)}" style="width:${width}px">
        <div class="cmp-zoom" data-id="${esc(item.asset_id)}">
          <img draggable="false" decoding="async" alt="" src="${esc(item.thumb)}">
        </div>
        <div class="no">${index + 1}</div>
        <button type="button" class="cmp-base" data-id="${esc(item.asset_id)}"
                aria-pressed="${isBase ? 'true' : 'false'}"
                title="${isBase ? 'この画像が差分の基準です' : 'この画像を差分の基準にする（b）'}"
                >${isBase ? '基準 ✓' : '基準にする'}</button>
        <div class="cmp-flag ${esc(item.review_state)}">${esc(flag)}</div>
        <div class="cmp-near">${esc(near)}</div>
      </div>
      <div class="cmp-cap" title="${esc(caption)}">${esc(caption)}</div>`;
    const frame = tile.querySelector('.cmp-frame');
    frame.addEventListener('wheel', (event) => onWheel(event, item.asset_id),
      { passive: false });
    frame.addEventListener('mousedown', (event) => onDragStart(event, item.asset_id));
    frame.addEventListener('dblclick', () => setView(item.asset_id, { s: 1, x: 0, y: 0 }));
    // マウスだけで基準を変えられる経路（監査 C1）。枠のドラッグ / 拡大には渡さない
    const baseButton = tile.querySelector('.cmp-base');
    for (const type of ['mousedown', 'wheel', 'dblclick']) {
      baseButton.addEventListener(type, (event) => event.stopPropagation());
    }
    baseButton.addEventListener('click', (event) => {
      event.stopPropagation();                         // タイルのクリック（選択）に伝えない
      setBase(item.asset_id);
    });
    tile.addEventListener('click', () => select(item.asset_id));
    stage.appendChild(tile);
    if (!state.views.has(item.asset_id)) state.views.set(item.asset_id, { s: 1, x: 0, y: 0 });
    applyView(item.asset_id);
  });
  installKeys();
}

// 基準を変える（監査 C1）。**URL を正とする**ので `base=` を書き換えて取り直す
// （`hashchange` → `app.js` の `route()` → `showCompare()`）。タイルの「基準にする」と
// `b` キーの両方から来る。`b` は補助で、マウスだけでも変えられる。
function setBase(assetId) {
  const doc = state.doc;
  if (!doc || !assetId) return;
  if (assetId === doc.base) {
    select(assetId);
    return;
  }
  // `ids=a,b` の形は設計の例（`p5-design.md` §6.1）と同じにする（`,` を %2C にしない）
  const parts = [`ids=${doc.ids.map(encodeURIComponent).join(',')}`,
                 `base=${encodeURIComponent(assetId)}`];
  if (state.group) parts.push(`group=${encodeURIComponent(state.group)}`);
  location.hash = `#/compare?${parts.join('&')}`;
}

function shortModel(name) {
  const text = String(name);
  return text.length > 24 ? `${text.slice(0, 22)}…` : text;
}

function renderDiff() {
  const doc = state.doc;
  const diff = doc.diff;
  const rows = state.showSame ? diff.changed.concat(diff.same) : diff.changed;
  // 表の列もタイルと同じ並びにする（`orderedIds()` の 1 か所で決める）
  const ids = orderedIds();
  const head = ids.map((id, index) =>
    `<th title="${esc(id)}"><span class="n">${index + 1}</span>`
    + `<img src="${esc(itemOf(id).thumb_small)}" alt=""></th>`).join('');

  const body = rows.map((row) => {
    // 監査 B2: 最終プロンプトが分からない枚は、値ではなく「分からない」と描く
    // （分かっている前置語だけを別に添える。`same` とも「無い（—）」とも言わない）
    const unknown = new Set(row.unknown || []);
    const prefix = row.known_prefix || {};
    // 監査 C1（数値の書体）: この行の値が数値なら、セルに `num` を付ける
    // （`styles.css` の `td.cell.num` が等幅版の一族を当てる。seed は `kind` が `text`）
    const numeric = row.kind === 'num' || row.key === 'seed';
    const numClass = numeric ? ' num' : '';
    const cells = ids.map((id) => {
      // 値はサーバの並び（`doc.ids`）で返る。表示は並び替えても、添字だけ直せばよい
      const at = serverIndex(id);
      const value = row.values[at];
      if (unknown.has(id)) {
        const known = prefix[id];
        // **（ワーディング監査 W-22）** 敬体に揃え、「未捕獲」はほどく（G-6）
        const title = known
          ? `最終プロンプトは分かりません（訳を捕獲していません）。分かっているのは前置語だけです: ${known}`
          : '最終プロンプトは分かりません（訳を捕獲しておらず、来歴にもありません）';
        return `<td class="cell unknown${numClass}" title="${esc(title)}">`
          + '<span class="unknown-mark">分からない</span>'
          + (known ? `<span class="partial">前置語: ${esc(known)}</span>` : '') + '</td>';
      }
      const cellState = (row.cells || [])[at] || 'same';
      // **（ワーディング監査 W-52）** 体言止めをやめる
      const title = value == null ? '（この画像にはありません）' : String(value);
      return `<td class="cell ${esc(cellState)}${numClass}" title="${esc(title)}">`
        + (value == null ? '<span class="none">—</span>' : esc(value)) + '</td>';
    }).join('');
    const badge = row.state === 'same' ? ''
      : `<span class="badge ${esc(row.state)}">${esc(stateLabel(row.state))}</span>`;
    return `<tr class="row ${esc(row.state)}">`
      + `<th><span class="k">${esc(row.label)}</span>`
      + `<span class="tag">${esc(row.key)}</span>${badge}</th>${cells}</tr>`;
  }).join('');

  const hidden = state.showSame ? '' : (diff.same.length
    ? `<div class="cmp-note">同じ ${diff.same.length} 行は畳んであります`
      + `（<b>m</b> か「同じ行」で開く）。</div>`
    : '');
  $('cmp-diff').innerHTML = `
    <div class="cmp-tablewrap">
      <table class="cmp-table">
        <thead><tr><th class="key">来歴</th>${head}</tr></thead>
        <tbody>${body || '<tr><td class="cmp-note">違う行はありません（すべて同じ）。</td></tr>'}</tbody>
      </table>
    </div>
    ${hidden}
    ${promptBlock()}
    ${jaBlock()}`;
}

function stateLabel(value) {
  // **（ワーディング監査 W-50）** 「分からない」と「不明」を混ぜない（1 つの語に揃える）
  return {
    changed: '違い',
    reweighted: '重み',
    only_in_some: '一部のみ',
    // 監査 B2: 「分からない」を「同じ」や「違い」と言わない
    unknown: '分からない',
    incomplete: '一部が分からない',
  }[value] || value;
}

// 語の差分（サーバの `prompt_diff`。基準つき。点検 C10）
function promptBlock() {
  const detail = state.doc.diff.prompt_diff;
  if (!detail) return '';
  if (detail.too_long) {
    return '<div class="cmp-note">語が多すぎるので語の差分は省きました'
      + '（表には値をそのまま出しています）。</div>';
  }
  // 監査 B2: 訳が未捕獲の枚は「分からない」と描く（空の行にしない）
  const unknownIds = new Set(detail.unknown || []);
  // 監査 D5: 行の並びも**画面の並び**（番号だけ直しても、6,3,1,7… の順では読みにくい）
  const others = Object.keys(detail.per_asset)
    .filter((id) => id !== detail.base)
    .sort((a, b) => displayIndex(a) - displayIndex(b));
  const lines = [];
  if (unknownIds.has(detail.base)) {
    // 基準そのものが分からないと、他の枚の語と比べられない（「追加」とは言わない）
    lines.push('<div class="cmp-line"><span class="who">基準</span>'
      + '<span class="word unknown">訳を捕獲していない（分かりません）</span></div>');
  }
  for (const id of others) {
    const index = displayIndex(id);                 // 監査 C2: 番号は画面の並び
    if (unknownIds.has(id)) {
      lines.push(`<div class="cmp-line"><span class="who">${index + 1}</span>`
        + '<span class="word unknown">訳を捕獲していない（分かりません）</span></div>');
      continue;
    }
    const words = detail.per_asset[id].map((word) => {
      const weight = word.w ? `<span class="w">:${esc(word.w)}</span>` : '';
      return `<span class="word ${esc(word.state)}" title="${esc(word.state)}">`
        + `${esc(word.t)}${weight}</span>`;
    }).join(' ');
    lines.push(`<div class="cmp-line"><span class="who">${index + 1}</span>${words}</div>`);
  }
  const linesHtml = lines.join('');
  if (!linesHtml) return '';
  const tokens = detail.tokens.map((token) =>
    `<span class="word ${esc(token.state)}" title="${esc(token.state)}">${esc(token.t)}</span>`)
    .join(' ');
  const summary = unknownIds.size
    ? `訳を捕獲していない画像がある（${unknownIds.size} 枚は分かりません）`
    : detail.normalized_equal ? '語も重みも同じ'
      : detail.reweighted ? '語は同じ・重みが違う' : '語が違う';
  const moved = detail.tokens.filter((token) => token.state === 'moved').length;
  return `<details class="cmp-detail" open>
    <summary>語の差分（基準 ${displayIndex(detail.base) + 1} 番）
      <span class="src">${esc(summary)} / 移動 ${moved} 語</span></summary>
    ${linesHtml}
    <div class="cmp-line"><span class="who">全体</span>${tokens}</div>
  </details>`;
}

// 日本語原文の差分（文単位 → 文字単位。`comparison.md` §3.2）
function jaBlock() {
  const detail = state.doc.diff.ja_diff;
  if (!detail) return '';
  const others = Object.keys(detail.per_asset)
    .filter((id) => id !== detail.base)
    .sort((a, b) => displayIndex(a) - displayIndex(b));   // 監査 D5: 画面の並び
  const changed = others.filter((id) => {
    const got = detail.per_asset[id] || {};
    return (got.sentences || []).some((s) => s.state !== 'same') || (got.chars || []).length;
  });
  if (!changed.length) return '';
  const lines = changed.map((id) => {
    const index = displayIndex(id);                 // 監査 C2: 番号は画面の並び
    const got = detail.per_asset[id];
    const sentences = (got.sentences || []).map((s) =>
      `<span class="word ${esc(s.state)}" title="${esc(s.state)}">${esc(s.t)}</span>`).join(' ');
    const chars = (got.chars || []).length
      ? `<div class="cmp-chars">${got.chars.map((run) =>
        `<span class="word ${esc(run.state)}">${esc(run.t)}</span>`).join('')}</div>`
      : '';
    return `<div class="cmp-line"><span class="who">${index + 1}</span>${sentences}${chars}</div>`;
  }).join('');
  return `<details class="cmp-detail"><summary>日本語原文の差分
    <span class="src">文単位、次に文字単位</span></summary>${lines}</details>`;
}

// ---- 差分ヒートマップ（P5-3。`comparison.md` §2.3・設計 §0.5 G6）----

// 基準と選択中の組の規則。**サーバが返した `pairs` をそのまま読む**
// （同じ seed か pHash 距離がしきい値以下か、をここで計算し直さない。設計 §10-4）
function heatRule() {
  const doc = state.doc;
  if (!doc) return null;
  const other = otherId();
  if (!other || other === doc.base) return null;
  return (doc.pairs || []).find((pair) => pair.b_id === other && pair.a_id === doc.base)
    || (doc.pairs || []).find((pair) => pair.a_id === other && pair.b_id === doc.base)
    || { a_id: doc.base, b_id: other, phash_distance: null, same_seed: false,
         heatmap: { enabled: false, reason: 'この組の規則がありません（サーバの版が古い）' } };
}

function heatLine() {
  const rule = heatRule();
  const why = $('cmp-heatwhy');
  const button = $('cmp-heat');
  // **監査 A1**: 「差分ヒートマップ」を `disabled` にしない。`disabled` にすると click が
  // 発火せず、強制の口（`#cmp-heatforce`）が隠れた包みの中にあると**マウスだけでは
  // 到達できない**（包みを開くのは `d` キーだけだった＝`comparison.md` §6 に反する）。
  // 押せないことは `aria-disabled` と見た目（`is-off`）で示し、click は `toggleHeat()`
  // （理由と「強制して出す」を開く）に結んである。
  if (!rule) {
    if (button) {
      button.disabled = false;
      button.setAttribute('aria-disabled', 'true');
      button.classList.add('is-off');
      button.title = '差分: 2 枚以上を選ぶと出せます';
    }
    if (why) why.textContent = '差分: 2 枚以上を選ぶと出せます';
    showForce(false);
    return;
  }
  const enabled = rule.heatmap.enabled;
  if (button) {
    button.disabled = false;
    button.setAttribute('aria-disabled', enabled ? 'false' : 'true');
    button.classList.toggle('is-off', !enabled);
    button.title = enabled
      ? '差分ヒートマップを出す（d）'
      : `出せません: ${rule.heatmap.reason}（「強制して出す」で見られます）`;
  }
  if (why) {
    // 監査 C1（実行込みのやり直し）: 同じ seed は「合う」の予測ではない（実データでは
    // 85 組中そろうのは 4 組だけ）。言い切らず、出してから分かると書く。
    why.textContent = enabled
      ? (rule.same_seed
        ? '差分: 同じ seed の組です（合うかは出してみるまで分かりません）'
        : `差分: 出せます（pHash 距離 ${rule.phash_distance}）`)
      : `差分: ${rule.heatmap.reason}`;
  }
  // 監査 C1: 「強制して出す」は**常に**出しておく（規則の外の組だけでは、同じ seed の
  // 85 組中 81 組が「位置が合いません」で行き止まりになる）。すでに絵が出ているときは
  // `showForce()` が自分で隠す。
  showForce(true);
}

// 「強制して出す」の見え方（**1 か所で決める**。監査 A1）。
// `wanted` = 「規則の外なので押せば出せる」組かどうか。すでに強制した絵が出ているときは
// 用が済んでいるので隠す（`state.heat.heatmap.available`）。
function showForce(wanted) {
  const force = $('cmp-heatforce');
  if (!force) return;
  const shown = !!(state.heat && state.heat.heatmap && state.heat.heatmap.available === true);
  force.hidden = !wanted || shown;
}

function syncHeatBar() {
  const wrap = $('cmp-heatwrap');
  if (wrap) wrap.hidden = !state.heat;
  // 出している組と選択がずれたら閉じる（別の組の絵を残さない）
  if (state.heat && state.doc) {
    const other = otherId();
    const same = !!state.heatPair && state.heatPair.a === state.doc.base
      && state.heatPair.b === other;
    if (!same) closeHeat();
  }
  heatLine();
  renderHeat();
}

// 指標の 1 行。**サーバが返した値をそのまま並べる**（画面では計算しない）
function metricsLine(body) {
  const parts = [];
  if (body.ssim != null) parts.push(`SSIM ${Number(body.ssim).toFixed(3)}`);
  if (body.changed_fraction != null) {
    parts.push(`変化 ${(body.changed_fraction * 100).toFixed(1)}%`);
  }
  if (body.mean_abs != null) parts.push(`平均差 ${Number(body.mean_abs).toFixed(1)}`);
  parts.push(body.phash_distance == null ? 'pHash 距離 —' : `pHash 距離 ${body.phash_distance}`);
  const heat = body.heatmap || {};
  if (heat.dx != null) parts.push(`ずれ ${heat.dx}×${heat.dy}px`);
  return parts.join(' / ');
}

function renderHeat() {
  const wrap = $('cmp-heatwrap');
  if (!wrap) return;
  const stage = $('cmp-stage');
  if (!state.heat) {
    wrap.hidden = true;
    if (stage) stage.hidden = false;
    return;
  }
  wrap.hidden = false;
  if (stage) stage.hidden = true;              // ヒートマップを見ている間はタイルを隠す
  const heat = state.heat.heatmap || {};
  const order = orderedIds();
  $('cmp-heatpair').textContent =
    `基準 ${indexOfBase() + 1} 番と ${order.indexOf(state.heatPair.b) + 1} 番`;
  $('cmp-heatmetrics').textContent = metricsLine(state.heat);
  if (heat.available && heat.image) {
    $('cmp-heatimg').innerHTML =
      `<img class="heat" src="${esc(heat.image)}" alt="差分ヒートマップ">`;
  } else {
    // 位置が合わないときは**画像ではなく理由**を出す（`comparison.md` §2.3）
    $('cmp-heatimg').innerHTML =
      `<div class="cmp-note heat-no">差分を出せません（${esc(heat.reason || '理由は不明です')}）</div>`;
  }
}

// 「差分ヒートマップ」を開く。条件の外では**要求を出さずに理由と「強制して出す」**を出す
// （点検 G6。画像の計算は 2 枚の復号を伴うので、出せない組では走らせない）
function openHeat() {
  const rule = heatRule();
  if (!rule) return;
  if (!rule.heatmap.enabled) {
    state.heatPair = { a: state.doc.base, b: otherId() };
    state.heat = { ssim: null, changed_fraction: null, mean_abs: null,
                   phash_distance: rule.phash_distance,
                   heatmap: { enabled: false, forced: false, available: false,
                              reason: rule.heatmap.reason } };
    syncHeatBar();
    return;
  }
  showHeat(false);
}

// 差分を出す（利用者が押した / `d` キー）。**サーバがその場で作る**（保存しない）
async function showHeat(force) {
  const doc = state.doc;
  const other = otherId();
  if (!doc || !other) return;
  const body = { a_id: doc.base, b_id: other, force: !!force };
  $('cmp-heatimg').innerHTML = '<div class="cmp-note">差分を作っています…</div>';
  state.heatPair = { a: doc.base, b: other };
  state.heat = { ssim: null, changed_fraction: null, mean_abs: null, phash_distance: null,
                 heatmap: { enabled: false, forced: !!force, available: false,
                            reason: '作っています…' } };
  syncHeatBar();
  try {
    const res = await fetch(PAIR_API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const text = await res.text();
    if (!res.ok) throw new Error(detailOf(res.status, text));
    state.heat = JSON.parse(text);
  } catch (error) {
    state.heat = { ssim: null, changed_fraction: null, mean_abs: null, phash_distance: null,
                   heatmap: { enabled: false, forced: !!force, available: false,
                              reason: error.message } };
  }
  renderHeat();
  heatLine();
}

function closeHeat() {
  state.heat = null;
  state.heatPair = null;
  const wrap = $('cmp-heatwrap');
  if (wrap) wrap.hidden = true;
  const stage = $('cmp-stage');
  if (stage) stage.hidden = false;
  heatLine();          // 強制の口の見え方も戻す（監査 A1。理由の 1 行の隣に出し直す）
}

function cycleOrder() {
  const at = ORDERS.findIndex((entry) => entry.id === state.order);
  state.order = ORDERS[(at + 1) % ORDERS.length].id;
  syncOrderLabel();
  closeHeat();
  render();
}

// 並び順のボタンの表示（**1 か所で決める**）
function syncOrderLabel() {
  const button = $('cmp-order');
  if (button) {
    button.textContent = `並び: ${ORDERS.find((entry) => entry.id === state.order).label}`;
  }
}

// ---- 同期ズーム（`comparison.md` §2.2）----

function viewOf(assetId) {
  if (!state.views.has(assetId)) state.views.set(assetId, { s: 1, x: 0, y: 0 });
  return state.views.get(assetId);
}

function applyView(assetId) {
  const el = document.querySelector(`.cmp-zoom[data-id="${sel(assetId)}"]`);
  if (!el) return;
  const view = viewOf(assetId);
  el.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.s})`;
}

function setView(assetId, next) {
  const view = {
    s: Math.max(MIN_SCALE, Math.min(MAX_SCALE, next.s)),
    x: next.x,
    y: next.y,
  };
  if (state.sync) {
    // 1 枚を動かすと全部が追従する（同じ倍率と同じずれ）
    for (const key of state.views.keys()) {
      state.views.set(key, { ...view });
      applyView(key);
    }
  } else {
    state.views.set(assetId, { ...view });
    applyView(assetId);
  }
  renderZoomLabel(view.s);
}

function renderZoomLabel(scale) {
  const el = $('cmp-zoom');
  if (!el) return;
  const at = scale != null ? scale : viewOf(state.selected).s;
  el.textContent = `${at.toFixed(2)}×`;
}

function select(assetId) {
  state.selected = assetId;
  for (const tile of document.querySelectorAll('.cmp-tile')) tile.classList.remove('selected');
  const frame = document.querySelector(`.cmp-frame[data-id="${sel(assetId)}"]`);
  if (frame) frame.parentElement.classList.add('selected');
  renderZoomLabel();
  syncHeatBar();                 // 組が変わったら差分を閉じ、理由を出し直す（P5-3）
}

function onWheel(event, assetId) {
  event.preventDefault();
  select(assetId);
  zoomAt(assetId, event.clientX, event.clientY, Math.exp(-event.deltaY * 0.0015));
}

function zoomAt(assetId, clientX, clientY, factor) {
  const frame = document.querySelector(`.cmp-frame[data-id="${sel(assetId)}"]`);
  if (!frame) return;
  const rect = frame.getBoundingClientRect();
  const view = viewOf(assetId);
  const scale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, view.s * factor));
  const k = scale / view.s;
  // ポインタの下の点を動かさない（`m` は枠の中心からのずれ。枠の高さは全枚で同じ）
  const mx = clientX - (rect.left + rect.width / 2);
  const my = clientY - (rect.top + rect.height / 2);
  setView(assetId, { s: scale, x: mx * (1 - k) + k * view.x, y: my * (1 - k) + k * view.y });
}

function onDragStart(event, assetId) {
  if (event.button !== 0) return;
  event.preventDefault();
  select(assetId);
  const start = { ...viewOf(assetId) };
  const from = { x: event.clientX, y: event.clientY };
  const frame = event.currentTarget;
  frame.classList.add('dragging');
  const move = (e) => {
    setView(assetId, {
      s: start.s,
      x: start.x + (e.clientX - from.x),
      y: start.y + (e.clientY - from.y),
    });
  };
  const stop = () => {
    frame.classList.remove('dragging');
    window.removeEventListener('mousemove', move);
    window.removeEventListener('mouseup', stop);
  };
  window.addEventListener('mousemove', move);
  window.addEventListener('mouseup', stop);
}

// ---- キー（補助。無くてもマウスだけでできる。§6）----

function frameCenter(assetId) {
  const frame = document.querySelector(`.cmp-frame[data-id="${sel(assetId)}"]`);
  if (!frame) return { x: 0, y: 0 };
  const rect = frame.getBoundingClientRect();
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

function installKeys() {
  if (keyHandler) document.removeEventListener('keydown', keyHandler);
  keyHandler = (event) => {
    const tag = (event.target && event.target.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    const view = viewOf(state.selected);
    const step = 40;
    const center = frameCenter(state.selected);
    if (event.key === '+' || event.key === '=') zoomAt(state.selected, center.x, center.y, 1.25);
    else if (event.key === '-') zoomAt(state.selected, center.x, center.y, 0.8);
    else if (event.key === '0') setView(state.selected, { s: 1, x: 0, y: 0 });
    else if (event.key === 'z') toggleSync();
    else if (event.key === 'm') toggleSame();
    // P5-3: `d` は差分ヒートマップ、`r` は並び順（`comparison.md` §6 の割り当て）
    else if (event.key === 'd') { toggleHeat(); return; }
    else if (event.key === 'r') { cycleOrder(); return; }
    // 監査 C1: 選択中のタイルを基準にする（マウスは「基準にする」ボタン。キーは補助）
    else if (event.key === 'b') { setBase(state.selected); return; }
    else if (event.key === 'ArrowLeft') setView(state.selected, { ...view, x: view.x + step });
    else if (event.key === 'ArrowRight') setView(state.selected, { ...view, x: view.x - step });
    else if (event.key === 'ArrowUp') setView(state.selected, { ...view, y: view.y + step });
    else if (event.key === 'ArrowDown') setView(state.selected, { ...view, y: view.y - step });
    else if (event.key === 'Escape') { location.hash = ''; return; }
    else if (/^[1-8]$/.test(event.key)) {
      // 監査 C2: 番号は**画面の並び**（似ている順でも、押した番号のタイルが選ばれる）
      const id = orderedIds()[Number(event.key) - 1];
      if (id) select(id);
      return;
    } else return;
    event.preventDefault();
  };
  document.addEventListener('keydown', keyHandler);
}

function toggleSync() {
  state.sync = !state.sync;
  const button = $('cmp-sync');
  if (button) button.textContent = `同期ズーム: ${state.sync ? '入' : '切'}`;
  if (state.sync) setView(state.selected, { ...viewOf(state.selected) });
}

function toggleSame() {
  state.showSame = !state.showSame;
  const button = $('cmp-same');
  if (button) button.textContent = `同じ行: ${state.showSame ? '出す' : '畳む'}`;
  renderDiff();
}

// 「差分ヒートマップ」ボタンと `d` キー（**キーは補助**。§6。監査 A1: ボタンだけでも届く）。
// 開いていれば閉じ、閉じていれば出す（条件の外は理由＋「強制して出す」を開く）
function toggleHeat() {
  if (state.heat) {
    closeHeat();
    return;
  }
  openHeat();
}

// 画面のボタンと結び付ける（`app.js` が起動時に 1 回呼ぶ）
export function wireCompare() {
  const same = $('cmp-same');
  if (same) same.addEventListener('click', toggleSame);
  const sync = $('cmp-sync');
  if (sync) sync.addEventListener('click', toggleSync);
  // P5-3
  const order = $('cmp-order');
  if (order) order.addEventListener('click', cycleOrder);
  // 監査 A1: 出せる組ではそのまま出す。出せない組では理由と「強制して出す」を開く
  // （`toggleHeat()` が両方を決める。`disabled` にしないので click が必ず届く）
  const heat = $('cmp-heat');
  if (heat) heat.addEventListener('click', toggleHeat);
  const force = $('cmp-heatforce');
  if (force) force.addEventListener('click', () => showHeat(true));
  const close = $('cmp-heatclose');
  if (close) close.addEventListener('click', closeHeat);
  const one = $('cmp-one');
  if (one) one.addEventListener('click', () => {
    for (const key of state.views.keys()) {
      state.views.set(key, { s: 1, x: 0, y: 0 });
      applyView(key);
    }
    renderZoomLabel(1);
  });
  window.addEventListener('resize', () => {
    if (!state.doc) return;
    if (!document.body.classList.contains('comparing')) return;
    renderStage();
  });
}
