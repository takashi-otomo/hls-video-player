"""Google Drive（もしくは任意のローカルパス）配下にある動画ファイルを走査して、
`media/source/` にシンボリックリンクで取り込むヘルパ。

Colab + Drive mount 環境では、ユーザーの動画は既に `/content/drive/MyDrive/...`
に存在している。ファイル選択ダイアログ（ブラウザアップロード）を使うと
一度 PC を経由してしまい非効率。本モジュールは Drive のパスを直接参照し、
symlink 経由で取り込むことで転送を回避する。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import NamedTuple

from hls_video.source_catalog import VIDEO_EXTS


class BrowseEntry(NamedTuple):
    path: str      # 絶対パス
    rel: str       # ブラウズルートからの相対パス（UI 表示用）
    size_bytes: int


def list_videos_under(root: str, *, max_depth: int = 3) -> list[BrowseEntry]:
    """root 配下を再帰的に走査し、動画拡張子のファイルを返す。

    - シンボリックリンクは辿らない（無限ループ回避）
    - 非表示ディレクトリ（`.` 始まり）、`node_modules`, `__pycache__` はスキップ
    - max_depth で深さ制限（Drive の巨大ツリー誤走査対策）
    """
    base = Path(root)
    if not base.is_dir():
        return []

    skip_names = {"node_modules", "__pycache__", ".git", ".claude", ".venv"}
    results: list[BrowseEntry] = []

    def walk(d: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda p: (not p.is_file(), p.name.lower()))
        except (PermissionError, OSError):
            return
        for entry in entries:
            if entry.name.startswith(".") or entry.name in skip_names:
                continue
            if entry.is_symlink():
                continue
            if entry.is_file():
                if entry.suffix.lower() in VIDEO_EXTS:
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        size = 0
                    results.append(BrowseEntry(
                        path=str(entry.resolve()),
                        rel=str(entry.relative_to(base)),
                        size_bytes=size,
                    ))
            elif entry.is_dir():
                walk(entry, depth + 1)

    walk(base, 0)
    return results


def import_as_symlink(src_path: str, media_root: str, *, overwrite: bool = False) -> dict:
    """任意のパスにある動画ファイルを `media/source/` にシンボリックリンクで取り込む。

    戻り値 dict:
      - ok (bool)
      - message (str)
      - filename (str | None)
    """
    src = Path(src_path)
    if not src.is_file():
        return {"ok": False, "message": f"ファイルが見つかりません: {src_path}", "filename": None}
    if src.suffix.lower() not in VIDEO_EXTS:
        return {
            "ok": False,
            "message": f"対応外の拡張子です（{', '.join(sorted(VIDEO_EXTS))}）",
            "filename": None,
        }

    source_dir = Path(media_root) / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    dst = source_dir / src.name

    if dst.exists() or dst.is_symlink():
        if not overwrite:
            return {
                "ok": False,
                "message": f"既に {src.name} が media/source/ にあります（上書きするには overwrite=True）",
                "filename": src.name,
            }
        if dst.is_symlink() or dst.is_file():
            dst.unlink()

    os.symlink(src.resolve(), dst)
    return {"ok": True, "message": f"{src.name} を追加しました（シンボリックリンク）", "filename": src.name}
