"""hls_converter のコマンド組立テスト。

NVENC / CPU の両バックエンドと filter_complex split を検証。
"""

import pytest

from hls_video.hls_converter import (
    DEFAULT_VARIANTS,
    _is_cuda_runtime_error,
    build_ffmpeg_args,
    convert_mp4_to_hls,
)


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

    def test_tune_flag_propagates_to_all_variants(self):
        args = self._args(x264_tune="zerolatency")
        tunes = [args[i + 1] for i in _find_all(args, "-tune")]
        assert tunes == ["zerolatency"] * 4

    def test_no_tune_flag_when_none(self):
        args = self._args(x264_tune=None)
        assert "-tune" not in args

    def test_audio_copy_replaces_aac_encoding(self):
        args = self._args(audio_copy=True)
        # 各 variant で -c:a copy が出る (4 variant)
        ca = [args[i + 1] for i in _find_all(args, "-c:a")]
        assert ca == ["copy"] * 4
        # -b:a (audio bitrate) は出ない
        assert "-b:a" not in args

    def test_audio_encoded_by_default(self):
        args = self._args()
        ca = [args[i + 1] for i in _find_all(args, "-c:a")]
        assert ca == ["aac"] * 4
        # -b:a が各 variant に付く
        ba = [args[i + 1] for i in _find_all(args, "-b:a")]
        assert len(ba) == 4


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
        # CUVID 未使用時は c:v が4個（各 variant の encoder 指定のみ）
        assert len(cv) == 4
        for i in cv:
            assert args[i + 1] == "h264_nvenc"

    def test_uses_vbr_cq_instead_of_crf(self):
        args = self._args()
        assert "-crf" not in args
        rc = [args[i + 1] for i in _find_all(args, "-rc")]
        assert rc == ["vbr"] * 4
        cq = [args[i + 1] for i in _find_all(args, "-cq")]
        assert cq == [str(v["crf"]) for v in DEFAULT_VARIANTS]

    def test_nvenc_preset_applied(self):
        args = self._args(nvenc_preset="p1")
        presets = [args[i + 1] for i in _find_all(args, "-preset")]
        assert presets == ["p1"] * 4

    def test_no_threads_flag_on_nvenc(self):
        args = self._args()
        assert "-threads" not in args

    def test_still_uses_filter_complex_split(self):
        args = self._args()
        fc = args[args.index("-filter_complex") + 1]
        assert "split=4" in fc

    def test_default_bframes_absent(self):
        """bframes 引数デフォルトは None → `-bf` を付けない (NVENC デフォルト任せ)。"""
        args = self._args()
        assert "-bf" not in args

    def test_bframes_none_omits_flag(self):
        args = self._args(bframes=None)
        assert "-bf" not in args

    def test_bframes_zero_propagates(self):
        args = self._args(bframes=0)
        bf = [args[i + 1] for i in _find_all(args, "-bf")]
        assert bf == ["0"] * 4

    def test_bframes_positive_propagates_to_all_variants(self):
        args = self._args(bframes=3)
        bf = [args[i + 1] for i in _find_all(args, "-bf")]
        assert bf == ["3"] * 4


