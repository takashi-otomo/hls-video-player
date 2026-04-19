"""FFmpeg / ffprobe を subprocess で起動するラッパ。

Node 側 utils/ffmpegRunner.js と同等:
- stderr ストリームを逐次取得しコールバックへ渡す
- `FFMPEG_NICE` が設定されていれば `nice -n N` で優先度を下げる
- ffprobe で動画尺を取得するヘルパ
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from typing import Callable, Optional

from hls_video.config import ffmpeg_nice, ffmpeg_path, ffprobe_path

logger = logging.getLogger(__name__)

# stderr のうち警告/エラー相当の行だけは INFO ロガーに出す（progress ノイズは DEBUG）
_STDERR_NOISE_RE = re.compile(r"(error|fatal|unable|permission|invalid|no such|failed)", re.IGNORECASE)


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
    label: Optional[str] = None,
) -> str:
    """FFmpeg をブロッキング実行。stderr 全体を返す。失敗時 RuntimeError。

    - ログ: コマンド開始 / 所要時間 / stderr 末尾を INFO レベルで出す。
    - progress 行 (fps=..., time=...) は DEBUG レベルに落として出しっぱなしにしない。
    - 警告・エラー相当の行は WARNING レベルで即時表示。
    """
    cmd_exe, cmd_args = build_invocation(ffmpeg_path or _default_ffmpeg(), args)
    tag = f"[{label}]" if label else ""
    # 入出力パスだけ抜き出して見やすい開始ログ
    input_hint = ""
    if "-i" in cmd_args:
        i = cmd_args.index("-i")
        if i + 1 < len(cmd_args):
            input_hint = cmd_args[i + 1]
    logger.info("%s ffmpeg start input=%s (argc=%d)", tag, input_hint or "?", len(cmd_args))

    t0 = time.monotonic()
    proc = subprocess.Popen(
        [cmd_exe, *cmd_args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stderr is not None
    collected: list[str] = []
    try:
        for chunk in iter(proc.stderr.readline, ""):
            collected.append(chunk)
            stripped = chunk.rstrip("\n")
            # 進捗行 (time= / fps= / frame=) は DEBUG、それ以外で警告/エラーは WARNING
            if _STDERR_NOISE_RE.search(stripped):
                logger.warning("%s ffmpeg: %s", tag, stripped[:240])
            else:
                logger.debug("%s ffmpeg: %s", tag, stripped[:240])
            if on_progress:
                try:
                    on_progress(chunk)
                except Exception:
                    pass
    finally:
        proc.stderr.close()
    rc = proc.wait()
    stderr_text = "".join(collected)
    elapsed = time.monotonic() - t0
    if rc != 0:
        tail = "".join(collected[-10:]).strip()
        logger.error("%s ffmpeg FAILED rc=%d elapsed=%.1fs tail=%r", tag, rc, elapsed, tail[-500:])
        raise RuntimeError(f"ffmpeg exited with code {rc}\n{stderr_text}")
    logger.info("%s ffmpeg done rc=0 elapsed=%.1fs", tag, elapsed)
    return stderr_text


def run_ffprobe_json(
    args: list[str],
    *,
    ffprobe_path: Optional[str] = None,
    label: Optional[str] = None,
) -> dict:
    """ffprobe をブロッキング実行。

    Drive FUSE 上の大きな MP4 では moov atom のスキャンで数十秒〜数分かかる
    ことがあるため、10 秒ごとに heartbeat ログを出して「まだ生きている」
    ことを可視化する。
    """
    import threading
    tag = f"[{label}]" if label else ""
    exe = ffprobe_path or _default_ffprobe()

    # 入力パスを引数から抜き出してログに載せる
    input_hint = args[-1] if args else ""
    logger.info("%s ffprobe start input=%s", tag, input_hint)

    t0 = time.monotonic()
    proc = subprocess.Popen(
        [exe, *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # heartbeat: 10 秒ごとに「まだ走ってる」と報告
    heartbeat_stop = threading.Event()

    def _heartbeat() -> None:
        while not heartbeat_stop.wait(10):
            elapsed = time.monotonic() - t0
            logger.info("%s ffprobe still running... (elapsed %.0fs)", tag, elapsed)

    threading.Thread(target=_heartbeat, daemon=True).start()

    try:
        stdout, stderr = proc.communicate()
    finally:
        heartbeat_stop.set()

    elapsed = time.monotonic() - t0
    if proc.returncode != 0:
        logger.error("%s ffprobe FAILED rc=%d elapsed=%.1fs stderr=%s",
                     tag, proc.returncode, elapsed, (stderr or "")[-500:])
        raise RuntimeError(
            f"ffprobe exited with code {proc.returncode}\n{stderr}"
        )
    logger.info("%s ffprobe done rc=0 elapsed=%.1fs", tag, elapsed)
    return json.loads(stdout)


def probe_duration_seconds(
    input_path: str,
    *,
    ffprobe_path: Optional[str] = None,
) -> float:
    data = run_ffprobe_json(
        [
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            input_path,
        ],
        ffprobe_path=ffprobe_path,
        label=f"probe:{os.path.basename(input_path)}",
    )
    return float(data.get("format", {}).get("duration", 0) or 0)


def _default_ffmpeg() -> str:
    return ffmpeg_path()


def _default_ffprobe() -> str:
    return ffprobe_path()
