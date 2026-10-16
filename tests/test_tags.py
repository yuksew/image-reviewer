"""タグの語の正規化と、手動の付け外しのテスト（P4-1）。

設計: docs/p4-design.md §0.7（正規形。**点検 A-1**）・§0.8（PNG の語。**点検 B-4 / G-4**）・
§0.14（Q1 / Q3）・§3.1（`human` だけ）・§3.4（契約の形）・§3.6（絞り込み）
点検 §I: `known` は**語彙から引き直す**（§I-1）・`GET /api/tags` は既定で `known=1`（§I-2）・
**長すぎる断片は入れない**（§I-3）

各テストの docstring に「何を壊すと落ちるか」を書く（P5 の監査 F1 の教訓）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from image_reviewer import db, tagger, tags
from image_reviewer.jobs import JobService
from image_reviewer.review import ReviewError
from image_reviewer.store import Store


def add_asset(store: Store, sha: str, name: str = "a.png", **kw) -> str:
    args = {"size": 100, "mtime_ns": 1, "width": 16, "height": 16, "fmt": "png",
            "meta": None, "note": None}
    args.update(kw)
    path = store.data_dir.parent / "images" / name
    asset_id, _ = store.register(sha256=sha, path=str(path), **args)
    return asset_id


@pytest.fixture
def env(tmp_path):
    store = Store(tmp_path / "data")
    jobs = JobService(store, recover=False)
    try:
        yield SimpleNamespace(store=store, jobs=jobs, tmp_path=tmp_path)
    finally:
        store.close()


# ---- 語の正規形（§0.7 / 点検 A-1）----


def test_normalization_keeps_parentheses_and_colons():
    """§0.7 / 点検 A-1: **括弧とコロンは語の一部**。

    落とすと CSV の 1,619 語（キャラ名の 51%）と一致しなくなる（`admiral_\\(kancolle\\)` が
    `admiral_kancolle` になる）。エスケープ `\\(` `\\)` だけを外す。
    """
    assert tagger.normalize_name(r"admiral_\(kancolle\)") == "admiral_(kancolle)"
    assert tagger.normalize_name(r"2b_\(nier:automata\)") == "2b_(nier:automata)"
    assert tagger.normalize_name(":d") == ":d"                    # コロンだけの語も残す
    assert tagger.normalize_name("Long Hair") == "long_hair"      # 空白は `_`、小文字に
    assert tagger.normalize_name("a[b]c") == "abc"                # `[` `]` は CSV に無いので落とす
    assert tagger.normalize_name("  ") == ""


def test_png_words_split_and_strip_weights_but_keep_inner_parentheses():
    """§0.8 / 点検 B-4・G-4: `,` と `.` で割り、前置きと**外側の重み**だけを外す。

    実データの形（`looking to the side. First girl: black hair, long hair`）で、
    `.` の後ろの語が拾えること・**内側の括弧は残る**ことを固定する。
    """
    text = ("masterpiece, (three quarter view:1.5), looking to the side. First girl: black hair,"
            " long hair, admiral_\\(kancolle\\), masterpiece")
    got = tagger.png_words(text)
    assert got == ["masterpiece", "three_quarter_view", "looking_to_the_side", "black_hair",
                   "long_hair", "admiral_(kancolle)"], got
    assert tagger.png_words(None) == []


def test_png_words_drop_over_long_fragments(env):
    """点検 §I-3: **長すぎる断片は入れない**（実データに 252 字の文が 1 語になった例がある）。"""
    long_text = "a" * 300
    assert tagger.is_acceptable("x" * tagger.MAX_TAG_LEN)
    assert not tagger.is_acceptable("x" * (tagger.MAX_TAG_LEN + 1))
    assert not tagger.is_acceptable("")
    assert tagger.png_words(long_text) == ["a" * 300]             # 切り出しはする（判断は書き込み側）
    assert not tagger.is_acceptable(tagger.png_words(long_text)[0])


# ---- 語彙（CSV）と `known`（§0.8-4 / 点検 §I-1）----


def write_csv(path: Path, names: list[tuple[str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("tag_id,name,category,count\n")
        for index, (name, category) in enumerate(names):
            handle.write(f"{index},{name},{category},0\n")
    return path


def test_the_csv_rejects_non_contiguous_categories(tmp_path):
    """§0.6-6 / 点検 C-2: `category` が連続していない CSV は**拒否する**。

    連続していないと `general_index` / `character_index` の決め方（最初の行）が成り立たず、
    出力ベクトルの切り方が壊れる。
    """
    good = write_csv(tmp_path / "good.csv",
                     [("safe", "9"), ("1girl", "0"), ("long_hair", "0"), ("hatsune_miku", "4")])
    csv = tagger.read_csv(good)
    assert (csv.general_index, csv.character_index) == (1, 3)
    assert csv.known("long_hair") and not csv.known("black_hair")
    assert csv.category_of("hatsune_miku") == (4, "character")

    bad = write_csv(tmp_path / "bad.csv",
                    [("1girl", "0"), ("hatsune_miku", "4"), ("long_hair", "0")])
    with pytest.raises(ReviewError) as got:
        tagger.read_csv(bad)
    assert got.value.code == "tagger_csv_unsupported"


def test_known_is_raised_by_upsert_and_refreshed_at_job_start(env):
    """点検 §I-1: `known` は**語彙から引き直す**。

    - `INSERT OR IGNORE` だと **PNG の語が先に入った語が `known=0` のまま残る**ので、
      `ON CONFLICT ... DO UPDATE SET known = max(known, excluded.known)` で**上げる**
    - ジョブの開始時に 1 回 `UPDATE tag SET known = (name IN 語彙)` で引き直す
    """
    with env.store.transaction() as con:
        first = JobService._ensure_tag(con, "black_hair", None, None, 0)
        assert con.execute("SELECT known FROM tag WHERE id = ?", (first,)).fetchone()["known"] == 0
        again = JobService._ensure_tag(con, "black_hair", 0, "general", 1)
        assert again == first, "同じ語で行が 2 つになった（name の一意性が壊れた）"
        row = con.execute("SELECT known, category FROM tag WHERE id = ?", (first,)).fetchone()
        assert row["known"] == 1, "known が 1 に上がっていない（§I-1）"
        assert row["category"] == 0, "後から分かった category が埋まっていない"

    csv = tagger.read_csv(write_csv(env.tmp_path / "t.csv",
                                    [("1girl", "0"), ("long_hair", "0"), ("black_hair", "0")]))
    with env.store.transaction() as con:
        JobService._ensure_tag(con, "black_hair", None, None, 0)
        con.execute("UPDATE tag SET known = 0")
        assert con.execute("SELECT known FROM tag WHERE name = 'black_hair'").fetchone()["known"] == 0
    env.jobs._refresh_known(csv)
    with env.store.locked() as con:
        assert con.execute("SELECT known FROM tag WHERE name = 'black_hair'").fetchone()["known"] == 1
        assert con.execute("SELECT count(*) AS n FROM tag").fetchone()["n"] == 1


# ---- 手動の付け外し（§3.1 / §0.14 Q3）----


def test_manual_tags_are_idempotent_and_human_only(tmp_path, monkeypatch):
    """§3.1: 同じ語を 2 回でも行は 1 つ。`human` 以外は 403。2 回目の `DELETE` は 404。"""
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from image_reviewer.app import create_app

    app = create_app()
    human = {"X-Image-Reviewer-Actor": "human"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        store = app.state.store
        asset = add_asset(store, "a" * 64)
        with store.transaction() as con:
            tag_id = JobService._ensure_tag(con, "long_hair", 0, "general", 1)

        got = client.post(f"/api/assets/{asset}/tags", json={"tag_id": tag_id}, headers=human)
        assert got.status_code == 200 and got.json()["added"] is True, got.text
        again = client.post(f"/api/assets/{asset}/tags", json={"tag_id": tag_id}, headers=human)
        assert again.json()["added"] is False, "2 回目で行が増えた（冪等でない）"
        with store.locked() as con:
            assert con.execute("SELECT count(*) AS n FROM asset_tag WHERE source = 'manual'"
                               ).fetchone()["n"] == 1
        # エージェントは 403（ヘッダが無ければ `agent`）
        assert client.post(f"/api/assets/{asset}/tags",
                           json={"tag_id": tag_id}).status_code == 403
        assert client.delete(f"/api/assets/{asset}/tags/{tag_id}").status_code == 403
        # 人が外す → 2 回目は 404
        assert client.delete(f"/api/assets/{asset}/tags/{tag_id}", headers=human).status_code == 200
        assert client.delete(f"/api/assets/{asset}/tags/{tag_id}", headers=human).status_code == 404
        # 知らない語は 404
        assert client.post(f"/api/assets/{asset}/tags", json={"name": "no_such_tag"},
                           headers=human).status_code == 404
        # 読む口は書かない（行数が変わらない）
        with store.locked() as con:
            before = con.execute("SELECT count(*) AS n FROM tag").fetchone()["n"]
        assert client.get(f"/api/assets/{asset}/tags").status_code == 200
        assert client.get("/api/tags").status_code == 200
        with store.locked() as con:
            assert con.execute("SELECT count(*) AS n FROM tag").fetchone()["n"] == before


def test_the_new_tag_endpoints_are_guarded(tmp_path, monkeypatch):
    """§3.1 / 既存の middleware（`design.md` §6.3.1）: 新しい `POST` も `Host` と
    `Content-Type` で弾かれる（P5・P6 と同じ観点。**口を足すたびに書く**）。"""
    monkeypatch.setenv("IMAGE_REVIEWER_DATA", str(tmp_path / "data"))
    from image_reviewer.app import create_app

    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/api/assets/tag", json={},
                           headers={"Host": "evil.example"}).status_code == 403
        assert client.post("/api/assets/tag", content=b"{}",
                           headers={"Content-Type": "text/plain"}).status_code == 403
        assert client.post("/api/jobs/01MISSING/cancel",
                           headers={"Host": "evil.example"}).status_code == 403
        # 守りを通過すれば 404（job が無い）まで届く
        assert client.post("/api/jobs/01MISSING/cancel").status_code == 404


def test_tag_docs_merge_sources_and_keep_the_deterministic_order(env):
    """§3.4・§0.10: 同じ語は 1 行にまとめて `sources` に全部入れる。並びは決定的。"""
    asset = add_asset(env.store, "a" * 64)
    with env.store.transaction() as con:
        wide = JobService._ensure_tag(con, "long_hair", 0, "general", 1)
        char = JobService._ensure_tag(con, "hatsune_miku", 4, "character", 1)
        for tag_id, source, score in ((wide, "png", None), (wide, "wd14", 0.5),
                                      (char, "wd14", 0.99)):
            con.execute("INSERT INTO asset_tag(asset_id, tag_id, score, source, model, actor,"
                        " tagged_at) VALUES (?,?,?,?,NULL,NULL,?)",
                        (asset, tag_id, score, source, db.stamp()))
    with env.store.locked() as con:
        items = tags.tag_docs(con, asset)
    assert [i["name"] for i in items] == ["hatsune_miku", "long_hair"], "キャラが先（§0.10）"
    merged = [i for i in items if i["name"] == "long_hair"][0]
    assert sorted(merged["sources"]) == ["png", "wd14"]
    assert merged["known"] is True and merged["gloss"] is None
    # **P4-3 の監査 A-2**: 画面が「訳す」で使う `tag_id` を返す（名前から `Number()` すると
    # `NaN` → `tag_ids: []` → **必ず 422** になっていた）。**足した欄は実際に出ていること**を固定する
    assert all(isinstance(i["tag_id"], int) for i in items), "items に tag_id が入っていない（監査 A-2）"
    assert merged["tag_id"] == wide


# ---- 語の一覧（§3.6 / 点検 §I-2）----


def test_the_tag_list_defaults_to_the_vocabulary(env):
    """点検 §I-2: `GET /api/tags` の既定は `known=1` だけ。

    実データでは件数の**上位 4 語が全部 `known=0` の品質語**（`masterpiece` / `best_quality` /
    `safe` / `score_7`）で、上位 50 のうち 25 語が `known=0`。既定で絞らないと一覧が埋まる。
    """
    asset = add_asset(env.store, "a" * 64)
    with env.store.transaction() as con:
        for name, known in (("masterpiece", 0), ("best_quality", 0), ("long_hair", 1)):
            tag_id = JobService._ensure_tag(con, name, None, None, known)
            con.execute("INSERT INTO asset_tag(asset_id, tag_id, score, source, model, actor,"
                        " tagged_at) VALUES (?,?,NULL,'png',NULL,NULL,?)",
                        (asset, tag_id, db.stamp()))
    with env.store.locked() as con:
        default = tags.list_tags(con)
        unknown = tags.list_tags(con, known="0")
        everything = tags.list_tags(con, known="all")
    assert [i["name"] for i in default["items"]] == ["long_hair"]
    # 同じ使用数なら名前順（`best_quality` < `masterpiece`）
    assert [i["name"] for i in unknown["items"]] == ["best_quality", "masterpiece"]
    assert len(everything["items"]) == 3
    assert default["counts"] == {"known": 1, "unknown": 2}
    assert everything["items"][0]["uses"] == 1
    with pytest.raises(ReviewError):
        with env.store.locked() as con:
            tags.list_tags(con, known="yes")


# ---- 監査で見つかった不具合の検査（P4-1 の監査 C-2 / C-3 / C-4 / C-5）----


def test_unbalanced_parentheses_are_stripped_or_dropped():
    """監査 C-3: `,` で先に割った残り（`(masterpiece` など）を語にしない。

    実データで `(masterpiece` が `known=0` の語として出ていた（外側の重みの規則に当たらない）。
    **数が合っていれば語の一部として残す**（`admiral_(kancolle)` は語。点検 A-1）。
    """
    got = tagger.png_words("(masterpiece, best quality:1.2), (bar), ((foo)), masterpiece)")
    assert got == ["masterpiece", "bar", "foo"], got
    # 語の中の括弧は残る（キャラ名。CSV の 51% が括弧を含む）
    assert tagger.png_words("admiral_\\(kancolle\\), rem_\\(re:zero\\)") == \
        ["admiral_(kancolle)", "rem_(re:zero)"]


def test_a_manual_tag_can_come_from_the_vocabulary(env, monkeypatch):
    """監査 C-4: **語彙（CSV）にある語なら、まだ誰も付けていなくても人が付けられる**。

    直す前は `tag` 表にある語しか付けられず、語彙にある `black_hair` でも 404 だった
    （文言は「語彙にありません」だが、実際は「表に無い」）。
    """
    asset = add_asset(env.store, "a" * 64)
    csv = write_csv(env.tmp_path / "models" / "selected_tags.csv", [("black_hair", "0")])
    monkeypatch.setattr(tagger, "find_csv", lambda explicit=None: csv)
    monkeypatch.setattr(tagger, "csv_of", lambda settings: tagger.read_csv(csv), raising=False)

    with env.store.transaction() as con:
        row = tags.ensure_tag(con, "black_hair", csv=tagger.read_csv(csv))
    assert row is not None, "語彙にある語の行を作っていない（監査 C-4）"
    assert row["known"] == 1
    # 語彙にも無い語は作らない（勝手に語彙を増やさない）
    with env.store.transaction() as con:
        assert tags.ensure_tag(con, "not_a_tag_at_all", csv=tagger.read_csv(csv)) is None


def test_the_manual_actor_survives_merging(env):
    """監査 C-5: 同じ語が `wd14` と `manual` にあるとき、**誰が付けたかを落とさない**。

    直す前は並びの都合で先に来る `wd14` の行（`actor` は NULL）の値だけが残り、
    人が付けた事実は `sources` に残るが `actor` は消えていた。
    """
    asset = add_asset(env.store, "a" * 64)
    with env.store.transaction() as con:
        tag_id = JobService._ensure_tag(con, "1girl", 0, "general", 1)
        con.execute("INSERT INTO asset_tag(asset_id, tag_id, score, source, model, actor,"
                    " tagged_at) VALUES (?,?,0.9,'wd14','m',NULL,?)", (asset, tag_id, db.stamp()))
        con.execute("INSERT INTO asset_tag(asset_id, tag_id, score, source, model, actor,"
                    " tagged_at) VALUES (?,?,NULL,'manual',NULL,'human',?)",
                    (asset, tag_id, db.stamp()))
    with env.store.locked() as con:
        item = [i for i in tags.tag_docs(con, asset) if i["name"] == "1girl"][0]
    assert sorted(item["sources"]) == ["manual", "wd14"]
    assert item["actor"] == "human", "人が付けた actor が消えている（監査 C-5）"


def test_the_default_targets_do_not_require_every_source(env):
    """監査 C-2: `wd14` が `sources` にあれば、**`wd14` の有無だけ**で対象を決める。

    直す前は出所の **AND** だったので、`png` だけ先に付いた画像が既定の走行から外れていた
    （`sources=["png","wd14"]` で「png も wd14 も無い画像」だけが対象になっていた）。
    """
    import json as _json

    from image_reviewer.jobs import JobService as _Jobs

    first = add_asset(env.store, "a" * 64, "a.png")
    second = add_asset(env.store, "b" * 64, "b.png")
    with env.store.transaction() as con:
        tag_id = _Jobs._ensure_tag(con, "1girl", 0, "general", 1)
        # 1 枚目は png の語だけ、2 枚目は wd14 の語だけを持つ
        con.execute("INSERT INTO asset_tag(asset_id, tag_id, source, tagged_at)"
                    " VALUES (?,?,'png',?)", (first, tag_id, db.stamp()))
        con.execute("INSERT INTO asset_tag(asset_id, tag_id, source, model, tagged_at)"
                    " VALUES (?,?,'wd14','m',?)", (second, tag_id, db.stamp()))
    with env.store.locked() as con:
        got = env.jobs._targets(con, asset_ids=None, sources=["png", "wd14"], limit=0)
    assert got == [first], "png しか無い画像を対象から外している（監査 C-2）"


def test_the_builtin_preprocess_resizes_with_int_like_the_node():
    """監査 B-3: 縮小は **`int()` の切り捨て**（ノード `wd14tagger.py:63` と同じ）。

    `round()` だと寸法が 1 px 違い、**語が 1〜2 語変わることがある**（監査の実測: 768×1360 の
    4 枚のうち 2 枚）。ここを揃えないと、線 8（内蔵と ComfyUI の一致）が**方式の違いではなく
    丸めの違い**で落ちる。768×1360 を 448 に合わせると **252**（`int`）か 253（`round`）。
    白パッドの左幅が 98（252 のとき）か 97（253 のとき）かで見分ける。
    """
    import numpy as np
    from PIL import Image

    image = Image.new("RGB", (768, 1360), (10, 20, 30))
    got = tagger.preprocess(image, 448)
    assert got.shape == (1, 448, 448, 3)
    canvas = got[0]
    assert tuple(canvas[0, 97]) == (255, 255, 255), "左の余白が 97 px（round の寸法）になっている"
    assert tuple(canvas[0, 98]) != (255, 255, 255), "余白が 98 px 未満（int の寸法になっていない）"
    # BGR で入る（RGB→BGR）ので、色は (30, 20, 10)
    assert tuple(canvas[0, 200]) == (30, 20, 10)


def test_the_job_list_returns_failed_items(env):
    """**P4-3 の監査 A-1**: 一覧（`GET /api/jobs`）も `items_failed` を先頭 20 件返す。

    以前は `failed_limit=0` だったので、画面（一覧だけを読む）は**失敗の理由も
    「もう一度」の押し場も出せなかった**（`GET /api/jobs/{id}` には入っているのに、読む口だけ空）。
    """
    jobs = JobService(env.store, poll=0.01)
    job_id = db.ulid()
    with env.store.transaction() as con:
        con.execute("INSERT INTO job(id, kind, state, params, created_at, started_at, finished_at)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (job_id, "tag", "failed", "{}", db.stamp(), db.stamp(), db.stamp()))
        con.execute("INSERT INTO job_item(job_id, ref, state, error) VALUES (?,?,?,?)",
                    (job_id, "01AUDITNOFILE00000000000000", "failed", "実体が見つかりません"))

    listed = jobs.list(limit=50)["items"][0]
    assert listed["counts"]["failed"] == 1
    assert listed["items_failed"], "一覧の items_failed が空（監査 A-1）"
    assert listed["items_failed"][0]["error"] == "実体が見つかりません"


def test_the_tag_list_pages_by_the_same_key_as_the_order(env):
    """P4-3 の再確認 B-1: 頁送りは**並びと同じ鍵**（`uses DESC, name`）で行う。

    前の版は `name` だけを鍵にしていたので、2 頁目が「`name` が cursor より後の語を**使用数順**に」なり、
    **1 頁目と重複**して続きに届かなかった（実測: 630 語のうち 413 語に届かない）。
    """
    from image_reviewer.tags import list_tags

    a = add_asset(env.store, "a" * 64)
    with env.store.transaction() as con:
        for i in range(25):
            con.execute("INSERT INTO tag(name, known) VALUES (?, 1)", (f"w{i:03d}",))
            con.execute("INSERT INTO asset_tag(asset_id, tag_id, source, tagged_at)"
                        " VALUES (?, (SELECT id FROM tag WHERE name = ?), 'wd14', ?)",
                        (a, f"w{i:03d}", db.now()))
    with env.store.locked() as con:
        page1 = list_tags(con, limit=10)
        page2 = list_tags(con, limit=10, cursor=page1["next_cursor"])
        page3 = list_tags(con, limit=10, cursor=page2["next_cursor"])

    names = [i["name"] for page in (page1, page2, page3) for i in page["items"]]
    assert len(names) == 25, f"3 頁で 25 語に届かない（{len(names)}）"
    assert len(set(names)) == 25, "頁をまたいで語が重複した（頁送りの鍵が並びと違う）"
    assert page1["total"] == page2["total"] == 25, "total が cursor で減った"
    assert page3["next_cursor"] is None, "最後の頁で next_cursor が残った"


def test_both_taggers_accept_the_same_call_shape():
    """`jobs.py` は方式を選ばずに `tag(path, name=...)` と呼ぶ（P4-2 の実測で踏んだ不具合）。

    内蔵（`BuiltinTagger`）が `name` を受けていなかったので、**`onnxruntime` を入れて初めて**
    内蔵のときだけ全件 `TypeError: tag() got an unexpected keyword argument 'name'` で失敗した
    （ジョブは `failed`、語は 0。実データの複製で再現）。**口が揃っていることをここで固定する**
    （本物の模型は呼ばない＝`inspect` で見る）。
    """
    import inspect

    from image_reviewer.tagger import BuiltinTagger, ComfyTagger

    for cls in (BuiltinTagger, ComfyTagger):
        params = inspect.signature(cls.tag).parameters
        assert "name" in params, f"{cls.__name__}.tag が name を受けない（jobs.py の呼び方と食い違う）"
        assert params["name"].kind is inspect.Parameter.KEYWORD_ONLY, \
            f"{cls.__name__}.tag の name はキーワード専用であること"
