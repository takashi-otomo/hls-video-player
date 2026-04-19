"""MP4 → HLS (ABR) 変換。

パフォーマンス最適化:
- `-filter_complex split=N` で **デコードを 1 回に抑え**、N 本のバリアントへ分岐させる
- `FFMPEG_HWACCEL=auto` なら NVENC (h264_nvenc) を自動選択。CPU 比で 10-30x 高速
- `FFMPEG_VARIANTS="720p,360p"` でラダーを絞れる
- `-threads 0` (auto) 既定

品質設定:
- CPU: `-preset <ultrafast|...>` + CRF
- NVENC: `-preset p1..p7` + `-rc vbr -cq`
- HLS の GOP/セグメント整合: `-g`/`-keyint_min` = segment_seconds × fps、`-sc_threshold 0`
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Literal, Optional, TypedDict

from hls_video.config import (
    ffmpeg_hwaccel,
    ffmpeg_nvenc_preset,
    ffmpeg_path,
    ffmpeg_preset,
    ffmpeg_threads,
    ffmpeg_variants_filter,
)
from hls_video.ffmpeg_runner import run_ffmpeg
from hls_video.hwaccel import Backend, resolve_hwaccel
from hls_video.master_playlist import build_master_playlist
from hls_video.progress_parser import create_progress_parser

logger = logging.getLogger(__name__)


class Variant(TypedDict):
    name: str
    height: int
    video_bitrate: str
    maxrate: str
    bufsize: str
    audio_bitrate: str
    crf: int
    resolution: str
    bandwidth: int


DEFAULT_VARIANTS: list[Variant] = [
    {
        "name": "720p", "height": 720,
        "video_bitrate": "3000k", "maxrate": "3600k", "bufsize": "6000k",
        "audio_bitrate": "128k", "crf": 26,
        "resolution": "1280x720", "bandwidth": 3000000,
    },
    {
        "name": "480p", "height": 480,
        "video_bitrate": "1500k", "maxrate": "1800k", "bufsize": "3000k",
        "audio_bitrate": "128k", "crf": 28,
        "resolution": "854x480", "bandwidth": 1500000,
    },
    {
        "name": "360p", "height": 360,
        "video_bitrate": "800k", "maxrate": "960k", "bufsize": "1600k",
        "audio_bitrate": "96k", "crf": 30,
        "resolution": "640x360", "bandwidth": 800000,
    },
    {
        "name": "240p", "height": 240,
        "video_bitrate": "400k", "maxrate": "480k", "bufsize": "800k",
        "audio_bitrate": "64k", "crf": 32,
        "resolution": "426x240", "bandwidth": 400000,
    },
]


def _filter_complex_split(variants: list[Variant], *, portrait: bool = False) -> str:
    """1 decode → N scale への split チェーンを組む。

    `[0:v]split=N[v0][v1]...; [v0]scale=...[vo0]; [v1]scale=...[vo1]; ...`

    縦動画 (portrait=True) では scale の w/h を入れ替え、variant.height を
    **短辺** として扱う。これにより 240p の縦動画が 135x240 ではなく 240x426 に
    なり、NVENC の最小解像度制約 (≥145px) を満たせる。
    """
    n = len(variants)
    labels = "".join(f"[v{i}]" for i in range(n))
    parts = [f"[0:v]split={n}{labels}"]
    for i, v in enumerate(variants):
        short_edge = v["height"]
        if portrait:
            # 縦動画: 横幅 (短辺) を short_edge に合わせる
            scale = (
                f"scale=w={short_edge}:h=-2:"
                f"force_original_aspect_ratio=decrease:force_divisible_by=2"
            )
        else:
            # 横動画: 従来通り高さを short_edge に合わせる
            scale = (
                f"scale=w=-2:h={short_edge}:"
                f"force_original_aspect_ratio=decrease:force_divisible_by=2"
            )
        parts.append(f"[v{i}]{scale}[vo{i}]")
    return ";".join(parts)


def _cpu_variant_output_args(
    variant: Variant,
    *,
    out_dir: str,
    map_label: str,
    segment_seconds: int,
    gop: int,
    preset: str,
    threads: int,
) -> list[str]:
    """CPU (libx264) の 1 variant 分 -map + エンコーダ引数。"""
    playlist = os.path.join(out_dir, f"{variant['name']}.m3u8")
    seg_pattern = os.path.join(out_dir, f"{variant['name']}_%03d.ts")
    return [
        "-map", map_label,
        "-map", "0:a:0?",
        "-c:a", "aac", "-ar", "48000", "-b:a", variant["audio_bitrate"],
        "-c:v", "h264", "-profile:v", "main",
        "-preset", preset,
        "-threads", str(threads),
        "-crf", str(variant["crf"]),
        "-pix_fmt", "yuv420p",
        "-sc_threshold", "0",
        "-g", str(gop), "-keyint_min", str(gop),
        "-b:v", variant["video_bitrate"],
        "-maxrate", variant["maxrate"],
        "-bufsize", variant["bufsize"],
        "-hls_time", str(segment_seconds),
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", seg_pattern,
        "-f", "hls", playlist,
    ]


def _nvenc_variant_output_args(
    variant: Variant,
    *,
    out_dir: str,
    map_label: str,
    segment_seconds: int,
    gop: int,
    preset: str,
) -> list[str]:
    """NVENC (h264_nvenc) の 1 variant 分。

    NVENC は -crf ではなく -rc vbr + -cq で品質目標を指定する。libx264 の CRF を
    近い体感画質にマップ: CRF そのまま CQ に使うと libx264 よりやや低画質側に寄るが、
    HLS 配信品質としては十分許容範囲。
    """
    playlist = os.path.join(out_dir, f"{variant['name']}.m3u8")
    seg_pattern = os.path.join(out_dir, f"{variant['name']}_%03d.ts")
    return [
        "-map", map_label,
        "-map", "0:a:0?",
        "-c:a", "aac", "-ar", "48000", "-b:a", variant["audio_bitrate"],
        "-c:v", "h264_nvenc",
        "-profile:v", "main",
        "-preset", preset,
        "-rc", "vbr",
        "-cq", str(variant["crf"]),
        "-b:v", variant["video_bitrate"],
        "-maxrate", variant["maxrate"],
        "-bufsize", variant["bufsize"],
        "-pix_fmt", "yuv420p",
        "-g", str(gop), "-keyint_min", str(gop),
        "-hls_time", str(segment_seconds),
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", seg_pattern,
        "-f", "hls", playlist,
    ]


def build_ffmpeg_args(
    *,
    input_path: str,
    output_dir: str,
    variants: list[Variant],
    segment_seconds: int,
    gop: int,
    backend: Backend,
    preset: str,
    threads: int,
    nvenc_preset: str,
    portrait: bool = False,
) -> list[str]:
    """フル ffmpeg 引数を組み立てる。

    NVENC / CPU の分岐と filter_complex split をここに集約。テストはこの関数で。
    portrait=True で縦動画向けに scale 式の w/h を入れ替える。
    """
    filter_complex = _filter_complex_split(variants, portrait=portrait)
    args: list[str] = ["-y", "-i", input_path, "-filter_complex", filter_complex]
    for i, v in enumerate(variants):
        label = f"[vo{i}]"
        if backend == "nvenc":
            args.extend(_nvenc_variant_output_args(
                v, out_dir=output_dir, map_label=label,
                segment_seconds=segment_seconds, gop=gop, preset=nvenc_preset,
            ))
        else:
            args.extend(_cpu_variant_output_args(
                v, out_dir=output_dir, map_label=label,
                segment_seconds=segment_seconds, gop=gop,
                preset=preset, threads=threads,
            ))
    return args


def convert_mp4_to_hls(
    *,
    input_path: str,
    output_dir: str,
    variants: Optional[list[Variant]] = None,
    segment_seconds: int = 4,
    fps: int = 24,
    preset: Optional[str] = None,
    threads: Optional[int] = None,
    duration_seconds: Optional[float] = None,
    on_progress: Optional[Callable[[float, dict], None]] = None,
    hwaccel: Optional[str] = None,
    nvenc_preset: Optional[str] = None,
    input_width: Optional[int] = None,
    input_height: Optional[int] = None,
) -> dict:
    selected = variants or DEFAULT_VARIANTS

    # 環境変数で絞り込み
    names_filter = ffmpeg_variants_filter()
    if names_filter:
        filtered = [v for v in selected if v["name"] in names_filter]
        if filtered:
            selected = filtered
        else:
            logger.warning(
                "FFMPEG_VARIANTS=%s does not match any variant; using full ladder",
                names_filter,
            )

    backend: Backend = resolve_hwaccel(hwaccel or ffmpeg_hwaccel(), ffmpeg_path())
    preset_ = preset or ffmpeg_preset()
    nvenc_preset_ = nvenc_preset or ffmpeg_nvenc_preset()
    threads_ = threads if threads is not None else ffmpeg_threads()

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    gop = max(2, round(segment_seconds * fps))

    # orientation 判定: 縦動画（height > width）のとき portrait=True。
    # 0/None の場合は landscape 扱い（既存挙動）。
    portrait = bool(
        input_width and input_height and int(input_height) > int(input_width)
    )

    logger.info(
        "HLS encode: backend=%s variants=%s preset=%s nvenc_preset=%s "
        "threads=%d gop=%d portrait=%s (in=%sx%s)",
        backend, [v["name"] for v in selected], preset_, nvenc_preset_,
        threads_, gop, portrait, input_width, input_height,
    )

    args = build_ffmpeg_args(
        input_path=input_path, output_dir=str(out), variants=selected,
        segment_seconds=segment_seconds, gop=gop, backend=backend,
        preset=preset_, threads=threads_, nvenc_preset=nvenc_preset_,
        portrait=portrait,
    )

    stderr_handler = (
        create_progress_parser(duration_seconds=duration_seconds, on_ratio=on_progress)
        if on_progress is not None
        else None
    )
    run_ffmpeg(args, on_progress=stderr_handler, label=f"hls:{Path(output_dir).name}")

    master = build_master_playlist([
        {"bandwidth": v["bandwidth"], "resolution": v["resolution"],
         "playlist": f"{v['name']}.m3u8"}
        for v in selected
    ])
    (out / "master.m3u8").write_text(master)

    return {
        "master_path": str(out / "master.m3u8"),
        "variants": [v["name"] for v in selected],
        "backend": backend,
    }
