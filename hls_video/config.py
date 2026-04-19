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
    """FFmpeg に渡す -threads 値。

    0 は ffmpeg の "auto" = 物理コア数に合わせた最適化。
    以前は 2 固定だったが、libx264/NVENC とも 0 (auto) が高速なので既定を 0 に変更。
    負数は 0 へクリップ。
    """
    raw = os.environ.get("FFMPEG_THREADS", "0")
    try:
        v = int(raw)
    except ValueError:
        return 0
    return max(0, v)


def ffmpeg_preset() -> str:
    """libx264 用の preset（NVENC とは別物）。

    CPU encode は preset が実行時間に大きく効くため既定を `ultrafast` に引き下げ。
    HLS 配信用途では CRF で品質を担保するためサイズの微増よりも速度を優先する。
    画質を優先したい場合は FFMPEG_PRESET=veryfast / fast などに上書き。
    """
    return os.environ.get("FFMPEG_PRESET", "ultrafast")


def ffmpeg_nvenc_preset() -> str:
    """NVENC (h264_nvenc) 用 preset。p1 (最速) .. p7 (最高画質)。

    既定は `p4`（バランス）。エンコード速度を最大化したいなら p1/p2 に。
    """
    return os.environ.get("FFMPEG_NVENC_PRESET", "p4")


def ffmpeg_hwaccel() -> str:
    """FFMPEG_HWACCEL: "auto" (既定) / "nvenc" / "cpu"。

    auto: h264_nvenc が ffmpeg に含まれていれば NVENC、無ければ CPU。
    nvenc: 強制 NVENC（検出失敗でも NVENC パスを組む）。
    cpu: 強制 libx264。
    """
    return os.environ.get("FFMPEG_HWACCEL", "auto").lower()


def ffmpeg_variants_filter() -> list[str] | None:
    """FFMPEG_VARIANTS="720p,360p" のように絞り込む。未指定なら全解像度。"""
    raw = os.environ.get("FFMPEG_VARIANTS", "").strip()
    if not raw:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]


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


def staging_dir() -> Path:
    """Drive からコピーしてきたソース MP4 を一時的に置く場所。

    Colab では /tmp (Colab ローカル SSD) が Drive FUSE より圧倒的に速いので、
    変換直前にここへコピーして ffmpeg に読ませる。変換完了後は自動削除。
    """
    return Path(os.environ.get("STAGING_DIR", "/tmp/hls-staging"))
