"""master.m3u8（複数解像度のトップレベルプレイリスト）組立。"""

from __future__ import annotations

from typing import Iterable, TypedDict


class VariantSpec(TypedDict):
    bandwidth: int
    resolution: str  # "1280x720" 等
    playlist: str    # 相対パス "720p.m3u8"


def build_master_playlist(variants: Iterable[VariantSpec]) -> str:
    variants_list = list(variants)
    if not variants_list:
        raise ValueError("variants must be a non-empty list")

    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for v in variants_list:
        lines.append(
            f"#EXT-X-STREAM-INF:BANDWIDTH={v['bandwidth']},RESOLUTION={v['resolution']}"
        )
        lines.append(v["playlist"])
    return "\n".join(lines) + "\n"
