"""MP4 → HLS (4 解像度 ABR) 変換。

Node 側 utils/hlsConverter.js と同等:
- scale filter + pad + libx264 main profile
- `-sc_threshold 0` + 固定 GOP でバリアント間キーフレーム整合
- `-pix_fmt yuv420p` 強制（4:4:4 ソース対策）
- `-preset` / `-threads` は CPU 抑制用の変数
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional, TypedDict

from hls_video.config import ffmpeg_preset, ffmpeg_threads
from hls_video.ffmpeg_runner import run_ffmpeg
from hls_video.master_playlist import build_master_playlist
from hls_video.progress_parser import create_progress_parser


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


def build_variant_args(
    variant: Variant,
    *,
    out_dir: str,
    segment_seconds: int,
    gop: int,
    preset: str,
    threads: int,
) -> list[str]:
    scale = (
        f"scale=w=-2:h={variant['height']}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    )
    playlist = os.path.join(out_dir, f"{variant['name']}.m3u8")
    seg_pattern = os.path.join(out_dir, f"{variant['name']}_%03d.ts")
    return [
        "-vf", scale,
        "-c:a", "aac", "-ar", "48000", "-b:a", variant["audio_bitrate"],
        "-c:v", "h264", "-profile:v", "main",
        "-preset", preset,
        "-threads", str(threads),
        "-crf", str(variant["crf"]),
        "-pix_fmt", "yuv420p",
        "-sc_threshold", "0",
        "-g", str(gop), "-keyint_min", str(gop),
        "-hls_time", str(segment_seconds),
        "-hls_playlist_type", "vod",
        "-b:v", variant["video_bitrate"],
        "-maxrate", variant["maxrate"],
        "-bufsize", variant["bufsize"],
        "-hls_segment_filename", seg_pattern,
        "-f", "hls", playlist,
    ]


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
) -> dict:
    variants = variants or DEFAULT_VARIANTS
    preset_ = preset or ffmpeg_preset()
    threads_ = threads if threads is not None else ffmpeg_threads()

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # GOP を segment_seconds × fps の 2 倍に合わせる（Node 版と同じ算出）
    gop = max(2, round(segment_seconds * fps))

    args = ["-y", "-i", input_path]
    for v in variants:
        args.extend(build_variant_args(
            v, out_dir=str(out), segment_seconds=segment_seconds, gop=gop,
            preset=preset_, threads=threads_,
        ))

    stderr_handler = (
        create_progress_parser(duration_seconds=duration_seconds, on_ratio=on_progress)
        if on_progress is not None
        else None
    )
    run_ffmpeg(args, on_progress=stderr_handler)

    master = build_master_playlist([
        {"bandwidth": v["bandwidth"], "resolution": v["resolution"], "playlist": f"{v['name']}.m3u8"}
        for v in variants
    ])
    (out / "master.m3u8").write_text(master)

    return {"master_path": str(out / "master.m3u8"), "variants": [v["name"] for v in variants]}
