"""アプリ全体のロガーを一度だけ設定するユーティリティ。

Colab での可視性のため:
- stdout への StreamHandler (ノートブック起動セルの実行中に見える)
- ファイルへの FileHandler (`/tmp/hls-video.log` 既定、LOG_FILE env で上書き可)
  → ノートブック上で `!tail -f /tmp/hls-video.log` するとリアルタイムに読める。

再起動セル (section 7) で複数回呼ばれてもハンドラが重複しないようガード。
LOG_LEVEL env で閾値を変更可能（既定 INFO）。
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def setup_logging(level: str | int | None = None) -> str:
    """ロガーを初期化する。戻り値はログファイルパス（既に設定済みなら既存を返す）。"""
    root = logging.getLogger()
    existing_tag = any(getattr(h, "_hls_video_tag", False) for h in root.handlers)

    resolved = level or os.environ.get("LOG_LEVEL", "INFO")
    if isinstance(resolved, str):
        resolved = logging.getLevelName(resolved.upper())

    log_file = os.environ.get("LOG_FILE", "/tmp/hls-video.log")

    if existing_tag:
        return log_file

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # stdout (ノートブックのセル実行中は cell output に出る)
    stream_h = logging.StreamHandler(sys.stdout)
    stream_h.setFormatter(fmt)
    stream_h._hls_video_tag = True  # type: ignore[attr-defined]
    root.addHandler(stream_h)

    # ファイル (バックグラウンドスレッドの出力もここには残る)
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_h = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_h.setFormatter(fmt)
        file_h._hls_video_tag = True  # type: ignore[attr-defined]
        root.addHandler(file_h)
    except OSError:
        # ファイルが書けない環境でも stdout ハンドラは残るので無視
        pass

    root.setLevel(resolved)

    for noisy in ("httpcore", "httpx", "multipart", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info("logging initialized → %s (level=%s)",
                                     log_file, logging.getLevelName(resolved))
    return log_file
