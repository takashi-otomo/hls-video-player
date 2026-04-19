"""アプリ全体のロガーを一度だけ設定するユーティリティ。

Colab のノートブックセル出力に見えるように stderr ではなく stdout を使う。
再起動セル (section 7) で複数回呼ばれてもハンドラが重複しないようガードする。

環境変数 LOG_LEVEL で閾値を変更可能（既定: INFO）。
"""

from __future__ import annotations

import logging
import os
import sys


def setup_logging(level: str | int | None = None) -> None:
    root = logging.getLogger()
    if any(getattr(h, "_hls_video_tag", False) for h in root.handlers):
        return  # 既にセットアップ済（再起動時）

    resolved = level or os.environ.get("LOG_LEVEL", "INFO")
    if isinstance(resolved, str):
        resolved = logging.getLevelName(resolved.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    handler._hls_video_tag = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    root.setLevel(resolved)

    # uvicorn / fastapi の default ロガーと二重に出ないよう propagate は維持
    # ただし httpcore などのノイズの多いライブラリは WARNING に抑える
    for noisy in ("httpcore", "httpx", "multipart", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