class TestBuildFfmpegArgsNVENCWithCuvid:
    """CUVID (GPU decode) + NVENC (GPU encode) の組み合わせ。"""

    def _args(self, **overrides):
        kw = dict(
            input_path="/tmp/in.mp4",
            output_dir="/out",
            variants=DEFAULT_VARIANTS,
            segment_seconds=4,
            gop=48,
            backend="nvenc",
            preset="ultrafast",
            threads=0,
            nvenc_preset="p4",
            cuvid_decoder="h264_cuvid",
        )
        kw.update(overrides)
        return build_ffmpeg_args(**kw)

    def test_scale_cuda_has_format_yuv420p(self):
        """scale_cuda に :format=yuv420p が必ず付く (NVENC negotiation 失敗対策)。"""
        args = self._args()
        fc = args[args.index("-filter_complex") + 1]
        # 各 variant の scale_cuda 行に format=yuv420p が入っている
        for v in DEFAULT_VARIANTS:
            assert f"format=yuv420p" in fc
        # scale_cuda を使う数だけ format=yuv420p が出る
        assert fc.count("format=yuv420p") == len(DEFAULT_VARIANTS)

    def test_cpu_scale_has_no_format_suffix(self):
        """CPU scale には format=yuv420p を付けない (不要 + 下位互換)。"""
        args = build_ffmpeg_args(
            input_path="/tmp/in.mp4", output_dir="/out",
            variants=DEFAULT_VARIANTS, segment_seconds=4, gop=48,
            backend="cpu", preset="ultrafast", threads=0, nvenc_preset="p4",
        )
        fc = args[args.index("-filter_complex") + 1]
        assert "format=yuv420p" not in fc

    def test_interlaced_adds_deint_option(self):
        """CUVID decode + interlaced → -deint 2 が decoder オプションに付く。"""
        args = self._args(interlaced=True)
        # -deint が -i より前にある (decoder option)
        i_idx = args.index("-i")
        pre_input = args[:i_idx]
        deint_idx = pre_input.index("-deint")
        assert pre_input[deint_idx + 1] == "2"
        # scale_cuda chain には yadif が入らない
        fc = args[args.index("-filter_complex") + 1]
        assert "yadif" not in fc

    def test_progressive_has_no_deint(self):
        args = self._args(interlaced=False)
        assert "-deint" not in args

    def test_hwaccel_cuda_prepended_before_input(self):
        args = self._args()
        # -hwaccel cuda / -hwaccel_output_format cuda が -i より前に出現
        i_idx = args.index("-i")
        hwaccel_idx = args.index("-hwaccel")
        fmt_idx = args.index("-hwaccel_output_format")
        assert hwaccel_idx < i_idx
        assert fmt_idx < i_idx
        assert args[hwaccel_idx + 1] == "cuda"
        assert args[fmt_idx + 1] == "cuda"

    def test_input_decoder_set_to_cuvid(self):
        args = self._args(cuvid_decoder="hevc_cuvid")
        # -i の前に現れる -c:v が CUVID decoder 指定
        i_idx = args.index("-i")
        # その前の範囲で -c:v を探す
        pre_input = args[:i_idx]
        cv_idx = pre_input.index("-c:v")
        assert pre_input[cv_idx + 1] == "hevc_cuvid"

    def test_filter_complex_uses_scale_cuda(self):
        args = self._args()
        fc = args[args.index("-filter_complex") + 1]
        assert "scale_cuda=" in fc
        # ただの scale= は出てこない（scale_cuda は含むので word boundary で）
        # "scale=" がどこかにあっても scale_cuda 以外として出てはいけない
        # → 安全側: 少なくとも 4 回 scale_cuda が出る
        assert fc.count("scale_cuda=") == 4

    def test_cuvid_off_when_not_specified(self):
        args = self._args(cuvid_decoder=None)
        # CUVID なし → hwaccel を追加しない
        assert "-hwaccel" not in args
        fc = args[args.index("-filter_complex") + 1]
        assert "scale_cuda" not in fc

    def test_cuvid_ignored_on_cpu_backend(self):
        """CPU backend のときは cuvid_decoder が指定されても無視する。"""
        args = self._args(backend="cpu", cuvid_decoder="h264_cuvid")
        assert "-hwaccel" not in args
        fc = args[args.index("-filter_complex") + 1]
        assert "scale_cuda" not in fc
        assert "scale=" in fc


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


class TestCudaRuntimeErrorDetection:
    def test_matches_cannot_load_libcuda(self):
        err = "ffmpeg ... Cannot load libcuda.so.1 ... Conversion failed!"
        assert _is_cuda_runtime_error(err) is True

    def test_matches_device_creation_failed(self):
        assert _is_cuda_runtime_error("Device creation failed: -1313558101.") is True

    def test_matches_device_setup_failed(self):
        assert _is_cuda_runtime_error("Device setup failed for decoder") is True

    def test_matches_scale_cuda_format_negotiation(self):
        """scale_cuda:format 未指定の典型エラーを CUDA エラーとして扱う。"""
        err = ("Impossible to convert between the formats supported by the "
               "filter 'Parsed_scale_cuda_4' and the filter 'auto_scaler_0'")
        assert _is_cuda_runtime_error(err) is True

    def test_matches_filter_reinit(self):
        assert _is_cuda_runtime_error("Error reinitializing filters!") is True

    def test_matches_cuda_oom(self):
        assert _is_cuda_runtime_error("CUDA_ERROR_OUT_OF_MEMORY") is True
        assert _is_cuda_runtime_error("Failed to allocate CUDA frame") is True

    def test_does_not_match_unrelated_error(self):
        assert _is_cuda_runtime_error("Invalid argument: -z") is False
        assert _is_cuda_runtime_error("No such file or directory") is False


