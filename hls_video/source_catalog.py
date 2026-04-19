"""`media/source/` のファイル一覧を変換状態つきで返す。

Node 側 utils/sourceCatalog.js と等価。変換済みのエントリには
video_catalog.resolve_sprite の結果（カードサムネイル用）を埋め込む。

ソース MP4 を削除済みだが HLS 出力は残っている動画も列挙に含める
（source_deleted=True フラグ付き）。
"""

from __future__ import annotations

import os
import re
import shutil
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

    rows: list[dict] = []
    seen_video_ids: set[str] = set()

    # Pass 1: source/ 配下のファイル
    if source_dir.exists():
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
                "source_deleted": False,
            })
            seen_video_ids.add(video_id)

    # Pass 2: hls/ にあるが source/ にはないものを source_deleted として追加
    if hls_dir.exists():
        for hls_entry in hls_dir.iterdir():
            if not hls_entry.is_dir():
                continue
            video_id = hls_entry.name
            if video_id in seen_video_ids:
                continue
            if not (hls_entry / "master.m3u8").exists():
                continue
            sprite = resolve_sprite(str(sprites_dir), video_id)
            rows.append({
                "filename": f"{video_id}.mp4",      # 表示用の便宜名
                "video_id": video_id,
                "size_bytes": 0,                     # 本体なし
                "modified_at": datetime.fromtimestamp(
                    hls_entry.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
                "converted": True,
                "sprite": sprite,
                "source_deleted": True,
            })

    return sorted(rows, key=lambda r: r["filename"])


def delete_source_file(media_root: str, filename: str) -> dict:
    """media/source/<filename> を安全に削除する。

    HLS 出力 (media/hls/<video_id>/) とスプライトは削除しない。変換後の MP4
    クリーンアップ用途。

    戻り値 dict:
      - ok (bool)
      - message (str)
      - filename (str | None)
    """
    source_dir = Path(media_root) / "source"
    target = (source_dir / filename).resolve()
    source_root = source_dir.resolve()

    # パストラバーサル防御: target が source_dir 配下でなければ拒否
    try:
        target.relative_to(source_root)
    except ValueError:
        return {"ok": False, "message": "無効なパスです（source/ の外）", "filename": filename}

    if not target.exists():
        return {"ok": False, "message": f"ファイルが見つかりません: {filename}", "filename": filename}

    # symlink / 通常ファイルいずれも unlink で OK（ディレクトリは拒否）
    if target.is_dir() and not target.is_symlink():
        return {"ok": False, "message": "ディレクトリは削除できません", "filename": filename}

    try:
        target.unlink()
    except OSError as e:
        return {"ok": False, "message": f"削除失敗: {e}", "filename": filename}

    return {
        "ok": True,
        "message": f"{filename} を削除しました（HLS と スプライトは保持）",
        "filename": filename,
    }
