// 画面に出す「枚」の規則（**1 か所だけ**。P9 の監査 C-2）
//
// 設計: docs/frontend-design.md §6「上部バー: 枚数」・§4.5（上部バー）
//
// なぜ 1 か所にしたか:
// - P9 は上部バーの枚数を `/api/assets` の `total`（**生きた枚**）に変えたが、
//   左の一覧の「すべて」(`#c-all`) と下部バーは `/api/stats` の `assets`
//   （**段 1〜3 で外した枚を含む**）のままだった。実データでは **上部 262 枚・すべて 455**
//   と、**同じ画面に 2 つの数**が並んだ（監査 C-2）。
// - **規則は 1 つ**: 画面に出す「枚」は**生きた枚**＝ `GET /api/assets` の `total`。
//   段 1〜3 で外した枚は `#/pending-deletes` に出るので、ここでは数えない。
// - 一覧は `limit=2000` で引くので**切れる**。切れているときだけ
//   「N 枚（先頭 M 枚を表示）」と添える（**数を黙って捨てない**）。
// - `total` が無い古いサーバでは `/api/stats` の `assets` に落とす（画面を止めない）。
//
// このモジュールは**純粋**（DOM を触らない）。`tools/gui_smoke.mjs` が 1 件だけ固定する。

/** 生きた枚（`GET /api/assets` の `total`。無ければ `/api/stats` の `assets`）。 */
export function liveTotal(stats, total) {
  const n = Number(total);
  if (Number.isFinite(n) && n >= 0) return n;
  return Number((stats || {}).assets) || 0;
}

/** 上部バーの文言（切れているときだけ「先頭 M 枚を表示」を添える）。 */
export function briefText(total, listed) {
  const n = Number(total) || 0;
  const shown = Number(listed) || 0;
  return (shown && n > shown) ? `${n} 枚（先頭 ${shown} 枚を表示）` : `${n} 枚`;
}

/**
 * 来歴あり／なしの数（`#c-with` / `#c-without` と下部バー）。
 *
 * **一覧が全部そろっているときは一覧から数える**（生きた枚の内訳になる）。
 * `limit=2000` で切れているときは一覧から数えられないので、`/api/stats` の値
 * （**全部の行**の数）に落とす——そのときは下部バーの内訳が `total` と足し合わないが、
 * **画面には「先頭 2000 枚を表示」と出ている**ので、何の数かは読める。
 */
export function provenanceCounts(items, total, stats) {
  const n = Number(total) || 0;
  const list = Array.isArray(items) ? items : [];
  if (list.length >= n) {
    const withProv = list.filter((a) => a && a.has_provenance).length;
    return { total: n, with: withProv, without: n - withProv };
  }
  return {
    total: n,
    with: Number((stats || {}).with_provenance) || 0,
    without: Number((stats || {}).without_provenance) || 0,
  };
}
