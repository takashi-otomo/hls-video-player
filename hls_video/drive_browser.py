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

import logging
import shutil
import time
from pathlib import Path
from typing import NamedTuple

from hls_video.source_catalog import VIDEO_EXTS, resolve_video_id

logger = logging.getLogger(__name__)


class BrowseEntry(NamedTuple):
    path: str        # 絶対パス
    rel: str         # ブラウズルートからの相対パス（UI 表示用）
    size_bytes: int
    mtime: float     # 更新時刻（epoch 秒）
    # 重複判定: 下記いずれかに該当すれば True
    #   - 同名ファイルが media_root/source/<filename> に既にある
    #   - resolve_video_id(filename) に対応する変換済み (hls/<video_id>/master.m3u8) がある
    already_imported: bool = False


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
    - media_root が指定されていれば、下記いずれかに該当するファイルに
      already_imported=True を立てる:
        1) 同じファイル名が media_root/source/ にある
        2) 対応する video_id が変換済み (media_root/hls/<id>/master.m3u8 あり)
    """
    base = Path(root)
    if not base.is_dir():
        return []

    skip_names = {"node_modules", "__pycache__", ".git", ".claude", ".venv"}

    # 重複判定用ルックアップ
    imported_names: set[str] = set()
    converted_video_ids: set[str] = set()
    if media_root:
        source_dir = Path(media_root) / "source"
        if source_dir.is_dir():
            for f in source_dir.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    imported_names.add(f.name)
        hls_dir = Path(media_root) / "hls"
        if hls_dir.is_dir():
            for d in hls_dir.iterdir():
                if d.is_dir() and (d / "master.m3u8").exists():
                    converted_video_ids.add(d.name)

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
                    vid = resolve_video_id(entry.name)
                    duplicate = (
                        entry.name in imported_names
                        or vid in converted_video_ids
                    )
                    results.append(BrowseEntry(
                        path=str(entry.resolve()),
                        rel=str(entry.relative_to(base)),
                        size_bytes=size,
                        mtime=mtime,
                        already_imported=duplicate,
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


def purge_stale_staging(staging_dir: str, *, older_than_seconds: int = 3600) -> int:
    """ステージング領域で N 秒以上前にコピーされた孤児ファイルを削除する。

    Colab ランタイム切断などで `run_conversion` の finally が走らず残った
    staged ファイルの回収用。

    - 動作中のジョブ（同じ staging を使っている）を誤って消さないよう、
      `older_than_seconds` (既定 1 時間) のしきい値を設ける。
    - 拡張子が `VIDEO_EXTS` のものだけを対象。ログや隠しファイルは触らない。
    - 返り値: 削除したファイル数。
    """
    out_dir = Path(staging_dir)
    if not out_dir.is_dir():
        return 0
    cutoff = time.time() - older_than_seconds
    removed = 0
    for p in out_dir.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in VIDEO_EXTS:
            continue
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                logger.info("purged stale staging file: %s", p)
                removed += 1
        except OSError as e:
            logger.warning("failed to purge %s: %s", p, e)
    return removed


def stage_to_local(src_path: str, staging_dir: str) -> dict:
    """Drive 上の動画ファイルを Colab ローカル SSD (ステージング領域) にコピーする。

    Drive FUSE は sequential read が遅いので、ffmpeg に渡す前に一度ローカルへ
    コピーしてから変換する。戻り値の `path` を run_conversion(source_path=...) に渡す。

    副作用: ステージング前に `purge_stale_staging` を呼び、1 時間以上前の
    取り残し (前回ランタイムでクラッシュしたジョブ等) を掃除する。

    戻り値 dict:
      - ok (bool)
      - message (str)
      - path (str | None)  ステージ後のローカル絶対パス
      - filename (str | None)
    """
    src = Path(src_path)
    if not src.is_file():
        return {"ok": False, "message": f"ファイルが見つかりません: {src_path}",
                "path": None, "filename": None}
    if src.suffix.lower() not in VIDEO_EXTS:
        return {
            "ok": False,
            "message": f"対応外の拡張子です（{', '.join(sorted(VIDEO_EXTS))}）",
            "path": None, "filename": None,
        }

    out_dir = Path(staging_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 前回の取り残し掃除（他ジョブの staged ファイルを壊さないよう 1h しきい値）
    purge_stale_staging(str(out_dir))

    dst = out_dir / src.name
    size_mb = src.stat().st_size / (1024 * 1024)

    logger.info("staging %.1f MB: %s -> %s", size_mb, src, dst)
    t0 = time.monotonic()
    # 既に同じサイズで存在するなら再コピー省略（再試行時の時短）
    if dst.exists() and dst.stat().st_size == src.stat().st_size:
        logger.info("staging skipped (already present): %s", dst)
    else:
        shutil.copy2(str(src), str(dst))
    elapsed = time.monotonic() - t0
    if elapsed > 0:
        logger.info("staging done in %.1fs (%.1f MB/s)", elapsed, size_mb / max(elapsed, 0.001))
    return {
        "ok": True,
        "message": f"{src.name} を {out_dir} にコピー ({elapsed:.1f}s)",
        "path": str(dst),
        "filename": src.name,
    }
