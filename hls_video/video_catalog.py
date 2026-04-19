"""変換済み動画（master.m3u8 を持つ）の一覧取得とスプライト情報の解決。

Node 側 utils/videoCatalog.js と等価。
UI は常に `sheets[]` 配列を通じてスプライトシートを参照する。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


def list_videos(media_root: str) -> list[dict]:
    hls_root = Path(media_root) / "hls"
    sprites_root = Path(media_root) / "sprites"
    if not hls_root.exists():
        return []

    videos: list[dict] = []
    for entry in sorted(hls_root.iterdir()):
        if not entry.is_dir():
            continue
        master = entry / "master.m3u8"
        if not master.exists():
            continue
        video_id = entry.name
        videos.append({
            "id": video_id,
            "title": video_id,
            "master_url": f"/hls/{video_id}/master.m3u8",
            "sprite": resolve_sprite(str(sprites_root), video_id),
        })
    return videos


def resolve_sprite(sprites_root: str, video_id: str) -> Optional[dict]:
    meta_path = Path(sprites_root) / f"{video_id}.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text())
    except Exception:
        return None

    sheet_count = max(1, int(meta.get("sheetCount") or 1))
    sheets: list[str] = []
    if sheet_count == 1:
        if (Path(sprites_root) / f"{video_id}.jpg").exists():
            sheets.append(f"/sprites/{video_id}.jpg")
    else:
        for i in range(1, sheet_count + 1):
            if (Path(sprites_root) / f"{video_id}-{i}.jpg").exists():
                sheets.append(f"/sprites/{video_id}-{i}.jpg")

    if not sheets:
        return None

    vtt_path = Path(sprites_root) / f"{video_id}.vtt"
    return {
        "sheets": sheets,
        "sheet_count": len(sheets),
        "vtt_url": f"/sprites/{video_id}.vtt" if vtt_path.exists() else None,
        "tile_width": meta.get("tileWidth"),
        "tile_height": meta.get("tileHeight"),
        "columns": meta.get("columns"),
        "rows": meta.get("rows", 10),
        "interval": meta.get("interval"),
        "tile_count": meta.get("tileCount"),
    }
