// 条件の記録（`#/asset/<id>/recipe`。P7-4）
// 設計: docs/p7-design.md §5.1〜§5.3（記録・判定・グラフ・検査・書き出し・結果と合否）/
//       §3.1〜§3.7（口）/ §4（状態）/ docs/frontend-design.md §4.7〜§4.12
//
// 約束:
// - **`GET` は 1 バイトも書かない**（画面を開くだけでは行が増えない。§0.10）
// - **記録時の理由（7 語）と書き出し時の理由（3 語）を混ぜない**（点検 A-3）。
//   記録時の理由は「その画像の条件がどれだけ揃っているか」、書き出し時の理由は
//   「その書き出しで何を変えたか」で、**別の物**（`frontend-design.md` §4.9）
// - **人が押す口だけ `POST`**（記録・検査・書き出し・紐付け・合否）。**合否は人が押す**
// - `esc()` を必ず通す（語釈や理由に `<script>` が入っても文字のまま）

const $ = (id) => document.getElementById(id);

const state = { assetId: null, record: null, exports: [], check: null, busy: false, msg: '' };

/** 記録時の理由（7 語。§0.6）。**書き出し時の 3 語はここに入れない**。 */
export const REASON_LABEL = {
  missing: '画像に条件が残っていない',
  text_not_captured: '英文が画像に残っていない',
  node_missing: '知らないノードがある',
  unresolved: '入力の値が宣言に無い',
  version_differs: '版が違う',
  hash_mismatch: 'モデルの中身が違う',
  gpu_differs: 'GPU が違う',
};

/** 書き出し時の理由（3 語。§0.6）。**記録時の 7 語と混ぜない**。 */
export const EXPORT_REASON_LABEL = {
  text_pinned: '英文を貼り付けた',
  llm_nondeterministic: '模型の出力は再現しない',
  manual_step: '手作業の工程がある',
};

/** 判定の 3 語（§0.6）。 */
export const STATUS_LABEL = { exact: '完全', approx: '近似', impossible: '再現できない' };

/** 書き出しの方式（§0.4）。 */
export const MODE_LABEL = {
  pin_text: '英文を貼り付ける',
  rerun_graph: 'グラフをそのまま回す',
  manual_text: '英文を自分で書く',
};

/** 合否（§3.6）。 */
export const VERDICT_LABEL = {
  same: '同じ', close: '近い', different: '違う', failed: '失敗',
};

