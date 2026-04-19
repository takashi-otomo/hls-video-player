"""NVENC 検出とバックエンド解決のテスト。

subprocess.check_output をモックして CPU/GPU 分岐を検証。
"""

import pytest

from hls_video import hwaccel


@pytest.fixture(autouse=True)
def _clear_cache():
    hwaccel.detect_nvenc.cache_clear()
    hwaccel._list_decoders.cache_clear()
    hwaccel.detect_cuda_runtime.cache_clear()
    yield
    hwaccel.detect_nvenc.cache_clear()
    hwaccel._list_decoders.cache_clear()
    hwaccel.detect_cuda_runtime.cache_clear()


@pytest.fixture
def cuda_runtime_ok(monkeypatch):
    """CUDA runtime 可用性をテスト用に True 固定。check_output モックと干渉しない。"""
    hwaccel.detect_cuda_runtime.cache_clear()
    # lru_cache を剥いだシンプル関数に差し替える（cache_clear を呼ばれても壊れないよう保護）
    replacement = lambda: True  # noqa: E731
    replacement.cache_clear = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setattr(hwaccel, "detect_cuda_runtime", replacement)


def _encoders_output(with_nvenc: bool) -> bytes:
    base = b"V.....  libx264              H.264\n"
    if with_nvenc:
        base += b"V....D  h264_nvenc          NVIDIA NVENC H.264\n"
    return base


class TestDetectNvenc:
    def test_returns_true_when_encoder_listed_and_runtime_available(self, monkeypatch, cuda_runtime_ok):
        def fake_check(*_a, **_kw):
            return _encoders_output(with_nvenc=True)
        monkeypatch.setattr(hwaccel.subprocess, "check_output", fake_check)
        assert hwaccel.detect_nvenc("ffmpeg") is True

    def test_returns_false_when_cuda_runtime_missing(self, monkeypatch):
        """h264_nvenc がビルドにあっても CUDA runtime 無ければ False。"""
        monkeypatch.setattr(
            hwaccel.subprocess, "check_output",
            lambda *_a, **_kw: _encoders_output(with_nvenc=True),
        )
        replacement = lambda: False  # noqa: E731
        replacement.cache_clear = lambda: None  # type: ignore[attr-defined]
        monkeypatch.setattr(hwaccel, "detect_cuda_runtime", replacement)
        assert hwaccel.detect_nvenc("ffmpeg") is False

    def test_returns_false_when_not_listed(self, monkeypatch, cuda_runtime_ok):
        monkeypatch.setattr(
            hwaccel.subprocess, "check_output",
            lambda *_a, **_kw: _encoders_output(with_nvenc=False),
        )
        assert hwaccel.detect_nvenc("ffmpeg") is False

    def test_returns_false_when_ffmpeg_missing(self, monkeypatch):
        def boom(*_a, **_kw):
            raise FileNotFoundError("no ffmpeg")
        monkeypatch.setattr(hwaccel.subprocess, "check_output", boom)
        assert hwaccel.detect_nvenc("/nope/ffmpeg") is False


class TestDetectCudaRuntime:
    def test_true_when_nvidia_smi_succeeds(self, monkeypatch):
        # subprocess.check_output をモックすれば nvidia-smi -L 呼び出しがそのまま通る
        monkeypatch.setattr(
            hwaccel.subprocess, "check_output",
            lambda *_a, **_kw: b"GPU 0: Tesla T4\n",
        )
        assert hwaccel.detect_cuda_runtime() is True

    def test_false_when_nvidia_smi_missing(self, monkeypatch):
        def boom(*_a, **_kw):
            raise FileNotFoundError
        monkeypatch.setattr(hwaccel.subprocess, "check_output", boom)
        assert hwaccel.detect_cuda_runtime() is False

    def test_false_when_nvidia_smi_nonzero(self, monkeypatch):
        def boom(*_a, **_kw):
            raise hwaccel.subprocess.CalledProcessError(1, "nvidia-smi")
        monkeypatch.setattr(hwaccel.subprocess, "check_output", boom)
        assert hwaccel.detect_cuda_runtime() is False


class TestResolveHwaccel:
    def test_cpu_forces_cpu(self, monkeypatch):
        # detect が True を返しても cpu 指定が勝つ
        monkeypatch.setattr(hwaccel, "detect_nvenc", lambda _p="ffmpeg": True)
        assert hwaccel.resolve_hwaccel("cpu") == "cpu"

    def test_nvenc_forces_nvenc_even_without_detection(self, monkeypatch):
        monkeypatch.setattr(hwaccel, "detect_nvenc", lambda _p="ffmpeg": False)
        assert hwaccel.resolve_hwaccel("nvenc") == "nvenc"

    def test_auto_picks_nvenc_when_available(self, monkeypatch):
        monkeypatch.setattr(hwaccel, "detect_nvenc", lambda _p="ffmpeg": True)
        assert hwaccel.resolve_hwaccel("auto") == "nvenc"

    def test_auto_falls_back_to_cpu(self, monkeypatch):
        monkeypatch.setattr(hwaccel, "detect_nvenc", lambda _p="ffmpeg": False)
        assert hwaccel.resolve_hwaccel("auto") == "cpu"

    def test_empty_or_none_treated_as_auto(self, monkeypatch):
        monkeypatch.setattr(hwaccel, "detect_nvenc", lambda _p="ffmpeg": False)
        assert hwaccel.resolve_hwaccel("") == "cpu"
        assert hwaccel.resolve_hwaccel(None) == "cpu"  # type: ignore[arg-type]


