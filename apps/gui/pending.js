// 最近の削除（`#/pending-deletes`。P8-3）
// 設計: docs/p8-design.md §5（画面）・§3.2〜§3.4（使う口）・§4.1 / §4.3（状態）・§0.14 の Q2・Q7・Q8、
//       docs/frontend-design.md §4.6（常設）・§6（文言）・§11（細部）
//
// 約束:
// - **`GET` は書かない**（残り時間も減らさない。減らすのはサーバのタイマー）
// - 残り時間の**見た目**だけを毎秒書き換える（`あと 3:12`）
// - **人は誰の削除でも戻せる**（§0.14 の e-2）。エージェントは自分の分だけ（押せない）
// - **（P8-3 の監査 C-2）段 1〜3 の全部を出す**（`frontend-design.md` §4.6 の
//   「1 行 = `deletion_log` の 1 行」）。段 1・2 のボタンは「戻す」、段 3 の窓は「取り消す」
// - **（P8-3 の監査 C-3）失敗の道でも `load()` する**（409 の直後に「別名で戻す」を出す）
// - **（P8-3 の監査 G-3）戻せなかった理由は `stuck_reason` で 4 通り**に分ける
// - **（P8-3 の監査 G-4）固定の名前・数を文言に埋め込まない**（フォルダは `/api/roots` から組む）
// - **（P8-5・Q8）許可の無いフォルダでは段 3 のラジオを出さない**（`root.allow_stage3`）
//   **（P8-5 の監査 D-5）一覧の上限（2000 枚）を超えるフォルダでは、選んだ枚が一覧に無い**ので、
//   その枚だけ `GET /api/assets/<id>` で引く（**足りない枚の数だけ**）
// - **（P8-5）走査中は「走査中です。終わるまで削除と取り消しは待ちます。」を 1 行**出す
// - 「いま消す」「別名で戻す」「アプリのゴミ箱から戻す」は**人だけ**の口（押す前に確認を 1 回挟む）
// - 拾い物（`found`）は**消さない**（人が決める）
// - `esc()` を必ず通す
// - **（C-2・C-3・C-5・C-6・D-5・D-7）** 画面の語は `design.md` §17 の「画面の語」の列に従う
//   （「いま取る」を案内しない・小見出しは実態に合わせる・「実体」→「ファイル」・「保留」→「一時置き場」）

const PENDING = '/api/pending-deletes';
const TRASH = '/api/trash';
const ROOTS = '/api/roots';
const SCAN = '/api/scan';
const ASSETS = '/api/assets?limit=2000&sort=path';   // 一覧（上限 2000 枚。足りない分は 1 枚の口）
const PREVIEW = '/api/locations/bulk-delete/preview';
const BULK = '/api/locations/bulk-delete';

// **（P10。利用者の要望）後から段 2 へ進める・実体が無い行を片付ける**。
// 記録: `docs/deletions-advance.md`。**どちらも人だけの口**（エージェントは 403）。
const ADVANCE_MANY = '/api/deletions/advance';
const CLOSE_MANY = '/api/deletions/close';
export const advanceOneUrl = (id) => `/api/deletions/${encodeURIComponent(id)}/advance`;
export const closeOneUrl = (id) => `/api/deletions/${encodeURIComponent(id)}/close`;
/** **1 回の上限**（サーバと同じ規則。`deletions.py` の `MAX_BATCH_PER_CALL`）。超える分は分けて送る。 */
export const BATCH_MAX = 200;

// **（ワーディング監査 W-20。D-5）** 段 3 は「ファイルを消す」で通す（「完全に消す」「実体を消す」と呼ばない。
// `frontend-design.md` §6 の「削除の確認: 段」・§17 の画面の語）
// **（ワーディングの修正 2）段の名前は 1 つ**にし、**実行のボタンと結果の 1 行は選んだ段の名前を
// そのまま動詞にする**（`frontend-design.md` §6.1 の規則 3）。前は段 1 を選んでいても
// 「N 枚を消す用意をする」と出て、**押す前に何が起きるか分からなかった**（`docs/wording-fix-2.md`）
export const STAGE_LABEL = { 1: 'カタログから外す', 2: 'アプリのゴミ箱へ移す', 3: 'ファイルを消す' };

/** **実行のボタン**の語（**選んだ段の名前をそのまま動詞にする**。§6.1 の規則 3）。
 *
 * 「用意する」のような曖昧な語を使わない（段 1 を選んでいても「消す用意」と出ていた）。
 * 段が読めないときは段 1 の文にする（**いきなり消す側に倒さない**）。
 */
export function execLabel(count, stage) {
  const n = Number(count) || 0;
  const s = Number(stage);
  if (s === 2) return `${n} 枚をアプリのゴミ箱へ移す`;
  if (s === 3) return `${n} 枚のファイルを消す`;
  return `${n} 枚をカタログから外す`;
}

/** 押した後の 1 行（**同じ段の動詞の過去形**＋取り消しの案内。§6.1 の規則 3）。
 *
 * **段 1・2 は窓が無い**ので「あと M:SS」を出さない（「いつでも戻せます」。§4.6）。
 * 前に「あと 4:58 は取り消せます」を段 1・2 にも出していた（窓が無いので嘘になる）。
 */
export function doneText(count, stage, remainSec) {
  const n = Number(count) || 0;
  const s = Number(stage);
  if (s === 2) return `${n} 枚をアプリのゴミ箱へ移しました。いつでも戻せます。`;
  if (s === 3) return `${n} 枚のファイルを消しました。あと ${fmtRemain(remainSec)} は取り消せます。`;
  return `${n} 枚をカタログから外しました。いつでも戻せます。`;
}

export const STATE_LABEL = {
  hidden: 'カタログから外しました', trashed: 'アプリのゴミ箱にあります', pending: '取り消せます',
  stuck: '戻せませんでした', purged: 'ファイルを消しました', restored: '戻しました',
  // **（P10）** 片付けた行（`closed_at`）。「最近の削除」からは外れ、台帳にだけ残る
  closed: '片付けました',
};

// ---- 後から段 2 へ進める・実体が無い行を片付ける（P10。利用者の要望）----

/** 段 1 の行を後から段 2 へ進めるボタン（**段の名前をそのまま動詞にする**。§6.1 の規約 3）。 */
export const ADVANCE_LABEL = 'アプリのゴミ箱へ移す';
/** 実体が無い行を終わりにするボタン（**ファイルは 1 つも消さない**）。
 *
 * **「実体」ではなく「ファイル」**（§6.1 の規約 4 が「実体」を禁じている。利用者の言い方は
 * 「実体が無いので片付ける」だが、画面の語は規則に合わせる。記録の「決めた点」を見よ）。
 */
export const CLOSE_LABEL = 'ファイルが無いので片付ける';

/** 押した後の 1 行（**段ごと・実際に起きたこと**。§6.1 の規約 3）。 */
export function advanceDoneText(count) {
  return `${Number(count || 0).toLocaleString('ja-JP')} 件をアプリのゴミ箱へ移しました。`;
}

/** **（D-1）既に片付いていた数を分けて言う**（`replayed_count`。監査 D-1）。
 *
 * まとめての再送では、既に片付けた行も**成功として数える**（200 で返る）。それを
 * 「片付けました」とだけ言うと、**実際には何も起きていないのに N 件片付けたように見える**。
 */
export function closeDoneText(count, replayed = 0) {
  const n = Number(count || 0);
  const again = Number(replayed || 0);
  return `${n.toLocaleString('ja-JP')} 件を片付けました。`
    + (again > 0 ? `${again.toLocaleString('ja-JP')} 件は既に片付けていました。` : '');
}

