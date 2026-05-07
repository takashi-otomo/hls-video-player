"""ライブラリ ({LIBRARY_ROOT}/converted/) を走査して変換済み動画を一覧化する。

新アーキテクチャの GUI / API データソース。旧 video_catalog.py の置き換え。

各 stem ディレクトリ:
  converted/{stem}/
    hls/master.m3u8
    thumbs/poster.png
    thumbs/thumb_{05,30,50,60,80}.jpg
    meta.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from hls_video.config import converted_dir_name
from hls_video.favorites import load_favorites
from hls_video.library_settings import get_library_root
from hls_video.thumbnail_generator import THUMB_PERCENTS, thumb_filename

logger = logging.getLogger(__name__)


# 静的 URL のプレフィックス（main.py の static mount と一致させること）
LIBRARY_URL_PREFIX = "/library"


def _converted_root(lib_root: Optional[Path] = None) -> Path:
    """変換出力ルート (`{lib_root}/converted/`) を返す。

    lib_root 未指定時は library_settings から取得（GUI で変更された値が反映される）。
    """
    base = Path(lib_root) if lib_root else get_library_root()
    return base / converted_dir_name()


def _stem_url(stem: str, rel: str) -> str:
    """`/library/{stem}/{rel}` を返す。"""
    return f"{LIBRARY_URL_PREFIX}/{stem}/{rel}"


def _read_meta(stem_dir: Path) -> Optional[dict]:
    meta_path = stem_dir / "meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text())
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to read meta.json for %s: %s", stem_dir.name, exc)
        return None


def _format_label(source_filename: Optional[str], codec: Optional[str]) -> str:
    """表示用のフォーマット文字列。

    例:
      "video-a.mp4" + "h264" → "MP4 / H.264"
      "video-b.mkv" + "hevc" → "MKV / HEVC"
      拡張子のみ判明: "MP4"
      何も判明しない: ""
    """
    parts: list[str] = []
    if source_filename:
        suffix = Path(source_filename).suffix.lstrip(".").upper()
        if suffix:
            parts.append(suffix)
    if codec:
        c = codec.strip().lower()
        codec_label = {
            "h264": "H.264",
            "hevc": "HEVC",
            "h265": "HEVC",
            "vp9": "VP9",
            "av1": "AV1",
            "mpeg4": "MPEG-4",
            "mpeg2video": "MPEG-2",
        }.get(c, c.upper())
        if codec_label:
            parts.append(codec_label)
    return " / ".join(parts)


def _entry_for(
    stem_dir: Path,
    *,
    favorites: Optional[set[str]] = None,
) -> Optional[dict]:
    """1 stem ディレクトリ → API/GUI 用の dict。

    必須ファイル: hls/master.m3u8, thumbs/poster.png, meta.json
    どれか欠けるものは None を返す（変換途中扱い）。
    """
    if not (stem_dir / "hls" / "master.m3u8").exists():
        return None
    if not (stem_dir / "thumbs" / "poster.png").exists():
        return None
    meta = _read_meta(stem_dir)
    if not meta:
        return None

    stem = stem_dir.name
    frames_meta = (meta.get("thumbs") or {}).get("frames") or [
        {"percent": p, "file": f"thumbs/{thumb_filename(p)}"} for p in THUMB_PERCENTS
    ]
    thumbs = []
    for f in frames_meta:
        rel = f.get("file")
        if not rel:
            continue
        if not (stem_dir / rel).exists():
            continue
        thumbs.append({
            "percent": int(f.get("percent") or 0),
            "url": _stem_url(stem, rel),
        })

    source_filename = meta.get("source_filename") or stem
    codec = meta.get("codec") or ""
    container = Path(source_filename).suffix.lstrip(".").lower()  # "mp4", "mkv"...

    return {
        "id": stem,
        "title": source_filename,
        "duration": float(meta.get("duration") or 0.0),
        "width": int(meta.get("width") or 0),
        "height": int(meta.get("height") or 0),
        "container": container,
        "codec": codec,
        "format_label": _format_label(source_filename, codec),
        "is_favorite": stem in (favorites or set()),
        "master_url": _stem_url(stem, "hls/master.m3u8"),
        "poster_url": _stem_url(stem, "thumbs/poster.png"),
        "thumbs": thumbs,
    }


def list_videos(lib_root: Optional[Path] = None) -> list[dict]:
    """`{lib_root}/converted/*/` を走査して変換済み動画一覧を返す。"""
    root = _converted_root(lib_root)
    if not root.is_dir():
        return []

    favorites = load_favorites(lib_root)
    out: list[dict] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        item = _entry_for(entry, favorites=favorites)
        if item:
            out.append(item)
    return out


def get_video(video_id: str, lib_root: Optional[Path] = None) -> Optional[dict]:
    """単一 video_id（= stem）のエントリを返す。未変換 / 不在なら None。"""
    stem_dir = _converted_root(lib_root) / video_id
    if not stem_dir.is_dir():
        return None
    favorites = load_favorites(lib_root)
    return _entry_for(stem_dir, favorites=favorites)
