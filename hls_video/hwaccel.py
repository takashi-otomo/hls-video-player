"""FFmpeg のハードウェアアクセラレーション可用性判定。

`ffmpeg -encoders` の出力に `h264_nvenc` が含まれるかをキャッシュ付きで調べる。
環境変数 FFMPEG_HWACCEL=cpu/nvenc/auto と組み合わせて最終バックエンドを決定する。
"""

from __future__ import annotations

import functools
import logging
import subprocess
import time
from typing import Literal

logger = logging.getLogger(__name__)

Backend = Literal["nvenc", "cpu"]


@functools.lru_cache(maxsize=8)
def detect_nvenc(ffmpeg_path: str = "ffmpeg") -> bool:
    """`ffmpeg -hide_banner -encoders` の出力に h264_nvenc が含まれるかで判定。

    ffmpeg 起動だけで数百ms掛かるので lru_cache で実行毎に1回に抑える。
    """
    t0 = time.monotonic()
    try:
        out = subprocess.check_output(
            [ffmpeg_path, "-hide_banner", "-encoders"],
            stderr=subprocess.STDOUT,
            timeout=10,
        ).decode(errors="ignore")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning("NVENC detection failed (%s): %s", ffmpeg_path, e)
        return False
    found = "h264_nvenc" in out
    logger.info(
        "NVENC detection: %s (ffmpeg=%s elapsed=%.2fs)",
        "available" if found else "unavailable",
        ffmpeg_path, time.monotonic() - t0,
    )
    return found


def resolve_hwaccel(mode: str, ffmpeg_path: str = "ffmpeg") -> Backend:
    """ユーザー指定 (`auto`/`nvenc`/`cpu`) を実際のバックエンド ("nvenc"/"cpu") に解決する。

    - `cpu`: 強制 CPU (libx264)
    - `nvenc`: 強制 NVENC（ffmpeg にビルドされていない環境だと実行時に失敗するので注意）
    - `auto`: NVENC 使えれば NVENC、ダメなら CPU にフォールバック
    """
    m = (mode or "auto").lower()
    if m == "cpu":
        return "cpu"
    if m == "nvenc":
        return "nvenc"
    return "nvenc" if detect_nvenc(ffmpeg_path) else "cpu"
