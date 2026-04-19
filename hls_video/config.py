"""環境変数から動作パラメータを集約するモジュール。

テスト容易性のため、呼び出し時に `os.environ` を都度参照する関数スタイル。
値の型変換（int / float）と範囲チェックもここで行う。
"""

from __future__ import annotations

import os
from pathlib import Path


def media_root() -> Path:
    """MEDIA_ROOT を絶対パスで返す。既定はカレントの ./media。"""
    return Path(os.environ.get("MEDIA_ROOT", "./media")).resolve()


def ffmpeg_path() -> str:
    return os.environ.get("FFMPEG_PATH", "ffmpeg")


def ffprobe_path() -> str:
    return os.environ.get("FFPROBE_PATH", "ffprobe")


def ffmpeg_threads() -> int:
    return max(1, int(os.environ.get("FFMPEG_THREADS", "2")))


def ffmpeg_preset() -> str:
    return os.environ.get("FFMPEG_PRESET", "veryfast")


def ffmpeg_nice() -> int | None:
    """FFMPEG_NICE が設定されていれば int として返す。未設定なら None。"""
    raw = os.environ.get("FFMPEG_NICE")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def max_concurrent_jobs() -> int:
    """同時変換ジョブ数の上限。既定 2、最低 1。"""
    return max(1, int(os.environ.get("MAX_CONCURRENT_JOBS", "2")))
