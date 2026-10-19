// 画像の上の印（注記。P6-2）
// 設計: docs/p6-design.md §5.3（拡大の画面）・§3.6（口）・§0.6（GET は書かない）・§0.7（座標）
//       docs/frontend-design.md §4.3（矩形と楕円・右の列に一覧・`--accent` の細い実線）
//
// 約束:
// - **4 px 未満のドラッグでは作らない**（誤操作。§8.2-6）
// - 座標は **0〜1 の割合**（画面の大きさに依らない。§0.7）
// - **`GET` は書かない**。切り出しを**書く**のは「切り出しを書き出す」を押したときだけ（POST）
// - 消せる・メモを変えられるのは**自分（human）の注記だけ**（点検 C7。断られたら 1 行で知らせる）
// - ドラッグで矩形、**Shift + ドラッグで楕円**（`frontend-design.md` §4.3）

const ACTOR = { 'X-Image-Reviewer-Actor': 'human' };
const JSON_HEADERS = { 'Content-Type': 'application/json', ...ACTOR };
export const MIN_DRAG_PX = 4;              // これ未満は「作らない」（§8.2-6）

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? '').replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

const state = {
  assetId: null,
  items: [],
  drawing: false,
  shape: 'rect',
  draft: null,      // {x1, y1, x2, y2}（画素。ステージの座標）
  error: null,
  note: null,
};

// どのまとまりのレビューから来たか（`#/asset/<id>?group=<id>`。`app.js` が入れる）。
// **注記に付けると、要求の `response.annotations`（`group_id` 一致で導出）に出る**
// （P6-2 の実装者が見つけた穴。まとまりレビュー → 拡大 → 印 → 決める、が繋がる）。
// `resetAnnotations()` では消さない（`app.js` の `select()` が先に呼ぶため）
let groupId = null;

export function setAnnotationGroup(id) {
  groupId = id || null;
}

export function resetAnnotations() {
  state.assetId = null;
  state.items = [];
  state.drawing = false;
  state.draft = null;
  state.error = null;
  state.note = null;
}

function surface() {
  return document.querySelector('.anno-stage');
}

// ---- 一覧の取得と描画 ----

async function refresh() {
  const assetId = state.assetId;
  if (!assetId) return;
  try {
    const res = await fetch(`/api/assets/${encodeURIComponent(assetId)}/annotations`);
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || res.status);
    state.items = body.items || [];
    state.error = null;
  } catch (error) {
    // **（C-8）** 英語の例外文は本文に出さず、次の一手を添える（§6.1 の規約 3）
    state.error = `注記を読めませんでした。もう一度試してください（詳細: ${error.message}）。`;
  }
  render();
}

function render() {
  // 一覧の並び（古い順）で**全件に番号を振る**。画像の印も**同じ番号**を使う
  // （別々に数えると、メモが間にあるとずれる。P6-2 の監査 上位 3:
  //  一覧「3: 楕円」に画像の印は「2」になっていた）
  const rows = state.items.map((item, index) => ({ item, no: index + 1 }));
  const list = $('anno-list');
  if (list) {
    list.innerHTML = rows.length
      ? rows.map(({ item, no }) => {
        const shape = item.shape === 'ellipse' ? '楕円' : item.shape === 'rect' ? '矩形' : 'メモ';
        const who = item.actor === 'agent' ? 'エージェント' : '人';
        // **（A-12）** 値が無いときの文は「（なし）」の 1 形
        const body = item.body ? esc(item.body) : '<span class="none">（なし）</span>';
        // メモ（領域なし）は**切れない**ので、リンクを出さない（押すと 422 になる。監査 C-8）
        // **（C-16・G-1）** 押すと何かが起きる物は終止形（「切り出し」→「切り出しを保存する」）
        const crop = item.shape
          ? `<a class="anno-get" href="/api/annotations/${esc(item.id)}/crop" download>切り出しを保存する</a>`
          : '';
        return `<div class="anno-row" data-anno="${esc(item.id)}">
            <span class="anno-no">${no}</span>
            <span class="anno-shape">${shape}</span>
            <span class="anno-body">${body}</span>
            <span class="anno-who">${who}</span>
            ${crop}
            <button type="button" class="anno-del" data-del="${esc(item.id)}">消す</button>
          </div>`;
      }).join('')
      : '<div class="stat">まだ注記はありません。ドラッグで囲むと付きます。</div>';
  }
  const stage = surface();
  if (stage) {
    const layer = stage.querySelector('.anno-layer');
    if (layer) layer.innerHTML = rows.filter(({ item }) => item.shape).map(({ item, no }) => (
      item.shape === 'ellipse'
        ? `<div class="anno-mark ellipse" style="left:${item.x * 100}%;top:${item.y * 100}%;
             width:${item.w * 100}%;height:${item.h * 100}%"><span>${no}</span></div>`
        : `<div class="anno-mark" style="left:${item.x * 100}%;top:${item.y * 100}%;
             width:${item.w * 100}%;height:${item.h * 100}%"><span>${no}</span></div>`
    )).join('');
    const draft = state.draft;
    if (draft) {
      const box = normalized(draft);
      layer.insertAdjacentHTML('beforeend',
        `<div class="anno-mark draft" style="left:${box.left}px;top:${box.top}px;
           width:${box.width}px;height:${box.height}px"></div>`);
    }
  }
  const note = $('anno-note');
  if (note) note.textContent = state.error || state.note || '';
  const toggle = $('anno-toggle');
  if (toggle) toggle.textContent = state.drawing ? '注記: 描く' : '注記: 見るだけ';
  const shape = $('anno-shape');
  if (shape) shape.value = state.shape;
}

