// 一覧の絞り込み（**左の列**と**上部の「来歴: …」**）と、0 枚のときの文。
//
// 設計: docs/frontend-design.md §6（文言）・§6.1（規約 A〜F を通し番号 1〜6 で）・§4.5（件数）
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
 * 一覧が 0 枚のときの 1 行（§6）。**HTML を返す**（コマンドを `<code>` で出す。
 * 文字列は定数なので `esc()` は要らない）。
 *
 * **（ワーディング監査 W-3）** 絞り込みで 0 枚なのに「画像がまだありません。
 * 走査するフォルダを追加すると…」と言わない（**走査は済んでいる**。間違った指示になる）。
 *
 * **（日本語 UI の監査 C-1）** 空のライブラリの案内は**実際にできる方法**を書く。
 * **フォルダを追加する画面はアプリに無い**（登録は CLI の `scan --root` だけ）ので、
 * 押せない入口を案内しない（§6.1 の規約 3「空の状態は『いまの状態』＋『次に押す物』の 2 文」）。
 */
export function emptyText(filtering) {
  return filtering
    ? '条件に合う画像がありません。絞り込みを外すと全部が見えます。'
    : '画像がまだ登録されていません。コマンド <code>image-reviewer scan --root &lt;フォルダ&gt;</code> '
      + 'で登録すると、ここに並びます。';
}
