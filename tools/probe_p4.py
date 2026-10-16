"""P4 の線を**実機で**出す（設計 §1.2 の線 1・2・7・8 / P4-2 の 4・5・6 / §8.4）。

- 線 1: 未タグの 8 枚に語が付く（`POST /api/assets/tag` → `GET /api/jobs/{id}` が `done`）
- 線 2: **出所が混ざらない**（`png` / `wd14` / `manual` を別々に取れる）
- 線 7: 手動の付け外しが冪等・`human` だけ（403 / 404）
- 線 8: **内蔵と ComfyUI の語の集合が一致**（`--engine both`。内蔵は `onnxruntime` が要る）
- **線 4・5・6（`--gloss`）**: 語釈。**20/20 が返るか**・**2 回目は模型を回さない**か・
  **人が直した語釈が守られる**か・**注入 4 種**（番号の無い行 / 番号の重複 / 英語のまま / 空の応答）で
  `tag_gloss` に誤った行が入らないか・**時間**

**実データ `.data/` は触らない**（`--data` で指定した使い捨ての置き場だけを使う）。
ComfyUI を**実際に叩く**（画像の生成はしない。タグ付けと訳だけ。§0.5・§0.9）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image                                     # noqa: E402

from image_reviewer.gloss import GlossService               # noqa: E402
from image_reviewer.store import Store                    # noqa: E402

BASE = ROOT / ".tmp-audit-redo" / "p4"
PORT = 8798
OK = True


def call(method: str, url: str, payload: dict | None = None, headers: dict | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    head = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(url, data=data, headers=head, method=method)
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            body = response.read()
            return response.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:                  # 4xx も中身を見たい
        body = exc.read()
        return exc.code, (json.loads(body) if body else None)


def seed(data: Path, count: int = 8) -> list[str]:
    """**絵の違う 8 枚**を作って登録する（線 1 と 8 は「別々の画像」で測る。§7）。"""
    images = data / "images"
    images.mkdir(parents=True, exist_ok=True)
    store = Store(data)
    try:
        ids: list[str] = []
        for index in range(count):
            path = images / f"img{index}.png"
            image = Image.new("RGB", (256, 256), (20 + index * 25, 90, 200 - index * 20))
            for x in range(0, 256, 16):                    # 絵に模様を入れる（同じ絵にしない）
                for y in range(0, 256, 16):
                    if (x // 16 + y // 16 + index) % 3 == 0:
                        image.putpixel((x, y), (250, 250, 250))
            image.save(path)
            asset_id, _ = store.register(
                sha256=f"{index:02d}" * 32, path=str(path), size=path.stat().st_size,
                mtime_ns=1, width=256, height=256, fmt="png", meta=None, note=None)
            ids.append(asset_id)
        return ids
    finally:
        store.close()


def wait_job(base: str, job_id: str, timeout: float = 1800.0) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        _, got = call("GET", f"{base}/api/jobs/{job_id}")
        last = got
        if got["state"] not in ("queued", "running"):
            return got
        time.sleep(2.0)
    return last or {}


def words_of(base: str, asset_id: str, source: str | None = None) -> list[str]:
    _, got = call("GET", f"{base}/api/assets/{asset_id}/tags")
    return sorted(item["name"] for item in got["items"]
                  if source is None or source in item["sources"])


class InjectedGlossEngine:
    """**注入する偽の模型**（線 6。`§0.9` の 4 種の壊れ方を試す。**本物は呼ばない**）。"""

    def __init__(self, replies, engine: str = "injected"):
        self.replies = list(replies)
        self.calls: list[list[str]] = []
        self.engine = engine
        self.base = "http://127.0.0.1:1"

    def ping(self) -> bool:
        return True

    def translate(self, names):
        self.calls.append(list(names))
        return self.replies.pop(0) if self.replies else ""


def _gloss_count(store) -> int:
    with store.locked() as con:
        return con.execute("SELECT count(*) AS n FROM tag_gloss").fetchone()["n"]


def _make_words(store, prefix: str, count: int) -> list[int]:
    """注入の試験用に**新しい語**を作る（使い捨ての置き場なので直接入れてよい）。

    「語釈の無い語」を `pending` から拾うと、直前の節で全部訳してしまって 0 件になる
    （1 回目の実行でそうなった）。**自分で作れば必ず足りる**。
    """
    from image_reviewer import db as _db

    out: list[int] = []
    with store.transaction() as con:
        for index in range(1, count + 1):
            name = f"{prefix}_{index}"
            con.execute("INSERT INTO tag(name, category, category_name, known)"
                        " VALUES (?,0,'general',0) ON CONFLICT(name) DO NOTHING", (name,))
            row = con.execute("SELECT id FROM tag WHERE name = ?", (name,)).fetchone()
            out.append(int(row["id"]))
    assert _db is not None
    return out


def check_gloss(base: str, data: Path, human: dict) -> None:
    """線 4・5・6 を実機で出す（§1.2。**ComfyUI の `TextGenerate` を実際に回す**）。"""
    global OK
    print("\n4/5/6. 語釈（線 4・5・6）")

    # 語彙にある語を使う（既定 `known=1`。人が見て分かる語の方が確かめやすい）
    _, listed = call("GET", f"{base}/api/tags?limit=20")
    ids = [item["tag_id"] for item in listed["items"]][:20]
    if len(ids) < 5:
        OK = False
        print(f"  NG: 語が足りません（{len(ids)} 語）")
        return
    # 使い捨ての置き場なので、語釈を消してから始める（**1 枚も訳していない状態**）
    store = Store(data)
    try:
        with store.transaction() as con:
            con.execute("DELETE FROM tag_gloss")
    finally:
        store.close()

    began = time.monotonic()
    status, got = call("POST", f"{base}/api/tags/gloss", {"tag_ids": ids, "force": True})
    elapsed = time.monotonic() - began
    translated = got.get("translated") or []
    good = [item for item in translated if item.get("ja")]
    print(f"  POST /api/tags/gloss（{len(ids)} 語）→ {status}")
    print(f"  返った数 {len(good)} / {len(ids)}（番号が取れて日本語になった数。実測は 20/20）")
    for item in good[:6]:
        print(f"    {item['name']} → {item['ja']}")
    print(f"  calls={got.get('calls')} elapsed_ms={got.get('elapsed_ms')} "
          f"（外から見た時間 {elapsed:.1f} 秒。初回は模型の読み込み込み。§7 の実測は 4.6〜4.8 秒）")
    if status != 200 or len(good) != len(ids) or got.get("calls", 0) < 1:
        OK = False
        print("  NG: 20/20 が返っていない（線 4）")
    if got.get("untranslated"):
        print(f"  訳せなかった語: {[u['name'] for u in got['untranslated']]}")

    # ---- 線 4（後半）: 2 回目は模型を回さない（点検 B-3）----
    _, again = call("POST", f"{base}/api/tags/gloss", {"tag_ids": ids})
    print(f"  2 回目（既定 `force=false`）→ calls={again.get('calls')}（**0 が正**）"
          f" skipped={len(again.get('skipped') or [])}")
    if again.get("calls") != 0 or len(again.get("skipped") or []) != len(ids):
        OK = False

    # ---- 線 5: 人が直したら守られる ----
    one = ids[0]
    edited_text = "人の手で直した語釈"
    added = call("POST", f"{base}/api/tags/{one}/gloss", {"ja": edited_text}, human)
    agent = call("POST", f"{base}/api/tags/{one}/gloss", {"ja": "x"})[0]
    _, forced = call("POST", f"{base}/api/tags/gloss", {"tag_ids": [one], "force": True})
    _, lookup = call("GET", f"{base}/api/tags/{one}/gloss")
    print(f"  人が直す → {added[0]} / エージェント {agent}（403）/ force で訳し直す →"
          f" calls={forced.get('calls')}（0）skipped={len(forced.get('skipped') or [])}")
    print(f"  いまの値 {lookup.get('ja')!r} edited={lookup.get('edited')}"
          f"（人が直した値のまま・edited=true が正）")
    if (added[0] != 200 or agent != 403 or lookup.get("ja") != edited_text
            or not lookup.get("edited")):
        OK = False

    # ---- `GET /api/tags/gloss/pending`（数えるだけ）----
    _, pend = call("GET", f"{base}/api/tags/gloss/pending?limit=5")
    print(f"  語釈の無い語: {pend['count']} 語（例 {[s['name'] for s in pend['sample']]}）")
    if not isinstance(pend.get("count"), int):
        OK = False

    # ---- 線 6: 注入 4 種（番号の無い行 / 番号の重複 / 英語のまま / 空の応答）----
    print("  線 6: 壊れた応答を注入（**誤った行を 1 つも保存しない**）")
    store = Store(data)
    try:
        four = _make_words(store, "inject", 4)
        before = _gloss_count(store)
        engine = InjectedGlossEngine([
            "番号の無い行です\n1. 語1",        # 番号の無い行は捨てる（1 だけ取れる）
            "1. long_hair",                    # **英語のまま** → 保存しない
            "1. 語3",                          # 取れる
            "",                                # **空の応答**
        ])
        svc = GlossService(store, engine_factory=lambda settings: engine)
        inj = svc.translate(tag_ids=four, force=True)
        after = _gloss_count(store)
        saved = sorted(item["ja"] for item in inj["translated"])
        lost = [item["name"] for item in inj["untranslated"]]
        print(f"    4 語 → 保存 {saved} / 保存しなかった {lost} / tag_gloss {before} → {after}")
        if after - before != 2 or len(lost) != 2 or "long_hair" in saved:
            OK = False

        # 番号の重複 → その番号は捨てる（1 語ずつも失敗させて、行が入らないことを見る）
        dup = _make_words(store, "inject_dup", 1)
        if dup:
            before = _gloss_count(store)
            engine = InjectedGlossEngine(["1. 一つ目\n1. 二つ目", ""])
            svc = GlossService(store, engine_factory=lambda settings: engine)
            inj = svc.translate(tag_ids=dup, force=True)
            after = _gloss_count(store)
            print(f"    番号の重複 1 語 → 保存 {len(inj['translated'])}（0 が正）"
                  f" / tag_gloss {before} → {after}（増えないが正）")
            if inj["translated"] or after != before:
                OK = False
    finally:
        store.close()


def main() -> int:
    global OK
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=f"http://127.0.0.1:{PORT}")
    parser.add_argument("--data", default=str(BASE / "data"))
    parser.add_argument("--engine", default="comfyui", choices=["comfyui", "builtin", "both", "auto"])
    parser.add_argument("--gloss", action="store_true",
                        help="P4-2 の語釈を実機で出す（線 4・5・6。TextGenerate を回す）")
    parser.add_argument("--keep", action="store_true", help="使い捨ての置き場を残す")
    parser.add_argument("--no-server", action="store_true", help="既に立っているサーバを使う")
    args = parser.parse_args()

    data = Path(args.data)
    if not args.no_server and data.exists():
        shutil.rmtree(data, ignore_errors=True)
    base = args.base.rstrip("/")
    print(f"engine={args.engine} data={data} base={base}")

    proc = None
    if not args.no_server:
        ids = seed(data)
        print(f"8 枚を用意した: {ids[0]} …")
        env = {**os.environ, "IMAGE_REVIEWER_DATA": str(data), "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "image_reviewer.app:app", "--host", "127.0.0.1",
             "--port", str(PORT), "--log-level", "warning"], env=env, cwd=str(ROOT))
        for _ in range(40):
            try:
                if call("GET", f"{base}/api/health")[0] == 200:
                    break
            except Exception:                              # noqa: BLE001
                pass
            time.sleep(1.0)
        else:
            print("サーバが立ちません")
            return 1
    else:
        _, stats = call("GET", f"{base}/api/stats")
        print("既存のサーバを使う:", stats)

    try:
        _, assets = call("GET", f"{base}/api/assets?limit=50")
        ids = [item["id"] for item in assets["items"]][:8]
        print(f"対象: {len(ids)} 枚")

        # ---- 線 1: 未タグの画像に語が付く ----
        print("\n1. 未タグの画像に語が付く（線 1）")
        first_engine = "comfyui" if args.engine == "both" else args.engine
        # **1 枚あたりの時間を測る**（P4-1 の監査 C-1。`/history` のポーリング間隔を詰めた効果を見る）
        began = time.monotonic()
        status, got = call("POST", f"{base}/api/assets/tag",
                           {"asset_ids": ids, "engine": first_engine, "sources": ["png", "wd14"]})
        print(f"  POST /api/assets/tag → {status} {got}")
        if status != 202:
            OK = False
        result = wait_job(base, got["job_id"])
        elapsed = time.monotonic() - began
        tagged = result["counts"]["tagged"]
        print(f"  job {result['state']} / tagged={tagged} / failed={result['counts']['failed']}"
              f" / {result['message']}")
        print(f"  1 枚あたり {elapsed / max(1, len(ids)):.2f} 秒（{elapsed:.1f} 秒 / {len(ids)} 枚。"
              "点検 C-1 の実測は 0.72 秒/枚だった）")
        counts = [len(words_of(base, one, "wd14")) for one in ids]
        print(f"  wd14 の語数: {counts}")
        if result["state"] != "done" or min(counts) < 1:
            OK = False
            print("  NG: 語が付いていない画像がある（8/8 に 1 語以上が線 1）")

        # ---- 線 2: 出所が混ざらない ----
        print("\n2. 出所が混ざらない（線 2）")
        one = ids[0]
        _, tag_list = call("GET", f"{base}/api/tags?limit=5&known=all")
        name = tag_list["items"][0]["name"]
        human = {"X-Image-Reviewer-Actor": "human"}
        status, added = call("POST", f"{base}/api/assets/{one}/tags", {"name": name}, human)
        png_words = words_of(base, one, "png")
        wd14_words = words_of(base, one, "wd14")
        manual_words = words_of(base, one, "manual")
        print(f"  manual に {name} を追加 → {status}（added={added.get('added')}）")
        print(f"  png={len(png_words)} wd14={len(wd14_words)} manual={manual_words}")
        if status != 200 or manual_words != [name]:
            OK = False

        # ---- 線 7: 冪等と人だけ ----
        print("\n7. 手動の付け外し（線 7）")
        again = call("POST", f"{base}/api/assets/{one}/tags", {"name": name}, human)[1]
        agent = call("POST", f"{base}/api/assets/{one}/tags", {"name": name})[0]
        _, listed = call("GET", f"{base}/api/assets/{one}/tags")
        manual_rows = [i for i in listed["items"] if "manual" in i["sources"]]
        removed = call("DELETE", f"{base}/api/assets/{one}/tags/{tag_list['items'][0]['tag_id']}",
                       None, human)[0]
        twice = call("DELETE", f"{base}/api/assets/{one}/tags/{tag_list['items'][0]['tag_id']}",
                     None, human)[0]
        print(f"  2 回目の追加 added={again.get('added')}（False が正）/ エージェント {agent}（403）"
              f" / manual の行 {len(manual_rows)}（1）/ 外す {removed}（200）/ 2 回目 {twice}（404）")
        if again.get("added") is not False or agent != 403 or len(manual_rows) != 1 \
                or removed != 200 or twice != 404:
            OK = False

        # ---- 線 4・5・6: 語釈（`--gloss`）----
        if args.gloss:
            check_gloss(base, data, human)

        # ---- 線 8: 内蔵と ComfyUI の語の集合 ----
        if args.engine in ("both", "builtin"):
            print("\n8. 内蔵と ComfyUI の語の集合（線 8）")
            shutil.rmtree(data, ignore_errors=True)
            ids = seed(data)
            store = Store(data)
            try:
                # 内蔵で付ける（既存の行を消してから）
                for one in ids:
                    with store.transaction() as con:
                        con.execute("DELETE FROM asset_tag WHERE asset_id = ? AND source='wd14'", (one,))
            finally:
                store.close()
            builtin_job = call("POST", f"{base}/api/assets/tag",
                               {"asset_ids": ids, "engine": "builtin", "sources": ["wd14"]})
            print(f"  builtin → {builtin_job[0]} {builtin_job[1]}")
            if builtin_job[0] != 202:
                OK = False
                print("  NG: 内蔵が使えない（onnxruntime 未導入。§0.4・Q4）")
            else:
                got_builtin = {one: set(words_of(base, one, "wd14")) for one in ids}
                comfy = call("POST", f"{base}/api/assets/tag",
                             {"asset_ids": ids, "engine": "comfyui", "sources": ["wd14"],
                              "force": True})
                wait_job(base, comfy[1]["job_id"])
                same = 0
                for one in ids:
                    comfy_words = set(words_of(base, one, "wd14"))
                    if comfy_words == got_builtin[one]:
                        same += 1
                    else:
                        print(f"    差: {one} 内蔵 {len(got_builtin[one])} 語 / ComfyUI"
                              f" {len(comfy_words)} 語 だけ={sorted(comfy_words ^ got_builtin[one])[:6]}")
                print(f"  一致 {same} / {len(ids)}")
                if same != len(ids):
                    OK = False
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        if not args.keep and not args.no_server:
            # **自分の置き場は自分で消す**（スキルの §4）。Windows はサーバを止めた直後に
            # SQLite のファイルを握っていることがあるので、数回試す（1 回目で諦めると
            # `p4/data` が残る。実際に残った）
            for attempt in range(5):
                shutil.rmtree(data, ignore_errors=True)
                if not data.exists():
                    break
                time.sleep(0.5)
            if data.exists():
                print(f"  （使い捨ての置き場が消えませんでした: {data}。--keep と同じ状態）")

    print("\n" + "=" * 74)
    print("まとめ: " + ("すべて OK" if OK else "NG あり（上の NG を見る）"))
    return 0 if OK else 1


if __name__ == "__main__":
    raise SystemExit(main())
