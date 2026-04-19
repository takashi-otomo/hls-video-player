"""Python 実装の変換 CLI。

既存の Node 版 `backend/scripts/convert.js` と同じく、1 本の MP4 を
HLS とスプライトに変換するワンショット動作。Gradio を介さず
ローカルから動作確認するためのツール。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hls_video.config import media_root
from hls_video.conversion_runner import run_conversion
from hls_video.job_registry import JobRegistry
from hls_video.source_catalog import resolve_video_id


def _progress_printer(reg: JobRegistry, job_id: str):
    last_printed = -1

    def tick() -> None:
        nonlocal last_printed
        job = reg.get(job_id)
        if not job:
            return
        pct = int((job.progress or 0) * 100)
        if pct != last_printed:
            last_printed = pct
            stage = job.stage or "-"
            sys.stderr.write(f"\r[{stage:<6}] {pct:3d}%")
            sys.stderr.flush()
    return tick


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert MP4 to HLS + sprite")
    parser.add_argument("input", help="Path to source video file (under media/source/ or absolute)")
    parser.add_argument("video_id", nargs="?", help="Override video id (default: sanitized filename)")
    args = parser.parse_args()

    root = media_root()
    source_dir = root / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    (root / "hls").mkdir(parents=True, exist_ok=True)
    (root / "sprites").mkdir(parents=True, exist_ok=True)

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = (source_dir / input_path.name).resolve()
    if not input_path.exists():
        print(f"input not found: {input_path}", file=sys.stderr)
        return 1

    source_file = input_path.name
    video_id = args.video_id or resolve_video_id(source_file)

    print(f"→ Converting {source_file!r} as id {video_id!r}")
    print(f"  HLS  : {root}/hls/{video_id}")
    print(f"  Sprite: {root}/sprites")

    reg = JobRegistry(max_workers=1)
    job = reg.create(video_id=video_id, source_file=source_file)
    # 同期実行（CLI なのでプールに投げずに直接呼ぶ）
    run_conversion(
        registry=reg,
        job_id=job.id,
        media_root=str(root),
        source_file=source_file,
        video_id=video_id,
    )
    final = reg.get(job.id)
    if final.state == "completed":
        print(f"\n✓ Done in stage={final.stage}, duration={final.duration_seconds:.1f}s")
        return 0
    print(f"\n✗ Failed: {final.error}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
