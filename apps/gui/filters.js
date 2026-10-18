// 一覧の絞り込み（**左の列**と**上部の「来歴: …」**）と、0 枚のときの文。
//
// 設計: docs/frontend-design.md §6（文言）・§6.1（規則 3 つ）・§4.5（件数）
//
// **なぜ分けたか（ワーディング監査 G-12）**: 左の列の「来歴あり」「来歴なし」は
// `data-filter="with"` / `"without"` を持っていて**押せるのに、何も絞られなかった**
// （`app.js` の `visibleAssets()` が `kind:` と `model:` しか見ていなかった）。
// 押したときに**どの軸がどう動くか**を、DOM を知らない純関数にして検査で固定する。
//
// **軸は 2 つで、左の列は 1 つだけ選べる**:
// - `filter`: `all` / `kind:<値>` / `model:<名前>`
// - `provenance`: `all` / `with` / `without`（上部の「来歴: すべて / あり / なし」と同じ軸）
//
// このモジュールは**純粋**（DOM を触らない）。`tools/gui_smoke.mjs` が固定する。

/** 左の列の 1 つを押したときの、新しい軸（**他の軸は外す**）。 */
export function railSelection(filter, provenance = 'all') {
  if (filter === 'with' || filter === 'without') return { filter: 'all', provenance: filter };
  if (filter === 'all') return { filter: 'all', provenance: 'all' };
  return { filter, provenance: 'all' };
}

/** 絞り込みが効いているか（0 枚のときの文を選ぶのに使う）。 */
export function isFiltering(filter, provenance = 'all') {
  return filter !== 'all' || provenance !== 'all';
}

/** 絞り込んだ結果の画像（`items` は `GET /api/assets` の `items`）。 */
export function visibleAssets(items, { filter = 'all', provenance = 'all' } = {}) {
  let list = Array.isArray(items) ? items : [];
  if (provenance === 'with') list = list.filter((a) => a && a.has_provenance);
  if (provenance === 'without') list = list.filter((a) => a && !a.has_provenance);
  if (typeof filter === 'string' && filter.startsWith('kind:')) {
    list = list.filter((a) => a && a.kind === filter.slice(5));
  } else if (typeof filter === 'string' && filter.startsWith('model:')) {
    list = list.filter((a) => a && a.model === filter.slice(6));
  }
  return list;
}

/**
 * 一覧が 0 枚のときの 1 行（§6）。
 *
 * **（ワーディング監査 W-3）** 絞り込みで 0 枚なのに「この入れ物にはまだ画像がありません。
 * 走査するフォルダを追加すると…」と言わない（**走査は済んでいる**。間違った指示になる）。
 */
export function emptyText(filtering) {
  return filtering
    ? '条件に合う画像がありません。絞り込みを外すと全部が見えます。'
    : 'この入れ物にはまだ画像がありません。走査するフォルダを追加すると、ここに並びます。';
}
