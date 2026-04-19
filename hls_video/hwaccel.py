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


@functools.lru_cache(maxsize=1)
def detect_cuda_runtime() -> bool:
    """CUDA ドライバ (libcuda) が実行時にロード可能か確認する。

    `ffmpeg -encoders` には `h264_nvenc` があっても、Colab で CPU ランタイムを
    選んでいたり GPU が使えない環境だと実行時に `Cannot load libcuda.so.1` で
    落ちる。このため「バイナリに含まれている」ではなく **nvidia-smi で
    実際の GPU を確認** することで確実に判定する。
    """
    t0 = time.monotonic()
    try:
        subprocess.check_output(
            ["nvidia-smi", "-L"],
            stderr=subprocess.STDOUT, timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.info(
            "CUDA runtime unavailable (no GPU / driver): %s", e.__class__.__name__,
        )
        return False
    logger.info(
        "CUDA runtime available (elapsed=%.2fs)", time.monotonic() - t0,
    )
    return True


@functools.lru_cache(maxsize=8)
def detect_nvenc(ffmpeg_path: str = "ffmpeg") -> bool:
    """NVENC encoder (`h264_nvenc`) がビルドに含まれ、かつ CUDA runtime も使えるか判定。

    以前はビルド有無だけ見ていたが、Colab CPU ランタイムなど libcuda を
    ロードできない環境では ffmpeg 実行時に落ちるため、`detect_cuda_runtime()`
    を併せてチェックする。
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
    built_in = "h264_nvenc" in out
    if not built_in:
        logger.info("NVENC: binary does not include h264_nvenc")
        return False
    runtime = detect_cuda_runtime()
    logger.info(
        "NVENC detection: binary=yes runtime=%s (ffmpeg=%s elapsed=%.2fs)",
        runtime, ffmpeg_path, time.monotonic() - t0,
    )
    return runtime


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

    例: "h264" → "h264_cuvid"（ffmpeg に decoder が含まれ、かつ CUDA runtime
    が実際に利用可能な場合のみ）。CPU ランタイムで libcuda が無い環境では
    実行時に落ちるのでここで弾く。
    """
    if not input_codec:
        return None
    cuvid = CUVID_DECODERS.get(input_codec.lower())
    if not cuvid:
        return None
    decoders = _list_decoders(ffmpeg_path)
    if cuvid not in decoders:
        return None
    if not detect_cuda_runtime():
        return None
    return cuvid


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
