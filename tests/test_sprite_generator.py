"""sprite_generator のユニットテスト。

FFmpeg を呼ばないロジック部分（メタデータ算出、コマンド組立、VTT 生成）を検証。
実 FFmpeg 呼出の統合テストは test_integration.py で扱う。
"""

import json
from pathlib import Path

import pytest

from hls_video.sprite_generator import (
    compute_sprite_layout,
    build_sprite_args,
)


class TestComputeSpriteLayout:
    def test_single_sheet_for_short_video(self):
        layout = compute_sprite_layout(duration=60, interval=10, columns=10, rows=10)
        assert layout["tile_count"] == 6
        assert layout["sheet_count"] == 1

    def test_exact_fill_one_sheet(self):
        # 10×10 = 100 tile ぴったり
        layout = compute_sprite_layout(duration=1000, interval=10, columns=10, rows=10)
        assert layout["tile_count"] == 100
        assert layout["sheet_count"] == 1

    def test_overflow_goes_to_second_sheet(self):
        # 1001s / 10s = 101 tile → 2 sheet
        layout = compute_sprite_layout(duration=1010, interval=10, columns=10, rows=10)
        assert layout["tile_count"] == 101
        assert layout["sheet_count"] == 2

    def test_long_video_multi_sheet(self):
        # 2346s / 10s = 235 tile → 3 sheet（既知の実測例）
        layout = compute_sprite_layout(duration=2346, interval=10, columns=10, rows=10)
        assert layout["tile_count"] == 235
        assert layout["sheet_count"] == 3

    def test_minimum_one_tile(self):
        layout = compute_sprite_layout(duration=0.5, interval=10, columns=10, rows=10)
        assert layout["tile_count"] == 1


class TestBuildSpriteArgs:
    def test_single_sheet_output_path(self, tmp_path):
        args = build_sprite_args(
            input_path="in.mp4",
            output_dir=str(tmp_path),
            video_id="foo",
            interval=10,
            tile_width=160,
            tile_height=90,
            columns=10,
            rows=10,
            sheet_count=1,
            threads=2,
        )
        # 単一シートの場合は foo.jpg
        assert any(a.endswith("foo.jpg") for a in args)

    def test_multi_sheet_uses_pattern(self, tmp_path):
        args = build_sprite_args(
            input_path="in.mp4",
            output_dir=str(tmp_path),
            video_id="foo",
            interval=10,
            tile_width=160,
            tile_height=90,
            columns=10,
            rows=10,
            sheet_count=3,
            threads=2,
        )
        assert any("foo-%d.jpg" in a for a in args)
        # image2 形式明示
        assert "-f" in args and args[args.index("-f") + 1] == "image2"

    def test_threads_included(self, tmp_path):
        args = build_sprite_args(
            input_path="in.mp4",
            output_dir=str(tmp_path),
            video_id="foo",
            interval=10,
            tile_width=160,
            tile_height=90,
            columns=10,
            rows=10,
            sheet_count=1,
            threads=2,
        )
        idx = args.index("-threads")
        assert args[idx + 1] == "2"
