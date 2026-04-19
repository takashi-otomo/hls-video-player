"""hls_converter のコマンド組立テスト。

NVENC / CPU の両バックエンドと filter_complex split を検証。
"""

import pytest

from hls_video.hls_converter import DEFAULT_VARIANTS, build_ffmpeg_args


def _find_all(args, key):
    return [i for i, a in enumerate(args) if a == key]


class TestBuildFfmpegArgsCPU:
    def _args(self, **overrides):
        kw = dict(
            input_path="/tmp/in.mp4",
            output_dir="/media/hls/abc",
            variants=DEFAULT_VARIANTS,
            segment_seconds=4,
            gop=48,
            backend="cpu",
            preset="ultrafast",
            threads=0,
            nvenc_preset="p4",
        )
        kw.update(overrides)
        return build_ffmpeg_args(**kw)

    def test_uses_filter_complex_split_for_all_variants(self):
        args = self._args()
        fc_idx = args.index("-filter_complex")
        filter_complex = args[fc_idx + 1]
        # split=4 が含まれ、4 つのラベル [vo0]..[vo3] が scale 出力として定義される
        assert "split=4" in filter_complex
        for i in range(4):
            assert f"[vo{i}]" in filter_complex
        # input は 1 回だけ
        assert len(_find_all(args, "-i")) == 1

    def test_uses_libx264_for_cpu_backend(self):
        args = self._args()
        # 4 variants 分の -c:v h264 が出現
        cv = _find_all(args, "-c:v")
        assert len(cv) == 4
        for i in cv:
            assert args[i + 1] == "h264"

    def test_preset_and_threads_propagate(self):
        args = self._args(preset="veryfast", threads=4)
        presets = [args[i + 1] for i in _find_all(args, "-preset")]
        threads = [args[i + 1] for i in _find_all(args, "-threads")]
        assert presets == ["veryfast"] * 4
        assert threads == ["4"] * 4

    def test_pix_fmt_yuv420p_forced_per_variant(self):
        args = self._args()
        pix = [args[i + 1] for i in _find_all(args, "-pix_fmt")]
        assert pix == ["yuv420p"] * 4

    def test_sc_threshold_zero(self):
        args = self._args()
        sc = [args[i + 1] for i in _find_all(args, "-sc_threshold")]
        assert sc == ["0"] * 4

    def test_gop_size_propagates(self):
        args = self._args(gop=96)
        g = [args[i + 1] for i in _find_all(args, "-g")]
        km = [args[i + 1] for i in _find_all(args, "-keyint_min")]
        assert g == ["96"] * 4
        assert km == ["96"] * 4

    def test_hls_segment_and_playlist_paths(self):
        args = self._args()
        assert "/media/hls/abc/720p.m3u8" in args
        assert any(a.endswith("/media/hls/abc/720p_%03d.ts") for a in args)
        assert "/media/hls/abc/240p.m3u8" in args

    def test_map_uses_filter_complex_outputs(self):
        args = self._args()
        maps = [args[i + 1] for i in _find_all(args, "-map")]
        # 各 variant で [vo{i}] と 0:a:0? の 2 マッピング
        for i in range(4):
            assert f"[vo{i}]" in maps
        assert maps.count("0:a:0?") == 4


class TestBuildFfmpegArgsNVENC:
    def _args(self, **overrides):
        kw = dict(
            input_path="/tmp/in.mp4",
            output_dir="/media/hls/abc",
            variants=DEFAULT_VARIANTS,
            segment_seconds=4,
            gop=48,
            backend="nvenc",
            preset="ultrafast",   # CPU preset（NVENC 時は未使用）
            threads=0,
            nvenc_preset="p4",
        )
        kw.update(overrides)
        return build_ffmpeg_args(**kw)

    def test_uses_h264_nvenc_encoder(self):
        args = self._args()
        cv = _find_all(args, "-c:v")
        assert len(cv) == 4
        for i in cv:
            assert args[i + 1] == "h264_nvenc"

    def test_uses_vbr_cq_instead_of_crf(self):
        args = self._args()
        # -crf は使わない
        assert "-crf" not in args
        # -rc vbr が出る
        rc = [args[i + 1] for i in _find_all(args, "-rc")]
        assert rc == ["vbr"] * 4
        # -cq は各 variant の crf 値に対応
        cq = [args[i + 1] for i in _find_all(args, "-cq")]
        assert cq == [str(v["crf"]) for v in DEFAULT_VARIANTS]

    def test_nvenc_preset_applied(self):
        args = self._args(nvenc_preset="p1")
        presets = [args[i + 1] for i in _find_all(args, "-preset")]
        assert presets == ["p1"] * 4

    def test_no_threads_flag_on_nvenc(self):
        # NVENC は GPU 任せなので -threads は付けない
        args = self._args()
        assert "-threads" not in args

    def test_still_uses_filter_complex_split(self):
        args = self._args()
        fc = args[args.index("-filter_complex") + 1]
        assert "split=4" in fc


class TestPortraitScaling:
    """縦動画向けに scale 式の w/h が入れ替わることを検証。

    横動画で variant.height=240 を適用すると 135x240 (NVENC 最小解像度違反) に
    なるバグを防ぐための orientation-aware スケーリング。
    """

    def test_landscape_scales_height(self):
        # portrait=False: 従来通り h=short_edge
        args = build_ffmpeg_args(
            input_path="/tmp/in.mp4", output_dir="/out",
            variants=[DEFAULT_VARIANTS[3]],  # 240p
            segment_seconds=4, gop=48, backend="cpu",
            preset="ultrafast", threads=0, nvenc_preset="p4",
            portrait=False,
        )
        fc = args[args.index("-filter_complex") + 1]
        assert "scale=w=-2:h=240" in fc

    def test_portrait_scales_width(self):
        # portrait=True: w=short_edge にすべき
        args = build_ffmpeg_args(
            input_path="/tmp/in.mp4", output_dir="/out",
            variants=[DEFAULT_VARIANTS[3]],  # 240p
            segment_seconds=4, gop=48, backend="cpu",
            preset="ultrafast", threads=0, nvenc_preset="p4",
            portrait=True,
        )
        fc = args[args.index("-filter_complex") + 1]
        assert "scale=w=240:h=-2" in fc

    def test_portrait_applies_to_all_variants(self):
        args = build_ffmpeg_args(
            input_path="/tmp/in.mp4", output_dir="/out",
            variants=DEFAULT_VARIANTS,
            segment_seconds=4, gop=48, backend="nvenc",
            preset="ultrafast", threads=0, nvenc_preset="p4",
            portrait=True,
        )
        fc = args[args.index("-filter_complex") + 1]
        for v in DEFAULT_VARIANTS:
            assert f"scale=w={v['height']}:h=-2" in fc


class TestVariantSubset:
    def test_two_variants_split_two(self):
        two = [DEFAULT_VARIANTS[0], DEFAULT_VARIANTS[2]]  # 720p + 360p
        args = build_ffmpeg_args(
            input_path="/tmp/in.mp4", output_dir="/out",
            variants=two, segment_seconds=4, gop=48,
            backend="cpu", preset="ultrafast", threads=0, nvenc_preset="p4",
        )
        fc = args[args.index("-filter_complex") + 1]
        assert "split=2" in fc
        assert "[vo0]" in fc
        assert "[vo1]" in fc
        assert "[vo2]" not in fc
