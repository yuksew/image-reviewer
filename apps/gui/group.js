// まとまりレビュー（`#/group/<id>`。P6-1b の最小形）
// 設計: docs/p6-design.md §5.1b（**P5 には無かった画面**。合格の線 2 の「開いて決める」の行き先）、
//       docs/frontend-design.md §2.4「まとまりレビュー（決定の画面）」の図・§4.1（フレーム）・§6（文言）
//
// 約束:
// - **最小形**。フィルムストリップ＋選択中の 1 枚＋理由＋「この 1 枚に決める」「全部ボツ」
//   「あとで」「選んだ 1 枚を拡大で開く」。比較・絞り込み・タグは足さない（次の段）
// - **注記の入口をここに置く**（点検 C5。前回の点検 C13 の未解決点）:
//   「選んだ 1 枚を拡大で開く」で `#/asset/<id>` へ移る。**印を付けてから決める**のが本筋
// - **マウスだけで完結**（キーは補助）。判断は `POST /api/groups/{id}/decide`（P5 で実装済み）
// - 判断は**人だけ**（`X-Image-Reviewer-Actor: human`。エージェントは 403。`design.md` §9.5）
// - 語は「**あとで**」（「保留」は使わない）。判断の取り消しは「**判断を消す**」（点検 C6）
// - 要求から来ていないまとまり（`kind='manual'`）でも同じ画面を使う（要求専用にしない）
// - **（P8-3 の監査 C-1）削除の入口を足した**: 「選んだ 1 枚を削除へ回す」で
//   `#/pending-deletes?ids=<1 枚>` へ**渡すだけ**（段の選択と確認はあちら。ここでは消さない）

const GROUPS = '/api/groups';
// **削除へ回す行き先は 1 か所で組む**（`pending.js`。監査 C-1）
import { toDelete } from './pending.js';
// ボツの理由（枚ごとに必須）と**キープの理由**（任意）。分ける理由は P6-1b の監査 B1:
// `decide` は「1 枚に決めたときは**その枚のキープ理由**をまとまりの理由として写す」ので、
// キープの理由を集めないと要求の `response.reason_code_id` が常に null になる
// （エージェントが `wants: ["reason"]` と求めても答えられない）
const REJECT_REASONS = '/api/reason-codes?applies_to=reject';
const KEEP_REASONS = '/api/reason-codes?applies_to=keep';

const $ = (id) => document.getElementById(id);

// 決定の語（画面は日本語。`selected` / `all_rejected` をそのまま出さない。監査 C5）
const DECISION_LABEL = { selected: '1 枚に決めた', all_rejected: '全部ボツ' };

const state = {
  group: null,
  items: [],
  selected: null,
  reasonId: '',
  keepReasonId: '',
  reasons: [],
  keepReasons: [],
  request: null,      // このまとまりを対象にした open な要求（あれば）
  prov: {},           // asset_id -> 来歴の 1 行（選択中の 1 枚だけ引く。監査 C3）
  provPending: new Set(),
  provFetched: new Set(),
  busy: false,
  error: null,
  note: null,         // 判断の後に出す 1 行
};

let wired = false;