/** **片付けの確認**（戻せない操作なので 1 回挟む。§6.1 の規約 3）。
 *
 * **「ファイルは消しません」を必ず書く**（「片付ける」がファイルを消すと読めないように）。
 */
export function closeConfirmText(count) {
  const n = Number(count) || 0;
  return (n > 1 ? `選んだ ${n} 件をまとめて片付けます。` : 'この行を終わりにします。')
    + 'ファイルは消しません。元に戻せません。';
}

/** 断られた理由の語（口の `code` → 画面の語。**英語の内部値を出さない**。§6.1 の規約 4）。 */
export const SKIP_TEXT = {
  missing_file: 'ファイルがありません',
  file_found: 'ファイルがまだあります',
  already_stage2: '既にアプリのゴミ箱にあります',
  already_stage3: '既にファイルを消しています',
  already_closed: '既に片付けています',
  already_restored: '既に戻しています',
  changed: '中身が変わっています',
  // **（P11 の監査 A-1）** OS が移動を断った（`move_failed`）。**段 2 の結果にもまとめてにも出る**。
  // 前は理由を見ずに「中身が変わっていたので消しませんでした」と固定で書いていた（嘘の理由）。
  move_failed: '移動できませんでした',
  // **（P10 の監査 A-1）** 消した画像はもうその場所に無く、**別の画像**が登録されている
  // （台帳の枚・大きさと合わない）。**そのまま「片付ける」へ案内する**（本文が案内する）
  different_file: '別の画像があります',
  not_registered: '登録がありません',
  refused: '見つかりません',
  failed: 'うまくいきませんでした',
};

export function skipText(reason) {
  return SKIP_TEXT[reason] || 'できませんでした';
}

/** **断られた数を、その操作の動詞で言う**（§6.1 の規約 3。段 2 は「移し」・段 3 は「消し」）。
 *
 * **（P11 の監査 A-1）** 前は段 2 の結果だけ「中身が変わっていたので**消し**ませんでした」と
 * **理由も動詞も固定**だった。**理由は API が返した `skipped[].reason` から**作る。
 */
export const SKIP_VERB = { move: '移し', advance: '移し', delete: '消し', close: '片付け' };

/** 断られた数と理由（**数を黙って捨てない**。理由は 2 つまで出し、残りは「ほか」）。 */
export function skippedText(kind, skipped) {
  const list = skipped || [];
  if (!list.length) return '';
  const seen = [...new Set(list.map((s) => skipText(s.reason)))];
  const why = (seen.length > 2 ? seen.slice(0, 2).concat('ほか') : seen).join('、');
  const verb = SKIP_VERB[kind] || SKIP_VERB.close;
  return `${list.length.toLocaleString('ja-JP')} 件は${verb}ませんでした（${why}）。`;
}

/** **次に何をすればよいか**（API が返した `skipped[].message` を**そのまま**出す。P11 の監査 A-1）。
 *
 * `move_failed` の文は「エクスプローラーで消してから「ファイルが無いので片付ける」を押してください」
 * まで含む（利用者の次の一手）。**理由の語だけでは何もできない**ので、**1 件目**の本文を続けて出す
 * （同じ文が並ぶので、数は `skippedText` が言う）。
 */
export function moveFailedText(skipped) {
  const hit = (skipped || []).find((s) => s.reason === 'move_failed' && s.message);
  return hit ? String(hit.message) : '';
}

/** まとめてのボタンの語（**枚はその操作が効く行で数える**。0 のときは枚数を書かない）。 */
export function bulkLabel(kind, count) {
  const n = Number(count) || 0;
  const what = kind === 'advance' ? 'アプリのゴミ箱へ移す' : '片付ける';
  return n > 0 ? `選んだ ${n.toLocaleString('ja-JP')} 件をまとめて${what}` : `選んだ行をまとめて${what}`;
}

const $ = (id) => document.getElementById(id);

function human() {
  return { 'Content-Type': 'application/json', 'X-Image-Reviewer-Actor': 'human' };
}

/** **読むときも人だと名乗る**（`undoable` / `mine` は「誰が読んだか」で決まる）。
 *
 * `actor_of()` は**ヘッダが無ければ `agent`** を返す（`api/__init__.py`）ので、名乗らないと
 * **人が消した物でも `undoable: false`** が返り、画面が「取り消す」を隠してしまう
 * （画面の写真で見つけた。**P8-3 の実装で見つけた穴**）。
 */
function asHuman() {
  return { 'X-Image-Reviewer-Actor': 'human' };
}

