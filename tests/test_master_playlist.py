"""masterPlaylist.test.js からの移植。"""

import pytest

from hls_video.master_playlist import build_master_playlist


def test_emits_extm3u_header():
    out = build_master_playlist([
        {"bandwidth": 400000, "resolution": "426x240", "playlist": "240p.m3u8"},
    ])
    assert out.split("\n")[0] == "#EXTM3U"


def test_emits_one_stream_inf_per_variant():
    out = build_master_playlist([
        {"bandwidth": 3000000, "resolution": "1280x720", "playlist": "720p.m3u8"},
        {"bandwidth": 1500000, "resolution": "854x480", "playlist": "480p.m3u8"},
    ])
    assert out.count("#EXT-X-STREAM-INF") == 2
    assert "BANDWIDTH=3000000" in out
    assert "RESOLUTION=1280x720" in out
    assert "720p.m3u8" in out


def test_raises_when_variants_empty():
    with pytest.raises(ValueError):
        build_master_playlist([])


def test_ends_with_newline():
    out = build_master_playlist([
        {"bandwidth": 400000, "resolution": "426x240", "playlist": "240p.m3u8"},
    ])
    assert out.endswith("\n")
