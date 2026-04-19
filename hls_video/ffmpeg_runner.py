"""FFmpeg / ffprobe を subprocess で起動するラッパ。

Node 側 utils/ffmpegRunner.js と同等:
- stderr ストリームを逐次取得しコールバックへ渡す
- `FFMPEG_NICE` が設定されていれば `nice -n N` で優先度を下げる
- ffprobe で動画尺を取得するヘルパ
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Callable, Optional

from hls_video.config import ffmpeg_nice, ffmpeg_path, ffprobe_path


def build_invocation(exe: str, args: list[str]) -> tuple[str, list[str]]:
    """必要なら `nice -n N <exe> <args...>` に変換して (cmd, cmdArgs) を返す。"""
    nice_level = ffmpeg_nice()
    if nice_level is not None and os.name != "nt":
        return "nice", ["-n", str(nice_level), exe, *args]
    return exe, list(args)


def run_ffmpeg(
    args: list[str],
    *,
    ffmpeg_path: Optional[str] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> str:
    """FFmpeg をブロッキング実行。stderr 全体を返す。失敗時 RuntimeError。"""
    cmd_exe, cmd_args = build_invocation(ffmpeg_path or _default_ffmpeg(), args)
    proc = subprocess.Popen(
        [cmd_exe, *cmd_args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,  # line buffered
    )
    assert proc.stderr is not None
    collected: list[str] = []
    try:
        for chunk in iter(proc.stderr.readline, ""):
            collected.append(chunk)
            if on_progress:
                try:
                    on_progress(chunk)
                except Exception:
                    pass
    finally:
        proc.stderr.close()
    rc = proc.wait()
    stderr_text = "".join(collected)
    if rc != 0:
        raise RuntimeError(f"ffmpeg exited with code {rc}\n{stderr_text}")
    return stderr_text


def run_ffprobe_json(args: list[str], *, ffprobe_path: Optional[str] = None) -> dict:
    result = subprocess.run(
        [ffprobe_path or _default_ffprobe(), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffprobe exited with code {result.returncode}\n{result.stderr}"
        )
    return json.loads(result.stdout)


def probe_duration_seconds(input_path: str, *, ffprobe_path: Optional[str] = None) -> float:
    data = run_ffprobe_json(
        [
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            input_path,
        ],
        ffprobe_path=ffprobe_path,
    )
    return float(data.get("format", {}).get("duration", 0) or 0)


def _default_ffmpeg() -> str:
    return ffmpeg_path()


def _default_ffprobe() -> str:
    return ffprobe_path()
