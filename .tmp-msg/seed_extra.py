"""`gui_layout --screen pending` の前提を**複製にだけ**足す（使い捨て。`.tmp-msg/`）。

利用者の実データは 194 行すべてが片付け済み（`closed_at`）になったので、素の複製では
「最近の削除」に**選べる行**が 1 つも無く、まとめての帯が出ない（検査の前提が崩れる）。
実データの 187 行がそうだった形（**ファイルが無い段 1 の行**）を 1 つ作る。
**ファイルは 1 つも作らない・動かさない**（存在しないパスを登録するだけ）。
"""

import hashlib
from pathlib import Path

from image_reviewer.deletions import DeletionService
from image_reviewer.store import Store

DATA = Path(r"C:\work\image-reviwer\.tmp-msg\replica")
MISSING = Path(r"C:\work\illust-authoring\.store\anima-dev\images\__layout-gone-1.png")

store = Store(DATA)
try:
    svc = DeletionService(store)
    assert not MISSING.exists(), f"前提が違う（実在する）: {MISSING}"
    digest = hashlib.sha256(b"layout-seed-missing-1").hexdigest()
    asset_id, _ = store.register(sha256=digest, path=str(MISSING), size=1234, mtime_ns=5678,
                                 width=16, height=16, fmt="png", meta=None, note=None)
    got = svc.delete(asset_id=asset_id, path=str(MISSING), stage=1, actor="human")
    print("足した段 1 の行:", got["deletion_id"], "asset:", got["asset_id"])
    print("まだ戻せる行:", svc.pending(actor="human")["count"])
finally:
    store.close()
