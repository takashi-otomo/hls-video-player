"""ライブラリフォルダを走査して未変換動画を HLS + サムネへ一括変換する CLI。

使い方:
  python -m hls_video.library_cli                       # ./library を処理
  python -m hls_video.library_cli /path/to/library      # 指定ディレクトリ
  python -m hls_video.library_cli -w 4                  # 4 並列
  python -m hls_video.library_cli --filter abc          # ファイル名フィルタ（部分一致）
  python -m hls_video.library_cli --force               # 既存出力を再生成

ts_merge_colab.py の体裁を踏襲。
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

from hls_video.library_converter import (
    VIDEO_EXTS, convert_one, is_already_converted, scan_library,
)
from hls_video.library_settings import get_library_root
from hls_video.logging_setup import setup_logging


def _log(msg: str, base: str = "") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = f"[{ts}]"
    if base:
        prefix += f" [{base}]"
    print(f"{prefix} {msg}", flush=True)


def _format_size(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024:
            return f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} TB"


def _process_one(src: Path, lib_root: Path, force: bool) -> dict:
    base = src.stem
    try:
        if not force and is_already_converted(base, lib_root):
            _log(f"⏭ スキップ (変換済): {src.name}", base)
            return {"base": base, "status": "skipped", "elapsed": 0.0}

        _log(f"🎬 変換開始: {src.name} ({_format_size(src.stat().st_size)})", base)
        result = convert_one(src, lib_root=lib_root, force=force)
        if result.skipped:
            _log(f"⏭ スキップ: {src.name}", base)
            return {"base": base, "status": "skipped", "elapsed": 0.0}
        _log(
            f"✅ 完了: {src.name} → {result.output_dir.name}/ "
            f"({result.elapsed:.1f}s, dur={result.duration:.1f}s)",
            base,
        )
        return {"base": base, "status": "ok", "elapsed": result.elapsed}
    except Exception as e:  # noqa: BLE001 - CLI 用に全例外を収集
        _log(f"❌ エラー: {e}", base)
        return {"base": base, "status": "error", "elapsed": 0.0, "message": str(e)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ライブラリフォルダを走査して HLS + サムネへ一括変換",
    )
    parser.add_argument(
        "folder", nargs="?", default=None,
        help="ライブラリのルート (省略時は GUI 設定 → 環境変数 LIBRARY_ROOT → ./library の順で解決)",
    )
    parser.add_argument(
        "-w", "--workers", type=int, default=2,
        help="並列ワーカー数 (デフォルト: 2)",
    )
    parser.add_argument(
        "-f", "--force", action="store_true",
        help="既存の変換出力を再生成",
    )
    parser.add_argument(
        "--filter", type=str, default="",
        help="ファイル名フィルタ (部分一致)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="走査結果のみ表示し、変換は実行しない",
    )
    args = parser.parse_args(argv)

    setup_logging()

    lib_root = get_library_root(args.folder if args.folder else None)
    if not lib_root.is_dir():
        print(f"エラー: ディレクトリが存在しません: {lib_root}", file=sys.stderr)
        return 1

    _log(f"=== HLS Library Convert ===")
    _log(f"ライブラリ: {lib_root}")
    _log(f"出力先   : {lib_root}/converted/<stem>/")
    _log(f"並列数   : {args.workers}")
    _log(f"対象拡張子: {sorted(VIDEO_EXTS)}")
    print("", flush=True)

    sources = scan_library(lib_root)
    if args.filter:
        sources = [s for s in sources if args.filter in s.name]
        _log(f"フィルター '{args.filter}': {len(sources)} 件一致")

    if not sources:
        _log("対象ファイルが見つかりません")
        return 0

    targets: list[Path] = []
    skipped = 0
    for s in sources:
        if not args.force and is_already_converted(s.stem, lib_root):
            skipped += 1
            continue
        targets.append(s)

    _log(f"検出: {len(sources)} 件 / 変換対象: {len(targets)} 件 (スキップ: {skipped})")

    if args.dry_run:
        for s in sources:
            mark = "✓" if is_already_converted(s.stem, lib_root) else "○"
            _log(f"  {mark} {s.name} ({_format_size(s.stat().st_size)})")
        return 0

    if not targets:
        _log("処理対象がありません")
        return 0

    print("", flush=True)
    t0 = time.time()
    results = {"ok": 0, "skipped": skipped, "error": 0}

    workers = max(1, args.workers)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_process_one, src, lib_root, args.force): src
            for src in targets
        }
        for fut in as_completed(futures):
            r = fut.result()
            if r["status"] == "ok":
                results["ok"] += 1
            elif r["status"] == "skipped":
                results["skipped"] += 1
            else:
                results["error"] += 1

    elapsed = str(timedelta(seconds=int(time.time() - t0)))
    print("", flush=True)
    _log("=== 結果 ===")
    _log(
        f"完了: {results['ok']} 件  "
        f"スキップ: {results['skipped']} 件  "
        f"エラー: {results['error']} 件  "
        f"所要時間: {elapsed}"
    )
    return 0 if results["error"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
