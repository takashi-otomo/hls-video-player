"""`media/source/` のファイル一覧を変換状態つきで返す。

Node 側 utils/sourceCatalog.js と等価。変換済みのエントリには
video_catalog.resolve_sprite の結果（カードサムネイル用）を埋め込む。
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from hls_video.video_catalog import resolve_sprite

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_-]")


def resolve_video_id(filename: str) -> str:
    base = Path(filename).stem
    return _SANITIZE_RE.sub("_", base)


def list_sources(media_root: str) -> list[dict]:
    source_dir = Path(media_root) / "source"
    hls_dir = Path(media_root) / "hls"
    sprites_dir = Path(media_root) / "sprites"
    if not source_dir.exists():
        return []

    rows: list[dict] = []
    for entry in source_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in VIDEO_EXTS:
            continue

        stat = entry.stat()
        video_id = resolve_video_id(entry.name)
        converted = (hls_dir / video_id / "master.m3u8").exists()
        sprite = resolve_sprite(str(sprites_dir), video_id) if converted else None

        rows.append({
            "filename": entry.name,
            "video_id": video_id,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "converted": converted,
            "sprite": sprite,
        })

    return sorted(rows, key=lambda r: r["filename"])
