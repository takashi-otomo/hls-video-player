"""変換ジョブをステージ加重で進捗集約しつつ実行するオーケストレータ。

Node 側 utils/conversionRunner.js と同等。
UI 側は job.progress (0..1) と job.stage を読んでプログレス表示する。
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from hls_video.ffmpeg_runner import probe_duration_seconds
from hls_video.hls_converter import convert_mp4_to_hls
from hls_video.job_registry import JobRegistry
from hls_video.sprite_generator import generate_sprite

logger = logging.getLogger(__name__)

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
    source_path: str | None = None,
    cleanup_source_after: bool = False,
) -> None:
    """変換ジョブ本体。

    - `source_file` は表示用（Job.source_file や UI ログ用）
    - `source_path` を明示した場合はそちらを ffmpeg 入力に使う（Colab のステージング
      対応）。省略時は従来通り `{media_root}/source/{source_file}` を参照。
    - `cleanup_source_after=True` のとき、成功時・失敗時のどちらも入力ファイルを
      unlink する（ステージングで /tmp に置いた一時ファイル向け）。
      成功時のみ消す等の細かい制御が必要なら別途フラグを用意すること。
    """
    if source_path:
        input_path = Path(source_path)
    else:
        input_path = Path(media_root) / "source" / source_file
    hls_dir = Path(media_root) / "hls" / video_id
    sprites_dir = Path(media_root) / "sprites"

    if not input_path.exists():
        logger.error("[%s] source not found: %s", video_id, input_path)
        registry.update(
            job_id,
            state="failed",
            error=f"source not found: {source_file}",
            progress=0.0,
        )
        return

    try:
        size_mb = input_path.stat().st_size / (1024 * 1024)
        logger.info(
            "[%s] conversion start: source=%s (%.1f MB)",
            video_id, source_file, size_mb,
        )

        now_iso = lambda: datetime.now(tz=timezone.utc).isoformat()

        registry.update(
            job_id, state="running", stage="probe",
            progress=0.0, last_progress_at=now_iso(),
        )

        # Drive FUSE 経由の大容量 MP4 は moov atom スキャンで数十秒〜数分
        # 固まることがある。呼び出し前後で明示的にログを出す。
        logger.info(
            "[%s] probing duration (may take a while on Drive-mounted large files)",
            video_id,
        )

        t_probe = time.monotonic()
        duration = probe_duration_seconds(str(input_path))
        logger.info(
            "[%s] probe done: duration=%.1fs (took %.1fs)",
            video_id, duration, time.monotonic() - t_probe,
        )
        registry.update(
            job_id,
            progress=STAGE_WEIGHTS["probe"],
            duration_seconds=duration,
            last_progress_at=now_iso(),
        )

        # --- HLS stage ---
        t_hls_start = time.monotonic()
        registry.update(job_id, stage="hls", last_progress_at=now_iso())
        logger.info("[%s] HLS stage start", video_id)

        # 進捗ログはノイズ削減のため 10% きざみ or 60 秒毎
        hls_log_state = {"last_pct": -10, "last_log_t": 0.0}

        def on_hls_progress(ratio: float, meta: dict) -> None:
            overall = STAGE_WEIGHTS["probe"] + STAGE_WEIGHTS["hls"] * ratio
            pct = int(overall * 100)
            now_t = time.monotonic()
            if (pct - hls_log_state["last_pct"] >= 10) or (now_t - hls_log_state["last_log_t"] >= 60):
                elapsed = now_t - t_hls_start
                rate = (ratio * duration) / elapsed if elapsed > 0 else 0
                logger.info(
                    "[%s] HLS %d%% (ffmpeg time=%.0fs / %.0fs, elapsed=%.0fs, speed=%.2fx)",
                    video_id, pct, meta.get("current_time", 0), duration, elapsed, rate,
                )
                hls_log_state["last_pct"] = pct
                hls_log_state["last_log_t"] = now_t
            registry.update(
                job_id,
                progress=_clamp01(overall),
                stage_progress=ratio,
                last_progress_at=now_iso(),
            )

        convert_mp4_to_hls(
            input_path=str(input_path),
            output_dir=str(hls_dir),
            duration_seconds=duration,
            on_progress=on_hls_progress,
        )
        logger.info(
            "[%s] HLS stage done (%.1fs)",
            video_id, time.monotonic() - t_hls_start,
        )
        registry.update(
            job_id,
            progress=STAGE_WEIGHTS["probe"] + STAGE_WEIGHTS["hls"],
            stage_progress=1.0,
            last_progress_at=now_iso(),
        )

        # --- Sprite stage ---
        t_sprite_start = time.monotonic()
        registry.update(job_id, stage="sprite", stage_progress=0.0, last_progress_at=now_iso())
        logger.info("[%s] sprite stage start", video_id)

        sprite_log_state = {"last_pct": -10, "last_log_t": 0.0}

        def on_sprite_progress(ratio: float, meta: dict) -> None:
            overall = STAGE_WEIGHTS["probe"] + STAGE_WEIGHTS["hls"] + STAGE_WEIGHTS["sprite"] * ratio
            pct = int(overall * 100)
            now_t = time.monotonic()
            if (pct - sprite_log_state["last_pct"] >= 10) or (now_t - sprite_log_state["last_log_t"] >= 60):
                elapsed = now_t - t_sprite_start
                logger.info(
                    "[%s] sprite %d%% (ffmpeg time=%.0fs, elapsed=%.0fs)",
                    video_id, pct, meta.get("current_time", 0), elapsed,
                )
                sprite_log_state["last_pct"] = pct
                sprite_log_state["last_log_t"] = now_t
            registry.update(
                job_id,
                progress=_clamp01(overall),
                stage_progress=ratio,
                last_progress_at=now_iso(),
            )

        generate_sprite(
            input_path=str(input_path),
            output_dir=str(sprites_dir),
            video_id=video_id,
            duration_seconds=duration,
            on_progress=on_sprite_progress,
        )
        logger.info(
            "[%s] sprite stage done (%.1fs)",
            video_id, time.monotonic() - t_sprite_start,
        )

        registry.update(
            job_id,
            state="completed", stage="done",
            progress=1.0, stage_progress=1.0,
            last_progress_at=now_iso(),
        )
        logger.info("[%s] conversion complete", video_id)
    except Exception as err:
        logger.exception("[%s] conversion FAILED: %s", video_id, err)
        registry.update(job_id, state="failed", error=str(err)[:500])
        if hls_dir.exists() and not (hls_dir / "master.m3u8").exists():
            shutil.rmtree(hls_dir, ignore_errors=True)
    finally:
        # ステージング領域の一時ファイルは成否にかかわらず掃除
        if cleanup_source_after and source_path:
            try:
                Path(source_path).unlink(missing_ok=True)
                logger.info("[%s] staged source cleaned up: %s", video_id, source_path)
            except OSError as e:
                logger.warning("[%s] staging cleanup failed: %s", video_id, e)