function esc(value) {
  return String(value ?? '').replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

export function itemLabel(row, index) {
  const at = (row.position ?? index) + 1;
  const word = { kept: 'キープ', rejected: 'ボツ' }[row.review_state] || '未判断';
  const reason = row.reason_label ? `（${row.reason_label}）` : '';
  return `${at} 番 ・ ${word}${reason}`;
}

function render() {
  const group = state.group;
  const strip = $('group-strip');
  const stage = $('group-stage');
  if (!group) return;
  $('group-title').textContent = group.title || 'まとまり';
  const ai = state.request && state.request.ai && state.request.ai.pick_asset_id
    ? state.request.ai.pick_asset_id : null;
  const aiIndex = ai ? state.items.findIndex((row) => row.asset_id === ai) + 1 : 0;
  $('group-brief').textContent = [
    `${state.items.length} 枚`,
    group.policy === 'pick_one' ? '1 枚選ぶ' : group.policy === 'all_reject_only' ? 'ボツのみ' : '複数選べる（P6 の画面は 1 枚）',
    group.state === 'decided'
      ? `決定済み（${DECISION_LABEL[group.decision] || group.decision || ''}）`   // 監査 C5: 日本語
      : '未決定',
    state.request ? 'エージェントの要求' : null,
    aiIndex ? `AI の推し: ${aiIndex} 番` : null,
  ].filter(Boolean).join(' ・ ');

  // フィルムストリップ（隙間なく接する。選択中だけ `--accent` の上辺）
  if (strip) {
    strip.innerHTML = '';
    state.items.forEach((row, index) => {
      const frame = document.createElement('div');
      frame.className = 'grp-frame' + (row.asset_id === state.selected ? ' selected' : '')
        + (row.asset_id === ai ? ' ai-pick' : '')
        + (row.review_state === 'kept' ? ' kept' : row.review_state === 'rejected' ? ' rejected' : '');
      frame.dataset.asset = row.asset_id;
      frame.title = itemLabel(row, index);
      frame.innerHTML = `<div class="no">${index + 1}</div>`
        + `<img loading="lazy" decoding="async" src="/api/assets/${esc(row.asset_id)}/thumb?size=256" alt="">`;
      frame.addEventListener('click', () => {
        state.selected = row.asset_id;
        render();
      });
      strip.appendChild(frame);
    });
  }

  // 選択中の 1 枚（選ばれていなければ先頭）
  const chosen = state.selected || (state.items[0] || {}).asset_id || null;
  state.selected = chosen;
  const row = state.items.find((entry) => entry.asset_id === chosen) || null;
  if (stage) {
    const prov = chosen ? (state.prov[chosen] || '') : '';
    stage.innerHTML = chosen
      ? `<img src="/api/assets/${esc(chosen)}/thumb?size=1024" alt="">`
        + `<div class="grp-cap">${esc(row ? itemLabel(row, state.items.indexOf(row)) : '')}`
        + (prov ? `<span class="grp-prov">${esc(prov)}</span>` : '') + '</div>'
      : '<div class="grp-note">このまとまりには画像がありません。</div>';
  }
  if (chosen) fillProv(chosen);      // 選択中の 1 枚の来歴（監査 C3。1 枚につき 1 回だけ引く）

  // 理由（ボツは必須・キープは任意。監査 B1）
  const reason = $('group-reason');
  if (reason) {
    reason.innerHTML = '<option value="">理由を選ぶ</option>'
      + state.reasons.map((r) => `<option value="${esc(r.id)}"${r.id === state.reasonId ? ' selected' : ''}>${esc(r.label)}</option>`).join('');
  }
  const keepReason = $('group-keep-reason');
  if (keepReason) {
    keepReason.innerHTML = '<option value="">選ばない</option>'
      + state.keepReasons.map((r) => `<option value="${esc(r.id)}"${r.id === state.keepReasonId ? ' selected' : ''}>${esc(r.label)}</option>`).join('');
  }

  // `all_reject_only` のまとまりでは「この 1 枚に決める」を出さない（監査 C6。
  // 押すと API が 422 を返し、その文言がそのまま画面に出てしまう）
  const canKeep = group.policy !== 'all_reject_only';
  const canDecide = group.state !== 'decided' && !!chosen && !state.busy && canKeep;
  const decide = $('group-decide');
  if (decide) {
    decide.disabled = !canDecide;
    decide.textContent = 'この 1 枚に決める';
    decide.title = canKeep ? '' : 'このまとまりは「ボツのみ」なので、1 枚に決められません';
  }
  const allReject = $('group-allreject');
  if (allReject) allReject.disabled = group.state === 'decided' || !state.items.length || state.busy;
  const zoom = $('group-zoom');
  if (zoom) zoom.disabled = !chosen;
  // P8-3: **まとまりからの削除の入口**（監査 C-1。`frontend-design.md` §11）。
  // フィルムストリップで選んでいる 1 枚を削除の確認へ渡す（**ここでは消さない**）
  const del = $('group-delete');
  if (del) {
    del.disabled = !chosen;
    del.textContent = '選んだ 1 枚を削除へ回す';
  }
  const note = $('group-note');
  if (note) {
    note.textContent = state.error ? `まとまりを読めません: ${state.error}` : (state.note || '');
    note.hidden = !note.textContent;
  }
}

async function load() {
  state.busy = true;
  state.error = null;
  try {
    const res = await fetch(`${GROUPS}/${encodeURIComponent(state.groupId)}`);
    if (!res.ok) throw new Error(`${res.status}`);
    state.group = await res.json();
    state.items = state.group.items || [];
    if (!state.selected || !state.items.some((row) => row.asset_id === state.selected)) {
      state.selected = (state.group.selected_asset_ids || [])[0] || (state.items[0] || {}).asset_id || null;
    }
  } catch (error) {
    state.group = null;
    state.items = [];
    state.error = error.message;
  }
  try {
    const res = await fetch(REJECT_REASONS);
    if (res.ok) state.reasons = (await res.json()).items || [];
  } catch (error) {
    state.reasons = [];
  }
  try {
    const res = await fetch(KEEP_REASONS);
    if (res.ok) state.keepReasons = (await res.json()).items || [];
  } catch (error) {
    state.keepReasons = [];
  }
  try {
    // **まとまりで絞る**（監査 C2。`?group_id=` は P6-1a の監査で足した口）。
    // 以前は `state=open&limit=200` を取って突き合わせていたので、201 件目以降の
    // まとまりでは「エージェントの要求」の見出しが出なかった
    const res = await fetch(`/api/review-requests?group_id=${encodeURIComponent(state.groupId)}&state=open&limit=1`);
    if (res.ok) {
      const body = await res.json();
      state.request = (body.items || [])[0] || null;
    }
  } catch (error) {
    state.request = null;
  }
  state.busy = false;
  render();
}

// 選択中の 1 枚の来歴を 1 行だけ引く（`compare.js` のキャプションと同じ作り。監査 C3）。
// **1 枚につき 1 回だけ**引く（`provFetched` で覚える。引けた結果が空文字でも「引いた」と
// 数える——空文字を偽として数えると、描き直すたびに引き直して**無限に描き直す**）
async function fillProv(assetId) {
  if (state.provFetched.has(assetId) || state.provPending.has(assetId)) return;
  state.provPending.add(assetId);
  try {
    const res = await fetch(`/api/assets/${encodeURIComponent(assetId)}`);
    if (!res.ok) throw new Error(`${res.status}`);
    const asset = await res.json();
    const meta = asset.meta || {};
    state.prov[assetId] = [
      meta.model ? String(meta.model).replace(/\.safetensors$/, '').slice(0, 24) : null,
      meta.seed != null ? `seed ${meta.seed}` : null,
      meta.steps != null ? `steps ${meta.steps}` : null,
      meta.cfg != null ? `cfg ${meta.cfg}` : null,
    ].filter(Boolean).join(' · ');
  } catch (error) {
    state.prov[assetId] = '';      // 引けなくても画面は出す（1 行が出ないだけ）
  } finally {
    state.provPending.delete(assetId);
    state.provFetched.add(assetId);
    render();
  }
}

// 判断を送る（`POST /api/groups/{id}/decide`。P5 の口。§5.1b）
async function decide(items, groupReasonId) {
  if (state.busy) return;
  state.busy = true;
  state.note = null;
  state.error = null;
  render();
  try {
    const res = await fetch(`${GROUPS}/${encodeURIComponent(state.groupId)}/decide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' },
      body: JSON.stringify({ items, group_reason_code_id: groupReasonId || null }),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.detail || `${res.status}`);
    const closed = body.closed_request_ids || [];
    const kept = (body.group && body.group.selected_asset_ids) || [];
    const at = kept.length ? state.items.findIndex((row) => row.asset_id === kept[0]) + 1 : 0;
    state.note = closed.length
      ? `要求を閉じました${at ? `（${at} 番に決めました）` : ''}。エージェントがここを読みます。`
      : `記録しました${at ? `（${at} 番に決めました）` : ''}。`;
    await load();
    state.note = closed.length
      ? `要求を閉じました${at ? `（${at} 番に決めました）` : ''}。エージェントがここを読みます。`
      : `記録しました${at ? `（${at} 番に決めました）` : ''}。`;
  } catch (error) {
    state.error = error.message;
  } finally {
    state.busy = false;
    render();
  }
}

// 「この 1 枚に決める」: 選んだ 1 枚を keep（**キープの理由は任意**。監査 B1）、
// 残りを reject（**理由が要る**）。`keepReasonId` を keep に入れると、P5 の `decide` が
// それをまとまりの理由として写すので、要求の `response.reason_code_id` が埋まる
export function decideOnePayload(items, selected, reasonId, keepReasonId = '') {
  return items.map((row) => (row.asset_id === selected
    ? { asset_id: row.asset_id, verdict: 'keep', reason_code_id: keepReasonId || null }
    : { asset_id: row.asset_id, verdict: 'reject', reason_code_id: reasonId || null }));
}

// 「全部ボツ」: 全枚 reject＋まとまりの理由
export function allRejectPayload(items, reasonId) {
  return items.map((row) => ({ asset_id: row.asset_id, verdict: 'reject', reason_code_id: reasonId || null }));
}

export async function showGroup(groupId) {
  state.groupId = groupId;
  state.selected = null;
  state.note = null;
  document.body.classList.add('grouping');
  await load();
}

export function hideGroup() {
  document.body.classList.remove('grouping');
  state.group = null;
  state.items = [];
  state.note = null;
  state.error = null;
}

export function wireGroup() {
  if (wired) return;
  wired = true;
  const reason = $('group-reason');
  if (reason) {
    reason.addEventListener('change', () => {
      state.reasonId = reason.value || '';
      render();
    });
  }
  const keepReason = $('group-keep-reason');
  if (keepReason) {
    keepReason.addEventListener('change', () => {
      state.keepReasonId = keepReason.value || '';
      render();
    });
  }
  // **変数名に注意**: `decide` は上の関数。ボタンの変数を `decide` にすると関数を隠して
  // `decide is not a function` になる（実機で踏んだ）
  const decideBtn = $('group-decide');
  if (decideBtn) {
    decideBtn.addEventListener('click', () => {
      if (!state.selected) return;
      if (!state.reasonId && state.items.length > 1) {
        state.note = '理由を選んでください（ボツにする枚に理由が要ります）。';
        render();
        return;
      }
      decide(state.items.length === 1
        ? [{ asset_id: state.selected, verdict: 'keep', reason_code_id: state.keepReasonId || null }]
        : decideOnePayload(state.items, state.selected, state.reasonId, state.keepReasonId), null);
    });
  }
  const allReject = $('group-allreject');
  if (allReject) {
    allReject.addEventListener('click', () => {
      if (!state.reasonId) {
        state.note = '全部ボツには理由が要ります。理由を選んでください。';
        render();
        return;
      }
      decide(allRejectPayload(state.items, state.reasonId), state.reasonId);
    });
  }
  const later = $('group-later');
  if (later) {
    // 「あとで」は何も書かない（点検 C6。まとまりレビューでも同じ語）
    later.addEventListener('click', () => { location.hash = '#/requests'; });
  }
  const zoom = $('group-zoom');
  if (zoom) {
    zoom.addEventListener('click', () => {
      // **まとまりを引き継ぐ**（P6-2 の実装者が見つけた穴）: 拡大で付けた注記に
      // `group_id` が入らないと、要求の `response.annotations`（`group_id` 一致で導出）に
      // 出てこない。`annotations.js` が本文に入れる
      if (state.selected) {
        location.hash = `#/asset/${state.selected}?group=${encodeURIComponent(state.groupId)}`;
      }
    });
  }
  // P8-3: 削除の入口（**渡すだけ**。`#/pending-deletes` で段を選ぶ。監査 C-1）
  const del = $('group-delete');
  if (del) {
    del.addEventListener('click', () => {
      if (state.selected) toDelete([state.selected]);
    });
  }
}