export function esc(value) {
  return String(value ?? '').replace(/[&<>"]/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

export function fmtBytes(n) {
  if (n == null) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** `あと 3:12`（**分:秒**。`frontend-design.md` §4.6）。負は 0 に丸める。 */
export function fmtRemain(sec) {
  const s = Math.max(0, Math.round(Number(sec) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** 1 秒ぶん減らす（**見た目だけ**。サーバは触らない）。 */
export function stepRemain(items) {
  for (const item of items || []) {
    if (item.remaining_sec != null) item.remaining_sec = Math.max(0, item.remaining_sec - 1);
  }
  return items;
}

export function fmtDay(iso) {
  return iso ? String(iso).slice(0, 10) : '—';
}

/** `2026-10-18T03:15:00Z` → `2026-10-18 12:15`（**現地の時刻**。台帳は UTC で持っている）。 */
export function fmtWhen(iso) {
  if (!iso) return '—';
  const got = new Date(iso);
  if (Number.isNaN(got.getTime())) return String(iso).replace('T', ' ').replace('Z', '');
  const two = (n) => String(n).padStart(2, '0');
  return `${got.getFullYear()}-${two(got.getMonth() + 1)}-${two(got.getDate())}`
    + ` ${two(got.getHours())}:${two(got.getMinutes())}`;
}

/** `#/pending-deletes?ids=a,b` を読む（削除の確認へ渡された枚）。 */
export function idsOf(search) {
  const params = new URLSearchParams(search || '');
  return (params.get('ids') || '').split(',').map((s) => s.trim()).filter(Boolean);
}

/** 誰が消したか（**色ではなく語で**。Q2 の帰結 b）。 */
export function actorText(actor) {
  return actor === 'agent' ? 'エージェント' : '人';
}

/** **戻せなかった理由**（`stuck_reason`。監査 G-3）。**理由ごとに 1 行**を出す。
 *
 * 以前は 1 通りしか無く、**元の場所が埋まっているだけ**（`target_exists`）でも
 * 「保留していたファイルが見つかりません」と出ていた（利用者が次の手を選べない）。
 * 理由を残していない古い行（`null`）は `missing` と同じ文言にする（画面を空にしない）。
 * **（D-7）** 「保留」ではなく「一時置き場」。
 */
export const STUCK_TEXT = {
  target_exists: '元の場所に既にファイルがあります。',
  move_failed: '元の場所へ移せませんでした。',
  different: '元の場所には別のファイルがあります。',
  missing: '一時置き場に移したファイルが見つかりません。',
};

export function stuckText(reason) {
  return STUCK_TEXT[reason] || STUCK_TEXT.missing;
}

/** `#/pending-deletes?ids=a,b`（**削除の確認へ渡す**行き先）。**消さない**（渡すだけ。§11）。
 *
 * 重複の画面・拡大・下部バー・まとまりレビューの**4 つの入口が同じ 1 か所**を使う
 * （監査 C-1。行き先の組み立てが散ると、片方だけ直して食い違う）。
 */
export function deleteHref(ids) {
  const list = (ids || []).map((s) => String(s || '').trim()).filter(Boolean);
  return list.length ? `#/pending-deletes?ids=${list.map(encodeURIComponent).join(',')}` : '';
}

/** 削除の確認へ渡す（押されたとき）。行き先を返す（検査しやすい形にする）。 */
export function toDelete(ids) {
  const href = deleteHref(ids);
  if (href) location.hash = href;
  return href;
}

/** 下部バーの入口の文言（**選んだ枚を出す**。`frontend-design.md` §6）。
 *
 * **（C-5・G-9）** 「削除へ回す」ではなく「削除する…」（「…」は確認が続くことを示す）。
 * **（C-22）** 0 枚のときは枚数を書かない（押せないボタンに「0 枚」と言わせない）。
 */
export function deleteEntryLabel(count) {
  const n = Number(count) || 0;
  return n > 0 ? `選んだ ${n} 枚を削除する…` : '選んだ画像を削除する…';
}

/** 下部バーの入口を描き直す（押せるのは 1 枚以上のときだけ）。`app.js` の `renderPickBar()` から。 */
export function renderDeleteEntry(button, count) {
  if (!button) return;
  const n = Number(count) || 0;
  button.textContent = deleteEntryLabel(n);
  button.disabled = n < 1;
}

/** 下部バーの入口を配線する（**押すと `#/pending-deletes?ids=` へ**。`app.js` から呼ぶ）。 */
export function wireDeleteEntry(button, idsFn) {
  if (!button) return;
  button.addEventListener('click', () => {
    const ids = (typeof idsFn === 'function' ? idsFn() : idsFn) || [];
    toDelete(ids);
  });
}

/** `p` が `root` の下か（`store.is_under` と同じ見方。**大小と区切りを揃えてから比べる**）。 */
export function underPath(p, root) {
  if (!p || !root) return false;
  const norm = (v) => String(v).replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase();
  const a = norm(p);
  const b = norm(root);
  return a === b || a.startsWith(`${b}\\`);
}

/** 段 3 の前置き（Q8）。**実際のフォルダから組む**（監査 G-4。固定のツール名を埋め込まない）。
 *
 * `root.allow_stage3` の**許可が無いフォルダ**のときだけ出す（許可があるなら何も言わない）。
 * `GET /api/roots` が無いサーバでも画面を止めない（`state.roots` が空なら出さない）。
 * **（D-5・D-6）** 「置き場」ではなく「フォルダ」、「実体」ではなく「ファイル」。
 */
export function stage3NoticeHtml(preview, roots) {
  if (!preview || Number(preview.stage) !== 3) return '';
  const paths = (preview.items || []).map((it) => it.display_path || it.path).filter(Boolean);
  const noMark = (roots || []).filter((r) => !r.allow_stage3
    && paths.some((p) => underPath(p, r.display_path)));
  if (!noMark.length) return '';
  const names = [...new Set(noMark.map((r) => r.display_path))];
  return `<div class="pd-warn">このフォルダは段 3 の許可が付いていません（${esc(names.join(' / '))}）。`
    + '段 3 はファイルを消します。許可は<a href="#/settings">設定</a>で付けられます。</div>';
}

/** **その場所が段 3 を許されているか**（`root.allow_stage3`。Q8）。
 *
 * `deletions.py` の `_stage3_ok` と同じ見方: **覆っているフォルダのどれか 1 つに許可があれば許す**。
 * **どのフォルダにも入っていない場所は許さない**（安全側。§0.6-6 の帰結）。
 */
export function stage3Allowed(roots, path) {
  if (!path) return false;
  const covering = (roots || []).filter((r) => underPath(path, r.display_path || r.path));
  return covering.some((r) => Boolean(r.allow_stage3));
}

/** 選んだ枚の**段 3 の出し分け**（P8-5・Q8）。
 *
 * `known` は「フォルダを確かめられたか」。確かめられないときは**出さない**（安全側）が、
 * 文は「許可が無い」と言い切らない（**確かめられなかった**と書く。家風「数を黙って捨てない」）。
 */
export function stage3OfPaths(roots, paths) {
  const known = Boolean(paths && paths.length) && paths.every(Boolean);
  return { allowed: known && paths.every((p) => stage3Allowed(roots, p)), known,
           paths: paths || [] };
}

/** 段 3 のラジオを出さないときの 1 行（`frontend-design.md` §6）。 */
export function stage3BlockedHtml() {
  const got = state.stage3;
  const why = got.known
    ? 'このフォルダには段 3 の許可がありません。段 1・2 だけ選べます。許可は設定で付けられます。'
    : 'フォルダを確かめられないので、段 3 は出していません。もう一度読み込むとやり直せます。';
  return `<div class="pd-warn">${esc(why)}<a href="#/settings">設定を開く</a></div>`;
}

/** 走査中の 1 行（P8-5。走査は削除と同じ錠を取るので、押しても待たされる。§4.6）。 */
export function scanHtml() {
  if (!state.scan || !state.scan.scanning) return '';
  return `<div class="pd-scan">走査中です。終わるまで削除と取り消しは待ちます。</div>`;
}

/** 3 段階の進行（**カタログから外す → アプリのゴミ箱 → ファイルを消す**）。いまの段に印を付ける。
 *
 * **（E-10）** 3 段の図は**凡例に 1 回だけ**出す（`legendHtml`）。**193 行の各行には出さない**
 * （読み上げで毎行「矢印」が入り、いまの段も分からなくなる）。行には `stageText()` を出す。
 */
export function stageStrip(stage) {
  // **（ワーディング監査 W-20。D-5）** 前は「1 印 → 2 ゴミ箱 → 3 実削除」で、同じ段 3 を
  // 「実削除」「完全に消す」「実体を消す」の 3 語で呼んでいた。**段の名前は 1 つ**にする
  // （設計 §6・§17 の「段 1 / 2 / 3」。§6 の行も同じ語に直した）
  const steps = ['1 カタログから外す', '2 アプリのゴミ箱', '3 ファイルを消す'];
  return `<span class="pd-strip">` + steps.map((text, i) =>
    `<span class="pd-step${i + 1 === Number(stage) ? ' on' : ''}">${esc(text)}</span>`
  ).join('<span class="pd-arrow">→</span>') + '</span>';
}

/** **その行の段だけ**の 1 語（E-10。`stageStrip` の 3 段を行に出さない）。 */
export function stageText(stage) {
  const n = Number(stage);
  return STAGE_LABEL[n] ? `段 ${n} ${STAGE_LABEL[n]}` : '';
}

// ---- 画面の状態 ----

const state = {
  items: [], windowSec: 300, found: [], foundCount: 0,
  trash: { days: [], count: 0, bytes: 0 },
  roots: [],                                 // 段 3 の前置きを**実際のフォルダから組む**（G-4）
  ids: [], stage: 1, preview: null, exec: null, msg: '', bad: false,
  confirmLast: false, timer: null, busy: false, ticks: 0,
  // P8-5: 走査中か（`GET /api/scan`）と、選んだ枚の段 3 の出し分け（Q8）
  scan: null, stage3: { allowed: false, known: false, paths: [] },
  // **（P10）まとめての選択**（id の集合。`selectableRows()` に在る行だけが効く）
  selected: new Set(),
};

// ---- 描く（文字列）----

/** まとめてのチェックを付けられる行か（**その行に効く操作がある行だけ**。P10）。 */
export function canPick(item) {
  return Number(item && item.stage) === 1 || Boolean(item && item.closeable);
}

/** 選べる行（「最近の削除」の一覧＋アプリのゴミ箱の欄。**段 2 は下の欄に出る**）。 */
export function selectableRows() {
  const running = state.items.filter((i) => i.state !== 'trashed');
  const trash = (state.trash.days || []).flatMap((day) => day.items || []);
  return [...running, ...trash].filter(canPick);
}

export function pickedRows() {
  return selectableRows().filter((i) => state.selected.has(i.id));
}

/** まとめてのチェック 1 つ（選べない行は同じ幅の空きで揃える）。 */
function pickBox(item) {
  if (!canPick(item)) return '<span class="pd-nopick"></span>';
  const on = state.selected.has(item.id) ? ' checked' : '';
  return `<input type="checkbox" class="pd-pick" data-id="${esc(item.id)}"${on}`
    + ' title="まとめて操作する行を選ぶ">';
}

/** まとめての帯（**全部選ぶ**＋2 つのボタン。P10。**194 件を 1 回で**片付けられる）。
 *
 * **枚はそれぞれの操作が効く行で数える**（段 1 の行だけが「移す」に数えられる）。
 * 1 件も選んでいなければ押せない。**（P10 の監査 D-2）1 件も選んでいないときは「選んだ 0 件」と
 * 書かない**——数ではなく**状態**を言う（「選んだ行はありません」。§6.1 の規約 3・C-22）。
 */
export function bulkHtml() {
  const rows = selectableRows();
  if (!rows.length) return '';
  const picked = pickedRows();
  const advance = picked.filter((i) => Number(i.stage) === 1).length;
  const close = picked.filter((i) => i.closeable).length;
  const all = picked.length === rows.length;
  const pickedText = picked.length
    ? `選んだ ${picked.length.toLocaleString('ja-JP')} 件` : '選んだ行はありません';
  return `<div class="pd-bulk">
    <label class="pd-all"><input type="checkbox" class="pd-all-box"${all ? ' checked' : ''}>`
    + ` 全部選ぶ</label>
    <span class="stat">${pickedText}</span>
    <span class="spacer"></span>
    <button class="pd-advance-many"${advance ? '' : ' disabled'}>`
    + `${esc(bulkLabel('advance', advance))}</button>
    <button class="pd-close-many"${close ? '' : ' disabled'}>`
    + `${esc(bulkLabel('close', close))}</button>
  </div>`;
}

export function rowHtml(item) {
  const stage = Number(item.stage);
  // 残り時間は**段 3 の窓の間だけ**（段 1・2 は窓が無い。§4.6・§11）
  const remain = stage === 3 && item.state === 'pending'
    ? `<span class="pd-remain num" data-remain="${esc(item.id)}">あと ${esc(fmtRemain(item.remaining_sec))}</span>`
    : '<span class="pd-remain num">—</span>';
  // **（P8-3 の再確認 D-1）** 元の場所が埋まっているだけの行は「別名で戻す」を勧める。
  // 「いま消す」は**ボタンだけ**にして、文では勧めない（取り返しのつかない側を大きく言わない）
  // **（P11 の監査 B-1）`move_failed` は「元へ移す」道を言う**——「別名で戻す」も「いま消す」も
  // 通らない（元のフォルダに書けない）。**消す側を案内しない**（戻したかった物が消える）
  const stuckHow = item.stuck_reason === 'target_exists' && item.needs_as_copy
    ? '「別名で戻す」で戻せます。'
    : (item.stuck_reason === 'move_failed'
      ? (stage === 3
        ? 'エクスプローラーで、一時置き場から元の場所へ移してください。'
        : 'エクスプローラーで、アプリのゴミ箱から元の場所へ移してください。')
      : '「別名で戻す」か「いま消す」を選べます。');
  const stuck = item.state === 'stuck'
    ? `<div class="pd-reason">戻せませんでした。${esc(stuckText(item.stuck_reason))}`
      + stuckHow
      + '</div>'
    : '';
  const buttons = [];
  if (item.undoable) {
    // **語を段で分ける**（§4.6）: 窓の無い段 1・2 は「戻す」、段 3 の 5 分の窓は「取り消す」
    buttons.push(`<button class="pd-undo" data-id="${esc(item.id)}">`
      + `${stage === 3 ? '取り消す' : '戻す'}</button>`);
  }
  // **（P10）段 1 の行は、後からアプリのゴミ箱へ移せる**（段 1 が行き止まりだったのを塞ぐ）
  if (stage === 1) {
    buttons.push(`<button class="pd-advance" data-id="${esc(item.id)}"`
      + ' title="この 1 件をアプリのゴミ箱へ移します（戻せます）">'
      + `${esc(ADVANCE_LABEL)}</button>`);
  }
  // **（P10）実体が無い行を終わりにする**（段 1・2 の行だけ。段 3 の行は今までどおり）
  if (item.closeable) {
    buttons.push(`<button class="pd-close" data-id="${esc(item.id)}"`
      + ' title="この行を終わりにします（ファイルは消しません。元に戻せません）">'
      + `${esc(CLOSE_LABEL)}</button>`);
  }
  if (stuck && item.needs_as_copy) {
    // **（C-25）** どんな名前になるかを `title` で補う（ボタンの語は短いまま）
    buttons.push(`<button class="pd-ascopy" data-id="${esc(item.id)}"`
      + ' title="元の名前の後ろに番号を付けて戻します">別名で戻す</button>');
  }
  if (stage === 3 && item.state !== 'purged') {
    buttons.push(`<button class="pd-purge" data-id="${esc(item.id)}">いま消す</button>`);
  }
  return `<div class="pd-row pd-${esc(item.state)}" data-id="${esc(item.id)}">
    ${pickBox(item)}${remain}
    <span class="pd-strip">${esc(stageText(stage))}</span>
    <span class="pd-path mono" title="${esc(item.display_path || item.path)}">${esc(item.display_path || item.path)}</span>
    <span class="pd-meta num">${esc(fmtBytes(item.size))}、${esc(actorText(item.actor))}`
    + `、${esc(fmtWhen(item.at))}</span>
    <span class="spacer"></span>${buttons.join('')}
    ${stuck}
  </div>`;
}

export function runningHtml() {
  // **（監査 C-2）段 1〜3 を出す**（`frontend-design.md` §4.6 の「1 行 = `deletion_log` の 1 行」）。
  // **段 2 だけは出さない**——すぐ下の「ゴミ箱」の欄に日付ごとに出るので、二重に出すと同じ
  // 1 行に「戻す」が 2 つ並ぶ（画面全体では 1 行 = 1 回）
  const rows = state.items.filter((i) => i.state !== 'trashed');
  if (!rows.length) {
    return state.trash.count
      ? `<div class="note">戻せる削除はありません。アプリのゴミ箱の ${state.trash.count} 件は下から戻せます。</div>`
      : '<div class="note">戻せる削除はありません。</div>';
  }
  return rows.map(rowHtml).join('');
}

/** 拾い物（台帳に無い一時置き場の中身。**消さない**。G-4。**D-7**）。 */
export function foundHtml() {
  if (!state.foundCount) return '';
  const shown = state.found.slice(0, 5).map((f) =>
    `<div class="pd-found-row"><span class="mono">${esc(f.path)}</span>`
    + `<span class="pd-meta num">${esc(fmtBytes(f.size))}</span></div>`).join('');
  return `<div class="pd-found"><div class="pd-sub">台帳に無いファイルが一時置き場に`
    + ` ${state.foundCount} 件あります。消しません。`
    + '<span class="stat">エクスプローラーで確かめてから決めてください。</span></div>'
    + shown
    + (state.foundCount > state.found.length
      ? `<div class="stat">ほか ${state.foundCount - state.found.length} 件</div>` : '')
    + '</div>';
}

/** アプリのゴミ箱（段 2。日付ごと。**自動では消さない**。Q7。**G-4** で初出に「アプリの」と書く）。 */
export function trashHtml() {
  if (!state.trash.count) {
    return '<div class="pd-sub">アプリのゴミ箱</div><div class="note">アプリのゴミ箱は空です。</div>';
  }
  const days = state.trash.days.map((day) => `<div class="pd-day">`
    + `<div class="pd-day-head">${esc(day.date)}、${day.count} 件、${esc(fmtBytes(day.bytes))}</div>`
    + day.items.map((item) => `<div class="pd-row pd-trashed" data-id="${esc(item.id)}">
        ${pickBox(item)}
        <span class="pd-strip">${esc(stageText(2))}</span>
        <span class="pd-path mono" title="${esc(item.display_path || item.path)}">${esc(item.display_path || item.path)}</span>
        <span class="pd-meta num">${esc(fmtBytes(item.size))}、${esc(actorText(item.actor))}</span>
        <span class="spacer"></span>
        <button class="pd-trash-restore" data-id="${esc(item.id)}">戻す</button>
        ${item.closeable ? `<button class="pd-close" data-id="${esc(item.id)}"`
          + ' title="この行を終わりにします（ファイルは消しません。元に戻せません）">'
          + `${esc(CLOSE_LABEL)}</button>` : ''}
      </div>`).join('')
    + '</div>').join('');
  // **（ワーディング監査 W-57）** 「掃除の前に一覧を出します」は何の一覧か分からない
  // **（C-3 の点検で見つけた二重の 1 文）** 同じ文を 2 回書いていたので 1 つにした
  return `<div class="pd-sub">アプリのゴミ箱の中身です<span class="stat">自動では消しません。</span></div>`
    + `<div class="pd-trash-head">${state.trash.count} 件、${esc(fmtBytes(state.trash.bytes))}</div>`
    + days;
}

/**
 * **（P9 の監査 G-5）日中に外した枚をその日のバックアップに入れる道を案内する。**
 *
 * 日次は**日付が変わったとき**に 1 回だけ取る（`frontend-design.md` §4.6・`backup.py` §0.12-1）。
 * 実データでは、利用者が 20:04〜20:12 JST に段 1 で外した 193 行が、**00:00:15 JST のバックアップまで
 * どの世代にも入っていなかった**（監査の実測）。段 1（カタログから外す）と段 3（ファイルを消す）の
 * 直後に、**設定の「取り直す」の場所を 1 行で案内する**——**自動では取らない**
 * （勝手に数百 MB を写さない。判断は人）。
 *
 * **（C-2。日本語 UI の監査）** 前は**存在しないボタン「いま取る」**を案内していた
 * （P8-5 で画面の語を「取り直す」に統一した後も、この 1 行だけ古い語だった）。**画面にある語だけを案内する。**
 *
 * 段 2（アプリのゴミ箱へ移す）では出さない（戻せるので急がない）。
 */
export function backupHintHtml(stage) {
  const n = Number(stage);
  if (n !== 1 && n !== 3) return '';
  return '<div class="stat">バックアップは日付が変わったときに取ります。'
    + '<a href="#/settings">設定</a>の「取り直す」で今すぐ取れます。</div>';
}

/** 削除の確認（**モーダルではなく画面の中の段**。`?ids=` で渡されたときだけ）。 */
export function confirmHtml() {
  if (!state.ids.length) return '';
  if (state.exec) {
    const skipped = state.exec.skipped || [];
    const stage = Number(state.exec.stage ?? state.stage);
    // **（P11 の監査 A-1）理由を固定で書かない。** API が返した `skipped[].reason` を日本語の
    // 地図（`SKIP_TEXT`）に通し、**`move_failed` は本文（次の一手）もそのまま出す**。
    // 前は `1 件は中身が変わっていたので消しませんでした。` と、**中身が変わっていない**ときにも
    // そう書いていた（本物の Chrome で見つかった）。
    const kind = stage === 2 ? 'move' : 'delete';
    return `<div class="pd-confirm"><div class="pd-sub">削除の確認</div>
      <div class="pd-done">${esc(doneText(state.exec.count, stage,
        state.exec.window_sec ?? state.windowSec))}</div>`
      + (skipped.length ? `<div class="stat">${esc(skippedText(kind, skipped))}</div>` : '')
      + (moveFailedText(skipped) ? `<div class="stat">${esc(moveFailedText(skipped))}</div>` : '')
      + backupHintHtml(stage)
      + '<div class="pd-confirm-actions">'
      + '<a class="back" href="#/pending-deletes">最近の削除で確かめる</a></div></div>';
  }
  // **（P8-5・Q8）許可の無いフォルダでは段 3 のラジオを出さない**（段 1・2 だけ出す）。
  // `state.stage3.allowed` は `GET /api/roots` と選んだ枚のパスから決める（`stage3OfPaths`）
  const offered = state.stage3.allowed ? [1, 2, 3] : [1, 2];
  const stages = offered.map((n) => `<label class="pd-stage${state.stage === n ? ' on' : ''}">`
    + `<input type="radio" name="pd-stage" class="pd-stage-box" value="${n}"`
    + `${state.stage === n ? ' checked' : ''}> 段 ${n} ${esc(STAGE_LABEL[n])}</label>`).join('');
  const thumbs = state.ids.slice(0, 12).map((id) =>
    `<img loading="lazy" src="/api/assets/${esc(id)}/thumb?size=256" alt="">`).join('');
  const preview = state.preview;
  const items = preview
    ? `<div class="pd-items">${preview.items.map((item) => `<div class="pd-item">
        <span class="mono pd-path">${esc(item.display_path || item.path)}</span>
        <span class="pd-meta num">${esc(fmtBytes(item.size))}</span></div>`).join('')}</div>
      <div class="pd-sum">${preview.count} 枚、${esc(fmtBytes(preview.bytes))}</div>
      <div class="pd-frees">${esc(preview.frees?.note || '')}</div>
      ${preview.not_allowed_count
        ? `<div class="pd-warn">許可の無いフォルダの ${preview.not_allowed_count} 枚は段 3 にできません（段 1・2 はできます）。</div>` : ''}
      ${stage3NoticeHtml(preview, state.roots)}
      ${preview.last_copies
        ? `<div class="pd-warn">この ${preview.last_copies} 枚は、ほかの場所にコピーがありません。消すと中身そのものが無くなります。`
          + `<label class="pd-last"><input type="checkbox" class="pd-last-box"`
          + `${state.confirmLast ? ' checked' : ''}> コピーの無い画像も消す</label></div>` : ''}
      <div class="pd-confirm-actions">
        <button class="pd-exec"${preview.expired ? ' disabled' : ''}>${esc(execLabel(preview.count, preview.stage ?? state.stage))}</button>
        <button class="pd-forget">やめる</button>
        ${preview.expired ? '<span class="stat">確認した一覧の有効期限が切れました。もう一度確認してください。</span>' : ''}
      </div>`
    : `<div class="pd-picked">${thumbs}</div>
      <div class="pd-sum">選んだ ${state.ids.length} 枚</div>
      <div class="pd-confirm-actions">
        <button class="pd-preview">消す内容を確かめる</button>
        <button class="pd-forget">やめる</button>
      </div>`;
  return `<div class="pd-confirm"><div class="pd-sub">削除の確認</div>
    <div class="pd-stages">${stages}</div>
    ${state.stage3.allowed ? '' : stage3BlockedHtml()}${items}</div>`;
}

export function messageHtml() {
  if (!state.msg) return '';
  return `<div class="pd-msg${state.bad ? ' bad' : ''}">${esc(state.msg)}</div>`;
}

export function legendHtml() {
  // **凡例は段に印を付けない**（`stageStrip(null)`。行と見分けが付かなくなる）
  return `<div class="pd-legend">${stageStrip(null)}<span class="stat">`
    // **（ワーディング監査 W-12）** 中黒で文を繋がない（規則 1）。段 3 の呼び方も 1 つに（W-20）
    // **（ワーディングの修正 2）** 「実体を消す用意です」→「ファイルを消します」（§6.1 の規則 3。
    // **利用者に見える文から「用意」をなくす**）
    // **（D-5・G-4）** 「実体」→「ファイル」、「ゴミ箱」→「アプリのゴミ箱」
    + '段 1 はカタログから外すだけで、容量は空きません。段 2 はアプリのゴミ箱へ移します。'
    + '段 3 はファイルを消します。段 1・2 はいつでも戻せ、段 3 は 5 分の間だけ取り消せます。</span></div>';
}

// ---- 読み込み（`GET` は書かない）----

async function load() {
  state.busy = true;
  const [pending, trash, roots] = await Promise.all([
    fetch(PENDING, { headers: asHuman() }).then((r) => r.json()),
    fetch(TRASH, { headers: asHuman() }).then((r) => r.json()),
    // **（監査 G-4）フォルダの一覧**（段 3 の前置きを実際の値から組む）。**無くても止めない**
    // （古いサーバが静的ファイルだけ新しい形。D-7）
    fetch(ROOTS, { headers: asHuman() })
      .then((r) => (r.ok ? r.json() : { roots: [] })).catch(() => ({ roots: [] })),
  ]);
  state.items = pending.items || [];
  state.windowSec = pending.window_sec || 300;
  state.found = pending.found || [];
  state.foundCount = pending.found_count || 0;
  state.trash = trash;
  state.roots = roots.roots || [];
  // **（P8-5）走査中か**（`GET /api/scan`。古いサーバでは 404 なので黙って「走査中でない」）
  state.scan = await fetch(SCAN, { headers: asHuman() })
    .then((r) => (r.ok ? r.json() : null)).catch(() => null);
  // **（P8-5・Q8）選んだ枚の段 3 の出し分け**（フォルダの許可と突き合わせる）
  state.stage3 = await stage3For(state.ids, state.roots);
  if (!state.stage3.allowed && Number(state.stage) === 3) {
    state.stage = 1;                       // 出さない段が選ばれたまま残らないように（安全側）
    state.preview = null;
  }
  // **（P10）消えた行（片付けた・移した）の選択を捨てる**（残すと「選んだ N 件」が食い違う）
  const live = new Set(selectableRows().map((i) => i.id));
  state.selected = new Set([...state.selected].filter((id) => live.has(id)));
  state.busy = false;
  render();
}

/** `GET /api/assets/<id>` の本文から**主のパス**を取る（`app.py` の `_primary_path` と同じ見方）。
 *
 * 一覧（`_summary`）は `path` を返すが、1 枚の口（`store.asset`）は `locations` を返す。
 * どちらの形でも同じ 1 本に決める（**欠けている物を主にしない**）。
 */
function primaryPathOf(one) {
  if (!one) return null;
  if (one.path) return one.path;
  const all = one.locations || [];
  const live = all.filter((l) => !l.missing_at);
  const locs = (live.length ? live : all).slice();
  locs.sort((a, b) => (Number(!a.is_primary) - Number(!b.is_primary))
    || String(a.path).localeCompare(String(b.path)));
  return locs.length ? (locs[0].path || null) : null;
}

/** 選んだ枚のパスを引き、**段 3 を出せるか**を決める（P8-5・Q8）。
 *
 * パスは `GET /api/assets`（1 回）から引く（**枚ごとに `GET` を並べない**）。
 * **（P8-5 の監査 D-5）一覧の上限（2000 枚）を超えるフォルダでは、選んだ枚が一覧に無い。**
 * その枚だけ `GET /api/assets/<id>` で引く（引くのは**足りない枚の数だけ**）。
 * 引けなければ `known: false`（＝段 3 を出さない。**安全側**）。
 */
async function stage3For(ids, roots) {
  if (!ids.length) return stage3OfPaths(roots, []);
  const res = await fetch(ASSETS, { headers: asHuman() }).catch(() => null);
  if (!res || !res.ok) return stage3OfPaths(roots, ids.map(() => null));
  const body = await res.json().catch(() => ({}));
  const byId = new Map((body.items || []).map((row) => [row.id, row.path || null]));
  const missing = [...new Set(ids)].filter((id) => !byId.has(id));
  for (const id of missing) {
    const one = await fetch(`/api/assets/${encodeURIComponent(id)}`, { headers: asHuman() })
      .then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (one) byId.set(id, primaryPathOf(one));
  }
  return stage3OfPaths(roots, ids.map((id) => (byId.has(id) ? (byId.get(id) || null) : null)));
}

function render() {
  const confirm = $('pd-confirm');
  if (confirm) confirm.innerHTML = confirmHtml();
  const scan = $('pd-scan');
  if (scan) scan.innerHTML = scanHtml();
  const legend = $('pd-legend');
  if (legend) legend.innerHTML = legendHtml();
  // **（P10）まとめての帯**（全部選ぶ＋2 つのボタン）。選べる行が 1 つも無ければ出さない
  const bulk = $('pd-bulk');
  if (bulk) bulk.innerHTML = bulkHtml();
  const running = $('pd-running');
  if (running) running.innerHTML = runningHtml();
  const found = $('pd-found');
  if (found) found.innerHTML = foundHtml();
  const trash = $('pd-trash');
  if (trash) trash.innerHTML = trashHtml();
  const msg = $('pd-msg');
  if (msg) msg.innerHTML = messageHtml();
  const brief = $('pd-brief');
  if (brief) {
    // **見出しの件数と合計は、この一覧に出ている行と同じ物**（§4.6）。段 2 はゴミ箱の欄に
    // 出るのでここには数えない（二重に数えると「3 件」と言いながら 2 行しか無い）
    const rows = state.items.filter((i) => i.state !== 'trashed');
    const pending = rows.filter((i) => i.state === 'pending').length;
    const bytes = rows.reduce((n, i) => n + (i.size || 0), 0);
    // **（ワーディング監査 W-2）件数と容量は同じ母数で出す。**
    // 前は件数が「段 3 の窓の数」、容量が「この一覧の全行の合計」で、**193 行ある画面に
    // 「0 件 ・ 324.9 MB」**と出ていた（数が嘘に見える）。いまは**行の数**を先に出す
    brief.textContent = `${Number(rows.length).toLocaleString('ja-JP')} 件`
      + (pending === rows.length ? '' : `（取り消せるのは ${Number(pending).toLocaleString('ja-JP')} 件）`)
      + `、${fmtBytes(bytes)}`;
  }
}

/** 毎秒の見た目だけの書き換え（サーバは触らない）。 */
export function startTick(tickMs = 1000) {
  stopTick();
  if (tickMs > 0) state.timer = setInterval(tickRemain, tickMs);
}

export function stopTick() {
  if (state.timer !== null) { clearInterval(state.timer); state.timer = null; }
}

export function tickActive() { return state.timer !== null; }

function tickRemain() {
  stepRemain(state.items);
  for (const item of state.items) {
    if (item.remaining_sec == null) continue;
    const cell = document.querySelector(`[data-remain="${item.id}"]`);
    if (cell) cell.textContent = `あと ${fmtRemain(item.remaining_sec)}`;
  }
  // **（P8-5）走査中の 1 行は 5 秒ごとに見直す**（走査が終わったら消す。`GET` は書かない）
  state.ticks = (state.ticks || 0) + 1;
  if (state.ticks % 5 === 0) refreshScan();
}

/** 走査中の 1 行だけを読み直す（**画面全体は描き直さない**。毎秒の書き換えを止めない）。 */
export async function refreshScan() {
  const got = await fetch(SCAN, { headers: asHuman() })
    .then((r) => (r.ok ? r.json() : null)).catch(() => null);
  const before = Boolean(state.scan && state.scan.scanning);
  state.scan = got;
  if (Boolean(got && got.scanning) === before) return got;
  const scan = $('pd-scan');
  if (scan) scan.innerHTML = scanHtml();
  return got;
}

// ---- 押されたとき ----

export function stageTaken() {
  return state.stage;
}

export function askStage(n) {
  const got = Number(n);
  if (![1, 2, 3].includes(got) || got === state.stage) return false;
  // **（P8-5・Q8）許可の無いフォルダでは段 3 を選ばせない**（ラジオを出していないのと同じ規則）
  if (got === 3 && !state.stage3.allowed) return false;
  state.stage = got;
  state.preview = null;                 // 段を変えたら凍結は捨てる（評価し直さない）
  state.exec = null;
  state.msg = '';
  render();
  return true;
}

export async function preview() {
  const res = await fetch(PREVIEW, {
    method: 'POST',
    headers: human(),
    body: JSON.stringify({ scope: { kind: 'assets', asset_ids: state.ids }, stage: state.stage }),
  });
  const body = await res.json().catch(() => ({}));
  // **（C-7）** 「確かめられません（409）」では次の一手が無い。2 文にして、番号は括弧の中へ
  if (!res.ok) {
    state.msg = body.detail || `確かめられませんでした。もう一度試してください（詳細: ${res.status}）。`;
    state.bad = true; render(); return null;
  }
  state.preview = body;
  state.msg = '';
  state.bad = false;
  state.confirmLast = false;
  render();
  return body;
}

export async function exec() {
  const got = state.preview;
  if (!got) return null;
  if (got.last_copies && state.stage === 3 && !state.confirmLast) {
    state.msg = 'コピーの無い画像を消すには「コピーの無い画像も消す」にチェックを入れてください。';
    state.bad = true;
    render();
    return null;
  }
  const res = await fetch(BULK, {
    method: 'POST',
    headers: human(),
    body: JSON.stringify({
      preview_id: got.preview_id, confirm: true,
      client_token: token(), confirm_last_copy: Boolean(state.confirmLast),
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    state.msg = body.code === 'preview_expired'
      ? '確認した一覧の有効期限が切れました。もう一度確認してください。'
      : (body.detail || `消せませんでした。もう一度試してください（詳細: ${res.status}）。`);
    state.bad = true;
    if (body.code === 'preview_expired') state.preview = { ...got, expired: true };
    render();
    return null;
  }
  state.exec = { ...body, window_sec: state.windowSec };
  state.preview = null;
  state.msg = '';
  state.bad = false;
  await load();
  return body;
}

export function token() {
  // 同じ操作の二重送信で二重に消さないための鍵（§0.13）。**押すたびに新しくする**
  return (globalThis.crypto?.randomUUID?.() || `t-${Date.now()}-${Math.random().toString(16).slice(2)}`);
}

export async function undo(id, asCopy = false) {
  const res = await fetch(`${PENDING}/${encodeURIComponent(id)}/undo`, {
    method: 'POST', headers: human(), body: JSON.stringify({ as_copy: Boolean(asCopy) }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    state.msg = body.code === 'target_exists'
      ? '元の場所に既にファイルがあります。「別名で戻す」で戻せます。'
      : (body.detail || `戻せませんでした。もう一度試してください（詳細: ${res.status}）。`);
    state.bad = true;
    // **（監査 C-3）失敗したら読み直す。** サーバはこの行を `stuck` にして
    // `stuck_reason` を立てている（`target_exists` なら「別名で戻す」を出す）。
    // 読み直さないと、文は「『別名で戻す』で戻せます」と言うのに**ボタンが 1 つも無い**
    // （利用者は再読込を探すことになる）。成功の道と同じく `load()` を通す
    await load();
    return null;
  }
  state.msg = body.recovered
    ? '戻しました（削除は起きていませんでした。ファイルは元のままです）。'
    : '1 枚を元の場所に戻しました。';
  state.bad = false;
  await load();
  return body;
}

export async function purge(id, confirmed = false) {
  if (!confirmed) return null;
  const res = await fetch(`/api/deletions/${encodeURIComponent(id)}/purge`, {
    method: 'POST', headers: human(), body: JSON.stringify({ confirm: true }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    state.msg = body.code === 'not_in_hold'
      ? '一時置き場にファイルがありません。「取り消す」を試してください。'
      : (body.detail || `消せませんでした。もう一度試してください（詳細: ${res.status}）。`);
    state.bad = true;
    await load();                                  // 失敗の道でも読み直す（C-3 と同じ考え方）
    return null;
  }
  state.msg = 'ファイルを消しました。元に戻せません。';
  state.bad = false;
  await load();
  return body;
}

// ---- 後から段 2 へ進める・実体が無い行を片付ける（P10。利用者の要望）----

/** **1 件を段 2 へ進める**（後からアプリのゴミ箱へ移す。**人だけ**の口）。
 *
 * **確認は挟まない**——「戻す」でいつでも戻せるので、戻す側と同じ軽さにする（§4.6）。
 * 失敗したら読み直す（サーバはその行を触っていないので、画面の状態と食い違わない）。
 *
 * **（P10 の監査 B-1）`busy` で二度押しを止める。** 止めないと POST が 2 回飛び、**1 回目の
 * 成功の文を 2 回目の 409（「既にアプリのゴミ箱へ移しています」）が上書きする**——
 * 利用者の 1 回の操作は成功しているのに、**失敗の文が出る**（本物の Chrome で再現）。
 * `load()` と同じ形（**`await` の前に立てる**ので、2 回目の押下はここで止まる）。
 */
export async function advance(id) {
  if (state.busy) return null;
  state.busy = true;
  try {
    const res = await fetch(advanceOneUrl(id), {
      method: 'POST', headers: human(), body: JSON.stringify({ stage: 2 }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      // **実体が無いときの 409 は本文がそのまま次の一手**（「ファイルが無いので片付ける」）
      state.msg = body.detail || `移せませんでした。もう一度試してください（詳細: ${res.status}）。`;
      state.bad = true;
      await load();
      return null;
    }
    state.msg = advanceDoneText(1);
    state.bad = false;
    await load();
    return body;
  } finally {
    state.busy = false;
  }
}

/** **1 件を片付ける**（実体が無い行を終わりにする。**人だけ**。**ファイルは消さない**）。
 *
 * 戻せない操作なので**押す前に 1 回確認する**（「ファイルは消しません」を文に入れる）。
 *
 * **（P10 の監査 B-1）`busy` で二度押しを止める**（確認の 2 回目も出さない。`await` の前に立てる）。
 */
export async function closeRow(id, confirmed = false) {
  if (state.busy) return null;
  state.busy = true;
  try {
    if (!confirmed && !globalThis.confirm(closeConfirmText(1))) return null;
    const res = await fetch(closeOneUrl(id), {
      method: 'POST', headers: human(), body: JSON.stringify({ reason: 'missing' }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      state.msg = body.detail || `片付けられませんでした。もう一度試してください（詳細: ${res.status}）。`;
      state.bad = true;
      await load();
      return null;
    }
    // **（D-1）既に片付いていた行（`replayed`）は、そう言う**
    state.msg = closeDoneText(1, body.replayed ? 1 : 0);
    state.bad = false;
    await load();
    return body;
  } finally {
    state.busy = false;
  }
}

/** **まとめて**（`kind` は `advance` / `close`。**選んだ行だけ**）。
 *
 * **200 件ずつ分けて送る**（サーバの上限は 1 回 200 件。194 件は 1 回で収まる）。
 * **数を黙って捨てない**——成功と断りを別々に数え、両方を 1 行ずつ出す。
 * 断られた行だけ選択に残す（そのまま押し直せる）。
 *
 * **（P10 の監査 B-1）`busy` で二度押しを止める。** 止めないと POST が 2 回飛び、**2 回目は
 * 0 件・全部断りになるので、6 枚動いたのに「0 件をアプリのゴミ箱へ移しました。」と出る**
 * （本物の Chrome で再現。§6.1 の規約 3「実際に起きたことを言う」に反する）。
 * 止めるのは**確認を出す前**（2 回目の確認も出さない）。
 */
export async function runBatch(kind, confirmed = false) {
  if (state.busy) return null;
  state.busy = true;
  try {
    const targets = pickedRows().filter((i) => (kind === 'advance'
      ? Number(i.stage) === 1 : Boolean(i.closeable)));
    if (!targets.length) return null;
    if (kind === 'close' && !confirmed && !globalThis.confirm(closeConfirmText(targets.length))) {
      return null;
    }
    const ids = targets.map((i) => i.id);
    const done = [];
    const skipped = [];
    let replayed = 0;
    for (let at = 0; at < ids.length; at += BATCH_MAX) {
      const chunk = ids.slice(at, at + BATCH_MAX);
      const res = await fetch(kind === 'advance' ? ADVANCE_MANY : CLOSE_MANY, {
        method: 'POST', headers: human(),
        body: JSON.stringify(kind === 'advance'
          ? { ids: chunk, stage: 2 } : { ids: chunk, reason: 'missing' }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        state.msg = body.detail || `できませんでした。もう一度試してください（詳細: ${res.status}）。`;
        state.bad = true;
        await load();
        return null;
      }
      done.push(...(body[kind === 'advance' ? 'advanced' : 'closed'] || []));
      skipped.push(...(body.skipped || []));
      replayed += Number(body.replayed_count || 0);       // **（D-1）既に片付いていた数**
    }
    state.msg = (kind === 'advance'
      ? advanceDoneText(done.length) : closeDoneText(done.length, replayed))
      + skippedText(kind, skipped)
      // **（P11 の監査 A-1）** 断った理由だけでは**次の一手が分からない**。
      // `move_failed` は API の本文（どこを手で消すか）をそのまま続ける
      + moveFailedText(skipped);
    state.bad = skipped.length > 0;
    const left = new Set(skipped.map((s) => s.deletion_id));
    state.selected = new Set([...state.selected].filter((id) => left.has(id)));
    await load();
    return { count: done.length, skipped: skipped.length, replayed };
  } finally {
    state.busy = false;
  }
}

/** チェック 1 つを切り替える（**描き直して帯の枚数を揃える**）。 */
export function togglePick(id, on) {
  if (on) state.selected.add(id);
  else state.selected.delete(id);
  render();
  return state.selected.has(id);
}

/** **全部選ぶ**（選べる行だけ。外すときは 1 つも選ばない）。 */
export function pickAll(on) {
  state.selected = on ? new Set(selectableRows().map((i) => i.id)) : new Set();
  render();
  return state.selected.size;
}

export async function trashRestore(id) {
  const res = await fetch('/api/trash/restore', {
    method: 'POST', headers: human(), body: JSON.stringify({ deletion_id: id }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    state.msg = body.code === 'target_exists'
      ? '元の場所に既にファイルがあります（アプリのゴミ箱からの復帰は上書きしません）。'
      : (body.detail || `戻せませんでした。もう一度試してください（詳細: ${res.status}）。`);
    state.bad = true;
    await load();                                  // 失敗の道でも読み直す（C-3 と同じ考え方）
    return null;
  }
  state.msg = '1 枚をアプリのゴミ箱から戻しました。';
  state.bad = false;
  await load();
  return body;
}

export function forget() {
  state.ids = [];
  state.preview = null;
  state.exec = null;
  state.msg = '';
  location.hash = '#/pending-deletes';
}

export async function onClick(event) {
  const target = event.target;
  const hit = (selector) => target.closest(selector);
  const stageBox = hit('.pd-stage-box');
  if (stageBox && askStage(stageBox.value)) return;
  if (hit('.pd-preview')) { await preview(); return; }
  if (hit('.pd-exec')) { await exec(); return; }
  if (hit('.pd-forget')) { forget(); return; }
  // **（P10）まとめて**（押す前に確認を 1 回。片付けは戻せない）
  if (hit('.pd-advance-many')) { await runBatch('advance'); return; }
  if (hit('.pd-close-many')) { await runBatch('close'); return; }
  // **（P10）1 行ずつ**（段 1 の行を段 2 へ／実体が無い行を片付ける）
  const advanceBtn = hit('.pd-advance');
  if (advanceBtn) { await advance(advanceBtn.dataset.id); return; }
  const closeBtn = hit('.pd-close');
  if (closeBtn) { await closeRow(closeBtn.dataset.id); return; }
  const undoBtn = hit('.pd-undo');
  if (undoBtn) { await undo(undoBtn.dataset.id); return; }
  const copyBtn = hit('.pd-ascopy');
  if (copyBtn) { await undo(copyBtn.dataset.id, true); return; }
  const purgeBtn = hit('.pd-purge');
  if (purgeBtn) {
    if (globalThis.confirm('ファイルをいま消します。元に戻せません。')) await purge(purgeBtn.dataset.id, true);
    return;
  }
  const restoreBtn = hit('.pd-trash-restore');
  if (restoreBtn) { await trashRestore(restoreBtn.dataset.id); return; }
}

export function onChange(event) {
  const target = event.target;
  if (target.closest('.pd-last-box')) {
    state.confirmLast = Boolean(target.checked);
    return;
  }
  // **（P10）まとめての選択**（全部選ぶ→ 1 行ずつのチェックの順に見る）
  const one = target.closest('.pd-pick');
  if (one) { togglePick(one.dataset.id, Boolean(one.checked)); return; }
  if (target.closest('.pd-all-box')) { pickAll(Boolean(target.checked)); return; }
  const box = target.closest('.pd-stage-box');
  if (box) askStage(box.value);
}

// ---- 入口 ----

export async function showPending(search) {
  state.ids = idsOf(search);
  state.preview = null;
  state.exec = null;
  state.msg = '';
  state.selected = new Set();                 // **（P10）画面を開き直したら 1 つも選ばない**
  document.body.classList.add('pending');
  await load();
  startTick();
}

export function hidePending() {
  document.body.classList.remove('pending');
  stopTick();
}

export function wirePending() {
  // **（P10）`pd-bulk` も配線する**（まとめての帯。押す検査はこの聞き手を叩く）
  for (const id of ['pd-confirm', 'pd-running', 'pd-trash', 'pd-bulk']) {
    const node = $(id);
    if (!node) continue;
    node.addEventListener('click', onClick);
    node.addEventListener('change', onChange);
  }
  const again = $('pd-again');
  if (again) again.addEventListener('click', () => { load().catch(() => {}); });
}
