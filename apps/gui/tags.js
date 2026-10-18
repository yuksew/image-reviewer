// 1 枚のタグ欄（P4-3）
// 設計: docs/p4-design.md §5.1（2 行 1 組・出所の印・スコアは 3 桁・「訳す」・「語を足す」・「外す」は manual だけ）/
//       §3.4（応答の形: items / glosses / pending_gloss / counts）/ §0.8（known=false の印）/ §0.7（括弧は消さない）/
//       docs/frontend-design.md §4.13（タグ）
//
// 約束:
// - **2 行 1 組**（1 行目 英語 / 2 行目 日本語の語釈）。**語釈の行に括弧書きを足さない**。
//   **語そのものの括弧は消さない**（`rem_(re:zero)` はそのまま出す。点検 A-1 / G-5）
// - **`GET` は訳さない**。訳すのは `POST /api/tags/gloss`（§0.10）
// - **同じ語を 1 行にまとめる**（出所は `sources` に全部。§2.4）
// - **`esc()` を必ず通す**（語と語釈は外から来る文字列）

const $ = (id) => document.getElementById(id);
const GLOSS_API = '/api/tags/gloss';
const TAGS_API = '/api/tags';

//: まとめて訳す単位（§0.9。20 語で実測 4.6〜4.8 秒）
export const GLOSS_LIMIT = 20;

//: カテゴリの見出し（**無いカテゴリは出さない**。§5.1）。この CSV は 4 と 0 だけ
export const CATEGORY_LABEL = { 4: 'キャラ', 3: '作品', 1: '作者', 0: '一般', 9: 'rating' };
const CATEGORY_RANK = [4, 3, 1, 0, 9];

//: タグの出どころ（§5.1。`manual` は「手」）。
//: **（ワーディング監査 §4）** 「印」は 6 つの物を指していて分からないので、ここは「出どころ」と呼ぶ
export const SOURCE_LABEL = { png: 'PNG', wd14: 'タガー', manual: '手' };

