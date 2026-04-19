"""spriteCoordinates.test.js からの移植。座標計算と VTT フォーマット。"""

from hls_video.vtt_builder import (
    compute_sprite_coordinates,
    format_timestamp,
    generate_vtt_content,
)


class TestComputeSpriteCoordinates:
    TILE_W, TILE_H, COLUMNS = 160, 90, 10

    def test_index_zero(self):
        assert compute_sprite_coordinates(0, self.COLUMNS, self.TILE_W, self.TILE_H) == (0, 0)

    def test_advances_x_within_row(self):
        assert compute_sprite_coordinates(3, self.COLUMNS, self.TILE_W, self.TILE_H) == (480, 0)

    def test_wraps_to_next_row(self):
        assert compute_sprite_coordinates(10, self.COLUMNS, self.TILE_W, self.TILE_H) == (0, 90)

    def test_reference_index_12(self):
        # 設計書の例: C=10 / W=160 / H=90 / i=12 → (320, 90)
        assert compute_sprite_coordinates(12, self.COLUMNS, self.TILE_W, self.TILE_H) == (320, 90)


class TestFormatTimestamp:
    def test_zero(self):
        assert format_timestamp(0) == "00:00:00.000"

    def test_hour_boundary(self):
        assert format_timestamp(3600) == "01:00:00.000"

    def test_sub_second(self):
        assert format_timestamp(12.345) == "00:00:12.345"


class TestGenerateVttContent:
    DEFAULTS = dict(
        sprite_url="sprite.jpg",
        tile_width=160,
        tile_height=90,
        columns=10,
        interval_seconds=10,
    )

    def test_webvtt_header(self):
        out = generate_vtt_content(tile_count=1, **self.DEFAULTS)
        assert out.startswith("WEBVTT")

    def test_cue_ranges(self):
        out = generate_vtt_content(tile_count=3, **self.DEFAULTS)
        assert "00:00:00.000 --> 00:00:10.000" in out
        assert "00:00:10.000 --> 00:00:20.000" in out
        assert "00:00:20.000 --> 00:00:30.000" in out

    def test_xywh_fragment(self):
        out = generate_vtt_content(tile_count=2, **self.DEFAULTS)
        assert "sprite.jpg#xywh=0,0,160,90" in out
        assert "sprite.jpg#xywh=160,0,160,90" in out

    def test_hour_boundary_cue(self):
        out = generate_vtt_content(tile_count=361, **self.DEFAULTS)
        assert "01:00:00.000 --> 01:00:10.000" in out
