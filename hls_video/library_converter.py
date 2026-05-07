"""フォルダ走査モデル用の変換オーケストレータ。

入力: ライブラリルート + 1 本の動画ファイルパス
出力: `{library_root}/{converted_dir}/{stem}/{hls,thumbs,meta.json}`

- HLS 変換: hls_converter.convert_mp4_to_hls
- サムネ: thumbnail_generator.generate_thumbnails (5 枚 + poster.png)
- メタ: meta.json に duration / thumbs[] / hls master 相対パス等を書き出し
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hls_video.config import library_root, converted_dir_name
from hls_video.ffmpeg_runner import probe_duration_seconds, probe_video_stream
from hls_video.hls_converter import convert_mp4_to_hls
from hls_video.thumbnail_generator import (
    THUMB_PERCENTS, generate_thumbnails, thumb_filename,
)

logger = logging.getLogger(__name__)

VIDEO_EXTS: frozenset[str] = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v"})


@dataclass
class ConvertResult:
    stem: str
    output_dir: Path        # converted/{stem}
    duration: float
    hls_master: Path
    poster: Path
    thumbs: list[Path]
    skipped: bool = False
    elapsed: float = 0.0


def converted_root(lib_root: Optional[Path] = None) -> Path:
    return (lib_root or library_root()) / converted_dir_name()


def output_dir_for(stem: str, lib_root: Optional[Path] = None) -> Path:
    return converted_root(lib_root) / stem


def is_already_converted(stem: str, lib_root: Optional[Path] = None) -> bool:
    """master.m3u8 + poster.png + meta.json の存在で「変換済」と判定。"""
    out = output_dir_for(stem, lib_root)
    return (
        (out / "hls" / "master.m3u8").exists()
        and (out / "thumbs" / "poster.png").exists()
        and (out / "meta.json").exists()
    )


def _write_meta(
    *,
    out_dir: Path,
    stem: str,
    source_filename: str,
    duration: float,
    width: int,
    height: int,
    codec: str,
    backend: str,
    variants: list[str],
) -> Path:
    """meta.json を書き出す。

    GUI / API はこのファイルから動画メタとサムネ参照を組み立てる。
    """
    meta = {
        "stem": stem,
        "source_filename": source_filename,
        "duration": round(float(duration), 3),
        "width": int(width),
        "height": int(height),
        "codec": codec,
        "hls": {
            "master": "hls/master.m3u8",
            "variants": variants,
        },
        "thumbs": {
            "poster": "thumbs/poster.png",
            "frames": [
                {"percent": p, "file": f"thumbs/{thumb_filename(p)}"}
                for p in THUMB_PERCENTS
            ],
        },
        "encoded_with": {
            "backend": backend,
        },
        "converted_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    meta_path = out_dir / "meta.json"
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    return meta_path


def convert_one(
    source_path: Path,
    *,
    lib_root: Optional[Path] = None,
    force: bool = False,
) -> ConvertResult:
    """1 本の動画を HLS + サムネへ変換する。

    既に変換済みかつ force=False ならスキップ（ConvertResult.skipped=True）。
    """
    src = Path(source_path).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"source not found: {src}")
    if src.suffix.lower() not in VIDEO_EXTS:
        raise ValueError(f"unsupported extension: {src.suffix}")

    stem = src.stem
    out_dir = output_dir_for(stem, lib_root)
    hls_dir = out_dir / "hls"
    thumbs_dir = out_dir / "thumbs"

    if not force and is_already_converted(stem, lib_root):
        return ConvertResult(
            stem=stem,
            output_dir=out_dir,
            duration=0.0,
            hls_master=hls_dir / "master.m3u8",
            poster=thumbs_dir / "poster.png",
            thumbs=[thumbs_dir / thumb_filename(p) for p in THUMB_PERCENTS],
            skipped=True,
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    hls_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    logger.info("convert start: %s → %s", src, out_dir)

    # 1) probe
    duration = probe_duration_seconds(str(src))
    stream = probe_video_stream(str(src))

    # 2) HLS 変換
    hls_result = convert_mp4_to_hls(
        input_path=str(src),
        output_dir=str(hls_dir),
        duration_seconds=duration,
        input_width=stream.get("width"),
        input_height=stream.get("height"),
        input_codec=stream.get("codec_name"),
        input_pix_fmt=stream.get("pix_fmt"),
        input_field_order=stream.get("field_order"),
    )

    # 3) サムネ + poster
    thumbs = generate_thumbnails(
        input_path=str(src),
        output_dir=str(thumbs_dir),
        duration_seconds=duration,
    )

    # 4) meta.json
    _write_meta(
        out_dir=out_dir,
        stem=stem,
        source_filename=src.name,
        duration=duration,
        width=stream.get("width") or 0,
        height=stream.get("height") or 0,
        codec=stream.get("codec_name") or "",
        backend=hls_result.get("backend", "?"),
        variants=hls_result.get("variants", []),
    )

    elapsed = time.monotonic() - t0
    logger.info("convert done : %s (%.1fs)", stem, elapsed)
    return ConvertResult(
        stem=stem,
        output_dir=out_dir,
        duration=duration,
        hls_master=hls_dir / "master.m3u8",
        poster=thumbs.poster_path,
        thumbs=thumbs.thumb_paths,
        skipped=False,
        elapsed=elapsed,
    )


def scan_library(lib_root: Optional[Path] = None) -> list[Path]:
    """ライブラリ直下の動画ファイルを列挙（変換済か否かは問わない）。"""
    root = Path(lib_root or library_root())
    if not root.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_file():
            continue
        if entry.name.startswith("."):
            continue
        if entry.suffix.lower() in VIDEO_EXTS:
            out.append(entry)
    return out