export function esc(value) {
  return String(value ?? '').replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

const reasonText = (kind) => REASON_LABEL[kind] || String(kind);
const exportReasonText = (kind) => EXPORT_REASON_LABEL[kind] || String(kind);

/** 判定の 1 行（**記録時の理由だけ**を出す）。 */
export function statusHtml(record, check) {
  const status = record ? record.status : null;
  if (!status) return '<div class="rc-note">まだ記録していません。</div>';
  const cls = status === 'exact' ? 'ok' : status === 'approx' ? 'warn' : 'bad';
  const reasons = record.reasons || [];
  const why = reasons.length
    ? `<ul class="rc-reasons">${reasons.map((kind) => `<li>${esc(reasonText(kind))}</li>`).join('')}</ul>`
    : '<div class="rc-why-none">条件は揃っています。</div>';
  // **繋がらなかったときは「調べていない」と書く**（監査 A-1。`impossible` と混同させない）
  const inspected = record.inspected === false
    ? '<div class="rc-warn">ComfyUI に繋がらなかったので、ノードの宣言は調べていません。</div>' : '';
  const notes = (record.notes || []).length
    ? `<div class="rc-notes">${(record.notes || []).map((n) => esc(n)).join(' / ')}</div>` : '';
  return `<div class="rc-status"><span class="rc-badge ${cls}">${esc(STATUS_LABEL[status] || status)}</span>`
    + `${why}${inspected}${notes}</div>`;
}

/** 検査の結果（`POST …/check` の後だけ）。**印の前提**を 1 行ずつ出す。 */
export function checkHtml(check) {
  if (!check) return '';
  const marker = check.marker_ok
    ? '<span class="rc-ok">印を付けられます</span>'
    : `<span class="rc-bad">印を付けずに書き出します（${esc(check.marker_skip_reason || '前提が外れています')}）</span>`;
  const nodes = (check.save_nodes || []).length;
  const unresolved = (check.unresolved || []).length;
  return `<div class="rc-check">${marker}`
    + `<span class="stat">保存ノード ${esc(String(nodes))} 個</span>`
    + (unresolved ? `<span class="rc-warn">宣言に無い入力 ${esc(String(unresolved))} 件</span>` : '')
    + ((check.notes || []).length
      ? `<div class="rc-notes">${(check.notes || []).map((n) => esc(n)).join(' / ')}</div>` : '')
    + '</div>';
}

/** 結果 1 枚（合否のボタンつき。**上書き**）。 */
export function resultHtml(item) {
  const verdict = item.verdict
    ? `<span class="rc-verdict ${esc(item.verdict)}">${esc(VERDICT_LABEL[item.verdict] || item.verdict)}</span>`
    : '<span class="rc-none">合否はまだ</span>';
  const flags = [
    item.matched_by === 'manual' ? '手で紐付け' : '印で発見',
    item.fetched ? '取り込み' : '参照',
    item.same_hash ? '鍵が一致' : '鍵が違う',
    item.seed_changed ? 'seed が違う' : null,
  ].filter(Boolean).map((t) => `<span class="rc-flag">${esc(t)}</span>`).join('');
  const buttons = Object.entries(VERDICT_LABEL).map(([key, label]) =>
    `<button class="rc-v" data-verdict="${esc(key)}" data-result="${esc(item.id)}">${esc(label)}</button>`).join('');
  const asset = item.result_asset_id
    ? `<a class="rc-open" href="#/asset/${esc(item.result_asset_id)}">結果を開く</a>` : '';
  return `<div class="rc-result" data-result="${esc(item.id)}">`
    + `<span class="rc-seed">seed ${esc(item.seed ?? '—')}</span>${verdict}${flags}${asset}`
    + `<span class="rc-vbtns">${buttons}</span>`
    + (item.note ? `<span class="rc-note">${esc(item.note)}</span>` : '')
    + '</div>';
}

/** 書き出し 1 束（ファイルと結果）。 */
export function attemptHtml(item) {
  const files = (item.files || []).map((f) =>
    `<li>seed ${esc(f.seed ?? '—')}${f.marker ? ` <span class="rc-marker">${esc(f.marker)}</span>` : ''}</li>`).join('');
  const marker = item.marker_skip_reason
    ? `<span class="rc-bad">印なし（${esc(item.marker_skip_reason)}）</span>`
    : '<span class="rc-ok">印あり</span>';
  const results = (item.results || []).length
    ? (item.results || []).map(resultHtml).join('')
    : '<div class="rc-none">結果はまだ紐付いていません。</div>';
  return `<div class="rc-attempt"><div class="rc-head">`
    + `<span class="rc-id">${esc(item.attempt_id)}</span>`
    + `<span>${esc(MODE_LABEL[item.mode] || item.mode)}</span>${marker}`
    + `<span class="stat">${esc(String((item.files || []).length))} ファイル</span>`
    + `<span class="stat">${esc(item.created_at || '')}</span></div>`
    + `<ul class="rc-files">${files}</ul>${results}</div>`;
}

/** 検査の結果を**画面に出さずに**取り直す（`load()` の後で出す。P4-3 の監査 B-2 と同じ）。 */
async function post(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' },
    body: JSON.stringify(body || {}),
  });
  const got = await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, ...got };
}

function msg(text, bad) {
  state.msg = text || '';
  const el = $('rc-msg');
  if (el) { el.textContent = state.msg; el.classList.toggle('bad', Boolean(bad)); }
}

/** 記録・書き出しの一覧を読み直して描く（**`GET` だけ**）。 */
export async function load() {
  const id = state.assetId;
  if (!id) return;
  const res = await fetch(`/api/assets/${encodeURIComponent(id)}/recipe`);
  if (res.status === 404) {
    state.record = null;
  } else if (res.ok) {
    state.record = await res.json();
  } else {
    state.record = null;
    msg(`記録を読めません（${res.status}）`, true);
  }
  state.exports = [];
  if (state.record) {
    const ex = await fetch(`/api/recipes/${encodeURIComponent(state.record.recipe_id)}/exports`);
    if (ex.ok) state.exports = (await ex.json()).items || [];
  }
  render();
}