// ドラッグ中の下書きを、ステージの中の箱に直す（負の幅を作らない）
function normalized(draft) {
  return {
    left: Math.min(draft.x1, draft.x2),
    top: Math.min(draft.y1, draft.y2),
    width: Math.abs(draft.x2 - draft.x1),
    height: Math.abs(draft.y2 - draft.y1),
  };
}

// ---- 描く ----

function pointOf(event, stage, image) {
  const box = (image || stage).getBoundingClientRect();
  return { x: event.clientX - box.left, y: event.clientY - box.top, box };
}

async function commit(image) {
  const draft = state.draft;
  state.draft = null;
  if (!draft) return;
  const box = normalized(draft);
  // **4 px 未満は作らない**（誤操作。§8.2-6）
  if (box.width < MIN_DRAG_PX || box.height < MIN_DRAG_PX) {
    // **（A-4・G-10）** 通知も文なので「。」を付ける
    state.note = '小さすぎるので作りませんでした（4 px 以上で囲んでください）。';
    render();
    return;
  }
  const rect = image.getBoundingClientRect();
  const keep = (v) => Math.min(1, Math.max(0, v));
  const x = keep(box.left / rect.width);
  const y = keep(box.top / rect.height);
  const w = Math.min(1 - x, box.width / rect.width);
  const h = Math.min(1 - y, box.height / rect.height);
  try {
    const res = await fetch(`/api/assets/${encodeURIComponent(state.assetId)}/annotations`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ shape: state.shape, x, y, w, h, group_id: groupId }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || res.status);
    }
    state.note = '注記を付けました。メモを書くなら一覧の「メモ」から書けます。';
  } catch (error) {
    state.error = `注記を付けられませんでした。もう一度試してください（詳細: ${error.message}）。`;
  }
  await refresh();
}

// ---- メモ（領域なしの注記もここから）----

async function addMemo() {
  const field = $('anno-memo');
  const text = (field?.value || '').trim();
  if (!text) {
    state.error = 'メモが空です。何か書いてから押してください。';
    render();
    return;
  }
  try {
    const res = await fetch(`/api/assets/${encodeURIComponent(state.assetId)}/annotations`, {
      method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ body: text, group_id: groupId }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || res.status);
    }
    if (field) field.value = '';
    state.error = null;
    state.note = 'メモを足しました。';
  } catch (error) {
    state.error = `メモを足せませんでした。もう一度試してください（詳細: ${error.message}）。`;
  }
  await refresh();
}

async function remove(id) {
  try {
    const res = await fetch(`/api/annotations/${encodeURIComponent(id)}`,
      { method: 'DELETE', headers: ACTOR });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || res.status);
    }
    state.note = '消しました。';
    state.error = null;
  } catch (error) {
    state.error = `消せませんでした。もう一度試してください（詳細: ${error.message}）。`;
  }
  await refresh();
}

// ---- 書き出し ----

