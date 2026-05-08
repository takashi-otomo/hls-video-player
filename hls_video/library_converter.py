"""フォルダ走査モデル用の変換オーケストレータ。

入力: ライブラリルート + 1 本の動画ファイルパス
出力: `{library_root}/{converted_dir}/{stem}/{hls,thumbs,meta.json}`

- HLS 変換: hls_converter.convert_mp4_to_hls
- サムネ: thumbnail_generator.generate_thumbnails (5 枚 + poster.png)
- メタ: meta.json に duration / thumbs[] / hls master 相対パス等を書き出し

中断検出 (重要):
- 変換開始時に `.converting` マーカーファイルを作成し、正常終了時のみ削除する
- `is_already_converted` はマーカーが残っているものは未完了扱いで再変換対象に
- これによりプロセス kill / OOM / kernel リセットなどによる中途半端出力を確実に検出
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from hls_video.config import library_root, converted_dir_name
from hls_video import converted_index
from hls_video.ffmpeg_runner import probe_duration_seconds, probe_video_stream
from hls_video.hls_converter import convert_mp4_to_hls
from hls_video.thumbnail_generator import (
    THUMB_PERCENTS, generate_thumbnails, thumb_filename,
)

logger = logging.getLogger(__name__)

VIDEO_EXTS: frozenset[str] = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v"})

# 変換中マーカー: 開始時に作成、正常終了時のみ削除
CONVERTING_MARKER = ".converting"


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


def is_converting(stem: str, lib_root: Optional[Path] = None) -> bool:
    """変換中マーカーがあるか判定。中断された変換を検出するために使う。"""
    return (output_dir_for(stem, lib_root) / CONVERTING_MARKER).exists()


def is_already_converted(
    stem: str,
    lib_root: Optional[Path] = None,
    *,
    source_path: Optional[Path] = None,
    index_data: Optional[dict] = None,
    use_index: bool = True,
) -> bool:
    """変換が完全に終了しているか判定。

    高速パス (use_index=True かつ source_path 指定):
      - converted/.index.json に stem があり、かつ元動画の (size, mtime) が
        記録と一致 → 即 True (FS stat なし)
      - これにより N 動画のスキャンが O(N) hash lookup に短縮される

    厳格 FS パス (use_index=False、または index miss 時):
      - .converting マーカー無し
      - hls/master.m3u8
      - thumbs/poster.png
      - thumbs/thumb_{05,30,50,60,80}.jpg (5 枚すべて)
      - meta.json (parse 可能)
    """
    # 高速パス: インデックスを参照 (3 状態)
    if use_index and source_path is not None:
        status = converted_index.index_status(
            stem, Path(source_path), lib_root=lib_root, data=index_data,
        )
        if status == converted_index.STATUS_MATCH:
            # マーカーが残っていれば中断扱いに格下げ (安全側)
            if (output_dir_for(stem, lib_root) / CONVERTING_MARKER).exists():
                return False
            return True
        if status == converted_index.STATUS_STALE:
            # 元動画が変わっている / 消えている → 古い出力は再変換対象
            return False
        # STATUS_UNKNOWN → 厳格 FS パスにフォールスルー
        # (旧バージョンでの変換済みも index 化されていない可能性があるため)

    # 厳格 FS パス
    out = output_dir_for(stem, lib_root)
    if (out / CONVERTING_MARKER).exists():
        return False
    if not (out / "hls" / "master.m3u8").exists():
        return False
    if not (out / "thumbs" / "poster.png").exists():
        return False
    thumbs_dir = out / "thumbs"
    for p in THUMB_PERCENTS:
        if not (thumbs_dir / thumb_filename(p)).exists():
            return False
    meta_path = out / "meta.json"
    if not meta_path.exists():
        return False
    try:
        json.loads(meta_path.read_text() or "{}")
    except Exception:
        return False
    return True


def _cleanup_partial_output(out_dir: Path) -> None:
    """中途半端な出力 (hls/, thumbs/, meta.json) を削除する。マーカーは触らない。"""
    for sub in ("hls", "thumbs"):
        target = out_dir / sub
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    meta_path = out_dir / "meta.json"
    if meta_path.exists():
        try:
            meta_path.unlink()
        except OSError:
            pass


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
    中断マーカー (`.converting`) が残っているものは中途半端な出力を掃除して再変換する。
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
    marker = out_dir / CONVERTING_MARKER

    if not force and is_already_converted(stem, lib_root, source_path=src):
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

    # 中途半端な出力を完全クリーンアップ (中断分 / force / 不完全状態いずれにも対応)
    interrupted = marker.exists()
    if interrupted:
        logger.warning("found interrupted conversion marker for %s — cleaning up", stem)
    _cleanup_partial_output(out_dir)

    hls_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    # 中断マーカーを立てる (失敗時に残れば次回の再変換対象になる)
    marker.write_text(
        json.dumps({
            "started_at": datetime.now(tz=timezone.utc).isoformat(),
            "source": src.name,
        }, ensure_ascii=False)
    )

    t0 = time.monotonic()
    logger.info("convert start: %s → %s%s", src, out_dir,
                " (resume from interrupted)" if interrupted else "")

    try:
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
    except BaseException:
        # 失敗 / 中断時はマーカーをそのまま残す → 次回 CLI で再変換対象になる
        raise

    # 全工程成功 → マーカー削除して「変換済み」状態にする
    try:
        marker.unlink()
    except OSError:
        pass

    # インデックス更新 (次回 CLI 起動時に O(1) で完了判定)
    try:
        converted_index.mark_complete(stem, src, lib_root=lib_root)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to update converted index for %s: %s", stem, exc)

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
