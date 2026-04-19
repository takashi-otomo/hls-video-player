"""スプライト画像の座標計算と WebVTT 出力。Node 側 utils/vttBuilder.js と等価。"""

from __future__ import annotations


def compute_sprite_coordinates(
    index: int, columns: int, tile_width: int, tile_height: int
) -> tuple[int, int]:
    x = (index % columns) * tile_width
    y = (index // columns) * tile_height
    return x, y


def format_timestamp(total_seconds: float) -> str:
    """`HH:MM:SS.mmm` 形式に整形。"""
    if total_seconds < 0:
        total_seconds = 0
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    millis = round((total_seconds - int(total_seconds)) * 1000)
    # 小数繰上げで 1000ms になったら秒に繰上げ
    if millis == 1000:
        millis = 0
        seconds += 1
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def generate_vtt_content(
    *,
    sprite_url: str,
    tile_count: int,
    tile_width: int,
    tile_height: int,
    columns: int,
    interval_seconds: int,
) -> str:
    lines = ["WEBVTT", ""]
    for i in range(tile_count):
        start = i * interval_seconds
        end = start + interval_seconds
        x, y = compute_sprite_coordinates(i, columns, tile_width, tile_height)
        lines.append(str(i + 1))
        lines.append(f"{format_timestamp(start)} --> {format_timestamp(end)}")
        lines.append(f"{sprite_url}#xywh={x},{y},{tile_width},{tile_height}")
        lines.append("")
    return "\n".join(lines)
