"""hlsConverter.js からの移植。コマンド組立と CPU 抑制（threads/preset）を検証。"""

import pytest

from hls_video.hls_converter import (
    DEFAULT_VARIANTS,
    build_variant_args,
)


class TestBuildVariantArgs:
    def test_includes_preset_and_threads(self):
        v = DEFAULT_VARIANTS[0]
        args = build_variant_args(v, out_dir="/tmp", segment_seconds=4, gop=48,
                                   preset="veryfast", threads=2)
        preset_idx = args.index("-preset")
        threads_idx = args.index("-threads")
        assert args[preset_idx + 1] == "veryfast"
        assert args[threads_idx + 1] == "2"

    def test_threads_can_be_one(self):
        v = DEFAULT_VARIANTS[0]
        args = build_variant_args(v, out_dir="/tmp", segment_seconds=4, gop=48,
                                   preset="ultrafast", threads=1)
        idx = args.index("-threads")
        assert args[idx + 1] == "1"

    def test_pix_fmt_yuv420p_forced(self):
        v = DEFAULT_VARIANTS[0]
        args = build_variant_args(v, out_dir="/tmp", segment_seconds=4, gop=48,
                                   preset="veryfast", threads=2)
        idx = args.index("-pix_fmt")
        assert args[idx + 1] == "yuv420p"

    def test_scenecut_disabled(self):
        v = DEFAULT_VARIANTS[0]
        args = build_variant_args(v, out_dir="/tmp", segment_seconds=4, gop=48,
                                   preset="veryfast", threads=2)
        idx = args.index("-sc_threshold")
        assert args[idx + 1] == "0"

    def test_gop_size_propagates(self):
        v = DEFAULT_VARIANTS[0]
        args = build_variant_args(v, out_dir="/tmp", segment_seconds=4, gop=48,
                                   preset="veryfast", threads=2)
        assert args[args.index("-g") + 1] == "48"
        assert args[args.index("-keyint_min") + 1] == "48"

    def test_hls_segment_filename_and_playlist_paths(self):
        v = DEFAULT_VARIANTS[0]
        args = build_variant_args(v, out_dir="/media/hls/abc", segment_seconds=4, gop=48,
                                   preset="veryfast", threads=2)
        assert "/media/hls/abc/720p.m3u8" in args
        assert any(a.endswith("/media/hls/abc/720p_%03d.ts") for a in args)
