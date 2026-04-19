"""MP4 → HLS (ABR) 変換。

パフォーマンス最適化:
- `-filter_complex split=N` で **デコードを 1 回に抑え**、N 本のバリアントへ分岐させる
- `FFMPEG_HWACCEL=auto` なら NVENC (h264_nvenc) を自動選択。CPU 比で 10-30x 高速
- `FFMPEG_VARIANTS="720p,360p"` でラダーを絞れる
- `-threads 0` (auto) 既定

品質設定:
- CPU: `-preset <ultrafast|...>` + CRF
- NVENC: `-preset p1..p7` + `-rc vbr -cq`
- HLS の GOP/セグメント整合: `-g`/`-keyint_min` = segment_seconds × fps、`-sc_threshold 0`
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Literal, Optional, TypedDict

from hls_video.config import (
    ffmpeg_bframes,
    ffmpeg_cuvid,
    ffmpeg_hwaccel,
    ffmpeg_nvenc_preset,
    ffmpeg_path,
    ffmpeg_preset,
    ffmpeg_threads,
    ffmpeg_variants_filter,
)
from hls_video.ffmpeg_runner import run_ffmpeg
from hls_video.hwaccel import (
    Backend, _list_decoders, detect_cuda_runtime, detect_nvenc,
    resolve_cuvid, resolve_hwaccel,
)
from hls_video.master_playlist import build_master_playlist
from hls_video.progress_parser import create_progress_parser

# ffmpeg が返す CUDA 関連エラーの代表パターン。どれかに該当したら
# NVENC/CUVID が runtime-unavailable と見なして CPU に切り替えて再実行する。
_CUDA_ERROR_MARKERS = (
    "Cannot load libcuda",
    "Could not dynamically load CUDA",
    "Device creation failed",
    "Device setup failed",
    "No device available",
    "Cannot load libnvcuvid",
    "NVENC capability",
    "OpenEncodeSessionEx failed",
)


def _is_cuda_runtime_error(message: str) -> bool:
    return any(m in message for m in _CUDA_ERROR_MARKERS)

logger = logging.getLogger(__name__)


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


def _filter_complex_split(
    variants: list[Variant],
    *,
    portrait: bool = False,
    scale_filter: str = "scale",
) -> str:
    """1 decode → N scale への split チェーンを組む。

    `[0:v]split=N[v0][v1]...; [v0]scale=...[vo0]; [v1]scale=...[vo1]; ...`

    - `portrait=True`: 縦動画向けに w/h を入れ替え、variant.height を短辺扱い
    - `scale_filter`: `scale` (CPU) か `scale_cuda` (CUVID decode 時)。
      scale_cuda は GPU メモリ上で解像度変換するので decode → scale → encode まで
      GPU に常駐し、メモリコピーが一切発生しない。ffmpeg 4.4 以降は
      `force_original_aspect_ratio` / `force_divisible_by` オプション対応。
    """
    n = len(variants)
    labels = "".join(f"[v{i}]" for i in range(n))
    parts = [f"[0:v]split={n}{labels}"]
    for i, v in enumerate(variants):
        short_edge = v["height"]
        if portrait:
            scale = (
                f"{scale_filter}=w={short_edge}:h=-2:"
                f"force_original_aspect_ratio=decrease:force_divisible_by=2"
            )
        else:
            scale = (
                f"{scale_filter}=w=-2:h={short_edge}:"
                f"force_original_aspect_ratio=decrease:force_divisible_by=2"
            )
        parts.append(f"[v{i}]{scale}[vo{i}]")
    return ";".join(parts)


def _cpu_variant_output_args(
    variant: Variant,
    *,
    out_dir: str,
    map_label: str,
    segment_seconds: int,
    gop: int,
    preset: str,
    threads: int,
) -> list[str]:
    """CPU (libx264) の 1 variant 分 -map + エンコーダ引数。"""
    playlist = os.path.join(out_dir, f"{variant['name']}.m3u8")
    seg_pattern = os.path.join(out_dir, f"{variant['name']}_%03d.ts")
    return [
        "-map", map_label,
        "-map", "0:a:0?",
        "-c:a", "aac", "-ar", "48000", "-b:a", variant["audio_bitrate"],
        "-c:v", "h264", "-profile:v", "main",
        "-preset", preset,
        "-threads", str(threads),
        "-crf", str(variant["crf"]),
        "-pix_fmt", "yuv420p",
        "-sc_threshold", "0",
        "-g", str(gop), "-keyint_min", str(gop),
        "-b:v", variant["video_bitrate"],
        "-maxrate", variant["maxrate"],
        "-bufsize", variant["bufsize"],
        "-hls_time", str(segment_seconds),
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", seg_pattern,
        "-f", "hls", playlist,
    ]


def _nvenc_variant_output_args(
    variant: Variant,
    *,
    out_dir: str,
    map_label: str,
    segment_seconds: int,
    gop: int,
    preset: str,
    bframes: Optional[int],
) -> list[str]:
    """NVENC (h264_nvenc) の 1 variant 分。

    NVENC は -crf ではなく -rc vbr + -cq で品質目標を指定する。libx264 の CRF を
    近い体感画質にマップ: CRF そのまま CQ に使うと libx264 よりやや低画質側に寄るが、
    HLS 配信品質としては十分許容範囲。

    bframes=None のときは `-bf` を付けず NVENC のデフォルトに任せる (推奨)。
    bframes=0 を明示すると B-frames 無効化で速度優先になるが、圧縮効率は悪化。
    """
    playlist = os.path.join(out_dir, f"{variant['name']}.m3u8")
    seg_pattern = os.path.join(out_dir, f"{variant['name']}_%03d.ts")
    args = [
        "-map", map_label,
        "-map", "0:a:0?",
        "-c:a", "aac", "-ar", "48000", "-b:a", variant["audio_bitrate"],
        "-c:v", "h264_nvenc",
        "-profile:v", "main",
        "-preset", preset,
        "-rc", "vbr",
        "-cq", str(variant["crf"]),
    ]
    if bframes is not None:
        args.extend(["-bf", str(bframes)])
    args.extend([
        "-b:v", variant["video_bitrate"],
        "-maxrate", variant["maxrate"],
        "-bufsize", variant["bufsize"],
        "-pix_fmt", "yuv420p",
        "-g", str(gop), "-keyint_min", str(gop),
        "-hls_time", str(segment_seconds),
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", seg_pattern,
        "-f", "hls", playlist,
    ])
    return args


def build_ffmpeg_args(
    *,
    input_path: str,
    output_dir: str,
    variants: list[Variant],
    segment_seconds: int,
    gop: int,
    backend: Backend,
    preset: str,
    threads: int,
    nvenc_preset: str,
    portrait: bool = False,
    cuvid_decoder: Optional[str] = None,
    bframes: Optional[int] = None,
) -> list[str]:
    """フル ffmpeg 引数を組み立てる。

    - `cuvid_decoder`: 非 None かつ backend="nvenc" のとき CUVID GPU decode を有効化。
      input 側に `-hwaccel cuda -hwaccel_output_format cuda -c:v <cuvid>` を追加し、
      filter_complex の scale を `scale_cuda` に置き換えて全工程を GPU 上で完結させる。
    - `bframes`: NVENC 出力に `-bf <N>` を付与。0 で無効化（速度優先）。libx264 は未使用。
    """
    use_cuvid = cuvid_decoder is not None and backend == "nvenc"
    filter_complex = _filter_complex_split(
        variants, portrait=portrait,
        scale_filter="scale_cuda" if use_cuvid else "scale",
    )

    args: list[str] = ["-y"]
    if use_cuvid:
        # -i の前に HW accel と decoder を指定する必要がある
        args.extend([
            "-hwaccel", "cuda",
            "-hwaccel_output_format", "cuda",
            "-c:v", cuvid_decoder,  # type: ignore[list-item]
        ])
    args.extend(["-i", input_path, "-filter_complex", filter_complex])

    for i, v in enumerate(variants):
        label = f"[vo{i}]"
        if backend == "nvenc":
            args.extend(_nvenc_variant_output_args(
                v, out_dir=output_dir, map_label=label,
                segment_seconds=segment_seconds, gop=gop, preset=nvenc_preset,
                bframes=bframes,
            ))
        else:
            args.extend(_cpu_variant_output_args(
                v, out_dir=output_dir, map_label=label,
                segment_seconds=segment_seconds, gop=gop,
                preset=preset, threads=threads,
            ))
    return args


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
    hwaccel: Optional[str] = None,
    nvenc_preset: Optional[str] = None,
    input_width: Optional[int] = None,
    input_height: Optional[int] = None,
    input_codec: Optional[str] = None,
    cuvid_mode: Optional[str] = None,
    bframes: Optional[int] = None,
) -> dict:
    selected = variants or DEFAULT_VARIANTS

    # 環境変数で絞り込み
    names_filter = ffmpeg_variants_filter()
    if names_filter:
        filtered = [v for v in selected if v["name"] in names_filter]
        if filtered:
            selected = filtered
        else:
            logger.warning(
                "FFMPEG_VARIANTS=%s does not match any variant; using full ladder",
                names_filter,
            )

    backend: Backend = resolve_hwaccel(hwaccel or ffmpeg_hwaccel(), ffmpeg_path())
    preset_ = preset or ffmpeg_preset()
    nvenc_preset_ = nvenc_preset or ffmpeg_nvenc_preset()
    threads_ = threads if threads is not None else ffmpeg_threads()
    bframes_ = bframes if bframes is not None else ffmpeg_bframes()  # None 可

    # CUVID decoder 解決。NVENC バックエンド時のみ有効。
    cuvid_decoder: Optional[str] = None
    if backend == "nvenc":
        cuvid_decoder = resolve_cuvid(
            cuvid_mode or ffmpeg_cuvid(), input_codec or "", ffmpeg_path(),
        )

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    gop = max(2, round(segment_seconds * fps))

    # orientation 判定: 縦動画（height > width）のとき portrait=True。
    # 0/None の場合は landscape 扱い（既存挙動）。
    portrait = bool(
        input_width and input_height and int(input_height) > int(input_width)
    )

    logger.info(
        "HLS encode: backend=%s variants=%s preset=%s nvenc_preset=%s "
        "threads=%d gop=%d portrait=%s (in=%sx%s codec=%s) "
        "cuvid=%s bframes=%s",
        backend, [v["name"] for v in selected], preset_, nvenc_preset_,
        threads_, gop, portrait, input_width, input_height, input_codec,
        cuvid_decoder or "off", "default" if bframes_ is None else bframes_,
    )

    args = build_ffmpeg_args(
        input_path=input_path, output_dir=str(out), variants=selected,
        segment_seconds=segment_seconds, gop=gop, backend=backend,
        preset=preset_, threads=threads_, nvenc_preset=nvenc_preset_,
        portrait=portrait, cuvid_decoder=cuvid_decoder, bframes=bframes_,
    )

    def _make_handler():
        return (
            create_progress_parser(duration_seconds=duration_seconds, on_ratio=on_progress)
            if on_progress is not None
            else None
        )

    label = f"hls:{Path(output_dir).name}"
    try:
        run_ffmpeg(args, on_progress=_make_handler(), label=label)
    except RuntimeError as err:
        # NVENC/CUVID 関連の runtime エラーなら CPU にフォールバックして再実行。
        # detect_cuda_runtime は判定に成功しても ffmpeg 側の lib 読み込みで
        # 落ちることがあるので、最後の砦として保険を入れる。
        if backend == "nvenc" and _is_cuda_runtime_error(str(err)):
            logger.warning(
                "NVENC/CUVID failed at runtime; falling back to CPU (libx264). "
                "error tail=%s", str(err)[-240:].replace("\n", " "),
            )
            # キャッシュを無効化: 次のジョブは最初から CPU 経路
            detect_nvenc.cache_clear()
            _list_decoders.cache_clear()
            detect_cuda_runtime.cache_clear()
            # 不完全な出力を掃除してから再実行
            if out.exists():
                for f in out.iterdir():
                    try:
                        f.unlink()
                    except OSError:
                        pass
            backend = "cpu"
            cuvid_decoder = None
            args = build_ffmpeg_args(
                input_path=input_path, output_dir=str(out), variants=selected,
                segment_seconds=segment_seconds, gop=gop, backend=backend,
                preset=preset_, threads=threads_, nvenc_preset=nvenc_preset_,
                portrait=portrait, cuvid_decoder=None, bframes=bframes_,
            )
            logger.info(
                "HLS encode (retry): backend=cpu preset=%s threads=%d",
                preset_, threads_,
            )
            run_ffmpeg(args, on_progress=_make_handler(), label=label)
        else:
            raise

    master = build_master_playlist([
        {"bandwidth": v["bandwidth"], "resolution": v["resolution"],
         "playlist": f"{v['name']}.m3u8"}
        for v in selected
    ])
    (out / "master.m3u8").write_text(master)

    return {
        "master_path": str(out / "master.m3u8"),
        "variants": [v["name"] for v in selected],
        "backend": backend,  # fallback 後は "cpu" に更新されている
        "cuvid": cuvid_decoder,
        "bframes": bframes_,
    }
