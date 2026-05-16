"""ダイジェスト用マルチサムネイル + 合成 poster の生成。

- 動画 duration の 5% / 30% / 50% / 60% / 80% 地点で 1 枚ずつ静止画を抽出 (JPG)
- 上記 5 枚を 3+2 グリッドで合成し、16:9 PNG を poster として出力

旧スプライト方式 (sprite_generator.py) は廃止。本モジュールがその代替。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from hls_video.config import ffmpeg_path
from hls_video.ffmpeg_runner import probe_duration_seconds, run_ffmpeg

logger = logging.getLogger(__name__)


# サムネ取得ポイント (動画 duration に対する比率)
THUMB_PERCENTS: tuple[int, ...] = (5, 30, 50, 60, 80)

# 各サムネ JPG の解像度（16:9）
THUMB_WIDTH = 426
THUMB_HEIGHT = 240

# poster.png（合成）の解像度（16:9）
POSTER_WIDTH = 1280
POSTER_HEIGHT = 720


@dataclass
class ThumbResult:
    poster_path: Path        # 合成 poster.png の絶対パス
    thumb_paths: list[Path]  # 各 % のサムネ JPG パス（THUMB_PERCENTS と同順）
    duration: float          # 動画尺 (秒)


def thumb_filename(percent: int) -> str:
    return f"thumb_{percent:02d}.jpg"


def _extract_one_thumb(
    *,
    input_path: str,
    timestamp: float,
    output_path: Path,
    width: int = THUMB_WIDTH,
    height: int = THUMB_HEIGHT,
) -> None:
    """指定タイムスタンプの 1 フレームを width x height (letterbox) で JPG 保存。"""
    # -ss を -i の前に置く高速 seek。短すぎる動画でも耐える 0 クランプ。
    ts = max(0.0, float(timestamp))
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
    )
    args = [
        "-y",
        "-ss", f"{ts:.3f}",
        "-i", input_path,
        "-frames:v", "1",
        "-vf", vf,
        "-q:v", "3",
        "-an",
        str(output_path),
    ]
    run_ffmpeg(
        args,
        ffmpeg_path=ffmpeg_path(),
        label=f"thumb:{output_path.name}",
    )


def _build_poster_grid_args(
    *,
    thumbs: list[Path],
    output_path: Path,
    width: int = POSTER_WIDTH,
    height: int = POSTER_HEIGHT,
) -> list[str]:
    """5 枚の thumb から 3+2 グリッド合成 PNG を作る ffmpeg 引数を組む。

    レイアウト (W x H = 1280x720, 16:9):
      上段 3 枚: 各 W/3 x H/2 = ~426 x 360
      下段 2 枚: 各 W/2 x H/2 = 640 x 360 (中央 2 枚)
    元 thumb を pad で 16:9 セルに letterbox してから xstack で並べる。
    """
    if len(thumbs) != 5:
        raise ValueError(f"poster grid expects 5 thumbs, got {len(thumbs)}")

    # セル寸法（偶数化）
    top_w = (width // 3) & ~1
    top_h = (height // 2) & ~1
    bot_w = (width // 2) & ~1
    bot_h = (height // 2) & ~1

    # 余り（奇数ピクセル）は最後のセルで吸収するため、x 座標で計算
    top0_x, top1_x, top2_x = 0, top_w, top_w * 2
    bot0_x, bot1_x = 0, bot_w
    top_y = 0
    bot_y = top_h

    # filter_complex: 各入力を該当セル寸法に letterbox → xstack で 5 枚配置
    filters = []
    for i, (cw, ch) in enumerate([
        (top_w, top_h), (top_w, top_h), (width - top_w * 2, top_h),  # 上段3枚（最後で余り吸収）
        (bot_w, bot_h), (width - bot_w, bot_h),                      # 下段2枚
    ]):
        # 偶数化（PNG 出力でも safe）
        ch2 = ch & ~1 if ch > 1 else ch
        cw2 = cw & ~1 if cw > 1 else cw
        filters.append(
            f"[{i}:v]scale={cw2}:{ch2}:force_original_aspect_ratio=decrease,"
            f"pad={cw2}:{ch2}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[c{i}]"
        )

    # xstack で 5 入力を絶対座標で配置（layout=x_y|x_y|...）
    layout = "|".join([
        f"{top0_x}_{top_y}",
        f"{top1_x}_{top_y}",
        f"{top2_x}_{top_y}",
        f"{bot0_x}_{bot_y}",
        f"{bot1_x}_{bot_y}",
    ])
    stack = (
        f"[c0][c1][c2][c3][c4]xstack=inputs=5:layout={layout}:fill=black[out]"
    )
    filter_complex = ";".join(filters + [stack])

    args = ["-y"]
    for t in thumbs:
        args.extend(["-i", str(t)])
    args.extend([
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-frames:v", "1",
        "-pix_fmt", "rgb24",
        str(output_path),
    ])
    return args


def _build_poster(thumbs: list[Path], output_path: Path) -> None:
    args = _build_poster_grid_args(thumbs=thumbs, output_path=output_path)
    run_ffmpeg(args, ffmpeg_path=ffmpeg_path(), label=f"poster:{output_path.name}")


def generate_thumbnails(
    *,
    input_path: str,
    output_dir: str,
    duration_seconds: Optional[float] = None,
) -> ThumbResult:
    """5 枚の % サムネ + 合成 poster.png を生成する。

    output_dir 配下に以下を出力:
      thumb_05.jpg, thumb_30.jpg, thumb_50.jpg, thumb_60.jpg, thumb_80.jpg, poster.png
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    duration = (
        float(duration_seconds)
        if duration_seconds and duration_seconds > 0
        else probe_duration_seconds(input_path)
    )
    if duration <= 0:
        raise RuntimeError(f"could not determine duration: {input_path}")

    # Google Drive FUSE 上 (Colab の /content/drive 等) では、ある ffmpeg が
    # 書いた thumb_*.jpg が直後に別 ffmpeg(poster 合成) から見えず
    # `No such file or directory` で失敗することがある (書込→即読込の
    # 反映遅延)。サムネ抽出と poster 合成はすべてローカル一時ディレクトリ
    # で完結させ、最後に成果物だけを出力先へ move する。
    with tempfile.TemporaryDirectory(prefix="hls-thumbs-") as tmpdir:
        tmp = Path(tmpdir)
        tmp_thumbs: list[Path] = []
        for pct in THUMB_PERCENTS:
            ts = duration * (pct / 100.0)
            # 動画末尾を超えないようマージン (50ms)
            ts = min(ts, max(0.0, duration - 0.05))
            tmp_path = tmp / thumb_filename(pct)
            _extract_one_thumb(
                input_path=input_path, timestamp=ts, output_path=tmp_path
            )
            tmp_thumbs.append(tmp_path)

        tmp_poster = tmp / "poster.png"
        _build_poster(tmp_thumbs, tmp_poster)

        # 成果物を出力先へ移動 (ローカル→Drive の単純コピーなので競合しない)
        thumb_paths: list[Path] = []
        for pct, tp in zip(THUMB_PERCENTS, tmp_thumbs):
            dst = out / thumb_filename(pct)
            shutil.move(str(tp), str(dst))
            thumb_paths.append(dst)
        poster_path = out / "poster.png"
        shutil.move(str(tmp_poster), str(poster_path))

    logger.info(
        "thumbnails: %d frames + poster generated for %s (duration=%.1fs)",
        len(thumb_paths), input_path, duration,
    )
    return ThumbResult(
        poster_path=poster_path,
        thumb_paths=thumb_paths,
        duration=duration,
    )