def _decoders_output(codecs: list[str]) -> bytes:
    base = b"V..... mpeg4                MPEG-4 part 2\n"
    for c in codecs:
        base += f"V..... {c}             (cuvid decoder)\n".encode()
    return base


class TestDetectCuvid:
    def test_returns_decoder_when_listed(self, monkeypatch, cuda_runtime_ok):
        monkeypatch.setattr(
            hwaccel.subprocess, "check_output",
            lambda *_a, **_kw: _decoders_output(["h264_cuvid", "hevc_cuvid"]),
        )
        assert hwaccel.detect_cuvid("h264") == "h264_cuvid"
        assert hwaccel.detect_cuvid("hevc") == "hevc_cuvid"
        # h265 はエイリアス扱いで hevc_cuvid にマップされる
        assert hwaccel.detect_cuvid("h265") == "hevc_cuvid"

    def test_returns_none_when_codec_unknown(self, monkeypatch, cuda_runtime_ok):
        monkeypatch.setattr(
            hwaccel.subprocess, "check_output",
            lambda *_a, **_kw: _decoders_output(["h264_cuvid"]),
        )
        # 未サポート codec
        assert hwaccel.detect_cuvid("prores") is None

    def test_returns_none_when_not_in_decoders(self, monkeypatch, cuda_runtime_ok):
        # h264 はマップにあるが ffmpeg ビルドに h264_cuvid が入っていない場合
        monkeypatch.setattr(
            hwaccel.subprocess, "check_output",
            lambda *_a, **_kw: _decoders_output([]),
        )
        assert hwaccel.detect_cuvid("h264") is None

    def test_returns_none_when_codec_empty(self):
        assert hwaccel.detect_cuvid("") is None

    def test_returns_none_when_ffmpeg_missing(self, monkeypatch, cuda_runtime_ok):
        def boom(*_a, **_kw):
            raise FileNotFoundError
        monkeypatch.setattr(hwaccel.subprocess, "check_output", boom)
        assert hwaccel.detect_cuvid("h264", "/nope/ffmpeg") is None

    def test_returns_none_when_cuda_runtime_missing(self, monkeypatch):
        """h264_cuvid が decoders にあっても libcuda ロード不可なら None。"""
        monkeypatch.setattr(
            hwaccel.subprocess, "check_output",
            lambda *_a, **_kw: _decoders_output(["h264_cuvid"]),
        )
        replacement = lambda: False  # noqa: E731
        replacement.cache_clear = lambda: None  # type: ignore[attr-defined]
        monkeypatch.setattr(hwaccel, "detect_cuda_runtime", replacement)
        assert hwaccel.detect_cuvid("h264") is None


class TestResolveCuvid:
    def test_off_returns_none(self, monkeypatch):
        monkeypatch.setattr(hwaccel, "detect_cuvid", lambda _c, _p="ffmpeg": "h264_cuvid")
        assert hwaccel.resolve_cuvid("off", "h264") is None

    def test_auto_returns_detected_decoder(self, monkeypatch):
        monkeypatch.setattr(hwaccel, "detect_cuvid", lambda _c, _p="ffmpeg": "h264_cuvid")
        assert hwaccel.resolve_cuvid("auto", "h264") == "h264_cuvid"

    def test_auto_returns_none_when_no_decoder(self, monkeypatch):
        monkeypatch.setattr(hwaccel, "detect_cuvid", lambda _c, _p="ffmpeg": None)
        assert hwaccel.resolve_cuvid("auto", "prores") is None

    def test_on_falls_back_when_no_decoder(self, monkeypatch):
        """on 指定でも検出できなければ None を返す（警告ログのみ）"""
        monkeypatch.setattr(hwaccel, "detect_cuvid", lambda _c, _p="ffmpeg": None)
        assert hwaccel.resolve_cuvid("on", "prores") is None

    def test_empty_mode_treated_as_auto(self, monkeypatch):
        monkeypatch.setattr(hwaccel, "detect_cuvid", lambda _c, _p="ffmpeg": "h264_cuvid")
        assert hwaccel.resolve_cuvid("", "h264") == "h264_cuvid"
