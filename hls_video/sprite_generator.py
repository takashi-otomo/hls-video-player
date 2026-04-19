"""スプライト画像 + WebVTT + メタ JSON の生成。

Node 側 utils/spriteGenerator.js と同等:
- FFmpeg `tile` フィルタで columns × rows のグリッド画像を生成
- タイル数が 1 sheet に収まらない場合は image2 出力で `<id>-1.jpg`, `<id>-2.jpg` …
- 生成後に .vtt と .json を書き出す
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Callable, Optional

from hls_video.config import ffmpeg_threads
from hls_video.ffmpeg_runner import probe_duration_seconds, run_ffmpeg
from hls_video.progress_parser import create_progress_parser
from hls_video.vtt_builder import generate_vtt_content


def compute_sprite_layout(
    *, duration: float, interval: int, columns: int, rows: int
) -> dict:
    tile_count = max(1, math.ceil(duration / interval))
    tiles_per_sheet = columns * rows
    sheet_count = math.ceil(tile_count / tiles_per_sheet)
    return {
        "tile_count": tile_count,
        "sheet_count": sheet_count,
    }


def build_sprite_args(
    *,
    input_path: str,
    output_dir: str,
    video_id: str,
    interval: int,
    tile_width: int,
    tile_height: int,
    columns: int,
    rows: int,
    sheet_count: int,
    threads: int,
) -> list[str]:
    if sheet_count <= 1:
        sprite_name = f"{video_id}.jpg"
    else:
        sprite_name = f"{video_id}-%d.jpg"
    sprite_path = os.path.join(output_dir, sprite_name)

    vf = (
        f"fps=1/{interval},"
        f"scale={tile_width}:{tile_height}:force_original_aspect_ratio=decrease,"
        f"pad={tile_width}:{tile_height}:(ow-iw)/2:(oh-ih)/2,"
        f"tile={columns}x{rows}"
    )
    args = [
        "-y",
        "-threads", str(threads),
        "-i", input_path,
        "-vf", vf,
        "-an",
        "-vsync", "vfr",
        "-qscale:v", "4",
    ]
    if sheet_count > 1:
        args.extend(["-f", "image2"])
    args.append(sprite_path)
    return args


def generate_sprite(
    *,
    input_path: str,
    output_dir: str,
    video_id: str,
    interval_seconds: int = 10,
    tile_width: int = 160,
    tile_height: int = 90,
    columns: int = 10,
    rows: int = 10,
    duration_seconds: Optional[float] = None,
    on_progress: Optional[Callable[[float, dict], None]] = None,
) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    duration = duration_seconds if duration_seconds else probe_duration_seconds(input_path)
    layout = compute_sprite_layout(
        duration=duration, interval=interval_seconds, columns=columns, rows=rows
    )
    tile_count = layout["tile_count"]
    sheet_count = layout["sheet_count"]

    args = build_sprite_args(
        input_path=input_path,
        output_dir=str(out),
        video_id=video_id,
        interval=interval_seconds,
        tile_width=tile_width,
        tile_height=tile_height,
        columns=columns,
        rows=rows,
        sheet_count=sheet_count,
        threads=ffmpeg_threads(),
    )

    stderr_handler = (
        create_progress_parser(duration_seconds=duration, on_ratio=on_progress)
        if on_progress is not None
        else None
    )
    run_ffmpeg(args, on_progress=stderr_handler, label=f"sprite:{video_id}")

    # VTT 生成（URL は `/sprites/<id>.jpg` を想定）
    sprite_url = f"/sprites/{video_id}.jpg"
    vtt = generate_vtt_content(
        sprite_url=sprite_url,
        tile_count=tile_count,
        tile_width=tile_width,
        tile_height=tile_height,
        columns=columns,
        interval_seconds=interval_seconds,
    )
    (out / f"{video_id}.vtt").write_text(vtt)

    meta = {
        "videoId": video_id,
        "duration": duration,
        "tileCount": tile_count,
        "tileWidth": tile_width,
        "tileHeight": tile_height,
        "columns": columns,
        "rows": rows,
        "interval": interval_seconds,
        "sheetCount": sheet_count,
    }
    (out / f"{video_id}.json").write_text(json.dumps(meta, indent=2))

    return {
        "sprite_path": os.path.join(str(out), f"{video_id}.jpg" if sheet_count == 1 else f"{video_id}-%d.jpg"),
        "vtt_path": str(out / f"{video_id}.vtt"),
        "meta_path": str(out / f"{video_id}.json"),
        "meta": meta,
    }