async function exportJson() {
  try {
    const res = await fetch(`/api/assets/${encodeURIComponent(state.assetId)}/annotations/export`);
    const doc = await res.json();
    if (!res.ok) throw new Error(doc.detail || res.status);
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `annotations-${state.assetId}.json`;
    a.click();
    URL.revokeObjectURL(url);
    state.note = '座標と文の JSON を作りました。';
  } catch (error) {
    state.error = `書き出せませんでした。もう一度試してください（詳細: ${error.message}）。`;
  }
  render();
}

async function exportCrops() {
  try {
    // **書くのはここだけ**（§0.6）。同じ名前に上書きするので何度押しても増えない
    const res = await fetch(`/api/assets/${encodeURIComponent(state.assetId)}/annotations/export`, {
      method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ format: 'crops' }),
    });
    const doc = await res.json();
    if (!res.ok) throw new Error(doc.detail || res.status);
    state.note = `切り出しを ${doc.crops.length} 枚書き出しました（${doc.crops[0]?.path.split('/')[0]}/…）。`;
  } catch (error) {
    state.error = `書き出せませんでした。もう一度試してください（詳細: ${error.message}）。`;
  }
  render();
}

// ---- 取り付け（`app.js` の `select()` から呼ぶ）----

export async function mountAnnotations(container, assetId) {
  resetAnnotations();
  state.assetId = assetId;
  const image = container.querySelector('img.preview');
  if (!image) return;

  const stage = document.createElement('div');
  stage.className = 'anno-stage';
  image.replaceWith(stage);
  stage.appendChild(image);
  const layer = document.createElement('div');
  layer.className = 'anno-layer';
  stage.appendChild(layer);

  const box = document.createElement('div');
  box.className = 'anno-box';
  box.innerHTML = `
    <div class="anno-bar">
      <button type="button" id="anno-toggle">注記: 見るだけ</button>
      <select id="anno-shape"><option value="rect">矩形</option><option value="ellipse">楕円</option></select>
      <span class="stat">ドラッグで囲む（Shift で楕円）</span>
    </div>
    <div class="anno-bar">
      <input type="text" id="anno-memo" placeholder="画像 1 枚へのメモ">
      <button type="button" id="anno-memo-add">メモを足す</button>
      <!-- **（C-16・G-1）** 名詞形を終止形に（「座標 JSON」→「座標 JSON を作る」） -->
      <button type="button" id="anno-json">座標 JSON を作る</button>
      <button type="button" id="anno-crops">切り出しを書き出す</button>
    </div>
    <div class="stat" id="anno-note"></div>
    <h3>注記</h3>
    <div id="anno-list" class="anno-list"></div>`;
  // **入口は画像のすぐ下に置く**（P6-2 の監査: いまは `#detail` の末尾だったので、来歴の長い
  // 画像では 2700 px 下になり、スクロールしないと見えなかった。`frontend-design.md` §4.3 の
  // 「拡大の画面」の意図に合わせる）
  if (stage.parentNode) stage.parentNode.insertBefore(box, stage.nextSibling);
  else container.appendChild(box);

  $('anno-toggle').addEventListener('click', () => {
    state.drawing = !state.drawing;
    state.draft = null;
    render();
  });
  $('anno-shape').addEventListener('change', (event) => { state.shape = event.target.value; });
  $('anno-memo-add').addEventListener('click', addMemo);
  $('anno-json').addEventListener('click', exportJson);
  $('anno-crops').addEventListener('click', exportCrops);
  $('anno-list').addEventListener('click', (event) => {
    const id = event.target?.getAttribute?.('data-del');
    if (id) remove(id);
  });

  stage.addEventListener('mousedown', (event) => {
    if (!state.drawing || event.button !== 0) return;
    event.preventDefault();
    const at = pointOf(event, stage, image);
    state.draft = { x1: at.x, y1: at.y, x2: at.x, y2: at.y };
    render();
  });
  stage.addEventListener('mousemove', (event) => {
    if (!state.draft) return;
    const at = pointOf(event, stage, image);
    state.draft.x2 = at.x;
    state.draft.y2 = at.y;
    render();
  });
  stage.addEventListener('mouseup', async (event) => {
    if (!state.draft) return;
    if (event.shiftKey) state.shape = 'ellipse';
    await commit(image);
  });
  stage.addEventListener('mouseleave', () => {
    if (state.draft) { state.draft = null; render(); }
  });

  await refresh();
}
