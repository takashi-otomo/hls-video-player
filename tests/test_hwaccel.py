"""NVENC 検出とバックエンド解決のテスト。

subprocess.check_output をモックして CPU/GPU 分岐を検証。
"""

import pytest

from hls_video import hwaccel


@pytest.fixture(autouse=True)
def _clear_cache():
    hwaccel.detect_nvenc.cache_clear()
    yield
    hwaccel.detect_nvenc.cache_clear()


def _encoders_output(with_nvenc: bool) -> bytes:
    base = b"V.....  libx264              H.264\n"
    if with_nvenc:
        base += b"V....D  h264_nvenc          NVIDIA NVENC H.264\n"
    return base


class TestDetectNvenc:
    def test_returns_true_when_encoder_listed(self, monkeypatch):
        def fake_check(*_a, **_kw):
            return _encoders_output(with_nvenc=True)
        monkeypatch.setattr(hwaccel.subprocess, "check_output", fake_check)
        assert hwaccel.detect_nvenc("ffmpeg") is True

    def test_returns_false_when_not_listed(self, monkeypatch):
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
