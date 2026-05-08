"""
TS 動画 結合・変換ツール

分割 TS ファイル (`<base>_<n>-<total>.ts` / `<base>_part<n>.ts`) を結合し MP4 を生成する。
ffmpeg の concat demuxer を使用し、並列処理に対応。
20GB 超のグループは自動的に前半・後半に分割して結合する。

CLI 使い方:
  ts-merge                    # カレントディレクトリを処理
  ts-merge /path/to/folder    # 指定ディレクトリを処理
  ts-merge -w 4               # 4 並列
  ts-merge --ts               # TS 形式のまま結合 (MP4 変換しない)
  ts-merge --delete           # 結合後に元ファイルを削除
  ts-merge --filter abc123    # ベース名にフィルタ

GUI 起動:
  ts-merge --gui              # Tkinter GUI で状況可視化 + 再生
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path

# 分割ファイルパターン
PAT_NEW = re.compile(r"^(.+?)_(\d+)-(\d+)\.ts$")
PAT_OLD = re.compile(r"^(.+?)_part(\d+)\.ts$")

# 20GB を超えるグループは前半・後半に分割
SIZE_THRESHOLD = 20 * 1024 ** 3


def log(msg: str, base: str = ""):
    """タイムスタンプ付きログ出力。"""
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = f"[{ts}]"
    if base:
        prefix += f" [{base[:8]}...]"
    print(f"{prefix} {msg}", flush=True)


def format_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def check_ffmpeg():
    """ffmpegの存在確認。"""
    if not shutil.which("ffmpeg"):
        print("エラー: ffmpeg が見つかりません", file=sys.stderr)
        print("  Colab: !apt-get install -y ffmpeg", file=sys.stderr)
        sys.exit(1)


def scan_folder(folder: Path) -> dict[str, dict]:
    """フォルダを走査し、ベース名ごとに分割ファイル情報を返す。"""
    groups: dict[str, dict] = {}

    for entry in sorted(folder.iterdir()):
        if not entry.is_file() or not entry.name.endswith(".ts"):
            continue

        m = PAT_NEW.match(entry.name)
        if m:
            base = m.group(1)
            part_num = int(m.group(2))
            total = int(m.group(3))
            if base not in groups:
                groups[base] = {"parts": [], "total": total, "format": "new"}
            groups[base]["parts"].append({
                "path": str(entry),
                "name": entry.name,
                "num": part_num,
                "size": entry.stat().st_size,
            })
            continue

        m = PAT_OLD.match(entry.name)
        if m:
            base = m.group(1)
            part_num = int(m.group(2))
            if base not in groups:
                groups[base] = {"parts": [], "total": None, "format": "old"}
            groups[base]["parts"].append({
                "path": str(entry),
                "name": entry.name,
                "num": part_num,
                "size": entry.stat().st_size,
            })
            continue

        # 単体TS (パート番号なし: uuid.ts) → 未変換の単体として扱う
        base_name = entry.stem  # 拡張子なしのファイル名
        if base_name not in groups:
            mp4_path = folder / f"{base_name}.mp4"
            # 分割MP4もチェック
            has_split_mp4 = (folder / f"{base_name}_1.mp4").exists()
            if not mp4_path.exists() and not has_split_mp4:
                groups[base_name] = {
                    "parts": [{
                        "path": str(entry),
                        "name": entry.name,
                        "num": 1,
                        "size": entry.stat().st_size,
                    }],
                    "total": 1,
                    "format": "single",
                }

    # ソート + 完全性チェック
    for base, info in groups.items():
        info["parts"].sort(key=lambda p: p["num"])
        info["total_size"] = sum(p["size"] for p in info["parts"])
        info["part_count"] = len(info["parts"])

        if info["format"] == "new" and info["total"] is not None:
            expected = set(range(1, info["total"] + 1))
            actual = {p["num"] for p in info["parts"]}
            info["complete"] = actual == expected
            info["missing"] = sorted(expected - actual)
        else:
            nums = [p["num"] for p in info["parts"]]
            if nums:
                expected = set(range(min(nums), max(nums) + 1))
                info["complete"] = set(nums) == expected
                info["missing"] = sorted(expected - set(nums))
            else:
                info["complete"] = False
                info["missing"] = []

        # 結合済みファイル確認
        mp4_path = folder / f"{base}.mp4"
        ts_path = folder / f"{base}.ts"
        info["has_mp4"] = mp4_path.exists()
        info["has_ts"] = ts_path.exists()

    return groups


def run_ffmpeg(cmd: list[str], base: str) -> tuple[int, str]:
    """ffmpegをPopenで実行し、進捗をリアルタイム出力する。タイムアウトなし。"""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # stderrから進捗を読み取る (ffmpeg -stats の出力先)
    stderr_lines = []
    for line in proc.stderr:
        line = line.rstrip()
        if line:
            stderr_lines.append(line)
            # 進捗行 (frame=, size=, time= 等) をログ表示
            if "time=" in line or "size=" in line:
                log(f"  ffmpeg: {line}", base)
    proc.wait()
    return proc.returncode, "\n".join(stderr_lines[-10:])


def _merge_parts(
    parts: list[str],
    output: Path,
    keep_ts: bool,
    base: str,
    expected_size: int | None = None,
) -> dict:
    """パートリストを1つのファイルに結合する。成功時 {"status":"ok"}, 失敗時 {"status":"error"}。"""
    result = {"status": "ok", "message": ""}

    if keep_ts:
        with open(str(output), "wb") as out_f:
            for p in parts:
                with open(p, "rb") as in_f:
                    shutil.copyfileobj(in_f, out_f, length=1024 * 1024)
        if expected_size is not None:
            out_size = output.stat().st_size
            if out_size != expected_size:
                output.unlink(missing_ok=True)
                result["status"] = "error"
                result["message"] = f"サイズ不一致: {out_size} != {expected_size}"
                return result
    else:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as concat_f:
            for p in parts:
                concat_f.write(f"file '{p}'\n")
            concat_list = concat_f.name

        with tempfile.NamedTemporaryFile(
            suffix=".mp4", delete=False
        ) as tmp_f:
            tmp_output = tmp_f.name

        try:
            cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                "-movflags", "+faststart",
                "-y",
                "-loglevel", "warning",
                "-stats",
                tmp_output,
            ]
            returncode, stderr = run_ffmpeg(cmd, base)
            if returncode != 0:
                result["status"] = "error"
                result["message"] = stderr.strip()[:200]
                return result
            shutil.move(tmp_output, str(output))
        finally:
            for f in [concat_list, tmp_output]:
                try:
                    os.unlink(f)
                except OSError:
                    pass

    return result


def merge_one(
    base: str,
    info: dict,
    folder: Path,
    keep_ts: bool,
    force: bool,
    delete_parts: bool,
) -> dict:
    """1グループの結合処理。スレッドセーフ。"""
    result = {"base": base, "status": "ok", "message": ""}
    ext = "ts" if keep_ts else "mp4"
    output = folder / f"{base}.{ext}"

    # スキップ判定
    if output.exists() and not force:
        result["status"] = "skipped"
        result["message"] = f"既に存在: {base}.{ext}"
        return result

    # 完全性チェック
    if not info["complete"]:
        missing = info["missing"][:5]
        missing_str = ", ".join(str(m) for m in missing)
        if len(info["missing"]) > 5:
            missing_str += f" ... 他{len(info['missing']) - 5}件"
        if not force:
            result["status"] = "skipped"
            result["message"] = f"不完全 (欠落: {missing_str}) → --force で強制結合"
            log(f"⏭ 不完全のためスキップ (欠落: {missing_str})", base)
            return result
        log(f"⚠ 不完全 (欠落: {missing_str}) → 強制結合", base)

    parts = [p["path"] for p in info["parts"]]
    total_size = info["total_size"]
    part_count = info["part_count"]

    log(f"🔗 結合開始: {part_count}パート, {format_size(total_size)}", base)
    start = time.time()

    try:
        # 20GB超かつ2パート以上 → 前半・後半に分割
        if total_size > SIZE_THRESHOLD and part_count >= 2:
            if part_count % 2 == 0:
                # 偶数: 均等分割 (4→2+2)
                split_idx = part_count // 2
            else:
                # 奇数: 前半少なく、後半多く (3→1+2, 5→2+3)
                split_idx = part_count // 2

            front_parts = parts[:split_idx]
            back_parts = parts[split_idx:]
            front_size = sum(
                info["parts"][i]["size"] for i in range(split_idx)
            )
            back_size = total_size - front_size

            log(
                f"📦 20GB超 → 分割結合: _1({len(front_parts)}パート,"
                f" {format_size(front_size)}) + _2({len(back_parts)}パート,"
                f" {format_size(back_size)})",
                base,
            )

            outputs = []
            for label, sub_parts, sub_size in [
                ("_1", front_parts, front_size),
                ("_2", back_parts, back_size),
            ]:
                num = 1 if label == "_1" else 2
                sub_output = folder / f"{base}_{num}.{ext}"

                if sub_output.exists() and not force:
                    log(f"⏭ スキップ (既に存在): {sub_output.name}", base)
                    outputs.append(sub_output)
                    continue

                log(f"🔗 {label}結合中: {len(sub_parts)}パート, {format_size(sub_size)}", base)
                expected = sub_size if keep_ts else None
                sub_result = _merge_parts(
                    sub_parts, sub_output, keep_ts, base, expected
                )
                if sub_result["status"] == "error":
                    result["status"] = "error"
                    result["message"] = f"{label}: {sub_result['message']}"
                    return result
                outputs.append(sub_output)

            elapsed = time.time() - start
            out_sizes = [o.stat().st_size for o in outputs if o.exists()]
            total_out = sum(out_sizes)
            filenames = ", ".join(o.name for o in outputs)
            log(
                f"✅ 完了: {filenames} (合計 {format_size(total_out)})"
                f" [{elapsed:.1f}秒]",
                base,
            )
            result["message"] = f"{filenames} ({format_size(total_out)})"

        else:
            # 通常の1ファイル結合
            expected = total_size if keep_ts else None
            sub_result = _merge_parts(parts, output, keep_ts, base, expected)
            if sub_result["status"] == "error":
                result["status"] = "error"
                result["message"] = sub_result["message"]
                return result

            elapsed = time.time() - start
            out_size = output.stat().st_size
            log(
                f"✅ 完了: {base}.{ext} ({format_size(out_size)})"
                f" [{elapsed:.1f}秒]",
                base,
            )
            result["message"] = f"{base}.{ext} ({format_size(out_size)})"

        # 元ファイル削除
        if delete_parts:
            for p in parts:
                try:
                    os.unlink(p)
                except OSError:
                    pass
            log(f"🗑 元ファイル削除: {part_count}ファイル", base)

    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)[:200]
        log(f"❌ エラー: {e}", base)

    return result


def build_parser() -> argparse.ArgumentParser:
    """ts-merge CLI の ArgumentParser。GUI ディスパッチ側からも参照する。"""
    parser = argparse.ArgumentParser(
        prog="ts-merge",
        description="TS動画 結合・変換ツール (--gui で Tkinter GUI 起動)",
    )
    parser.add_argument(
        "folder", nargs="?", default=".",
        help="処理対象のディレクトリ (デフォルト: カレント)",
    )
    parser.add_argument(
        "-w", "--workers", type=int, default=2,
        help="並列ワーカー数 (デフォルト: 2)",
    )
    parser.add_argument(
        "-t", "--ts", action="store_true",
        help="TS形式のまま結合 (MP4変換しない)",
    )
    parser.add_argument(
        "-d", "--delete", action="store_true",
        help="結合後に元ファイルを削除",
    )
    parser.add_argument(
        "-f", "--force", action="store_true",
        help="既存ファイルを上書き",
    )
    parser.add_argument(
        "--filter", type=str, default="",
        help="ベース名フィルター (部分一致)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    folder = Path(args.folder).resolve()
    if not folder.is_dir():
        print(f"エラー: ディレクトリが見つかりません: {folder}", file=sys.stderr)
        return 1

    keep_ts = args.ts
    if not keep_ts:
        check_ffmpeg()

    mode_label = "TS結合" if keep_ts else "MP4変換"
    log(f"=== TS Merge ({mode_label}) ===")
    log(f"フォルダ: {folder}")
    log(f"並列数: {args.workers}")
    print("", flush=True)

    # スキャン
    groups = scan_folder(folder)

    # フィルター適用
    if args.filter:
        groups = {
            b: info for b, info in groups.items()
            if args.filter in b
        }
        log(f"フィルター '{args.filter}': {len(groups)}件一致")

    if not groups:
        log("分割ファイルが見つかりません")
        return 0

    # 未処理のもののみ抽出 (--force でなければスキップ)
    targets = {}
    skipped = 0
    for base, info in sorted(groups.items()):
        ext = "ts" if keep_ts else "mp4"
        output = folder / f"{base}.{ext}"
        if output.exists() and not args.force:
            skipped += 1
            continue
        targets[base] = info

    log(f"対象: {len(targets)}件 (スキップ: {skipped}件)")
    if not targets:
        log("処理対象がありません")
        return 0

    # サマリー表示
    total_parts = sum(info["part_count"] for info in targets.values())
    total_size = sum(info["total_size"] for info in targets.values())
    incomplete = sum(1 for info in targets.values() if not info["complete"])
    log(
        f"合計: {total_parts}パート, {format_size(total_size)}"
        + (f" (不完全: {incomplete}件)" if incomplete else "")
    )
    print("", flush=True)

    # 並列処理
    start_all = time.time()
    results = {"ok": 0, "skipped": 0, "error": 0}

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {}
        for base, info in sorted(targets.items()):
            future = executor.submit(
                merge_one, base, info, folder,
                keep_ts, args.force, args.delete,
            )
            futures[future] = base

        for future in as_completed(futures):
            result = future.result()
            results[result["status"]] += 1
            if result["status"] == "error":
                log(f"❌ {result['base']}: {result['message']}")

    # 結果サマリー
    elapsed = time.time() - start_all
    elapsed_str = str(timedelta(seconds=int(elapsed)))
    print("", flush=True)
    log("=== 結果 ===")
    log(
        f"完了: {results['ok']}件"
        f"  スキップ: {results['skipped'] + skipped}件"
        f"  エラー: {results['error']}件"
        f"  所要時間: {elapsed_str}"
    )
    return 0 if results["error"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
