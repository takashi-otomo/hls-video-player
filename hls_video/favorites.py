"""お気に入り動画の永続化。

保存先: `{LIBRARY_ROOT}/favorites.json` （`converted/` と同じ階層）
ファイル形式:
    {"favorites": ["video-a", "video-c", ...]}

動画の stem (= 拡張子なしファイル名) のリスト。重複排除済み・ソート済みで保存。
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Optional

from hls_video.library_settings import get_library_root

logger = logging.getLogger(__name__)

FAVORITES_FILENAME = "favorites.json"

_LOCK = threading.RLock()


def favorites_path(lib_root: Optional[Path] = None) -> Path:
    return Path(lib_root or get_library_root()) / FAVORITES_FILENAME


def load_favorites(lib_root: Optional[Path] = None) -> set[str]:
    p = favorites_path(lib_root)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text() or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to read %s: %s", p, exc)
        return set()
    return {str(x) for x in (data.get("favorites") or []) if x}


def save_favorites(values: set[str], lib_root: Optional[Path] = None) -> Path:
    p = favorites_path(lib_root)
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {"favorites": sorted(values)},
                indent=2,
                ensure_ascii=False,
            )
        )
        tmp.replace(p)
    return p


def is_favorite(video_id: str, lib_root: Optional[Path] = None) -> bool:
    return video_id in load_favorites(lib_root)


def set_favorite(
    video_id: str,
    favorited: bool,
    lib_root: Optional[Path] = None,
) -> bool:
    """お気に入り状態を明示的に設定。返り値は保存後の状態。"""
    with _LOCK:
        favs = load_favorites(lib_root)
        if favorited:
            favs.add(video_id)
        else:
            favs.discard(video_id)
        save_favorites(favs, lib_root)
    return favorited


def toggle_favorite(
    video_id: str,
    lib_root: Optional[Path] = None,
) -> bool:
    """トグル。返り値は新しい状態（True=お気に入り化された）。"""
    with _LOCK:
        favs = load_favorites(lib_root)
        if video_id in favs:
            favs.discard(video_id)
            new_state = False
        else:
            favs.add(video_id)
            new_state = True
        save_favorites(favs, lib_root)
    logger.info("favorite %s: %s", video_id, "added" if new_state else "removed")
    return new_state
