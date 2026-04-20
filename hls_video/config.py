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


def ffmpeg_cuvid() -> str:
    """FFMPEG_CUVID: "off" (既定) / "on" / "auto"。

    NVENC 使用時に **GPU decode (CUVID)** も使うかどうか。有効なら input 側で
    `-hwaccel cuda -hwaccel_output_format cuda -c:v <codec>_cuvid` を追加し、
    filter_complex も `scale_cuda` に置き換える。decode / scale / encode が
    全て GPU 上で完結しメモリコピーも排除できるが、環境によっては libcuda.so.1
    のロードに失敗するため **既定は off**。動作確認済み環境で速度を出したい
    場合だけ明示的に `on` / `auto` を指定。

    auto: 入力 codec に対応する cuvid decoder が ffmpeg にあれば自動有効化。
    on: 対応が検出できれば使う。
    off: CPU decode のまま (NVENC encode のみ)。[既定]
    """
    return os.environ.get("FFMPEG_CUVID", "off").lower()


def ffmpeg_bframes() -> int | None:
    """NVENC の -bf 値。未設定なら None → `-bf` 引数自体を付けない (NVENC デフォルト動作)。

    - 未設定 / 不正値: None (NVENC 既定の B-frames 使用、通常は 0 か 2)
    - "0": B-frames 無効化、速度優先だが圧縮効率は 5-10% 悪化
    - "2"〜"3": 圧縮重視
    """
    raw = os.environ.get("FFMPEG_BFRAMES")
    if raw is None or raw == "":
        return None
    try:
        v = int(raw)
    except ValueError:
        return None
    return max(0, v)


def ffmpeg_variants_filter() -> list[str] | None:
    """FFMPEG_VARIANTS="720p,360p" のように絞り込む。未指定なら全解像度。"""
    raw = os.environ.get("FFMPEG_VARIANTS", "").strip()
    if not raw:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]


def ffmpeg_audio_copy() -> bool:
    """音声を再エンコードせず `-c:a copy` で通すか。既定 False。

    入力音声が AAC で HLS 出力もそのまま AAC でよい場合、音声の decode+encode
    を省略して 5% 程度高速化できる。入力が非 AAC (MP3, PCM 等) のときに有効化
    すると HLS プレイヤーで再生できなくなる可能性があるため要注意。
    """
    raw = os.environ.get("FFMPEG_AUDIO_COPY", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def ffmpeg_x264_tune() -> str | None:
    """libx264 の `-tune` オプション。未指定なら付けない。

    代表値:
    - "zerolatency": B-frames 無効・lookahead 無効で 10-20% 速度向上 (速度優先)
    - "fastdecode": 再生側 decode 負荷を軽減 (encode 側の効果は限定的)
    - "film" / "animation" / "grain": 画質優先 (速度下がる)

    CPU fallback 時のみ効く。NVENC は独自の preset 体系なので無視される。
    """
    raw = os.environ.get("FFMPEG_X264_TUNE", "").strip()
    return raw or None


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