function render() {
  const panel = $('recipe');
  if (!panel) return;
  const record = state.record;
  const actions = record
    ? `<div class="rc-actions">`
      + `<button id="rc-check">書き出す前に調べる</button>`
      + `<label>方式 <select id="rc-mode">${Object.entries(MODE_LABEL).map(([k, v]) =>
        `<option value="${esc(k)}"${record.mode === k ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`
      + `<label>seed <input id="rc-seeds" placeholder="1, 2" size="10"></label>`
      + `<label>枚数 <input id="rc-count" type="number" min="1" max="8" value="1" size="3"></label>`
      + `<label class="rc-inline"><input id="rc-marker" type="checkbox" checked> 印を付ける</label>`
      + `<button id="rc-export">書き出す</button></div>`
      + `<div class="rc-refs"><span class="stat">鍵 ${esc((record.recipe_hash || '').slice(0, 16))}…</span>`
      + (record.graph_path
        ? `<a class="rc-open" href="/api/assets/${esc(state.assetId)}/graph?format=api" target="_blank">グラフを見る</a>`
        : '<span class="rc-warn">グラフが残っていません</span>')
      + `<span class="stat">出所 ${esc(record.graph_source || '—')}</span></div>`
    : `<div class="rc-actions"><label>方式 <select id="rc-mode">${Object.entries(MODE_LABEL).map(([k, v]) =>
      `<option value="${esc(k)}">${esc(v)}</option>`).join('')}</select></label>`
      + `<button id="rc-record">記録する</button></div>`;
  const exports = state.exports.length
    ? state.exports.map(attemptHtml).join('')
    : (record ? '<div class="rc-none">まだ書き出していません。</div>' : '');
  const attach = record
    ? `<div class="rc-attach"><input id="rc-attach-id" placeholder="結果の画像の id" size="28">`
      + `<input id="rc-attach-attempt" placeholder="書き出しの id" size="12">`
      + `<button id="rc-attach">紐付ける</button></div>` : '';
  panel.innerHTML = `<div class="topbar">`
    + `<a class="back" href="#/asset/${esc(state.assetId)}">← 拡大</a>`
    + `<span class="name">条件の記録</span>`
    + `<span class="stat" id="rc-msg">${esc(state.msg)}</span>`
    + `<span class="spacer"></span><a class="back" href="#/recipes">記録の一覧へ</a></div>`
    + `<div class="rc-body">${statusHtml(record, state.check)}${actions}`
    + `${checkHtml(state.check)}<div class="rc-exports">${exports}</div>${attach}</div>`
    + `<div class="rc-help">`
    + `「記録する」は<b>画像に残っている条件</b>を読んで、再現できるかどうかを判定します。`
    + `書き出すと、印つきのグラフが <b>ComfyUI に読み込める形</b>で保存されます。`
    + `結果の画像は印から自動で紐付き、<b>合否は人が押して</b>残します。`
    + '</div>';
}

export async function showRecipe(assetId) {
  state.assetId = assetId;
  state.check = null;
  state.msg = '';
  document.body.classList.add('recipe');
  await load();
}

export function hideRecipe() {
  document.body.classList.remove('recipe');
}

/** 拡大の画面に出す入口（1 行。`app.js` の来歴の近く）。 */
export function recipeLinkHtml(assetId, record) {
  const label = record ? `条件の記録（${esc(STATUS_LABEL[record.status] || record.status)}）` : '条件の記録';
  return `<a class="rc-link" href="#/asset/${esc(assetId)}/recipe">${label}</a>`;
}

export function wireRecipe() {
  const panel = $('recipe');
  if (!panel) return;
  panel.addEventListener('click', async (event) => {
    const id = state.record ? state.record.recipe_id : null;
    if (event.target.id === 'rc-record') {
      event.preventDefault();
      msg('記録しています…');
      const got = await post(`/api/assets/${encodeURIComponent(state.assetId)}/recipe`,
                             { mode: $('rc-mode')?.value || 'pin_text' });
      await load();                                   // **先に描き直してから知らせる**（B-2 と同じ）
      msg(got.ok ? `記録しました（${STATUS_LABEL[got.status] || got.status}）。`
        : `記録できません（${got.detail || got.status}）`, !got.ok);
      return;
    }
    if (event.target.id === 'rc-check' && id) {
      event.preventDefault();
      const got = await post(`/api/recipes/${encodeURIComponent(id)}/check`);
      state.check = got.ok ? got : null;
      render();
      msg(got.ok ? '調べました。' : `調べられません（${got.detail || got.status}）`, !got.ok);
      return;
    }
    if (event.target.id === 'rc-export' && id) {
      event.preventDefault();
      const seeds = ($('rc-seeds')?.value || '').split(',').map((s) => s.trim()).filter(Boolean);
      const got = await post(`/api/recipes/${encodeURIComponent(id)}/export`, {
        mode: $('rc-mode')?.value || undefined,
        seeds: seeds.length ? seeds : undefined,
        count: Number($('rc-count')?.value || 0) || undefined,
        marker: Boolean($('rc-marker')?.checked),
      });
      await load();
      msg(got.ok ? `書き出しました（${(got.files || []).length} ファイル）。`
        : `書き出せません（${got.detail || got.status}）`, !got.ok);
      return;
    }
    const verdict = event.target.dataset ? event.target.dataset.verdict : null;
    if (verdict && id) {
      event.preventDefault();
      const attempt = event.target.closest('.rc-attempt')?.querySelector('.rc-id')?.textContent || '';
      const got = await post(
        `/api/recipes/${encodeURIComponent(id)}/exports/${encodeURIComponent(attempt)}`
        + `/results/${encodeURIComponent(event.target.dataset.result)}/verdict`, { verdict });
      await load();
      msg(got.ok ? '合否を記録しました。' : `記録できません（${got.detail || got.status}）`, !got.ok);
      return;
    }
    if (event.target.id === 'rc-attach' && id) {
      event.preventDefault();
      const got = await post(
        `/api/recipes/${encodeURIComponent(id)}/exports/`
        + `${encodeURIComponent(($('rc-attach-attempt')?.value || '').trim())}/results`,
        { result_asset_id: ($('rc-attach-id')?.value || '').trim() });
      await load();
      msg(got.ok ? '紐付けました。' : `紐付けられません（${got.detail || got.status}）`, !got.ok);
    }
  });
}
