"""FFmpeg のハードウェアアクセラレーション可用性判定。

- NVENC encoder (`h264_nvenc`) の検出
- CUVID decoder (`h264_cuvid` / `hevc_cuvid` / ...) の検出
いずれも `ffmpeg -encoders` / `-decoders` をキャッシュ付きで調べる。

環境変数 FFMPEG_HWACCEL / FFMPEG_CUVID と組み合わせて最終バックエンドを決定する。
"""

from __future__ import annotations

import functools
import logging
import subprocess
import time
from typing import Literal, Optional

logger = logging.getLogger(__name__)

Backend = Literal["nvenc", "cpu"]


# 入力 codec_name → CUVID decoder 名のマッピング
# ffprobe の codec_name に揃える（例: HEVC は ffprobe 上 "hevc"、decoder は hevc_cuvid）
CUVID_DECODERS: dict[str, str] = {
    "h264": "h264_cuvid",
    "hevc": "hevc_cuvid",
    "h265": "hevc_cuvid",        # エイリアス
    "vp9": "vp9_cuvid",
    "vp8": "vp8_cuvid",
    "av1": "av1_cuvid",
    "mpeg2video": "mpeg2_cuvid",
    "mpeg4": "mpeg4_cuvid",
    "vc1": "vc1_cuvid",
}


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


@functools.lru_cache(maxsize=8)
def _list_decoders(ffmpeg_path: str = "ffmpeg") -> str:
    """`ffmpeg -hide_banner -decoders` のテキスト出力（キャッシュ付き）。"""
    try:
        return subprocess.check_output(
            [ffmpeg_path, "-hide_banner", "-decoders"],
            stderr=subprocess.STDOUT, timeout=10,
        ).decode(errors="ignore")
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.warning("decoders listing failed (%s): %s", ffmpeg_path, e)
        return ""


def detect_cuvid(input_codec: str, ffmpeg_path: str = "ffmpeg") -> Optional[str]:
    """input 側 codec_name に対応する cuvid decoder 名を返す。無ければ None。

    例: "h264" → "h264_cuvid"（ffmpeg の decoders リストに含まれる場合のみ）
    """
    if not input_codec:
        return None
    cuvid = CUVID_DECODERS.get(input_codec.lower())
    if not cuvid:
        return None
    decoders = _list_decoders(ffmpeg_path)
    return cuvid if cuvid in decoders else None


def resolve_cuvid(
    mode: str, input_codec: str, ffmpeg_path: str = "ffmpeg",
) -> Optional[str]:
    """CUVID decoder 名を返す。使わない場合 None。

    - mode="off": 必ず None (CPU decode)
    - mode="on" / "auto": 入力 codec に対応する cuvid があれば返す、なければ None
      （on 指定時は検出失敗を警告ログに残す）
    """
    m = (mode or "auto").lower()
    if m == "off":
        return None
    decoder = detect_cuvid(input_codec, ffmpeg_path)
    if decoder is None and m == "on":
        logger.warning(
            "FFMPEG_CUVID=on but no cuvid decoder for codec=%r; falling back to CPU decode",
            input_codec,
        )
    return decoder
