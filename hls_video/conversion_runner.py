"""変換ジョブをステージ加重で進捗集約しつつ実行するオーケストレータ。

Node 側 utils/conversionRunner.js と同等。
UI 側は job.progress (0..1) と job.stage を読んでプログレス表示する。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from hls_video.ffmpeg_runner import probe_duration_seconds
from hls_video.hls_converter import convert_mp4_to_hls
from hls_video.job_registry import JobRegistry
from hls_video.sprite_generator import generate_sprite

# 合計 1.0。HLS が重い (83%)、スプライトは 15%、先頭 2% は probe/準備に割当。
STAGE_WEIGHTS = {"probe": 0.02, "hls": 0.83, "sprite": 0.15}


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def run_conversion(
    *,
    registry: JobRegistry,
    job_id: str,
    media_root: str,
    source_file: str,
    video_id: str,
) -> None:
    input_path = Path(media_root) / "source" / source_file
    hls_dir = Path(media_root) / "hls" / video_id
    sprites_dir = Path(media_root) / "sprites"

    if not input_path.exists():
        registry.update(job_id, state="failed", error=f"source not found: {source_file}", progress=0.0)
        return

    try:
        registry.update(job_id, state="running", stage="probe", progress=0.0)
        duration = probe_duration_seconds(str(input_path))
        registry.update(job_id, progress=STAGE_WEIGHTS["probe"], duration_seconds=duration)

        # --- HLS stage ---
        registry.update(job_id, stage="hls")

        def on_hls_progress(ratio: float, _meta: dict) -> None:
            overall = STAGE_WEIGHTS["probe"] + STAGE_WEIGHTS["hls"] * ratio
            registry.update(job_id, progress=_clamp01(overall), stage_progress=ratio)

        convert_mp4_to_hls(
            input_path=str(input_path),
            output_dir=str(hls_dir),
            duration_seconds=duration,
            on_progress=on_hls_progress,
        )
        registry.update(
            job_id,
            progress=STAGE_WEIGHTS["probe"] + STAGE_WEIGHTS["hls"],
            stage_progress=1.0,
        )

        # --- Sprite stage ---
        registry.update(job_id, stage="sprite", stage_progress=0.0)

        def on_sprite_progress(ratio: float, _meta: dict) -> None:
            overall = STAGE_WEIGHTS["probe"] + STAGE_WEIGHTS["hls"] + STAGE_WEIGHTS["sprite"] * ratio
            registry.update(job_id, progress=_clamp01(overall), stage_progress=ratio)

        generate_sprite(
            input_path=str(input_path),
            output_dir=str(sprites_dir),
            video_id=video_id,
            duration_seconds=duration,
            on_progress=on_sprite_progress,
        )

        registry.update(job_id, state="completed", stage="done", progress=1.0, stage_progress=1.0)
    except Exception as err:
        registry.update(job_id, state="failed", error=str(err)[:500])
        # 中途半端な HLS 出力はクリーンアップ
        if hls_dir.exists() and not (hls_dir / "master.m3u8").exists():
            shutil.rmtree(hls_dir, ignore_errors=True)