export function esc(value) {
  return String(value ?? '').replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// ---- 組み立て（純関数。テストはここを直接見る）----

/** 同じ語（`name`）を 1 行にまとめる（§2.4）。`score` は最大、`sources` は合算、`known` は OR。 */
export function mergeWords(items) {
  const byName = new Map();
  for (const item of items || []) {
    const key = item.name;
    const got = byName.get(key);
    if (!got) {
      byName.set(key, {
        name: key,
        category: item.category ?? null,
        category_name: item.category_name ?? null,
        known: Boolean(item.known),
        score: item.score ?? null,
        sources: [...(item.sources || [item.source]).filter(Boolean)],
        gloss: item.gloss ?? null,
        gloss_edited: item.gloss_edited ?? null,
      });
      continue;
    }
    for (const s of item.sources || [item.source]) {
      if (s && !got.sources.includes(s)) got.sources.push(s);
    }
    if (item.score != null && (got.score == null || item.score > got.score)) got.score = item.score;
    if (!got.gloss && item.gloss) got.gloss = item.gloss;
    got.known = got.known || Boolean(item.known);
    if (got.category == null) got.category = item.category ?? null;
  }
  return [...byName.values()];
}

/** 並びは §0.10（カテゴリ → スコア降順・NULL 最後 → 名前）。**同じ入力なら同じ並び**。 */
export function sortWords(words) {
  const rank = (w) => {
    const at = CATEGORY_RANK.indexOf(w.category);
    return at < 0 ? CATEGORY_RANK.length : at;
  };
  return [...words].sort((a, b) => {
    if (rank(a) !== rank(b)) return rank(a) - rank(b);
    const as = a.score == null ? -1 : a.score;          // NULL は最後
    const bs = b.score == null ? -1 : b.score;
    if (as !== bs) return bs - as;
    return String(a.name).localeCompare(String(b.name));
  });
}

/** カテゴリごとの束（**語が無いカテゴリは出さない**。§5.1）。 */
export function groupByCategory(words) {
  const groups = [];
  for (const w of sortWords(words)) {
    const label = CATEGORY_LABEL[w.category] || (w.category_name ? esc(w.category_name) : 'その他');
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.words.push(w);
    else groups.push({ label, words: [w] });
  }
  return groups;
}

/** 出所の印（複数あれば印も複数。§5.1）。 */
export function sourceMarks(sources) {
  return (sources || []).map((s) =>
    `<span class="tg-src tg-src-${esc(s)}" title="${esc(s)}">${esc(SOURCE_LABEL[s] || s)}</span>`).join('');
}

/** スコアは**タガーの行だけ**、小数 3 桁（§5.1）。 */
export function scoreText(word) {
  if (word.score == null) return '';
  if (!(word.sources || []).some((s) => s === 'wd14')) return '';
  return `<span class="tg-score num">${Number(word.score).toFixed(3)}</span>`;
}

/** 1 語の 2 行 1 組（§5.1）。`gloss` が無ければ「まだありません」＋「訳す」。 */
export function wordRowHtml(word, { pending = true } = {}) {
  const unknown = word.known === false
    ? '<span class="tg-unknown" title="タグの語彙（Danbooru）に無い語。既定の検索では出ません">語彙外</span>' : '';
  const remove = (word.sources || []).includes('manual')
    ? `<button class="tg-remove" data-name="${esc(word.name)}" title="人が付けた語を外す">外す</button>` : '';
  const gloss = word.gloss
    ? `<div class="ja">${esc(word.gloss)}${word.gloss_edited ? '<span class="tg-edited">人が直した</span>' : ''}</div>`
    : `<div class="ja tg-none">日本語の語釈はまだありません。`
      + (pending ? `<button class="tg-translate" data-name="${esc(word.name)}">訳す</button>` : '')
      + '</div>';
  return `<div class="tg-row" data-name="${esc(word.name)}">`
    + `<div class="en"><span class="tg-name">${esc(word.name)}</span>${unknown}`
    + `${sourceMarks(word.sources)}${scoreText(word)}${remove}</div>`
    + gloss
    + '</div>';
}

/** 語釈待ちの数と出所ごとの数（`counts` は出所ごと。§3.4）。 */
export function briefHtml(data) {
  const counts = data.counts || {};
  const parts = Object.keys(SOURCE_LABEL)
    .filter((s) => counts[s])
    .map((s) => `${SOURCE_LABEL[s]} ${counts[s]}`);
  const pending = (data.pending_gloss || []).length;
  return `${parts.join('、') || 'タグなし'}${pending ? `、語釈待ち ${pending} 語` : ''}`;
}

/** 欄ぜんたい（見出し・説明・操作・本体）。 */
export function panelHtml(data) {
  const words = mergeWords(data.items || []);
  const groups = groupByCategory(words);
  const pending = (data.pending_gloss || []).length;
  const body = groups.length
    ? groups.map((g) => `<h4 class="tg-head">${esc(g.label)}</h4>`
        + g.words.map((w) => wordRowHtml(w)).join('')).join('')
    : '<div class="note">この画像にはまだタグがありません。タグの一覧（<b>タグ</b>）の「一括タグ付け」で付けるか、下の「語を足す」で 1 つずつ付けられます。</div>';
  return `<div class="tg-brief">${esc(briefHtml(data))}</div>`
    + body
    + '<div class="tg-actions">'
    + `<button id="tg-translate-all"${pending ? '' : ' disabled'} title="見えている語のうち語釈が無いものを ${GLOSS_LIMIT} 語まで訳す">`
    + `訳す（${GLOSS_LIMIT} 語まで）</button>`
    + '<span class="tg-add"><input id="tg-add-input" type="text" placeholder="語を足す（例: long_hair）" '
    + 'list="tg-candidates" autocomplete="off"><datalist id="tg-candidates"></datalist>'
    + '<button id="tg-add-go">足す</button></span>'
    + '</div>'
    + '<div class="tg-msg" id="tg-msg" hidden></div>'
    + '<div class="tg-help">タガーは下ごしらえで、手の破綻までは読めません。人が見て直してください。'
    + '訳は自動ですが、直せます。</div>';
}

// ---- 取得と操作 ----

let state = { assetId: null, data: null, ids: new Map(), wired: false };

/** 語名 → `tag_id` の地図を作る。
 *
 * **`GET /api/assets/{id}/tags` の items には `tag_id` が入っていない**（契約の形に合わせてあるため。
 * P4-2 の実装の記録・報告を参照）。訳す口と外す口は `tag_id` を要るので、語の一覧から 1 回だけ引いて作る。
 * 語は数百件なので 1 回で足りる（`limit=1000`）。
 */
export async function loadIds() {
  const body = await (await fetch(`${TAGS_API}?known=all&limit=1000`)).json();
  const map = new Map();
  for (const item of body.items || []) map.set(item.name, item.tag_id);
  state.ids = map;
  return map;
}

export function idOf(name) {
  return state.ids.get(name) ?? null;
}

/** 「訳す」。`tag_ids` を渡す（**名前では訳せない**）。 */
export async function translate(names) {
  const ids = names.map((n) => idOf(n)).filter((v) => v != null).slice(0, GLOSS_LIMIT);
  if (!ids.length) return { translated: [], skipped: [], untranslated: [], calls: 0 };
  const res = await fetch(GLOSS_API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' },
    body: JSON.stringify({ tag_ids: ids, limit: GLOSS_LIMIT }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail || `${res.status}`);
  return body;
}

export function messageOf(body) {
  const t = (body.translated || []).length;
  const u = (body.untranslated || []).length;
  const s = (body.skipped || []).length;
  const parts = [`${t} 語を訳しました`];
  if (s) parts.push(`${s} 語は語釈済み`);
  if (u) parts.push(`${u} 語は訳せませんでした（保存していません）`);
  return `${parts.join('、')}。`;
}

async function reload() {
  const container = $('tg-panel');
  if (!container || !state.assetId) return;
  const res = await fetch(`/api/assets/${encodeURIComponent(state.assetId)}/tags`);
  state.data = await res.json();
  container.innerHTML = panelHtml(state.data);
  wirePanel(container);
}

function wirePanel(container) {
  const msg = (text, bad) => {
    const el = $('tg-msg');
    if (!el) return;
    el.textContent = text;
    el.hidden = !text;
    el.classList.toggle('bad', Boolean(bad));
  };
  const translateAll = $('tg-translate-all');
  if (translateAll) {
    translateAll.addEventListener('click', async () => {
      const pending = (state.data.pending_gloss || []).slice(0, GLOSS_LIMIT);
      translateAll.disabled = true;
      try {
        const body = await translate(pending);
        await reload();
        const el = $('tg-msg');
        if (el) { el.textContent = messageOf(body); el.hidden = false; }
      } catch (error) {
        msg(`訳せません: ${error.message}`, true);
        translateAll.disabled = false;
      }
    });
  }
  for (const btn of container.querySelectorAll('.tg-translate')) {
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        const body = await translate([btn.dataset.name]);
        await reload();
        const el = $('tg-msg');
        if (el) { el.textContent = messageOf(body); el.hidden = false; }
      } catch (error) {
        msg(`訳せません: ${error.message}`, true);
        btn.disabled = false;
      }
    });
  }
  for (const btn of container.querySelectorAll('.tg-remove')) {
    btn.addEventListener('click', async () => {
      const id = idOf(btn.dataset.name);
      if (id == null) { msg('語の id が分かりません（読み直してください）', true); return; }
      const res = await fetch(`/api/assets/${encodeURIComponent(state.assetId)}/tags/${id}`, {
        method: 'DELETE', headers: { 'X-Image-Reviewer-Actor': 'human' },
      });
      if (!res.ok) { const b = await res.json().catch(() => ({})); msg(b.detail || `外せません（${res.status}）`, true); return; }
      await reload();
      msg('外しました。');
    });
  }
  const addInput = $('tg-add-input');
  const addGo = $('tg-add-go');
  const candidates = $('tg-candidates');
  if (addInput && candidates) {
    addInput.addEventListener('input', async () => {
      const q = addInput.value.trim();
      if (!q) { candidates.innerHTML = ''; return; }
      try {
        const body = await (await fetch(`${TAGS_API}?q=${encodeURIComponent(q)}&limit=8`)).json();
        candidates.innerHTML = (body.items || [])
          .map((it) => `<option value="${esc(it.name)}">${esc(String(it.uses))} 枚</option>`).join('');
      } catch (error) { /* 候補が出ないだけで止めない */ }
    });
  }
  if (addGo && addInput) {
    addGo.addEventListener('click', async () => {
      const name = addInput.value.trim();
      if (!name) return;                       // 空なら送らない
      const res = await fetch(`/api/assets/${encodeURIComponent(state.assetId)}/tags`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' },
        body: JSON.stringify({ name }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) { msg(body.detail || `付けられません（${res.status}）`, true); return; }
      addInput.value = '';
      await reload();
      msg(body.added ? '足しました。' : 'もう付いています。');
    });
  }
}

/** 詳細（`#/asset/<id>`）のタグ欄を取り付ける。**view 側は器だけ置く**。 */
export async function mountTags(container, assetId) {
  if (!container) return;
  state.assetId = assetId;
  state.wired = true;
  try {
    await loadIds();
    await reload();
  } catch (error) {
    container.innerHTML = `<div class="note">タグを読めません: ${esc(error.message)}</div>`;
  }
}

export function resetTags() {
  state = { assetId: null, data: null, ids: new Map(), wired: false };
}
