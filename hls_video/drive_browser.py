"""Google Drive（もしくは任意のローカルパス）配下にある動画ファイルを走査して、
`media/source/` にコピーで取り込むヘルパ。

Colab + Drive mount 環境では、ユーザーの動画は既に `/content/drive/MyDrive/...`
に存在している。ファイル選択ダイアログ（ブラウザアップロード）を使うと
一度 PC を経由してしまい非効率。本モジュールは Drive のパスを直接参照し、
`media/source/` にコピー取り込みすることでブラウザ往復を回避する。

※ Drive FUSE は symlink を拒否する (Errno 95 Operation not supported) ため、
   実コピーで統一する。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import NamedTuple

from hls_video.source_catalog import VIDEO_EXTS


class BrowseEntry(NamedTuple):
    path: str        # 絶対パス
    rel: str         # ブラウズルートからの相対パス（UI 表示用）
    size_bytes: int
    mtime: float     # 更新時刻（epoch 秒）
    already_imported: bool = False  # media/source/ に同名ファイルが既にあるか


def list_videos_under(
    root: str,
    *,
    max_depth: int = 3,
    media_root: str | None = None,
) -> list[BrowseEntry]:
    """root 配下を再帰的に走査し、動画拡張子のファイルを返す。

    - シンボリックリンクは辿らない（無限ループ回避）
    - 非表示ディレクトリ（`.` 始まり）、`node_modules`, `__pycache__` はスキップ
    - max_depth で深さ制限（Drive の巨大ツリー誤走査対策）
    - media_root が指定されていれば、`media_root/source/<filename>` の存在を調べ、
      already_imported フラグを立てる
    """
    base = Path(root)
    if not base.is_dir():
        return []

    skip_names = {"node_modules", "__pycache__", ".git", ".claude", ".venv"}
    imported_names: set[str] = set()
    if media_root:
        source_dir = Path(media_root) / "source"
        if source_dir.is_dir():
            for f in source_dir.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    imported_names.add(f.name)

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
                        st = entry.stat()
                        size = st.st_size
                        mtime = st.st_mtime
                    except OSError:
                        size, mtime = 0, 0.0
                    results.append(BrowseEntry(
                        path=str(entry.resolve()),
                        rel=str(entry.relative_to(base)),
                        size_bytes=size,
                        mtime=mtime,
                        already_imported=entry.name in imported_names,
                    ))
            elif entry.is_dir():
                walk(entry, depth + 1)

    walk(base, 0)
    return results


def import_file(src_path: str, media_root: str, *, overwrite: bool = False) -> dict:
    """任意のパスにある動画ファイルを `media/source/` にコピー取り込み。

    Drive FUSE は symlink を受け付けないため実コピーで統一。
    large file を想定して `shutil.copy2` (メタデータ保持) を使う。

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
                "message": f"既に {src.name} が media/source/ にあります（overwrite=True で上書き）",
                "filename": src.name,
            }
        if dst.is_symlink() or dst.is_file():
            dst.unlink()

    shutil.copy2(str(src.resolve()), str(dst))
    return {
        "ok": True,
        "message": f"{src.name} を media/source/ にコピーしました",
        "filename": src.name,
    }


# 後方互換のために旧名を残すが、新規コードは import_file を使うこと
import_as_symlink = import_file