class TestConvertMp4ToHlsFallback:
    """NVENC/CUVID が runtime で落ちたとき CPU で再実行する。"""

    def test_falls_back_to_cpu_on_cuda_runtime_error(self, tmp_path, monkeypatch):
        import hls_video.hls_converter as mod

        # nvenc + cuvid 経路に確定させる
        monkeypatch.setattr(mod, "resolve_hwaccel", lambda *_a, **_kw: "nvenc")
        monkeypatch.setattr(mod, "resolve_cuvid", lambda *_a, **_kw: "h264_cuvid")

        calls: list[list[str]] = []

        def fake_run_ffmpeg(args, on_progress=None, label=None):
            calls.append(list(args))
            if len(calls) == 1:
                # 1回目 (NVENC+CUVID) で CUDA エラー
                raise RuntimeError(
                    "ffmpeg exited with code 1\n"
                    "... Cannot load libcuda.so.1 ...\n"
                    "Device setup failed for decoder on input stream #0:0"
                )
            # 2回目 (CPU) は成功

        monkeypatch.setattr(mod, "run_ffmpeg", fake_run_ffmpeg)

        out = tmp_path / "hls" / "vid"
        res = convert_mp4_to_hls(
            input_path="/tmp/in.mp4", output_dir=str(out),
            input_codec="h264", duration_seconds=10.0,
        )
        assert len(calls) == 2, "CUDA エラー後に CPU で再試行するはず"
        # 1 回目は nvenc + cuvid
        first = calls[0]
        assert "h264_nvenc" in first
        assert "h264_cuvid" in first
        # 2 回目は CPU（libx264 encoder=h264, hwaccel なし）
        second = calls[1]
        assert "h264_nvenc" not in second
        assert "h264_cuvid" not in second
        assert "-hwaccel" not in second
        assert res["backend"] == "cpu"

    def test_does_not_retry_on_non_cuda_error(self, tmp_path, monkeypatch):
        """CUDA 以外のエラーでは再試行しない（元の例外を再 raise）。"""
        import hls_video.hls_converter as mod
        monkeypatch.setattr(mod, "resolve_hwaccel", lambda *_a, **_kw: "nvenc")
        monkeypatch.setattr(mod, "resolve_cuvid", lambda *_a, **_kw: None)

        def boom(args, on_progress=None, label=None):
            raise RuntimeError("Invalid argument -z")

        monkeypatch.setattr(mod, "run_ffmpeg", boom)

        out = tmp_path / "hls" / "vid2"
        with pytest.raises(RuntimeError):
            convert_mp4_to_hls(
                input_path="/tmp/in.mp4", output_dir=str(out),
                input_codec="h264", duration_seconds=10.0,
            )


class TestInterlacedCpuYadif:
    """CPU decode + interlaced → yadif が filter_complex に挿入される。"""

    def test_cpu_interlaced_adds_yadif_before_split(self):
        args = build_ffmpeg_args(
            input_path="/tmp/in.mp4", output_dir="/out",
            variants=DEFAULT_VARIANTS, segment_seconds=4, gop=48,
            backend="cpu", preset="ultrafast", threads=0, nvenc_preset="p4",
            interlaced=True,
        )
        fc = args[args.index("-filter_complex") + 1]
        # yadif=mode=1, が split の前に入る
        assert fc.startswith("[0:v]yadif=mode=1,split=")

    def test_cpu_progressive_no_yadif(self):
        args = build_ffmpeg_args(
            input_path="/tmp/in.mp4", output_dir="/out",
            variants=DEFAULT_VARIANTS, segment_seconds=4, gop=48,
            backend="cpu", preset="ultrafast", threads=0, nvenc_preset="p4",
            interlaced=False,
        )
        fc = args[args.index("-filter_complex") + 1]
        assert "yadif" not in fc


class TestVariantSubsetByInputSize:
    """入力より大きい variant はスキップ (拡大防止 + NVENC 最小対策)。"""

    def test_skips_variants_larger_than_input(self, tmp_path, monkeypatch):
        import hls_video.hls_converter as mod
        monkeypatch.setattr(mod, "resolve_hwaccel", lambda *_a, **_kw: "cpu")

        called: dict = {}

        def fake_run(args, on_progress=None, label=None):
            called["args"] = args

        monkeypatch.setattr(mod, "run_ffmpeg", fake_run)

        # 入力 720x1280 (縦動画、短辺720) → 720p までは OK、それ以上の variant は
        # ない (DEFAULT_VARIANTS max=720)。代わりに 480x854 (短辺480) で試す。
        mod.convert_mp4_to_hls(
            input_path="/tmp/in.mp4", output_dir=str(tmp_path / "hls"),
            input_width=480, input_height=854,
            input_codec="h264", duration_seconds=10.0,
        )
        fc = called["args"][called["args"].index("-filter_complex") + 1]
        # 入力短辺 480 以下のみ残る = 480p / 360p / 240p の 3 本
        assert "split=3" in fc

    def test_keeps_smallest_variant_when_all_too_large(self, tmp_path, monkeypatch):
        import hls_video.hls_converter as mod
        monkeypatch.setattr(mod, "resolve_hwaccel", lambda *_a, **_kw: "cpu")

        def fake_run(args, on_progress=None, label=None):
            pass

        monkeypatch.setattr(mod, "run_ffmpeg", fake_run)

        # 入力 100x100 → 全 variant が大きい。最小 (240p) 1 本だけ残る。
        res = mod.convert_mp4_to_hls(
            input_path="/tmp/in.mp4", output_dir=str(tmp_path / "hls"),
            input_width=100, input_height=100,
            input_codec="h264", duration_seconds=10.0,
        )
        assert res["variants"] == ["240p"]


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
