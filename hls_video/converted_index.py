"""変換済み動画のインデックス。

`{lib_root}/{converted_dir}/.index.json` に「変換済みステム」を記録し、
CLI 起動時の「既変換判定」を O(1) で済ませる。Drive FUSE のように stat が
遅い環境で、毎回 7 ファイル × N 動画の存在チェックが致命的に遅くなるのを回避。

エントリ形式:
    {
      "version": 1,
      "completed": {
        "<stem>": {
          "size":  12345,         # 元動画のバイト数 (mp4 など)
          "mtime": 1715123456.0,  # 元動画の修正時刻 (epoch sec)
          "completed_at": "2026-05-08T11:22:33+00:00",
          "source": "video-a.mp4"
        },
        ...
      }
    }

判定ルール:
  - インデックスに stem があり、かつ (size, mtime) が現在の元動画と一致 → 完了とみなす
  - mtime が変わっていれば「上書きされた / 別動画」として再変換扱い
  - インデックス自体が壊れていたら空扱いで再構築 (FS から rebuild_from_fs)
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hls_video.config import converted_dir_name
from hls_video.library_settings import get_library_root

logger = logging.getLogger(__name__)

INDEX_FILENAME = ".index.json"
INDEX_VERSION = 1

# mtime 比較の許容誤差。Drive FUSE では mtime の精度が秒単位なので 1s。
_MTIME_EPSILON = 1.0

_LOCK = threading.RLock()


def index_path(lib_root: Optional[Path] = None) -> Path:
    base = Path(lib_root) if lib_root else get_library_root()
    return base / converted_dir_name() / INDEX_FILENAME


def _empty() -> dict:
    return {"version": INDEX_VERSION, "completed": {}}


def load(lib_root: Optional[Path] = None) -> dict:
    """インデックスを読み込む。存在しない / 破損していれば空 dict を返す。"""
    p = index_path(lib_root)
    if not p.exists():
        return _empty()
    try:
        data = json.loads(p.read_text() or "{}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("converted index parse failed (%s); treating as empty", exc)
        return _empty()
    if data.get("version") != INDEX_VERSION:
        # 互換性ない → 一旦空扱い (CLI 側で rebuild)
        logger.info(
            "converted index version mismatch (%s != %s); treating as empty",
            data.get("version"), INDEX_VERSION,
        )
        return _empty()
    if not isinstance(data.get("completed"), dict):
        return _empty()
    return data


def save(data: dict, lib_root: Optional[Path] = None) -> None:
    """インデックスをアトミックに保存する (.tmp → rename)。"""
    p = index_path(lib_root)
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        tmp.replace(p)


# インデックス参照結果の 3 状態
STATUS_MATCH = "match"      # index に登録あり + 元動画とマッチ → 変換済確定
STATUS_STALE = "stale"      # index に登録あり + 元動画が変わっている → 要再変換
STATUS_UNKNOWN = "unknown"  # index に登録なし → 判定不能 (FS にフォールスルー)


def index_status(
    stem: str,
    source_path: Path,
    *,
    lib_root: Optional[Path] = None,
    data: Optional[dict] = None,
) -> str:
    """インデックスとの照合結果を 3 状態で返す。

    呼び出し側で何度もインデックスを読まないように `data` を渡せる。
    """
    if data is None:
        data = load(lib_root)
    entry = data.get("completed", {}).get(stem)
    if not entry:
        return STATUS_UNKNOWN
    try:
        stat = source_path.stat()
    except OSError:
        # 元動画が消えた → stale 扱い
        return STATUS_STALE
    if entry.get("size") != stat.st_size:
        return STATUS_STALE
    try:
        if abs(float(entry.get("mtime", 0.0)) - stat.st_mtime) > _MTIME_EPSILON:
            return STATUS_STALE
    except (TypeError, ValueError):
        return STATUS_STALE
    return STATUS_MATCH


def is_completed(
    stem: str,
    source_path: Path,
    *,
    lib_root: Optional[Path] = None,
    data: Optional[dict] = None,
) -> bool:
    """簡易 API: STATUS_MATCH のときだけ True。"""
    return index_status(
        stem, source_path, lib_root=lib_root, data=data,
    ) == STATUS_MATCH


def mark_complete(
    stem: str,
    source_path: Path,
    *,
    lib_root: Optional[Path] = None,
) -> None:
    """ある stem を完了として記録する。並列実行に配慮した RMW を排他制御する。"""
    try:
        stat = source_path.stat()
    except OSError as exc:
        logger.warning("could not stat %s for index: %s", source_path, exc)
        return
    with _LOCK:
        data = load(lib_root)
        data["completed"][stem] = {
            "size": int(stat.st_size),
            "mtime": float(stat.st_mtime),
            "completed_at": datetime.now(tz=timezone.utc).isoformat(),
            "source": source_path.name,
        }
        save(data, lib_root)


def remove(stem: str, *, lib_root: Optional[Path] = None) -> None:
    with _LOCK:
        data = load(lib_root)
        if stem in data.get("completed", {}):
            del data["completed"][stem]
            save(data, lib_root)


def rebuild_from_fs(lib_root: Optional[Path] = None) -> dict:
    """ファイルシステムを走査して index を再構築する。

    converted/{stem}/ を 1 つずつ見て、library_converter.is_already_converted の
    厳格 FS 判定 (マーカー / 5 枚サムネ / meta.json parse) をパスしたものだけ index 化。
    元動画が見つかれば (size, mtime) も記録する。
    """
    # 循環 import 回避のため遅延 import
    from hls_video.library_converter import (
        is_already_converted, scan_library, output_dir_for,
    )

    base = Path(lib_root) if lib_root else get_library_root()
    sources_by_stem = {p.stem: p for p in scan_library(base)}

    new_data = _empty()
    completed = new_data["completed"]

    converted_root = base / converted_dir_name()
    if not converted_root.is_dir():
        save(new_data, base)
        return new_data

    count = 0
    for entry in sorted(converted_root.iterdir()):
        if not entry.is_dir():
            continue
        stem = entry.name
        # 厳格 FS チェックで完了している stem だけ採用
        if not is_already_converted(stem, base, use_index=False):
            continue
        record: dict = {
            "completed_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        src = sources_by_stem.get(stem)
        if src is not None:
            try:
                st = src.stat()
                record["size"] = int(st.st_size)
                record["mtime"] = float(st.st_mtime)
                record["source"] = src.name
            except OSError:
                pass
        completed[stem] = record
        count += 1

    save(new_data, base)
    logger.info("converted index rebuilt: %d entries → %s", count, index_path(base))
    return new_data
